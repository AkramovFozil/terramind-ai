"""Figures: the pre-approval quick-look (hillshade) and the post-score histogram overlay."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LightSource  # noqa: E402

# Validated categorical pair (light surface): slot 1 blue = Earth, slot 2 orange = Mars.
EARTH_COLOR = "#2a78d6"
MARS_COLOR = "#eb6834"
SURFACE = "#fcfcfb"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
INK = "#1f1f1d"
MUTED = "#5f5e57"

HILLSHADE_AZ = 315
HILLSHADE_ALT = 45
VERTICAL_EXAGGERATION = 2.0

METRIC_LABELS = {
    "slope_deg": ("Slope", "degrees"),
    "relief_m": ("Local relief", "metres from ROI median"),
    "tri_m": ("Roughness (TRI)", "metres"),
}


def hillshade(dem: np.ndarray, res_m: float) -> np.ndarray:
    """Hillshade 0..1 (az 315, alt 45). NaN stays NaN. Display only."""
    z = np.asarray(dem, dtype="float64")
    mask = ~np.isfinite(z)
    filled = np.where(mask, np.nanmedian(z), z)
    ls = LightSource(azdeg=HILLSHADE_AZ, altdeg=HILLSHADE_ALT)
    hs = ls.hillshade(filled, vert_exag=VERTICAL_EXAGGERATION, dx=res_m, dy=res_m)
    hs[mask] = np.nan
    return hs


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=8)


def _panel(ax, dem, res_m, half_km, title):
    hs = hillshade(dem, res_m)
    extent = (-half_km, half_km, -half_km, half_km)
    cmap = plt.get_cmap("gray").with_extremes(bad="#f3c9c9")  # nodata shown as pale red, never hidden
    ax.imshow(np.ma.masked_invalid(hs), cmap=cmap, vmin=0, vmax=1, extent=extent, interpolation="nearest")
    ax.plot(0, 0, marker="+", markersize=16, mew=2.5, color="white")
    ax.plot(0, 0, marker="+", markersize=14, mew=1.2, color="#c0261b")
    # 10 km scale bar, lower left
    x0, y0 = -half_km + 2.5, -half_km + 3.0
    ax.plot([x0, x0 + 10], [y0, y0], color="white", lw=6, solid_capstyle="butt")
    ax.plot([x0, x0 + 10], [y0, y0], color="black", lw=3, solid_capstyle="butt")
    ax.text(x0 + 5, y0 + 1.2, "10 km", ha="center", va="bottom", fontsize=9, color="black",
            bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.8})
    ax.set_title(title, fontsize=10, color=INK, loc="left")
    ax.set_xlabel("km east of center", fontsize=8, color=MUTED)
    ax.set_ylabel("km north of center", fontsize=8, color=MUTED)
    _style(ax)


def quicklook(path: Path, site, dem463: np.ndarray, grid463, bbox, dem30=None, grid30=None, map_links=None) -> Path:
    """Hillshade of the 463 m DEM (and the 30 m Earth DEM), center marker, 10 km bar, title with bbox."""
    panels = 2 if dem30 is not None else 1
    fig, axes = plt.subplots(1, panels, figsize=(7.0 * panels, 7.6), dpi=120, facecolor=SURFACE, squeeze=False)
    half_km = grid463.half_extent_m / 1000.0
    _panel(axes[0][0], dem463, grid463.res_m, half_km, f"Matching grid, {grid463.res_m:g} m pixels")
    if dem30 is not None:
        _panel(axes[0][1], dem30, grid30.res_m, grid30.half_extent_m / 1000.0, f"Native Earth DEM, {grid30.res_m:g} m pixels")

    w, s, e, n = bbox
    status = "PROVISIONAL center" if site.provisional else "center"
    fig.suptitle(
        f"{site.name} — {site.body.title()} ({site.role})\n"
        f"{status} {site.lat:.4f}, {site.lon:.4f} · window {2 * half_km:.0f} × {2 * half_km:.0f} km\n"
        f"bbox lon {w:.3f}..{e:.3f}, lat {s:.3f}..{n:.3f}",
        fontsize=11, color=INK, x=0.02, ha="left",
    )
    foot = [
        f"Hillshade az {HILLSHADE_AZ}°, alt {HILLSHADE_ALT}°, vertical exaggeration {VERTICAL_EXAGGERATION:g}×. "
        "Red + = site center. Pale red = nodata.",
        "QUICK-LOOK FOR HUMAN REVIEW — not a result. Check for rivers, fields, towns, mines and edges, then approve.",
    ]
    if map_links:
        foot.append("Satellite view: " + map_links["satellite"])
    fig.text(0.02, 0.015, "\n".join(foot), fontsize=7.5, color=MUTED, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.1, 1, 0.88))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def histograms(path: Path, comparison: dict, target, candidate) -> Path:
    """One panel per metric: Earth filled, Mars outlined, shared fixed bins."""
    fig, axes = plt.subplots(1, len(comparison), figsize=(5.2 * len(comparison), 4.6), dpi=120, facecolor=SURFACE)
    axes = np.atleast_1d(axes)
    sites = {"target": target, "candidate": candidate}
    for ax, (metric, res) in zip(axes, comparison.items()):
        edges = res["edges"]
        centers = (edges[:-1] + edges[1:]) / 2.0
        inner = {k: res[f"p_{k}"][1:-1] for k in sites}
        nonzero = np.flatnonzero((inner["target"] > 0) | (inner["candidate"] > 0))
        if nonzero.size:
            lo, hi = edges[max(nonzero[0] - 2, 0)], edges[min(nonzero[-1] + 3, len(edges) - 1)]
        else:
            lo, hi = edges[0], edges[-1]
        for key, site in sites.items():
            color = EARTH_COLOR if site.body == "earth" else MARS_COLOR
            p = inner[key]
            if site.body == "earth":
                ax.fill_between(centers, p, step="mid", color=color, alpha=0.35, lw=0)
                ax.step(centers, p, where="mid", color=color, lw=1.2, label=f"{site.name} (Earth)")
            else:
                ax.step(centers, p, where="mid", color=color, lw=2.0, label=f"{site.name} ({site.body.title()})")
        name, unit = METRIC_LABELS.get(metric, (metric, ""))
        ax.set_xlim(lo, hi)
        ax.set_ylim(bottom=0)
        ax.set_title(f"{name}: overlap {res['score']:.3f}", fontsize=10, color=INK, loc="left")
        ax.set_xlabel(unit, fontsize=8, color=MUTED)
        ax.set_ylabel("share of pixels", fontsize=8, color=MUTED)
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        _style(ax)
        tails = []
        for key, site in sites.items():
            under, over = res[f"p_{key}"][0], res[f"p_{key}"][-1]
            if under > 0 or over > 0:
                tails.append(f"{site.name}: {under:.1%} below, {over:.1%} above range")
        if tails:
            ax.text(0.99, 0.97, "\n".join(tails), transform=ax.transAxes, ha="right", va="top", fontsize=7, color=MUTED)
    axes[0].legend(fontsize=8, frameon=False, loc="upper left", bbox_to_anchor=(0, -0.18), ncol=2)
    fig.suptitle(f"{target.name} vs {candidate.name} — distribution overlap on fixed bins (1 = identical)",
                 fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return path


# Sequential blue ramp (light -> dark), fixed 0..1 scale so colors mean the same in every run.
SEQ_BLUE = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
            "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]


def matrix_figure(path: Path, refs, earth, cells: dict, weight_set: str) -> Path:
    """Heatmap: rows = Earth sites, columns = Mars references, cell = overall score (0..1)."""
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("seq_blue", SEQ_BLUE)
    data = np.array([[cells[f"{r.id}__{s.id}"]["overall"][weight_set] for r in refs] for s in earth])
    fig, ax = plt.subplots(figsize=(2.4 + 2.6 * len(refs), 1.6 + 0.75 * len(earth)), dpi=120, facecolor=SURFACE)
    ax.imshow(data, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i in range(len(earth)):
        for j in range(len(refs)):
            v = data[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=12,
                    color="white" if v >= 0.55 else INK)
    ax.set_xticks(range(len(refs)), [r.name for r in refs], fontsize=8, color=INK)
    ax.set_yticks(range(len(earth)), [f"{s.name}\n({s.role})" for s in earth], fontsize=8, color=INK)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xticks(np.arange(-0.5, len(refs)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(earth)), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=3)
    ax.tick_params(which="minor", length=0)
    fig.text(0.01, 0.01, f"Overall similarity, weight set {weight_set} (0 = no overlap, 1 = identical). Every approved site is shown.",
             fontsize=7.5, color=MUTED, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def search_map(path: Path, region, vrt_path, rows: list, top: list, known: list, ref_name: str,
               key: str, window_km: float) -> Path:
    """Hillshade of the region with every scored window colored by similarity, top leads numbered."""
    import math

    import rasterio
    from matplotlib.collections import PatchCollection
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Rectangle
    from rasterio.enums import Resampling as RioResampling

    w, s, e, n = region.bbox
    mid = math.radians((s + n) / 2)
    with rasterio.open(vrt_path) as src:
        scale = max(src.width, src.height) / 1400.0
        out_w, out_h = max(1, int(src.width / max(scale, 1))), max(1, int(src.height / max(scale, 1)))
        dem = src.read(1, out_shape=(out_h, out_w), resampling=RioResampling.average, masked=True).astype("float64").filled(np.nan)
        b = src.bounds
    px_m = (b.right - b.left) / out_w * 111_320 * math.cos(mid)
    hs = hillshade(dem, px_m)

    cmap = LinearSegmentedColormap.from_list("seq_blue", SEQ_BLUE)
    aspect = 1 / math.cos(mid)
    width_in = 9.0
    height_in = max(4.0, width_in * (n - s) * aspect / (e - w)) + 1.6
    fig, ax = plt.subplots(figsize=(width_in + 1.4, min(height_in, 14)), dpi=120, facecolor=SURFACE)
    ax.imshow(np.ma.masked_invalid(hs), cmap="gray", vmin=0, vmax=1, extent=(b.left, b.right, b.bottom, b.top),
              interpolation="bilinear", alpha=0.9)

    ok = [r for r in rows if r.get("status") == "ok"]
    stride_km = region.stride_km
    patches, values = [], []
    for r in ok:
        dlat = stride_km / 111.32
        dlon = stride_km / (111.32 * math.cos(math.radians(r["lat"])))
        patches.append(Rectangle((r["lon"] - dlon / 2, r["lat"] - dlat / 2), dlon, dlat))
        values.append(r[key])
    if patches:
        pc = PatchCollection(patches, cmap=cmap, alpha=0.78, linewidths=0)
        pc.set_array(np.array(values))
        pc.set_clim(0, 1)
        ax.add_collection(pc)
        cb = fig.colorbar(pc, ax=ax, fraction=0.035, pad=0.02)
        cb.set_label(f"similarity to {ref_name}", fontsize=8, color=INK)
        cb.ax.tick_params(labelsize=7, colors=MUTED)
        cb.outline.set_visible(False)

    for i, r in enumerate(top, 1):
        ax.plot(r["lon"], r["lat"], marker="o", markersize=15, mfc="white", mec=INK, mew=1.2, zorder=5)
        ax.text(r["lon"], r["lat"], str(i), ha="center", va="center", fontsize=8, color=INK, zorder=6, fontweight="bold")
    for k in known:
        site_lat, site_lon = k["nearest_window"]["lat"], k["nearest_window"]["lon"]
        ax.plot(site_lon, site_lat, marker="^", markersize=11, mfc=MARS_COLOR, mec="white", mew=1.0, zorder=7)
        ax.annotate(f"{k['name']}: rank {k['rank']} of {k['of']} (top {k['top_percent']}%)",
                    (site_lon, site_lat), xytext=(8, -14), textcoords="offset points", fontsize=8, color=INK, zorder=8,
                    bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "none", "alpha": 0.85})

    ax.set_xlim(w, e)
    ax.set_ylim(s, n)
    ax.set_aspect(aspect)
    ax.set_xlabel("longitude", fontsize=8, color=MUTED)
    ax.set_ylabel("latitude", fontsize=8, color=MUTED)
    _style(ax)
    ax.set_title(f"Analog search: {region.name}\nwindows most similar to {ref_name} (numbered = top leads, ≥ {window_km:g} km apart)",
                 fontsize=10, color=INK, loc="left")
    fig.text(0.01, 0.01,
             f"{len(ok)} windows of {window_km:g} km scored every {stride_km:g} km; water and nodata windows not shown. "
             "Leads for human review, not confirmed analogs. Data: NASA SRTM GL3 via OpenTopography.",
             fontsize=7, color=MUTED, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path
