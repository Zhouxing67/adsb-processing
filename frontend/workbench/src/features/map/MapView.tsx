import { useEffect, useRef } from 'react';
import L from 'leaflet';
import type { LeafletMouseEvent, Map as LeafletMap } from 'leaflet';
import type { LineGeometry, MapFlightEntry, SelectedFeature, WorkbenchState } from '../../api/types';
import type { FocusFeatureRequest, FocusFlightRequest } from '../../app/WorkbenchContext';
import { segmentScreenAngleDegrees } from '../../domain/geometry';

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
  focusFlightRequest?: FocusFlightRequest | null;
  focusFeatureRequest?: FocusFeatureRequest | null;
  fitMapVersion?: number;
  observationLocation?: [number, number] | null;
  onFeature(feature: SelectedFeature): void;
  onMapClick(longitude: number, latitude: number): void;
}

export function MapView({ state, flights, splitValidation, baseLayer = 'none', showEdges = true, showParking = true, showNodes = true, selected = [], drawPoints = [], previewGeometry, focusFlightRequest, focusFeatureRequest, fitMapVersion = 0, observationLocation, onFeature, onMapClick }: Props) {
  const element = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const edgesGroup = useRef<L.LayerGroup | null>(null);
  const parkingGroup = useRef<L.LayerGroup | null>(null);
  const nodesGroup = useRef<L.LayerGroup | null>(null);
  const edgesLayerRef = useRef<L.GeoJSON | null>(null);
  const parkingLayerRef = useRef<L.GeoJSON | null>(null);
  const flightGroup = useRef<L.LayerGroup | null>(null);
  const flightLayersRef = useRef<Map<string, { entry: MapFlightEntry; layer: L.LayerGroup }>>(new Map());
  const previewGroup = useRef<L.LayerGroup | null>(null);
  const baseLayers = useRef<Record<'osm' | 'satellite', L.TileLayer> | null>(null);
  const fitted = useRef(false);
  const flightsRef = useRef(flights);
  const splitValidationRef = useRef(splitValidation);
  const featureHandler = useRef(onFeature);
  const mapClickHandler = useRef(onMapClick);
  flightsRef.current = flights;
  splitValidationRef.current = splitValidation;
  featureHandler.current = onFeature;
  mapClickHandler.current = onMapClick;

  const edgeStyle = (feature?: GeoJSON.Feature) => {
    const properties = feature?.properties as Record<string, unknown> | undefined;
    const parking = properties?.aeroway === 'parking_position';
    const validate = splitValidationRef.current;
    return {
      color: validate ? String(properties?.validation_color) : parking ? '#dc6b32' : '#9a684d',
      weight: validate ? 3.4 : parking ? 3.2 : 2.8,
      opacity: .78,
    };
  };

  useEffect(() => {
    if (!element.current) return;
    const map = L.map(element.current, {
      preferCanvas: true,
      renderer: L.canvas({ padding: 0.5 }),
      zoomControl: false,
      maxZoom: 26,
      zoomSnap: .25,
      zoomDelta: .5,
      inertiaDeceleration: 6000,
      inertiaMaxSpeed: 450,
      easeLinearity: .1,
    });
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxNativeZoom: 19, maxZoom: 26, attribution: '© OpenStreetMap contributors' });
    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom: 19, maxZoom: 26, attribution: 'Esri, Maxar, Earthstar Geographics' });
    baseLayers.current = { osm, satellite };
    edgesGroup.current = L.layerGroup();
    parkingGroup.current = L.layerGroup();
    nodesGroup.current = L.layerGroup();
    flightGroup.current = L.layerGroup().addTo(map);
    previewGroup.current = L.layerGroup().addTo(map);
    map.on('click', (event: LeafletMouseEvent) => mapClickHandler.current(event.latlng.lng, event.latlng.lat));
    mapRef.current = map;
    let resizeFrame = 0;
    const resizeObserver = new ResizeObserver(() => {
      window.cancelAnimationFrame(resizeFrame);
      resizeFrame = window.requestAnimationFrame(() => map.invalidateSize({ animate: false, pan: false }));
    });
    resizeObserver.observe(element.current);
    return () => {
      resizeObserver.disconnect();
      window.cancelAnimationFrame(resizeFrame);
      map.remove();
      mapRef.current = null;
      edgesGroup.current = null;
      parkingGroup.current = null;
      nodesGroup.current = null;
      edgesLayerRef.current = null;
      parkingLayerRef.current = null;
      flightLayersRef.current.clear();
      flightGroup.current = null;
      previewGroup.current = null;
      baseLayers.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current, layers = baseLayers.current;
    if (!map || !layers) return;
    Object.values(layers).forEach(layer => { if (map.hasLayer(layer)) map.removeLayer(layer); });
    if (baseLayer !== 'none') layers[baseLayer].addTo(map);
  }, [baseLayer]);

  useEffect(() => {
    const map = mapRef.current;
    const eGroup = edgesGroup.current;
    const pGroup = parkingGroup.current;
    const nGroup = nodesGroup.current;
    if (!map || !eGroup || !pGroup || !nGroup) return;
    eGroup.clearLayers();
    pGroup.clearLayers();
    nGroup.clearLayers();

    const makeEdgeLayer = (features: typeof state.edges.features) => {
      const geo = L.geoJSON({ ...state.edges, features } as never, {
        style: edgeStyle,
        onEachFeature: (feature, layer) => {
          layer.bindPopup(featurePopup(feature));
          layer.on('click', event => {
            L.DomEvent.stopPropagation(event);
            featureHandler.current(feature as SelectedFeature);
          });
          if (layer instanceof L.Path) {
            layer.on('mouseover', () => layer.setStyle({ weight: 5, color: '#243746', opacity: 1 }));
            layer.on('mouseout', () => geo.resetStyle(layer));
          }
        },
      });
      return geo;
    };

    const derivedFeatures = state.edges.features.filter(feature => feature.properties.aeroway !== 'parking_position');
    const parkingFeatures = state.edges.features.filter(feature => feature.properties.aeroway === 'parking_position');
    const derivedLayer = makeEdgeLayer(derivedFeatures).addTo(eGroup);
    const parkingLayer = makeEdgeLayer(parkingFeatures).addTo(pGroup);
    edgesLayerRef.current = derivedLayer;
    parkingLayerRef.current = parkingLayer;

    const nodesLayer = L.geoJSON(state.nodes as never, {
      pointToLayer: (feature, latlng) => {
        const p = feature.properties as Record<string, unknown>;
        if (p.node_type === 'runway_interface') return L.marker(latlng, { icon: L.divIcon({ className: 'business-node-icon runway-interface', html: 'R', iconSize: [20, 20] }) });
        return L.circleMarker(latlng, { radius: Math.max(Number(p.radius) || 0, 4), color: '#fff', weight: 1, fillColor: String(p.color || '#416878'), fillOpacity: .95 });
      },
      onEachFeature: (feature, layer) => {
        layer.bindPopup(featurePopup(feature));
        layer.on('click', event => {
          L.DomEvent.stopPropagation(event);
          featureHandler.current(feature as SelectedFeature);
        });
      },
    }).addTo(nGroup);

    if (!fitted.current) {
      const bounds = L.featureGroup([derivedLayer, parkingLayer, nodesLayer]).getBounds();
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [24, 24] });
        const minimumZoom = Math.floor((map.getZoom() - Math.log2(3)) * 4) / 4;
        map.setMinZoom(minimumZoom);
        fitted.current = true;
      }
    }
  }, [state]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const sync = (group: L.LayerGroup | null, visible: boolean) => {
      if (!group) return;
      if (visible && !map.hasLayer(group)) group.addTo(map);
      else if (!visible && map.hasLayer(group)) map.removeLayer(group);
    };
    sync(edgesGroup.current, showEdges);
    sync(parkingGroup.current, showParking);
    sync(nodesGroup.current, showNodes);
    flightGroup.current?.eachLayer(() => {});
  }, [showEdges, showParking, showNodes]);

  useEffect(() => {
    edgesLayerRef.current?.setStyle(edgeStyle);
    parkingLayerRef.current?.setStyle(edgeStyle);
  }, [splitValidation]);

  useEffect(() => {
    const group = flightGroup.current;
    if (!group) return;
    const rendered = flightLayersRef.current;

    for (const [key, record] of rendered.entries()) {
      if (!flights.has(key)) {
        group.removeLayer(record.layer);
        rendered.delete(key);
      }
    }

    for (const [key, entry] of flights.entries()) {
      const existing = rendered.get(key);
      if (
        existing &&
        existing.entry.geometry === entry.geometry &&
        existing.entry.slot === entry.slot &&
        existing.entry.label === entry.label &&
        existing.entry.trajectoryVisible === entry.trajectoryVisible &&
        existing.entry.pathVisible === entry.pathVisible
      ) {
        continue;
      }
      if (existing) group.removeLayer(existing.layer);

      const subGroup = L.layerGroup();
      const color = colors[entry.slot % colors.length];
      const geometry = entry.geometry;
      if (entry.pathVisible && geometry.path) {
        L.geoJSON(geometry.path as never, { style: { color: '#fff', weight: 9, opacity: .9 } }).addTo(subGroup);
        L.geoJSON(geometry.path as never, { style: { color, weight: 5.5, opacity: .95 } }).addTo(subGroup);
        geometry.path.features.forEach((feature, index) => {
          if (feature.geometry.type !== 'LineString' || (index % Math.max(1, Math.ceil(geometry.path!.features.length / 6)) !== 0 && index !== geometry.path!.features.length - 1)) return;
          const coordinates = feature.geometry.coordinates;
          if (coordinates.length < 2) return;
          const mid = Math.max(1, Math.floor(coordinates.length / 2));
          const prev = coordinates[mid - 1];
          const point = coordinates[mid];
          const angle = segmentScreenAngleDegrees([prev[0], prev[1]], [point[0], point[1]]);
          L.marker([point[1], point[0]], { interactive: false, icon: L.divIcon({ className: 'path-direction', html: `<span style="color:${color};display:inline-block;transform:rotate(${angle.toFixed(1)}deg)">▶</span>`, iconSize: [14, 14] }) }).addTo(subGroup);
        });
      }
      if (entry.trajectoryVisible) {
        L.geoJSON(geometry.flight as never, {
          style: { color, weight: 3, dashArray: '7 6', opacity: .9 },
          pointToLayer: (_f, ll) => L.circleMarker(ll, { radius: 3, color, fillColor: '#fff', weight: 2, fillOpacity: 1 }),
        }).addTo(subGroup);
      }
      const point = geometry.flight.features.find(feature => feature.geometry.type === 'Point');
      if (entry.trajectoryVisible && point?.geometry.type === 'Point') {
        L.marker([point.geometry.coordinates[1], point.geometry.coordinates[0]], {
          icon: L.divIcon({ className: 'flight-map-label', html: `<b style="background:${color}">${entry.slot + 1}</b><span>${escapeHtml(entry.label)}</span>` }),
        }).addTo(subGroup);
      }
      subGroup.addTo(group);
      rendered.set(key, { entry, layer: subGroup });
    }
  }, [flights]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!focusFlightRequest && fitMapVersion === 0) return;
    const currentFlights = flightsRef.current;
    const focusKey = focusFlightRequest?.key;
    const entries = focusKey && currentFlights.has(focusKey) ? [currentFlights.get(focusKey)!] : [...currentFlights.values()];
    const bounds = L.latLngBounds([]);
    entries.forEach(entry => {
      const layer = L.geoJSON(entry.geometry.flight as never);
      const entryBounds = layer.getBounds();
      if (entryBounds.isValid()) bounds.extend(entryBounds);
    });
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [55, 55], maxZoom: focusKey ? 21 : 20 });
  }, [focusFlightRequest, fitMapVersion]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focusFeatureRequest) return;
    const { feature } = focusFeatureRequest;
    if (feature.geometry.type === 'Point') {
      const [lng, lat] = feature.geometry.coordinates;
      map.setView([lat, lng], Math.max(map.getZoom(), 18), { animate: false });
    } else {
      const bounds = L.geoJSON(feature as never).getBounds();
      if (bounds.isValid()) map.fitBounds(bounds, { padding: [80, 80], maxZoom: 20, animate: false });
    }
  }, [focusFeatureRequest]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !observationLocation) return;
    map.setView(observationLocation, Math.max(map.getZoom(), 18), { animate: false });
  }, [observationLocation]);

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
