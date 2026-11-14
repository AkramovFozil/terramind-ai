"""Analysis windows (ROI) and target grids in a site's local metric CRS."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pyproj import Transformer
from rasterio.crs import CRS as RioCRS
from rasterio.transform import Affine, from_origin

from terramind.crs import geographic_crs_string, local_crs_string


@dataclass(frozen=True)
class Grid:
    """A square raster grid centred on (0, 0) of a local AEQD projection."""

    crs_string: str
    transform: Affine
    width: int
    height: int
    res_m: float
    center_lat: float
    center_lon: float

    @property
    def crs(self) -> RioCRS:
        return RioCRS.from_string(self.crs_string)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)

    @property
    def half_extent_m(self) -> float:
        return self.width * self.res_m / 2.0


def make_grid(body: str, lat: float, lon: float, window_km: float, res_m: float) -> Grid:
    """Square window of `window_km` centred on the site, with pixels of `res_m` metres."""
    n = int(round(window_km * 1000.0 / res_m))
    if n < 3:
        raise ValueError(f"window {window_km} km is too small for {res_m} m pixels")
    half = n * res_m / 2.0
    return Grid(
        crs_string=local_crs_string(body, lat, lon),
        transform=from_origin(-half, half, res_m, res_m),
        width=n,
        height=n,
        res_m=float(res_m),
        center_lat=float(lat),
        center_lon=float(lon),
    )


def geographic_bounds(grid: Grid, body: str, margin: float = 0.05, samples: int = 64) -> tuple[float, float, float, float]:
    """(west, south, east, north) in degrees covering the grid, padded by `margin` of the span.

    Edges are densified, because a square in AEQD is not a rectangle in lon/lat.
    """
    transformer = Transformer.from_crs(grid.crs_string, geographic_crs_string(body), always_xy=True)
    h = grid.half_extent_m
    s = np.linspace(-h, h, samples)
    xs = np.concatenate([s, s, np.full(samples, -h), np.full(samples, h)])
    ys = np.concatenate([np.full(samples, -h), np.full(samples, h), s, s])
    lon, lat = transformer.transform(xs, ys)
    west, east = float(np.min(lon)), float(np.max(lon))
    south, north = float(np.min(lat)), float(np.max(lat))
    dx, dy = (east - west) * margin, (north - south) * margin
    return west - dx, south - dy, east + dx, north + dy
