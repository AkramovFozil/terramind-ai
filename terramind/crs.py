"""Coordinate reference systems for Earth and Mars.

Mars is NOT Earth: every Mars distance uses a sphere of radius 3,396,190 m.
Never use WGS84 / EPSG:4326 maths for Mars.
"""

from __future__ import annotations

from pyproj import CRS, Geod
from rasterio.crs import CRS as RioCRS

from terramind.config import ConfigError

MARS_RADIUS_M = 3_396_190.0
EARTH_SEMI_MAJOR_M = 6_378_137.0

MARS_GEOGRAPHIC = f"+proj=longlat +R={MARS_RADIUS_M:.0f} +no_defs"
EARTH_GEOGRAPHIC = "EPSG:4326"


def local_crs_string(body: str, lat: float, lon: float) -> str:
    """Azimuthal Equidistant projection centred on the site, in metres."""
    if body == "earth":
        return f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs"
    if body == "mars":
        return f"+proj=aeqd +lat_0={lat} +lon_0={lon} +R={MARS_RADIUS_M:.0f} +units=m +no_defs"
    raise ConfigError(f"Unknown body {body!r}")


def local_crs(body: str, lat: float, lon: float) -> RioCRS:
    return RioCRS.from_string(local_crs_string(body, lat, lon))


def geographic_crs_string(body: str) -> str:
    if body == "earth":
        return EARTH_GEOGRAPHIC
    if body == "mars":
        return MARS_GEOGRAPHIC
    raise ConfigError(f"Unknown body {body!r}")


def geod(body: str) -> Geod:
    if body == "earth":
        return Geod(ellps="WGS84")
    if body == "mars":
        return Geod(a=MARS_RADIUS_M, f=0.0)
    raise ConfigError(f"Unknown body {body!r}")


def semi_major_axis_m(crs) -> float:
    """Semi-major axis of a CRS's ellipsoid (works for rasterio or pyproj CRS)."""
    wkt = crs.to_wkt() if hasattr(crs, "to_wkt") else str(crs)
    ellipsoid = CRS.from_user_input(wkt).ellipsoid
    if ellipsoid is None:
        raise ConfigError("CRS has no ellipsoid")
    return float(ellipsoid.semi_major_metre)


def check_body_crs(crs, body: str, label: str = "input") -> None:
    """Refuse a raster whose CRS belongs to the wrong planet."""
    if crs is None:
        raise ConfigError(f"{label} has no CRS")
    a = semi_major_axis_m(crs)
    if body == "mars" and abs(a - MARS_RADIUS_M) > 2_000:
        raise ConfigError(f"{label}: CRS radius {a:,.0f} m is not Mars ({MARS_RADIUS_M:,.0f} m)")
    if body == "earth" and abs(a - EARTH_SEMI_MAJOR_M) > 1_000:
        raise ConfigError(f"{label}: CRS semi-major axis {a:,.0f} m is not Earth (WGS84)")
