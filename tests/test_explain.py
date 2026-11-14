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
