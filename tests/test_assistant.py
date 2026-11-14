"""AI assistant flow: reference first, then Earth analogs; Moon map and 3D terrain payloads."""

import json

import pytest
from fastapi.testclient import TestClient

from terramind.assistant import chat, point_terrain, reference_map, site_terrain
from terramind.config import load_settings
from terramind.gate import approve
from terramind.pipeline import prepare
from terramind.search import search
from tests.test_explain import FakeResponse, SequenceSession, reply
from tests.test_search import FakeOpenTopo

REGIONS = "regions:\n  testland:\n    name: Test land\n    bbox: [56.0, 43.4, 56.6, 43.9]\n    stride_km: 5\n    tile_deg: 0.3\n"


@pytest.fixture
def moon_project(project, synthetic_lola):
    (project / "config" / "regions.yaml").write_text(REGIONS, encoding="utf-8")
    s = load_settings(project)
    prepare(s, "mouton")
    approve(s, "mouton")
    return project


def tool_call(cid, name, args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def test_chat_marks_reference_then_finds_earth_analogs(moon_project):
    s = load_settings(moon_project)
    res_search = search(s, "mouton", "testland", api_key="key", session=FakeOpenTopo(), top_n=3)
    lead = res_search["top"][0]
    session = SequenceSession(
        FakeResponse(200, {"choices": [{"message": {"content": None, "tool_calls": [tool_call("c1", "show_reference", {"reference": "mouton"})]}}]}),
        FakeResponse(200, {"choices": [{"message": {"content": None, "tool_calls": [tool_call("c2", "find_earth_analogs", {"reference": "mouton", "region": "testland"})]}}]}),
        reply(f"Best lead {lead['lat']:.4f}, {lead['lon']:.4f} scores {lead['overall_A']:.2f}. Review it on imagery. It is 0.99 lunar."),
    )
    out = chat(s, "Oydagi LOLA relyefiga mos joyni Yerdan top", "key", session=session,
               search_fn=lambda ref, reg: res_search)
    assert [st["kind"] for st in out["steps"]] == ["reference", "search"]
    assert out["steps"][0]["reference"]["body"] == "moon"
    assert out["steps"][1]["search_id"] == "mouton__testland" and out["steps"][1]["top"]
    assert out["unverified_numbers"] == ["0.99"]
    first = session.calls[0]
    names = [t["function"]["name"] for t in first["tools"]]
    assert names == ["show_reference", "find_earth_analogs"]
    assert first["tools"][0]["function"]["parameters"]["properties"]["reference"]["enum"] == ["mouton"]


def test_moon_map_marks_the_site(moon_project):
    s = load_settings(moon_project)
    m = reference_map(s, "mouton")
    assert m["kind"] == "polar" and 0 < m["marker"]["x"] < 1 and 0 < m["marker"]["y"] < 1
    assert m["box"]["x0"] < m["marker"]["x"] < m["box"]["x1"]
    assert (moon_project / "data" / "processed" / "maps" / "moon_south_pole.png").exists()


def test_terrain_payloads_for_compare_view(moon_project):
    s = load_settings(moon_project)
    t = site_terrain(s, "mouton")
    assert t["body"] == "moon" and t["width"] == round(s.window_km * 1000 / s.grid_m)
    assert len(t["elevations"]) == t["width"] * t["height"] and t["measured_dem"]
    search(s, "mouton", "testland", api_key="key", session=FakeOpenTopo())
    e = point_terrain(s, "testland", 43.65, 56.3)
    assert e["body"] == "earth" and set(e["layers"]) == {"slope_deg", "roughness_m"}


def test_routes(moon_project, monkeypatch):
    monkeypatch.setenv("TERRAMIND_ROOT", str(moon_project))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from terramind.api import create_app

    class Dummy:
        def close(self):
            pass

    client = TestClient(create_app(service=Dummy(), serve_frontend=False))
    ov = client.get("/api/tm/overview").json()
    assert [r["id"] for r in ov["references"]] == ["mouton"]
    ref = client.get("/api/tm/reference/mouton").json()
    assert ref["map"]["kind"] == "polar"
    assert client.get(ref["map"]["image"]).status_code == 200
    assert client.get("/api/tm/terrain/site/mouton").status_code == 200
    img = client.get("/api/tm/window-image/mouton.png")
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert client.get("/api/tm/window-image/nope.png").status_code == 404
    assert ov["pending_references"] == [] or all(p["state"] != "approved" for p in ov["pending_references"])
    r = client.post("/api/tm/chat", json={"question": "find"})
    assert r.status_code == 400 and "OPENROUTER_API_KEY" in r.json()["detail"]
