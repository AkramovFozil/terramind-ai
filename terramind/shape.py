"""Spatial shape similarity: does the terrain have the same *form*, not only the same statistics?

Histogram overlap alone cannot tell a crater (a bowl) from a volcano (a cone):
both have steep slopes and a wide spread of heights. Two complementary
measures fix that, and both work on relief = elevation minus the circle median.

* A rotation- and mirror-invariant polar descriptor: the circle is split into
  rings and sectors; for each ring the sector means are Fourier transformed.
  Harmonic 0 (signed) is the radial profile (bowl: negative centre, positive
  rim; cone: the opposite). Harmonics 1..4 (magnitudes) describe one-sided
  slopes, valleys and ridges. Cheap enough for the global screening index.
* A pattern correlation: the Mars relief map is rotated (every 15 degrees,
  plus mirror images) and correlated with the Earth relief map. The best
  Pearson correlation says how well the two landforms overlay.

Both are terrain-shape measures, not geology.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

RINGS = 8
SECTORS = 16
HARMONICS = 5  # 0 (signed radial profile) .. 4
ROTATION_STEP_DEG = 15


def circle_offsets(radius_px: float) -> tuple[np.ndarray, np.ndarray]:
    """Integer (dy, dx) offsets of the pixels whose centres lie inside the circle."""
    r = int(np.floor(radius_px))
    dy, dx = np.mgrid[-r:r + 1, -r:r + 1]
    keep = dy ** 2 + dx ** 2 <= radius_px ** 2
    return dy[keep].astype(np.int32), dx[keep].astype(np.int32)


def polar_cells(dy: np.ndarray, dx: np.ndarray, radius: float) -> np.ndarray:
    """Ring-sector cell index for each pixel offset (row offset dy grows southwards)."""
    r = np.hypot(dy, dx) / radius
    ring = np.minimum((r * RINGS).astype(int), RINGS - 1)
    angle = np.mod(np.arctan2(-dy, dx), 2 * np.pi)
    sector = np.minimum((angle / (2 * np.pi) * SECTORS).astype(int), SECTORS - 1)
    return ring * SECTORS + sector


def descriptor_from_cells(relief: np.ndarray, cells: np.ndarray) -> np.ndarray:
    """Polar descriptor for one or many windows.

    relief: (P,) or (n, P) relief values (NaN allowed) in the pixel order of `cells`.
    Returns (RINGS*HARMONICS,) or (n, RINGS*HARMONICS) in metres.
    """
    values = np.atleast_2d(np.asarray(relief, dtype="float64"))
    n = values.shape[0]
    finite = np.isfinite(values)
    ncell = RINGS * SECTORS
    onehot = np.zeros((cells.size, ncell))
    onehot[np.arange(cells.size), cells] = 1.0
    sums = np.where(finite, values, 0.0) @ onehot
    counts = finite.astype("float64") @ onehot
    means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
    spectrum = np.fft.rfft(means.reshape(n, RINGS, SECTORS), axis=-1)[..., :HARMONICS] / SECTORS
    feats = np.abs(spectrum)
    feats[..., 0] = spectrum[..., 0].real  # keep the sign: bowl versus dome
    feats = feats.reshape(n, RINGS * HARMONICS)
    return feats[0] if np.ndim(relief) == 1 else feats


def descriptor_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """0..1. Identical shape and size = 1; inverted shape (bowl vs dome) = 0."""
    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    dist = np.linalg.norm(a - b, axis=-1)
    scale = np.linalg.norm(a, axis=-1) + np.linalg.norm(b, axis=-1)
    return np.clip(1.0 - dist / np.maximum(scale, 1e-9), 0.0, 1.0)


def relief_descriptor(dem: np.ndarray, inside: np.ndarray) -> np.ndarray:
    """Polar descriptor of a 2-D window; the circle centre is the array centre."""
    h, w = dem.shape
    yy, xx = np.nonzero(inside)
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    radius = max(np.hypot(yy - cy, xx - cx).max(), 1.0)
    cells = polar_cells(yy - cy, xx - cx, radius + 0.5)
    values = dem[yy, xx].astype("float64")
    values = values - np.nanmedian(values)
    return descriptor_from_cells(values, cells)


class PatternMatcher:
    """Rotated and mirrored Mars relief templates for a fixed square grid size.

    `score(window)` returns the best Pearson correlation (clipped to 0..1) and the
    rotation that produced it. Windows must have the template's shape.
    """

    def __init__(self, dem: np.ndarray, inside: np.ndarray, step_deg: int = ROTATION_STEP_DEG):
        h, w = dem.shape
        cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
        yy, xx = np.mgrid[0:h, 0:w]
        radius = np.hypot(yy[inside] - cy, xx[inside] - cx).max()
        # Rotation pulls in pixels from outside the circle; evaluate a slightly smaller disc.
        self.mask = np.hypot(yy - cy, xx - cx) <= radius * 0.96
        self.shape = dem.shape
        relief = np.where(inside, dem - np.nanmedian(dem[inside]), np.nan).astype("float64")
        filled = np.where(np.isfinite(relief), relief, 0.0)
        templates, labels = [], []
        for mirror in (False, True):
            base = filled[:, ::-1] if mirror else filled
            for angle in range(0, 360, step_deg):
                rotated = ndimage.rotate(base, angle, reshape=False, order=1, mode="nearest") if angle else base
                v = rotated[self.mask]
                v = v - v.mean()
                norm = np.linalg.norm(v)
                templates.append(v / norm if norm > 0 else v)
                labels.append({"rotation_deg": angle, "mirrored": mirror})
        self.templates = np.asarray(templates)
        self.labels = labels

    def correlations(self, window: np.ndarray) -> np.ndarray:
        if window.shape != self.shape:
            raise ValueError(f"window shape {window.shape} does not match template {self.shape}")
        v = window[self.mask].astype("float64")
        finite = np.isfinite(v)
        if finite.sum() < 0.8 * v.size:
            return np.zeros(len(self.templates))
        v = np.where(finite, v, np.nanmean(v))
        v = v - v.mean()
        norm = np.linalg.norm(v)
        if norm == 0:
            return np.zeros(len(self.templates))
        return self.templates @ (v / norm)

    def score(self, window: np.ndarray) -> tuple[float, dict]:
        corr = self.correlations(window)
        best = int(np.argmax(corr))
        return float(np.clip(corr[best], 0.0, 1.0)), dict(self.labels[best], correlation=round(float(corr[best]), 4))
