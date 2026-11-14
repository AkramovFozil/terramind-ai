# Validation

How we check that TerraMind measures something real, and what we have checked so far.

## 1. Unit tests (done)

`pytest` runs 35 tests on synthetic data, with no downloads:

| Area | Check |
|---|---|
| Mars CRS | 1° of latitude on the Mars sphere = 59,274 m ± 0.1 % |
| Earth CRS | 1° of latitude on WGS84 is 110.6–111.7 km |
| Wrong planet | Mars data in WGS84 (and the reverse) is refused |
| Grid | a 50 km window at 463 m is 108 ± 1 px on each side, for both planets |
| Slope | flat plane → 0°; plane rising 1 m per 1 m → 45° ± 0.01 (x, y and diagonal); true pixel size used |
| TRI | flat → 0; single spike and checkerboard → hand-computed values |
| Relief | median subtraction on a known array; empty input refused |
| Nodata | NaN spreads to its 3 × 3 neighbourhood; window edges are nodata |
| Histograms | identical → 1.0; disjoint → 0.0; half overlap → 0.5; under/overflow bins counted |
| Weights | weighted mean normalised by the weight sum; mismatched metrics refused |
| Spearman | same ranking → 1; reversed → −1; fewer than 3 sites refused |
| Quality | fewer than 2,500 valid pixels fails; more than 10 % nodata fails; both numbers reported |
| Inputs | missing MOLA file and missing API key give exact instructions; the API key never appears in errors; SRTM is cached |
| Gate | score refuses unapproved sites; refuses after a center change; approve refuses until prepared again |
| End to end | synthetic MOLA (Mars Equirectangular) + synthetic SRTM (EPSG:4326) → prepare → approve → score writes all files |

The tests found one real bug while being written: Horn's slope does not use the centre cell, so a nodata pixel surrounded by valid ones got a slope value. Fixed: a nodata centre is now always nodata.

## 2. Validation sites (Phase 2, planned)

Known Mars analogs are scored against Gale with exactly the same settings, so the Ustyurt score can be read on the same scale:

| Site | Why |
|---|---|
| Yungay, Atacama (Chile) | widely used Mars analog (hyper-arid) |
| MDRS, Utah (USA) | Mars Desert Research Station field site |

Expected: established analogs should not score far below the candidate. If Ustyurt scored much higher than both, we would check for a bias (e.g. flat terrain matching MOLA's smoothed equatorial grid) before claiming anything.

## 3. Weight sensitivity (Phase 2)

With three or more approved candidates, the Spearman correlation between the rankings under weight sets A and B is reported. ρ close to 1 means the ranking does not depend on the weights.

## 4. What validation cannot show

A high score means similar slope, relief and roughness **distributions** at 463 m. It does not show similar geology, origin, climate or suitability for a mission.
