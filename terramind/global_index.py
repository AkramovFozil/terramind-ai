"""Global Earth screening index: every land window on the planet, described once.

Built from NOAA ETOPO 2022 60" (about 1.85 km). For each window centre on a
~0.25 degree lattice (lon spacing widened by 1/cos(lat) so centres stay ~28 km
apart) it stores, for a 25 km radius circle:

* coarse histograms of slope, relief and TRI (screening bins), and
* the rotation-invariant polar shape descriptor (terramind.shape).

Each lattice row is resampled along longitude to square ~1852 m pixels by exact
area averaging, so slope and TRI use the same pixel size as the Mars side,
which is the 463 m MOLA grid averaged 4 x 4 (1852 m).

The index only *screens*, comparing equal-radius regional context. For a
different requested search radius it remains a context shortlist, never a
substitute score at that radius. Every reported result is re-measured on
Copernicus GLO-30 at 463 m over the requested circle and re-scored.
"""

from __future__ import annotations

import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from terramind import shape, terrain
from terramind.sources.etopo import ETOPO_PROVENANCE, data_root, etopo_path

INDEX_VERSION = 1
SCREEN_FACTOR = 4                 # Mars 463 m grid -> 1852 m screening grid
SCREEN_PIXEL_M = 463.0 * SCREEN_FACTOR
LAT_STEP_DEG = 0.25
LAT_RANGE = (-56.0, 80.0)          # no Antarctica; Arctic analogs (Devon Island, Svalbard) stay in
MIN_LAND_FRACTION = 0.9
SCREEN_BINS = {
    "slope_deg": {"min": 0, "max": 30, "step": 0.5},
    "relief_m": {"min": -1500, "max": 1500, "step": 50},
    "tri_m": {"min": 0, "max": 300, "step": 5},
}
METERS_PER_ARCSEC_LAT = 30.87  # metres per arc-second of latitude (mean)


def index_dir(cache_dir=None) -> Path:
    return data_root(cache_dir) / "global" / f"earth_index_v{INDEX_VERSION}"


def _edges(spec):
    lo, hi, step = float(spec["min"]), float(spec["max"]), float(spec["step"])
    return lo + step * np.arange(int(round((hi - lo) / step)) + 1)


EDGES = {m: _edges(s) for m, s in SCREEN_BINS.items()}
NBINS = {m: len(e) + 1 for m, e in EDGES.items()}


def histograms(values: np.ndarray, metric: str) -> np.ndarray:
    """Counts per screening bin for each row of `values` (n, P); NaN ignored. uint16."""
    v = np.atleast_2d(values)
    n = v.shape[0]
    nb = NBINS[metric]
    idx = np.searchsorted(EDGES[metric], np.where(np.isfinite(v), v, 0), side="right")
    idx = idx + (np.arange(n)[:, None] * nb)
    flat = idx[np.isfinite(v)]
    return np.bincount(flat, minlength=n * nb).reshape(n, nb).astype(np.uint16)


def _area_resample_row(row: np.ndarray, factor: float) -> np.ndarray:
    """Average `row` into pixels `factor` times wider (exact area weighting; NaN-aware)."""
    n_out = max(int(round(row.size / factor)), 8)
    edges = np.linspace(0, row.size, n_out + 1)
    valid = np.isfinite(row)
    x = np.arange(row.size + 1)
    total = np.interp(edges, x, np.concatenate([[0.0], np.cumsum(np.where(valid, row, 0.0), dtype="float64")]))
    count = np.interp(edges, x, np.concatenate([[0.0], np.cumsum(valid, dtype="float64")]))
    d_total, d_count = np.diff(total), np.diff(count)
    ok = d_count >= 0.5 * np.diff(edges)
    return np.where(ok, d_total / np.maximum(d_count, 1e-12), np.nan).astype("float32")


def _cells_and_offsets(radius_px: float):
    dy, dx = shape.circle_offsets(radius_px)
    return dy, dx, shape.polar_cells(dy, dx, radius_px + 0.5)


def describe_window(dem_s: np.ndarray, inside: np.ndarray) -> dict:
    """Screening descriptors of one square window already on the screening grid (used for Mars)."""
    slope = terrain.slope_deg(dem_s, SCREEN_PIXEL_M)
    tri = terrain.tri(dem_s)
    relief = dem_s - np.nanmedian(dem_s[inside])
    out = {m: histograms(v[inside][None, :], m)[0] for m, v in (("slope_deg", slope), ("relief_m", relief), ("tri_m", tri))}
    out["shape"] = shape.relief_descriptor(np.where(inside, dem_s, np.nan), inside)
    return out


def block_average(dem: np.ndarray, factor: int = SCREEN_FACTOR) -> np.ndarray:
    h, w = (dem.shape[0] // factor) * factor, (dem.shape[1] // factor) * factor
    blocks = dem[:h, :w].reshape(h // factor, factor, w // factor, factor)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN blocks outside the circle stay NaN
        return np.nanmean(blocks, axis=(1, 3)).astype("float32")


def build_index(cache_dir=None, radius_km: float = 25.0, progress=print, lat_range=LAT_RANGE,
                source: Path | None = None, out: Path | None = None) -> Path:
    """Scan ETOPO and write the index folder (npy arrays + meta.json). Takes several minutes.

    `source` may be any north-up EPSG:4326 elevation raster (tests use a small one);
    a source spanning 360 degrees wraps across the antimeridian.
    """
    import rasterio

    src_path = Path(source) if source else etopo_path(cache_dir)
    if not src_path.exists():
        raise FileNotFoundError(f"{src_path} is missing; run `python -m terramind build-index` to download it")
    out = Path(out) if out else index_dir(cache_dir)
    out.mkdir(parents=True, exist_ok=True)
    radius_px = radius_km * 1000.0 / SCREEN_PIXEL_M
    pad = int(math.ceil(radius_px)) + 2
    dy, dx, cells = _cells_and_offsets(radius_px)
    lats, lons, land = [], [], []
    hists = {m: [] for m in SCREEN_BINS}
    descs = []
    with rasterio.open(src_path) as src:
        transform = src.transform
        res_deg = abs(transform.e)
        top, west = transform.f, transform.c
        width = src.width
        span = width * abs(transform.a)
        is_global = span >= 359.9
        south = top - src.height * res_deg
        lo_lat = max(lat_range[0], south + radius_km / 111.0 + res_deg)
        hi_lat = min(lat_range[1], top - radius_km / 111.0 - res_deg)
        centre_lats = np.arange(lo_lat, hi_lat + 1e-9, LAT_STEP_DEG)[::-1]
        for k, lat in enumerate(centre_lats):
            row_c = int(round((top - lat) / res_deg - 0.5))
            lat = top - (row_c + 0.5) * res_deg
            r0, r1 = row_c - pad, row_c + pad + 1
            band = src.read(1, window=((r0, r1), (0, width)), boundless=True, fill_value=np.nan).astype("float32")
            band = np.where(np.isfinite(band) & (band > -20000), band, np.nan) if src.nodata is None else np.where(band == src.nodata, np.nan, band)
            lat_m = METERS_PER_ARCSEC_LAT * res_deg * 3600.0
            lon_m = METERS_PER_ARCSEC_LAT * abs(transform.a) * 3600.0 * math.cos(math.radians(lat))
            factor = SCREEN_PIXEL_M / lon_m
            band = np.vstack([_area_resample_row(r, factor) for r in band])
            ncol = band.shape[1]
            # Rows are lat_m apart; lat_m is within 0.5 % of SCREEN_PIXEL_M for the 60" grid.
            if is_global:
                wrapped = np.hstack([band[:, -pad:], band, band[:, :pad]])
            else:
                edge = np.full((band.shape[0], pad), np.nan, dtype="float32")
                wrapped = np.hstack([edge, band, edge])
            slope = terrain.slope_deg(wrapped, SCREEN_PIXEL_M)
            tri = terrain.tri(wrapped)
            step_px = max(int(round(LAT_STEP_DEG * 111_320 / SCREEN_PIXEL_M)), 1)
            cols = np.arange(0, ncol, step_px)
            cy, cxs = pad, cols + pad
            elev = wrapped[cy + dy[None, :], cxs[:, None] + dx[None, :]]
            land_frac = (elev > 0).mean(axis=1)  # NaN (outside the source) counts as not land
            keep = land_frac >= MIN_LAND_FRACTION
            if keep.any():
                cxs_k = cxs[keep]
                e = elev[keep]
                relief = e - np.median(e, axis=1, keepdims=True)
                hists["relief_m"].append(histograms(relief, "relief_m"))
                hists["slope_deg"].append(histograms(slope[cy + dy[None, :], cxs_k[:, None] + dx[None, :]], "slope_deg"))
                hists["tri_m"].append(histograms(tri[cy + dy[None, :], cxs_k[:, None] + dx[None, :]], "tri_m"))
                descs.append(shape.descriptor_from_cells(relief, cells).astype("float32"))
                lon = west + (cols[keep] + 0.5) * (span / ncol)
                lon = (lon + 180.0) % 360.0 - 180.0
                lats.append(np.full(lon.size, lat))
                lons.append(lon)
                land.append(land_frac[keep])
            if k % 40 == 0:
                progress(f"index row {k + 1}/{len(centre_lats)} lat {lat:.2f}: {sum(map(len, lats))} land windows")
    np.save(out / "lat.npy", np.concatenate(lats).astype("float32"))
    np.save(out / "lon.npy", np.concatenate(lons).astype("float32"))
    np.save(out / "land_fraction.npy", np.concatenate(land).astype("float16"))
    for m, parts in hists.items():
        np.save(out / f"hist_{m}.npy", np.vstack(parts))
    np.save(out / "shape.npy", np.vstack(descs))
    meta = {
        "version": INDEX_VERSION, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windows": int(sum(map(len, lats))), "radius_km": radius_km, "pixel_m": SCREEN_PIXEL_M,
        "lat_step_deg": LAT_STEP_DEG, "lat_range": list(lat_range), "min_land_fraction": MIN_LAND_FRACTION,
        "screen_bins": SCREEN_BINS, "shape": {"rings": shape.RINGS, "sectors": shape.SECTORS, "harmonics": shape.HARMONICS},
        "source": ETOPO_PROVENANCE,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    progress(f"index written: {meta['windows']} land windows -> {out}")
    return out


class EarthIndex:
    """Memory-mapped screening index."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        meta_path = self.folder / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Global Earth index not found at {self.folder}")
        self.meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.lat = np.load(self.folder / "lat.npy")
        self.lon = np.load(self.folder / "lon.npy")
        self.hist = {m: np.load(self.folder / f"hist_{m}.npy", mmap_mode="r") for m in SCREEN_BINS}
        self.shape = np.load(self.folder / "shape.npy", mmap_mode="r")

    def __len__(self):
        return int(self.lat.size)

    @classmethod
    def load(cls, cache_dir=None) -> "EarthIndex":
        return cls(index_dir(cache_dir))

    def screen(self, target: dict, weights: dict, shape_weight: float, chunk: int = 20000) -> np.ndarray:
        """Screening score 0..1 for every window: shape descriptor + weighted histogram overlap."""
        total = sum(weights.values())
        out = np.empty(len(self), dtype="float32")
        p_t = {m: target[m] / max(target[m].sum(), 1) for m in SCREEN_BINS}
        for start in range(0, len(self), chunk):
            stop = min(start + chunk, len(self))
            dist = 0.0
            for m in SCREEN_BINS:
                h = np.asarray(self.hist[m][start:stop], dtype="float32")
                p = h / np.maximum(h.sum(axis=1, keepdims=True), 1)
                dist = dist + weights[m] / total * np.minimum(p, p_t[m][None, :]).sum(axis=1)
            sim = shape.descriptor_similarity(np.asarray(self.shape[start:stop]), target["shape"][None, :])
            out[start:stop] = shape_weight * sim + (1 - shape_weight) * dist
        return out


def pick_spread(lat: np.ndarray, lon: np.ndarray, score: np.ndarray, k: int, min_km: float) -> list[int]:
    """Top-k indices by score, at least `min_km` apart (great-circle) so results are distinct places."""
    order = np.argsort(-score)
    chosen: list[int] = []
    for i in order:
        if len(chosen) >= k:
            break
        if chosen:
            la1, lo1 = np.radians(lat[i]), np.radians(lon[i])
            la2, lo2 = np.radians(lat[chosen]), np.radians(lon[chosen])
            h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
            if (2 * 6371.0 * np.arcsin(np.sqrt(np.minimum(h, 1)))).min() < min_km:
                continue
        chosen.append(int(i))
    return chosen
