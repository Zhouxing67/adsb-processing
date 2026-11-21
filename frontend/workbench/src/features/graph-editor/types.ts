import type { components as GraphApi } from '../../api/generated/graph';
import type { EdgeIdentity, GeoFeature, LineGeometry, NodeId } from '../../api/types';

export type RestorePreview = GraphApi['schemas']['RestoreOptionsResponse'];
export type MergePreview = GraphApi['schemas']['MergeNodesPreviewResponse'];
export type MergeCandidates = GraphApi['schemas']['MergeCandidatesResponse'];
export type EdgeDeletePreview = GraphApi['schemas']['DeleteEdgePreviewResponse'];
export type NodeDeletePreview = GraphApi['schemas']['DeleteNodePreviewResponse'];
export type SplitPreview = GraphApi['schemas']['SplitSourcePreviewResponse'];
export type SnapPreview = GraphApi['schemas']['ManualSnapPreviewResponse'];

export type GraphDialogState =
  | { kind: 'restore'; preview: RestorePreview; start: NodeId; end: NodeId }
  | { kind: 'merge'; preview: MergePreview }
  | { kind: 'merge-candidates'; preview: MergeCandidates }
  | { kind: 'delete-edge'; preview: EdgeDeletePreview; edge: EdgeIdentity }
  | { kind: 'delete-node'; preview: NodeDeletePreview; node: NodeId }
  | { kind: 'split'; preview: SplitPreview; edge: EdgeIdentity; longitude: number; latitude: number }
  | { kind: 'snap'; preview: SnapPreview; node: NodeId; edge: EdgeIdentity };

export type PreviewGeometry = GeoFeature<LineGeometry> | null;
