"""Global screening index on a small synthetic EPSG:4326 grid (no download)."""
import math

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from scipy.ndimage import gaussian_filter

from terramind import global_index
from terramind.global_index import EarthIndex, block_average, build_index, describe_window, pick_spread

CRATER = (35.0, 47.5)


def _crater(dist_km):
    """Bowl 600 m deep, rim at 20 km, decaying outer flank."""
    return np.where(dist_km < 20, -600 + 1.5 * dist_km ** 2, (dist_km < 32) * (400 - 33 * (dist_km - 20)))


def _earth_tif(path):
    res = 1 / 60
    west, north, w, h = 40.0, 40.0, int(15 / res), int(10 / res)
    rng = np.random.default_rng(4)
    z = gaussian_filter(rng.normal(size=(h, w)), 3)
    z = z / np.abs(z).max() * 250 + 800
    lat = north - (np.arange(h) + 0.5) * res
    lon = west + (np.arange(w) + 0.5) * res
    dy = (lat[:, None] - CRATER[0]) * 111.0
    dx = (lon[None, :] - CRATER[1]) * 111.0 * math.cos(math.radians(CRATER[0]))
    z = z + _crater(np.hypot(dy, dx))
    z[:, :60] = -200  # a strip of sea on the west edge
    with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(west, north, res, res)) as dst:
        dst.write(z.astype("float32"), 1)
    return path


def _mars_target():
    c = (np.arange(108) + 0.5 - 54) * 0.463
    dist = np.hypot(c[None, :], c[:, None])
    dem = (_crater(dist) - 4000).astype("float32")
    inside = dist <= 25
    coarse = block_average(np.where(inside, dem, np.nan))
    n = coarse.shape[0]
    cc = np.arange(n) - (n - 1) / 2
    r = 25000 / global_index.SCREEN_PIXEL_M
    return describe_window(coarse, (cc[None, :] ** 2 + cc[:, None] ** 2 <= r ** 2) & np.isfinite(coarse))


def test_index_finds_the_matching_landform(tmp_path):
    src = _earth_tif(tmp_path / "earth.tif")
    out = build_index(source=src, out=tmp_path / "index", progress=lambda *_: None, lat_range=(-56, 80))
    index = EarthIndex(out)
    assert len(index) > 100
    assert index.meta["windows"] == len(index)
    assert index.lon.min() > 40.3, "sea strip and source edge are not land windows"
    weights = {"slope_deg": 0.4, "relief_m": 0.35, "tri_m": 0.25}
    score = index.screen(_mars_target(), weights, 0.5)
    best = int(np.argmax(score))
    km = math.hypot((index.lat[best] - CRATER[0]) * 111, (index.lon[best] - CRATER[1]) * 111 * math.cos(math.radians(35)))
    assert km < 25, f"best window is {km:.0f} km from the crater"
    picks = pick_spread(index.lat, index.lon, score, 5, 150)
    assert picks[0] == best and len(picks) == 5


def test_pick_spread_enforces_distance():
    lat = np.array([0.0, 0.1, 5.0])
    lon = np.array([0.0, 0.1, 5.0])
    assert pick_spread(lat, lon, np.array([0.9, 0.8, 0.5]), 3, 100) == [0, 2]


def test_area_resample_keeps_mean_and_marks_gaps():
    row = np.arange(12, dtype="float32")
    out = global_index._area_resample_row(row, 3.0)
    assert out.mean() == pytest.approx(row.mean())
    row[:6] = np.nan
    assert np.isnan(global_index._area_resample_row(row, 3.0)[0])
