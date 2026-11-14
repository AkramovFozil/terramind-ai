"""Command line: status, prepare, approve, score."""

from __future__ import annotations

import argparse
import os
import sys

from terramind.config import TerraMindError, load_settings, project_root


def _load_env(root) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(root / ".env", override=False)


def cmd_status(settings, args) -> int:
    from terramind.gate import site_state

    print(f"{'site':<10} {'body':<6} {'role':<11} {'enabled':<8} {'center':<22} state")
    for site in settings.sites.values():
        center = "—" if site.lat is None else f"{site.lat:.4f}, {site.lon:.4f}"
        if site.provisional and site.lat is not None:
            center += " *"
        print(f"{site.id:<10} {site.body:<6} {site.role:<11} {str(site.enabled).lower():<8} {center:<22} {site_state(settings, site)}")
    if any(s.provisional for s in settings.sites.values()):
        print("* provisional center")
    return 0


def cmd_prepare(settings, args) -> int:
    from terramind.pipeline import prepare

    site = settings.site(args.site)
    if site.provisional:
        print(f"NOTE: {site.id} has a PROVISIONAL center. Freeze the final center before approving.")
    roi = prepare(settings, args.site, api_key=os.environ.get("OPENTOPO_API_KEY"))
    q = roi["quality"]
    print(f"Prepared {site.id}: {q['valid_pixels']} valid pixels of {q['total_pixels']}, nodata {q['nodata_fraction']:.1%}")
    for path in roi["files"].values():
        print(f"  wrote {path}")
    if roi.get("map_links"):
        print(f"  satellite view: {roi['map_links']['satellite']}")
        print(f"  map:            {roi['map_links']['openstreetmap']}")
    print(f"Status: {roi['status']}. Open {roi['files']['quicklook']}, check the area, then run:")
    print(f"  python -m terramind approve --site {site.id}")
    return 0


def cmd_approve(settings, args) -> int:
    from terramind.gate import approve

    roi = approve(settings, args.site)
    print(f"Approved {args.site} at {roi['approved_at']} (params {roi['params_hash'][:12]})")
    return 0


def cmd_score(settings, args) -> int:
    from terramind.pipeline import score

    res = score(settings, args.target, args.candidate)
    print(f"{res['target']['name']} vs {res['candidate']['name']}")
    for m, r in res["per_metric"].items():
        print(f"  {m:<10} overlap {r['score']:.3f}")
    for name, o in res["overall"].items():
        print(f"  overall {name}: {o['score']:.3f}")
    for path in res["files"]:
        print(f"  wrote {path}")
    for c in res["caveats"]:
        print(f"  caveat: {c}")
    return 0


def cmd_matrix(settings, args) -> int:
    from terramind.pipeline import matrix

    res = matrix(settings)
    refs = [r["id"] for r in res["references"]]
    ws = next(iter(settings.weights))
    print(f"{'earth site':<12} {'role':<11} " + " ".join(f"{r:>10}" for r in refs) + f"   (overall, weights {ws})")
    for s in res["earth_sites"]:
        row = [res["cells"][f"{r}__{s['id']}"]["overall"][ws] for r in refs]
        print(f"{s['id']:<12} {s['role']:<11} " + " ".join(f"{v:>10.3f}" for v in row))
    for ref, st in res["rank_stability"].items():
        rho = st["spearman_rho"]
        print(f"rank stability A vs B for {ref}: " + ("n/a (" + st["reason"] + ")" if rho is None else f"Spearman rho = {rho:.2f}"))
    for path in res["files"]:
        print(f"  wrote {path}")
    return 0


def cmd_ask(settings, args) -> int:
    from terramind.explain import ask

    res = ask(
        settings,
        " ".join(args.question),
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        model=args.model or os.environ.get("OPENROUTER_MODEL") or None,
        max_tokens=int(os.environ.get("OPENROUTER_MAX_TOKENS") or 0) or None,
        opentopo_key=os.environ.get("OPENTOPO_API_KEY"),
        progress=lambda m: print("  " + m, flush=True),
    )
    print(res["answer"])
    if res.get("search"):
        sr = res["search"]
        key = next(iter(settings.weights))
        print(f"\nLeads computed by TerraMind ({sr['region']['name']} vs {sr['reference']['name']}):")
        for i, r in enumerate(sr["top"], 1):
            print(f"  {i:>2}. {r['lat']:.4f}, {r['lon']:.4f}  score {r['overall_' + key]:.3f}  {r['satellite']}")
        files = sr.get("files") or [f"results/search/{sr['reference']['id']}__{sr['region']['id']}/map.png"]
        print("  map: " + next((f for f in files if f.endswith("map.png")), files[0]))
    print(f"\n[model: {res['model']} · context: {res['context_source']}]")
    if res["unverified_numbers"]:
        print("WARNING: these numbers are not in TerraMind's results — do not trust them: "
              + ", ".join(res["unverified_numbers"]))
    return 0


def cmd_regions(settings, args) -> int:
    from terramind.regions import load_regions, tile_bounds, window_centers

    print(f"{'region':<16} {'tiles':>5} {'windows':>8}  name")
    for r in load_regions(settings).values():
        n = len(window_centers(r, settings.window_km))
        print(f"{r.id:<16} {len(tile_bounds(r)):>5} {n:>8}  {r.name}")
    return 0


def cmd_search(settings, args) -> int:
    from terramind.search import search

    res = search(settings, args.reference, args.region, api_key=os.environ.get("OPENTOPO_API_KEY"),
                 top_n=args.top, progress=lambda m: print("  " + m, flush=True))
    c = res["counts"]
    key = next(iter(settings.weights))
    print(f"\n{res['region']['name']} vs {res['reference']['name']}")
    print(f"windows {c['windows']}: scored {c['scored']}, water {c['water']}, nodata {c['nodata']}")
    if res["score_distribution"]:
        d = res["score_distribution"]
        print(f"scores: max {d['max']:.3f}, top 10% from {d['p90']:.3f}, median {d['median']:.3f}")
    print(f"\nTop leads (weight set {key}, at least {settings.window_km:g} km apart):")
    for i, r in enumerate(res["top"], 1):
        print(f"  {i:>2}. {r['lat']:.4f}, {r['lon']:.4f}  score {r['overall_' + key]:.3f}  {r['satellite']}")
    for k in res["known_sites"]:
        print(f"Known site {k['name']}: nearest window ranks {k['rank']} of {k['of']} "
              f"(top {k['top_percent']}%), score {k['score']:.3f}")
    for path in res["files"]:
        print(f"  wrote {path}")
    print("Leads are for human review: check the satellite view before treating any of them as an analog.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="terramind", description="TerraMind AI — Earth/Mars DEM terrain matching (Phase 1)")
    p.add_argument("--root", help="project root (default: $TERRAMIND_ROOT or current directory)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="list sites and their review state").set_defaults(func=cmd_status)
    sp = sub.add_parser("prepare", help="clip, reproject, compute metrics and the quick-look for one site")
    sp.add_argument("--site", required=True)
    sp.set_defaults(func=cmd_prepare)
    sa = sub.add_parser("approve", help="approve a prepared site after looking at its quick-look")
    sa.add_argument("--site", required=True)
    sa.set_defaults(func=cmd_approve)
    ss = sub.add_parser("score", help="compare two approved sites")
    ss.add_argument("--target", required=True)
    ss.add_argument("--candidate", required=True)
    ss.set_defaults(func=cmd_score)
    sub.add_parser("matrix", help="score every approved Mars reference against every approved Earth site").set_defaults(func=cmd_matrix)
    sub.add_parser("regions", help="list search regions").set_defaults(func=cmd_regions)
    sr = sub.add_parser("search", help="Analog Finder: scan a region for windows similar to a Mars reference")
    sr.add_argument("--reference", required=True, help="approved Mars site, e.g. gale or meridiani")
    sr.add_argument("--region", required=True, help="region id from config/regions.yaml")
    sr.add_argument("--top", type=int, default=10)
    sr.set_defaults(func=cmd_search)
    sq = sub.add_parser("ask", help="ask the AI to explain TerraMind's results (OpenRouter)")
    sq.add_argument("question", nargs="+")
    sq.add_argument("--model", help="OpenRouter model id (default: $OPENROUTER_MODEL or openai/gpt-4o)")
    sq.set_defaults(func=cmd_ask)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = project_root(args.root)
        _load_env(root)
        settings = load_settings(root)
        return args.func(settings, args)
    except TerraMindError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
