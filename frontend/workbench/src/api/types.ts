export interface PointGeometry { type: 'Point'; coordinates: [number, number] }
export interface LineGeometry { type: 'LineString'; coordinates: Array<[number, number]> }
export interface GeoFeature<G, P = Record<string, unknown>> { type: 'Feature'; geometry: G; properties: P }
export interface GeoCollection<G = PointGeometry | LineGeometry, P = Record<string, unknown>> { type: 'FeatureCollection'; features: Array<GeoFeature<G, P>> }

export type EncodedValue = { type: string; value: unknown };
export type EdgeIdentity = { u: EncodedValue; v: EncodedValue; key: EncodedValue };

export interface NodeProperties {
  id: EncodedValue; node_id: string; node_type: string; degree: number;
  component: number; topology_role: string; editable_attributes: Record<string, unknown>;
  color: string; radius: number;
}
export interface EdgeProperties {
  id: EdgeIdentity; edge_id: string; u: string; v: string; aeroway?: string | null;
  ref?: string | null; name?: string | null; validation_color: string;
  editable_attributes: Record<string, unknown>;
}
export interface TopologySummary {
  component_count: number; largest_component: number; isolated_count: number;
  dangling_count: number; parallel_pair_count: number; isolated_nodes: string[];
  dangling_nodes: string[];
  components: Array<{ index: number; size: number; node_ids: EncodedValue[] }>;
  parallel_groups: Array<{ u: string; v: string; edge_ids: EdgeIdentity[] }>;
}
export interface WorkbenchState {
  revision: number; topology_revision: number; graph_id?: string; flight_mode: boolean;
  capabilities: { can_edit_graph: boolean; has_flights: boolean; can_match: boolean };
  nodes: GeoCollection<PointGeometry, NodeProperties>;
  edges: GeoCollection<LineGeometry, EdgeProperties>;
  node_count: number; edge_count: number; flight_count: number; path_count: number;
  topology: TopologySummary; can_undo: boolean; can_finish: boolean; save_path: string;
}
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
