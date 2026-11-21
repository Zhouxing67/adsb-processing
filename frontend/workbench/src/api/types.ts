import type { components as GraphApi } from './generated/graph';

export type PointGeometry = GraphApi['schemas']['PointGeometry'];
export type LineGeometry = GraphApi['schemas']['LineStringGeometry'];
export interface GeoFeature<G, P = Record<string, unknown>> { type: 'Feature'; geometry: G; properties: P }
export interface GeoCollection<G = PointGeometry | LineGeometry, P = Record<string, unknown>> { type: 'FeatureCollection'; features: Array<GeoFeature<G, P>> }

export type NodeId = GraphApi['schemas']['NodeIdField'];
export type EdgeIdentity = GraphApi['schemas']['EdgeIdentity'];
export type NodeProperties = GraphApi['schemas']['NodeProperties'];
export type EdgeProperties = GraphApi['schemas']['EdgeProperties'];
export type TopologySummary = GraphApi['schemas']['TopologySummary'];
export type WorkbenchState = GraphApi['schemas']['WorkbenchStateResponse'];
export interface MatchState {
  flight_key: string; graph_id?: string | null; status: string; error?: string | null;
  failure_type?: string | null; task_id?: string | null; has_path: boolean;
}
export interface FlightItem {
  flight_key: string; flight_id: string; flight_number?: string | null;
  movement_type: string; start_time: string; end_time: string; point_count: number;
  stand_position?: string | null; can_edit_stand: boolean; inconsistent_fields: string[];
  match: MatchState;
}
export interface FlightCatalogue {
  items: FlightItem[]; stand_options: string[]; supports_validation_filter: boolean;
  total: number; total_pages: number; page: number; page_size: number;
  dataset_max_points: number; max_map_flights: number; graph_id: string;
  time: { input_semantics: string; display_timezone: string };
}
export interface FlightGeometry {
  flight_key: string; flight: GeoCollection; path: GeoCollection | null; match: MatchState;
}
export interface MapFlightEntry {
  geometry: FlightGeometry; label: string; slot: number;
  trajectoryVisible: boolean; pathVisible: boolean;
}
export interface FlightDetail {
  summary: FlightItem; fields: Record<string, unknown>; inconsistent_fields: Record<string, unknown>;
  observations: Array<Record<string, unknown>>; observation_columns: string[];
  observation_page: number; observation_pages: number; observation_total: number; all_fields: boolean; match: MatchState;
}
export interface MatchTask { task_id: string; flight_keys: string[]; complete: boolean; items: MatchState[] }
export interface MatchStatus {
  graph_id: string; tasks: MatchTask[];
  progress: { total: number; waiting: number; running: number; success: number; failed: number; complete: boolean; summary: Record<string, unknown> };
}
export type SelectedFeature = GeoFeature<PointGeometry, NodeProperties> | GeoFeature<LineGeometry, EdgeProperties>;
