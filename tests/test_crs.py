import pytest
from rasterio.crs import CRS

from terramind.config import ConfigError
from terramind.crs import check_body_crs, geod, local_crs
from terramind.roi import geographic_bounds, make_grid


def test_mars_one_degree_latitude():
    _, _, dist = geod("mars").inv(137.42, -5.0, 137.42, -4.0)
    assert dist == pytest.approx(59_274, rel=1e-3)


def test_earth_one_degree_latitude():
    _, _, dist = geod("earth").inv(56.0, 43.0, 56.0, 44.0)
    assert 110_600 <= dist <= 111_700


@pytest.mark.parametrize("body,lat,lon", [("mars", -4.49, 137.42), ("earth", 43.651, 56.128)])
def test_roi_is_108_pixels(body, lat, lon):
    g = make_grid(body, lat, lon, 50, 463)
    assert abs(g.width - 108) <= 1 and abs(g.height - 108) <= 1
    assert g.half_extent_m == pytest.approx(25_000, abs=463)


def test_mars_bbox_is_about_50_km():
    g = make_grid("mars", -4.49, 137.42, 50, 463)
    w, s, e, n = geographic_bounds(g, "mars", margin=0)
    assert (n - s) * 59_274 == pytest.approx(50_000, rel=0.01)


def test_local_crs_uses_the_right_planet():
    check_body_crs(local_crs("mars", -4.49, 137.42), "mars")
    check_body_crs(local_crs("earth", 43.6, 56.1), "earth")


def test_mars_data_in_wgs84_is_refused():
    with pytest.raises(ConfigError):
        check_body_crs(CRS.from_epsg(4326), "mars", "fake MOLA")
    with pytest.raises(ConfigError):
        check_body_crs(local_crs("mars", 0, 0), "earth", "fake SRTM")
