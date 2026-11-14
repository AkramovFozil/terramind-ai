# TerraMind AI

**Understand Earth. Explore Beyond.**

TerraMind AI finds places on Earth whose terrain resembles a chosen site on Mars, using NASA open elevation data, and explains every score.

Built for **NASA Space Apps Challenge 2026**, challenge *“Identify Earth Locations that Analog the Permanent Moon Base Locations and Mars”*.
Student team from OXUS University, Tashkent. Not affiliated with or endorsed by NASA.

> **Core principle:** the algorithm calculates, the AI only explains. The AI never invents or changes a score.

## How it works

1. Cut a 25 × 25 km window around each site (small enough that the Gale window is crater floor only — see the decision log in [docs/methodology.md](docs/methodology.md)).
2. Project each window into its own local azimuthal equidistant (AEQD) projection: Mars on a sphere of radius 3,396,190 m, Earth on WGS84.
3. Resample both planets to one common 463 m grid (Earth SRTM by averaging, Mars MOLA bilinear).
4. Derive three terrain metrics: local relief (elevation minus window median), slope (Horn, degrees) and roughness (TRI, metres).
5. Compare each metric’s distribution with a histogram intersection (0 = no overlap, 1 = identical).
6. Combine the three scores with a weighted mean (weight set A: slope 40 %, relief 35 %, TRI 25 %; set B: equal).
7. A human reviews and freezes every window **before** any score is computed.

The score compares terrain shape only. It is **not** a habitability or mission-safety assessment.
Details: [docs/methodology.md](docs/methodology.md) · [docs/data-sources.md](docs/data-sources.md) · [docs/validation.md](docs/validation.md)

## Global search (web explorer)

The web explorer does not pick from a fixed list of Earth sites. For any Mars point it searches all of Earth's land:

1. **Mars** — the 25 km radius circle is read from USGS MOLA on the 463 m grid.
2. **Global screening** — a one-time index of every land window on Earth (56° S – 80° N, centres every ~28 km), built from NOAA ETOPO 2022 60″, stores slope / relief / TRI histograms and a rotation- and mirror-invariant *shape descriptor* (ring × sector means, Fourier harmonics; harmonic 0 keeps its sign, so a crater and a dome are opposites). The 12 best places at least 150 km apart go on.
3. **Precise match** — for each place a 90 × 90 km Copernicus GLO-30 area is measured at 463 m and the 25 km circle is slid ±20 km to the centre where the Mars landform overlays best. That circle is then scored in full.

**Score** = 50 % *shape* (best Pearson correlation of the relief maps, Mars rotated every 15° and mirrored) + 50 % *distribution*, where distribution = 70 % histogram overlap of slope, relief and TRI + 30 % overlap of *detrended roughness*. Shape is what separates a crater floor from a volcano; histograms alone cannot. Detrended roughness (RMS residual from the best-fit 3 × 3 plane) is scored separately because TRI rises on any slope, even a smooth one.
Open water (sea, lakes: exactly flat in Copernicus) over 10 % of the circle is rejected.

Copernicus is read from each tile's internal 8× overview (~240 m), which is the exact block mean of the 30 m data, so averaging it into the 463 m grid loses nothing and a search takes seconds. Tiles are cached on disk after the first download.

The **Mars ↔ Earth compare view** shows both measured surfaces side by side (Mars left, Earth right) on one colour scale and one vertical scale, with relief / slope / roughness layers, synced cameras, Earth turned into the matched orientation, and a cursor that reads the values of the same matched point on both planets.

```bash
pip install -e ".[dev,api]"
python -m terramind build-index      # once: downloads ETOPO (~480 MB) and writes the index (~100 MB)
cd web && npm ci && npm run build && cd ..   # once: builds the site into web/dist
python -m uvicorn terramind.api:app --host 127.0.0.1 --port 8000   # serves web/dist and /api
python scripts/search_demo.py 18.38 77.58    # optional: one search from the command line (run with PYTHONPATH=.)
```

Large data goes to `$TERRAMIND_DATA_DIR` (on the dev PC, `D:\CodexWork\terramind-ai\data`).

## Quick start (from a fresh clone)

Python 3.10+ with GDAL-backed `rasterio` (on Windows, `pip install rasterio` ships wheels with GDAL included).

```bash
git clone https://github.com/AkramovFozil/terramind-ai.git
cd terramind-ai
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                               # all tests run on synthetic data, no downloads
```

**1. Inputs**

- Earth: get a free API key at [opentopography.org](https://portal.opentopography.org/) and put it in `.env`:
  ```bash
  cp .env.example .env               # then edit .env: OPENTOPO_API_KEY=...
  ```
  `prepare` downloads SRTM for the window once and caches it in `data/raw/earth/`.
- Mars: the Gale window needs MOLA. Either clip only the Gale region straight from USGS (a few tens of MB read, not 2 GB):
  ```bash
  python scripts/clip_mola_gale.py   # writes data/raw/mars/gale_mola_463m.tif
  ```
  or put the full global mosaic at `data/raw/mars/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif`.

**2. Prepare → review → approve → score**

```bash
python -m terramind status
python -m terramind prepare --site gale
python -m terramind prepare --site ustyurt
# open data/processed/<site>/quicklook.png (and the satellite link printed for Earth sites)
python -m terramind approve --site gale
python -m terramind approve --site ustyurt
python -m terramind score --target gale --candidate ustyurt
```

`score` refuses to run until both sites are approved, and refuses again if a site’s center, window, grid, CRS or dataset changes after approval. Results go to `results/gale__ustyurt/`: `metrics.json`, `comparison.csv`, `histograms.png`.

A missing input or key stops with exact instructions and a non-zero exit code. The pipeline never writes made-up output.

| Exit code | Meaning |
|---|---|
| 0 | OK |
| 2 | Missing input (DEM file, API key, download failed) |
| 3 | Review gate: site not approved, or changed after approval |
| 4 | Quality check failed (fewer than 2,500 valid pixels or more than 10 % nodata) |
| 5 | Configuration problem (unknown site, no center yet, disabled site) |

## Sites (MVP)

| Site | Body | Role | Center |
|---|---|---|---|
| Gale Crater floor (Aeolis Palus) | Mars | Reference | 4.49° S, 137.42° E |
| Ustyurt Plateau | Earth | Candidate | 43.65° N, 56.18° E |
| Kyzylkum Desert | Earth | Candidate | to be chosen |
| Yungay, Atacama | Earth | Validation (known Mars analog) | 24.08° S, 69.92° W |
| MDRS, Utah | Earth | Validation (known Mars analog) | 38.41° N, 110.79° W |

## Data

| Dataset | Body | Resolution | Source |
|---|---|---|---|
| SRTM GL1 v003 | Earth | 1″ ≈ 30 m | NASA LP DAAC, via the OpenTopography Global DEM API ([DOI 10.5067/MEaSUREs/SRTM/SRTMGL1.003](https://doi.org/10.5067/MEaSUREs/SRTM/SRTMGL1.003)) |
| MGS MOLA DEM 463 m | Mars | 463 m | [USGS Astrogeology](https://astrogeology.usgs.gov/search/map/mars_mgs_mola_dem_463m) |
| LOLA DEM (south pole) | Moon | 80 m | NASA PDS — next phase |

## Repository layout

```
config/       sites.yaml (sites, windows) · metrics.yaml (bins, weights)
terramind/    Python package
  config.py     settings, sites, dataset registry, error types
  crs.py        Mars sphere / WGS84 local AEQD projections
  roi.py        square window and 463 m / 30 m grids
  raster.py     reproject a DEM onto a grid, quality check, GeoTIFF I/O
  terrain.py    slope (Horn), local relief, TRI
  similarity.py fixed-bin histograms, intersection, weighted score, Spearman
  quicklook.py  hillshade quick-look, histogram figure
  gate.py       review gate: params hash, approve, refuse
  pipeline.py   prepare and score
  cli.py        status / prepare / approve / score
  sources/      MOLA (local file) and OpenTopography (download + cache)
scripts/      clip_mola_gale.py
tests/        pytest, synthetic DEMs only
design/       UI prototype (terramind-ui.html) and the design prompt
docs/         PHASE1.md (technical task), methodology, data sources, validation
```

## Status

| Part | Status |
|---|---|
| Concept, slides, UI design, technical spec | Done (before the hackathon) |
| Config + Mars/Earth CRS module | Done (before the hackathon) |
| DEM pipeline, metrics, similarity, review gate, CLI, tests | Done (hackathon, day 1) — run on real data next |
| Validation sites (Yungay, MDRS), Kyzylkum | Planned (hackathon) |
| Web app + AI explanation | Planned (hackathon) |

## Work done before the hackathon

Space Apps allows preparation; we list it openly. Before 14 November 2026 the team prepared the concept, the presentation, the UI design ([design/terramind-ui.html](design/terramind-ui.html)), the technical specification ([docs/PHASE1.md](docs/PHASE1.md)) and the first two pipeline modules (`terramind/config.py`, `terramind/crs.py`). Everything else is built during the hackathon, 14–15 November 2026, and the commit history shows it.

## Secrets

The OpenTopography API key lives only in a local `.env` file (see `.env.example`), which is git-ignored. Never commit it. The pipeline never prints it, and removes it from any error message.

## License

Open source, as Space Apps requires. The team will choose the license before submission; if none is stated, NASA distributes the original content under Apache 2.0.
