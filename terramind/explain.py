"""AI explanation layer: the algorithm calculates, the AI only explains.

The model receives TerraMind's computed results as context and must answer from
them alone. Every decimal number in its answer is checked against that context;
numbers that do not appear there are reported as unverified.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import requests

from terramind.config import MissingInputError, Settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o"
REPO_URL = "https://github.com/AkramovFozil/terramind-ai"

SYSTEM_PROMPT = """You are the explainer of TerraMind AI, a NASA Space Apps 2026 project that compares the
terrain of Earth sites with reference sites on Mars using NASA elevation data (MOLA for Mars, SRTM for Earth).

You receive the project's computed results as JSON in CONTEXT. Rules:
1. Use only numbers that appear in CONTEXT. Never compute, estimate, round differently or invent a score.
   If a number the user asks for is not in CONTEXT, say that TerraMind has not computed it.
2. Say which pair (Mars reference vs Earth site) and which weight set (A or B) a score belongs to.
3. Scores compare distributions of slope, local relief and roughness (TRI) on a 463 m grid in 25 x 25 km
   windows, from 0 (no overlap) to 1 (identical). They say nothing about geology, minerals, climate,
   water or habitability. If asked about those, say TerraMind does not measure them.
4. When it matters, mention the relevant limits listed in CONTEXT (e.g. Meridiani was added after the first
   score; a high Meridiani score mostly means "equally flat"; one window per site; MOLA interpolation).
5. Answer in the language of the question. Be short and concrete: a few sentences, plain words."""


def results_root(settings: Settings) -> Path:
    """Live results (results/) if the matrix exists there, else the published snapshot (docs/results/)."""
    live = settings.root / "results"
    if (live / "matrix" / "matrix.json").exists():
        return live
    snap = settings.root / "docs" / "results"
    if (snap / "matrix.json").exists():
        return snap
    if live.exists() and any(live.glob("*__*/metrics.json")):
        return live
    raise MissingInputError(
        "No TerraMind results to explain yet. Run: python -m terramind matrix "
        "(or score a pair first)."
    )


def _pair_dirs(root: Path) -> list[Path]:
    base = root / "pairs" if (root / "pairs").exists() else root
    return sorted(p.parent for p in base.glob("*__*/metrics.json"))


def load_context(settings: Settings) -> dict:
    """Compact JSON context: the matrix, every scored pair, site summaries and the stated limits."""
    root = results_root(settings)
    ctx: dict = {"source": str(root.relative_to(settings.root)) if root.is_relative_to(settings.root) else str(root)}
    matrix_path = (root / "matrix" / "matrix.json") if (root / "matrix").exists() else (root / "matrix.json")
    if matrix_path.exists():
        m = json.loads(matrix_path.read_text(encoding="utf-8"))
        ctx["matrix"] = {"cells": m.get("cells"), "rank_stability": m.get("rank_stability"), "note": m.get("note")}
    pairs = {}
    for d in _pair_dirs(root):
        m = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
        pairs[d.name] = {
            "reference": {k: m["target"][k] for k in ("id", "name", "body", "center", "approved_at")},
            "earth_site": {k: m["candidate"][k] for k in ("id", "name", "body", "role", "center", "approved_at")},
            "overall": m["overall"],
            "per_metric": m["per_metric"],
            "caveats": m.get("caveats", []),
        }
    ctx["pairs"] = pairs
    ctx["method"] = {
        "window_km": settings.window_km,
        "grid_m": settings.grid_m,
        "metrics": "slope (Horn, degrees), local relief (elevation minus window median, m), roughness TRI (m)",
        "similarity": "histogram intersection on fixed bins; overall = weighted mean (A: slope .40, relief .35, TRI .25; B: equal)",
    }
    ctx["limits"] = [
        "Meridiani Planum was added as a second Mars reference after the first score (Gale vs Ustyurt = 0.12); this is logged openly.",
        "A high score against Meridiani mostly means 'equally flat'; no negative control (a flat non-analog plain) has been tested yet.",
        "Shape only at 463 m: nothing about rock type, minerals, climate or habitability.",
        "One 25 km window per site; another window in the same region can score differently.",
        "MOLA near the equator is partly interpolated between orbit tracks, which smooths the Mars references.",
    ]
    return ctx


_NUM = re.compile(r"(?<![\w.])-?\d+\.\d+")


def _context_numbers(obj) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_context_numbers(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_context_numbers(v))
    elif isinstance(obj, str):
        out.extend(float(x) for x in _NUM.findall(obj))
    return out


_PCT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?%")


def _matches(value: float, decimals: int, known: list[float]) -> bool:
    return any(round(k, decimals) == round(value, decimals) for k in known)


def unverified_numbers(answer: str, context: dict) -> list[str]:
    """Numbers in the answer (decimals and percentages) that no context number rounds to."""
    known = _context_numbers(context)
    bad = []
    for m in _PCT.finditer(answer):
        token = m.group(1)
        decimals = len(token.split(".")[1]) if "." in token else 0
        value = float(token)
        # 74% may stand for a score of 0.74 or for a value stored as 74
        if not (_matches(value / 100.0, decimals + 2, known) or _matches(value, decimals, known)):
            bad.append(token + "%")
    for token in _NUM.findall(_PCT.sub(" ", answer)):
        decimals = len(token.split(".")[1])
        if not _matches(float(token), decimals, known):
            bad.append(token)
    return bad


def _redact(text: str, secret: str | None) -> str:
    return text.replace(secret, "***") if secret else text


def ask(settings: Settings, question: str, api_key: str | None, model: str | None = None,
        session=None, timeout: float = 90.0) -> dict:
    """Ask the explainer. Returns {answer, model, unverified_numbers, context_source}."""
    if not question.strip():
        raise MissingInputError("Empty question.")
    if not api_key:
        raise MissingInputError(
            "OPENROUTER_API_KEY is not set. Add it to the .env file in the project root "
            "(see .env.example). The key stays on this computer or server, never in browser code."
        )
    context = load_context(settings)
    model = model or DEFAULT_MODEL
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": "CONTEXT:\n" + json.dumps(context, ensure_ascii=False)},
            {"role": "user", "content": question},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": REPO_URL,
        "X-Title": "TerraMind AI",
    }
    http = session or requests
    try:
        resp = http.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise MissingInputError(f"OpenRouter request failed: {_redact(str(exc), api_key)}") from None
    if resp.status_code != 200:
        body = (resp.text or "")[:400]
        raise MissingInputError(f"OpenRouter returned HTTP {resp.status_code}: {_redact(body, api_key)}")
    try:
        answer = resp.json()["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError, TypeError):
        raise MissingInputError(f"Unexpected OpenRouter response: {_redact((resp.text or '')[:400], api_key)}") from None
    return {
        "answer": answer,
        "model": model,
        "unverified_numbers": unverified_numbers(answer, context),
        "context_source": context["source"],
    }
