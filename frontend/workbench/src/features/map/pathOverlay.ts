import L from 'leaflet';
import {
  canonicalSegmentKey,
  offsetSegmentWithPinnedEndpoints,
  segmentScreenAngleDegrees,
} from '@/domain/geometry';

export interface PathFeatureLike {
  geometry: {
    type: string;
    coordinates: unknown;
  };
}

export interface PathCollectionLike<F extends PathFeatureLike = PathFeatureLike> {
  features: F[];
}

export function buildEdgeOccupants(
  items: Array<{ id: string; path: PathCollectionLike }>,
): Map<string, string[]> {
  const edgeOccupants = new Map<string, string[]>();
  for (const { id, path } of items) {
    const seen = new Set<string>();
    for (const feature of path.features) {
      if (feature.geometry.type !== 'LineString') continue;
      const { key } = canonicalSegmentKey(feature.geometry.coordinates as Array<[number, number]>);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      const list = edgeOccupants.get(key) ?? [];
      list.push(id);
      edgeOccupants.set(key, list);
    }
  }
  return edgeOccupants;
}

export function computeSpreadSignature(
  id: string,
  path: PathCollectionLike | null | undefined,
  edgeOccupants: Map<string, string[]>,
  spreadRoutes: boolean,
): string {
  if (!spreadRoutes || !path) return 'off';
  const parts: string[] = [];
  for (const feature of path.features) {
    if (feature.geometry.type !== 'LineString') continue;
    const { key } = canonicalSegmentKey(feature.geometry.coordinates as Array<[number, number]>);
    if (!key) continue;
    const occupants = edgeOccupants.get(key);
    if (!occupants || occupants.length <= 1) continue;
    const slotIndex = occupants.indexOf(id);
    if (slotIndex >= 0) parts.push(`${key}:${slotIndex}/${occupants.length}`);
  }
  return parts.join('|');
}

export function applySpreadOffset<C extends PathCollectionLike>(
  rawPath: C,
  id: string,
  edgeOccupants: Map<string, string[]>,
  spreadRoutes: boolean,
): C {
  if (!spreadRoutes) return rawPath;
  return {
    ...rawPath,
    features: rawPath.features.map(feature => {
      if (feature.geometry.type !== 'LineString') return feature;
      const coords = feature.geometry.coordinates as Array<[number, number]>;
      const { key: edgeKey, reversed } = canonicalSegmentKey(coords);
      const occupants = edgeOccupants.get(edgeKey);
      if (!occupants || occupants.length <= 1) return feature;
      const slotIndex = occupants.indexOf(id);
      if (slotIndex < 0) return feature;
      const offsetMeters = (slotIndex - (occupants.length - 1) / 2) * 5.5;
      return {
        ...feature,
        geometry: {
          ...feature.geometry,
          coordinates: offsetSegmentWithPinnedEndpoints(coords, offsetMeters, reversed),
        },
      };
    }),
  };
}

export function addPathDirectionArrows(
  displayPath: PathCollectionLike,
  color: string,
  targetGroup: L.LayerGroup,
): void {
  const total = displayPath.features.length;
  const stride = Math.max(1, Math.ceil(total / 6));
  displayPath.features.forEach((feature, index) => {
    if (feature.geometry.type !== 'LineString' || (index % stride !== 0 && index !== total - 1)) {
      return;
    }
    const coordinates = feature.geometry.coordinates as Array<[number, number]>;
    if (coordinates.length < 2) return;
    const mid = Math.max(1, Math.floor(coordinates.length / 2));
    const prev = coordinates[mid - 1];
    const point = coordinates[mid];
    const angle = segmentScreenAngleDegrees([prev[0], prev[1]], [point[0], point[1]]);
    L.marker([point[1], point[0]], {
      interactive: false,
      icon: L.divIcon({
        className: 'path-direction',
        html: `<span style="color:${color};display:inline-block;transform:rotate(${angle.toFixed(1)}deg)">▶</span>`,
        iconSize: [14, 14],
      }),
    }).addTo(targetGroup);
  });
}

export interface StyledPathOverlayOptions {
  color: string;
  weight?: number;
  opacity?: number;
  dashArray?: string;
  haloWeight?: number;
  haloOpacity?: number;
  tooltip?: string;
  onClick(event: L.LeafletMouseEvent): void;
}

export function addStyledPathOverlay(
  displayPath: PathCollectionLike,
  options: StyledPathOverlayOptions,
  targetGroup: L.LayerGroup,
): L.GeoJSON[] {
  const halo = L.geoJSON(displayPath as never, {
    style: {
      color: '#fff',
      weight: options.haloWeight ?? 8.5,
      opacity: options.haloOpacity ?? 0.9,
    },
    interactive: false,
  }).addTo(targetGroup);
  const pathLayer = L.geoJSON(displayPath as never, {
    style: {
      color: options.color,
      weight: options.weight ?? 5,
      opacity: options.opacity ?? 0.95,
      dashArray: options.dashArray,
    },
    onEachFeature: (_feature, layer) => {
      if (options.tooltip) {
        layer.bindTooltip(options.tooltip, { sticky: true, direction: 'top', offset: [0, -8] });
      }
      layer.on('click', options.onClick);
    },
  }).addTo(targetGroup);
  addPathDirectionArrows(displayPath, options.color, targetGroup);
  return [halo, pathLayer];
}

export function fitGeoJsonEntries<T>(
  map: L.Map,
  entries: Map<string, T>,
  focusKey: string | undefined,
  getGeoJson: (entry: T) => unknown,
  maxZoom: { single: number; all: number },
): void {
  const selected = focusKey && entries.has(focusKey) ? [entries.get(focusKey)!] : [...entries.values()];
  const bounds = L.latLngBounds([]);
  selected.forEach(entry => {
    const entryBounds = L.geoJSON(getGeoJson(entry) as never).getBounds();
    if (entryBounds.isValid()) bounds.extend(entryBounds);
  });
  if (bounds.isValid()) {
    map.invalidateSize({ animate: false, pan: false });
    map.fitBounds(bounds, { padding: [55, 55], maxZoom: focusKey ? maxZoom.single : maxZoom.all });
  }
}
