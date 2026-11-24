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

export const ROUTE_SOURCE_LABELS: Record<string, string> = {
  matched: '匹配导入',
  manual: '人工录入',
};
