"""Terrain metrics on a square-pixel grid. Identical code for Earth and Mars.

Cells without a full valid 3x3 neighbourhood (edges, next to nodata) become NaN.
Nothing is filled or invented.
"""

from __future__ import annotations

import numpy as np


def _neighbourhood(z: np.ndarray):
    """The 3x3 neighbours of every cell, as views (a b c / d e f / g h i)."""
    p = np.pad(np.asarray(z, dtype="float64"), 1, mode="constant", constant_values=np.nan)
    return (
        p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:],
        p[1:-1, :-2], p[1:-1, 1:-1], p[1:-1, 2:],
        p[2:, :-2], p[2:, 1:-1], p[2:, 2:],
    )


def slope_deg(z: np.ndarray, res_m: float) -> np.ndarray:
    """Slope in degrees, Horn (1981) 3x3 method, `res_m` = pixel size in metres."""
    a, b, c, d, e, f, g, h, i = _neighbourhood(z)
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * res_m)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8.0 * res_m)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    slope[~np.isfinite(e)] = np.nan  # Horn ignores the centre cell; a nodata centre is still nodata
    return slope.astype("float32")


def tri(z: np.ndarray) -> np.ndarray:
    """Terrain Ruggedness Index: mean absolute difference to the 8 neighbours, metres."""
    a, b, c, d, e, f, g, h, i = _neighbourhood(z)
    neighbours = np.stack([a, b, c, d, f, g, h, i])
    return np.mean(np.abs(neighbours - e), axis=0).astype("float32")


def local_relief(z: np.ndarray) -> np.ndarray:
    """Elevation minus the window median, metres (each planet has its own zero level)."""
    z = np.asarray(z, dtype="float64")
    if not np.isfinite(z).any():
        raise ValueError("no valid elevation values")
    return (z - np.nanmedian(z)).astype("float32")


def summary(values: np.ndarray) -> dict:
    """p5, median and p95 of the valid values, rounded for reports."""
    v = np.asarray(values, dtype="float64")
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"p5": None, "median": None, "p95": None, "count": 0}
    p5, med, p95 = np.percentile(v, [5, 50, 95])
    return {"p5": round(float(p5), 3), "median": round(float(med), 3), "p95": round(float(p95), 3), "count": int(v.size)}
