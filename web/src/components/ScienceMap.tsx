import { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './science-map.css';

type Coordinates = { lat: number; lon: number };
export type ScienceMapMarker = Coordinates & {
  id: string;
  name: string;
  score?: number;
};

export type ScienceMapProps = {
  body: 'mars' | 'moon' | 'earth';
  center: Coordinates;
  radiusKm: number;
  onSelect?: (lat: number, lon: number) => void;
  markers?: ScienceMapMarker[];
  onMarkerSelect?: (id: string) => void;
  selectedId?: string;
  /** Where to point the camera, if not at the selected region (whole-Moon view). */
  focus?: Coordinates;
};

const MARS_RADIUS_M = 3_396_190;
const DEG = Math.PI / 180;
const VIKING_TILES = 'https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/default/default028mm/{z}/{y}/{x}.jpg';
const MOON_RADIUS_M = 1_737_400;
// Same NASA Trek EQ tile matrix as Mars (two columns, one row at zoom zero).
const MOON_TILES = 'https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/default/default028mm/{z}/{y}/{x}.jpg';
const EMPTY_MARKERS: ScienceMapMarker[] = [];

function normalLongitude(longitude: number) {
  return ((longitude + 180) % 360 + 360) % 360 - 180;
}

function marsDistance(a: L.LatLng, b: L.LatLng) {
  const h = Math.sin((b.lat - a.lat) * DEG / 2) ** 2
    + Math.cos(a.lat * DEG) * Math.cos(b.lat * DEG)
    * Math.sin((b.lng - a.lng) * DEG / 2) ** 2;
  return 2 * MARS_RADIUS_M * Math.asin(Math.sqrt(Math.min(1, Math.max(0, h))));
}

// NASA's EQ WMTS has two columns and one row at zoom zero. EPSG4326's
// pixel transformation matches that matrix, but distances use the Mars sphere.
const MARS_CRS: L.CRS = L.extend({}, L.CRS.EPSG4326, {
  code: 'IAU2000:49900',
  R: MARS_RADIUS_M,
  distance: marsDistance,
});

function moonDistance(a: L.LatLng, b: L.LatLng) {
  return marsDistance(a, b) * MOON_RADIUS_M / MARS_RADIUS_M;
}

const MOON_CRS: L.CRS = L.extend({}, L.CRS.EPSG4326, {
  code: 'IAU2000:30100',
  R: MOON_RADIUS_M,
  distance: moonDistance,
});

function marsCircle(center: Coordinates, radiusKm: number, sphereM = MARS_RADIUS_M): L.LatLngTuple[] {
  const latitude = center.lat * DEG;
  const longitude = center.lon * DEG;
  const angularDistance = radiusKm * 1000 / sphereM;
  return Array.from({ length: 129 }, (_, index) => {
    const bearing = index / 128 * 2 * Math.PI;
    const lat = Math.asin(Math.sin(latitude) * Math.cos(angularDistance)
      + Math.cos(latitude) * Math.sin(angularDistance) * Math.cos(bearing));
    const lon = longitude + Math.atan2(
      Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(latitude),
      Math.cos(angularDistance) - Math.sin(latitude) * Math.sin(lat),
    );
    // Keep the ring continuous across the date line. Copies below support
    // both sides of Leaflet's wrapped world without a polygon across the planet.
    return [lat / DEG, center.lon + normalLongitude(lon / DEG - center.lon)];
  });
}

function fitEarthOverview(map: L.Map, markers: ScienceMapMarker[]) {
  if (markers.length) {
    map.fitBounds(L.latLngBounds(markers.map(({ lat, lon }): L.LatLngTuple => [lat, lon])), {
      padding: [42, 56], maxZoom: 4, animate: false,
    });
  } else {
    map.fitWorld({ animate: false });
  }
}

export default function ScienceMap({
  body, center, radiusKm, onSelect, markers = EMPTY_MARKERS,
  onMarkerSelect, selectedId, focus,
}: ScienceMapProps) {
  const elementRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const roiRef = useRef<L.LayerGroup | null>(null);
  const markersRef = useRef<L.LayerGroup | null>(null);
  const callbacks = useRef({ onSelect, onMarkerSelect });
  const currentCenter = useRef(center);
  const overviewRef = useRef({ markers, selectedId });
  const hasSelectedRegion = body !== 'earth' || Boolean(selectedId);
  const [tileState, setTileState] = useState<'loading' | 'ready' | 'error'>('loading');
  callbacks.current = { onSelect, onMarkerSelect };
  currentCenter.current = center;
  overviewRef.current = { markers, selectedId };

  useEffect(() => {
    if (!elementRef.current) return;
    const map = L.map(elementRef.current, {
      crs: body === 'mars' ? MARS_CRS : body === 'moon' ? MOON_CRS : L.CRS.EPSG3857,
      center: focus ? [focus.lat, focus.lon] : [currentCenter.current.lat, currentCenter.current.lon],
      zoom: body === 'mars' ? 6 : body === 'moon' ? 0 : 3,
      minZoom: body === 'mars' ? 1 : 0,
      maxZoom: body === 'earth' ? 18 : 10,
      zoomControl: false,
      worldCopyJump: true,
      attributionControl: true,
    });
    mapRef.current = map;
    roiRef.current = L.layerGroup().addTo(map);
    markersRef.current = L.layerGroup().addTo(map);
    setTileState('loading');
    map.attributionControl.setPrefix(false);
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    L.control.scale({ position: 'bottomleft', imperial: false, maxWidth: 110 }).addTo(map);

    const tiles = body === 'moon'
      ? L.tileLayer(MOON_TILES, {
        maxNativeZoom: 7,
        maxZoom: 10,
        crossOrigin: 'anonymous',
        attribution: '<a href="https://trek.nasa.gov/moon/" target="_blank" rel="noreferrer">NASA Moon Trek</a> · LRO WAC mosaic',
      })
      : body === 'mars'
      ? L.tileLayer(VIKING_TILES, {
        maxNativeZoom: 7,
        maxZoom: 10,
        crossOrigin: 'anonymous',
        attribution: '<a href="https://trek.nasa.gov/mars/" target="_blank" rel="noreferrer">NASA/JPL Mars Trek</a> · USGS Viking MDIM 2.1',
      })
      : L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>',
      });
    tiles.on('tileload', () => setTileState('ready'));
    tiles.on('tileerror', () => setTileState('error'));
    tiles.addTo(map);
    map.on('click', (event: L.LeafletMouseEvent) => {
      if (body !== 'moon' && (event.latlng.lat < -85 || event.latlng.lat > 85)) return;
      callbacks.current.onSelect?.(event.latlng.lat, normalLongitude(event.latlng.lng));
    });
    const resize = new ResizeObserver(() => {
      map.invalidateSize({ pan: false });
      if (body === 'earth' && !overviewRef.current.selectedId) {
        fitEarthOverview(map, overviewRef.current.markers);
      }
    });
    resize.observe(elementRef.current);
    return () => {
      resize.disconnect();
      tiles.off();
      map.remove();
      mapRef.current = null;
      roiRef.current = null;
      markersRef.current = null;
    };
  }, [body]);

  useEffect(() => {
    const map = mapRef.current;
    const group = roiRef.current;
    if (!map || !group) return;
    group.clearLayers();
    // The Earth catalog is an overview, not a selected measurement at the
    // camera's fallback center. Draw a measurement only after selection.
    if (!hasSelectedRegion) return;
    const color = body === 'mars' ? '#f0c59d' : body === 'moon' ? '#f2cc9e' : '#b9e3ce';
    const style: L.PathOptions = {
      color, weight: 1.8, fillColor: color, fillOpacity: 0.09,
      dashArray: '5 5', interactive: false,
    };
    if (body !== 'earth') {
      const ring = marsCircle(center, radiusKm, body === 'moon' ? MOON_RADIUS_M : MARS_RADIUS_M);
      for (const offset of [-360, 0, 360]) {
        L.polygon(ring.map(([lat, lon]): L.LatLngTuple => [lat, lon + offset]), style).addTo(group);
      }
    } else {
      L.circle([center.lat, center.lon], { ...style, radius: radiusKm * 1000 }).addTo(group);
    }
    L.circleMarker([center.lat, center.lon], {
      radius: 4, color: '#fff8e9', weight: 2, fillColor: color,
      fillOpacity: 1, interactive: false,
    }).addTo(group);
    if (!focus) map.panTo([center.lat, center.lon], { animate: false });
  }, [body, center.lat, center.lon, radiusKm, hasSelectedRegion]);

  useEffect(() => {
    const group = markersRef.current;
    if (!group) return;
    group.clearLayers();
    markers.forEach((point, index) => {
      const active = point.id === selectedId;
      const badge = document.createElement('span');
      badge.className = `science-map-pin${active ? ' is-selected' : ''}`;
      badge.textContent = String(index + 1);
      const marker = L.marker([point.lat, point.lon], {
        icon: L.divIcon({ className: 'science-map-pin-holder', html: badge, iconSize: [30, 30], iconAnchor: [15, 15] }),
        title: point.name,
        alt: `${point.name}${point.score === undefined ? '' : `, score ${point.score.toFixed(1)}`}`,
        keyboard: true,
        zIndexOffset: active ? 1000 : 0,
      });
      const label = document.createElement('span');
      label.textContent = `${point.name}${point.score === undefined ? '' : ` · ${point.score.toFixed(1)}/100`}`;
      marker.bindTooltip(label, { direction: 'top', offset: [0, -12], className: 'science-map-tooltip' });
      marker.on('click', () => callbacks.current.onMarkerSelect?.(point.id));
      marker.addTo(group);
    });
    if (body === 'earth' && !selectedId && mapRef.current) {
      fitEarthOverview(mapRef.current, markers);
    }
  }, [body, markers, selectedId]);

  function recenter() {
    const map = mapRef.current;
    if (!map) return;
    if (body === 'earth' && !selectedId) fitEarthOverview(map, markers);
    else map.setView([center.lat, center.lon], 7, { animate: false });
  }

  return (
    <div className={`science-map science-map-${body}`}>
      <div className="science-map-canvas" ref={elementRef}
        role="region" aria-label={`${body === 'mars' ? 'Mars Viking imagery' : 'Earth'} interactive map. ${onSelect ? 'Click to choose a region.' : 'Use the map controls to explore.'}`} />
      <div className="science-map-caption" aria-hidden="true">
        <span className="science-map-caption-dot" />
        {body === 'mars' ? 'VIKING ORBITER · MARS' : 'EARTH · CANDIDATE REGIONS'}
      </div>
      <button type="button" className="science-map-recenter" onClick={recenter}
        aria-label={hasSelectedRegion ? 'Recenter map on selected region' : 'Show all candidate regions'}
        title={hasSelectedRegion ? 'Recenter on selected region' : 'Show all candidate regions'}>⌖</button>
      {hasSelectedRegion && <div className="science-map-coordinate-readout">
        {Math.abs(center.lat).toFixed(3)}°{center.lat < 0 ? 'S' : 'N'}
        <span> / </span>
        {Math.abs(center.lon).toFixed(3)}°{center.lon < 0 ? 'W' : 'E'}
        <span> · </span>{radiusKm} km radius
      </div>}
      {tileState !== 'ready' && <div className={`science-map-status ${tileState}`} role="status">
        {tileState === 'loading' ? 'Loading map imagery…' : 'Map imagery is unavailable. Coordinates and region selection remain active.'}
      </div>}
      {onSelect && <span className="science-map-select-hint">Click the map to move the region</span>}
    </div>
  );
}
