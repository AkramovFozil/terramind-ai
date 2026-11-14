"""NOAA ETOPO 2022 global relief (60 arc-second surface), used only to screen Earth.

The global search needs every land window on Earth. Reading Copernicus GLO-30
for the whole planet on demand is not practical, so the planet is screened once
on ETOPO 2022 60" (about 1.85 km; its land part is built mainly from Copernicus
GLO-30), and only the best windows are re-measured on Copernicus at 463 m.
(The 30" grid would screen more finely but is 1.6 GB; the NOAA server is slow.)

The file (about 480 MB) is downloaded once with parallel HTTP range requests,
resumable, into the data directory. It is never committed.
"""

from __future__ import annotations

import os
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from terramind.config import MissingInputError

ETOPO_URL = ("https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/60s/"
             "60s_surface_elev_netcdf/ETOPO_2022_v1_60s_N90W180_surface.nc")
ETOPO_SOURCE = "https://www.ncei.noaa.gov/products/etopo-global-relief-model"
ETOPO_NAME = "ETOPO_2022_v1_60s_N90W180_surface.nc"
ETOPO_PROVENANCE = {
    "source": "NOAA NCEI ETOPO 2022 Global Relief Model",
    "dataset": "ETOPO_2022_v1_60s_surface",
    "source_url": ETOPO_SOURCE,
    "url": ETOPO_URL,
    "doi": "10.25921/fd45-gt74",
    "native_resolution_arcsec": 60,
    "vertical_reference": "EGM2008; metres",
    "license": "Public domain (US Government work)",
    "use": "Global screening only. Final scores are always recomputed on Copernicus GLO-30 at 463 m.",
}
_PART = 4 * 1024 * 1024


def data_root(cache_dir=None) -> Path:
    """Folder for large downloaded data. TERRAMIND_DATA_DIR wins; C: is avoided on the dev PC."""
    if cache_dir is not None:
        root = Path(cache_dir)
    elif os.environ.get("TERRAMIND_DATA_DIR"):
        root = Path(os.environ["TERRAMIND_DATA_DIR"])
    else:
        task_data = Path("D:/CodexWork/terramind-ai/data")
        root = task_data if os.name == "nt" and task_data.is_dir() else Path.cwd() / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def etopo_path(cache_dir=None) -> Path:
    return data_root(cache_dir) / "global" / ETOPO_NAME


def _remote_size(url: str) -> int:
    # The THREDDS server omits Content-Length on HEAD; a one-byte range reply has the total.
    request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        total = (response.headers.get("Content-Range") or "").rpartition("/")[2]
        if not total.isdigit():
            raise IOError("server did not report the file size")
        return int(total)


def download_etopo(cache_dir=None, workers: int = 16, progress=print) -> Path:
    """Download the ETOPO 60" surface grid once. Resumable: finished parts are kept."""
    final = etopo_path(cache_dir)
    if final.exists():
        return final
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        size = _remote_size(ETOPO_URL)
    except Exception as exc:
        raise MissingInputError(f"Cannot reach NOAA ETOPO ({ETOPO_URL}): {exc}") from exc
    partial = final.with_suffix(".nc.partial")
    done_dir = final.parent / (final.name + ".parts")
    done_dir.mkdir(exist_ok=True)
    if not partial.exists() or partial.stat().st_size != size:
        with open(partial, "wb") as fh:
            fh.truncate(size)
    parts = [(start, min(start + _PART, size) - 1) for start in range(0, size, _PART)]
    lock = threading.Lock()
    finished = [sum((done_dir / f"{s}").exists() for s, _ in parts)]

    def fetch(part):
        start, end = part
        marker = done_dir / f"{start}"
        if marker.exists():
            return
        last = None
        for attempt in range(12):
            try:
                request = urllib.request.Request(ETOPO_URL, headers={"Range": f"bytes={start}-{end}"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    data = response.read()
                if len(data) != end - start + 1:
                    raise IOError(f"short read {len(data)} of {end - start + 1}")
                with lock:
                    with open(partial, "r+b") as fh:
                        fh.seek(start)
                        fh.write(data)
                    marker.touch()
                    finished[0] += 1
                    if finished[0] % 10 == 0 or finished[0] == len(parts):
                        progress(f"ETOPO download {finished[0]}/{len(parts)} parts")
                return
            except Exception as exc:  # retried; the last error is raised
                last = exc
                time.sleep(min(5 * (attempt + 1), 60))  # ride out short network outages
        raise MissingInputError(f"ETOPO part {start}-{end} failed: {last}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(fetch, parts))
    partial.replace(final)
    for marker in done_dir.iterdir():
        marker.unlink()
    done_dir.rmdir()
    return final
