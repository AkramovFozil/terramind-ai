"""Planetary DEMs (Mars MOLA, Moon LOLA): always read from a local file, never downloaded automatically."""

from __future__ import annotations

from pathlib import Path

from terramind.config import DATASETS, MissingInputError, Settings, Site


def resolve_dem_path(settings: Settings, site: Site) -> Path:
    """First existing file from the site's `dem_paths`, else exact instructions."""
    candidates = [settings.root / p for p in site.dem_paths]
    for path in candidates:
        if path.exists():
            return path
    ds = DATASETS[site.dataset]
    lines = [f"No {site.body.title()} DEM found for site '{site.id}'. Put one of these files in place:"]
    lines += [f"  - {p}" for p in candidates] or ["  (no dem_paths configured in config/sites.yaml)"]
    lines += [
        f"Download ({ds['name']}; resumable: curl -C - -L -O <url>): {ds['download_url']}",
        f"Dataset page: {ds['source_url']}",
    ]
    if site.dataset == "MOLA_MEGDR_463m":
        lines.append("Or clip only the Gale region with: python scripts/clip_mola_gale.py")
    raise MissingInputError("\n".join(lines))
