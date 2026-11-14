"""Shared fixtures: a throw-away project root with the real config and synthetic DEMs."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from scipy.ndimage import gaussian_filter

REPO = Path(__file__).resolve().parents[1]
MARS_EQC = "+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs"
MOLA_PX_M = 463.0835744


def _terrain(shape, seed, amplitude, sigma):
    rng = np.random.default_rng(seed)
    z = gaussian_filter(rng.normal(size=shape), sigma)
    z = z / np.abs(z).max() * amplitude
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    for cy, cx, r, d in ((0.4, 0.45, 0.08, 300.0), (0.6, 0.6, 0.05, 150.0)):
        dist = np.hypot(yy - cy * shape[0], xx - cx * shape[1]) / (r * shape[0])
        z -= d * np.clip(1 - dist**2, 0, None)
    return z


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    for name in ("sites.yaml", "metrics.yaml"):
        shutil.copy(REPO / "config" / name, root / "config" / name)
    return root


@pytest.fixture
def synthetic_mola(project: Path) -> Path:
    """MOLA-like Mars raster (Mars sphere, Equirectangular) around Gale, int16 metres."""
    deg_m = np.pi * 3_396_190.0 / 180.0
    lon0, lat1 = 135.0, -2.0
    n = int(round(5 * deg_m / MOLA_PX_M))
    z = (-4500 + _terrain((n, n), 1, 600.0, 4)).astype("int16")
    path = project / "data" / "raw" / "mars" / "gale_mola_463m.tif"
    path.parent.mkdir(parents=True)
    with rasterio.open(
        path, "w", driver="GTiff", width=n, height=n, count=1, dtype="int16", crs=MARS_EQC,
        transform=from_origin(lon0 * deg_m, lat1 * deg_m, MOLA_PX_M, MOLA_PX_M),
    ) as dst:
        dst.write(z, 1)
    return path


@pytest.fixture
def synthetic_srtm(project: Path) -> Path:
    """SRTM-like Earth raster (EPSG:4326, 3 arc-second) placed where the cache expects it."""
    from terramind.config import load_settings
    from terramind.sources.opentopo import srtm_cache_path

    settings = load_settings(project)
    path = srtm_cache_path(settings, settings.site("ustyurt"))
    path.parent.mkdir(parents=True, exist_ok=True)
    res = 1 / 1200
    west, north = 55.5, 44.1
    w, h = int(1.3 / res), int(1.0 / res)
    z = (180 + _terrain((h, w), 2, 120.0, 10)).astype("int16")
    z[:5, :5] = -32768  # a few voids, outside the ROI
    with rasterio.open(
        path, "w", driver="GTiff", width=w, height=h, count=1, dtype="int16", crs="EPSG:4326",
        transform=from_origin(west, north, res, res), nodata=-32768,
    ) as dst:
        dst.write(z, 1)
    return path
