# TerraMind AI — Phase 1: DEM pipeline (Gale + Ustyurt)

You are the geospatial engineer for TerraMind AI, a NASA Space Apps 2026 project that
compares terrain on Earth with reference sites on Mars using NASA open elevation data.

Build ONLY Phase 1 below. Do NOT build: frontend, LLM/chatbot, database server, Docker,
PostGIS, Redis, 3D, computer vision, ML training, hazard map. Work in small steps, run the
tests after each module, and ASK before changing any scientific choice listed here
(window size, CRS, metrics, bins, weights, similarity method).

## Goal

One reference site on Mars (Gale Crater) and one candidate site on Earth (Ustyurt), processed
into comparable terrain metrics on a common 463 m grid, with a human review gate before scoring.

## Stack

Python 3.11. rasterio, numpy, scipy, pyproj, matplotlib, pyyaml, requests, python-dotenv, pytest.
CLI via `python -m terramind <command>`. Must run on Windows, macOS and Linux.
No GeoPandas, no web server in this phase.

## Repo layout

```
terramind/            # package: cli.py, config.py, crs.py, roi.py, terrain.py,
                      # similarity.py, quicklook.py, gate.py, sources/opentopo.py, sources/mola.py
config/sites.yaml     # sites, roles, centers, status
config/metrics.yaml   # bin edges, weight sets
data/raw/             # input DEMs (gitignored)
data/processed/<site>/
results/<target>__<candidate>/
tests/
docs/methodology.md, docs/data-sources.md, docs/validation.md
README.md, .env.example, .gitignore (.env, data/raw/)
```

## Sites (config/sites.yaml)

| id       | body  | role       | center lat, lon      | enabled |
|----------|-------|------------|----------------------|---------|
| gale     | mars  | reference  | -4.49, 137.42        | yes     |
| ustyurt  | earth | candidate  | 43.6510, 56.1280 (PROVISIONAL — team picks final center after quick-look; 56°E is near the Kazakhstan border) | yes |
| kyzylkum | earth | candidate  | null (TBD by team)   | no      |
| yungay   | earth | validation | -24.0848, -69.9151   | no      |
| mdrs     | earth | validation | 38.4062, -110.7894   | no      |

Refuse to process a site whose center is null. Disabled sites are Phase 2.

## Data sources

- **Mars:** USGS Astrogeology "Mars MGS MOLA DEM 463m" global GeoTIFF, read from a LOCAL file.
  Path configurable; default `data/raw/mars/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif`.
  Never download this ~2 GB file automatically. If missing, print the exact path expected and
  the USGS page to get it, then exit non-zero.
  Check the file's longitude domain (−180..180 vs 0..360) before clipping.
- **Earth:** SRTMGL1 v3 (~30 m) via OpenTopography Global DEM API (`demtype=SRTMGL1`,
  bbox request, GeoTIFF). API key from env var `OPENTOPO_API_KEY` (.env, never hard-coded,
  never logged). Cache the download in `data/raw/earth/`; do not re-download if present.
- Record for every input: dataset name, version, source URL/DOI, download date, native
  resolution, CRS. Write it into `docs/data-sources.md` and each site's `roi.json`.

## CRS — the most important rule

Mars is NOT Earth.
- Earth ROI: local Azimuthal Equidistant projection on WGS84 centered on the site
  (`+proj=aeqd +lat_0=<lat> +lon_0=<lon> +datum=WGS84 +units=m`).
- Mars ROI: local Azimuthal Equidistant projection on a Mars sphere
  (`+proj=aeqd +lat_0=<lat> +lon_0=<lon> +R=3396190 +units=m +no_defs`).
- Never compute Mars distances, pixel sizes or slopes with WGS84/EPSG:4326 math.

## ROI and grids

1. ROI = 50 × 50 km square in the site's local metric CRS, centered exactly on the configured center.
2. Matching grid: 463 m pixels for both bodies (≈ 108 × 108 px).
   - Earth: aggregate 30 m → 463 m with `average` resampling. Document it.
   - Mars: reproject MOLA into the Mars local CRS at 463 m (`bilinear`). Document it.
3. Keep the native ~30 m Earth DEM in the local CRS as a separate file (for the Phase 2 hazard map).
4. Fail if a ROI has fewer than 2,500 valid pixels or more than 10% nodata; report both numbers.

## Metrics (on the 463 m grids, identical code for both bodies)

- **Slope:** Horn's 3×3 method, degrees, using the true pixel size in metres.
- **Local relief:** elevation minus the ROI median elevation, metres (planets have different zero levels).
- **Roughness (TRI):** mean absolute difference between a cell and its 8 neighbours, metres.
- Cells without a full valid 3×3 neighbourhood become nodata. Never fill or invent values.

## Similarity

- Per metric: normalized histograms on FIXED bin edges from `config/metrics.yaml`, same for every
  site, with underflow/overflow bins. Score = histogram intersection Σ min(p, q), range 0–1.
  Suggested bins: slope 0–45° step 0.5; relief −1000..+1000 m step 10; TRI 0–200 m step 1.
- Overall = weighted mean. Two weight sets:
  A: slope 0.40, relief 0.35, roughness 0.25 · B: 1/3 each. Report both.
- Implement Spearman rank correlation between the A and B rankings, but only run it when
  there are ≥ 3 candidates (Phase 2). Unit-test it now.

## Human review gate (scoring must not run before this)

1. `python -m terramind prepare --site <id>` → clips, reprojects, computes metrics, writes:
   `dem_463m.tif`, `slope_463m.tif`, `relief_463m.tif`, `tri_463m.tif`, (Earth) `dem_30m.tif`,
   `quicklook.png`, `roi.json` with `status: pending_review`.
2. `quicklook.png`: hillshade (az 315°, alt 45°) of the 463 m DEM, plus the 30 m hillshade for
   Earth; center marker, 10 km scale bar, title with site, body, center and bbox. For Earth
   sites also print a satellite-view map link for the ROI center so a human can check for
   rivers, fields, towns and mines.
3. `python -m terramind approve --site <id>` → sets `status: approved`, `approved_at`, and a
   `params_hash` of (center, window, CRS, dataset, grid).
4. `python -m terramind score --target gale --candidate ustyurt` → REFUSES with a clear
   message if either site is not approved or its params changed since approval.
   Otherwise writes to `results/gale__ustyurt/`: `metrics.json`, `comparison.csv`,
   `histograms.png` (overlay per metric; Earth filled, Mars outlined).

## Known limitation to document

MOLA's 128 px/degree grid near the equator is partly interpolated between orbit tracks, so
roughness at Gale may be underestimated. Write this in `docs/methodology.md`.

## Tests (pytest, all must pass)

- Mars: 1° of latitude on the Mars sphere = 59,274 m ± 0.1%.
- Earth: 1° of latitude ≈ 110.6–111.7 km on WGS84.
- ROI at 463 m is 108 ± 1 px on each side, for both bodies.
- Slope: flat plane → 0°; plane rising 1 m per 1 m → 45° ± 0.01.
- TRI: flat → 0; a known synthetic pattern → its hand-computed value.
- Relief: median subtraction on a known array.
- Nodata: NaN propagates; edge cells are nodata.
- Histogram intersection: identical → 1.0; disjoint → 0.0.
- Gate: score refuses when unapproved; refuses when params_hash changed.
- Valid-pixel check fails below 2,500.

## Acceptance

1. `pytest` passes.
2. With the MOLA file and an API key present, `prepare` for gale and ustyurt produces all files above.
3. `score` refuses before approval; after approval it writes the three result files.
4. A missing input or key gives exact instructions and a non-zero exit — never fake output.
5. README lists the exact commands, in order, from a fresh clone.

Stop after Phase 1 and summarize what was built, what was tested, and any open questions.
