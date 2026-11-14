"""Analog Finder: scan a region of Earth for windows whose terrain resembles an approved Mars reference.

Same method as `score`: 25 km windows, local AEQD, 463 m grid, slope/relief/TRI, histogram
intersection on fixed bins, weighted mean. Results are LEADS for human review, not confirmed analogs.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timezone

import numpy as np
import rasterio
from pyproj import Geod
from rasterio.warp import Resampling, reproject

from terramind import __version__, terrain
from terramind.config import METRICS, ConfigError, Settings
from terramind.gate import require_approved
from terramind.raster import read_band
from terramind.regions import Region, fetch_region, get_region, window_centers
from terramind.roi import make_grid
from terramind.similarity import bin_edges, histogram, intersection, weighted_score

METRIC_FILES = {"slope_deg": "slope_463m.tif", "relief_m": "relief_463m.tif", "tri_m": "tri_463m.tif"}
WATER_MAX_FRACTION = 0.05  # windows with more exactly-flat (water-flattened) pixels are excluded
_GEOD = Geod(ellps="WGS84")

LIMITS = [
    "Leads for human review, not confirmed analogs: check satellite imagery, then add a lead as a site and run prepare/approve.",
    "Search data is SRTM GL3 (~90 m) averaged to 463 m; sites use SRTM GL1 (~30 m) averaged to 463 m. Scores can differ slightly.",
    "SRTM flattens lakes and seas; windows with more than 5% exactly-flat pixels are treated as water and excluded.",
    "SRTM dates from February 2000 (e.g. the Aral Sea shoreline of that year).",
    "Shape only: slope, relief and roughness distributions. Nothing about geology, minerals, climate or habitability.",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def satellite_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/@{lat:.5f},{lon:.5f},12z/data=!3m1!1e3"


def _reference_hists(settings: Settings, ref_id: str) -> dict:
    out = {}
    for m in METRICS:
        a = read_band(settings.processed_dir(ref_id) / METRIC_FILES[m])
        out[m] = histogram(a, bin_edges(settings.bins[m]))
    return out


def _spaced_top(rows: list[dict], key: str, n: int, min_sep_km: float) -> list[dict]:
    picked: list[dict] = []
    for r in sorted(rows, key=lambda r: r[key], reverse=True):
        if all(_GEOD.inv(r["lon"], r["lat"], p["lon"], p["lat"])[2] / 1000.0 >= min_sep_km for p in picked):
            picked.append(r)
            if len(picked) == n:
                break
    return picked


def scan(settings: Settings, ref_hists: dict, vrt_path, centers, progress=None) -> list[dict]:
    """Score every window center. Returns one row per window with its status and scores."""
    edges = {m: bin_edges(settings.bins[m]) for m in METRICS}
    rows = []
    t0 = time.time()
    with rasterio.open(vrt_path) as src:
        band = rasterio.band(src, 1)
        for k, (lat, lon) in enumerate(centers, 1):
            grid = make_grid("earth", lat, lon, settings.window_km, settings.grid_m)
            dem = np.full(grid.shape, np.nan, dtype="float32")
            reproject(
                source=band, destination=dem, src_transform=src.transform, src_crs=src.crs,
                src_nodata=src.nodata, dst_transform=grid.transform, dst_crs=grid.crs,
                dst_nodata=np.nan, resampling=Resampling.average,
            )
            valid = int(np.isfinite(dem).sum())
            nodata = 1.0 - valid / dem.size
            row = {"lat": lat, "lon": lon, "valid_pixels": valid, "nodata_fraction": round(nodata, 4)}
            if valid < settings.min_valid_pixels or nodata > settings.max_nodata_fraction:
                row["status"] = "nodata"
                rows.append(row)
                continue
            metrics = {
                "slope_deg": terrain.slope_deg(dem, grid.res_m),
                "relief_m": terrain.local_relief(dem),
                "tri_m": terrain.tri(dem),
            }
            s = metrics["slope_deg"][np.isfinite(metrics["slope_deg"])]
            water = float(np.mean(s == 0.0)) if s.size else 1.0
            row["water_fraction"] = round(water, 4)
            if water > WATER_MAX_FRACTION:
                row["status"] = "water"
                rows.append(row)
                continue
            per = {m: intersection(ref_hists[m], histogram(metrics[m], edges[m])) for m in METRICS}
            row["status"] = "ok"
            row.update({m: round(v, 4) for m, v in per.items()})
            for name, w in settings.weights.items():
                row[f"overall_{name}"] = round(weighted_score(per, w), 4)
            row["slope_median"] = round(float(np.median(s)), 3)
            row["tri_median"] = round(float(np.nanmedian(metrics["tri_m"])), 3)
            rows.append(row)
            if progress and (k % 250 == 0 or k == len(centers)):
                progress(f"scanned {k}/{len(centers)} windows ({time.time() - t0:.0f} s)")
    return rows


def known_sites_in(settings: Settings, region: Region) -> list:
    w, s, e, n = region.bbox
    return [
        site for site in settings.sites.values()
        if site.body == "earth" and site.lat is not None and w <= site.lon <= e and s <= site.lat <= n
    ]


def search(settings: Settings, reference_id: str, region_id: str, api_key: str | None = None,
           session=None, top_n: int = 10, min_sep_km: float | None = None, progress=None) -> dict:
    ref = settings.site(reference_id)
    if ref.body not in ("mars", "moon"):
        raise ConfigError(f"'{reference_id}' is not a Mars or Moon site; the search reference must be one.")
    ref_roi = require_approved(settings, reference_id)
    region = get_region(settings, region_id)
    ref_hists = _reference_hists(settings, reference_id)

    vrt = fetch_region(settings, region, api_key, session=session, progress=progress)
    centers = window_centers(region, settings.window_km)
    if not centers:
        raise ConfigError(f"Region '{region_id}' is smaller than one {settings.window_km:g} km window.")
    rows = scan(settings, ref_hists, vrt, centers, progress=progress)

    weight_names = list(settings.weights)
    key = f"overall_{weight_names[0]}"
    ok = [r for r in rows if r["status"] == "ok"]
    ok_sorted = sorted(ok, key=lambda r: r[key], reverse=True)
    for rank, r in enumerate(ok_sorted, 1):
        r["rank"] = rank
    sep = min_sep_km or settings.window_km
    top = _spaced_top(ok, key, top_n, sep)
    for r in top:
        r["satellite"] = satellite_link(r["lat"], r["lon"])

    known = []
    for site in known_sites_in(settings, region):
        if not ok:
            break
        d = [(_GEOD.inv(site.lon, site.lat, r["lon"], r["lat"])[2], r) for r in ok]
        dist, nearest = min(d, key=lambda x: x[0])
        known.append({
            "site": site.id, "name": site.name, "role": site.role,
            "nearest_window": {"lat": nearest["lat"], "lon": nearest["lon"], "distance_km": round(dist / 1000, 1)},
            "score": nearest[key], "rank": nearest["rank"], "of": len(ok),
            "top_percent": round(100.0 * nearest["rank"] / len(ok), 1),
        })

    scores = np.array([r[key] for r in ok]) if ok else np.array([])
    result = {
        "reference": {"id": ref.id, "name": ref.name, "params_hash": ref_roi["params_hash"]},
        "region": {"id": region.id, "name": region.name, "bbox": list(region.bbox), "note": region.note},
        "method": {
            "data": f"{region.demtype} (OpenTopography), averaged to {settings.grid_m:g} m",
            "window_km": settings.window_km,
            "stride_km": region.stride_km,
            "ranking": f"weight set {weight_names[0]}; top list keeps windows at least {sep:g} km apart",
            "water_rule": f"excluded if more than {WATER_MAX_FRACTION:.0%} of slope pixels are exactly flat",
        },
        "counts": {
            "windows": len(rows),
            "scored": len(ok),
            "water": sum(r["status"] == "water" for r in rows),
            "nodata": sum(r["status"] == "nodata" for r in rows),
        },
        "score_distribution": None if not ok else {
            "max": round(float(scores.max()), 4), "p90": round(float(np.percentile(scores, 90)), 4),
            "median": round(float(np.median(scores)), 4), "min": round(float(scores.min()), 4),
        },
        "top": top,
        "known_sites": known,
        "limits": LIMITS,
        "generated_at": _now(),
        "terramind_version": __version__,
    }

    out = settings.root / "results" / "search" / f"{reference_id}__{region_id}"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "search.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    cols = ["lat", "lon", "status", "rank", key] + [f"overall_{w}" for w in weight_names[1:]] + list(METRICS) + [
        "slope_median", "tri_median", "valid_pixels", "nodata_fraction", "water_fraction"]
    with open(out / "windows.csv", "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        for r in rows:
            wr.writerow(r)
    from terramind.quicklook import search_map

    search_map(out / "map.png", region, vrt, rows, top, known, ref.name, key, settings.window_km)
    result["files"] = [str((out / f).relative_to(settings.root)) for f in ("search.json", "windows.csv", "map.png")]
    return result
