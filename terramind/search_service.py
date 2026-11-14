"""Global Earth search for the terrain that best matches a chosen Mars region.

There is no fixed candidate list. A search runs in three stages:

1. Mars: the 25 km radius circle is measured on real USGS MOLA at 463 m.
2. Screening: every land window on Earth (global ETOPO index, ~28 km lattice,
   see terramind.global_index) is scored against the Mars circle with the
   rotation-invariant shape descriptor plus slope / relief / TRI overlap.
   The best distinct places (at least MIN_SEPARATION_KM apart) go on.
3. Precise match: for each of them a larger Copernicus GLO-30 area is measured
   at 463 m and the 25 km circle is slid across it (+-REFINE_SHIFT_KM) to the
   centre that best overlays the Mars landform. The circle at that refined
   centre is then fetched and scored with the full method.

Score (0-100) = SHAPE_WEIGHT x pattern correlation (Mars relief map rotated and
mirrored over the Earth relief map) + (1 - SHAPE_WEIGHT) x the weighted
histogram overlap of slope, relief and TRI. Results are automated and
unreviewed; the CLI's human approval gate is unchanged.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Callable
from uuid import uuid4
import math

import numpy as np
from pyproj import Transformer

from terramind import global_index, terrain
from terramind.config import METRICS, MissingInputError, QualityError, Settings, load_settings
from terramind.crs import local_crs_string
from terramind.raster import check_quality
from terramind.shape import PatternMatcher
from terramind.similarity import compare_metrics, histogram, intersection, rank_stability, weighted_score

MARS_PRESETS = [
    {"id": "gale", "name": "Gale Crater", "lat": -4.49, "lon": 137.42},
    {"id": "jezero", "name": "Jezero Crater", "lat": 18.38, "lon": 77.58},
    {"id": "oxia", "name": "Oxia Planum", "lat": 18.20, "lon": -24.34},
    {"id": "valles", "name": "Valles Marineris", "lat": -12.0, "lon": -70.0},
]
RADIUS_KM = 25
SHAPE_WEIGHT = 0.5
SCREEN_CANDIDATES = 12
MIN_SEPARATION_KM = 150
REFINE_RADIUS_KM = 45
REFINE_SHIFT_KM = 20
COARSE_STEP_PX = 6
FINE_STEP_PX = 2
MAX_WATER_FRACTION = 0.10
FETCH_WORKERS = 6
MAX_REFINE_PASSES = 3
# TRI rises on any slope, so two places can share a TRI histogram while one is smooth and the
# other broken. Detrended roughness (terrain.roughness) is scored separately for that reason.
ROUGHNESS_WEIGHT = 0.3
ROUGHNESS_EDGES = np.arange(0.0, 50.0 + 1e-9, 0.25)
SCOPE = ("Global search over Earth's land (56 S - 80 N) on a ~28 km lattice of 25 km circles; "
         "the best places are re-measured on Copernicus GLO-30 and their centres refined at 463 m.")
REVIEW = {
    "status": "automated_quality_screened_unreviewed",
    "human_approved": False,
    "cli_approval_gate": "unchanged",
    "adaptation": "Exploratory API uses a circular 25 km radius ROI and automatic quality filters. The CLI retains its separate human approval gate and configured square windows.",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default_provider(body, lat, lon, radius_km, grid_m=463):
    from terramind.sources.public_dem import fetch_roi
    return fetch_roi(body, lat, lon, radius_km, grid_m=grid_m)


def _default_index():
    return global_index.EarthIndex.load()


class SearchBusyError(RuntimeError):
    pass


class TerrainNotReadyError(RuntimeError):
    pass


def _circle(n: int, pixel: float, radius_km: float) -> np.ndarray:
    c = (np.arange(n) + 0.5 - n / 2) * pixel
    return c[None, :] ** 2 + c[:, None] ** 2 <= (radius_km * 1000) ** 2


def _water_fraction(dem: np.ndarray, inside: np.ndarray) -> float:
    """Open water is exactly flat in Copernicus (sea = 0 m, lakes = one level)."""
    flat = terrain.tri(dem) < 0.01
    return float(flat[inside].mean())


class SearchService:
    def __init__(self, provider: Callable | None = None, index=None, index_loader: Callable | None = None,
                 settings: Settings | None = None, max_workers: int = 1,
                 max_pending: int = 4, max_jobs: int = 24, screen_candidates: int = SCREEN_CANDIDATES):
        self.settings = settings or load_settings(Path(__file__).resolve().parents[1])
        self.provider = provider or _default_provider
        self._index = index
        self._index_loader = index_loader or _default_index
        self.screen_candidates = screen_candidates
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="terramind-search")
        self._lock = RLock()
        self._jobs: OrderedDict[str, dict] = OrderedDict()
        self._terrain: dict[str, dict[str, dict]] = {}
        self._max_pending = max_pending
        self._max_jobs = max_jobs

    def close(self):
        self._pool.shutdown(wait=True, cancel_futures=True)

    # ------------------------------------------------------------------ index
    def index(self):
        with self._lock:
            if self._index is None:
                try:
                    self._index = self._index_loader()
                except FileNotFoundError as exc:
                    raise QualityError(f"{exc}. Build it once with: python -m terramind build-index") from None
            return self._index

    def index_status(self) -> dict:
        try:
            idx = self.index()
            return {"ready": True, "windows": len(idx), "meta": {k: idx.meta.get(k) for k in ("version", "built_at", "lat_range", "lat_step_deg", "pixel_m")}}
        except Exception as exc:
            return {"ready": False, "reason": str(exc)[:400]}

    def catalog(self) -> dict:
        status = self.index_status()
        return {
            "mars_presets": deepcopy(MARS_PRESETS),
            "earth_candidates": [],
            "radius_km": {"default": RADIUS_KM, "allowed": [RADIUS_KM]},
            "grid_m": self.settings.grid_m,
            "coverage": {"kind": "global_land_search", "global_search": True, "index": status, "description": SCOPE},
            "quality_thresholds": {"min_valid_pixels": 2500, "max_nodata_fraction": 0.10, "max_water_fraction": MAX_WATER_FRACTION},
            "review": deepcopy(REVIEW),
            "sources": {"mars": "USGS MGS MOLA DEM", "earth_screening": "NOAA ETOPO 2022 60 arc-second",
                        "earth": "Copernicus DEM GLO-30 DSM (includes surface features)"},
            "method": self._method(),
        }

    def _method(self) -> dict:
        return {
            "grid_m": self.settings.grid_m,
            "roi_shape": "circle", "radius_km": RADIUS_KM,
            "projection": "Body-specific local azimuthal equidistant (AEQD)",
            "search": {"coverage": SCOPE, "screen_candidates": self.screen_candidates, "min_separation_km": MIN_SEPARATION_KM,
                       "refine_shift_km": REFINE_SHIFT_KM, "screen_pixel_m": global_index.SCREEN_PIXEL_M},
            "metrics": {"shape": "Best Pearson correlation of relief maps, Mars rotated every 15 degrees and mirrored",
                        "slope_deg": "Horn (1981) 3x3 slope in degrees", "relief_m": "Elevation minus circular ROI median, metres",
                        "tri_m": "Mean absolute elevation difference to eight neighbours, metres",
                        "roughness_m": "RMS residual from the best-fit 3x3 plane (slope removed), metres"},
            "similarity": (f"{SHAPE_WEIGHT:g} x shape correlation + {1 - SHAPE_WEIGHT:g} x distribution overlap, where distribution = "
                           f"{1 - ROUGHNESS_WEIGHT:g} x weighted slope/relief/TRI histogram intersection + {ROUGHNESS_WEIGHT:g} x detrended-roughness intersection; 0-100"),
            "roughness_weight": ROUGHNESS_WEIGHT,
            "shape_weight": SHAPE_WEIGHT,
            "bins": deepcopy(self.settings.bins), "weights": deepcopy(self.settings.weights),
            "ranking_weights": self._primary(),
            "interpretation": "Terrain-shape similarity, not a probability, confidence, geological equivalence or landing-safety score.",
        }

    def _primary(self) -> str:
        return "A" if "A" in self.settings.weights else next(iter(self.settings.weights))

    # ------------------------------------------------------------------ jobs
    def submit(self, lat: float, lon: float, radius_km: float = RADIUS_KM) -> dict:
        if not all(math.isfinite(v) for v in (lat, lon, radius_km)) or not -85 <= lat <= 85 or not -180 <= lon <= 180 or radius_km != RADIUS_KM:
            raise ValueError("Latitude must be -85..85, longitude -180..180, and radius_km must be 25")
        with self._lock:
            pending = sum(j["status"] in ("queued", "running") for j in self._jobs.values())
            if pending >= self._max_pending:
                raise SearchBusyError("Search queue is full. Wait for a running search to finish.")
            while len(self._jobs) >= self._max_jobs:
                expired = next((key for key, value in self._jobs.items() if value["status"] in ("completed", "failed")), None)
                if expired is None:
                    raise SearchBusyError("Search capacity reached. Try again shortly.")
                del self._jobs[expired]
                self._terrain.pop(expired, None)
            job_id = uuid4().hex
            self._jobs[job_id] = {
                "job_id": job_id, "status": "queued", "progress": 0,
                "message": "Waiting for DEM analysis worker", "created_at": _now(),
                "request": {"lat": lat, "lon": lon, "radius_km": radius_km},
                "status_url": f"/api/search/{job_id}",
            }
            self._terrain[job_id] = {}
            self._pool.submit(self._run, job_id, lat, lon, radius_km)
            return {k: self._jobs[job_id][k] for k in ("job_id", "status", "status_url")}

    def get_job(self, job_id: str) -> dict:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return deepcopy(self._jobs[job_id])

    def _update(self, job_id: str, **values):
        with self._lock:
            self._jobs[job_id].update(values)

    # ------------------------------------------------------------------ measuring
    def _prepare(self, body: str, lat: float, lon: float, radius_km: float, name: str) -> dict:
        raw = self.provider(body, lat, lon, radius_km, grid_m=self.settings.grid_m)
        dem = np.array(raw["dem"], dtype="float32", copy=True)
        if dem.ndim != 2 or min(dem.shape) < 3:
            raise QualityError(f"{name}: DEM must be a two-dimensional grid")
        pixel = float(raw["pixel_size_m"])
        if not math.isfinite(pixel) or not math.isclose(pixel, self.settings.grid_m, rel_tol=1e-6):
            raise QualityError(f"{name}: DEM must use the common {self.settings.grid_m:g} m grid")
        if raw.get("nodata_mask") is not None:
            mask = np.asarray(raw["nodata_mask"], dtype=bool)
            if mask.shape != dem.shape:
                raise QualityError(f"{name}: nodata mask does not match DEM")
            dem[mask] = np.nan
        dem[~np.isfinite(dem)] = np.nan
        height, width = dem.shape
        if width * pixel < radius_km * 2000 - pixel or height * pixel < radius_km * 2000 - pixel:
            raise QualityError(f"{name}: DEM does not cover the requested circle")
        x = (np.arange(width) + 0.5 - width / 2) * pixel
        y = (height / 2 - np.arange(height) - 0.5) * pixel
        inside = y[:, None] ** 2 + x[None, :] ** 2 <= (radius_km * 1000) ** 2
        quality = check_quality(dem[inside], 2500, 0.10, name)
        if body == "earth":
            water = _water_fraction(dem, inside)
            if water > MAX_WATER_FRACTION:
                raise QualityError(f"{name}: {water:.0%} of the circle is open water (flat sea or lake surface)")
            quality["water_fraction"] = round(water, 4)
        circle_dem = np.where(inside, dem, np.nan)
        metrics = {"slope_deg": terrain.slope_deg(dem, pixel), "relief_m": terrain.local_relief(circle_dem), "tri_m": terrain.tri(dem),
                   "roughness_m": terrain.roughness(dem)}
        for key, values in metrics.items():
            values[~inside] = np.nan
            valid = int(np.isfinite(values).sum())
            if valid < 2500:
                raise QualityError(f"{name}: {key} has {valid} valid metric pixels; minimum is 2500")
        quality.update({"passed": True, "roi_shape": "circle", "outside_roi_pixels": int(dem.size - inside.sum()), "metric_valid_pixels": {m: int(np.isfinite(v).sum()) for m, v in metrics.items()}})
        provenance = deepcopy(raw.get("provenance") or {})
        if not provenance.get("source") or not provenance.get("dataset"):
            raise QualityError(f"{name}: DEM source provenance is missing")
        return {"dem": dem, "inside": inside, "metrics": metrics, "pixel_size_m": pixel,
                "bounds": deepcopy(raw.get("bounds")), "crs": raw.get("crs"),
                "projected_bounds_m": raw.get("projected_bounds_m", [-width * pixel / 2, -height * pixel / 2, width * pixel / 2, height * pixel / 2]),
                "quality": quality, "provenance": provenance, "lat": lat, "lon": lon,
                "radius_km": radius_km, "body": body,
                "summary": {m: terrain.summary(v) for m, v in metrics.items()}}

    def _score(self, target: dict, matcher: PatternMatcher, dem: np.ndarray, metrics: dict) -> dict:
        """Full score of one Earth circle (arrays on the target's grid shape)."""
        comparison = compare_metrics(target["metrics"], metrics, self.settings.bins)
        dist = {m: comparison[m]["score"] for m in METRICS}
        shape_score, match = matcher.score(dem)
        rough = intersection(histogram(target["metrics"]["roughness_m"], ROUGHNESS_EDGES), histogram(metrics["roughness_m"], ROUGHNESS_EDGES))
        overall = {name: SHAPE_WEIGHT * shape_score + (1 - SHAPE_WEIGHT) * ((1 - ROUGHNESS_WEIGHT) * weighted_score(dist, w) + ROUGHNESS_WEIGHT * rough)
                   for name, w in self.settings.weights.items()}
        return {"overall": overall, "dist": dist, "roughness": rough, "shape": shape_score, "match": match, "comparison": comparison}

    def _screen_target(self, target: dict) -> dict:
        factor = global_index.SCREEN_FACTOR
        coarse = global_index.block_average(np.where(target["inside"], target["dem"], np.nan), factor)
        n = coarse.shape[0]
        c = np.arange(n) - (n - 1) / 2
        radius_px = target["radius_km"] * 1000 / global_index.SCREEN_PIXEL_M
        inside = (c[None, :] ** 2 + c[:, None] ** 2 <= radius_px ** 2) & np.isfinite(coarse)
        return global_index.describe_window(coarse, inside)

    def _fetch_area(self, lat: float, lon: float) -> dict:
        return self.provider("earth", lat, lon, REFINE_RADIUS_KM, grid_m=self.settings.grid_m)

    def _refine(self, target: dict, matcher: PatternMatcher, lat: float, lon: float, name: str, raw: dict | None = None) -> dict:
        """Slide the circle over a larger real DEM and return the best centre (lat, lon) and its score."""
        raw = raw if raw is not None else self._fetch_area(lat, lon)
        big = np.array(raw["dem"], dtype="float32", copy=True)
        if raw.get("nodata_mask") is not None:
            big[np.asarray(raw["nodata_mask"], dtype=bool)] = np.nan
        big[~np.isfinite(big)] = np.nan
        pixel = float(raw["pixel_size_m"])
        n = target["dem"].shape[0]
        if big.shape[0] < n or big.shape[1] < n:
            raise QualityError(f"{name}: refinement window is smaller than the analysis circle")
        inside = target["inside"]
        slope = terrain.slope_deg(big, pixel)
        tri = terrain.tri(big)
        rough = terrain.roughness(big)
        base_r, base_c = (big.shape[0] - n) // 2, (big.shape[1] - n) // 2
        reach = min(int(REFINE_SHIFT_KM * 1000 / pixel), base_r, base_c, big.shape[0] - n - base_r, big.shape[1] - n - base_c)
        primary = self._primary()
        cache: dict[tuple[int, int], float] = {}

        def evaluate(oy: int, ox: int) -> float:
            if (oy, ox) in cache:
                return cache[(oy, ox)]
            r0, c0 = base_r + oy, base_c + ox
            sub = big[r0:r0 + n, c0:c0 + n]
            value = -1.0
            vals = sub[inside]
            if np.isfinite(vals).mean() >= 0.9 and (tri[r0:r0 + n, c0:c0 + n][inside] < 0.01).mean() <= MAX_WATER_FRACTION:
                circle = np.where(inside, sub, np.nan)
                metrics = {"slope_deg": np.where(inside, slope[r0:r0 + n, c0:c0 + n], np.nan),
                           "relief_m": circle - np.nanmedian(circle),
                           "tri_m": np.where(inside, tri[r0:r0 + n, c0:c0 + n], np.nan),
                           "roughness_m": np.where(inside, rough[r0:r0 + n, c0:c0 + n], np.nan)}
                value = self._score(target, matcher, circle, metrics)["overall"][primary]
            cache[(oy, ox)] = value
            return value

        offsets = range(-(reach // COARSE_STEP_PX) * COARSE_STEP_PX, reach + 1, COARSE_STEP_PX)
        best = max(((oy, ox) for oy in offsets for ox in offsets), key=lambda o: evaluate(*o))
        for step in (FINE_STEP_PX, 1):
            centre = best
            for dy in (-2 * step, -step, 0, step, 2 * step):
                for dx in (-2 * step, -step, 0, step, 2 * step):
                    oy, ox = centre[0] + dy, centre[1] + dx
                    if abs(oy) <= reach and abs(ox) <= reach and evaluate(oy, ox) > evaluate(*best):
                        best = (oy, ox)
        if evaluate(*best) < 0:
            raise QualityError(f"{name}: no water-free circle with valid data near this place")
        # Grid centre shift -> metres in the local AEQD (rows grow southwards) -> lat/lon.
        x_m = (best[1] + (base_c + n / 2) - big.shape[1] / 2) * pixel
        y_m = -(best[0] + (base_r + n / 2) - big.shape[0] / 2) * pixel
        to_geo = Transformer.from_crs(local_crs_string("earth", lat, lon), "EPSG:4326", always_xy=True)
        new_lon, new_lat = to_geo.transform(x_m, y_m)
        return {"lat": round(float(new_lat), 5), "lon": round(float(new_lon), 5),
                "shift_km": round(math.hypot(x_m, y_m) / 1000, 2), "positions_tested": len(cache),
                "refine_score": round(evaluate(*best) * 100, 4)}

    def _site(self, job_id: str, site_id: str, name: str, prepared: dict) -> dict:
        with self._lock:
            self._terrain[job_id][site_id] = prepared
        return {"id": site_id, "name": name, "body": prepared["body"], "lat": prepared["lat"], "lon": prepared["lon"],
                "center": {"lat": prepared["lat"], "lon": prepared["lon"]}, "radius_km": prepared["radius_km"],
                "summary": prepared["summary"], "quality": prepared["quality"],
                "provenance": prepared["provenance"], "review": deepcopy(REVIEW),
                "terrain_url": f"/api/terrain?job_id={job_id}&site_id={site_id}"}

    # ------------------------------------------------------------------ search
    def _run(self, job_id: str, lat: float, lon: float, radius_km: float):
        try:
            self._update(job_id, status="running", progress=2, message="Fetching real Mars MOLA elevation data", started_at=_now())
            target = self._prepare("mars", lat, lon, radius_km, "Mars ROI")
            target_site = self._site(job_id, "target", "Selected Mars ROI", target)
            self._update(job_id, progress=8, message="Screening every land window on Earth", target=target_site)

            index = self.index()
            screen = index.screen(self._screen_target(target), self.settings.weights[self._primary()], SHAPE_WEIGHT)
            picks = global_index.pick_spread(index.lat, index.lon, screen, self.screen_candidates, MIN_SEPARATION_KM)
            if not picks:
                raise QualityError("The global index returned no land windows to compare")
            screened = [{"lat": float(index.lat[i]), "lon": float(index.lon[i]), "screen_score": round(float(screen[i]) * 100, 2)} for i in picks]
            self._update(job_id, progress=12, screened_windows=len(index), shortlisted=deepcopy(screened),
                         message=f"Screened {len(index):,} Earth windows; measuring the best {len(screened)} at 463 m")

            matcher = PatternMatcher(target["dem"], target["inside"])
            primary = self._primary()

            def measure(i: int, cand: dict) -> dict:
                """Refine one shortlisted place and score its circle. Runs in a worker thread."""
                label = f"Earth place {i + 1}"
                refined = self._refine(target, matcher, cand["lat"], cand["lon"], label)
                first_shift, passes = refined["shift_km"], 1
                # The best centre sat on the edge of the searched area: search again around it.
                while refined["shift_km"] >= 0.75 * REFINE_SHIFT_KM and passes < MAX_REFINE_PASSES:
                    again = self._refine(target, matcher, refined["lat"], refined["lon"], label)
                    passes += 1
                    if again["refine_score"] <= refined["refine_score"]:
                        break
                    refined = again
                refined = dict(refined, passes=passes, shift_km=round(_distance_km(refined, cand), 2), first_pass_shift_km=first_shift)
                prepared = self._prepare("earth", refined["lat"], refined["lon"], radius_km, label)
                s = self._score(target, matcher, np.where(prepared["inside"], prepared["dem"], np.nan), prepared["metrics"])
                site = self._site(job_id, f"place-{i + 1}", label, prepared)
                overall = {k: round(v * 100, 4) for k, v in s["overall"].items()}
                metric_scores = {"shape": round(s["shape"] * 100, 4), **{m: round(v * 100, 4) for m, v in s["dist"].items()},
                                 "roughness_m": round(s["roughness"] * 100, 4)}
                site.update({"score": overall[primary], "metric_scores": metric_scores, "overall": overall,
                             "match": s["match"], "screen": cand, "refinement": refined, "found_by": "global_search",
                             "histograms": {m: {"edges": c["edges"].tolist(), "target": c["p_target"].tolist(), "candidate": c["p_candidate"].tolist()} for m, c in s["comparison"].items()}})
                return site

            # Network-bound: measure the shortlisted places in parallel. A place whose download
            # failed is tried once more at the end; tiles that did arrive are already cached.
            measured, excluded, done = [], [], 0
            pending = list(enumerate(screened))
            for attempt in (1, 2):
                retry = []
                with ThreadPoolExecutor(max_workers=FETCH_WORKERS, thread_name_prefix="terramind-place") as pool:
                    futures = {pool.submit(measure, i, c): (i, c) for i, c in pending}
                    for future in as_completed(futures):
                        i, cand = futures[future]
                        try:
                            measured.append(future.result())
                        except MissingInputError as exc:
                            if attempt == 1:
                                retry.append((i, cand))
                                continue
                            excluded.append({"id": f"place-{i + 1}", "name": f"Earth place {i + 1}", "reason": str(exc)[:600], "error_type": type(exc).__name__})
                        except Exception as exc:
                            excluded.append({"id": f"place-{i + 1}", "name": f"Earth place {i + 1}", "reason": str(exc)[:600], "error_type": type(exc).__name__})
                        done += 1
                        self._update(job_id, progress=12 + round(85 * done / len(screened)), compared_candidates=len(measured),
                                     excluded_candidates=deepcopy(excluded),
                                     message=f"Measured {done}/{len(screened)} places on Copernicus 463 m")
                pending = retry
                if not pending:
                    break
                self._update(job_id, message=f"Connection dropped; retrying {len(pending)} places")
            ranked = []
            for site in sorted(measured, key=lambda row: (-row["score"], row["id"])):
                if any(_distance_km(site, kept) < 30 for kept in ranked):
                    excluded.append({"id": site["id"], "name": site["name"], "reason": "Refined centre duplicates a better place", "error_type": "Duplicate"})
                    continue
                ranked.append(site)
            if not ranked:
                network = sum("internet" in e["reason"].lower() or "could not be fetched" in e["reason"].lower() for e in excluded)
                hint = (" Most failures were downloads: check the internet connection and run the search again (finished downloads are cached)."
                        if network >= len(excluded) / 2 else "")
                raise QualityError(f"No shortlisted Earth place could be measured on real Copernicus data.{hint} "
                                   f"First reason: {excluded[0]['reason'][:300] if excluded else 'none'}")
            ranked.sort(key=lambda row: (-row["score"], row["id"]))
            for i, site in enumerate(ranked, 1):
                site["rank"] = i
                site["name"] = f"Earth analog #{i}"
            stability = {"spearman_rho": None, "reason": "At least three scored places and two weight sets are required."}
            names = list(self.settings.weights)
            if len(ranked) >= 3 and len(names) >= 2:
                a = {r["id"]: r["overall"][names[0]] for r in ranked}
                b = {r["id"]: r["overall"][names[1]] for r in ranked}
                if len(set(a.values())) > 1 and len(set(b.values())) > 1:
                    rho = rank_stability(a, b)
                    stability = {"spearman_rho": round(rho, 4) if math.isfinite(rho) else None, "weight_sets": names[:2]}
            best = ranked[0]
            ms = best["metric_scores"]
            explanation = {"type": "computed", "engine": "deterministic_metric_summary", "llm_used": False,
                           "text": (f"The best match found anywhere on Earth's land is at {best['lat']:.4f}, {best['lon']:.4f} "
                                    f"with {best['score']:.1f}/100. The Mars relief map overlays it with correlation "
                                    f"{best['match']['correlation']:.2f} (rotated {best['match']['rotation_deg']} degrees"
                                    f"{', mirrored' if best['match']['mirrored'] else ''}); slope overlap {ms['slope_deg']:.1f}, "
                                    f"relative elevation {ms['relief_m']:.1f}, TRI {ms['tri_m']:.1f}, detrended roughness {ms['roughness_m']:.1f}. "
                                    "This compares surface shape only, not geology or mission safety.")}
            result = {"target": target_site, "candidates": ranked, "excluded_candidates": excluded,
                      "coverage": {"kind": "global_land_search", "global_search": True, "screened_windows": len(index),
                                   "shortlisted": len(screened), "evaluated_count": len(ranked), "excluded_count": len(excluded),
                                   "catalog_count": len(screened), "description": SCOPE},
                      "method": self._method(), "review": deepcopy(REVIEW), "rank_stability": stability,
                      "explanation": explanation, "generated_at": _now(),
                      "caveats": [SCOPE,
                                  "Screening uses ETOPO 2022 at ~1.85 km; a place the screen ranks low is not re-measured.",
                                  "MOLA interpolates between orbit tracks; some roughness is unresolved at 463 m.",
                                  "Copernicus GLO-30 is a digital surface model; vegetation and buildings may affect elevation.",
                                  "Exploratory results have not passed human scientific review."]}
            self._update(job_id, status="completed", progress=100,
                         message=f"Searched {len(index):,} Earth windows; {len(ranked)} places measured precisely", result=result, completed_at=_now())
        except Exception as exc:
            self._update(job_id, status="failed", progress=100, message="Search stopped; no synthetic replacement data was used", error=str(exc)[:1000], error_type=type(exc).__name__, completed_at=_now())

    def get_terrain(self, job_id: str, site_id: str) -> dict:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            prepared = self._terrain[job_id].get(site_id)
            if prepared is None:
                raise TerrainNotReadyError("Terrain is not available for this site; wait for its DEM or inspect the job error.")
            dem = prepared["dem"]
            height, width = dem.shape
            inside = prepared["inside"]

            def flat(array, digits=2):
                return [round(float(v), digits) if math.isfinite(float(v)) else None for v in np.asarray(array).flat]

            values = flat(dem)
            rough = prepared["metrics"]["roughness_m"]
            slope = prepared["metrics"]["slope_deg"]
            layers = {"slope_deg": flat(slope, 3), "roughness_m": flat(rough, 3)}
            stats = {name: terrain.summary(np.where(inside, layer, np.nan)) for name, layer in (("slope_deg", slope), ("roughness_m", rough))}
            median = float(np.nanmedian(dem[inside]))
            return {"site_id": site_id, "body": prepared["body"], "width": width, "height": height,
                    "elevations": values, "roi_mask": inside.ravel().tolist(),
                    "layers": layers, "layer_stats": stats, "median_elevation_m": median,
                    "layer_notes": {"roughness_m": "RMS residual from the best-fit 3x3 plane (slope removed), metres",
                                    "slope_deg": "Horn (1981) slope, degrees"},
                    "pixel_size_m": prepared["pixel_size_m"], "units": "metres", "row_order": "north_to_south", "column_order": "west_to_east",
                    "center": {"lat": prepared["lat"], "lon": prepared["lon"]}, "radius_km": prepared["radius_km"],
                    "bounds": prepared["bounds"], "projected_bounds_m": prepared["projected_bounds_m"], "crs": prepared["crs"],
                    "min_elevation_m": float(np.nanmin(dem)), "max_elevation_m": float(np.nanmax(dem)),
                    "roi_min_elevation_m": float(np.nanmin(dem[inside])), "roi_max_elevation_m": float(np.nanmax(dem[inside])),
                    "quality": deepcopy(prepared["quality"]), "provenance": deepcopy(prepared["provenance"]),
                    "measured_dem": True, "vertical_exaggeration": 1}


def _distance_km(a: dict, b: dict) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(h, 1.0)))
