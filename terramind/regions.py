"""Search regions: definitions, tile download (OpenTopography) and a VRT mosaic of the tiles."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import rasterio
import yaml

from terramind.config import ConfigError, Settings
from terramind.sources.opentopo import fetch_srtm

GDAL_TYPES = {"int16": "Int16", "uint16": "UInt16", "int32": "Int32", "float32": "Float32", "float64": "Float64"}
EARTH_KM_PER_DEG = 111.32


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    bbox: tuple[float, float, float, float]  # west, south, east, north
    stride_km: float
    note: str = ""
    demtype: str = "SRTMGL3"
    tile_deg: float = 3.0


def load_regions(settings: Settings) -> dict[str, Region]:
    path = settings.root / "config" / "regions.yaml"
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = {}
    for rid, r in (raw.get("regions") or {}).items():
        try:
            w, s, e, n = (float(v) for v in r["bbox"])
        except (KeyError, TypeError, ValueError):
            raise ConfigError(f"Region '{rid}': bbox must be [west, south, east, north]") from None
        if not (-180 <= w < e <= 180 and -60 <= s < n <= 60):
            raise ConfigError(f"Region '{rid}': bbox {r['bbox']} is invalid or outside SRTM coverage (60 N - 60 S)")
        out[rid] = Region(
            id=rid,
            name=str(r.get("name", rid)),
            bbox=(w, s, e, n),
            stride_km=float(r.get("stride_km", 12.5)),
            note=str(r.get("note", "") or ""),
            demtype=str(r.get("demtype", "SRTMGL3")),
            tile_deg=float(r.get("tile_deg", 3.0)),
        )
    if not out:
        raise ConfigError("config/regions.yaml defines no regions")
    return out


def get_region(settings: Settings, region_id: str) -> Region:
    regions = load_regions(settings)
    if region_id not in regions:
        raise ConfigError(f"Unknown region '{region_id}'. Known regions: {', '.join(sorted(regions))}")
    return regions[region_id]


def tile_bounds(region: Region) -> list[tuple[float, float, float, float]]:
    w, s, e, n = region.bbox
    nx = max(1, math.ceil((e - w) / region.tile_deg - 1e-9))
    ny = max(1, math.ceil((n - s) / region.tile_deg - 1e-9))
    tiles = []
    for j in range(ny):
        for i in range(nx):
            tw = w + i * region.tile_deg
            ts = s + j * region.tile_deg
            tiles.append((round(tw, 6), round(ts, 6), round(min(tw + region.tile_deg, e), 6), round(min(ts + region.tile_deg, n), 6)))
    return tiles


def region_dir(settings: Settings, region: Region) -> Path:
    return settings.raw_dir / "earth" / "regions" / region.id


def _retile(path: Path) -> None:
    """Rewrite a downloaded GeoTIFF as tiled + compressed so window reads are fast."""
    with rasterio.open(path) as src:
        if src.profile.get("tiled"):
            return
        data = src.read(1)
        profile = src.profile.copy()
    profile.update(tiled=True, blockxsize=256, blockysize=256, compress="deflate")
    tmp = path.with_name(path.name + ".tiled")
    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(data, 1)
    tmp.replace(path)


def fetch_region(settings: Settings, region: Region, api_key: str | None, session=None, progress=None) -> Path:
    """Download (or reuse) every tile of the region and return a VRT mosaic over them."""
    out = region_dir(settings, region)
    paths = []
    tiles = tile_bounds(region)
    for k, (w, s, e, n) in enumerate(tiles, 1):
        dest = out / f"{region.demtype}_{w:.3f}_{s:.3f}_{e:.3f}_{n:.3f}.tif"
        cached = dest.exists()
        if progress:
            progress(f"tile {k}/{len(tiles)} {'cached' if cached else 'downloading'}: {w:.2f},{s:.2f} .. {e:.2f},{n:.2f}")
        fetch_srtm((w, s, e, n), dest, api_key, session=session, demtype=region.demtype)
        if not cached:
            _retile(dest)
        paths.append(dest)
    vrt = out / f"{region.demtype}_mosaic.vrt"
    build_vrt(paths, vrt)
    return vrt


def build_vrt(paths: list[Path], vrt: Path) -> Path:
    """Minimal GDAL VRT mosaic of tiles that share one CRS and pixel size."""
    infos = []
    for p in paths:
        with rasterio.open(p) as src:
            infos.append((p, src.transform, src.width, src.height, src.crs, src.nodata, src.dtypes[0]))
    t0 = infos[0][1]
    rx, ry = t0.a, -t0.e
    crs, nodata, dtype = infos[0][4], infos[0][5], infos[0][6]
    for p, t, *_rest in infos:
        if not (math.isclose(t.a, rx, rel_tol=1e-6) and math.isclose(-t.e, ry, rel_tol=1e-6)):
            raise ConfigError(f"Tile {p.name} has a different pixel size; cannot mosaic")
    x0 = min(t.c for _, t, *_ in infos)
    y0 = max(t.f for _, t, *_ in infos)
    x1 = max(t.c + w * rx for _, t, w, *_ in infos)
    y1 = min(t.f - h * ry for _, t, _, h, *_ in infos)
    width, height = int(round((x1 - x0) / rx)), int(round((y0 - y1) / ry))
    nd = "" if nodata is None else f"<NoDataValue>{nodata:g}</NoDataValue>"
    sources = []
    for p, t, w, h, *_ in infos:
        dx, dy = (t.c - x0) / rx, (y0 - t.f) / ry
        if abs(dx - round(dx)) > 0.01 or abs(dy - round(dy)) > 0.01:
            raise ConfigError(f"Tile {p.name} is not aligned to the common pixel grid; cannot mosaic")
        src_nd = "" if nodata is None else f"<NODATA>{nodata:g}</NODATA>"
        sources.append(
            f'    <ComplexSource><SourceFilename relativeToVRT="1">{escape(p.name)}</SourceFilename>'
            f"<SourceBand>1</SourceBand>"
            f'<SrcRect xOff="0" yOff="0" xSize="{w}" ySize="{h}"/>'
            f'<DstRect xOff="{int(round(dx))}" yOff="{int(round(dy))}" xSize="{w}" ySize="{h}"/>{src_nd}</ComplexSource>'
        )
    xml = (
        f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}">\n'
        f"  <SRS>{escape(crs.to_wkt())}</SRS>\n"
        f"  <GeoTransform>{x0!r}, {rx!r}, 0.0, {y0!r}, 0.0, {-ry!r}</GeoTransform>\n"
        f'  <VRTRasterBand dataType="{GDAL_TYPES[np.dtype(dtype).name]}" band="1">\n'
        f"    {nd}\n" + "\n".join(sources) + "\n  </VRTRasterBand>\n</VRTDataset>\n"
    )
    vrt.parent.mkdir(parents=True, exist_ok=True)
    vrt.write_text(xml, encoding="utf-8")
    return vrt


def window_centers(region: Region, window_km: float, stride_km: float | None = None) -> list[tuple[float, float]]:
    """Window centers on rows of constant latitude, spaced `stride_km`, whole window inside the bbox."""
    w, s, e, n = region.bbox
    stride = stride_km or region.stride_km
    half = window_km / 2.0 * 1.02  # small margin so the AEQD square stays inside the box
    dlat = stride / EARTH_KM_PER_DEG
    inset_lat = half / EARTH_KM_PER_DEG
    centers = []
    lat = s + inset_lat
    while lat <= n - inset_lat + 1e-9:
        kx = EARTH_KM_PER_DEG * math.cos(math.radians(lat))
        dlon, inset_lon = stride / kx, half / kx
        lon = w + inset_lon
        while lon <= e - inset_lon + 1e-9:
            centers.append((round(lat, 5), round(lon, 5)))
            lon += dlon
        lat += dlat
    return centers
