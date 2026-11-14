"""Real, key-free DEM windows from USGS MOLA and the public AWS Copernicus DSM.

This acquisition path is intentionally separate from the existing SRTM API
source. Copernicus is a DSM, and provenance never calls it SRTM. Remote GeoTIFFs
are read with HTTP ranges; missing data raises an error rather than generating
terrain. Cached rasters contain real elevations in metres on a local AEQD grid.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import Affine
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window, from_bounds as window_from_bounds

from terramind.config import MissingInputError
from terramind.crs import check_body_crs
from terramind.raster import check_quality, write_geotiff
from terramind.roi import geographic_bounds, make_grid

MOLA_URL = "https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif"
MOLA_SOURCE = "https://astrogeology.usgs.gov/search/map/mars_mgs_mola_dem_463m"
COPERNICUS_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
COPERNICUS_SOURCE = "https://registry.opendata.aws/copernicus-dem/"
# Copernicus COGs carry internal overviews at 2x, 4x, 8x, and each level is the exact
# block mean of the 30 m data (verified: level 2 == 2x2 mean of level 1, difference 0.0).
# Level 2 (8x, about 240 m) therefore averages into the 463 m analysis grid with the
# same result as averaging the 30 m samples, while reading ~64x fewer bytes. That is
# what makes a global search with 12 refined places take seconds instead of minutes.
EARTH_OVERVIEW_LEVEL = 2
_CACHE_VERSION = 3
_LOCK = threading.RLock()
_UA = "terramind-dem-reader/0.3"  # the USGS server refuses the default Python-urllib agent
_KEY_LOCKS: dict[str, threading.RLock] = {}


def _key_lock(key: str) -> threading.RLock:
    """One lock per cached window: the same window is fetched once, different windows in parallel."""
    with _LOCK:
        return _KEY_LOCKS.setdefault(key, threading.RLock())


def _validate(body, lat, lon, radius_km, grid_m):
    body = str(body).lower()
    if body not in ("earth", "mars"):
        raise ValueError("body must be 'earth' or 'mars'")
    lat, lon, radius_km, grid_m = map(float, (lat, lon, radius_km, grid_m))
    if not all(math.isfinite(x) for x in (lat, lon, radius_km, grid_m)):
        raise ValueError("Coordinates, radius and grid size must be finite")
    if not -85 <= lat <= 85 or not -180 <= lon <= 180:
        raise ValueError("Supported centres: latitude -85..85 and longitude -180..180")
    if not 0 < radius_km <= 100:
        raise ValueError("radius_km must be greater than zero and at most 100")
    if not 100 <= grid_m <= 2000:
        raise ValueError("grid_m must be between 100 and 2000 metres")
    return body, lat, lon, radius_km, grid_m


def _cache_root(cache_dir):
    if cache_dir is not None:
        root = Path(cache_dir)
    elif os.environ.get("TERRAMIND_DATA_DIR"):
        root = Path(os.environ["TERRAMIND_DATA_DIR"]) / "public_dem"
    else:
        # The desktop task has no free space on C:. Keep this available-drive
        # fallback local to Windows; deployed apps should set TERRAMIND_DATA_DIR.
        task_data = Path("D:/CodexWork/terramind-ai/data")
        root = task_data / "public_dem" if os.name == "nt" and task_data.is_dir() else Path.cwd() / "data" / "public_dem"
    root.mkdir(parents=True, exist_ok=True)
    return root


def copernicus_tile_url(south: int, west: int) -> str:
    """A GLO-30 tile is addressed by its southwest integer-degree corner."""
    northing = f"{'N' if south >= 0 else 'S'}{abs(south):02d}_00"
    easting = f"{'E' if west >= 0 else 'W'}{abs(west):03d}_00"
    name = f"Copernicus_DSM_COG_10_{northing}_{easting}_DEM"
    return f"{COPERNICUS_BASE}/{name}/{name}.tif"


def _earth_urls(bounds):
    west, south, east, north = bounds
    return [copernicus_tile_url(y, x)
            for y in range(math.floor(south), math.floor(north) + 1)
            for x in range(math.floor(west), math.floor(east) + 1)]


def _remote_env():
    return rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
        GDAL_HTTP_CONNECTTIMEOUT="20",
        GDAL_HTTP_TIMEOUT="90",
        GDAL_HTTP_MAX_RETRY="2",
        GDAL_HTTP_RETRY_DELAY="1",
        GDAL_HTTP_MULTIRANGE="YES",
        GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
        GDAL_CACHEMAX=64 * 1024 * 1024,
    )


def _read_strip_window(src, window) -> np.ndarray:
    """Read a window of an uncompressed, one-row-per-strip remote GeoTIFF with parallel byte ranges.

    The USGS MOLA mosaic is 46080 x 23040 int16 with one strip per row. GDAL fetches
    such windows row by row, one request after another (over a minute). Here the
    strip offsets come from GDAL's parsed header and each row's slice is a separate
    HTTP range request over 16 kept-alive connections. Anything unexpected falls back to GDAL.
    """
    import http.client
    import urllib.request
    from urllib.parse import urlsplit

    row0, col0 = int(window.row_off), int(window.col_off)
    nrows, ncols = int(window.height), int(window.width)
    dtype = np.dtype(src.dtypes[0])
    plain = (src.block_shapes[0][0] == 1 and src.count == 1 and src.profile.get("compress") is None
             and src.profile.get("interleave", "band") in ("band", None))
    if not plain or nrows <= 0 or ncols <= 0:
        return src.read(1, window=window, masked=True).astype("float32").filled(np.nan)
    # USGS answers every request with a redirect to its storage host. Resolve that once
    # and talk to the storage host directly over kept-alive connections.
    with urllib.request.urlopen(urllib.request.Request(MOLA_URL, headers={"Range": "bytes=0-1", "User-Agent": _UA}), timeout=60) as response:
        order = "<" if response.read() == b"II" else ">"
        final = urlsplit(response.url)
    dtype = dtype.newbyteorder(order)
    offsets = [int(src.get_tag_item(f"BLOCK_OFFSET_0_{row}", "TIFF", bidx=1)) for row in range(row0, row0 + nrows)]
    local = threading.local()

    def fetch(i):
        start = offsets[i] + col0 * dtype.itemsize
        end = start + ncols * dtype.itemsize - 1
        last = None
        for attempt in range(5):
            try:
                if getattr(local, "conn", None) is None:
                    local.conn = http.client.HTTPSConnection(final.netloc, timeout=30)
                local.conn.request("GET", final.path, headers={"Range": f"bytes={start}-{end}", "User-Agent": _UA})
                response = local.conn.getresponse()
                data = response.read()
                if response.status != 206 or len(data) != ncols * dtype.itemsize:
                    raise IOError(f"HTTP {response.status}, {len(data)} bytes")
                return np.frombuffer(data, dtype=dtype)
            except Exception as exc:
                last = exc
                try:
                    local.conn.close()
                except Exception:
                    pass
                local.conn = None
                time.sleep(0.5 * attempt)
        raise IOError(f"MOLA row {row0 + i} could not be read: {last}")

    with ThreadPoolExecutor(max_workers=16) as pool:
        rows = list(pool.map(fetch, range(nrows)))
    array = np.vstack(rows).astype("float32")
    if src.nodata is not None:
        array[array == src.nodata] = np.nan
    return array


def _mars_window(grid):
    with _remote_env(), rasterio.open(MOLA_URL) as src:
        check_body_crs(src.crs, "mars", "USGS MOLA")
        half = grid.half_extent_m
        bounds = transform_bounds(grid.crs, src.crs, -half, -half, half, half, densify_pts=64)
        raw = window_from_bounds(*bounds, transform=src.transform)
        left, top = math.floor(raw.col_off) - 3, math.floor(raw.row_off) - 3
        right = math.ceil(raw.col_off + raw.width) + 3
        bottom = math.ceil(raw.row_off + raw.height) + 3
        window = Window(left, top, right - left, bottom - top).intersection(Window(0, 0, src.width, src.height))
        array = _read_strip_window(src, window)
        return array, src.window_transform(window), src.crs, {
            "source": "USGS Astrogeology / NASA MGS MOLA",
            "dataset": "MOLA_MEGDR_463m",
            "source_url": MOLA_SOURCE,
            "url": MOLA_URL,
            "urls": [MOLA_URL],
            "native_resolution_m": 463.0835744,
            "version": "USGS global mosaic, edition 2003-03-21",
            "vertical_reference": "Mars areoid GMM-2B; metres",
            "body_radius_m": 3396190,
            "license": "CC0/public domain",
            "source_crs": src.crs.to_wkt(),
            "source_shape": [src.height, src.width],
            "source_window_shape": list(array.shape),
            "source_pixel_size": [abs(src.res[0]), abs(src.res[1])],
            "limitations": "MOLA is a gridded altimetry product. Gaps between orbital tracks were interpolated by the source producer; 463m spacing does not resolve rocks or small dunes.",
        }


_TILES: set[str] | None = None


def _tile_list() -> set[str]:
    """Names of all published Copernicus GLO-30 tiles (cached). A tile not listed is open ocean."""
    global _TILES
    with _LOCK:
        if _TILES is None:
            path = _cache_root(None).parent / "global" / "copernicus_tileList.txt"
            if not path.exists():
                import urllib.request
                request = urllib.request.Request(f"{COPERNICUS_BASE}/tileList.txt", headers={"User-Agent": _UA})
                with urllib.request.urlopen(request, timeout=60) as response:
                    text = response.read().decode()
                if text.count("Copernicus_DSM") < 20000:
                    raise MissingInputError("Copernicus tile list looks incomplete; check the network and retry")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            _TILES = {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
        return _TILES


def _tile_cache_path(name: str) -> Path:
    folder = _cache_root(None) / f"tiles_L{EARTH_OVERVIEW_LEVEL}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{name}.npz"


@lru_cache(maxsize=96)
def _read_tile(url):
    """(array, transform, crs) of one Copernicus tile overview, or None for open ocean.

    Ocean is decided by the official tile list, never by an error message: when the
    network drops, GDAL reports "does not exist" for files that do exist. A listed
    tile that cannot be read is retried and then raised; land is never silently NaN.
    Each tile is downloaded once and kept on disk, so later searches reuse it.
    """
    name = url.rsplit("/", 2)[-2]
    if name not in _tile_list():
        return None
    cached = _tile_cache_path(name)
    if cached.exists():
        try:
            with np.load(cached) as data:
                return data["array"].astype("float32"), Affine(*data["transform"]), rasterio.crs.CRS.from_wkt(str(data["crs"]))
        except Exception:
            cached.unlink(missing_ok=True)  # a truncated cache file: download again
    delays = (1, 2, 4)  # the search retries a failed place once more at the end
    for attempt in range(len(delays) + 1):
        try:
            with _remote_env(), rasterio.open(url, overview_level=EARTH_OVERVIEW_LEVEL) as src:
                array = src.read(1, masked=True).astype("float32").filled(np.nan)
                transform, crs = src.transform, src.crs
            pending = cached.with_name(f"{name}.{uuid.uuid4().hex}.partial.npz")
            np.savez_compressed(pending, array=array, transform=np.array(tuple(transform)[:6]), crs=crs.to_wkt())
            pending.replace(cached)
            return array, transform, crs
        except rasterio.errors.RasterioIOError as exc:
            if attempt == len(delays):
                raise MissingInputError(f"Copernicus tile could not be downloaded after {attempt + 1} tries "
                                        f"(internet connection problem?): {url.rsplit('/', 1)[-1]}") from exc
            time.sleep(delays[attempt])  # a dropped connection or DNS hiccup; try again


def _earth_window(grid):
    bounds = geographic_bounds(grid, "earth", margin=0.03)
    all_urls = _earth_urls(bounds)
    # Read each tile's overview whole (one ~1-3 MB request) in parallel, then merge in
    # memory. Merging remote datasets directly issues many slow small range reads.
    with ThreadPoolExecutor(max_workers=4) as pool:
        tiles = list(pool.map(_read_tile, all_urls))
    present = [t for t in tiles if t is not None]
    urls = [u for u, t in zip(all_urls, tiles) if t is not None]
    missing = [u for u, t in zip(all_urls, tiles) if t is None]
    if not present:
        raise FileNotFoundError("no Copernicus tile covers this window (open ocean)")
    with ExitStack() as stack:
        sources = []
        for array_t, transform_t, crs_t in present:
            check_body_crs(crs_t, "earth", "Copernicus GLO-30")
            memfile = stack.enter_context(MemoryFile())
            dataset = stack.enter_context(memfile.open(driver="GTiff", width=array_t.shape[1], height=array_t.shape[0], count=1,
                                                       dtype="float32", crs=crs_t, transform=transform_t, nodata=np.nan))
            dataset.write(array_t, 1)
            sources.append(dataset)
        # Merge before resampling. Reprojecting each tile separately would give
        # incorrect averages along tile boundaries. Absent tiles (open ocean) stay NaN.
        data, transform = merge(sources, bounds=bounds, nodata=np.nan, dtype="float32", method="first")
        array = data[0]
        return array, transform, sources[0].crs, {
            "source": "Copernicus DEM / ESA, distributed by Sinergise on AWS",
            "dataset": "COPERNICUS_GLO30_2021_DSM",
            "source_url": COPERNICUS_SOURCE,
            "url": COPERNICUS_SOURCE,
            "urls": urls,
            "missing_tiles_open_ocean": missing,
            "native_resolution_m": 30.0,
            "native_resolution_description": "1 arc-second latitude; longitude spacing varies with latitude",
            "version": "Copernicus DEM 2021 release, AWS COG GLO-30 Public",
            "vertical_reference": "EGM2008 orthometric height; metres",
            "license": "Copernicus DEM GLO-30 Public free/open licence; attribution required",
            "attribution": "Copernicus DEM was accessed from https://registry.opendata.aws/copernicus-dem/. Copernicus DEM GLO-30: DLR e.V. 2010-2014 and Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA; all rights reserved.",
            "source_crs": sources[0].crs.to_wkt(),
            "source_window_shape": list(array.shape),
            "source_pixel_size": [abs(transform.a), abs(transform.e)],
            "source_overview": f"internal COG overview level {EARTH_OVERVIEW_LEVEL} (8x block mean of the 30 m data, about 240 m), averaged to the analysis grid",
            "limitations": "This is a digital surface model including vegetation and buildings, not SRTM or a bare-earth DEM. Missing source tiles are errors, never synthetic zero-filled terrain.",
        }


def _save_native(path, array, transform, crs):
    with rasterio.open(path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0],
                       count=1, dtype="float32", crs=crs, transform=transform,
                       nodata=np.nan, compress="deflate", predictor=3) as dst:
        dst.write(array, 1)


def fetch_roi(body, lat, lon, radius_km=25, grid_m=463, *, cache_dir=None):
    """Return a real square DEM window of side ``2 * radius_km``.

    Returns dem(float32 ndarray, NaN nodata), pixel_size_m, bounds([W,S,E,N]),
    crs(WKT), transform(Affine), nodata_mask, projected_bounds_m and provenance.
    Coordinate bounds describe the actual rounded grid. No human approval is
    implied by acquiring a window. Native source cutouts remain in the cache.
    """
    body, lat, lon, radius_km, grid_m = _validate(body, lat, lon, radius_km, grid_m)
    grid = make_grid(body, lat, lon, radius_km * 2, grid_m)
    bounds = list(geographic_bounds(grid, body, margin=0))
    if bounds[2] - bounds[0] > 180 or bounds[0] < -180 or bounds[2] > 180:
        raise MissingInputError("This window crosses the antimeridian; choose a smaller window or another centre")
    key_input = {"v": _CACHE_VERSION, "body": body, "lat": lat, "lon": lon, "radius_km": radius_km, "grid_m": grid_m}
    key = hashlib.sha256(json.dumps(key_input, sort_keys=True).encode()).hexdigest()[:24]
    folder = _cache_root(cache_dir) / f"{body}_{key}"
    dem_path, info_path = folder / "dem.tif", folder / "provenance.json"
    with _key_lock(key):
        if dem_path.exists() and info_path.exists():
            provenance = json.loads(info_path.read_text(encoding="utf-8"))
            if hashlib.sha256(dem_path.read_bytes()).hexdigest() != provenance.get("sha256"):
                raise MissingInputError(f"Cached DEM checksum mismatch at {dem_path}; reacquire this window before analysis")
            with rasterio.open(dem_path) as src:
                dem = src.read(1).astype("float32")
            check_quality(dem, 2500, 0.1, f"Cached {body} DEM")
        else:
            try:
                native, native_transform, native_crs, provenance = _mars_window(grid) if body == "mars" else _earth_window(grid)
            except Exception as exc:
                raise MissingInputError(f"Real {body} DEM could not be fetched at {lat}, {lon}: {exc}. No substitute heights were generated.") from exc
            dem = np.full(grid.shape, np.nan, dtype="float32")
            method = Resampling.bilinear if body == "mars" else Resampling.average
            reproject(source=native, destination=dem,
                      src_transform=native_transform, src_crs=native_crs, src_nodata=np.nan,
                      dst_transform=grid.transform, dst_crs=grid.crs, dst_nodata=np.nan,
                      resampling=method, num_threads=2)
            quality = check_quality(dem, 2500, 0.1, f"Real {body} DEM")
            folder.mkdir(parents=True, exist_ok=True)
            token = uuid.uuid4().hex
            native_temporary = folder / f"native.{token}.partial.tif"
            _save_native(native_temporary, native, native_transform, native_crs)
            native_temporary.replace(folder / "native.tif")
            temporary = folder / f"dem.{token}.partial.tif"
            write_geotiff(temporary, dem, grid, f"{body} real elevation, metres")
            temporary.replace(dem_path)
            provenance.update({
                "accessed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "center": {"lat": lat, "lon": lon},
                "requested_radius_km": radius_km,
                "requested_window_km": radius_km * 2,
                "actual_window_km": grid.width * grid_m / 1000,
                "grid_m": grid_m,
                "resampling": method.name,
                "bounds": bounds,
                "shape": list(dem.shape),
                "quality": quality,
                "cache_key": key,
                "cache_path": str(dem_path),
                "native_cache_path": str(folder / "native.tif"),
                "sha256": hashlib.sha256(dem_path.read_bytes()).hexdigest(),
                "approval_status": "not_reviewed",
                "is_synthetic": False,
            })
            pending = folder / f"provenance.{token}.partial.json"
            pending.write_text(json.dumps(provenance, indent=2, allow_nan=False), encoding="utf-8")
            pending.replace(info_path)
    half = grid.half_extent_m
    return {"dem": dem, "elevation": dem, "pixel_size_m": grid_m,
            "nodata_mask": ~np.isfinite(dem), "bounds": bounds,
            "projected_bounds_m": [-half, -half, half, half],
            "transform": grid.transform, "crs": grid.crs.to_wkt(),
            "provenance": provenance}


load_roi = fetch_roi
