"""Moon support: sphere radius, CRS check, LOLA-like input through prepare and the matrix."""

import pytest
import rasterio

from terramind.config import ConfigError, load_settings
from terramind.crs import check_body_crs, geod, local_crs
from terramind.gate import approve
from terramind.pipeline import prepare, score


def test_moon_one_degree_latitude():
    _, _, dist = geod("moon").inv(29.0, -85.0, 29.0, -84.0)
    assert dist == pytest.approx(30_323, rel=1e-3)


def test_moon_crs_is_checked():
    check_body_crs(local_crs("moon", -84.79, 29.2), "moon")
    with pytest.raises(ConfigError):
        check_body_crs(local_crs("mars", -84.79, 29.2), "moon", "fake LOLA")


def test_prepare_and_score_moon_reference(project, synthetic_lola, synthetic_srtm):
    s = load_settings(project)
    roi = prepare(s, "mouton")
    assert roi["quality"]["valid_pixels"] >= s.min_valid_pixels
    assert roi["input"]["resampling"] == "average"  # 80 m LOLA is averaged to 463 m, like SRTM
    with rasterio.open(project / roi["files"]["dem"]) as src:
        assert "1737400" in src.crs.to_string()
    prepare(s, "ustyurt")
    approve(s, "mouton")
    approve(s, "ustyurt")
    res = score(s, "mouton", "ustyurt")
    assert 0.0 <= res["overall"]["A"]["score"] <= 1.0
    assert not any("MOLA" in c for c in res["caveats"])  # MOLA caveat only for Mars pairs
