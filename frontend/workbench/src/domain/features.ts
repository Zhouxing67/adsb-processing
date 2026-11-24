import type { EdgeIdentity, GeoFeature, NodeProperties, PointGeometry, SelectedFeature } from '@/api/types';

export function isNodeFeature(
  feature: SelectedFeature,
): feature is GeoFeature<PointGeometry, NodeProperties> {
  return feature.geometry.type === 'Point';
}

export function formatEdgeId(id: Pick<EdgeIdentity, 'u' | 'v' | 'key'>): string {
  return `${id.u}—${id.v} · ${id.key}`;
}
