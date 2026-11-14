"""Acquisition boundary checks; no network calls and no live-data substitutes."""

import pytest

from terramind.config import MissingInputError
from terramind.sources import public_dem


def test_negative_coordinates_select_southwest_degree_tile():
    # Yungay is -24.0848,-69.9151: truncating toward zero would select
    # the wrong hemisphere-adjacent tile (S24/W069 rather than S25/W070).
    urls = public_dem._earth_urls((-69.92, -24.09, -69.91, -24.08))
    assert len(urls) == 1
    assert "/Copernicus_DSM_COG_10_S25_00_W070_00_DEM/" in urls[0]


def test_missing_real_dem_raises_without_creating_fake_cache(tmp_path, monkeypatch):
    def unavailable(_grid):
        raise OSError("source unavailable")

    monkeypatch.setattr(public_dem, "_mars_window", unavailable)
    with pytest.raises(MissingInputError, match="No substitute heights were generated"):
        public_dem.fetch_roi("mars", -4.49, 137.42, 25, cache_dir=tmp_path)
    assert not list(tmp_path.rglob("*.tif"))


@pytest.mark.parametrize("body,lat,lon,radius", [
    ("moon", 0, 0, 25),
    ("mars", float("nan"), 137.42, 25),
    ("earth", 43.651, 56.18, -1),
    ("earth", 43.651, 56.18, 200),
])
def test_invalid_query_never_starts_download(body, lat, lon, radius, tmp_path):
    with pytest.raises(ValueError):
        public_dem.fetch_roi(body, lat, lon, radius, cache_dir=tmp_path)
    assert not list(tmp_path.iterdir())
