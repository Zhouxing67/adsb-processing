/** Shared visual palettes and domain labels across workbench views. */

export const FLIGHT_COLORS = [
  '#0072B2',
  '#D55E00',
  '#009E73',
  '#CC79A7',
  '#B77900',
  '#56B4E9',
  '#E69F00',
  '#6A3D9A',
  '#1B9E77',
  '#E7298A',
] as const;

export const ROUTE_COLORS = [
  '#7C3AED',
  '#0D9488',
  '#DB2777',
  '#2563EB',
  '#EA580C',
  '#16A34A',
  '#9333EA',
  '#0284C7',
] as const;

export const MOVEMENT_LABELS: Record<string, string> = {
  arrival: '进港',
  departure: '离港',
  unknown: '未知',
};

export const MATCH_STATUS_LABELS: Record<string, string> = {
  unmatched: '未匹配',
  queued: '排队中',
  matching: '匹配中',
  success: '成功',
  failed: '失败',
};

export const ROUTE_STATUS_LABELS: Record<string, string> = {
  candidate: '待审校',
  verified: '已通过',
  rejected: '已驳回',
  manual: '手动',
};

export const AEROWAY_EDGE_COLORS = {
  taxiway: '#9a684d',
  runway: '#1d5fa7',
  parking_position: '#dc6b32',
  other: '#64748b',
} as const;

export const PAIR_PREVIEW_COLORS = [
  '#1d5fa7',
  '#147a6e',
  '#c86428',
  '#db2777',
  '#0284c7',
  '#16a34a',
] as const;

export const ROUTE_SOURCE_LABELS: Record<string, string> = {
  matched: '匹配导入',
  manual: '人工录入',
};

export const ROUTE_ANOMALY_LABELS: Record<string, string> = {
  repeated_edge: '重复边',
  closed_loop: '闭合环路',
  extreme_detour: '极端绕行',
};

export const STAND_CLUSTER_COLORS = [
  '#147a6e',
  '#c86428',
  '#be185d',
  '#4d7c0f',
  '#b45309',
  '#0e7490',
  '#9f1239',
  '#a16207',
  '#0f766e',
  '#c2410c',
  '#047857',
  '#b91c1c',
] as const;

export const UNCLUSTERED_STAND_COLOR = '#94a3b8';
export const MAP_SELECTION_COLOR = '#1d5fa7';

export function standClusterColor(cId: number): string {
  const index = Math.abs(cId - 1) % STAND_CLUSTER_COLORS.length;
  return STAND_CLUSTER_COLORS[index];
}
