"""AI explanation layer: grounding check, key safety, context loading."""

import shutil
from pathlib import Path

import pytest

from terramind.config import MissingInputError, load_settings
from terramind.explain import ask, load_context, unverified_numbers

REPO = Path(__file__).resolve().parents[1]
FAKE_KEY = "sk-or-test-0123456789abcdef"


class FakeResponse:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def post(self, url, headers, json, timeout):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.resp


def reply(text):
    return FakeResponse(200, {"choices": [{"message": {"content": text}}]})


@pytest.fixture
def with_results(project):
    shutil.copytree(REPO / "docs" / "results", project / "docs" / "results")
    return load_settings(project)


def test_context_has_matrix_and_pairs(with_results):
    ctx = load_context(with_results)
    assert ctx["matrix"]["cells"]["meridiani__ustyurt"]["overall"]["A"] == pytest.approx(0.7391)
    assert "gale__ustyurt" in ctx["pairs"]
    assert any("Meridiani" in x for x in ctx["limits"])


def test_grounding_accepts_real_numbers_and_flags_invented_ones():
    ctx = {"cells": {"x": {"overall": {"A": 0.7391}}}, "slope": {"median": 1.443}}
    assert unverified_numbers("Ustyurt scores 0.74 (74%) and Gale's median slope is 1.4°.", ctx) == []
    assert unverified_numbers("Ustyurt scores 0.93.", ctx) == ["0.93"]
    assert unverified_numbers("That is a 91% match.", ctx) == ["91%"]


def test_ask_sends_context_and_checks_answer(with_results):
    session = FakeSession(reply("Ustyurt vs Meridiani: 0.74 (A). Against Gale it is 0.12. Probability of water: 0.55."))
    res = ask(with_results, "Why?", FAKE_KEY, session=session)
    assert res["unverified_numbers"] == ["0.55"]
    sent = session.calls[0]
    assert sent["url"].startswith("https://openrouter.ai/")
    assert sent["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    assert "CONTEXT" in sent["json"]["messages"][1]["content"]
    assert sent["json"]["messages"][-1] == {"role": "user", "content": "Why?"}
    assert 0 < sent["json"]["max_tokens"] <= 2000  # never ask for the model maximum (HTTP 402 on small balances)


def test_payment_error_gives_a_hint(with_results):
    session = FakeSession(FakeResponse(402, text="This request requires more credits"))
    with pytest.raises(MissingInputError, match="gpt-4o-mini"):
        ask(with_results, "Why?", FAKE_KEY, session=session)


def test_missing_key(with_results):
    with pytest.raises(MissingInputError, match="OPENROUTER_API_KEY"):
        ask(with_results, "Why?", None)


def test_errors_never_leak_the_key(with_results):
    session = FakeSession(FakeResponse(401, text=f"bad key {FAKE_KEY}"))
    with pytest.raises(MissingInputError) as e:
        ask(with_results, "Why?", FAKE_KEY, session=session)
    assert FAKE_KEY not in str(e.value) and "***" in str(e.value)


def test_no_results_yet(project):
    with pytest.raises(MissingInputError, match="matrix"):
        load_context(load_settings(project))


class SequenceSession:
    """Returns the queued responses in order and records every request."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, headers, json, timeout):
        self.calls.append(json)
        return self.responses.pop(0)


def test_ai_can_call_the_search_tool(project, synthetic_mola):
    from terramind.gate import approve
    from terramind.pipeline import prepare

    (project / "config" / "regions.yaml").write_text(
        "regions:\n  testland:\n    name: Test land\n    bbox: [56.0, 43.4, 56.6, 43.9]\n    stride_km: 5\n",
        encoding="utf-8")
    s = load_settings(project)
    prepare(s, "gale")
    approve(s, "gale")

    fake_result = {
        "reference": {"id": "gale", "name": "Gale Crater (Aeolis Palus)", "params_hash": "x"},
        "region": {"id": "testland", "name": "Test land", "bbox": [56.0, 43.4, 56.6, 43.9]},
        "method": {"window_km": 25}, "counts": {"windows": 35, "scored": 26, "water": 9, "nodata": 0},
        "score_distribution": {"max": 0.4167, "p90": 0.4156, "median": 0.4131, "min": 0.4072},
        "top": [{"lat": 43.5612, "lon": 56.3401, "rank": 1, "overall_A": 0.4167, "overall_B": 0.41,
                 "satellite": "https://www.google.com/maps/@43.56120,56.34010,12z/data=!3m1!1e3"}],
        "known_sites": [], "limits": ["Leads for human review."],
    }
    calls = []

    def fake_search(ref, reg):
        calls.append((ref, reg))
        return fake_result

    tool_call = {"id": "call_1", "type": "function",
                 "function": {"name": "analog_search", "arguments": '{"reference": "gale", "region": "testland"}'}}
    session = SequenceSession(
        FakeResponse(200, {"choices": [{"message": {"content": None, "tool_calls": [tool_call]}}]}),
        reply("Best lead: 43.5612, 56.3401 with 0.42 (A). It is a lead for human review. Water probability 0.66."),
    )
    res = ask(s, "Test land'da Gale'ga o'xshash joy top", FAKE_KEY, session=session, search_fn=fake_search)
    assert calls == [("gale", "testland")]
    assert res["search"] is fake_result
    assert res["unverified_numbers"] == ["0.66"]  # the invented number is caught, the lead's numbers are not
    first, second = session.calls
    assert first["tools"][0]["function"]["name"] == "analog_search"
    assert first["tools"][0]["function"]["parameters"]["properties"]["region"]["enum"] == ["testland"]
    assert second["messages"][-1]["role"] == "tool" and "43.5612" in second["messages"][-1]["content"]
    assert "tools" not in second
