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

## First results (14 Nov 2026)

![Similarity matrix](docs/results/matrix.png)

Known Mars analogs Yungay and MDRS score 0.77 and 0.66 against the Gale crater floor, so the method recognises them. Ustyurt does not resemble Gale (0.12) but scores 0.74 against Meridiani Planum, the flat plain where Opportunity landed. Full table, per-metric scores and limits: **[docs/results.md](docs/results.md)**.

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

**4. Web platform** — interactive map of the Analog Finder (satellite imagery to review leads, accept/reject), the matrix, every site's quick-look and approval, and Ask AI:

```bash
python -m terramind serve           # then open http://127.0.0.1:8000
```

Runs locally with the Python standard library; API keys stay on the server. Lead reviews are saved to `results/search/<search>/reviews.json`.

**5. Ask the AI** (needs `OPENROUTER_API_KEY` in `.env`) (needs `OPENROUTER_API_KEY` in `.env`):

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
| Demo video / slides, Space Apps project page | Planned (hackathon, day 2) |

## Work done before the hackathon

Space Apps allows preparation; we list it openly. Before 14 November 2026 the team prepared the concept, the presentation, the UI design ([design/terramind-ui.html](design/terramind-ui.html)), the technical specification ([docs/PHASE1.md](docs/PHASE1.md)) and the first two pipeline modules (`terramind/config.py`, `terramind/crs.py`). Everything else is built during the hackathon, 14–15 November 2026, and the commit history shows it.

## Secrets

The OpenTopography and OpenRouter API keys live only in a local `.env` file (see `.env.example`), which is git-ignored. Never commit it. The pipeline never prints it, and removes it from any error message.

## License

Open source, as Space Apps requires. The team will choose the license before submission; if none is stated, NASA distributes the original content under Apache 2.0.
