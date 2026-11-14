# Methodology (Phase 1)

TerraMind compares the **shape of terrain** in two 25 × 25 km windows, one on Mars and one on Earth. It does not compare geology, minerals, climate or habitability.

## 1. Windows and projections

- Each site has a fixed center in `config/sites.yaml`. The window is a 25 × 25 km square centered exactly on it (`window_km` in `config/sites.yaml`).
- Each window gets its own **local azimuthal equidistant (AEQD)** projection centered on the site, so distances and pixel sizes are true metres near the center.
  - Mars: `+proj=aeqd +lat_0=<lat> +lon_0=<lon> +R=3396190 +units=m` — the IAU Mars sphere used by MOLA.
  - Earth: `+proj=aeqd +lat_0=<lat> +lon_0=<lon> +datum=WGS84 +units=m`.
- Mars data is never processed with Earth (WGS84 / EPSG:4326) maths. The code refuses a raster whose CRS radius belongs to the wrong planet.

## 2. Common grid

- Both planets are resampled to the same **463 m** grid (54 × 54 = 2,916 pixels), close to MOLA's native resolution.
  - Earth SRTM (~30 m) → 463 m with **average** resampling (each 463 m cell is the mean of the few hundred SRTM cells inside it).
  - Mars MOLA (463 m) → local grid with **bilinear** resampling.
- Earth also keeps a **30 m** version of the window (`dem_30m.tif`, bilinear) for the Phase 2 hazard map. It is not used for the score.
- A window fails if it has fewer than **2,500 valid pixels** or more than **10 % nodata**. Both numbers are reported.

## 3. Metrics

All three are computed with the same code for both planets, on the 463 m grid.

| Metric | Definition | Unit |
|---|---|---|
| Slope | Horn (1981) 3 × 3 finite differences, using the true pixel size | degrees |
| Local relief | elevation − median elevation of the window | metres |
| Roughness (TRI) | mean absolute difference between a cell and its 8 neighbours | metres |

Local relief removes the absolute height, because Mars and Earth have different zero levels (areoid vs. geoid).
Cells without a complete valid 3 × 3 neighbourhood (window edges, next to nodata) become nodata. Nothing is filled or interpolated.

## 4. Similarity

- For each metric, both windows are turned into **normalised histograms on fixed bins** (`config/metrics.yaml`), identical for every site:
  slope 0–45° step 0.5; relief −1000…+1000 m step 10; TRI 0–200 m step 1.
  Values below or above the range go to separate under/overflow bins, so no pixel is dropped.
- Score per metric = **histogram intersection** Σ min(pᵢ, qᵢ): 0 = no overlap, 1 = identical distributions.
- Overall score = weighted mean of the three metric scores. Two weight sets are always reported:
  - **A:** slope 0.40, relief 0.35, roughness 0.25
  - **B:** equal weights
- With three or more approved candidates, the Spearman rank correlation between the A and B rankings shows whether the ranking depends on the choice of weights (Phase 2; implemented and unit-tested now).

## 5. Human review gate

1. `prepare` builds the window, metrics and a hillshade **quick-look** (az 315°, alt 45°, 2× vertical exaggeration), and marks the site `pending_review`.
2. A person checks the quick-look and, for Earth, the satellite view: rivers, fields, towns, mines, data edges.
3. `approve` records the time and a SHA-256 hash of the window parameters (center, window size, grid, CRS, dataset).
4. `score` refuses to run unless both sites are approved and their parameters are unchanged since approval.

The center is frozen **before** any score is seen, so a site cannot be moved around until it scores well.

## 6. Analog Finder (search)

The search turns the question around: given an approved Mars reference, which places in a region of Earth look most like it?

1. A region is a box in `config/regions.yaml` (e.g. western Uzbekistan, or Utah around MDRS for validation).
2. NASA SRTM GL3 (3 arc-second, ~90 m) is downloaded from OpenTopography in tiles and mosaicked.
3. 25 km windows are placed every `stride_km` (5 km for validation regions, 12.5 km for large ones), each fully inside the box.
4. Each window goes through exactly the same steps as a site: local AEQD, average to 463 m, slope / relief / TRI, histogram intersection against the reference's histograms, weighted mean.
5. Windows with more than 10 % nodata are skipped. SRTM flattens lakes and seas to a constant height, so windows where more than 5 % of slope pixels are exactly 0 are marked as water and skipped.
6. The top list keeps the best windows that are at least one window width (25 km) apart, so it is not ten copies of the same place.
7. If a known site lies in the region, the rank of its nearest window is reported. This checks whether the search singles out known analog terrain.

Search results are **leads**: a person checks satellite imagery, and a lead becomes a site only through the normal prepare → review → approve steps. The reference must be approved before it can be searched for.

An AI model can start a search from a plain-language request (`ask`), but only through this tool, with a fixed list of references and regions; it never names places from its own knowledge, and every number in its answer is checked against the computed results.

## 7. Known limitations

- **MOLA interpolation near the equator.** MOLA's 128 pixels/degree grid is built from orbit tracks that are sparse near the equator; between tracks the values are interpolated. Roughness (TRI) at Gale may therefore be **underestimated**, which biases the Mars TRI histogram toward smoother terrain.
- **Resolution mismatch at source.** SRTM averaged to 463 m and MOLA at 463 m are not identical products: MOLA cells are partly interpolated, SRTM cells are true averages. The common grid reduces, but does not remove, this difference.
- **Distributions, not shapes.** Histogram intersection compares how often each slope, relief or roughness value occurs. Two windows with the same distribution can still have different spatial patterns (e.g. one large crater vs. many small hills).
- **One window per site.** The score depends on the chosen center. That is why centers are frozen before scoring and why validation sites are added in Phase 2.
- **Gravity, atmosphere and erosion differ.** Similar shapes on Earth and Mars can come from different processes.

## References

- Horn, B. K. P. (1981). Hill shading and the reflectance map. *Proceedings of the IEEE*, 69(1), 14–47.
- Riley, S. J., DeGloria, S. D., & Elliot, R. (1999). A terrain ruggedness index that quantifies topographic heterogeneity. *Intermountain Journal of Sciences*, 5, 23–27.
- Swain, M. J., & Ballard, D. H. (1991). Color indexing. *International Journal of Computer Vision*, 7(1), 11–32. (histogram intersection)
- Smith, D. E., et al. (2001). Mars Orbiter Laser Altimeter: Experiment summary after the first year of global mapping of Mars. *JGR Planets*, 106(E10), 23689–23722.
- Farr, T. G., et al. (2007). The Shuttle Radar Topography Mission. *Reviews of Geophysics*, 45, RG2004.

## Decision log

| Date | Decision | Why |
|---|---|---|
| 2026-11-14 | Window reduced from **50 km to 25 km** for every site, before any score was computed. | The first real Gale quick-look (MOLA) showed that a 50 km window around −4.49°, 137.42° is not only crater floor: it includes the northern crater wall and the foot of Aeolis Mons (Mount Sharp), up to ~4.7 km above the window median. 26 % of pixels were more than 1 km above the median and 22 % had slopes above 10°. In the 25 km window at the same center these drop to 0.2 % and 3 %, so the reference really is Aeolis Palus. 25 km is close to the smallest window that still passes the 2,500-pixel minimum at 463 m (2,916 pixels). |
| 2026-11-14 | Ustyurt center moved from 56.128° E to **56.180° E** (latitude unchanged) and marked final, before any score was computed. | At 56.128° E the west edge of the 25 km window (55.973° E) crossed the Kazakhstan–Uzbekistan border, which follows the 56th meridian here. At 56.180° E the window spans 56.025–56.335° E, entirely in Uzbekistan. The reason is geographic, not the score. |
| 2026-11-14 | **Comparison matrix declared** before any new score: Mars references **Gale** and **Meridiani Planum** (Opportunity landing site, 1.9462° S, 354.4734° E) × Earth sites **Ustyurt** (candidate), **Yungay** and **MDRS** (known Mars analogs, validation). | The first result, Gale vs Ustyurt = 0.12, showed that this part of Ustyurt is far smoother than Gale's floor (median slope 0.1° vs 1.4°). Meridiani was added *after* seeing that score, as one of the flattest landing plains on Mars; we say so openly. Yungay and MDRS give the scale: how high do established analogs score with the same settings? Every cell is reported, including Gale–Ustyurt 0.12. The `matrix` command refuses to run until every enabled site is approved, so no cell can be dropped. |
| 2026-11-14 | **Analog Finder added**: scan a region for windows similar to a Mars reference, with the same method. First regions: Utah and Atacama (validation, contain MDRS and Yungay), western Uzbekistan and Uzbekistan. | Comparing hand-picked sites cannot discover new analogs. The validation regions test whether the search ranks known analog terrain highly before we trust leads in Uzbekistan. |
