"""Analysis console: `python -m terramind serve` → http://127.0.0.1:8001

Standard-library HTTP server (no extra dependencies). It serves the single-page app in
terramind/web/, read-only JSON views of TerraMind's results, lead reviews, and the AI
explainer. API keys stay on the server; the browser never sees them.
"""

from __future__ import annotations

import csv
import json
import mimetypes
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from terramind import __version__
from terramind.config import TerraMindError, Settings

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_QUESTION = 500
ASK_LIMIT_PER_MIN = 12


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def overview(settings: Settings) -> dict:
    from terramind.gate import read_roi, site_state
    from terramind.regions import load_regions

    sites = []
    for s in settings.sites.values():
        roi = read_roi(settings, s.id) if s.lat is not None else None
        sites.append({
            "id": s.id, "name": s.name, "body": s.body, "role": s.role, "enabled": s.enabled,
            "center": [s.lat, s.lon], "state": site_state(settings, s), "note": s.note,
            "approved_at": (roi or {}).get("approved_at"),
            "params_hash": ((roi or {}).get("params_hash") or "")[:12] or None,
            "metric_summary": (roi or {}).get("metric_summary"),
            "dataset": (roi or {}).get("input", {}).get("name"),
            "quicklook": f"/files/data/processed/{s.id}/quicklook.png"
            if (settings.processed_dir(s.id) / "quicklook.png").exists() else None,
        })
    searches = []
    base = settings.root / "results" / "search"
    if base.exists():
        for d in sorted(base.iterdir()):
            j = _read_json(d / "search.json")
            if j:
                searches.append({
                    "id": d.name, "reference": j["reference"], "region": j["region"],
                    "counts": j["counts"], "score_distribution": j["score_distribution"],
                    "generated_at": j.get("generated_at"),
                })
    try:
        regions = [{"id": r.id, "name": r.name, "bbox": list(r.bbox)} for r in load_regions(settings).values()]
    except TerraMindError:
        regions = []
    return {
        "version": __version__,
        "window_km": settings.window_km,
        "grid_m": settings.grid_m,
        "weights": settings.weights,
        "sites": sites,
        "matrix": _read_json(settings.root / "results" / "matrix" / "matrix.json"),
        "searches": searches,
        "regions": regions,
        "ai_available": bool(os.environ.get("OPENROUTER_API_KEY")),
    }


def search_view(settings: Settings, search_id: str) -> dict | None:
    d = settings.root / "results" / "search" / search_id
    if "/" in search_id or "\\" in search_id or ".." in search_id or not (d / "search.json").exists():
        return None
    res = _read_json(d / "search.json")
    key = "overall_" + next(iter(settings.weights))
    windows = []
    with open(d / "windows.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["status"] == "ok":
                windows.append([float(r["lat"]), float(r["lon"]), float(r[key])])
    res["windows"] = windows
    res["stride_km"] = res["method"]["stride_km"]
    res["reviews"] = _read_json(d / "reviews.json") or {}
    res["map_png"] = f"/files/results/search/{search_id}/map.png"
    return res


def save_review(settings: Settings, payload: dict) -> dict:
    search_id = str(payload.get("search_id", ""))
    d = settings.root / "results" / "search" / search_id
    if "/" in search_id or "\\" in search_id or ".." in search_id or not (d / "search.json").exists():
        raise ValueError("unknown search")
    verdict = payload.get("verdict")
    if verdict not in ("accepted", "rejected", "clear"):
        raise ValueError("verdict must be accepted, rejected or clear")
    lat, lon = float(payload["lat"]), float(payload["lon"])
    key = f"{lat:.5f},{lon:.5f}"
    reviews = _read_json(d / "reviews.json") or {}
    if verdict == "clear":
        reviews.pop(key, None)
    else:
        reviews[key] = {
            "verdict": verdict,
            "note": str(payload.get("note", ""))[:300],
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    (d / "reviews.json").write_text(json.dumps(reviews, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return reviews


class _RateLimit:
    def __init__(self, per_min: int):
        self.per_min, self.times, self.lock = per_min, [], threading.Lock()

    def allow(self) -> bool:
        now = time.time()
        with self.lock:
            self.times = [t for t in self.times if now - t < 60]
            if len(self.times) >= self.per_min:
                return False
            self.times.append(now)
            return True


def make_handler(settings: Settings):
    ask_limit = _RateLimit(ASK_LIMIT_PER_MIN)
    allowed_roots = [(settings.root / "results").resolve(), (settings.root / "data" / "processed").resolve()]

    class Handler(BaseHTTPRequestHandler):
        server_version = f"TerraMind/{__version__}"

        def log_message(self, fmt, *args):  # keep the console readable
            if not self.path.startswith(("/static/", "/files/")):
                super().log_message(fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str, cache: bool = False):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=300" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _file(self, path: Path, roots: list[Path]):
            try:
                real = path.resolve()
            except OSError:
                return self._json({"error": "not found"}, 404)
            if not any(real == r or r in real.parents for r in roots) or not real.is_file():
                return self._json({"error": "not found"}, 404)
            if real.suffix.lower() not in (".png", ".json", ".csv", ".html", ".js", ".css", ".svg"):
                return self._json({"error": "not found"}, 404)
            ctype = mimetypes.guess_type(real.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            self._send(200, real.read_bytes(), ctype, cache=real.suffix == ".png")

        def do_GET(self):
            url = urlparse(self.path)
            p = url.path
            try:
                if p in ("/", "/index.html"):
                    return self._file(WEB_DIR / "index.html", [WEB_DIR.resolve()])
                if p.startswith("/static/"):
                    return self._file(WEB_DIR / p[len("/static/"):], [WEB_DIR.resolve()])
                if p.startswith("/files/"):
                    return self._file(settings.root / p[len("/files/"):], allowed_roots)
                if p == "/api/overview":
                    return self._json(overview(settings))
                if p == "/api/search":
                    sid = (parse_qs(url.query).get("id") or [""])[0]
                    res = search_view(settings, sid)
                    return self._json(res) if res else self._json({"error": "unknown search"}, 404)
                return self._json({"error": "not found"}, 404)
            except TerraMindError as exc:
                return self._json({"error": str(exc)}, 400)

        def do_POST(self):
            p = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            if length > 20_000:
                return self._json({"error": "request too large"}, 413)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "invalid JSON"}, 400)
            if p == "/api/review":
                try:
                    return self._json({"reviews": save_review(settings, payload)})
                except (ValueError, KeyError, TypeError) as exc:
                    return self._json({"error": str(exc)}, 400)
            if p == "/api/ask":
                question = str(payload.get("question", "")).strip()[:MAX_QUESTION]
                if not question:
                    return self._json({"error": "empty question"}, 400)
                if not ask_limit.allow():
                    return self._json({"error": "too many questions, wait a minute"}, 429)
                from terramind.explain import ask

                try:
                    res = ask(
                        settings, question,
                        api_key=os.environ.get("OPENROUTER_API_KEY"),
                        model=os.environ.get("OPENROUTER_MODEL") or None,
                        max_tokens=int(os.environ.get("OPENROUTER_MAX_TOKENS") or 0) or None,
                        opentopo_key=os.environ.get("OPENTOPO_API_KEY"),
                    )
                except TerraMindError as exc:
                    return self._json({"error": str(exc)}, 400)
                search = res.get("search")
                return self._json({
                    "answer": res["answer"],
                    "model": res["model"],
                    "unverified_numbers": res["unverified_numbers"],
                    "search_id": f"{search['reference']['id']}__{search['region']['id']}" if search else None,
                })
            return self._json({"error": "not found"}, 404)

    return Handler


def serve(settings: Settings, host: str = "127.0.0.1", port: int = 8001) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(settings))
    print(f"TerraMind platform: http://{host}:{port}   (Ctrl+C to stop)", flush=True)
    if host not in ("127.0.0.1", "localhost"):
        print("WARNING: the server is reachable from other computers; 'Ask AI' spends your OpenRouter credits.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

