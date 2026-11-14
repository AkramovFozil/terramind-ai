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
DEFAULT_MAX_TOKENS = 700  # answers are a few sentences; also keeps the credit reservation small
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
5. For a "why" question, explain the cause, not just the score: compare the per-metric scores and the
   medians (and p5-p95) of slope, relief and TRI of both sites from CONTEXT. Say which metric drives the result.
6. Round scores to two decimals (0.74, not 0.7391).
7. If Meridiani is involved, add one sentence: it was added after the first score, and a high score against it
   mostly means the site is equally flat; a negative control has not been tested yet.
8. Answer in the language of the question, in plain everyday words, a short paragraph (at most ~120 words).
   In Uzbek use: slope = qiyalik, local relief = balandlik farqi (relyef), roughness (TRI) = notekislik,
   score = o'xshashlik bali, weight set = vaznlar to'plami."""


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


SEARCH_PROMPT = """
Searching: if the user asks to FIND or SEARCH places on Earth that resemble a Mars site, call the
analog_search tool with a Mars reference and a region from its lists. Never name candidate places from your
own knowledge: only the tool's results count. Present the top leads with coordinates and scores, say they are
leads for human review (check satellite imagery first), and if a known analog site is in the region, report its
rank as a check of the method. Only the listed regions can be searched; if the user asks for the whole Earth or
another area, say which regions are available and use the closest one."""


def _http_error(resp, api_key) -> MissingInputError:
    body = (resp.text or "")[:400]
    hint = ""
    if resp.status_code == 402:
        hint = (" — not enough OpenRouter credits. Add credits, lower OPENROUTER_MAX_TOKENS, "
                "or use a cheaper model, e.g. OPENROUTER_MODEL=openai/gpt-4o-mini in .env.")
    return MissingInputError(f"OpenRouter returned HTTP {resp.status_code}{hint}\n{_redact(body, api_key)}")


def _post(http, headers, payload, timeout, api_key) -> dict:
    try:
        resp = http.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise MissingInputError(f"OpenRouter request failed: {_redact(str(exc), api_key)}") from None
    if resp.status_code != 200:
        raise _http_error(resp, api_key)
    try:
        return resp.json()["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise MissingInputError(f"Unexpected OpenRouter response: {_redact((resp.text or '')[:400], api_key)}") from None


def search_tool_spec(settings: Settings) -> dict | None:
    """OpenAI-style tool schema for analog_search, limited to approved Mars references and configured regions."""
    from terramind.gate import site_state
    from terramind.regions import load_regions

    refs = [s for s in settings.sites.values() if s.body == "mars" and s.role == "reference"
            and s.lat is not None and site_state(settings, s) == "approved"]
    try:
        regions = load_regions(settings)
    except Exception:
        return None
    if not refs or not regions:
        return None
    return {
        "type": "function",
        "function": {
            "name": "analog_search",
            "description": (
                "Scan a region of Earth with NASA SRTM elevation data for 25 x 25 km windows whose terrain "
                "(slope, relief, roughness) resembles an approved Mars reference site. Returns ranked leads "
                "computed by TerraMind's algorithm. References: "
                + "; ".join(f"{s.id} = {s.name}" for s in refs)
                + ". Regions: " + "; ".join(f"{r.id} = {r.name}" for r in regions.values()) + "."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reference": {"type": "string", "enum": [s.id for s in refs]},
                    "region": {"type": "string", "enum": list(regions)},
                },
                "required": ["reference", "region"],
            },
        },
    }


def cached_or_run_search(settings: Settings, reference: str, region: str, opentopo_key: str | None,
                         progress=None) -> dict:
    """Reuse results/search/<ref>__<region>/search.json if it matches the current approval, else run the search."""
    from terramind.gate import require_approved
    from terramind.regions import get_region
    from terramind.search import search

    path = settings.root / "results" / "search" / f"{reference}__{region}" / "search.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        roi = require_approved(settings, reference)
        if (old.get("reference", {}).get("params_hash") == roi["params_hash"]
                and old.get("region", {}).get("bbox") == list(get_region(settings, region).bbox)):
            return old
    return search(settings, reference, region, api_key=opentopo_key, progress=progress)


def _search_context(res: dict) -> dict:
    keep = ("lat", "lon", "rank", "overall_A", "overall_B", "slope_deg", "relief_m", "tri_m", "slope_median", "tri_median")
    return {
        "reference": res["reference"]["name"],
        "region": res["region"]["name"],
        "method": res["method"],
        "counts": res["counts"],
        "score_distribution": res["score_distribution"],
        "top_leads": [{k: t[k] for k in keep if k in t} for t in res["top"]],
        "known_sites": res["known_sites"],
        "limits": res["limits"],
    }


def ask(settings: Settings, question: str, api_key: str | None, model: str | None = None,
        session=None, timeout: float = 90.0, max_tokens: int | None = None,
        opentopo_key: str | None = None, allow_search: bool = True, search_fn=None, progress=None) -> dict:
    """Ask the explainer. It may call the analog search tool; numbers in the answer are checked.

    Returns {answer, model, unverified_numbers, context_source, search}.
    """
    if not question.strip():
        raise MissingInputError("Empty question.")
    if not api_key:
        raise MissingInputError(
            "OPENROUTER_API_KEY is not set. Add it to the .env file in the project root "
            "(see .env.example). The key stays on this computer or server, never in browser code."
        )
    try:
        context = load_context(settings)
    except MissingInputError:
        context = {"source": "none (no scores computed yet)"}
    model = model or DEFAULT_MODEL
    tool = search_tool_spec(settings) if allow_search else None
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + (SEARCH_PROMPT if tool else "")},
        {"role": "system", "content": "CONTEXT:\n" + json.dumps(context, ensure_ascii=False)},
        {"role": "user", "content": question},
    ]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": REPO_URL,
        "X-Title": "TerraMind AI",
    }
    base = {"model": model, "temperature": 0.2, "max_tokens": int(max_tokens or DEFAULT_MAX_TOKENS)}
    http = session or requests

    payload = dict(base, messages=messages)
    if tool:
        payload.update(tools=[tool], tool_choice="auto")
    msg = _post(http, headers, payload, timeout, api_key)

    search_result = None
    calls = (msg.get("tool_calls") or [])[:1] if tool else []
    if calls:
        call = calls[0]
        try:
            args = json.loads(call["function"]["arguments"] or "{}")
            reference, region = args["reference"], args["region"]
        except (KeyError, TypeError, ValueError):
            raise MissingInputError("The AI asked for a search with invalid arguments.") from None
        run = search_fn or (lambda ref, reg: cached_or_run_search(settings, ref, reg, opentopo_key, progress))
        search_result = run(reference, region)
        tool_ctx = _search_context(search_result)
        context = dict(context, search=tool_ctx)
        messages += [
            {"role": "assistant", "content": msg.get("content") or "", "tool_calls": [call]},
            {"role": "tool", "tool_call_id": call.get("id", "call_0"), "content": json.dumps(tool_ctx, ensure_ascii=False)},
        ]
        msg = _post(http, headers, dict(base, messages=messages), timeout, api_key)

    answer = (msg.get("content") or "").strip()
    if not answer:
        raise MissingInputError("The AI returned an empty answer.")
    return {
        "answer": answer,
        "model": model,
        "unverified_numbers": unverified_numbers(answer, context),
        "context_source": context["source"],
        "search": search_result,
    }
