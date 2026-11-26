import type {
  EdgeIdentity,
  EdgeProperties,
  GeoFeature,
  LineGeometry,
  NodeProperties,
  PointGeometry,
  SelectedFeature,
  StandCluster,
} from '@/api/types';

export function isNodeFeature(
  feature: SelectedFeature,
): feature is GeoFeature<PointGeometry, NodeProperties> {
  return feature.geometry.type === 'Point';
}

export function isParkingEdgeFeature(
  feature: SelectedFeature,
): feature is GeoFeature<LineGeometry, EdgeProperties> {
  return !isNodeFeature(feature) && feature.properties.aeroway === 'parking_position';
}

export function formatEdgeId(id: Pick<EdgeIdentity, 'u' | 'v' | 'key'>): string {
  return `${id.u}—${id.v} · ${id.key}`;
}

export function formatClusterLabel(cluster: Pick<StandCluster, 'c_id' | 'name'>): string {
  return cluster.name ? `#${cluster.c_id} · ${cluster.name}` : `#${cluster.c_id}`;
}

export function formatRouteOd(route: {
  movement: string;
  stand_ref: string;
  runway_ref: string | null;
}): string {
  const rwy = route.runway_ref ?? '无跑道';
  return route.movement === 'departure' ? `${route.stand_ref} → ${rwy}` : `${rwy} → ${route.stand_ref}`;
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
