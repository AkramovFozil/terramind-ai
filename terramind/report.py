"""Mission brief: one printable page for one Earth lead (reference window + lead + provenance + review state).

GET /api/tm/report/<reference>__<region>?lat=&lon=  -> self-contained HTML (print to PDF from the browser).
Every number comes from the saved search and the processed windows; nothing is estimated here.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from terramind import __version__
from terramind.config import DATASETS, MissingInputError, Settings

REPO_URL = "https://github.com/AkramovFozil/terramind-ai"
SRTM_SOURCES = {
    "SRTMGL3": ("NASA SRTM GL3 (3 arc-second, ~90 m) via OpenTopography", "https://doi.org/10.5069/G9445JDF"),
    "SRTMGL1": ("NASA SRTM GL1 (1 arc-second, ~30 m) via OpenTopography", "https://doi.org/10.5069/G9445JDF"),
}


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f} %"


def _f(v, d=2) -> str:
    return "—" if v is None else f"{float(v):.{d}f}"


def lead_window_png(settings: Settings, region_id: str, lat: float, lon: float) -> Path:
    """Shaded relief of the lead's 25 km window from the region's SRTM mosaic, cached next to the search."""
    from matplotlib import colormaps
    from matplotlib.colors import LightSource
    from PIL import Image
    from rasterio.warp import Resampling

    from terramind.raster import read_to_grid
    from terramind.regions import get_region, region_dir
    from terramind.roi import make_grid

    region = get_region(settings, region_id)
    out_dir = settings.root / "results" / "search" / "leads"
    out = out_dir / f"{region_id}_{lat:.5f}_{lon:.5f}.png"
    if out.exists():
        return out
    vrt = region_dir(settings, region) / f"{region.demtype}_mosaic.vrt"
    if not vrt.exists():
        raise MissingInputError(f"Region '{region_id}' has not been downloaded yet.")
    grid = make_grid("earth", lat, lon, settings.window_km, settings.grid_m)
    dem, _ = read_to_grid(vrt, grid, "earth", Resampling.average, f"{region_id} lead")
    dem = np.asarray(dem, dtype="float64")
    filled = np.where(np.isfinite(dem), dem, np.nanmedian(dem))
    big = np.asarray(Image.fromarray(filled.astype("float32"), mode="F").resize((filled.shape[1] * 8, filled.shape[0] * 8), Image.BICUBIC), dtype="float64")
    lo, hi = np.nanpercentile(big, [2, 98])
    rgb = LightSource(azdeg=315, altdeg=40).shade(big, cmap=colormaps["gist_earth"], blend_mode="soft", vert_exag=3,
                                                  dx=settings.grid_m / 8, dy=settings.grid_m / 8, vmin=lo, vmax=hi if hi > lo else lo + 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(rgb[..., :3], 0, 1) * 255).astype("uint8")).save(out, optimize=True)
    return out


def _data_uri(path: Path) -> str:
    import base64

    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def mission_brief(settings: Settings, search_id: str, lat: float, lon: float) -> str:
    from terramind.assistant import landing_safety, point_terrain, reference_info, window_image
    from terramind.gate import read_roi
    from terramind.regions import get_region
    from terramind.server import search_view

    res = search_view(settings, search_id)
    if not res:
        raise MissingInputError("unknown search")
    lead = min(res["top"], key=lambda t: abs(t["lat"] - lat) + abs(t["lon"] - lon))
    if abs(lead["lat"] - lat) + abs(lead["lon"] - lon) > 1e-3:
        raise MissingInputError("This point is not one of the saved leads.")
    ref = reference_info(settings, res["reference"]["id"])
    roi = read_roi(settings, ref["id"]) or {}
    region = get_region(settings, res["region"]["id"])
    site = settings.site(ref["id"])
    ds = DATASETS[site.dataset]
    key = f"{lead['lat']:.5f},{lead['lon']:.5f}"
    review = res["reviews"].get(key)
    rank = lead.get("rank")
    body_name = "Moon" if ref["body"] == "moon" else "Mars"

    earth = point_terrain(settings, region.id, lead["lat"], lead["lon"])
    ref_landing = ref.get("landing") or landing_safety(np.array([]))
    lead_landing = earth["landing"]
    ms = ref.get("metric_summary") or {}
    es = earth["layer_stats"]
    srtm_name, srtm_doi = SRTM_SOURCES.get(region.demtype, (region.demtype, ""))
    known = res.get("known_sites") or []
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    try:
        ref_img = _data_uri(window_image(settings, ref["id"]))
    except Exception:  # pragma: no cover - image is optional
        ref_img = ""
    try:
        lead_img = _data_uri(lead_window_png(settings, region.id, lead["lat"], lead["lon"]))
    except Exception:  # pragma: no cover
        lead_img = ""
    map_png = settings.root / "results" / "search" / search_id / "map.png"
    map_img = _data_uri(map_png) if map_png.exists() else ""

    def row(label, a, b):
        return f"<tr><th>{_esc(label)}</th><td>{a}</td><td>{b}</td></tr>"

    review_html = (f"<span class='tag {review['verdict']}'>{_esc(review['verdict'].upper())}</span> {_esc(review.get('note', ''))} "
                   f"<small>({_esc(review.get('reviewed_at', ''))})</small>" if review else "<span class='tag pending'>NOT YET REVIEWED</span> — check the satellite view before treating this lead as an analog.")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TerraMind mission brief — {_esc(ref['name'])} → {_esc(lead['lat'])}, {_esc(lead['lon'])}</title>
<style>
:root{{--ink:#17201a;--quiet:#5e6a60;--line:#d8ded3;--accent:#4f7a3a;--bg:#fbfcf8}}
*{{box-sizing:border-box}}body{{margin:0;background:#e9ece5;color:var(--ink);font:14px/1.5 -apple-system,'Segoe UI','DM Sans',Arial,sans-serif}}
.page{{max-width:900px;margin:24px auto;background:var(--bg);padding:40px 48px;border:1px solid var(--line);border-radius:10px}}
.k{{font:10px 'IBM Plex Mono',Consolas,monospace;letter-spacing:1.6px;color:var(--quiet);text-transform:uppercase}}
h1{{font-size:26px;margin:6px 0 2px;letter-spacing:-.5px}}h2{{font-size:15px;margin:28px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}}
.sub{{color:var(--quiet);margin:0 0 18px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}
figure{{margin:0}}figure img{{width:100%;aspect-ratio:1;object-fit:cover;border-radius:6px;border:1px solid var(--line);background:#222}}
figcaption{{font-size:11.5px;color:var(--quiet);margin-top:6px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--quiet);font-weight:500;width:34%}}
thead th{{color:var(--ink);font-weight:600}}
.tag{{display:inline-block;padding:3px 8px;border-radius:4px;font:600 10px 'IBM Plex Mono',monospace;letter-spacing:1px;color:#fff;background:#8a8f87}}
.tag.accepted{{background:#4f7a3a}}.tag.rejected{{background:#b2452f}}.tag.pending{{background:#b58a2b}}
.bar{{display:flex;height:8px;border-radius:4px;overflow:hidden;background:#ddd;margin-top:4px}}.bar b{{display:block;height:100%}}.flat{{background:#6fb55a}}.caution{{background:#e2b25a}}.hazard{{background:#c75a44}}
.score{{font-size:34px;font-weight:600;letter-spacing:-1px;color:var(--accent)}}
.note{{font-size:12px;color:var(--quiet);border-left:3px solid var(--line);padding:6px 10px;margin:14px 0 0}}
.foot{{margin-top:28px;padding-top:12px;border-top:1px solid var(--line);font-size:11px;color:var(--quiet);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}}
.print{{position:fixed;right:18px;top:18px;padding:10px 14px;border:0;border-radius:6px;background:var(--ink);color:#fff;font-size:12px;cursor:pointer}}
a{{color:var(--accent)}}
@media print{{body{{background:#fff}}.page{{margin:0;border:0;border-radius:0;max-width:none;padding:18mm 16mm}}.print{{display:none}}}}
</style></head><body>
<button class="print" onclick="window.print()">Print / save as PDF</button>
<div class="page">
<p class="k">TerraMind AI · Mission brief · candidate Earth analog</p>
<h1>{_esc(ref['name'])} → Earth lead #{_esc(rank)}</h1>
<p class="sub">{_esc(region.name)} · {_esc(f"{lead['lat']:.5f}")}, {_esc(f"{lead['lon']:.5f}")} · generated {generated} · TerraMind {_esc(__version__)}</p>

<div class="grid">
<div><p class="k">Similarity (weight set A: slope 40 % · relief 35 % · roughness 25 %)</p><div class="score">{_f(lead['overall_A'])}</div>
<p style="margin:4px 0 0">Rank {_esc(rank)} of {_esc(res['counts']['scored'])} scored windows · weight set B: {_f(lead.get('overall_B'))} · slope {_f(lead.get('slope_deg'))} · relief {_f(lead.get('relief_m'))} · roughness {_f(lead.get('tri_m'))}</p>
<p style="margin:10px 0 0"><b>Review:</b> {review_html}</p>
<p style="margin:10px 0 0"><a href="{_esc(lead.get('satellite'))}" target="_blank" rel="noreferrer">Open in satellite view</a></p></div>
<div><p class="k">Region similarity map</p>{f'<img src="{map_img}" style="width:100%;border:1px solid var(--line);border-radius:6px">' if map_img else '<p>map.png not found</p>'}</div>
</div>

<h2>Both 25 km windows, same 463 m grid</h2>
<div class="grid">
<figure>{f'<img src="{ref_img}" alt="">' if ref_img else ''}<figcaption><b>{body_name} · {_esc(ref['name'])}</b><br>{_esc(ref['center']['lat'])}, {_esc(ref['center']['lon'])} · {_esc(ds['name'])}<br>Window approved {_esc(roi.get('approved_at', '—'))} · params {_esc((roi.get('params_hash') or '')[:12])}</figcaption></figure>
<figure>{f'<img src="{lead_img}" alt="">' if lead_img else ''}<figcaption><b>Earth · lead #{_esc(rank)}</b><br>{_esc(f"{lead['lat']:.5f}")}, {_esc(f"{lead['lon']:.5f}")} · {_esc(srtm_name)}<br>Shaded relief; colours are elevation, not a photo.</figcaption></figure>
</div>

<table style="margin-top:18px"><thead><tr><th></th><th>{body_name} reference</th><th>Earth lead</th></tr></thead><tbody>
{row('Median slope', f"{_f((ms.get('slope_deg') or {}).get('median'), 2)}°", f"{_f(es['slope_deg']['median'], 2)}°")}
{row('Slope p95', f"{_f((ms.get('slope_deg') or {}).get('p95'), 2)}°", f"{_f(es['slope_deg']['p95'], 2)}°")}
{row('Relief 5–95 %', f"{_f((ms.get('relief_m') or {}).get('p5'), 0)} … {_f((ms.get('relief_m') or {}).get('p95'), 0)} m", f"{_f(earth['roi_min_elevation_m'] - earth['median_elevation_m'], 0)} … {_f(earth['roi_max_elevation_m'] - earth['median_elevation_m'], 0)} m (min…max)")}
{row('Median roughness (TRI)', f"{_f((ms.get('tri_m') or {}).get('median'), 1)} m", f"{_f(lead.get('tri_median'), 1)} m")}
{row('Flat for landing (slope < 5°)', _pct(ref_landing.get('flat_lt5')) + f"<div class='bar'><b class='flat' style='width:{(ref_landing.get('flat_lt5') or 0) * 100:.0f}%'></b><b class='caution' style='width:{((ref_landing.get('lt15') or 0) - (ref_landing.get('flat_lt5') or 0)) * 100:.0f}%'></b><b class='hazard' style='width:{(ref_landing.get('hazard_gt15') or 0) * 100:.0f}%'></b></div>",
     _pct(lead_landing.get('flat_lt5')) + f"<div class='bar'><b class='flat' style='width:{(lead_landing.get('flat_lt5') or 0) * 100:.0f}%'></b><b class='caution' style='width:{((lead_landing.get('lt15') or 0) - (lead_landing.get('flat_lt5') or 0)) * 100:.0f}%'></b><b class='hazard' style='width:{(lead_landing.get('hazard_gt15') or 0) * 100:.0f}%'></b></div>")}
{row('Caution (5–15°) / hazard (≥ 15°)', f"{_pct((ref_landing.get('lt15') or 0) - (ref_landing.get('flat_lt5') or 0))} / {_pct(ref_landing.get('hazard_gt15'))}", f"{_pct((lead_landing.get('lt15') or 0) - (lead_landing.get('flat_lt5') or 0))} / {_pct(lead_landing.get('hazard_gt15'))}")}
</tbody></table>
<p class="note">Landing figures are a simple slope screen on the 463 m grid (flat &lt; 5°, caution 5–15°, hazard ≥ 15°). They are not a mission safety rating: boulders, craters smaller than 463 m, illumination and soil are not measured here.</p>

<h2>Context of the search</h2>
<table><tbody>
{row('Region', f"{_esc(region.name)} · bbox {_esc(region.bbox)}", '')}
{row('Windows', f"{_esc(res['counts']['windows'])} total · {_esc(res['counts']['scored'])} scored · {_esc(res['counts']['water'])} water-excluded · stride {_esc(res['stride_km'])} km", '')}
{row('Score distribution', f"max {_f((res.get('score_distribution') or {}).get('max'))} · p90 {_f((res.get('score_distribution') or {}).get('p90'))} · median {_f((res.get('score_distribution') or {}).get('median'))}", '')}
{''.join(row('Known analog site', f"{_esc(k['name'])}: rank {_esc(k['rank'])} of {_esc(k['of'])} (top {_esc(k['top_percent'])} %), score {_f(k['score'])}", '') for k in known)}
{row('Method', 'Local azimuthal-equidistant projection on each body’s own sphere → common 463 m grid → Horn slope, relief (elevation − window median), TRI → histogram intersection per metric → weighted mean. A person approves the reference window before any score is computed; moving it afterwards invalidates the scores.', '')}
</tbody></table>

<h2>Data and provenance</h2>
<table><tbody>
{row(body_name + ' elevation', f"{_esc(ds['name'])} — {_esc(ds.get('provider', ''))}<br><a href='{_esc(ds.get('source_url', ''))}'>{_esc(ds.get('source_url', ''))}</a>" + (f"<br>DOI: {_esc(ds['doi'])}" if ds.get('doi') else ''), '')}
{row('Earth elevation', f"{_esc(srtm_name)}<br><a href='{_esc(srtm_doi)}'>{_esc(srtm_doi)}</a>", '')}
{row('Search file', f"results/search/{_esc(search_id)}/search.json · generated {_esc(res.get('generated_at'))}", '')}
{row('Software', f"TerraMind AI {_esc(__version__)} · open source · <a href='{REPO_URL}'>{REPO_URL}</a>", '')}
</tbody></table>

<div class="foot"><span>TerraMind AI · NASA Space Apps Challenge 2026 · OXUS University, Tashkent · not affiliated with or endorsed by NASA.</span><span>Terrain shape only — no claim about rock type, climate or habitability.</span></div>
</div></body></html>"""
