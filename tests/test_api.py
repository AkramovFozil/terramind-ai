"""API uses real scientific functions; synthetic DEMs here are test fixtures only."""
import time
from threading import Event

import numpy as np
import pytest
from pyproj import Transformer
from scipy.ndimage import gaussian_filter

pytest.importorskip("fastapi", reason="Install the api extra to test HTTP endpoints")
from fastapi.testclient import TestClient

from terramind.api import create_app
from terramind.config import load_settings
from terramind.crs import local_crs_string
from terramind.search_service import SearchService

PX = 463.0
MATCH = (40.0, 50.0)       # where the screening index points to the matching place
OTHER = (45.0, 60.0)       # a second, different place
SHIFT = (10, -8)           # the true landform sits 10 rows south and 8 columns west of MATCH


def _dem():
    y, x = np.indices((108, 108), dtype="float32")
    r = np.hypot(y - 53.5, x - 53.5)
    bowl = np.where(r < 40, -800 + 0.3 * r ** 2, -320 + (r - 40) * 30)  # a crater: floor, rim
    return (bowl + x * 2 + np.sin(x / 9) * 40).astype("float32")


def _rough(seed, size):
    rng = np.random.default_rng(seed)
    z = gaussian_filter(rng.normal(size=(size, size)), 6)
    return (z / np.abs(z).max() * 400 + 500).astype("float32")


def _world():
    """A 400 x 400 Earth area around MATCH with the Mars landform embedded off-centre."""
    world = _rough(1, 400)
    r0, c0 = 200 - 54 + SHIFT[0], 200 - 54 + SHIFT[1]
    world[r0:r0 + 108, c0:c0 + 108] = _dem() + 900
    return world


WORLD = _world()


def _data(dem):
    return {"dem": dem, "pixel_size_m": PX, "bounds": [1, 2, 3, 4], "crs": "test AEQD",
            "provenance": {"source": "Synthetic test fixture", "dataset": "test-only", "url": "https://example.invalid/test"}}


def _crop(lat, lon, radius_km):
    n = int(round(radius_km * 2000 / PX))
    to_local = Transformer.from_crs("EPSG:4326", local_crs_string("earth", *MATCH), always_xy=True)
    x, y = to_local.transform(lon, lat)
    col, row = 200 + int(round(x / PX)), 200 - int(round(y / PX))
    return WORLD[row - n // 2: row - n // 2 + n, col - n // 2: col - n // 2 + n].copy()


def _provider(body, lat, lon, radius_km, grid_m=463):
    if body == "mars":
        return _data(_dem())
    if abs(lat - OTHER[0]) < 1:
        return _data(_rough(7, int(round(radius_km * 2000 / PX))))
    return _data(_crop(lat, lon, radius_km))


class FakeIndex:
    meta = {"version": 0, "built_at": "test", "lat_range": [-56, 80], "lat_step_deg": 0.25, "pixel_m": 1852}

    def __init__(self, points=(MATCH, OTHER), scores=(0.9, 0.8)):
        self.lat = np.array([p[0] for p in points], dtype="float32")
        self.lon = np.array([p[1] for p in points], dtype="float32")
        self.scores = np.array(scores, dtype="float32")

    def __len__(self):
        return len(self.lat)

    def screen(self, target, weights, shape_weight):
        assert target["shape"].shape == (40,)
        return self.scores


def _client(project, provider=_provider, index=None):
    service = SearchService(provider=provider, index=index or FakeIndex(), settings=load_settings(project))
    return TestClient(create_app(service, serve_frontend=False))


def _finish(client, payload=None):
    response = client.post("/api/search", json=payload or {"lat": -4.49, "lon": 137.42, "radius_km": 25})
    assert response.status_code == 202
    location = response.json()["status_url"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(location).json()
        if job["status"] in ("completed", "failed"):
            return job
        Event().wait(0.02)
    pytest.fail("Background job did not finish")


def test_global_search_refines_to_the_exact_matching_place(project):
    with _client(project) as client:
        job = _finish(client)
        assert job["status"] == "completed", job
        result = job["result"]
        top = result["candidates"][0]
        assert top["found_by"] == "global_search"
        assert top["score"] == pytest.approx(100, abs=0.01)
        assert top["metric_scores"]["shape"] == pytest.approx(100, abs=0.01)
        # The refined centre moved onto the embedded landform.
        to_local = Transformer.from_crs("EPSG:4326", local_crs_string("earth", *MATCH), always_xy=True)
        x, y = to_local.transform(top["lon"], top["lat"])
        assert round(x / PX) == SHIFT[1] and round(-y / PX) == SHIFT[0]
        assert top["refinement"]["shift_km"] == pytest.approx(np.hypot(*SHIFT) * PX / 1000, abs=0.05)
        assert len(result["candidates"]) == 2
        assert result["candidates"][1]["score"] < top["score"]
        assert result["coverage"]["global_search"] is True
        assert result["coverage"]["screened_windows"] == 2
        assert result["review"]["human_approved"] is False
        terrain = client.get(top["terrain_url"])
        assert terrain.status_code == 200
        grid = terrain.json()
        assert grid["measured_dem"] is True and grid["width"] == grid["height"] == 108
        np.testing.assert_allclose(np.array(grid["elevations"]).reshape(108, 108), _dem() + 900, atol=0.0051)
    assert not (project / "data" / "processed").exists(), "API must not approve or write CLI ROIs"


def test_inverted_landform_scores_low_on_shape(project):
    """A dome where Mars has a crater must not look similar (the reported bug)."""
    def provider(body, lat, lon, radius_km, grid_m=463):
        if body == "mars":
            return _data(_dem())
        n = int(round(radius_km * 2000 / PX))
        world = np.full((n, n), 0, dtype="float32") + _rough(3, n) * 0.05
        c = (n - 108) // 2
        world[c:c + 108, c:c + 108] = -_dem() + 900
        return _data(world)
    with _client(project, provider, FakeIndex(points=(MATCH,), scores=(0.9,))) as client:
        job = _finish(client)
        assert job["status"] == "completed", job
        top = job["result"]["candidates"][0]
        assert top["metric_scores"]["shape"] < 20
        assert top["score"] < 60


def test_open_water_is_rejected(project):
    def provider(body, lat, lon, radius_km, grid_m=463):
        if body == "mars":
            return _data(_dem())
        return _data(np.zeros((int(round(radius_km * 2000 / PX)),) * 2, dtype="float32"))
    with _client(project, provider) as client:
        job = _finish(client)
        assert job["status"] == "failed"
        assert all("water" in c["reason"] for c in job["excluded_candidates"])


@pytest.mark.parametrize("payload", [
    {"lat": 86, "lon": 0}, {"lat": 0, "lon": 181},
    {"lat": 0, "lon": 0, "radius_km": 0.99}, {"lat": 0, "lon": 0, "radius_km": 100.01},
    {"lat": 0, "lon": 0, "radius_km": "10"}, {"lat": 0, "lon": 0, "radius_km": True},
    {"lat": "0", "lon": 0}, {"lat": True, "lon": 0},
    {"lat": 0, "lon": 0, "invented": 1},
])
def test_invalid_search_is_rejected(project, payload):
    with _client(project) as client:
        assert client.post("/api/search", json=payload).status_code == 422


def test_nonfinite_json_is_rejected_without_serialization_error(project):
    with _client(project) as client:
        response = client.post("/api/search", content='{"lat":NaN,"lon":0}', headers={"Content-Type": "application/json"})
        assert response.status_code == 422


def test_target_nodata_fails_without_scores(project):
    def provider(*args, **kwargs):
        return _data(np.full((108, 108), np.nan, dtype="float32"))
    with _client(project, provider) as client:
        job = _finish(client)
        assert job["status"] == "failed"
        assert "quality check" in job["error"]
        assert "result" not in job


def test_candidate_source_failure_is_excluded_and_reported(project):
    def provider(body, lat, lon, radius_km, grid_m=463):
        if body == "earth" and abs(lat - OTHER[0]) < 1:
            raise RuntimeError("Official DEM service unavailable")
        return _provider(body, lat, lon, radius_km, grid_m)
    with _client(project, provider) as client:
        job = _finish(client)
        assert job["status"] == "completed"
        result = job["result"]
        assert len(result["candidates"]) == 1
        assert result["coverage"]["excluded_count"] == 1
        assert "unavailable" in result["excluded_candidates"][0]["reason"]


def test_all_candidates_unavailable_returns_no_ranking(project):
    def provider(body, *args, **kwargs):
        if body == "earth":
            raise RuntimeError("Network unavailable")
        return _data(_dem())
    with _client(project, provider) as client:
        job = _finish(client)
        assert job["status"] == "failed"
        assert len(job["excluded_candidates"]) == 2
        assert "result" not in job


def test_missing_index_fails_with_build_instructions(project):
    def loader():
        raise FileNotFoundError("Global Earth index not found at X")
    service = SearchService(provider=_provider, index_loader=loader, settings=load_settings(project))
    with TestClient(create_app(service, serve_frontend=False)) as client:
        catalog = client.get("/api/catalog").json()
        assert catalog["coverage"]["index"]["ready"] is False
        job = _finish(client)
        assert job["status"] == "failed"
        assert "build-index" in job["error"]


def test_nodata_is_preserved_in_visualization_and_circle_quality(project):
    def provider(body, *args, **kwargs):
        data = _provider(body, *args, **kwargs)
        if body == "mars":
            data["dem"][0, 0] = np.nan  # Outside the requested circle; not a failed ROI.
        return data
    with _client(project, provider) as client:
        job = _finish(client)
        assert job["status"] == "completed"
        terrain = client.get(job["result"]["target"]["terrain_url"]).json()
        assert terrain["elevations"][0] is None
        assert terrain["roi_mask"][0] is False
        assert terrain["quality"]["nodata_fraction"] == 0


def test_unknown_job_and_catalog_coverage(project):
    with _client(project) as client:
        assert client.get("/api/search/missing").status_code == 404
        assert client.get("/api/terrain?job_id=missing").status_code == 404
        catalog = client.get("/api/catalog").json()
        assert catalog["coverage"]["global_search"] is True
        assert catalog["coverage"]["index"]["ready"] is True
        assert catalog["earth_candidates"] == []
        assert catalog["radius_km"] == {"default": 25, "min": 1, "max": 100, "step": None}


def test_background_fetch_keeps_api_responsive_and_queue_bounded(project):
    entered, release = Event(), Event()

    def provider(*args, **kwargs):
        entered.set()
        assert release.wait(5), "Test did not release provider"
        return _data(_dem())

    service = SearchService(provider=provider, index=FakeIndex(), settings=load_settings(project), max_pending=1)
    with TestClient(create_app(service, serve_frontend=False)) as client:
        try:
            response = client.post("/api/search", json={"lat": 0, "lon": 0})
            assert response.status_code == 202
            assert entered.wait(2)
            assert client.get("/api/health").status_code == 200
            job_id = response.json()["job_id"]
            assert client.get(f"/api/terrain?job_id={job_id}").status_code == 409
            overloaded = client.post("/api/search", json={"lat": 1, "lon": 1})
            assert overloaded.status_code == 503
            assert overloaded.headers["retry-after"] == "5"
        finally:
            release.set()


def test_circle_nodata_threshold_is_enforced_even_with_many_valid_pixels(project):
    def provider(*args, **kwargs):
        dem = _dem()
        dem[45:63] = np.nan
        return _data(dem)

    with _client(project, provider) as client:
        job = _finish(client)
        assert job["status"] == "failed"
        assert "nodata" in job["error"] and "maximum 10%" in job["error"]


def test_mismatched_analysis_resolution_cannot_produce_score(project):
    def provider(*args, **kwargs):
        data = _data(_dem())
        data["pixel_size_m"] = 30
        return data

    with _client(project, provider) as client:
        job = _finish(client)
        assert job["status"] == "failed"
        assert "common 463 m grid" in job["error"]
        assert "result" not in job
