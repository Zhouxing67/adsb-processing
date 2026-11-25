import { useEffect, useRef } from 'react';
import L from 'leaflet';
import type { LeafletMouseEvent, Map as LeafletMap } from 'leaflet';
import type { LineGeometry, MapFlightEntry, MapRouteEntry, SelectedFeature, WorkbenchState } from '../../api/types';
import type { FocusFeatureRequest, FocusFlightRequest } from '../../app/WorkbenchContext';
import { formatEdgeId } from '../../domain/features';
import {
  AEROWAY_EDGE_COLORS,
  FLIGHT_COLORS as colors,
  ROUTE_COLORS as routeColors,
  ROUTE_STATUS_LABELS as routeStatusLabels,
} from '../../domain/palette';
import { addPathDirectionArrows, applySpreadOffset, buildEdgeOccupants, computeSpreadSignature } from './pathOverlay';

export interface MapPreviewLine {
  geometry: LineGeometry;
  color?: string;
  emphasis?: boolean;
  dashed?: boolean;
}
function escapeHtml(value: unknown) { return String(value ?? '—').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]!); }
function featureTooltip(feature: GeoJSON.Feature) {
  const properties = feature.properties ?? {};
  const node = feature.geometry.type === 'Point';
  const identity = node ? properties.id : formatEdgeId(properties.id);
  const details = [properties.aeroway, properties.ref, properties.name].filter(
    value => value !== null && value !== undefined && value !== '',
  );
  const suffix = details.length ? ` · ${details.map(escapeHtml).join(' / ')}` : '';
  return `<strong>${node ? '节点' : '边'} ${escapeHtml(identity)}</strong>${suffix}`;
}
interface Props {
  state: WorkbenchState;
  flights: Map<string, MapFlightEntry>;
  routes?: Map<string, MapRouteEntry>;
  splitValidation: boolean;
  baseLayer?: 'none' | 'osm' | 'satellite';
  showEdges?: boolean;
  showParking?: boolean;
  showNodes?: boolean;
  spreadRoutes?: boolean;
  mapId?: string;
  selected?: SelectedFeature[];
  drawPoints?: Array<[number, number]>;
  previewOverlays?: MapPreviewLine[];
  focusFlightRequest?: FocusFlightRequest | null;
  focusRouteRequest?: FocusFlightRequest | null;
  focusFeatureRequest?: FocusFeatureRequest | null;
  fitMapVersion?: number;
  fitRoutesVersion?: number;
  observationLocation?: [number, number] | null;
  onFeature(feature: SelectedFeature, clickPoint?: [number, number]): void;
  onMapClick(longitude: number, latitude: number): void;
  onFlightClick?(flightKey: string): void;
  onRouteClick?(routeId: string): void;
}

const EMPTY_ROUTES: Map<string, MapRouteEntry> = new Map();
const EMPTY_PREVIEWS: MapPreviewLine[] = [];

export function MapView({ state, flights, routes = EMPTY_ROUTES, splitValidation, baseLayer = 'none', showEdges = true, showParking = true, showNodes = true, spreadRoutes = true, mapId = 'map', selected = [], drawPoints = [], previewOverlays = EMPTY_PREVIEWS, focusFlightRequest, focusRouteRequest, focusFeatureRequest, fitMapVersion = 0, fitRoutesVersion = 0, observationLocation, onFeature, onMapClick, onFlightClick, onRouteClick }: Props) {
  const element = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const nodesRendererRef = useRef<L.Renderer | null>(null);
  const previewRendererRef = useRef<L.Renderer | null>(null);
  const initialBoundsRef = useRef<L.LatLngBounds | null>(null);
  const edgesGroup = useRef<L.LayerGroup | null>(null);
  const parkingGroup = useRef<L.LayerGroup | null>(null);
  const nodesGroup = useRef<L.LayerGroup | null>(null);
  const edgesLayerRef = useRef<L.GeoJSON | null>(null);
  const parkingLayerRef = useRef<L.GeoJSON | null>(null);
  const flightGroup = useRef<L.LayerGroup | null>(null);
  const flightLayersRef = useRef<Map<string, { entry: MapFlightEntry; spreadSig: string; layer: L.LayerGroup }>>(new Map());
  const routeGroup = useRef<L.LayerGroup | null>(null);
  const routeLayersRef = useRef<Map<string, { entry: MapRouteEntry; spreadSig: string; layer: L.LayerGroup }>>(new Map());
  const previewGroup = useRef<L.LayerGroup | null>(null);
  const baseLayers = useRef<Record<'osm' | 'satellite', L.TileLayer> | null>(null);
  const fitted = useRef(false);
  const flightsRef = useRef(flights);
  const routesRef = useRef(routes);
  const splitValidationRef = useRef(splitValidation);
  const featureHandler = useRef(onFeature);
  const mapClickHandler = useRef(onMapClick);
  const flightClickHandler = useRef(onFlightClick);
  const routeClickHandler = useRef(onRouteClick);
  flightsRef.current = flights;
  routesRef.current = routes;
  splitValidationRef.current = splitValidation;
  featureHandler.current = onFeature;
  mapClickHandler.current = onMapClick;
  flightClickHandler.current = onFlightClick;
  routeClickHandler.current = onRouteClick;

  const hasOverlay = flights.size > 0 || routes.size > 0;
  const hasOverlayRef = useRef(hasOverlay);
  hasOverlayRef.current = hasOverlay;

  const edgeStyle = (feature?: GeoJSON.Feature) => {
    const properties = feature?.properties as Record<string, unknown> | undefined;
    const aeroway = properties?.aeroway;
    const parking = aeroway === 'parking_position';
    const runway = aeroway === 'runway';
    const taxiway = aeroway === 'taxiway';
    const validate = splitValidationRef.current;
    const dimmed = !validate && hasOverlayRef.current;
    const baseColor = parking
      ? AEROWAY_EDGE_COLORS.parking_position
      : runway
        ? AEROWAY_EDGE_COLORS.runway
        : taxiway
          ? AEROWAY_EDGE_COLORS.taxiway
          : AEROWAY_EDGE_COLORS.other;
    return {
      color: validate ? String(properties?.validation_color) : baseColor,
      weight: validate ? 3.4 : dimmed ? (parking ? 2.2 : 1.9) : runway ? 4.2 : parking ? 3.2 : 2.8,
      opacity: dimmed ? 0.34 : 0.82,
    };
  };

  useEffect(() => {
    if (!element.current) return;
    const map = L.map(element.current, {
      preferCanvas: true,
      renderer: L.canvas({ padding: 0.5 }),
      zoomControl: false,
      minZoom: 3,
      maxZoom: 26,
      zoomSnap: .25,
      zoomDelta: .5,
      inertiaDeceleration: 6000,
      inertiaMaxSpeed: 450,
      easeLinearity: .1,
    });
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    const nodesPane = map.createPane('nodesPane');
    nodesPane.style.zIndex = '620';
    nodesPane.style.pointerEvents = 'none';
    const previewPane = map.createPane('previewPane');
    previewPane.style.zIndex = '630';
    previewPane.style.pointerEvents = 'none';
    nodesRendererRef.current = L.svg({ padding: 0.5, pane: 'nodesPane' });
    previewRendererRef.current = L.svg({ padding: 0.5, pane: 'previewPane' });
    const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxNativeZoom: 19, maxZoom: 26, attribution: '© OpenStreetMap contributors' });
    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom: 19, maxZoom: 26, attribution: 'Esri, Maxar, Earthstar Geographics' });
    baseLayers.current = { osm, satellite };
    edgesGroup.current = L.layerGroup();
    parkingGroup.current = L.layerGroup();
    nodesGroup.current = L.layerGroup();
    flightGroup.current = L.layerGroup().addTo(map);
    routeGroup.current = L.layerGroup().addTo(map);
    previewGroup.current = L.layerGroup().addTo(map);
    map.on('click', (event: LeafletMouseEvent) => mapClickHandler.current(event.latlng.lng, event.latlng.lat));
    mapRef.current = map;
    let resizeFrame = 0;
    const resizeObserver = new ResizeObserver(() => {
      window.cancelAnimationFrame(resizeFrame);
      resizeFrame = window.requestAnimationFrame(() => {
        map.invalidateSize({ animate: false, pan: false });
        if (
          !fitted.current &&
          initialBoundsRef.current?.isValid() &&
          element.current &&
          element.current.clientWidth > 0 &&
          element.current.clientHeight > 0
        ) {
          map.fitBounds(initialBoundsRef.current, { padding: [24, 24] });
          fitted.current = true;
        }
      });
    });
    resizeObserver.observe(element.current);
    return () => {
      resizeObserver.disconnect();
      window.cancelAnimationFrame(resizeFrame);
      map.remove();
      mapRef.current = null;
      nodesRendererRef.current = null;
      previewRendererRef.current = null;
      initialBoundsRef.current = null;
      fitted.current = false;
      edgesGroup.current = null;
      parkingGroup.current = null;
      nodesGroup.current = null;
      edgesLayerRef.current = null;
      parkingLayerRef.current = null;
      flightLayersRef.current.clear();
      flightGroup.current = null;
      routeLayersRef.current.clear();
      routeGroup.current = null;
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
          layer.bindTooltip(featureTooltip(feature), { sticky: true, direction: 'top', offset: [0, -8] });
          layer.on('click', event => {
            L.DomEvent.stopPropagation(event);
            featureHandler.current(feature as SelectedFeature, [event.latlng.lng, event.latlng.lat]);
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
        if (p.node_type === 'runway_interface') {
          return L.marker(latlng, {
            pane: 'nodesPane',
            icon: L.divIcon({ className: 'business-node-icon runway-interface', html: 'R', iconSize: [16, 16] }),
          });
        }
        return L.circleMarker(latlng, {
          pane: 'nodesPane',
          renderer: nodesRendererRef.current ?? undefined,
          radius: Math.max(Number(p.radius) || 0, 3.2),
          color: '#fff',
          weight: 1,
          fillColor: String(p.color || '#416878'),
          fillOpacity: 0.85,
        });
      },
      onEachFeature: (feature, layer) => {
        layer.bindTooltip(featureTooltip(feature), { direction: 'top', offset: [0, -8] });
        layer.on('click', event => {
          L.DomEvent.stopPropagation(event);
          featureHandler.current(feature as SelectedFeature);
        });
      },
    }).addTo(nGroup);

    const bounds = L.featureGroup([derivedLayer, parkingLayer, nodesLayer]).getBounds();
    initialBoundsRef.current = bounds.isValid() ? bounds : null;
    if (!fitted.current && bounds.isValid() && element.current && element.current.clientWidth > 0 && element.current.clientHeight > 0) {
      map.invalidateSize({ animate: false, pan: false });
      map.fitBounds(bounds, { padding: [24, 24] });
      fitted.current = true;
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
  }, [splitValidation, hasOverlay]);

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

    const edgeOccupants = spreadRoutes
      ? buildEdgeOccupants(
          [...flights.entries()]
            .filter(([, entry]) => entry.pathVisible && Boolean(entry.geometry.path))
            .sort((a, b) => a[1].slot - b[1].slot)
            .map(([id, entry]) => ({ id, path: entry.geometry.path! })),
        )
      : new Map<string, string[]>();

    for (const [key, entry] of flights.entries()) {
      const spreadSig = entry.pathVisible
        ? computeSpreadSignature(key, entry.geometry.path, edgeOccupants, spreadRoutes)
        : 'hidden';
      const existing = rendered.get(key);
      if (
        existing &&
        existing.spreadSig === spreadSig &&
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
      const interactiveLayers: Array<L.GeoJSON> = [];
      const handleFlightClick = (event: LeafletMouseEvent) => {
        L.DomEvent.stopPropagation(event);
        interactiveLayers.forEach(layer => layer.bringToFront());
        flightClickHandler.current?.(key);
      };
      if (entry.pathVisible && geometry.path) {
        const displayPath = applySpreadOffset(geometry.path, key, edgeOccupants, spreadRoutes);
        const halo = L.geoJSON(displayPath as never, { style: { color: '#fff', weight: 8.5, opacity: .9 }, interactive: false }).addTo(subGroup);
        const pathLayer = L.geoJSON(displayPath as never, {
          style: { color, weight: 5, opacity: .95 },
          onEachFeature: (_feature, layer) => {
            layer.on('click', handleFlightClick);
          },
        }).addTo(subGroup);
        interactiveLayers.push(halo, pathLayer);
        addPathDirectionArrows(displayPath, color, subGroup);
      }
      if (entry.trajectoryVisible) {
        const trajLayer = L.geoJSON(geometry.flight as never, {
          style: { color, weight: 3, dashArray: '7 6', opacity: .9 },
          pointToLayer: (_f, ll) => L.circleMarker(ll, { radius: 4, color, fillColor: '#fff', weight: 2, fillOpacity: 1 }),
          onEachFeature: (_feature, layer) => {
            layer.on('click', handleFlightClick);
          },
        }).addTo(subGroup);
        interactiveLayers.push(trajLayer);
      }
      const point = geometry.flight.features.find(feature => feature.geometry.type === 'Point');
      if (entry.trajectoryVisible && point?.geometry.type === 'Point') {
        const marker = L.marker([point.geometry.coordinates[1], point.geometry.coordinates[0]], {
          icon: L.divIcon({
            className: 'flight-map-label',
            html: `<b style="background:${color}">${entry.slot + 1}</b>`,
            iconSize: [20, 20],
            iconAnchor: [10, 10],
          }),
        });
        marker.bindTooltip(escapeHtml(entry.label), { direction: 'top', offset: [0, -10] });
        marker.on('click', handleFlightClick);
        marker.addTo(subGroup);
      }
      subGroup.addTo(group);
      rendered.set(key, { entry, spreadSig, layer: subGroup });
    }
  }, [flights, spreadRoutes]);

  useEffect(() => {
    const group = routeGroup.current;
    if (!group) return;
    const rendered = routeLayersRef.current;

    for (const [routeId, record] of rendered.entries()) {
      if (!routes.has(routeId)) {
        group.removeLayer(record.layer);
        rendered.delete(routeId);
      }
    }

    const edgeOccupants = spreadRoutes
      ? buildEdgeOccupants(
          [...routes.entries()]
            .filter(([, entry]) => entry.visible)
            .sort((a, b) => a[1].slot - b[1].slot)
            .map(([id, entry]) => ({ id, path: entry.geometry.path })),
        )
      : new Map<string, string[]>();

    for (const [routeId, entry] of routes.entries()) {
      const spreadSig = entry.visible
        ? computeSpreadSignature(routeId, entry.geometry.path, edgeOccupants, spreadRoutes)
        : 'hidden';
      const existing = rendered.get(routeId);
      if (
        existing &&
        existing.spreadSig === spreadSig &&
        existing.entry.geometry === entry.geometry &&
        existing.entry.slot === entry.slot &&
        existing.entry.label === entry.label &&
        existing.entry.visible === entry.visible
      ) {
        continue;
      }
      if (existing) group.removeLayer(existing.layer);

      const subGroup = L.layerGroup();
      if (entry.visible) {
        const color = routeColors[entry.slot % routeColors.length];
        const route = entry.geometry.route;
        const rejected = route.status === 'rejected';
        const verified = route.status === 'verified' || route.status === 'manual';
        const displayPath = applySpreadOffset(entry.geometry.path, routeId, edgeOccupants, spreadRoutes);

        const interactiveLayers: Array<L.GeoJSON> = [];
        const handleRouteClick = (event: LeafletMouseEvent) => {
          L.DomEvent.stopPropagation(event);
          interactiveLayers.forEach(layer => layer.bringToFront());
          routeClickHandler.current?.(routeId);
        };
        const tooltip = `<strong>${escapeHtml(entry.label)}</strong> · ${Math.round(route.total_length_m)} m · ${route.edge_count} 边 · ${escapeHtml(routeStatusLabels[route.status] ?? route.status)}`;

        const halo = L.geoJSON(displayPath as never, {
          style: { color: '#fff', weight: verified ? 9 : 7.5, opacity: rejected ? 0.5 : 0.88 },
          interactive: false,
        }).addTo(subGroup);
        const pathLayer = L.geoJSON(displayPath as never, {
          style: {
            color,
            weight: verified ? 5.5 : rejected ? 3.5 : 4.5,
            opacity: rejected ? 0.65 : 0.95,
            dashArray: rejected ? '8 6' : undefined,
          },
          onEachFeature: (_feature, layer) => {
            layer.bindTooltip(tooltip, { sticky: true, direction: 'top', offset: [0, -8] });
            layer.on('click', handleRouteClick);
          },
        }).addTo(subGroup);
        interactiveLayers.push(halo, pathLayer);
        addPathDirectionArrows(displayPath, color, subGroup);
      }
      subGroup.addTo(group);
      rendered.set(routeId, { entry, spreadSig, layer: subGroup });
    }
  }, [routes, spreadRoutes]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!focusRouteRequest && fitRoutesVersion === 0) return;
    const currentRoutes = routesRef.current;
    const focusId = focusRouteRequest?.key;
    const entries = focusId && currentRoutes.has(focusId) ? [currentRoutes.get(focusId)!] : [...currentRoutes.values()];
    const bounds = L.latLngBounds([]);
    entries.forEach(entry => {
      const layer = L.geoJSON(entry.geometry.path as never);
      const entryBounds = layer.getBounds();
      if (entryBounds.isValid()) bounds.extend(entryBounds);
    });
    if (bounds.isValid()) {
      map.invalidateSize({ animate: false, pan: false });
      map.fitBounds(bounds, { padding: [55, 55], maxZoom: focusId ? 20 : 19 });
    }
  }, [focusRouteRequest, fitRoutesVersion]);

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
    if (bounds.isValid()) {
      map.invalidateSize({ animate: false, pan: false });
      map.fitBounds(bounds, { padding: [55, 55], maxZoom: focusKey ? 21 : 20 });
    }
  }, [focusFlightRequest, fitMapVersion]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focusFeatureRequest) return;
    map.invalidateSize({ animate: false, pan: false });
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
    map.invalidateSize({ animate: false, pan: false });
    map.setView(observationLocation, Math.max(map.getZoom(), 18), { animate: false });
  }, [observationLocation]);

  useEffect(() => {
    const group = previewGroup.current;
    if (!group) return;
    group.clearLayers();
    const pane = 'previewPane';
    const renderer = previewRendererRef.current ?? undefined;

    // Highlight all edges incident to selected node(s) in contrasting teal before drawing the node marker on top.
    const selectedNodeIds = new Set(
      selected
        .filter(feature => feature.geometry.type === 'Point')
        .map(feature => String(feature.properties.id)),
    );
    if (selectedNodeIds.size > 0) {
      const incidentEdges = state.edges.features.filter(
        edge => selectedNodeIds.has(String(edge.properties.u)) || selectedNodeIds.has(String(edge.properties.v)),
      );
      if (incidentEdges.length > 0) {
        L.geoJSON({ ...state.edges, features: incidentEdges } as never, {
          style: { color: '#147a6e', weight: 5, opacity: 0.92, pane, renderer },
          interactive: false,
        }).addTo(group);
      }
    }

    selected.forEach(feature => L.geoJSON(feature as never, {
      style: { color: '#1d5fa7', weight: 6, opacity: 1, pane, renderer },
      interactive: false,
      pointToLayer: (_feature, latlng) => L.circleMarker(latlng, { pane, renderer, interactive: false, radius: 8, color: '#1d5fa7', weight: 3, fillColor: '#fff', fillOpacity: 1 }),
    }).addTo(group));
    const orderedPreviews = [...previewOverlays].sort(
      (left, right) => Number(Boolean(left.emphasis)) - Number(Boolean(right.emphasis)),
    );
    orderedPreviews.forEach(item => {
      const color = item.color ?? '#db2777';
      const weight = item.emphasis ? 7 : 5;
      L.geoJSON({ type: 'Feature', geometry: item.geometry, properties: {} } as never, {
        style: { color: '#fff', weight: weight + 3.5, opacity: item.dashed ? 0.65 : 0.9, pane, renderer },
        interactive: false,
      }).addTo(group);
      L.geoJSON({ type: 'Feature', geometry: item.geometry, properties: {} } as never, {
        style: {
          color,
          weight,
          opacity: item.emphasis ? 1 : 0.92,
          dashArray: item.dashed ? '8 6' : undefined,
          pane,
          renderer,
        },
        interactive: false,
      }).addTo(group);
    });
    if (drawPoints.length > 1) L.polyline(drawPoints.map(([longitude, latitude]) => [latitude, longitude]), { color: '#1d5fa7', weight: 4, dashArray: '6 4', pane, renderer, interactive: false }).addTo(group);
    drawPoints.forEach(([longitude, latitude]) => L.circleMarker([latitude, longitude], { pane, renderer, interactive: false, radius: 5, color: '#1d5fa7', fillOpacity: 1 }).addTo(group));
    if (observationLocation) L.circleMarker(observationLocation, { pane, renderer, interactive: false, radius: 9, color: '#111827', weight: 3, fillColor: '#facc15', fillOpacity: 1 }).addTo(group);
  }, [selected, drawPoints, previewOverlays, observationLocation, state]);

  return <div ref={element} id={mapId} className="h-full w-full" aria-label="机场工作台地图" />;
}
