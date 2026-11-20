import type { EdgeIdentity, EncodedValue, GeoFeature, LineGeometry } from '../../api/types';

export interface RestoreCandidate {
  candidate_id: string; source_ids: string[]; osm_way_ids: Array<string | number>;
  length_m: number; geometry: LineGeometry;
}
export interface RestorePreview { revision: number; current_endpoints: string[]; candidates: RestoreCandidate[] }
export interface MergeNode { id: EncodedValue; node_id: string; manual: boolean; degree: number; source_ids: string[]; position?: [number, number] }
export interface MergePreview {
  revision: number; node_ids: EncodedValue[]; canonical_node_id: EncodedValue; nodes: MergeNode[];
  max_distance_m: number; affected_edges: unknown[]; warnings: string[];
}
export interface MergeCandidates { revision: number; candidates: Array<{ node_ids: EncodedValue[]; max_distance_m: number; nodes: MergeNode[] }> }
export interface EdgeDeletePreview { revision: number; edge: string; source_segments: Array<{ source_id: string; source_start_m: number; source_end_m: number; reversed: boolean }> }
export interface NodeDeletePair { pair_id: string; left: string; right: string; endpoints: string[]; source_ids: string[]; same_source: boolean; angle_degrees: number; geometry: LineGeometry; recommended: boolean }
export interface NodeDeletePreview {
  revision: number; node: string; degree: number;
  half_edges: Array<{ half_id: string; edge: string; outer_node: string; source_ids: string[] }>;
  pair_candidates: NodeDeletePair[]; recommended_unpaired: string[];
}
export interface SplitPreview { revision: number; source_id: string; candidates: Array<{ id: EncodedValue; distance_m: number }>; recommended_node?: EncodedValue | null }
export interface SnapPreview { revision: number; node: string; edge: string; distance_m: number; target_source_id: string; target_station_m: number; connector_geometry: LineGeometry }

export type GraphDialogState =
  | { kind: 'restore'; preview: RestorePreview; start: EncodedValue; end: EncodedValue }
  | { kind: 'merge'; preview: MergePreview }
  | { kind: 'merge-candidates'; preview: MergeCandidates }
  | { kind: 'delete-edge'; preview: EdgeDeletePreview; edge: EdgeIdentity }
  | { kind: 'delete-node'; preview: NodeDeletePreview; node: EncodedValue }
  | { kind: 'split'; preview: SplitPreview; edge: EdgeIdentity; longitude: number; latitude: number }
  | { kind: 'snap'; preview: SnapPreview; node: EncodedValue; edge: EdgeIdentity };

export type PreviewGeometry = GeoFeature<LineGeometry> | null;
