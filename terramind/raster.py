"""Reading DEMs onto a site grid, quality checks, and GeoTIFF output."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS as ProjCRS
from pyproj import Transformer
from rasterio.warp import Resampling, reproject

from terramind.config import QualityError
from terramind.crs import check_body_crs
from terramind.roi import Grid


def lon_domain(src) -> str:
    """'-180..180', '0..360' for a global raster, else 'regional'. Works for geographic and projected CRS."""
    crs = ProjCRS.from_wkt(src.crs.to_wkt())
    b = src.bounds
    y_mid = (b.top + b.bottom) / 2.0
    eps = abs(src.res[0]) / 2.0
    if crs.is_geographic:
        lon_left, lon_right = b.left + eps, b.right - eps
    else:
        to_geo = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
        (lon_left, lon_right), _ = to_geo.transform([b.left + eps, b.right - eps], [y_mid, y_mid])
    span = (lon_right - lon_left) % 360.0
    if span < 359.0 and not math.isclose(span, 0.0, abs_tol=1e-6):
        return "regional"
    if lon_left < -179.0:
        return "-180..180"
    if abs(lon_left) < 1.0:
        return "0..360"
    return "regional"


def read_to_grid(path: Path, grid: Grid, body: str, resampling: Resampling, label: str, root: Path | None = None):
    """Reproject band 1 of `path` onto `grid`. Returns (float32 array with NaN nodata, provenance dict)."""
    with rasterio.open(path) as src:
        check_body_crs(src.crs, body, label)
        # Recorded so a site that falls outside the file's coverage can be diagnosed;
        # the valid-pixel check then refuses the ROI instead of producing empty output.
        domain = lon_domain(src)
        dst =np.full(grid.shape, np.nan, dtype="float32")
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=grid.transform,
            dst_crs=grid.crs,
            dst_nodata=np.nan,
            resampling=resampling,
        )
        try:
            shown = str(path.resolve().relative_to(root.resolve())) if root else str(path)
        except ValueError:
            shown = str(path)
        stat = path.stat()
        info = {
            "file": shown,
            "file_bytes": stat.st_size,
            "file_modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
            "source_crs": src.crs.to_string(),
            "source_pixel_size": [abs(src.res[0]), abs(src.res[1])],
            "source_nodata": src.nodata,
            "longitude_domain": domain,
            "resampling": resampling.name,
            "target_pixel_m": grid.res_m,
        }
    return dst, info


def check_quality(dem: np.ndarray, min_valid_pixels: int, max_nodata_fraction: float, label: str) -> dict:
    """Valid-pixel and nodata checks. Raises QualityError, reporting both numbers."""
    total = int(dem.size)
    valid = int(np.isfinite(dem).sum())
    nodata_fraction = 1.0 - valid / total if total else 1.0
    report = {"valid_pixels": valid, "total_pixels": total, "nodata_fraction": round(nodata_fraction, 4)}
    problems = []
    if valid < min_valid_pixels:
        problems.append(f"{valid} valid pixels < minimum {min_valid_pixels}")
    if nodata_fraction > max_nodata_fraction:
        problems.append(f"nodata {nodata_fraction:.1%} > maximum {max_nodata_fraction:.0%}")
    if problems:
        raise QualityError(
            f"{label}: ROI failed the quality check ({'; '.join(problems)}). "
            f"Valid pixels: {valid} of {total}; nodata fraction: {nodata_fraction:.1%}. "
            "Check that the site center lies inside the DEM coverage."
        )
    return report


def write_geotiff(path: Path, array: np.ndarray, grid: Grid, description: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": grid.width,
        "height": grid.height,
        "count": 1,
        "dtype": "float32",
        "crs": grid.crs,
        "transform": grid.transform,
        "nodata": float("nan"),
        "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.asarray(array, dtype="float32"), 1)
        if description:
            dst.set_band_description(1, description)
    return path


def read_band(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        a = src.read(1).astype("float32")
        if src.nodata is not None and not np.isnan(src.nodata):
            a[a == src.nodata] = np.nan
    return a
