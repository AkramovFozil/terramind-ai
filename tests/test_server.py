"""Web platform API: overview, search view, reviews, file access limits, ask without a key."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from terramind.config import load_settings
from terramind.gate import approve
from terramind.pipeline import prepare
from terramind.search import search
from terramind.server import make_handler
from tests.test_search import FakeOpenTopo


@pytest.fixture
def server(project, synthetic_mola, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    (project / "config" / "regions.yaml").write_text(
        "regions:\n  testland:\n    name: Test land\n    bbox: [56.0, 43.4, 56.6, 43.9]\n    stride_km: 5\n    tile_deg: 0.3\n",
        encoding="utf-8")
    s = load_settings(project)
    prepare(s, "gale")
    approve(s, "gale")
    search(s, "gale", "testland", api_key="key", session=FakeOpenTopo(), top_n=3)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(s))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_pages_and_overview(server):
    code, ctype, body = get(server + "/")
    assert code == 200 and "text/html" in ctype and b"TerraMind AI" in body
    assert get(server + "/static/app.js")[0] == 200
    ov = json.loads(get(server + "/api/overview")[2])
    assert {s["id"] for s in ov["sites"]} >= {"gale", "ustyurt", "mouton"}
    assert [x["id"] for x in ov["searches"]] == ["gale__testland"]
    assert ov["ai_available"] is False


def test_search_view_and_reviews(server):
    s = json.loads(get(server + "/api/search?id=gale__testland")[2])
    assert s["windows"] and len(s["windows"][0]) == 3 and len(s["top"]) <= 3
    lead = s["top"][0]
    code, r = post(server + "/api/review", {"search_id": "gale__testland", "lat": lead["lat"], "lon": lead["lon"],
                                            "verdict": "rejected", "note": "open-pit mine"})
    assert code == 200 and list(r["reviews"].values())[0]["verdict"] == "rejected"
    s = json.loads(get(server + "/api/search?id=gale__testland")[2])
    assert list(s["reviews"].values())[0]["note"] == "open-pit mine"
    assert post(server + "/api/review", {"search_id": "../x", "lat": 0, "lon": 0, "verdict": "accepted"})[0] == 400


def test_files_are_limited_to_results(server):
    assert get(server + "/files/results/search/gale__testland/map.png")[0] == 200
    for bad in ("/files/config/sites.yaml", "/files/.env", "/files/results/../config/sites.yaml", "/static/../server.py"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(server + bad)
        assert e.value.code == 404


def test_ask_without_key_is_a_clear_error(server):
    code, r = post(server + "/api/ask", {"question": "Why?"})
    assert code == 400 and "OPENROUTER_API_KEY" in r["error"]
