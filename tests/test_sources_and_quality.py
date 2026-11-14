import numpy as np
import pytest

from terramind.config import MissingInputError, QualityError, load_settings
from terramind.raster import check_quality
from terramind.sources.mola import resolve_dem_path
from terramind.sources.opentopo import fetch_srtm

FAKE_KEY = "sk-test-0123456789abcdef"


def test_quality_fails_below_2500_valid_pixels():
    dem = np.full((108, 108), np.nan, dtype="float32")
    dem.flat[:2400] = 1.0
    with pytest.raises(QualityError) as e:
        check_quality(dem, 2500, 1.0, "test")
    assert "2400" in str(e.value)


def test_quality_fails_on_too_much_nodata():
    dem = np.ones((108, 108), dtype="float32")
    dem[:20] = np.nan  # 18.5 % nodata, but 9504 valid pixels
    with pytest.raises(QualityError) as e:
        check_quality(dem, 2500, 0.10, "test")
    assert "9504" in str(e.value) and "18.5%" in str(e.value)


def test_quality_passes():
    r = check_quality(np.ones((108, 108)), 2500, 0.10, "test")
    assert r["valid_pixels"] == 11664 and r["nodata_fraction"] == 0


def test_missing_mola_gives_instructions(project):
    s = load_settings(project)
    with pytest.raises(MissingInputError) as e:
        resolve_dem_path(s, s.site("gale"))
    msg = str(e.value)
    assert "Mars_MGS_MOLA_DEM_mosaic_global_463m.tif" in msg and "planetarymaps.usgs.gov" in msg


def test_missing_api_key(tmp_path):
    with pytest.raises(MissingInputError) as e:
        fetch_srtm((56, 43, 57, 44), tmp_path / "x.tif", api_key=None)
    assert "OPENTOPO_API_KEY" in str(e.value)


class FakeResponse:
    def __init__(self, status, content):
        self.status_code, self.content = status, content


class FakeSession:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, params, timeout):
        self.calls.append(params)
        return self.resp


def test_error_never_leaks_the_key(tmp_path):
    session = FakeSession(FakeResponse(401, f"Invalid API key {FAKE_KEY}".encode()))
    with pytest.raises(MissingInputError) as e:
        fetch_srtm((56, 43, 57, 44), tmp_path / "x.tif", FAKE_KEY, session=session)
    assert FAKE_KEY not in str(e.value) and "***" in str(e.value)
    assert not (tmp_path / "x.tif").exists()


def test_download_is_cached(tmp_path):
    session = FakeSession(FakeResponse(200, b"II*\x00" + b"\x00" * 100))
    dest = tmp_path / "earth" / "x.tif"
    fetch_srtm((56, 43, 57, 44), dest, FAKE_KEY, session=session)
    fetch_srtm((56, 43, 57, 44), dest, FAKE_KEY, session=session)
    assert len(session.calls) == 1
    assert session.calls[0]["demtype"] == "SRTMGL1" and session.calls[0]["outputFormat"] == "GTiff"
