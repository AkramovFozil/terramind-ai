"""Human review gate: prepare -> look at quick-look -> approve -> score.

Scoring refuses a site that is not approved, or whose parameters changed after approval.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from terramind.config import GateError, MissingInputError, Settings, Site
from terramind.crs import local_crs_string

PENDING = "pending_review"
APPROVED = "approved"


def site_params(settings: Settings, site: Site) -> dict:
    """Everything that defines a ROI. Any change invalidates an approval."""
    return {
        "site": site.id,
        "body": site.body,
        "center": [site.lat, site.lon],
        "window_km": settings.window_km,
        "grid_m": settings.grid_m,
        "crs": local_crs_string(site.body, site.lat, site.lon),
        "dataset": site.dataset,
    }


def params_hash(params: dict) -> str:
    blob = json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def roi_path(settings: Settings, site_id: str) -> Path:
    return settings.processed_dir(site_id) / "roi.json"


def read_roi(settings: Settings, site_id: str) -> dict | None:
    path = roi_path(settings, site_id)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_roi(settings: Settings, site_id: str, roi: dict) -> Path:
    path = roi_path(settings, site_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(roi, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)
    return path


def site_state(settings: Settings, site: Site) -> str:
    """not_prepared | pending_review | approved | stale (config changed since prepare/approval)."""
    if site.lat is None or site.lon is None:
        return "no_center"
    roi = read_roi(settings, site.id)
    if roi is None:
        return "not_prepared"
    current = params_hash(site_params(settings, site))
    stored = roi.get("params_hash") if roi.get("status") == APPROVED else roi.get("prepared_params_hash")
    if stored != current:
        return "stale"
    return roi.get("status", "unknown")


def approve(settings: Settings, site_id: str) -> dict:
    site = settings.site(site_id)
    roi = read_roi(settings, site_id)
    if roi is None:
        raise MissingInputError(f"Site '{site_id}' is not prepared. Run: python -m terramind prepare --site {site_id}")
    current = params_hash(site_params(settings, site))
    if roi.get("prepared_params_hash") != current:
        raise GateError(
            f"Site '{site_id}': its center, window, grid or dataset in config/sites.yaml changed since prepare. "
            f"Run prepare again, look at the new quick-look, then approve."
        )
    roi["status"] = APPROVED
    roi["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    roi["params_hash"] = current
    write_roi(settings, site_id, roi)
    return roi


def require_approved(settings: Settings, site_id: str) -> dict:
    """Return the approved roi.json, or refuse with the reason and the command that fixes it."""
    site = settings.site(site_id)
    roi = read_roi(settings, site_id)
    if roi is None:
        raise GateError(
            f"Refusing to score: site '{site_id}' is not prepared.\n"
            f"  python -m terramind prepare --site {site_id}\n"
            f"  (look at data/processed/{site_id}/quicklook.png)\n"
            f"  python -m terramind approve --site {site_id}"
        )
    if roi.get("status") != APPROVED:
        raise GateError(
            f"Refusing to score: site '{site_id}' is '{roi.get('status')}', not approved.\n"
            f"  Look at data/processed/{site_id}/quicklook.png, then run: python -m terramind approve --site {site_id}"
        )
    if roi.get("params_hash") != params_hash(site_params(settings, site)):
        raise GateError(
            f"Refusing to score: site '{site_id}' parameters changed after approval "
            f"(center, window, grid, CRS or dataset). Run prepare and approve again."
        )
    return roi
