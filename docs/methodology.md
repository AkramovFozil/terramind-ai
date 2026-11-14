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

## 6. Known limitations

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
