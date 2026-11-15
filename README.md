# TerraMind AI

https://zerohacker557.github.io/nasahacktahon-abubakr/

**Understand Earth. Explore Beyond.**

TerraMind AI finds places on Earth whose terrain resembles a chosen site on Mars or the Moon, using NASA open elevation data (MOLA, LOLA, SRTM), and explains every score.

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

## First results (14 Nov 2026)

![Similarity matrix](docs/results/matrix.png)

Known Mars analogs Yungay and MDRS score 0.77 and 0.66 against the Gale crater floor, so the method recognises them. Ustyurt does not resemble Gale (0.12) but scores 0.74 against Meridiani Planum, the flat plain where Opportunity landed. Full table, per-metric scores and limits: **[docs/results.md](docs/results.md)**.

**Live preview:** https://terramind-ai-one.vercel.app — landing page and interface only. The analysis (search, measured 3D terrain, Moon, AI assistant) needs the local server and the NASA data files, so the preview shows "server offline"; run it locally as described below.

## One platform

Open **http://127.0.0.1:8000** after the steps below: the Global Explorer (Abubakr's 3D web app) with the **AI yordamchi** panel inside it (header button or the floating button).

Ask in any language, e.g. *"Menga Oydagi LOLA ning yerdagi relyefiga mos bo'lgan joyni topib ber"*. The AI calls TerraMind's tools: **1** it marks the reference on its map (Moon south-pole hillshade from LRO LOLA, or the Mars map) and shows the approved 25 km window; **2** the Analog Finder scans an Earth region with the same method and the leads are drawn on the Earth map; **3** *3D da solishtirish* puts the reference and an Earth lead side by side on one scale. Every number in the answer is checked against the computed results; anything else is flagged. Without an AI key, the panel's direct mode shows the same results. Each lead has a **landing screen** (share of the window with slope < 5° / < 15° / ≥ 15°) and a one-page **mission brief** (`/api/tm/report/<ref>__<region>?lat=&lon=`: both windows, numbers, provenance with DOIs, review state; print to PDF).

```bash
pip install -e ".[dev,api]"
python -m terramind build-index          # once (~480 MB ETOPO download): enables "O'xshash joylarni topish"
cd web && npm ci && npm run build && cd ..
python -m uvicorn terramind.api:app --host 127.0.0.1 --port 8000    # from the project root
```

The AI decides which tool to call; the algorithm computes every score. Keys (`OPENROUTER_API_KEY`, `OPENTOPO_API_KEY`) stay in `.env` on the server.

## Global Explorer (3D web app)

The Global Explorer (React + Three.js, `web/`, FastAPI `terramind/api.py`) selects Earth candidates using a global land index, then evaluates the requested region around each candidate. The interface defaults to Russian; the header switches between **RU / EN / UZ** and remembers the choice across pages.

1. **Mars** — choose a radius from **1 to 100 km**, including decimal values (default 25 km). The actual requested circle is read from USGS MOLA on the 463 m grid; changing radius changes acquisition, masks, refinement, final scores and terrain exports.
2. **Global screening** — a one-time index of every land window on Earth (56° S – 80° N, centres every ~28 km), built from NOAA ETOPO 2022 60″, stores slope / relief / TRI histograms and a rotation- and mirror-invariant *shape descriptor* (ring × sector means, Fourier harmonics; harmonic 0 keeps its sign, so a crater and a dome are opposites). The 12 best places at least 150 km apart go on.
3. **Precise match** — each candidate is measured from Copernicus GLO-30 at 463 m. The requested circle is moved within the available buffer (up to ±20 km) and scored against the same-radius Mars circle. At 100 km radius, acquisition reaches its supported limit, so candidate centres are evaluated without shifting.

The global index uses **25 km regional context only to choose a shortlist**, including when the requested radius is different. It is not an exhaustive search at every requested scale: a local analog rejected by this context screen is not remeasured. Final similarity scores always use the requested radius. Small regions expose sample counts and a sparse-data warning; a 1 km region can have only four complete 3×3 metric samples on the 463 m grid. A high score with so few samples is not a strong analog confirmation.

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

Large data goes to `$TERRAMIND_DATA_DIR`, or `data/` in the project root (git-ignored).

The Global Explorer is exploratory: its circles use the selected **radius** and its score adds a shape term, so its numbers are not the same scale as the reviewed pipeline below (25 km square windows, histogram overlap only). Both use the same slope / relief / TRI code.

Measured terrain also offers a full-screen mission view: an AI-assisted TerraMind rocket concept can land, launch and fly around the selected location. Drag to orbit and scroll to zoom. The scene retains the **AI-generated** label; vehicle motion and sub-grid visual detail are illustrative, not flight dynamics or a landing-safety assessment.

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
- Moon: download `LDEM_80S_80MPP_ADJ.TIF` (~181 MB) from https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_80MPP_ADJ.TIF into `data/raw/moon/`.
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

To compare every Mars reference with every Earth site at once (all enabled sites must be approved first):

```bash
python -m terramind matrix          # writes results/matrix/matrix.json, matrix.csv, matrix.png
```

**3. Analog Finder — let TerraMind find the places**

```bash
python -m terramind regions                                   # list search regions
python -m terramind search --reference gale --region utah     # validation: does MDRS rank high?
python -m terramind search --reference meridiani --region uzbekistan_west
```

Scans every 25 km window in the region (NASA SRTM GL3 via OpenTopography) with the same method and writes `results/search/<reference>__<region>/`: `map.png` (similarity map with numbered leads), `windows.csv` (every window), `search.json` (top leads with satellite links, known-site rank, limits). Leads are for human review, not confirmed analogs.

**4. Analysis console** (older stand-alone page; the AI Assistant above now covers the same flow) — interactive map of the Analog Finder (satellite imagery to review leads, accept/reject), the matrix, every site's quick-look and approval, and Ask AI:

```bash
python -m terramind serve           # then open http://127.0.0.1:8001
```

Runs locally with the Python standard library; API keys stay on the server. Lead reviews are saved to `results/search/<search>/reviews.json`.

**5. Ask the AI** (needs `OPENROUTER_API_KEY` in `.env`):

```bash
python -m terramind ask "Why does Ustyurt match Meridiani but not Gale?"
python -m terramind ask "Find places in western Uzbekistan that look like Meridiani Planum"
```

For a "find" request the model calls the Analog Finder tool (fixed lists of references and regions) instead of naming places itself. The model gets only TerraMind's computed results as context. Every number in its answer is checked against those results; anything that is not there is printed as a warning. The AI explains, it never scores.

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
| Meridiani Planum (Opportunity landing site) | Mars | Reference | 1.95° S, 354.47° E |
| Mons Mouton Plateau (Artemis III candidate region, IM-2 landing point) | Moon | Reference | 84.79° S, 29.20° E |
| Ustyurt Plateau | Earth | Candidate | 43.65° N, 56.18° E |
| Kyzylkum Desert | Earth | Candidate | to be chosen |
| Yungay, Atacama | Earth | Validation (known Mars analog) | 24.08° S, 69.92° W |
| MDRS, Utah | Earth | Validation (known Mars analog) | 38.41° N, 110.79° W |

## Data

| Dataset | Body | Resolution | Source |
|---|---|---|---|
| SRTM GL1 v003 | Earth | 1″ ≈ 30 m | NASA LP DAAC, via the OpenTopography Global DEM API ([DOI 10.5067/MEaSUREs/SRTM/SRTMGL1.003](https://doi.org/10.5067/MEaSUREs/SRTM/SRTMGL1.003)) |
| MGS MOLA DEM 463 m | Mars | 463 m | [USGS Astrogeology](https://astrogeology.usgs.gov/search/map/mars_mgs_mola_dem_463m) |
| LRO LOLA south pole DEM | Moon | 80 m | [NASA GSFC PGDA](https://pgda.gsfc.nasa.gov/products/90) (Barker et al. 2023, [DOI 10.60903/gsfcpgda-lola-spole](https://doi.org/10.60903/gsfcpgda-lola-spole)) |

## Repository layout

```
config/       sites.yaml (sites, windows) · metrics.yaml (bins, weights) · regions.yaml (search regions)
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
  regions.py    search regions, SRTM GL3 tile download, VRT mosaic
  search.py     Analog Finder: scan, score, rank, known-site check
  explain.py    AI explanation via OpenRouter: search tool + number-grounding check
  server.py     local web platform (standard library HTTP server + JSON API)
  web/          single-page app: Analog Finder map, matrix, sites, Ask AI, method
  cli.py        status / prepare / approve / score / matrix / regions / search / serve / ask
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
| First real result: Gale vs Ustyurt = 0.12 | Done (hackathon, day 1) |
| Matrix: Gale + Meridiani × Ustyurt, Yungay, MDRS | Done (hackathon, day 1) — [results](docs/results.md) |
| Negative control (flat non-analog plain) | Planned (hackathon) |
| Kyzylkum | Planned (hackathon) |
| AI explanation (`ask`, OpenRouter, grounding check) | Done (hackathon, day 1) |
| Analog Finder (`search`) + AI search tool | Done (hackathon, day 1) — first real runs next |
| Moon reference (Mons Mouton Plateau, LOLA) | Done (hackathon, day 1) |
| Web platform (`serve`) | Done (hackathon, day 1) |
| AI yordamchi panel inside the Global Explorer (Moon/Mars reference → Earth leads → 3D compare) | Done (hackathon, day 1 night) |
| Demo video / slides, Space Apps project page | Planned (hackathon, day 2) |

## Work done before the hackathon

Space Apps allows preparation; we list it openly. Before 14 November 2026 the team prepared the concept, the presentation, the UI design ([design/terramind-ui.html](design/terramind-ui.html)), the technical specification ([docs/PHASE1.md](docs/PHASE1.md)) and the first two pipeline modules (`terramind/config.py`, `terramind/crs.py`). Everything else is built during the hackathon, 14–15 November 2026, and the commit history shows it.

## Secrets

The OpenTopography and OpenRouter API keys live only in a local `.env` file (see `.env.example`), which is git-ignored. Never commit it. The pipeline never prints it, and removes it from any error message.

## License

**Code:** Apache License 2.0 — see [LICENSE](LICENSE). Copyright 2026 the TerraMind AI team (NASA Space Apps Challenge 2026, Tashkent).

**Data and imagery we use** (cited as Space Apps requires; none of it is redistributed in this repository except small derived previews):

| Source | Used for | License / terms | Citation |
|---|---|---|---|
| Mars MGS MOLA DEM 463 m (USGS Astrogeology / NASA PDS) | Mars terrain | U.S. Government work, public domain | Smith et al., MOLA; astrogeology.usgs.gov/search/map/mars_mgs_mola_dem_463m |
| LRO LOLA south-pole DEM 80 m (NASA GSFC PGDA) | Moon terrain | U.S. Government work, public domain | Barker et al. 2023, doi:10.60903/gsfcpgda-lola-spole |
| NASA SRTM GL3 via OpenTopography | Earth terrain (Analog Finder) | NASA data public domain; OpenTopography API key under its non-commercial / academic terms (key kept private in `.env`) | doi:10.5069/G9445JDF |
| NOAA ETOPO 2022 (60″) | Global Earth screening index | U.S. Government work, public domain | NOAA NCEI, doi:10.25921/fd45-gt74 |
| Copernicus DEM GLO-30 | Global Explorer refinement | Free use with attribution | © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018, provided under COPERNICUS by the European Union and ESA |
| NASA Mars Trek (Viking MDIM 2.1) and Moon Trek (LRO WAC mosaic) tiles | Map backgrounds | NASA imagery, public domain; credit shown on the map | trek.nasa.gov |
| OpenStreetMap tiles | Earth map background | Data ODbL, attribution required; light use under the OSM tile policy | © OpenStreetMap contributors |
| Solar System Scope planet textures | 3D globes (Studio page) | CC BY 4.0 | Planet textures: Solar System Scope (CC BY 4.0) — see `web/public/ASSET-CREDITS.txt` |
| Poly Haven rock and sand textures | Visual surface detail | CC0 1.0 | Rob Tuytel, polyhaven.com |

**Software** (installed, not vendored): React, Vite, Three.js (MIT), Leaflet (BSD-2), lucide-react (ISC), FastAPI, Uvicorn (BSD/MIT), NumPy, SciPy, rasterio, pyproj, matplotlib, Pillow (BSD-style / PSF-based licenses).

**AI use:** large language models (via OpenRouter) only choose tools and explain computed results in the AI assistant; every score is computed by the algorithm and every number in an answer is checked. AI coding assistants were used during development. Any AI-generated visual is labelled "AI-generated" where it appears.

TerraMind AI is not affiliated with or endorsed by NASA, ESA or the other data providers.
