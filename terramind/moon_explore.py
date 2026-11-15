"""Moon explorer: pick any point on the LOLA south-pole map, see its measured 25 km window, scan Earth for it.

Exploration mode: the point is NOT a reviewed/approved site (the approved reference is Mons Mouton). Results are
labelled as such and are not saved as a reference. Everything is computed from the LOLA file and the cached SRTM
region mosaic with the same metrics, grid and scoring as the Analog Finder.
"""

from __future__ import annotations

import numpy as np

from terramind.config import ConfigError, MissingInputError, Settings

MOON_SITE = "mouton"  # the site whose dataset entry points at the LOLA south-pole file


def _lola(settings: Settings):
    from terramind.sources.mola import resolve_dem_path

    return resolve_dem_path(settings, settings.site(MOON_SITE))


def _frame(settings: Settings):
    import rasterio
    from pyproj import Transformer

    from terramind.crs import MOON_GEOGRAPHIC

    with rasterio.open(_lola(settings)) as src:
        b, wkt = src.bounds, src.crs.to_wkt()
    return b, Transformer.from_crs(wkt, MOON_GEOGRAPHIC, always_xy=True), Transformer.from_crs(MOON_GEOGRAPHIC, wkt, always_xy=True)


def _marker(settings: Settings, b, x: float, y: float) -> dict:
    w, h, half = b.right - b.left, b.top - b.bottom, settings.window_km * 500.0
    return {"marker": {"x": (x - b.left) / w, "y": (b.top - y) / h},
            "box": {"x0": (x - half - b.left) / w, "y0": (b.top - (y + half)) / h,
                    "x1": (x + half - b.left) / w, "y1": (b.top - (y - half)) / h}}


def pick(settings: Settings, fx: float, fy: float) -> dict:
    """Map fraction (0..1 from the left/top of the polar image) -> lat/lon of the window centre."""
    b, to_geo, _ = _frame(settings)
    half = settings.window_km * 500.0
    x = b.left + fx * (b.right - b.left)
    y = b.top - fy * (b.top - b.bottom)
    if not (b.left + half <= x <= b.right - half and b.bottom + half <= y <= b.top - half):
        raise ConfigError("Bu nuqtada 25 km oyna LOLA xaritasidan chiqib ketadi. Biroz ichkariroq joyni tanlang.")
    lon, lat = to_geo.transform(x, y)
    return {"lat": round(float(lat), 4), "lon": round(float(lon), 4), **_marker(settings, b, x, y)}


def locate(settings: Settings, lat: float, lon: float) -> dict:
    b, _, to_src = _frame(settings)
    x, y = to_src.transform(lon, lat)
    half = settings.window_km * 500.0
    if not (b.left + half <= x <= b.right - half and b.bottom + half <= y <= b.top - half):
        raise ConfigError("Bu joy uchun relyef ma’lumoti yo‘q: LOLA 80 m faqat janubiy qutbni (80°J – 90°J, Artemis bazalari hududi) qamraydi. Joy tanlash uchun «Janubiy qutb · LOLA» ko‘rinishiga o‘ting.")
    return {"lat": lat, "lon": lon, **_marker(settings, b, x, y)}


def window_dem(settings: Settings, lat: float, lon: float) -> np.ndarray:
    from rasterio.warp import Resampling

    from terramind.raster import read_to_grid
    from terramind.roi import make_grid

    locate(settings, lat, lon)
    grid = make_grid("moon", lat, lon, settings.window_km, settings.grid_m)
    dem, _ = read_to_grid(_lola(settings), grid, "moon", Resampling.average, "LOLA window")
    dem = np.asarray(dem, dtype="float64")
    valid = int(np.isfinite(dem).sum())
    if valid < settings.min_valid_pixels or 1 - valid / dem.size > settings.max_nodata_fraction:
        raise ConfigError("Too little LOLA data in this window. Pick another point.")
    return dem


def terrain(settings: Settings, lat: float, lon: float) -> dict:
    from terramind.assistant import terrain_payload

    dem = window_dem(settings, lat, lon)
    return terrain_payload(dem, settings.grid_m, "moon", lat, lon,
                           {"dataset": "NASA LRO LOLA south pole DEM 80 m", "window": f"{settings.window_km:g} km square",
                            "mode": "exploration point (not a reviewed site)"})


def search(settings: Settings, lat: float, lon: float, region_id: str, top_n: int = 10) -> dict:
    """Same scan and scoring as terramind.search, with the reference histograms taken from this Moon window."""
    from terramind import terrain as tm
    from terramind.assistant import landing_safety
    from terramind.config import METRICS
    from terramind.similarity import bin_edges, histogram
    from terramind.regions import get_region, region_dir, window_centers
    from terramind.search import _spaced_top, known_sites_in, satellite_link, scan

    dem = window_dem(settings, lat, lon)
    metrics = {"slope_deg": tm.slope_deg(dem, settings.grid_m), "relief_m": tm.local_relief(dem), "tri_m": tm.tri(dem)}
    ref_hists = {m: histogram(metrics[m], bin_edges(settings.bins[m])) for m in METRICS}
    region = get_region(settings, region_id)
    vrt = region_dir(settings, region) / f"{region.demtype}_mosaic.vrt"
    if not vrt.exists():
        raise MissingInputError(f"Region '{region_id}' has not been downloaded yet; run one search there first.")
    rows = scan(settings, ref_hists, vrt, window_centers(region, settings.window_km))
    key = "overall_" + next(iter(settings.weights))
    ok = sorted([r for r in rows if r["status"] == "ok"], key=lambda r: r[key], reverse=True)
    for rank, r in enumerate(ok, 1):
        r["rank"] = rank
    top = _spaced_top(ok, key, top_n, settings.window_km)
    for r in top:
        r["satellite"] = satellite_link(r["lat"], r["lon"])
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    known = []
    for site in known_sites_in(settings, region):
        if not ok:
            break
        dist, nearest = min(((geod.inv(site.lon, site.lat, r["lon"], r["lat"])[2], r) for r in ok), key=lambda t: t[0])
        known.append({"site": site.id, "name": site.name, "score": nearest[key], "rank": nearest["rank"], "of": len(ok),
                      "top_percent": round(100.0 * nearest["rank"] / len(ok), 1),
                      "nearest_window": {"lat": nearest["lat"], "lon": nearest["lon"], "distance_km": round(dist / 1000, 1)}})
    scores = np.array([r[key] for r in ok]) if ok else np.array([])
    s = tm.summary
    return {
        "reference": {"id": f"moon@{lat:.4f},{lon:.4f}", "name": f"Moon · {abs(lat):.3f}° S, {lon:.3f}° E (exploration point)",
                      "exploration": True},
        "reference_metrics": {"slope_deg": s(metrics["slope_deg"]), "relief_m": s(metrics["relief_m"]), "tri_m": s(metrics["tri_m"]),
                              "landing": landing_safety(metrics["slope_deg"])},
        "region": {"id": region.id, "name": region.name, "bbox": list(region.bbox)},
        "counts": {"windows": len(rows), "scored": len(ok), "water": sum(r["status"] == "water" for r in rows),
                   "nodata": sum(r["status"] == "nodata" for r in rows)},
        "score_distribution": None if not ok else {"max": round(float(scores.max()), 4), "p90": round(float(np.percentile(scores, 90)), 4),
                                                   "median": round(float(np.median(scores)), 4)},
        "top": top, "known_sites": known,
        "note": "Exploration point: not a reviewed site. Same metrics, grid and scoring as the Analog Finder.",
    }
