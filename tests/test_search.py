"""Analog Finder on synthetic data: tiles, mosaic, water filter, ranking, known-site rank."""

import json
import math

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from terramind.cli import main
from terramind.config import ConfigError, GateError, load_settings
from terramind.gate import approve
from terramind.pipeline import prepare
from terramind.regions import build_vrt, get_region, tile_bounds, window_centers
from terramind.search import search

RES = 1 / 1200  # 3 arc-second, like SRTM GL3
LAKE = (56.00, 43.74, 56.22, 43.90)  # w, s, e, n: flattened water, like SRTM lakes


def terrain(lon, lat):
    z = 150 + 40 * np.sin(lon * 37.0) * np.cos(lat * 29.0) + 15 * np.sin(lon * 211.0 + lat * 173.0)
    lake = (lon >= LAKE[0]) & (lon <= LAKE[2]) & (lat >= LAKE[1]) & (lat <= LAKE[3])
    return np.where(lake, 120.0, z)


class FakeOpenTopo:
    """Serves a GeoTIFF for any requested bbox, aligned to the global 3-arc-second grid."""

    def __init__(self):
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params)
        w, s, e, n = (float(params[k]) for k in ("west", "south", "east", "north"))
        x0, y0 = math.floor(w / RES) * RES, math.ceil(n / RES) * RES
        width, height = int(round((e - x0) / RES)), int(round((y0 - s) / RES))
        lon = x0 + (np.arange(width) + 0.5) * RES
        lat = y0 - (np.arange(height) + 0.5) * RES
        z = terrain(lon[None, :], lat[:, None]).astype("int16")
        with MemoryFile() as mem:
            with mem.open(driver="GTiff", width=width, height=height, count=1, dtype="int16", crs="EPSG:4326",
                          transform=from_origin(x0, y0, RES, RES), nodata=-32768) as dst:
                dst.write(z, 1)
            content = mem.read()

        class R:
            status_code = 200
        r = R()
        r.content = content
        return r


@pytest.fixture
def test_region(project):
    (project / "config" / "regions.yaml").write_text(
        "regions:\n"
        "  testland:\n"
        "    name: Test land\n"
        "    bbox: [56.0, 43.4, 56.6, 43.9]\n"
        "    stride_km: 5\n"
        "    tile_deg: 0.3\n",
        encoding="utf-8",
    )
    return project


def test_tiles_and_centers(test_region):
    s = load_settings(test_region)
    r = get_region(s, "testland")
    assert len(tile_bounds(r)) == 4  # 0.6 x 0.5 deg in 0.3 deg tiles -> 2 x 2
    centers = window_centers(r, s.window_km)
    assert centers and all(56.0 < lon < 56.6 and 43.4 < lat < 43.9 for lat, lon in centers)


def test_vrt_mosaic_matches_tiles(test_region, tmp_path):
    s = load_settings(test_region)
    r = get_region(s, "testland")
    from terramind.regions import fetch_region

    vrt = fetch_region(s, r, "key", session=FakeOpenTopo())
    with rasterio.open(vrt) as v:
        lon, lat = 56.3013, 43.6507  # interior point near a tile corner
        row, col = v.index(lon, lat)
        val = v.read(1, window=((row, row + 1), (col, col + 1)))[0, 0]
    assert abs(val - float(terrain(np.array(lon), np.array(lat)))) <= 1  # int16 truncation


def test_search_ranks_filters_water_and_reports_known_site(test_region, synthetic_mola, synthetic_srtm):
    s = load_settings(test_region)
    with pytest.raises(GateError):
        search(s, "gale", "testland", api_key="key", session=FakeOpenTopo())
    prepare(s, "gale")
    approve(s, "gale")
    with pytest.raises(ConfigError):
        search(s, "ustyurt", "testland", api_key="key", session=FakeOpenTopo())  # not a Mars reference

    fake = FakeOpenTopo()
    res = search(s, "gale", "testland", api_key="key", session=fake, top_n=5)
    assert len(fake.calls) == 4 and all(c["demtype"] == "SRTMGL3" for c in fake.calls)
    c = res["counts"]
    assert c["windows"] == c["scored"] + c["water"] + c["nodata"]
    assert c["water"] > 0 and c["scored"] > 0
    top = res["top"]
    assert 1 <= len(top) <= 5
    key = "overall_A"
    assert [t[key] for t in top] == sorted((t[key] for t in top), reverse=True)
    from pyproj import Geod
    g = Geod(ellps="WGS84")
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            assert g.inv(top[i]["lon"], top[i]["lat"], top[j]["lon"], top[j]["lat"])[2] >= s.window_km * 1000 - 1
    for t in top:
        assert t["satellite"].startswith("https://")
    known = {k["site"]: k for k in res["known_sites"]}
    assert "ustyurt" in known and 1 <= known["ustyurt"]["rank"] <= c["scored"]

    out = test_region / "results" / "search" / "gale__testland"
    for name in ("search.json", "windows.csv", "map.png"):
        assert (out / name).exists()
    assert json.loads((out / "search.json").read_text(encoding="utf-8"))["counts"] == c

    # second run reuses the cached tiles
    fake2 = FakeOpenTopo()
    search(s, "gale", "testland", api_key="key", session=fake2)
    assert fake2.calls == []


def test_regions_cli(test_region):
    assert main(["--root", str(test_region), "regions"]) == 0
