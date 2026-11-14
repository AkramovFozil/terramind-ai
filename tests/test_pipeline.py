"""End to end on synthetic DEMs: prepare -> score refused -> approve -> score -> config change refused."""

import json

import numpy as np
import pytest
import rasterio

from terramind.cli import main
from terramind.config import GateError, load_settings
from terramind.gate import approve, site_state
from terramind.pipeline import prepare, score


def test_full_flow(project, synthetic_mola, synthetic_srtm):
    s = load_settings(project)

    gale = prepare(s, "gale")
    ust = prepare(s, "ustyurt")  # uses the cached synthetic SRTM, no network, no key
    for roi, extra in ((gale, set()), (ust, {"dem_30m"})):
        assert roi["status"] == "pending_review"
        assert roi["quality"]["valid_pixels"] >= 2500
        assert set(roi["files"]) == {"dem", "slope_deg", "relief_m", "tri_m", "quicklook"} | extra
        for f in roi["files"].values():
            assert (project / f).exists()
    assert ust["map_links"]["satellite"].startswith("https://")
    assert gale["input"]["longitude_domain"] == "regional"

    with rasterio.open(project / gale["files"]["dem"]) as src:
        expected = round(s.window_km * 1000 / s.grid_m)
        assert abs(src.width - expected) <= 1 and src.res[0] == pytest.approx(463)
        assert "3396190" in src.crs.to_string()
        dem = src.read(1)
        assert -6000 < np.nanmedian(dem) < -3000  # MOLA-like values survived reprojection
    with rasterio.open(project / ust["files"]["dem_30m"]) as src:
        assert src.res[0] == pytest.approx(30)

    with pytest.raises(GateError, match="not approved"):
        score(s, "gale", "ustyurt")

    approve(s, "gale")
    with pytest.raises(GateError, match="ustyurt"):
        score(s, "gale", "ustyurt")
    approve(s, "ustyurt")

    res = score(s, "gale", "ustyurt")
    out = project / "results" / "gale__ustyurt"
    for name in ("metrics.json", "comparison.csv", "histograms.png"):
        assert (out / name).exists()
    m = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert set(m["overall"]) == {"A", "B"}
    for r in m["per_metric"].values():
        assert 0.0 <= r["score"] <= 1.0
    assert m["rank_stability"]["spearman_rho"] is None
    assert any("MOLA" in c for c in m["caveats"])
    assert res["overall"]["A"]["score"] == m["overall"]["A"]["score"]

    # Moving the center after approval blocks scoring.
    cfg = project / "config" / "sites.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("lon: 56.1800", "lon: 56.2000"), encoding="utf-8")
    s2 = load_settings(project)
    assert site_state(s2, s2.site("ustyurt")) == "stale"
    with pytest.raises(GateError, match="changed after approval"):
        score(s2, "gale", "ustyurt")
    with pytest.raises(GateError, match="changed since prepare"):
        approve(s2, "ustyurt")


def test_cli_exit_codes(project, synthetic_mola, capsys):
    root = str(project)
    assert main(["--root", root, "status"]) == 0
    assert main(["--root", root, "score", "--target", "gale", "--candidate", "ustyurt"]) == 3
    assert main(["--root", root, "prepare", "--site", "kyzylkum"]) == 5  # no center yet
    assert main(["--root", root, "prepare", "--site", "gale"]) == 0
    assert main(["--root", root, "approve", "--site", "gale"]) == 0
    err = capsys.readouterr().err
    assert "Refusing to score" in err


def test_cli_missing_key(project, monkeypatch, capsys):
    monkeypatch.delenv("OPENTOPO_API_KEY", raising=False)
    assert main(["--root", str(project), "prepare", "--site", "ustyurt"]) == 2
    assert "OPENTOPO_API_KEY" in capsys.readouterr().err
