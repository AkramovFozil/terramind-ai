import { useEffect, useId, useRef, useState } from 'react';
import L from 'leaflet';
import { useI18n } from '../i18n';
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

function fitMarsRegion(map: L.Map, center: Coordinates, radiusKm: number) {
  map.fitBounds(L.latLngBounds(marsCircle(center, radiusKm)), {
    paddingTopLeft: [48, 66], paddingBottomRight: [48, 91], maxZoom: 14, animate: false,
  });
}

export default function ScienceMap({
  body, center, radiusKm, onSelect, markers = EMPTY_MARKERS,
  onMarkerSelect, selectedId, focus,
}: ScienceMapProps) {
  const { locale, t } = useI18n();
  const hintId = useId();
  const elementRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const roiRef = useRef<L.LayerGroup | null>(null);
  const markersRef = useRef<L.LayerGroup | null>(null);
  const previewRef = useRef<{ update: () => void; clear: () => void } | null>(null);
  const callbacks = useRef({ onSelect, onMarkerSelect });
  const currentCenter = useRef(center);
  const currentRadius = useRef(radiusKm);
  const overviewRef = useRef({ markers, selectedId });
  const hasSelectedRegion = body !== 'earth' || Boolean(selectedId);
  const [tileState, setTileState] = useState<'loading' | 'ready' | 'error'>('loading');
  callbacks.current = { onSelect, onMarkerSelect };
  currentCenter.current = center;
  currentRadius.current = radiusKm;
  overviewRef.current = { markers, selectedId };

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return;
    const map = L.map(element, {
      crs: body === 'mars' ? MARS_CRS : body === 'moon' ? MOON_CRS : L.CRS.EPSG3857,
      center: focus ? [focus.lat, focus.lon] : [currentCenter.current.lat, currentCenter.current.lon],
      zoom: body === 'mars' ? 6 : body === 'moon' ? 0 : 3,
      minZoom: body === 'mars' ? 1 : 0,
      maxZoom: body === 'mars' ? 14 : body === 'moon' ? 10 : 18,
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
        maxZoom: 14,
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
    // Reuse one SVG path as the pointer moves; its radius always comes from
    // current props and its geometry uses Mars' sphere, including at the date line.
    const preview = L.polygon([], {
      color: '#fff3d9', weight: 1.5, dashArray: '4 6', fillOpacity: 0.035,
      interactive: false, className: 'science-map-preview-ring',
    });
    const previewPin = L.marker([0, 0], {
      icon: L.divIcon({ className: 'science-map-crosshair', iconSize: [22, 22], iconAnchor: [11, 11] }),
      interactive: false, keyboard: false,
    });
    let previewPoint: L.LatLng | null = null;
    let keyboardPreview = false;
    let dragging = false;
    const clearPreview = () => { preview.remove(); previewPin.remove(); previewPoint = null; };
    const drawPreview = () => {
      if (body !== 'mars' || !callbacks.current.onSelect || !previewPoint || dragging
        || Math.abs(previewPoint.lat) > 85) { clearPreview(); return; }
      preview.setLatLngs(marsCircle({ lat: previewPoint.lat, lon: previewPoint.lng }, currentRadius.current));
      previewPin.setLatLng(previewPoint);
      if (!map.hasLayer(preview)) { preview.addTo(map); previewPin.addTo(map); }
    };
    previewRef.current = { update: drawPreview, clear: clearPreview };
    map.on('mousemove', (event: L.LeafletMouseEvent) => {
      keyboardPreview = false;
      previewPoint = event.latlng;
      drawPreview();
    });
    map.on('mouseout zoomstart', clearPreview);
    map.on('dragstart', () => { dragging = true; keyboardPreview = false; clearPreview(); });
    map.on('dragend', () => { dragging = false; });
    map.on('moveend zoomend', () => {
      if (keyboardPreview) { previewPoint = map.getCenter(); drawPreview(); }
    });
    const keyboard = (event: KeyboardEvent) => {
      if (event.target !== element || !callbacks.current.onSelect || body !== 'mars') return;
      if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', '+', '-', '='].includes(event.key)) {
        keyboardPreview = true; previewPoint = map.getCenter(); drawPreview();
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        const point = map.getCenter();
        if (Math.abs(point.lat) <= 85) callbacks.current.onSelect(point.lat, normalLongitude(point.lng));
        keyboardPreview = true; previewPoint = point; drawPreview();
      }
      if (event.key === 'Escape') { keyboardPreview = false; clearPreview(); }
    };
    const onFocus = () => {
      if (element.matches(':focus-visible')) {
        keyboardPreview = true; previewPoint = map.getCenter(); drawPreview();
      }
    };
    const blur = () => { keyboardPreview = false; clearPreview(); };
    element.addEventListener('keydown', keyboard);
    element.addEventListener('focus', onFocus);
    element.addEventListener('blur', blur);
    const resize = new ResizeObserver(() => {
      map.invalidateSize({ pan: false });
      if (body === 'earth' && !overviewRef.current.selectedId) {
        fitEarthOverview(map, overviewRef.current.markers);
      }
    });
    resize.observe(element);
    return () => {
      resize.disconnect();
      element.removeEventListener('keydown', keyboard);
      element.removeEventListener('focus', onFocus);
      element.removeEventListener('blur', blur);
      tiles.off();
      map.remove();
      mapRef.current = null;
      roiRef.current = null;
      markersRef.current = null;
      previewRef.current = null;
    };
  }, [body]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const zoomIn = map.getContainer().querySelector<HTMLAnchorElement>('.leaflet-control-zoom-in');
    const zoomOut = map.getContainer().querySelector<HTMLAnchorElement>('.leaflet-control-zoom-out');
    const labels = [t({ ru: 'Приблизить', en: 'Zoom in', uz: 'Yaqinlashtirish' }), t({ ru: 'Отдалить', en: 'Zoom out', uz: 'Uzoqlashtirish' })];
    [zoomIn, zoomOut].forEach((button, index) => {
      if (button) { button.title = labels[index]; button.setAttribute('aria-label', labels[index]); }
    });
  }, [body, t]);

  useEffect(() => {
    if (onSelect) previewRef.current?.update();
    else previewRef.current?.clear();
  }, [radiusKm, onSelect]);

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
      color, weight: 2, fillColor: color, fillOpacity: 0.09, interactive: false,
    };
    if (body !== 'earth') {
      const ring = marsCircle(center, radiusKm, body === 'moon' ? MOON_RADIUS_M : MARS_RADIUS_M);
      for (const offset of [-360, 0, 360]) {
        L.polygon(ring.map(([lat, lon]): L.LatLngTuple => [lat, lon + offset]), style).addTo(group);
      }
    } else {
      L.circle([center.lat, center.lon], { ...style, radius: radiusKm * 1000 }).addTo(group);
    }
    for (const offset of body !== 'earth' ? [-360, 0, 360] : [0]) {
      L.marker([center.lat, center.lon + offset], {
        icon: L.divIcon({ className: 'science-map-selected-center', iconSize: [18, 18], iconAnchor: [9, 9] }),
        interactive: false, keyboard: false,
      }).addTo(group);
    }
    if (body === 'mars') {
      // Update the ring immediately, but wait for numeric input to settle
      // before reframing. Typing 1 → 10 → 100 should not bounce the camera.
      const timer = window.setTimeout(() => fitMarsRegion(map, center, radiusKm), 220);
      return () => window.clearTimeout(timer);
    }
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
        alt: `${point.name}${point.score === undefined ? '' : `, ${t({ ru: 'сходство', en: 'similarity', uz: 'o‘xshashlik' })} ${point.score.toLocaleString(locale, { maximumFractionDigits: 1 })}/100`}`,
        keyboard: true,
        zIndexOffset: active ? 1000 : 0,
      });
      const label = document.createElement('span');
      label.textContent = `${point.name}${point.score === undefined ? '' : ` · ${point.score.toLocaleString(locale, { maximumFractionDigits: 1 })}/100`}`;
      marker.bindTooltip(label, { direction: 'top', offset: [0, -12], className: 'science-map-tooltip' });
      marker.on('click', () => callbacks.current.onMarkerSelect?.(point.id));
      marker.addTo(group);
    });
    if (body === 'earth' && !selectedId && mapRef.current) {
      fitEarthOverview(mapRef.current, markers);
    }
  }, [body, markers, selectedId, locale, t]);

  function recenter() {
    const map = mapRef.current;
    if (!map) return;
    if (body === 'earth' && !selectedId) fitEarthOverview(map, markers);
    else if (body === 'mars') fitMarsRegion(map, center, radiusKm);
    else map.setView([center.lat, center.lon], 7, { animate: false });
  }

  const regionLabel = hasSelectedRegion
    ? t({ ru: 'Показать выбранный участок', en: 'Show selected region', uz: 'Tanlangan hududni ko‘rsatish' })
    : t({ ru: 'Показать все найденные участки', en: 'Show all candidate regions', uz: 'Barcha nomzod hududlarni ko‘rsatish' });
  const keyboardHint = t({ ru: 'Стрелки — перемещение, +/− — масштаб, Enter — выбрать центр карты.', en: 'Arrow keys pan, +/− zoom, Enter selects the map center.', uz: 'Strelkalar — siljitish, +/− — masshtab, Enter — xarita markazini tanlash.' });
  const pointerHint = t({ ru: 'Наведите курсор для просмотра радиуса · Нажмите, чтобы выбрать · Перетаскивайте карту', en: 'Hover to preview radius · Click to select · Drag to pan', uz: 'Radiusni ko‘rish uchun kursorni suring · Bosib tanlang · Xaritani sudrang' });

  return (
    <div className={`science-map science-map-${body}${onSelect ? ' is-selectable' : ''}`}>
      <div className="science-map-canvas" ref={elementRef}
        role="region" tabIndex={0} aria-describedby={onSelect ? hintId : undefined}
        aria-label={body === 'mars'
          ? t({ ru: 'Интерактивная карта Марса, снимки Viking', en: 'Interactive Mars map, Viking imagery', uz: 'Interaktiv Mars xaritasi, Viking tasvirlari' })
          : t({ ru: 'Интерактивная карта Земли', en: 'Interactive Earth map', uz: 'Interaktiv Yer xaritasi' })} />
      <div className="science-map-caption" aria-hidden="true">
        <span className="science-map-caption-dot" />
        {body === 'mars'
          ? t({ ru: 'VIKING ORBITER · МАРС', en: 'VIKING ORBITER · MARS', uz: 'VIKING ORBITER · MARS' })
          : t({ ru: 'ЗЕМЛЯ · НАЙДЕННЫЕ УЧАСТКИ', en: 'EARTH · CANDIDATE REGIONS', uz: 'YER · NOMZOD HUDUDLAR' })}
      </div>
      <button type="button" className="science-map-recenter" onClick={recenter}
        aria-label={regionLabel} title={regionLabel}>⌖</button>
      {hasSelectedRegion && <div className="science-map-coordinate-readout">
        {Math.abs(center.lat).toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}°{center.lat < 0 ? 'S' : 'N'}
        <span> / </span>
        {Math.abs(center.lon).toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}°{center.lon < 0 ? 'W' : 'E'}
        <span> · </span>{t({ ru: 'Радиус', en: 'Radius', uz: 'Radius' })} {radiusKm.toLocaleString(locale, { maximumFractionDigits: 2 })} {t({ ru: 'км', en: 'km', uz: 'km' })}
      </div>}
      {tileState !== 'ready' && <div className={`science-map-status ${tileState}`} role="status">
        {tileState === 'loading'
          ? t({ ru: 'Загрузка снимков…', en: 'Loading map imagery…', uz: 'Xarita tasvirlari yuklanmoqda…' })
          : t({ ru: 'Снимки недоступны. Координаты и выбор участка продолжают работать.', en: 'Imagery is unavailable. Coordinates and region selection remain active.', uz: 'Tasvirlar hozir ochilmadi. Koordinatalar va hudud tanlash ishlashda davom etadi.' })}
      </div>}
      {onSelect && <div className="science-map-select-hint" id={hintId}>
        <span className="science-map-pointer-hint">{pointerHint}</span>
        <span className="science-map-touch-hint">{t({ ru: 'Коснитесь для выбора · Перетаскивайте карту · Масштабируйте двумя пальцами', en: 'Tap to select · Drag to pan · Pinch to zoom', uz: 'Bosib tanlang · Sudrab siljiting · Ikki barmoq bilan masshtablang' })}</span>
        <span className="science-map-keyboard-hint">{keyboardHint}</span>
      </div>}
    </div>
  );
}
