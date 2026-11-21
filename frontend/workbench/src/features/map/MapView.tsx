import { useEffect, useRef } from 'react';
import L from 'leaflet';
import type { LeafletMouseEvent, Map as LeafletMap } from 'leaflet';
import type { LineGeometry, MapFlightEntry, SelectedFeature, WorkbenchState } from '../../api/types';

const colors = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#B77900', '#56B4E9', '#E69F00', '#6A3D9A', '#1B9E77', '#E7298A'];
function escapeHtml(value: unknown) { return String(value ?? '—').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]!); }
function featurePopup(feature: GeoJSON.Feature) {
  const properties = feature.properties ?? {}, node = feature.geometry.type === 'Point';
  const identity = node ? properties.id : `${properties.id.u}—${properties.id.v} · ${properties.id.key}`;
  const details = [properties.aeroway, properties.ref, properties.name].filter(value => value !== null && value !== undefined && value !== '');
  return `<div class="feature-popup"><strong>${node ? '节点' : '边'} · ${escapeHtml(identity)}</strong>${details.map(value => `<span>${escapeHtml(value)}</span>`).join('')}</div>`;
}
interface Props {
  state: WorkbenchState;
  flights: Map<string, MapFlightEntry>;
  splitValidation: boolean;
  baseLayer?: 'none' | 'osm' | 'satellite';
  showEdges?: boolean;
  showParking?: boolean;
  showNodes?: boolean;
  selected?: SelectedFeature[];
  drawPoints?: Array<[number, number]>;
  previewGeometry?: LineGeometry | null;
  focusFlightKey?: string | null;
  fitMapVersion?: number;
  observationLocation?: [number, number] | null;
  onFeature(feature: SelectedFeature): void;
  onMapClick(longitude: number, latitude: number): void;
}

export function MapView({ state, flights, splitValidation, baseLayer = 'none', showEdges = true, showParking = true, showNodes = true, selected = [], drawPoints = [], previewGeometry, focusFlightKey, fitMapVersion = 0, observationLocation, onFeature, onMapClick }: Props) {
  const element = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const graphGroup = useRef<L.LayerGroup | null>(null);
  const flightGroup = useRef<L.LayerGroup | null>(null);
  const previewGroup = useRef<L.LayerGroup | null>(null);
  const baseLayers = useRef<Record<'osm' | 'satellite', L.TileLayer> | null>(null);
  const fitted = useRef(false);
  const featureHandler = useRef(onFeature);
  const mapClickHandler = useRef(onMapClick);
  featureHandler.current = onFeature;
  mapClickHandler.current = onMapClick;

  useEffect(() => {
    if (!element.current) return;
    const map = L.map(element.current, { preferCanvas: true, zoomControl: false, maxZoom: 26 });
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxNativeZoom: 19, maxZoom: 26, attribution: '© OpenStreetMap contributors' });
    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom: 19, maxZoom: 26, attribution: 'Esri, Maxar, Earthstar Geographics' });
    baseLayers.current = { osm, satellite };
    graphGroup.current = L.layerGroup().addTo(map);
    flightGroup.current = L.layerGroup().addTo(map);
    previewGroup.current = L.layerGroup().addTo(map);
    map.on('click', (event: LeafletMouseEvent) => mapClickHandler.current(event.latlng.lng, event.latlng.lat));
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; graphGroup.current = null; flightGroup.current = null; previewGroup.current = null; baseLayers.current = null; };
  }, []);

  useEffect(() => {
    const map = mapRef.current, layers = baseLayers.current;
    if (!map || !layers) return;
    Object.values(layers).forEach(layer => { if (map.hasLayer(layer)) map.removeLayer(layer); });
    if (baseLayer !== 'none') layers[baseLayer].addTo(map);
  }, [baseLayer]);

  useEffect(() => {
    const map = mapRef.current, group = graphGroup.current;
    if (!map || !group) return;
    group.clearLayers();
    const edgeFeatures = state.edges.features.filter(feature => feature.properties.aeroway === 'parking_position' ? showParking : showEdges);
    const edges = L.geoJSON({ ...state.edges, features: edgeFeatures } as never, {
      style: feature => {
        const properties = feature?.properties as Record<string, unknown> | undefined;
        const parking = properties?.aeroway === 'parking_position';
        return { color: splitValidation ? String(properties?.validation_color) : parking ? '#dc6b32' : '#9a684d', weight: splitValidation ? 3.4 : parking ? 3.2 : 2.8, opacity: .78 };
      },
      onEachFeature: (feature, layer) => { layer.bindPopup(featurePopup(feature)); layer.on('click', event => { L.DomEvent.stopPropagation(event); featureHandler.current(feature as SelectedFeature); }); if (layer instanceof L.Path) { layer.on('mouseover', () => layer.setStyle({ weight: 5, color: '#243746', opacity: 1 })); layer.on('mouseout', () => edges.resetStyle(layer)); } },
    }).addTo(group);
    const nodes = L.geoJSON({ ...state.nodes, features: showNodes ? state.nodes.features : [] } as never, {
      pointToLayer: (feature, latlng) => {
        const p = feature.properties as Record<string, unknown>;
        return L.circleMarker(latlng, { radius: Math.max(Number(p.radius) || 0, 4), color: '#fff', weight: 1, fillColor: String(p.color || '#416878'), fillOpacity: .95 });
      },
      onEachFeature: (feature, layer) => { layer.bindPopup(featurePopup(feature)); layer.on('click', event => { L.DomEvent.stopPropagation(event); featureHandler.current(feature as SelectedFeature); }); },
    }).addTo(group);
    if (!fitted.current) {
      const bounds = L.featureGroup([edges, nodes]).getBounds();
      if (bounds.isValid()) { map.fitBounds(bounds, { padding: [24, 24] }); fitted.current = true; }
    }
  }, [state, splitValidation, showEdges, showParking, showNodes]);

  useEffect(() => {
    const group = flightGroup.current;
    if (!group) return;
    group.clearLayers();
    [...flights.values()].forEach(entry => {
      const color = colors[entry.slot % colors.length], geometry = entry.geometry;
      if (entry.trajectoryVisible) L.geoJSON(geometry.flight as never, { style: { color, weight: 3, dashArray: '7 6', opacity: .75 }, pointToLayer: (_f, ll) => L.circleMarker(ll, { radius: 3, color, fillColor: '#fff', weight: 2, fillOpacity: 1 }) }).addTo(group);
      if (entry.pathVisible && geometry.path) {
        L.geoJSON(geometry.path as never, { style: { color: '#fff', weight: 9, opacity: .9 } }).addTo(group);
        L.geoJSON(geometry.path as never, { style: { color, weight: 5.5, opacity: .95 } }).addTo(group);
        geometry.path.features.forEach((feature, index) => {
          if (feature.geometry.type !== 'LineString' || (index % Math.max(1, Math.ceil(geometry.path!.features.length / 6)) !== 0 && index !== geometry.path!.features.length - 1)) return;
          const coordinates = feature.geometry.coordinates;
          if (coordinates.length < 2) return;
          const point = coordinates[Math.max(1, Math.floor(coordinates.length / 2))];
          L.marker([point[1], point[0]], { interactive: false, icon: L.divIcon({ className: 'path-direction', html: `<span style="color:${color}">▶</span>`, iconSize: [14, 14] }) }).addTo(group);
        });
      }
      const point = geometry.flight.features.find(feature => feature.geometry.type === 'Point');
      if (point?.geometry.type === 'Point') L.marker([point.geometry.coordinates[1], point.geometry.coordinates[0]], { icon: L.divIcon({ className: 'flight-map-label', html: `<b style="background:${color}">${entry.slot + 1}</b><span>${entry.label.replace(/[&<>"']/g, '')}</span>` }) }).addTo(group);
    });
  }, [flights]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const entries = focusFlightKey && flights.has(focusFlightKey) ? [flights.get(focusFlightKey)!] : [...flights.values()];
    if (!focusFlightKey && fitMapVersion === 0) return;
    const bounds = L.latLngBounds([]);
    entries.forEach(entry => {
      const layer = L.geoJSON(entry.geometry.flight as never);
      const entryBounds = layer.getBounds();
      if (entryBounds.isValid()) bounds.extend(entryBounds);
    });
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [55, 55], maxZoom: focusFlightKey ? 21 : 20 });
  }, [focusFlightKey, fitMapVersion, flights]);

  useEffect(() => {
    const group = previewGroup.current;
    if (!group) return;
    group.clearLayers();
    selected.forEach(feature => L.geoJSON(feature as never, {
      style: { color: '#2563eb', weight: 6, opacity: 1 },
      pointToLayer: (_feature, latlng) => L.circleMarker(latlng, { radius: 8, color: '#2563eb', weight: 3, fillColor: '#fff', fillOpacity: 1 }),
    }).addTo(group));
    if (previewGeometry) L.geoJSON({ type: 'Feature', geometry: previewGeometry, properties: {} } as never, { style: { color: '#db2777', weight: 5, opacity: .9 } }).addTo(group);
    if (drawPoints.length > 1) L.polyline(drawPoints.map(([longitude, latitude]) => [latitude, longitude]), { color: '#2563eb', weight: 4, dashArray: '6 4' }).addTo(group);
    drawPoints.forEach(([longitude, latitude]) => L.circleMarker([latitude, longitude], { radius: 5, color: '#2563eb', fillOpacity: 1 }).addTo(group));
    if (observationLocation) L.circleMarker(observationLocation, { radius: 9, color: '#111827', weight: 3, fillColor: '#facc15', fillOpacity: 1 }).addTo(group);
  }, [selected, drawPoints, previewGeometry, observationLocation]);

  return <div ref={element} id="map" aria-label="机场工作台地图" />;
}
