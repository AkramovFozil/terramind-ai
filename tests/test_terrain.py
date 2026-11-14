import numpy as np
import pytest

from terramind import terrain


def plane(n=7, dzdx=0.0, dzdy=0.0, res=1.0):
    yy, xx = np.mgrid[0:n, 0:n] * res
    return dzdx * xx + dzdy * yy


def interior(a):
    return a[1:-1, 1:-1]


def test_flat_slope_is_zero():
    assert np.allclose(interior(terrain.slope_deg(np.full((7, 7), 100.0), 463)), 0)


@pytest.mark.parametrize("dzdx,dzdy", [(1.0, 0.0), (0.0, 1.0), (np.sqrt(0.5), np.sqrt(0.5))])
def test_unit_gradient_is_45_degrees(dzdx, dzdy):
    res = 30.0
    s = terrain.slope_deg(plane(9, dzdx, dzdy, res), res)
    assert np.allclose(interior(s), 45.0, atol=0.01)


def test_slope_uses_true_pixel_size():
    z = plane(9, 1.0, 0.0, res=1.0)  # rises 1 m per pixel
    s = terrain.slope_deg(z, 463.0)  # ... over 463 m pixels
    assert np.allclose(interior(s), np.degrees(np.arctan(1 / 463.0)), atol=1e-4)


def test_edges_are_nodata():
    s = terrain.slope_deg(np.zeros((5, 5)), 1.0)
    t = terrain.tri(np.zeros((5, 5)))
    for a in (s, t):
        assert np.isnan(a[0]).all() and np.isnan(a[-1]).all()
        assert np.isnan(a[:, 0]).all() and np.isnan(a[:, -1]).all()
        assert np.isfinite(interior(a)).all()


def test_nan_propagates_to_neighbours():
    z = np.zeros((7, 7))
    z[3, 3] = np.nan
    for a in (terrain.slope_deg(z, 1.0), terrain.tri(z)):
        assert np.isnan(a[2:5, 2:5]).all()
        assert np.isfinite(a[1, 1]) and np.isfinite(a[5, 5])


def test_tri_flat_is_zero():
    assert np.allclose(interior(terrain.tri(np.full((5, 5), 7.0))), 0)


def test_tri_known_pattern():
    z = np.zeros((5, 5))
    z[2, 2] = 8.0  # a spike: centre differs by 8 from all 8 neighbours
    t = terrain.tri(z)
    assert t[2, 2] == pytest.approx(8.0)
    assert t[1, 1] == pytest.approx(1.0)  # corner neighbour sees the spike once: 8 / 8
    z = np.indices((5, 5)).sum(axis=0) % 2 * 2.0  # checkerboard 0/2
    t = terrain.tri(z)
    # 4 edge neighbours differ by 2, 4 diagonal ones by 0 -> mean 1
    assert np.allclose(interior(t), 1.0)


def test_relief_subtracts_median():
    z = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, np.nan]])
    r = terrain.local_relief(z)
    assert np.nanmedian(z) == 4.5
    assert np.allclose(r[0], [-3.5, -2.5, -1.5])
    assert np.isnan(r[2, 2])


def test_relief_refuses_empty():
    with pytest.raises(ValueError):
        terrain.local_relief(np.full((3, 3), np.nan))
