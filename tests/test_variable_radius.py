"""Requested radius must affect acquisition and measurements, not only the map circle."""
import math
import time
from threading import Event

import numpy as np
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from terramind.api import create_app
from terramind.config import QualityError, load_settings
from terramind.search_service import SearchService
from terramind.shape import PatternMatcher
from terramind.sources import public_dem

PX = 463.0


class ContextIndex:
    meta = {"radius_km": 25, "pixel_m": 1852}
    lat = np.array([35.0])
    lon = np.array([45.0])

    def __len__(self):
        return 1

    def screen(self, target, weights, shape_weight):
        assert target["shape"].shape == (40,)
        assert all(np.isfinite(v).all() for v in target.values())
        return np.array([0.9])


def measured_fixture(body, lat, lon, radius_km, grid_m=PX):
    """Analytical elevations are synthetic TEST DATA, never a production fallback."""
    n = round(radius_km * 2000 / grid_m)
    c = (np.arange(n) + 0.5 - n / 2) * grid_m
    x, y = np.meshgrid(c, -c)
    dem = 200 * np.sin(x / 4500) + 120 * np.cos(y / 6000) + 100 * np.sin((x + y) / 8000) + .003 * x - .002 * y
    if body == "earth":
        dem += 1000
    return {"dem": dem.astype("float32"), "pixel_size_m": grid_m,
            "provenance": {"source": "test-only", "dataset": "analytical test fixture"}}


def finish(client, radius):
    response = client.post("/api/search", json={"lat": -4.49, "lon": 137.42, "radius_km": radius})
    assert response.status_code == 202, response.text
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = client.get(response.json()["status_url"]).json()
        if job["status"] in ("completed", "failed"):
            return job
        Event().wait(.02)
    pytest.fail("Radius search did not finish")


@pytest.mark.parametrize("radius", [1, 10, 25, 100, 7.25])
def test_requested_radius_reaches_actual_dem_scoring_masks_and_export(project, radius):
    calls = []

    def provider(body, lat, lon, radius_km, grid_m=PX):
        calls.append((body, radius_km, grid_m))
        return measured_fixture(body, lat, lon, radius_km, grid_m)

    service = SearchService(provider=provider, index=ContextIndex(), settings=load_settings(project))
    with TestClient(create_app(service, serve_frontend=False)) as client:
        job = finish(client, radius)
        assert job["status"] == "completed", job
        assert job["request"]["radius_km"] == radius
        result = job["result"]
        assert result["method"]["radius_km"] == radius
        assert result["coverage"]["score_radius_km"] == radius
        assert result["coverage"]["screen_radius_km"] == 25
        assert result["coverage"]["exhaustive_at_requested_radius"] is False
        assert ("mars", radius, PX) in calls
        assert ("mars", 25, PX) in calls
        assert ("earth", radius, PX) in calls
        assert ("earth", min(100, radius + 20), PX) in calls
        assert all(r <= 100 and pixel == PX for _, r, pixel in calls)
        n = round(radius * 2000 / PX)
        c = (np.arange(n) + .5 - n / 2) * PX
        expected_mask = c[:, None] ** 2 + c[None, :] ** 2 <= (radius * 1000) ** 2
        for site in [result["target"], *result["candidates"]]:
            assert site["radius_km"] == radius
            assert site["quality"]["valid_pixels"] == int(expected_mask.sum())
            exported = client.get(site["terrain_url"]).json()
            assert exported["radius_km"] == radius
            assert exported["pixel_size_m"] == PX
            assert exported["width"] == exported["height"] == n
            np.testing.assert_array_equal(np.array(exported["roi_mask"]).reshape(n, n), expected_mask)
            slopes = np.array(exported["layers"]["slope_deg"], dtype=float).reshape(n, n)
            assert np.isnan(slopes[~expected_mask]).all()
        candidate = result["candidates"][0]
        assert math.isfinite(candidate["score"])
        assert candidate["refinement"]["radius_km"] == radius
        assert candidate["screen"]["role"] == "regional_context_shortlist_only"
        if radius == 1:
            assert result["target"]["quality"]["sparse_sampling"] is True
            assert result["target"]["quality"]["metric_valid_pixels"]["slope_deg"] == 4
            assert "Sparse sampling" in result["target"]["quality"]["resolution_note"]
        if radius == 100:
            assert candidate["refinement"]["positions_tested"] == 1
            assert candidate["refinement"]["available_shift_km"] == 0


@pytest.mark.parametrize("radius", [0, .999, 100.001, float("inf"), float("nan"), True, "10"])
def test_direct_submit_rejects_invalid_radius_before_provider(project, radius):
    def never(*args, **kwargs):
        pytest.fail("Invalid radius must not fetch data")
    service = SearchService(provider=never, index=ContextIndex(), settings=load_settings(project))
    try:
        with pytest.raises(ValueError, match="radius_km"):
            service.submit(0, 0, radius)
    finally:
        service.close()


def test_small_circle_requires_real_metric_neighbourhoods(project):
    def provider(*args, **kwargs):
        raw = measured_fixture(*args, **kwargs)
        raw["nodata_mask"] = np.zeros(raw["dem"].shape, dtype=bool)
        raw["nodata_mask"][0, 0] = True  # 1/16 elevation loss, but destroys 3x3 metric support.
        return raw
    service = SearchService(provider=provider, index=ContextIndex(), settings=load_settings(project))
    try:
        with pytest.raises(QualityError, match="valid metric pixels"):
            service._prepare("mars", 0, 0, 1, "small ROI")
    finally:
        service.close()


def test_jobs_at_same_coordinates_keep_independent_radius_and_terrain(project):
    service = SearchService(provider=measured_fixture, index=ContextIndex(), settings=load_settings(project))
    with TestClient(create_app(service, serve_frontend=False)) as client:
        small, large = finish(client, 1), finish(client, 10)
        assert small["status"] == large["status"] == "completed"
        assert small["job_id"] != large["job_id"]
        for job, radius in ((small, 1), (large, 10)):
            stored = client.get(job["status_url"]).json()
            terrain = client.get(stored["result"]["target"]["terrain_url"]).json()
            assert stored["request"]["radius_km"] == terrain["radius_km"] == radius
            assert terrain["width"] == round(radius * 2000 / PX)


def test_refinement_cannot_score_mismatched_resolution_or_mask(project):
    service = SearchService(provider=measured_fixture, index=ContextIndex(), settings=load_settings(project))
    try:
        target = service._prepare("mars", 0, 0, 1, "small ROI")
        matcher = PatternMatcher(target["dem"], target["inside"])
        raw = measured_fixture("earth", 35, 45, 21)
        raw["pixel_size_m"] = 30
        with pytest.raises(QualityError, match="common 463 m grid"):
            service._refine(target, matcher, 35, 45, "Earth", raw)
        raw["pixel_size_m"] = PX
        raw["nodata_mask"] = np.zeros((2, 2), dtype=bool)
        with pytest.raises(QualityError, match="mask does not match"):
            service._refine(target, matcher, 35, 45, "Earth", raw)
    finally:
        service.close()


def test_small_radius_refinement_uses_same_metric_support_as_final_grid(project, monkeypatch):
    service = SearchService(provider=measured_fixture, index=ContextIndex(), settings=load_settings(project))
    try:
        target = service._prepare("mars", 0, 0, 1, "small ROI")
        matcher = PatternMatcher(target["dem"], target["inside"])
        original_score = service._score
        scored = []

        def check_support(target, matcher, dem, metrics):
            counts = {key: int(np.isfinite(value).sum()) for key, value in metrics.items()}
            assert counts == {"slope_deg": 4, "relief_m": 16, "tri_m": 4, "roughness_m": 4}
            scored.append(counts)
            return original_score(target, matcher, dem, metrics)

        monkeypatch.setattr(service, "_score", check_support)
        service._refine(target, matcher, 35, 45, "small Earth ROI")
        assert scored
    finally:
        service.close()


def test_real_acquisition_cache_distinguishes_radius_without_upsampling(tmp_path, monkeypatch):
    fetched = []

    def native(grid):
        fetched.append(grid.shape)
        y, x = np.indices(grid.shape)
        values = (x * 10 + y * y).astype("float32")
        return values, grid.transform, grid.crs, {"source": "test-only", "dataset": "cache fixture"}

    monkeypatch.setattr(public_dem, "_mars_window", native)
    results = [public_dem.fetch_roi("mars", -4.49, 137.42, r, cache_dir=tmp_path) for r in (1, 10, 25, 100, 7.25, 1)]
    assert len(fetched) == 5
    keys = [r["provenance"]["cache_key"] for r in results]
    assert len(set(keys)) == 5 and keys[0] == keys[-1]
    for radius, result in zip((1, 10, 25, 100, 7.25, 1), results):
        assert result["dem"].shape == (round(radius * 2000 / PX),) * 2
        assert result["pixel_size_m"] == PX
        assert result["provenance"]["requested_radius_km"] == radius
