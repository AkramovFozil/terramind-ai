"""The matrix refuses until every enabled site is approved, then reports every cell."""

import json
import shutil

import pytest
import yaml

from terramind.cli import main
from terramind.config import GateError, load_settings
from terramind.gate import approve
from terramind.pipeline import matrix, prepare
from terramind.sources.opentopo import srtm_cache_path


def _edit_sites(project, fn):
    path = project / "config" / "sites.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(cfg["sites"])
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def test_matrix_refuses_until_all_enabled_sites_are_approved(project, synthetic_mola, synthetic_srtm):
    s = load_settings(project)
    for site in ("gale", "ustyurt"):
        prepare(s, site)
        approve(s, site)
    with pytest.raises(GateError) as e:
        matrix(s)
    for missing in ("meridiani", "mouton", "yungay", "mdrs"):
        assert missing in str(e.value)


def test_matrix_reports_every_cell_and_rank_stability(project, synthetic_mola, synthetic_srtm):
    # Keep Gale as the only Mars reference; add two more Earth sites on the same synthetic DEM
    # so that rank stability (>= 3 Earth sites) is computed.
    def edit(sites):
        for sid in ("meridiani", "mouton", "yungay", "mdrs"):
            sites[sid]["enabled"] = False
        for sid, dlat in (("ust_b", 0.05), ("ust_c", -0.05)):
            sites[sid] = dict(sites["ustyurt"], name=f"Test {sid}", role="validation", lat=sites["ustyurt"]["lat"] + dlat)

    _edit_sites(project, edit)
    s = load_settings(project)
    for sid in ("ust_b", "ust_c"):
        dest = srtm_cache_path(s, s.site(sid))
        shutil.copy(synthetic_srtm, dest)
    for sid in ("gale", "ustyurt", "ust_b", "ust_c"):
        prepare(s, sid)
        approve(s, sid)

    res = matrix(s)
    assert len(res["cells"]) == 3
    for cell in res["cells"].values():
        for v in cell["overall"].values():
            assert 0.0 <= v <= 1.0
    rho = res["rank_stability"]["gale"]["spearman_rho"]
    assert rho is not None and -1.0 <= rho <= 1.0
    out = project / "results" / "matrix"
    for name in ("matrix.json", "matrix.csv", "matrix.png"):
        assert (out / name).exists()
    assert json.loads((out / "matrix.json").read_text(encoding="utf-8"))["cells"].keys() == res["cells"].keys()
    assert main(["--root", str(project), "matrix"]) == 0
