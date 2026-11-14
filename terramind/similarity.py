"""Distribution similarity: fixed-bin histograms, histogram intersection, weighted score, rank stability."""

from __future__ import annotations

import numpy as np
from scipy.stats import spearmanr


def bin_edges(spec: dict) -> np.ndarray:
    """Inner bin edges from {min, max, step}. Under/overflow bins are added by `histogram`."""
    lo, hi, step = float(spec["min"]), float(spec["max"]), float(spec["step"])
    if step <= 0 or hi <= lo:
        raise ValueError(f"bad bin spec {spec}")
    n = int(round((hi - lo) / step))
    return lo + step * np.arange(n + 1)


def histogram(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Normalised histogram with an underflow bin (index 0) and an overflow bin (last index)."""
    v = np.asarray(values, dtype="float64").ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        raise ValueError("no valid values to histogram")
    idx = np.searchsorted(edges, v, side="right")  # 0: < edges[0]; len(edges): >= edges[-1]
    counts = np.bincount(idx, minlength=len(edges) + 1).astype("float64")
    return counts / counts.sum()


def intersection(p: np.ndarray, q: np.ndarray) -> float:
    """Histogram intersection of two normalised histograms: 0 = no overlap, 1 = identical."""
    return float(np.minimum(p, q).sum())


def compare_metrics(target: dict, candidate: dict, bins: dict) -> dict:
    """Per metric: score, inner edges and both histograms."""
    out = {}
    for metric, spec in bins.items():
        edges = bin_edges(spec)
        p_t = histogram(target[metric], edges)
        p_c = histogram(candidate[metric], edges)
        out[metric] = {"score": intersection(p_t, p_c), "edges": edges, "p_target": p_t, "p_candidate": p_c}
    return out


def weighted_score(scores: dict, weights: dict) -> float:
    """Weighted mean of metric scores; weights are normalised by their sum."""
    if set(scores) != set(weights):
        raise ValueError(f"metrics {sorted(scores)} do not match weights {sorted(weights)}")
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("weights sum to zero")
    return float(sum(scores[m] * weights[m] for m in scores) / total)


def rank_stability(scores_a: dict, scores_b: dict) -> float:
    """Spearman correlation of two {site: score} rankings. Needs at least 3 sites."""
    keys = sorted(scores_a)
    if set(keys) != set(scores_b):
        raise ValueError("both rankings must cover the same sites")
    if len(keys) < 3:
        raise ValueError("rank stability needs at least 3 approved sites")
    rho = spearmanr([scores_a[k] for k in keys], [scores_b[k] for k in keys]).statistic
    return float(rho)
