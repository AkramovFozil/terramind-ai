"""Command line: status, prepare, approve, score, build-index."""

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


def cmd_build_index(settings, args) -> int:
    from terramind.global_index import build_index, index_dir
    from terramind.sources.etopo import download_etopo

    if (index_dir() / "meta.json").exists() and not args.force:
        print(f"Global Earth index already exists at {index_dir()} (use --force to rebuild)")
        return 0
    path = download_etopo(progress=print)
    print(f"ETOPO grid: {path}")
    build_index(progress=print)
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
    sb = sub.add_parser("build-index", help="download ETOPO once and build the global Earth search index")
    sb.add_argument("--force", action="store_true", help="rebuild even if the index exists")
    sb.set_defaults(func=cmd_build_index)
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
