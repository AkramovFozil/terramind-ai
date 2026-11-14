"""Cut a small Gale Crater window out of the global MOLA 463 m mosaic.

Works on a local copy of the mosaic, or straight from the USGS URL: GDAL then
reads only the rows it needs (tens of MB) instead of the whole ~2 GB file.

    python scripts/clip_mola_gale.py                       # from the USGS URL
    python scripts/clip_mola_gale.py --src data/raw/mars/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif

Writes data/raw/mars/gale_mola_463m.tif (unchanged values, unchanged CRS), which
config/sites.yaml lists as a valid Mars DEM path for the `gale` site.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terramind.config import DATASETS  # noqa: E402
from terramind.crs import MARS_GEOGRAPHIC, check_body_crs  # noqa: E402

GALE_LAT, GALE_LON = -4.49, 137.42


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default=DATASETS["MOLA_MEGDR_463m"]["download_url"], help="local path or https URL")
    ap.add_argument("--out", default="data/raw/mars/gale_mola_463m.tif")
    ap.add_argument("--pad-deg", type=float, default=1.5, help="half-size of the box in degrees (default 1.5)")
    args = ap.parse_args()

    src_path = args.src
    if src_path.startswith(("http://", "https://")):
        src_path = "/vsicurl/" + src_path
    lon0, lon1 = GALE_LON - args.pad_deg, GALE_LON + args.pad_deg
    lat0, lat1 = GALE_LAT - args.pad_deg, GALE_LAT + args.pad_deg

    env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_MAX_RETRY": "5", "GDAL_HTTP_RETRY_DELAY": "2"}
    with rasterio.Env(**env), rasterio.open(src_path) as src:
        check_body_crs(src.crs, "mars", "MOLA source")
        left, bottom, right, top = transform_bounds(MARS_GEOGRAPHIC, src.crs, lon0, lat0, lon1, lat1)
        window = from_bounds(left, bottom, right, top, src.transform).round_offsets().round_lengths()
        data = src.read(1, window=window)
        profile = src.profile.copy()
        profile.update(
            driver="GTiff", width=window.width, height=window.height,
            transform=src.window_transform(window), compress="deflate", tiled=False,
        )
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(data, 1)
    print(f"wrote {out}  ({window.width} x {window.height} px, lon {lon0}..{lon1}, lat {lat0}..{lat1})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
