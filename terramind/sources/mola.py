"""Mars MOLA DEM: always read from a local file, never downloaded automatically (~2 GB)."""

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
    lines = [f"No Mars DEM found for site '{site.id}'. Put one of these files in place:"]
    lines += [f"  - {p}" for p in candidates] or ["  (no dem_paths configured in config/sites.yaml)"]
    lines += [
        f"Download the global mosaic (~2 GB, resumable: curl -C - -L -O <url>): {ds['download_url']}",
        f"Dataset page: {ds['source_url']}",
        "Or clip only the Gale region with: python scripts/clip_mola_gale.py",
    ]
    raise MissingInputError("\n".join(lines))
