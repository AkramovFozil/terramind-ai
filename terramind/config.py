"""Project settings, site definitions, dataset registry and error types."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


class TerraMindError(Exception):
    """Base error. `exit_code` is what the CLI returns."""

    exit_code = 1


class MissingInputError(TerraMindError):
    exit_code = 2


class GateError(TerraMindError):
    exit_code = 3


class QualityError(TerraMindError):
    exit_code = 4


class ConfigError(TerraMindError):
    exit_code = 5


BODIES = ("earth", "mars")
ROLES = ("reference", "candidate", "validation")

# Provenance for every dataset the pipeline can read.
DATASETS: dict[str, dict] = {
    "MOLA_MEGDR_463m": {
        "body": "mars",
        "name": "Mars MGS MOLA DEM 463m (global mosaic)",
        "provider": "USGS Astrogeology Science Center",
        "source_url": "https://astrogeology.usgs.gov/search/map/mars_mgs_mola_dem_463m",
        "download_url": "https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif",
        "native_resolution_m": 463.0835744,
        "notes": "Simple Cylindrical, Mars sphere R = 3,396,190 m, longitude -180..180, metres.",
    },
    "SRTMGL1": {
        "body": "earth",
        "name": "NASA SRTM Global 1 arc-second (SRTMGL1 v003)",
        "provider": "NASA LP DAAC, served by the OpenTopography Global DEM API",
        "source_url": "https://portal.opentopography.org/API/globaldem",
        "doi": "10.5067/MEaSUREs/SRTM/SRTMGL1.003",
        "native_resolution_m": 30.0,
        "notes": "Coverage 60N-56S. OpenTopography API keys are for non-commercial use.",
    },
}

METRICS = ("slope_deg", "relief_m", "tri_m")


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    body: str
    role: str
    lat: float | None
    lon: float | None
    enabled: bool
    dataset: str
    provisional: bool = False
    note: str = ""
    dem_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    root: Path
    window_km: float
    grid_m: float
    hazard_grid_m: float
    min_valid_pixels: int
    max_nodata_fraction: float
    sites: dict[str, Site]
    bins: dict[str, dict]
    weights: dict[str, dict[str, float]]

    def site(self, site_id: str) -> Site:
        if site_id not in self.sites:
            known = ", ".join(sorted(self.sites))
            raise ConfigError(f"Unknown site '{site_id}'. Known sites: {known}")
        return self.sites[site_id]

    def processed_dir(self, site_id: str) -> Path:
        return self.root / "data" / "processed" / site_id

    def results_dir(self, target_id: str, candidate_id: str) -> Path:
        return self.root / "results" / f"{target_id}__{candidate_id}"

    @property
    def raw_dir(self) -> Path:
        return self.root / "data" / "raw"


def project_root(root: str | os.PathLike | None = None) -> Path:
    return Path(root or os.environ.get("TERRAMIND_ROOT") or Path.cwd()).resolve()


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping")
    return data


def _parse_site(site_id: str, raw: dict) -> Site:
    body = raw.get("body")
    role = raw.get("role")
    dataset = raw.get("dataset")
    if body not in BODIES:
        raise ConfigError(f"Site '{site_id}': body must be one of {BODIES}, got {body!r}")
    if role not in ROLES:
        raise ConfigError(f"Site '{site_id}': role must be one of {ROLES}, got {role!r}")
    if dataset not in DATASETS:
        raise ConfigError(f"Site '{site_id}': unknown dataset {dataset!r}")
    if DATASETS[dataset]["body"] != body:
        raise ConfigError(f"Site '{site_id}': dataset {dataset} is for {DATASETS[dataset]['body']}, not {body}")
    lat, lon = raw.get("lat"), raw.get("lon")
    if lat is not None and not -90 <= float(lat) <= 90:
        raise ConfigError(f"Site '{site_id}': latitude {lat} out of range")
    if lon is not None and not -180 <= float(lon) <= 360:
        raise ConfigError(f"Site '{site_id}': longitude {lon} out of range")
    return Site(
        id=site_id,
        name=str(raw.get("name", site_id)),
        body=body,
        role=role,
        lat=None if lat is None else float(lat),
        lon=None if lon is None else float(lon),
        enabled=bool(raw.get("enabled", False)),
        dataset=dataset,
        provisional=bool(raw.get("provisional", False)),
        note=str(raw.get("note", "") or "").strip(),
        dem_paths=tuple(raw.get("dem_paths", ()) or ()),
    )


def load_settings(root: str | os.PathLike | None = None) -> Settings:
    root_path = project_root(root)
    sites_cfg = _read_yaml(root_path / "config" / "sites.yaml")
    metrics_cfg = _read_yaml(root_path / "config" / "metrics.yaml")

    sites = {sid: _parse_site(sid, raw or {}) for sid, raw in (sites_cfg.get("sites") or {}).items()}
    if not sites:
        raise ConfigError("config/sites.yaml defines no sites")

    bins = metrics_cfg.get("bins") or {}
    weights = metrics_cfg.get("weights") or {}
    for metric in METRICS:
        if metric not in bins:
            raise ConfigError(f"config/metrics.yaml: missing bins for {metric}")
    for name, wset in weights.items():
        if set(wset) != set(METRICS):
            raise ConfigError(f"config/metrics.yaml: weight set {name} must define exactly {METRICS}")
        if sum(float(v) for v in wset.values()) <= 0:
            raise ConfigError(f"config/metrics.yaml: weight set {name} sums to zero")

    return Settings(
        root=root_path,
        window_km=float(sites_cfg.get("window_km", 50)),
        grid_m=float(sites_cfg.get("grid_m", 463)),
        hazard_grid_m=float(sites_cfg.get("hazard_grid_m", 30)),
        min_valid_pixels=int(sites_cfg.get("min_valid_pixels", 2500)),
        max_nodata_fraction=float(sites_cfg.get("max_nodata_fraction", 0.10)),
        sites=sites,
        bins=bins,
        weights={k: {m: float(w) for m, w in v.items()} for k, v in weights.items()},
    )
