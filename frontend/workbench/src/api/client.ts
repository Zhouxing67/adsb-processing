import type { FlightCatalogue, FlightDetail, FlightGeometry, ImportRoutesRequest, ImportRoutesSummary, MatchIssueList, MatchIssueMutation, MatchStatus, RouteGeometry, RouteItem, RouteList, RouteReviewUpdate, WorkbenchState } from './types';
import type { components as GraphApi } from './generated/graph';
import type { paths as GraphPaths } from './generated/graph';
import type { components as FlightApi } from './generated/flight';
import type { operations as FlightOperations } from './generated/flight';

export type ApiErrorDetail = GraphApi['schemas']['ErrorDetail'];
type PostOperation<P extends keyof GraphPaths> = GraphPaths[P] extends { post: infer Operation } ? Operation : never;
export type GraphPostPath = {
  [P in keyof GraphPaths]: PostOperation<P> extends never ? never : P;
}[keyof GraphPaths];
export type GraphPostRequest<P extends GraphPostPath> = PostOperation<P> extends {
  requestBody: { content: { 'application/json': infer Body } };
} ? Body : never;
export type GraphPostResponse<P extends GraphPostPath> = PostOperation<P> extends {
  responses: { 200: { content: { 'application/json': infer Body } } };
} ? Body : never;
export type GraphPostInput<P extends GraphPostPath> = Omit<GraphPostRequest<P>, 'expected_revision'> & {
  expected_revision?: number;
};
export type FlightSelectionQuery = NonNullable<FlightOperations['flight_selection_api_flight_selection_get']['parameters']['query']>;
export type FlightCatalogueQuery = NonNullable<FlightOperations['flights_catalogue_api_flights_get']['parameters']['query']>;
export type RouteListQuery = NonNullable<FlightOperations['routes_list_api_routes_get']['parameters']['query']>;
export type MatchStatusQuery = NonNullable<FlightOperations['match_status_api_matches_get']['parameters']['query']>;

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: ApiErrorDetail) { super(message); }
}
function errorDetail(value: unknown): ApiErrorDetail | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const detail = value as Record<string, unknown>;
  if (typeof detail.code !== 'string' || typeof detail.message !== 'string' || !detail.context || typeof detail.context !== 'object') return undefined;
  return detail as ApiErrorDetail;
}
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (response.status === 204) return undefined as T;
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
  if (!response.ok) {
    const detail = errorDetail(payload?.detail);
    throw new ApiError(detail?.message ?? '请求失败', response.status, detail);
  }
  return payload as T;
}
function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}
function queryString(params: FlightCatalogueQuery | FlightSelectionQuery | RouteListQuery | MatchStatusQuery): string {
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) value.forEach(item => query.append(name, String(item)));
    else query.set(name, String(value));
  }
  return query.toString();
}
export const api = {
  state: (signal?: AbortSignal) => request<WorkbenchState>('/api/state', { signal }),
  catalogue: (params: FlightCatalogueQuery, signal?: AbortSignal) => request<FlightCatalogue>(`/api/flights?${queryString(params)}`, { signal }),
  filteredFlights: (params: FlightSelectionQuery) => request<FlightApi['schemas']['FlightSelectionResponse']>(`/api/flight-selection?${queryString(params)}`),
  geometry: (key: string, signal?: AbortSignal) => request<FlightGeometry>(`/api/flights/${encodeURIComponent(key)}/geometry`, { signal }),
  detail: (key: string, page = 1, allFields = false) => request<FlightDetail>(`/api/flights/${encodeURIComponent(key)}?observation_page=${page}&observation_page_size=100&all_fields=${allFields}`),
  updateStand: (key: string, stand_position: string | null) => request<void>(`/api/flights/${encodeURIComponent(key)}/stand`, json('PATCH', { stand_position })),
  recommendStands: (key: string, signal: AbortSignal) =>
    request<FlightApi['schemas']['StandRecommendations']>(`/api/flights/${encodeURIComponent(key)}/stand-recommendations`, { signal }),
  submitMatches: (flight_keys: string[], force = false) => request<FlightApi['schemas']['MatchSubmissionResponse']>('/api/matches', json('POST', { flight_keys, force })),
  matchStatus: (params?: MatchStatusQuery) => {
    const qs = params ? queryString(params) : '';
    return request<MatchStatus>(qs ? `/api/matches?${qs}` : '/api/matches');
  },
  routes: (params: RouteListQuery, signal?: AbortSignal) => request<RouteList>(`/api/routes?${queryString(params)}`, { signal }),
  routeGeometry: (routeId: string, signal?: AbortSignal) => request<RouteGeometry>(`/api/routes/${encodeURIComponent(routeId)}/geometry`, { signal }),
  updateRouteReview: (routeId: string, body: RouteReviewUpdate) => request<RouteItem>(`/api/routes/${encodeURIComponent(routeId)}`, json('PATCH', body)),
  importMatchedRoutes: (body: ImportRoutesRequest = { replace_candidates: false }) => request<ImportRoutesSummary>('/api/routes/import-matches', json('POST', body)),
  matchIssues: (signal?: AbortSignal) => request<MatchIssueList>('/api/match-issues', { signal }),
  addMatchIssues: (flight_keys: string[], reason?: string | null) => request<MatchIssueMutation>('/api/match-issues', json('POST', { flight_keys, reason: reason ?? null })),
  removeMatchIssues: (flight_keys: string[]) => request<MatchIssueMutation>('/api/match-issues/remove', json('POST', { flight_keys })),
  mergeCandidates: () => request<GraphApi['schemas']['MergeCandidatesResponse']>('/api/merge-candidates'),
  graphCommand: <P extends GraphPostPath>(path: P, body: GraphPostRequest<P>) =>
    request<GraphPostResponse<P>>(path, json('POST', body)),
};
