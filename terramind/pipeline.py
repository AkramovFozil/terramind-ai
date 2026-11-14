"""prepare (per site) and score (target vs candidate). No step invents data."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from rasterio.warp import Resampling

from terramind import __version__
from terramind import terrain
from terramind.config import DATASETS, METRICS, ConfigError, QualityError, Settings, Site
from terramind.gate import PENDING, params_hash, require_approved, site_params, write_roi
from terramind.quicklook import histograms, quicklook
from terramind.raster import check_quality, read_band, read_to_grid, write_geotiff
from terramind.roi import geographic_bounds, make_grid
from terramind.similarity import compare_metrics, rank_stability, weighted_score
from terramind.sources.mola import resolve_dem_path
from terramind.sources.opentopo import fetch_srtm, srtm_cache_path

METRIC_FILES = {"slope_deg": "slope_463m.tif", "relief_m": "relief_463m.tif", "tri_m": "tri_463m.tif"}
METRIC_UNITS = {"slope_deg": "degrees", "relief_m": "m", "tri_m": "m"}

MOLA_CAVEAT = (
    "MOLA's 128 px/degree grid near the equator is partly interpolated between orbit tracks, "
    "so roughness (TRI) at Gale may be underestimated."
)
SCOPE_CAVEAT = (
    "The score compares distributions of slope, local relief and roughness only. "
    "It says nothing about geology, mineralogy, climate or habitability."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def map_links(lat: float, lon: float) -> dict:
    return {
        "satellite": f"https://www.google.com/maps/@{lat:.5f},{lon:.5f},12z/data=!3m1!1e3",
        "openstreetmap": f"https://www.openstreetmap.org/#map=12/{lat:.5f}/{lon:.5f}",
    }


def _check_site(site: Site) -> None:
    if site.lat is None or site.lon is None:
        raise ConfigError(
            f"Site '{site.id}' has no center yet (lat/lon is null in config/sites.yaml). "
            "The team must pick and freeze a center before it can be processed."
        )
    if not site.enabled:
        raise ConfigError(f"Site '{site.id}' is disabled (Phase 2). Set enabled: true in config/sites.yaml to process it.")


def prepare(settings: Settings, site_id: str, api_key: str | None = None, session=None) -> dict:
    """Clip + reproject the DEM, compute metrics, write rasters, quick-look and roi.json (pending_review)."""
    site = settings.site(site_id)
    _check_site(site)
    grid = make_grid(site.body, site.lat, site.lon, settings.window_km, settings.grid_m)
    bbox = geographic_bounds(grid, site.body)
    out = settings.processed_dir(site.id)
    dem30 = grid30 = None

    if site.body == "mars":
        src = resolve_dem_path(settings, site)
        dem, src_info = read_to_grid(src, grid, "mars", Resampling.bilinear, f"{site.id} MOLA", settings.root)
    else:
        src = srtm_cache_path(settings, site)
        downloaded = not src.exists()
        fetch_srtm(bbox, src, api_key, session=session)
        dem, src_info = read_to_grid(src, grid, "earth", Resampling.average, f"{site.id} SRTM", settings.root)
        src_info["downloaded_this_run"] = downloaded
        src_info["request_bbox_lonlat"] = [round(v, 6) for v in bbox]

    try:
        quality = check_quality(dem, settings.min_valid_pixels, settings.max_nodata_fraction, site.id)
    except QualityError as exc:
        raise QualityError(f"{exc} Source: {src_info['file']} (longitude domain {src_info['longitude_domain']}).") from None

    if site.body == "earth":
        grid30 = make_grid("earth", site.lat, site.lon, settings.window_km, settings.hazard_grid_m)
        dem30, _ = read_to_grid(src, grid30, "earth", Resampling.bilinear, f"{site.id} SRTM 30 m", settings.root)

    metrics = {
        "slope_deg": terrain.slope_deg(dem, grid.res_m),
        "relief_m": terrain.local_relief(dem),
        "tri_m": terrain.tri(dem),
    }

    files = {"dem": write_geotiff(out / "dem_463m.tif", dem, grid, "elevation (m)")}
    for m, arr in metrics.items():
        files[m] = write_geotiff(out / METRIC_FILES[m], arr, grid, m)
    if dem30 is not None:
        files["dem_30m"] = write_geotiff(out / "dem_30m.tif", dem30, grid30, "elevation (m), hazard-map grid")

    links = map_links(site.lat, site.lon) if site.body == "earth" else None
    files["quicklook"] = quicklook(out / "quicklook.png", site, dem, grid, bbox, dem30, grid30, links)

    params = site_params(settings, site)
    ds = DATASETS[site.dataset]
    roi = {
        "site": {
            "id": site.id, "name": site.name, "body": site.body, "role": site.role,
            "provisional": site.provisional, "note": site.note,
        },
        "status": PENDING,
        "prepared_at": _now(),
        "approved_at": None,
        "params": params,
        "prepared_params_hash": params_hash(params),
        "params_hash": None,
        "grid": {
            "crs": grid.crs_string, "pixel_m": grid.res_m, "width": grid.width, "height": grid.height,
            "extent_m": [-grid.half_extent_m, -grid.half_extent_m, grid.half_extent_m, grid.half_extent_m],
            "bbox_lonlat": [round(v, 6) for v in bbox],
        },
        "quality": quality,
        "input": {"dataset_id": site.dataset, **{k: v for k, v in ds.items() if k != "body"}, **src_info},
        "metric_summary": {m: terrain.summary(a) for m, a in metrics.items()},
        "files": {k: str(Path(v).relative_to(settings.root)) for k, v in files.items()},
        "map_links": links,
        "terramind_version": __version__,
    }
    if dem30 is not None:
        roi["hazard_grid"] = {"crs": grid30.crs_string, "pixel_m": grid30.res_m, "width": grid30.width, "height": grid30.height}
    write_roi(settings, site.id, roi)
    return roi


def score(settings: Settings, target_id: str, candidate_id: str) -> dict:
    """Compare two APPROVED sites. Writes metrics.json, comparison.csv and histograms.png."""
    if target_id == candidate_id:
        raise ConfigError("Target and candidate must be different sites.")
    roi_t = require_approved(settings, target_id)
    roi_c = require_approved(settings, candidate_id)
    target, candidate = settings.site(target_id), settings.site(candidate_id)

    arrays = {}
    for key, sid in (("target", target_id), ("candidate", candidate_id)):
        arrays[key] = {m: read_band(settings.processed_dir(sid) / METRIC_FILES[m]) for m in METRICS}

    comparison = compare_metrics(arrays["target"], arrays["candidate"], {m: settings.bins[m] for m in METRICS})
    per_metric_scores = {m: comparison[m]["score"] for m in METRICS}
    overall = {
        name: {"weights": w, "score": round(weighted_score(per_metric_scores, w), 4)}
        for name, w in settings.weights.items()
    }

    caveats = [SCOPE_CAVEAT]
    if "mars" in (target.body, candidate.body):
        caveats.append(MOLA_CAVEAT)
    for s in (target, candidate):
        if s.provisional:
            caveats.append(f"{s.name}: the center is PROVISIONAL; the score may change when the team freezes it.")

    def site_block(s: Site, roi: dict) -> dict:
        return {
            "id": s.id, "name": s.name, "body": s.body, "role": s.role, "center": [s.lat, s.lon],
            "provisional": s.provisional, "params_hash": roi["params_hash"], "approved_at": roi["approved_at"],
            "valid_pixels": roi["quality"]["valid_pixels"], "nodata_fraction": roi["quality"]["nodata_fraction"],
            "dataset": roi["input"]["name"],
        }

    per_metric = {}
    for m in METRICS:
        r = comparison[m]
        per_metric[m] = {
            "score": round(r["score"], 4),
            "unit": METRIC_UNITS[m],
            "target": {**terrain.summary(arrays["target"][m]),
                       "below_range": round(float(r["p_target"][0]), 4), "above_range": round(float(r["p_target"][-1]), 4)},
            "candidate": {**terrain.summary(arrays["candidate"][m]),
                          "below_range": round(float(r["p_candidate"][0]), 4), "above_range": round(float(r["p_candidate"][-1]), 4)},
        }

    result = {
        "target": site_block(target, roi_t),
        "candidate": site_block(candidate, roi_c),
        "method": {
            "grid_m": settings.grid_m,
            "window_km": settings.window_km,
            "metrics": {
                "slope_deg": "Horn (1981) 3x3 slope, degrees",
                "relief_m": "elevation minus ROI median elevation, metres",
                "tri_m": "mean absolute difference to the 8 neighbours, metres",
            },
            "similarity": "histogram intersection on fixed bins from config/metrics.yaml, with under/overflow bins; 0 = no overlap, 1 = identical",
            "bins": {m: settings.bins[m] for m in METRICS},
            "overall": "weighted mean of the three metric scores, weights normalised by their sum",
        },
        "per_metric": per_metric,
        "overall": overall,
        "rank_stability": {
            "spearman_rho": None,
            "reason": "Needs at least 3 approved candidates (Phase 2). Implemented and unit-tested.",
        },
        "caveats": caveats,
        "generated_at": _now(),
        "terramind_version": __version__,
    }

    out = settings.results_dir(target_id, candidate_id)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    _write_csv(out / "comparison.csv", per_metric, overall)
    histograms(out / "histograms.png", comparison, target, candidate)
    result["files"] = [str((out / f).relative_to(settings.root)) for f in ("metrics.json", "comparison.csv", "histograms.png")]
    return result


def _write_csv(path: Path, per_metric: dict, overall: dict) -> None:
    cols = ["row", "unit", "score", "target_p5", "target_median", "target_p95",
            "candidate_p5", "candidate_median", "candidate_p95"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for m, r in per_metric.items():
            t, c = r["target"], r["candidate"]
            w.writerow([m, r["unit"], r["score"], t["p5"], t["median"], t["p95"], c["p5"], c["median"], c["p95"]])
        for name, o in overall.items():
            w.writerow([f"overall_{name}", "", o["score"], "", "", "", "", "", ""])


def ranking_stability(scores_a: dict, scores_b: dict) -> float:
    """Spearman rho between the A and B rankings of >= 3 candidates (Phase 2 entry point)."""
    return rank_stability(scores_a, scores_b)
