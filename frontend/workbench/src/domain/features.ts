import type { EdgeIdentity, GeoFeature, NodeProperties, PointGeometry, SelectedFeature } from '@/api/types';

export function isNodeFeature(
  feature: SelectedFeature,
): feature is GeoFeature<PointGeometry, NodeProperties> {
  return feature.geometry.type === 'Point';
}

export function formatEdgeId(id: Pick<EdgeIdentity, 'u' | 'v' | 'key'>): string {
  return `${id.u}—${id.v} · ${id.key}`;
}

export function isSameEdge(
  left: Pick<EdgeIdentity, 'u' | 'v' | 'key'>,
  right: Pick<EdgeIdentity, 'u' | 'v' | 'key'>,
): boolean {
  return (
    left.key === right.key &&
    ((left.u === right.u && left.v === right.v) || (left.u === right.v && left.v === right.u))
  );
}
