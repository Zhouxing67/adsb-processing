import type { FlightCatalogue, FlightDetail, FlightGeometry, MatchStatus, WorkbenchState } from './types';

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) { super(message); }
}
function detailMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message);
  return '请求失败';
}
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (response.status === 204) return undefined as T;
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
  if (!response.ok) throw new ApiError(detailMessage(payload?.detail), response.status, payload?.detail);
  return payload as T;
}
function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}
export const api = {
  state: (signal?: AbortSignal) => request<WorkbenchState>('/api/state', { signal }),
  catalogue: (params: URLSearchParams, signal?: AbortSignal) => request<FlightCatalogue>(`/api/flights?${params}`, { signal }),
  filteredFlights: (params: URLSearchParams) => request<{ flight_keys: string[]; count: number }>(`/api/flight-selection?${params}`),
  geometry: (key: string) => request<FlightGeometry>(`/api/flights/${encodeURIComponent(key)}/geometry`),
  detail: (key: string, page = 1, allFields = false) => request<FlightDetail>(`/api/flights/${encodeURIComponent(key)}?observation_page=${page}&observation_page_size=100&all_fields=${allFields}`),
  updateStand: (key: string, stand_position: string | null) => request<void>(`/api/flights/${encodeURIComponent(key)}/stand`, json('PATCH', { stand_position })),
  submitMatches: (flight_keys: string[], force = false) => request<{ task_id: string; queued_count: number }>('/api/matches', json('POST', { flight_keys, force })),
  matchStatus: () => request<MatchStatus>('/api/matches'),
  mergeCandidates: <T>() => request<T>('/api/merge-candidates'),
  graphCommand: <T>(path: string, body: unknown) => request<T>(path, json('POST', body)),
};
