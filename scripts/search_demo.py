"""Run one real global search from the command line and print the ranking.

    python scripts/search_demo.py -4.49 137.42      # Gale crater floor
"""
import sys
import time

from terramind.search_service import SearchService


def main():
    lat, lon = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (-4.49, 137.42)
    service = SearchService()
    started = time.time()
    job_id = service.submit(lat, lon)["job_id"]
    last = ""
    while True:
        job = service.get_job(job_id)
        if job["message"] != last:
            last = job["message"]
            print(f"[{time.time() - started:6.1f}s] {job['progress']:3d}% {last}", flush=True)
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(1)
    service.close()
    if job["status"] == "failed":
        print("FAILED:", job.get("error"))
        for c in job.get("excluded_candidates", []):
            print("  excluded:", c["name"], c["reason"][:160])
        return 1
    result = job["result"]
    print(f"\nMars {lat}, {lon}  ->  {result['coverage']['screened_windows']:,} Earth windows screened")
    print(f"{'#':>2} {'lat':>9} {'lon':>10} {'score':>6} {'shape':>6} {'slope':>6} {'relief':>6} {'tri':>6} {'rough':>6} {'corr':>5} {'shift':>6}")
    for c in result["candidates"]:
        m = c["metric_scores"]
        print(f"{c['rank']:>2} {c['lat']:>9.4f} {c['lon']:>10.4f} {c['score']:>6.1f} {m['shape']:>6.1f} {m['slope_deg']:>6.1f} "
              f"{m['relief_m']:>6.1f} {m['tri_m']:>6.1f} {m['roughness_m']:>6.1f} {c['match']['correlation']:>5.2f} {c['refinement']['shift_km']:>5.1f}k")
    for c in result["excluded_candidates"]:
        print("  excluded:", c["name"], c["reason"][:160])
    if len(sys.argv) > 3:
        _figure(service, job_id, result, sys.argv[3])
    return 0


def _figure(service, job_id, result, path):
    """Mars circle next to the top three Earth matches, Earth turned the way it matched."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from scipy import ndimage

    def relief(site_id):
        t = service.get_terrain(job_id, site_id)
        z = np.array([np.nan if v is None else v for v in t["elevations"]], dtype=float).reshape(t["height"], t["width"])
        inside = np.array(t["roi_mask"]).reshape(z.shape)
        return np.where(inside, z - np.nanmedian(z[inside]), np.nan)

    panels = [("MARS " + f"{result['target']['lat']:.2f}, {result['target']['lon']:.2f}", relief("target"))]
    for c in result["candidates"][:3]:
        z = relief(c["id"])
        # Undo the template's rotation/mirror so Earth is shown in the Mars orientation.
        filled = np.where(np.isfinite(z), z, 0)
        filled = ndimage.rotate(filled, -c["match"]["rotation_deg"], reshape=False, order=1)
        if c["match"]["mirrored"]:
            filled = filled[:, ::-1]
        z = np.where(np.isfinite(relief("target")), filled, np.nan)
        panels.append((f"#{c['rank']} {c['lat']:.3f}, {c['lon']:.3f}\n{c['score']:.1f}/100 · r={c['match']['correlation']:.2f}", z))
    fig, axes = plt.subplots(1, len(panels), figsize=(4 * len(panels), 4.4))
    for ax, (title, z) in zip(axes, panels):
        lim = np.nanmax(np.abs(z))
        ax.imshow(z, cmap="RdYlBu_r", vmin=-lim, vmax=lim)
        ls = matplotlib.colors.LightSource(315, 45)
        ax.imshow(ls.hillshade(np.nan_to_num(z), dx=463, dy=463), cmap="gray", alpha=0.35)
        ax.set_title(title, fontsize=9)
        ax.axis("off")
    fig.suptitle("Relief (elevation − circle median), 25 km radius, 463 m grid", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    print("figure:", path)


if __name__ == "__main__":
    sys.exit(main())
