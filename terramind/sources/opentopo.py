"""Earth SRTM GL1 via the OpenTopography Global DEM API, cached under data/raw/earth/."""

from __future__ import annotations

from pathlib import Path

import requests

from terramind.config import MissingInputError, Settings, Site

OPENTOPO_URL = "https://portal.opentopography.org/API/globaldem"
TIFF_MAGIC = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")


def srtm_cache_path(settings: Settings, site: Site) -> Path:
    """Cache file name encodes the center and window, so a moved center never reuses old data."""
    name = f"{site.id}_{site.lat:.4f}_{site.lon:.4f}_{settings.window_km:g}km_SRTMGL1.tif"
    return settings.raw_dir / "earth" / name


def _redact(text: str, secret: str | None) -> str:
    return text.replace(secret, "***") if secret else text


def fetch_srtm(
    bounds: tuple[float, float, float, float],
    dest: Path,
    api_key: str | None,
    session=None,
    timeout: float = 180.0,
    demtype: str = "SRTMGL1",
) -> Path:
    """Download a DEM (default SRTMGL1) for (west, south, east, north) to `dest`. Reuses `dest` if it exists."""
    if dest.exists():
        return dest
    if not api_key:
        raise MissingInputError(
            "OPENTOPO_API_KEY is not set. Put it in a .env file in the project root "
            "(copy .env.example), or place a GeoTIFF manually at:\n  " + str(dest)
        )
    west, south, east, north = bounds
    params = {
        "demtype": demtype,
        "south": f"{south:.6f}",
        "north": f"{north:.6f}",
        "west": f"{west:.6f}",
        "east": f"{east:.6f}",
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }
    http = session or requests
    try:
        resp = http.get(OPENTOPO_URL, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise MissingInputError(f"OpenTopography request failed: {_redact(str(exc), api_key)}") from None

    body = resp.content or b""
    if resp.status_code != 200 or not body.startswith(TIFF_MAGIC):
        text = body[:400].decode("utf-8", "replace").strip()
        raise MissingInputError(
            f"OpenTopography did not return a GeoTIFF (HTTP {resp.status_code}): {_redact(text, api_key)}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(body)
    tmp.replace(dest)
    return dest
