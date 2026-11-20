import { useEffect, useRef } from 'react';
import L from 'leaflet';
import type { LeafletMouseEvent, Map as LeafletMap } from 'leaflet';
import type { FlightGeometry, SelectedFeature, WorkbenchState } from '../../api/types';

const colors = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#B77900', '#56B4E9', '#E69F00', '#6A3D9A', '#1B9E77', '#E7298A'];
interface Props {
  state: WorkbenchState;
  flights: Map<string, FlightGeometry>;
  splitValidation: boolean;
  onFeature(feature: SelectedFeature): void;
  onMapClick(longitude: number, latitude: number): void;
}

export function MapView({ state, flights, splitValidation, onFeature, onMapClick }: Props) {
  const element = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const graphGroup = useRef<L.LayerGroup | null>(null);
  const flightGroup = useRef<L.LayerGroup | null>(null);
  const fitted = useRef(false);
  const featureHandler = useRef(onFeature);
  const mapClickHandler = useRef(onMapClick);
  featureHandler.current = onFeature;
  mapClickHandler.current = onMapClick;

  useEffect(() => {
    if (!element.current) return;
    const map = L.map(element.current, { preferCanvas: true, zoomControl: false, maxZoom: 26 });
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    const blank = L.layerGroup().addTo(map);
    const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxNativeZoom: 19, maxZoom: 26, attribution: '© OpenStreetMap contributors' });
    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom: 19, maxZoom: 26, attribution: 'Esri, Maxar, Earthstar Geographics' });
    L.control.layers({ '无底图': blank, 'OpenStreetMap': osm, 'ESRI 卫星': satellite }, {}, { position: 'topleft' }).addTo(map);
    graphGroup.current = L.layerGroup().addTo(map);
    flightGroup.current = L.layerGroup().addTo(map);
    map.on('click', (event: LeafletMouseEvent) => mapClickHandler.current(event.latlng.lng, event.latlng.lat));
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; graphGroup.current = null; flightGroup.current = null; };
  }, []);

  useEffect(() => {
    const map = mapRef.current, group = graphGroup.current;
    if (!map || !group) return;
    group.clearLayers();
    const edges = L.geoJSON(state.edges as never, {
      style: feature => {
        const properties = feature?.properties as Record<string, unknown> | undefined;
        const parking = properties?.aeroway === 'parking_position';
        return { color: splitValidation ? String(properties?.validation_color) : parking ? '#dc6b32' : '#526477', weight: parking ? 5 : 3, opacity: .9 };
      },
      onEachFeature: (feature, layer) => layer.on('click', event => { L.DomEvent.stopPropagation(event); featureHandler.current(feature as SelectedFeature); }),
    }).addTo(group);
    const nodes = L.geoJSON(state.nodes as never, {
      pointToLayer: (feature, latlng) => {
        const p = feature.properties as Record<string, unknown>;
        return L.circleMarker(latlng, { radius: Math.max(Number(p.radius) || 0, 4), color: '#fff', weight: 1, fillColor: String(p.color || '#416878'), fillOpacity: .95 });
      },
      onEachFeature: (feature, layer) => layer.on('click', event => { L.DomEvent.stopPropagation(event); featureHandler.current(feature as SelectedFeature); }),
    }).addTo(group);
    if (!fitted.current) {
      const bounds = L.featureGroup([edges, nodes]).getBounds();
      if (bounds.isValid()) { map.fitBounds(bounds, { padding: [24, 24] }); fitted.current = true; }
    }
  }, [state, splitValidation]);

  useEffect(() => {
    const group = flightGroup.current;
    if (!group) return;
    group.clearLayers();
    [...flights.values()].forEach((geometry, index) => {
      const color = colors[index % colors.length];
      L.geoJSON(geometry.flight as never, { style: { color, weight: 3, dashArray: '7 6', opacity: .75 }, pointToLayer: (_f, ll) => L.circleMarker(ll, { radius: 3, color, fillOpacity: 1 }) }).addTo(group);
      if (geometry.path) L.geoJSON(geometry.path as never, { style: { color, weight: 6, opacity: .95 } }).addTo(group);
    });
  }, [flights]);

  return <div ref={element} id="map" aria-label="机场工作台地图" />;
}
