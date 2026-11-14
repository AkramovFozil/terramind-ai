# Data sources

Every input the pipeline reads is listed here. Each prepared window also records its own provenance in `data/processed/<site>/roi.json` (`input` block: dataset, source URL/DOI, file, file date, source CRS, native pixel size, nodata value, resampling).

## Mars — MGS MOLA DEM 463 m

| Field | Value |
|---|---|
| Name | Mars MGS MOLA DEM 463m (global mosaic) |
| Provider | USGS Astrogeology Science Center (data: NASA MGS MOLA team, PDS) |
| Page | https://astrogeology.usgs.gov/search/map/mars_mgs_mola_dem_463m |
| File | https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif (~2 GB) |
| Resolution | 463.08 m/pixel (128 pixels/degree) |
| CRS | Simple Cylindrical (Equirectangular), Mars sphere R = 3,396,190 m, longitude −180…180 |
| Values | elevation in metres relative to the MOLA areoid |
| How we use it | read locally; never downloaded automatically. `scripts/clip_mola_gale.py` can cut only the Gale window from the URL |
| Citation | Smith, D. E., et al. (2001), JGR Planets 106(E10). |

## Moon — LRO LOLA south pole DEM (80 m)

| Field | Value |
|---|---|
| Name | LOLA Digital Elevation Model, 80° S to pole, 80 m/pixel (`LDEM_80S_80MPP_ADJ.TIF`) |
| Provider | NASA Goddard Planetary Geodesy Data Archive (LRO Lunar Orbiter Laser Altimeter) |
| Page | https://pgda.gsfc.nasa.gov/products/90 |
| File | https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_80MPP_ADJ.TIF (~181 MB, cloud-optimised GeoTIFF) |
| CRS | south polar stereographic, metres, MOON_ME frame (JPL DE421); Moon sphere R = 1,737,400 m for our local projection |
| Values | surface height in metres |
| How we use it | read locally; averaged from 80 m to the 463 m matching grid |
| Citation | Barker, M. K., et al. (2023), *Planet. Sci. J.* 4, 183, doi:10.3847/PSJ/acf3e1. Data: doi:10.60903/gsfcpgda-lola-spole |

## Earth — SRTM GL1 v003

| Field | Value |
|---|---|
| Name | NASA SRTM Global 1 arc-second (SRTMGL1 v003) |
| Provider | NASA LP DAAC; served by the OpenTopography Global DEM API |
| DOI | [10.5067/MEaSUREs/SRTM/SRTMGL1.003](https://doi.org/10.5067/MEaSUREs/SRTM/SRTMGL1.003) |
| API | `https://portal.opentopography.org/API/globaldem?demtype=SRTMGL1&south=…&north=…&west=…&east=…&outputFormat=GTiff&API_Key=…` |
| Resolution | 1 arc-second (~30 m) |
| Coverage | 60° N – 56° S |
| CRS | geographic, WGS84 (EPSG:4326); elevation in metres (EGM96 geoid) |
| How we use it | one bounding-box request per window, cached in `data/raw/earth/` and never re-downloaded |
| Terms | OpenTopography API keys are for non-commercial use. TerraMind is a non-commercial student project. |
| Citation | Farr, T. G., et al. (2007), Reviews of Geophysics 45, RG2004. OpenTopography: https://doi.org/10.5069/G9445JDF |

## Earth — SRTM GL3 (Analog Finder)

The region search uses NASA SRTM GL3 (3 arc-second, ~90 m) from the same OpenTopography API (`demtype=SRTMGL3`), downloaded in tiles of up to 3° × 3° and cached in `data/raw/earth/regions/<region>/`, then averaged to the 463 m grid.

## Not used for scoring

- Satellite imagery links (Google Maps, OpenStreetMap) printed by `prepare` are only for a human to check a window for rivers, fields, towns or mines. They are not processed.
