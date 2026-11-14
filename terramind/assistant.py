"""TerraMind AI assistant: one conversational flow over the whole platform.

"Find a place on Earth whose relief matches LOLA on the Moon" becomes:
  1. show_reference   → the Moon (or Mars) site is marked on a map built from NASA data
  2. find_earth_analogs → the Analog Finder ranks Earth windows with the same method
  3. the model explains the computed numbers; every number in its answer is checked.

The AI decides which tool to call; the algorithm computes every score.
Mounted on the FastAPI app (terramind/api.py) under /api/tm.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from terramind import terrain as tmetrics
from terramind.config import MissingInputError, Settings, TerraMindError, load_settings, project_root

ABOUT_TOOLS = """
You run TerraMind's analog search. Use the tools; never name places from your own knowledge.
- When the user mentions a Mars or Moon site, dataset or mission (Gale/Curiosity, Meridiani/Opportunity,
  MOLA = Mars; LOLA/Artemis/Mons Mouton/south pole = Moon), first call show_reference with that reference.
- When the user asks to find, match or search places on Earth, call find_earth_analogs with the reference and the
  closest available region (if they say "Earth" or "anywhere", use uzbekistan_west and say which regions exist).
- Then answer in 3-6 short sentences in the user's language: what the reference terrain is like, the best leads with
  coordinates and scores, which metric drives the match, and that leads need human review on satellite imagery.
  Mention a known analog site's rank when the region contains one."""


# --------------------------------------------------------------------------- settings / helpers

def _settings() -> Settings:
    root = project_root(None)
    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env", override=False)
    except ImportError:  # pragma: no cover
        pass
    return load_settings(root)


def _approved_references(settings: Settings) -> list:
    from terramind.gate import site_state

    return [s for s in settings.sites.values()
            if s.body in ("mars", "moon") and s.role == "reference" and s.lat is not None
            and site_state(settings, s) == "approved"]


def _pending_references(settings: Settings) -> list[dict]:
    """Mars/Moon references that exist in sites.yaml but cannot be used yet (not prepared or not approved)."""
    from terramind.gate import site_state

    return [{"id": s.id, "name": s.name, "body": s.body, "state": site_state(settings, s)}
            for s in settings.sites.values()
            if s.body in ("mars", "moon") and s.role == "reference" and s.lat is not None and s.enabled
            and site_state(settings, s) != "approved"]


def reference_info(settings: Settings, site_id: str) -> dict:
    from terramind.gate import read_roi, site_state

    site = settings.site(site_id)
    roi = read_roi(settings, site.id) or {}
    return {
        "id": site.id, "name": site.name, "body": site.body, "role": site.role,
        "center": {"lat": site.lat, "lon": site.lon}, "state": site_state(settings, site),
        "dataset": (roi.get("input") or {}).get("name"),
        "window_km": settings.window_km, "grid_m": settings.grid_m,
        "metric_summary": roi.get("metric_summary"),
        "note": site.note,
    }


def terrain_payload(dem: np.ndarray, res_m: float, body: str, lat: float, lon: float, provenance: dict) -> dict:
    """TerrainData for the 3D compare view (same contract as the Global Explorer's /api/terrain)."""
    dem = np.asarray(dem, dtype="float64")
    inside = np.isfinite(dem)
    if inside.sum() < 9:
        raise MissingInputError("Not enough valid elevation pixels for a 3D view.")
    slope = tmetrics.slope_deg(dem, res_m)
    rough = tmetrics.roughness(dem)

    def flat(a, d=2):
        return [round(float(v), d) if math.isfinite(float(v)) else None for v in np.asarray(a).flat]

    stats = {name: tmetrics.summary(np.where(inside, layer, np.nan)) for name, layer in (("slope_deg", slope), ("roughness_m", rough))}
    h, w = dem.shape
    return {
        "body": body, "width": w, "height": h, "elevations": flat(dem), "roi_mask": inside.ravel().tolist(),
        "pixel_size_m": float(res_m), "center": {"lat": lat, "lon": lon}, "radius_km": w * res_m / 2000.0,
        "min_elevation_m": float(np.nanmin(dem)), "max_elevation_m": float(np.nanmax(dem)),
        "roi_min_elevation_m": float(np.nanmin(dem)), "roi_max_elevation_m": float(np.nanmax(dem)),
        "median_elevation_m": float(np.nanmedian(dem)),
        "layers": {"slope_deg": flat(slope, 3), "roughness_m": flat(rough, 3)},
        "layer_stats": stats, "provenance": provenance, "measured_dem": True,
    }


def site_terrain(settings: Settings, site_id: str) -> dict:
    from terramind.raster import read_band

    site = settings.site(site_id)
    path = settings.processed_dir(site.id) / "dem_463m.tif"
    if not path.exists():
        raise MissingInputError(f"Site '{site_id}' is not prepared yet.")
    from terramind.config import DATASETS

    return terrain_payload(read_band(path), settings.grid_m, site.body, site.lat, site.lon,
                           {"dataset": DATASETS[site.dataset]["name"], "window": f"{settings.window_km:g} km square"})


def point_terrain(settings: Settings, region_id: str, lat: float, lon: float) -> dict:
    from rasterio.warp import Resampling

    from terramind.raster import read_to_grid
    from terramind.regions import get_region, region_dir
    from terramind.roi import make_grid

    region = get_region(settings, region_id)
    vrt = region_dir(settings, region) / f"{region.demtype}_mosaic.vrt"
    if not vrt.exists():
        raise MissingInputError(f"Region '{region_id}' has not been downloaded yet; run a search there first.")
    grid = make_grid("earth", lat, lon, settings.window_km, settings.grid_m)
    dem, _ = read_to_grid(vrt, grid, "earth", Resampling.average, f"{region_id} window")
    return terrain_payload(dem, settings.grid_m, "earth", lat, lon,
                           {"dataset": f"NASA {region.demtype} (OpenTopography)", "window": f"{settings.window_km:g} km square"})


# --------------------------------------------------------------------------- reference maps

def reference_map(settings: Settings, site_id: str) -> dict:
    """Where to draw the reference on a map. Moon: a south-polar hillshade built from LOLA. Mars: the global texture."""
    site = settings.site(site_id)
    half = settings.window_km / 2.0
    if site.body == "mars":
        def frac(lon, lat):
            return ((lon + 180.0) / 360.0, (90.0 - lat) / 180.0)
        dlat = half / (math.pi * 3396.19 / 180.0)
        dlon = dlat / max(math.cos(math.radians(site.lat)), 0.05)
        x0, y0 = frac(site.lon - dlon, site.lat + dlat)
        x1, y1 = frac(site.lon + dlon, site.lat - dlat)
        mx, my = frac(site.lon, site.lat)
        return {"kind": "equirect", "image": "/textures/planets/mars-color-2k.jpg", "marker": {"x": mx, "y": my},
                "box": {"x0": x0, "y0": y0, "x1": x1, "y1": y1}, "caption": "Mars · equirectangular map"}
    if site.body == "moon":
        meta = _moon_map(settings, site)
        return meta
    raise HTTPException(status_code=400, detail="Only Mars and Moon references have reference maps.")


def window_image(settings: Settings, site_id: str) -> Path:
    """Shaded relief of the approved 25 km window itself (the exact pixels that were scored), cached as PNG."""
    from matplotlib import colormaps
    from matplotlib.colors import LightSource
    from PIL import Image

    from terramind.raster import read_band

    site = settings.site(site_id)
    dem_path = settings.processed_dir(site.id) / "dem_463m.tif"
    if not dem_path.exists():
        raise MissingInputError(f"Site '{site_id}' is not prepared yet.")
    out = settings.processed_dir(site.id) / "window_view.png"
    if out.exists() and out.stat().st_mtime >= dem_path.stat().st_mtime:
        return out
    dem = np.asarray(read_band(dem_path), dtype="float64")
    filled = np.where(np.isfinite(dem), dem, np.nanmedian(dem))
    big = np.asarray(Image.fromarray(filled.astype("float32"), mode="F").resize(
        (filled.shape[1] * 8, filled.shape[0] * 8), Image.BICUBIC), dtype="float64")
    cmap = colormaps["copper" if site.body == "mars" else "gray" if site.body == "moon" else "gist_earth"]
    lo, hi = np.nanpercentile(big, [2, 98])
    rgb = LightSource(azdeg=315, altdeg=40).shade(big, cmap=cmap, blend_mode="soft", vert_exag=3,
                                                  dx=settings.grid_m / 8, dy=settings.grid_m / 8,
                                                  vmin=lo, vmax=hi if hi > lo else lo + 1)
    Image.fromarray((np.clip(rgb[..., :3], 0, 1) * 255).astype("uint8")).save(out, optimize=True)
    return out


def _moon_map(settings: Settings, site) -> dict:
    import rasterio
    from matplotlib.colors import LightSource
    from PIL import Image
    from pyproj import Transformer
    from rasterio.enums import Resampling as RioResampling

    from terramind.crs import MOON_GEOGRAPHIC
    from terramind.sources.mola import resolve_dem_path

    src_path = resolve_dem_path(settings, site)
    out_dir = settings.root / "data" / "processed" / "maps"
    png = out_dir / "moon_south_pole.png"
    meta_path = out_dir / f"moon_{site.id}.json"
    if meta_path.exists() and png.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    with rasterio.open(src_path) as src:
        n = 1000
        z = src.read(1, out_shape=(n, n), resampling=RioResampling.average, masked=True).astype("float64").filled(np.nan)
        b = src.bounds
        to_src = Transformer.from_crs(MOON_GEOGRAPHIC, src.crs.to_wkt(), always_xy=True)
        x, y = to_src.transform(site.lon, site.lat)
    px = (b.right - b.left) / n
    filled = np.where(np.isfinite(z), z, np.nanmedian(z))
    hs = LightSource(azdeg=315, altdeg=35).hillshade(filled, vert_exag=2, dx=px, dy=px)
    img = (np.clip(hs, 0, 1) * 235 + 10).astype("uint8")
    out_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img, mode="L").save(png, optimize=True)
    half_m = settings.window_km * 500.0
    w, h = b.right - b.left, b.top - b.bottom
    meta = {
        "kind": "polar", "image": "/api/tm/map-image/moon_south_pole.png",
        "marker": {"x": (x - b.left) / w, "y": (b.top - y) / h},
        "box": {"x0": (x - half_m - b.left) / w, "y0": (b.top - (y + half_m)) / h,
                "x1": (x + half_m - b.left) / w, "y1": (b.top - (y - half_m)) / h},
        "caption": "Moon · south pole, 80° S to the pole · hillshade from NASA LRO LOLA",
    }
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return meta


# --------------------------------------------------------------------------- the agent

def _tools(settings: Settings) -> list[dict]:
    from terramind.regions import load_regions

    refs = _approved_references(settings)
    regions = load_regions(settings)
    ref_desc = "; ".join(f"{s.id} = {s.name} ({s.body}, {'LOLA' if s.body == 'moon' else 'MOLA'})" for s in refs)
    reg_desc = "; ".join(f"{r.id} = {r.name}" for r in regions.values())
    ref_param = {"type": "string", "enum": [s.id for s in refs], "description": ref_desc}
    return [
        {"type": "function", "function": {
            "name": "show_reference",
            "description": "Mark a Mars or Moon reference site on its map and return its measured terrain. References: " + ref_desc,
            "parameters": {"type": "object", "properties": {"reference": ref_param}, "required": ["reference"]}}},
        {"type": "function", "function": {
            "name": "find_earth_analogs",
            "description": "Scan an Earth region with NASA SRTM for 25 km windows whose slope, relief and roughness "
                           "match the reference; returns ranked leads computed by TerraMind. Regions: " + reg_desc,
            "parameters": {"type": "object", "properties": {
                "reference": ref_param,
                "region": {"type": "string", "enum": list(regions), "description": reg_desc}},
                "required": ["reference", "region"]}}},
    ]


def chat(settings: Settings, question: str, api_key: str | None, model: str | None = None,
         opentopo_key: str | None = None, session=None, search_fn=None, history: list | None = None,
         max_tokens: int | None = None) -> dict:
    from terramind.explain import (DEFAULT_MAX_TOKENS, DEFAULT_MODEL, REPO_URL, SYSTEM_PROMPT,
                                   _post, _search_context, cached_or_run_search, load_context,
                                   unverified_numbers)

    if not question.strip():
        raise MissingInputError("Empty question.")
    if not api_key:
        raise MissingInputError("OPENROUTER_API_KEY is not set in .env, so the assistant cannot answer.")
    try:
        context = load_context(settings)
    except MissingInputError:
        context = {"source": "none"}
    tools = _tools(settings)
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT + ABOUT_TOOLS},
        {"role": "system", "content": "CONTEXT:\n" + json.dumps(context, ensure_ascii=False)},
    ]
    pending = _pending_references(settings)
    if pending:
        msgs.append({"role": "system", "content": "Not usable yet (a person must prepare and approve the window first): "
                     + "; ".join(f"{p['name']} [{p['state']}] -> python -m terramind approve --site {p['id']}" for p in pending)
                     + ". If the user asks for one of these, say so and give that command."})
    for m in (history or [])[-6:]:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            msgs.append({"role": m["role"], "content": m["content"][:2000]})
    msgs.append({"role": "user", "content": question})
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
               "HTTP-Referer": REPO_URL, "X-Title": "TerraMind AI"}
    base = {"model": model or DEFAULT_MODEL, "temperature": 0.2, "max_tokens": int(max_tokens or DEFAULT_MAX_TOKENS)}
    http = session or requests
    run_search = search_fn or (lambda ref, reg: cached_or_run_search(settings, ref, reg, opentopo_key))
    steps: list[dict] = []
    grounded = dict(context)
    for _round in range(4):
        msg = _post(http, headers, dict(base, messages=msgs, tools=tools, tool_choice="auto"), 120.0, api_key)
        calls = (msg.get("tool_calls") or [])[:2]
        if not calls:
            answer = (msg.get("content") or "").strip()
            return {"answer": answer, "model": base["model"], "steps": steps,
                    "unverified_numbers": unverified_numbers(answer, grounded)}
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            name = call.get("function", {}).get("name")
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
                if name == "show_reference":
                    info = reference_info(settings, args["reference"])
                    steps.append({"kind": "reference", "reference": info})
                    result = info
                elif name == "find_earth_analogs":
                    res = run_search(args["reference"], args["region"])
                    ctx = _search_context(res)
                    steps.append({"kind": "search", "search_id": f"{res['reference']['id']}__{res['region']['id']}",
                                  "reference": res["reference"], "region": res["region"], "counts": res["counts"],
                                  "score_distribution": res["score_distribution"], "top": res["top"],
                                  "known_sites": res["known_sites"]})
                    result = ctx
                else:
                    result = {"error": f"unknown tool {name}"}
            except (KeyError, ValueError, TypeError, TerraMindError) as exc:
                result = {"error": str(exc)}
            grounded.setdefault("tool_results", []).append(result)
            msgs.append({"role": "tool", "tool_call_id": call.get("id", "call"), "content": json.dumps(result, ensure_ascii=False)})
    raise MissingInputError("The assistant did not finish after several tool calls; try a more specific question.")


# --------------------------------------------------------------------------- HTTP routes

class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=600)
    history: list[dict] = Field(default_factory=list, max_length=12)


class ReviewRequest(BaseModel):
    search_id: str
    lat: float
    lon: float
    verdict: str
    note: str = ""


def _http(exc: Exception, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=str(exc))


def make_router() -> APIRouter:
    router = APIRouter(prefix="/api/tm")

    @router.get("/overview")
    def overview():
        from terramind.server import overview as ov

        s = _settings()
        data = ov(s)
        data["references"] = [reference_info(s, r.id) for r in _approved_references(s)]
        data["pending_references"] = _pending_references(s)
        return data

    @router.get("/reference/{site_id}")
    def reference(site_id: str):
        s = _settings()
        try:
            info = reference_info(s, site_id)
        except TerraMindError as exc:
            raise _http(exc, 404) from None
        try:
            info["map"] = reference_map(s, site_id)
        except (TerraMindError, OSError, ValueError) as exc:  # e.g. the LOLA mosaic is not on this computer
            info["map"], info["map_error"] = None, str(exc)
        return info

    @router.get("/map-image/{name}")
    def map_image(name: str):
        if name != "moon_south_pole.png":
            raise HTTPException(status_code=404)
        path = _settings().root / "data" / "processed" / "maps" / name
        if not path.exists():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="image/png")

    @router.get("/window-image/{site_id}.png")
    def window_png(site_id: str):
        s = _settings()
        if site_id not in s.sites:
            raise HTTPException(status_code=404)
        try:
            return FileResponse(window_image(s, site_id), media_type="image/png")
        except TerraMindError as exc:
            raise _http(exc, 404) from None

    @router.get("/quicklook/{site_id}.png")
    def quicklook(site_id: str):
        s = _settings()
        if site_id not in s.sites:
            raise HTTPException(status_code=404)
        path = s.processed_dir(site_id) / "quicklook.png"
        if not path.exists():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="image/png")

    @router.get("/search/{search_id}")
    def search(search_id: str):
        from terramind.server import search_view

        res = search_view(_settings(), search_id)
        if not res:
            raise HTTPException(status_code=404, detail="unknown search")
        return res

    @router.post("/review")
    def review(req: ReviewRequest):
        from terramind.server import save_review

        try:
            return {"reviews": save_review(_settings(), req.model_dump())}
        except (ValueError, KeyError) as exc:
            raise _http(exc) from None

    @router.get("/terrain/site/{site_id}")
    def terrain_site(site_id: str):
        try:
            return site_terrain(_settings(), site_id)
        except TerraMindError as exc:
            raise _http(exc, 404) from None

    @router.get("/terrain/point")
    def terrain_point(region: str = Query(min_length=1), lat: float = Query(ge=-60, le=60), lon: float = Query(ge=-180, le=180)):
        try:
            return point_terrain(_settings(), region, lat, lon)
        except TerraMindError as exc:
            raise _http(exc, 404) from None

    @router.post("/chat")
    def chat_route(req: ChatRequest):
        s = _settings()
        try:
            return chat(
                s, req.question, api_key=os.environ.get("OPENROUTER_API_KEY"),
                model=os.environ.get("OPENROUTER_MODEL") or None,
                opentopo_key=os.environ.get("OPENTOPO_API_KEY"), history=req.history,
                max_tokens=int(os.environ.get("OPENROUTER_MAX_TOKENS") or 0) or None,
            )
        except TerraMindError as exc:
            raise _http(exc) from None

    return router
