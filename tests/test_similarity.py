import numpy as np
import pytest

from terramind import similarity as sim

SLOPE = {"min": 0, "max": 45, "step": 0.5}


def test_bin_edges():
    e = sim.bin_edges(SLOPE)
    assert len(e) == 91 and e[0] == 0 and e[-1] == 45


def test_histogram_has_under_and_overflow():
    e = sim.bin_edges({"min": 0, "max": 10, "step": 1})
    p = sim.histogram(np.array([-5, 0, 9.99, 10, 50, np.nan]), e)
    assert p.sum() == pytest.approx(1.0)
    assert p[0] == pytest.approx(0.2)  # -5
    assert p[-1] == pytest.approx(0.4)  # 10 and 50
    assert len(p) == len(e) + 1


def test_identical_is_one():
    rng = np.random.default_rng(0)
    v = rng.uniform(0, 30, 5000)
    e = sim.bin_edges(SLOPE)
    assert sim.intersection(sim.histogram(v, e), sim.histogram(v, e)) == pytest.approx(1.0)


def test_disjoint_is_zero():
    e = sim.bin_edges(SLOPE)
    p = sim.histogram(np.full(100, 2.0), e)
    q = sim.histogram(np.full(100, 30.0), e)
    assert sim.intersection(p, q) == 0.0


def test_partial_overlap():
    e = sim.bin_edges({"min": 0, "max": 4, "step": 1})
    p = sim.histogram(np.array([0.5, 1.5]), e)
    q = sim.histogram(np.array([1.5, 2.5]), e)
    assert sim.intersection(p, q) == pytest.approx(0.5)


def test_weighted_score_normalises():
    s = {"slope_deg": 1.0, "relief_m": 0.0, "tri_m": 0.5}
    assert sim.weighted_score(s, {"slope_deg": 0.4, "relief_m": 0.35, "tri_m": 0.25}) == pytest.approx(0.525)
    assert sim.weighted_score(s, {"slope_deg": 1, "relief_m": 1, "tri_m": 1}) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        sim.weighted_score(s, {"slope_deg": 1})


def test_rank_stability():
    a = {"x": 0.9, "y": 0.5, "z": 0.1}
    assert sim.rank_stability(a, {"x": 0.8, "y": 0.6, "z": 0.2}) == pytest.approx(1.0)
    assert sim.rank_stability(a, {"x": 0.1, "y": 0.5, "z": 0.9}) == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        sim.rank_stability({"x": 1, "y": 2}, {"x": 1, "y": 2})
