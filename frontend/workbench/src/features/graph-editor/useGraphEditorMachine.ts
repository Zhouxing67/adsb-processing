import { useCallback, useEffect, useReducer, useState } from 'react';
import { api } from '../../api/client';
import type { GraphPostInput, GraphPostPath } from '../../api/client';
import type { EdgeProperties, GeoFeature, LineGeometry, NodeId, NodeProperties, PointGeometry, SelectedFeature } from '../../api/types';
import { useWorkbench } from '../../app/WorkbenchContext';
import type { EditorTool } from '../../app/WorkbenchContext';
import { isNodeFeature as isNode } from '../../domain/features';
import type { Aeroway } from '../../domain/properties';
import type { GraphDialogState } from './types';

type DrawPoint = [number, number];
type IdleState = { phase: 'idle'; tool: EditorTool; selection: []; drawPoints: []; dialog: null; previewGeometry: null };
type SelectingState = { phase: 'selecting'; tool: EditorTool; selection: SelectedFeature[]; drawPoints: DrawPoint[]; dialog: null; previewGeometry: null };
type ConfirmingState = { phase: 'confirming'; tool: EditorTool; selection: SelectedFeature[]; drawPoints: DrawPoint[]; dialog: GraphDialogState; previewGeometry: LineGeometry | null };
export type GraphEditorState = IdleState | SelectingState | ConfirmingState;

type MachineEvent =
  | { type: 'RESET'; tool: EditorTool }
  | { type: 'SELECT'; selection: SelectedFeature[] }
  | { type: 'ADD_POINT'; point: DrawPoint }
  | { type: 'UNDO_POINT' }
  | { type: 'OPEN_DIALOG'; dialog: GraphDialogState }
  | { type: 'SET_PREVIEW'; geometry: LineGeometry | null };

function idle(tool: EditorTool): IdleState { return { phase: 'idle', tool, selection: [], drawPoints: [], dialog: null, previewGeometry: null }; }

export function graphEditorReducer(state: GraphEditorState, event: MachineEvent): GraphEditorState {
  switch (event.type) {
    case 'RESET': return idle(event.tool);
    case 'SELECT': return event.selection.length ? { phase: 'selecting', tool: state.tool, selection: event.selection, drawPoints: state.drawPoints, dialog: null, previewGeometry: null } : idle(state.tool);
    case 'ADD_POINT': return state.phase === 'selecting' ? { ...state, drawPoints: [...state.drawPoints, event.point] } : state;
    case 'UNDO_POINT': return state.phase === 'selecting' ? { ...state, drawPoints: state.drawPoints.slice(0, -1) } : state;
    case 'OPEN_DIALOG': return { phase: 'confirming', tool: state.tool, selection: state.selection, drawPoints: state.drawPoints, dialog: event.dialog, previewGeometry: null };
    case 'SET_PREVIEW': return state.phase === 'confirming' ? { ...state, previewGeometry: event.geometry } : state;
  }
}

export function useGraphEditorMachine() {
  const wb = useWorkbench();
  const [machine, send] = useReducer(graphEditorReducer, wb.tool, idle);
  const [drawAeroway, setDrawAeroway] = useState<Aeroway>('taxiway');
  const [drawRef, setDrawRef] = useState('');
  useEffect(() => { send({ type: 'RESET', tool: wb.tool }); }, [wb.tool]);

  const reset = useCallback(() => {
    send({ type: 'RESET', tool: wb.tool });
    wb.dispatch({ type: 'selected', value: null });
  }, [wb]);
  const openDialog = useCallback((dialog: GraphDialogState) => send({ type: 'OPEN_DIALOG', dialog }), []);
  const previewMerge = useCallback(async (nodeIds: NodeId[], revision: number) => {
    const preview = await wb.previewGraphCommand('/api/merge-nodes-preview', { node_ids: nodeIds, canonical_node_id: null, expected_revision: revision });
    if (preview) openDialog({ kind: 'merge', preview });
  }, [wb, openDialog]);
  const openMergeCandidates = useCallback(async () => {
    try { openDialog({ kind: 'merge-candidates', preview: await api.mergeCandidates() }); }
    catch (error) { wb.dispatch({ type: 'error', value: error instanceof Error ? error.message : '候选节点读取失败' }); }
  }, [wb, openDialog]);
  const confirmDialog = useCallback(async <P extends GraphPostPath,>(path: P, body: GraphPostInput<P>) => {
    if (await wb.runGraphCommand(path, body) !== null) reset();
  }, [wb, reset]);

  const handleFeature = useCallback(async (feature: SelectedFeature) => {
    const state = wb.state;
    if (!state?.capabilities.can_edit_graph || wb.tool === 'inspect') { wb.dispatch({ type: 'selected', value: feature }); return; }
    if (wb.tool === 'delete') {
      if (isNode(feature)) {
        const preview = await wb.previewGraphCommand('/api/delete-node-preview', { node: feature.properties.id, pair_ids: [], discard_unpaired: false });
        if (preview) openDialog({ kind: 'delete-node', preview, node: feature.properties.id });
      } else {
        const preview = await wb.previewGraphCommand('/api/delete-edge-preview', { edge: feature.properties.id });
        if (preview) openDialog({ kind: 'delete-edge', preview, edge: feature.properties.id });
      }
      return;
    }
    if (wb.tool === 'split') {
      if (!isNode(feature)) { send({ type: 'SELECT', selection: [feature] }); wb.dispatch({ type: 'status', value: '已选择目标边，请点击切分位置' }); }
      return;
    }
    if (wb.tool === 'merge') {
      if (!isNode(feature)) return;
      const duplicate = machine.selection.some(item => isNode(item) && item.properties.id === feature.properties.id);
      const selection = duplicate ? machine.selection : [...machine.selection, feature];
      if (!duplicate) send({ type: 'SELECT', selection });
      wb.dispatch({ type: 'status', value: `已选择 ${selection.length} 个待合并节点` });
      return;
    }
    if (wb.tool === 'draw' || wb.tool === 'restore') {
      if (!isNode(feature)) return;
      if (!machine.selection.length) { send({ type: 'SELECT', selection: [feature] }); wb.dispatch({ type: 'status', value: '已选择起点，请选择终点' }); return; }
      const start = machine.selection[0] as GeoFeature<PointGeometry, NodeProperties>;
      if (start.properties.id === feature.properties.id) {
        wb.dispatch({ type: 'status', value: '起点和终点不能相同' });
        return;
      }
      if (wb.tool === 'draw') {
        const ref = drawRef.trim() || null;
        const result = await wb.runGraphCommand('/api/draw-connection', { start: start.properties.id, end: feature.properties.id, intermediate_points: machine.drawPoints, aeroway: drawAeroway, ref });
        if (result !== null) { setDrawRef(''); reset(); }
      } else {
        const preview = await wb.previewGraphCommand('/api/restore-options', { start: start.properties.id, end: feature.properties.id, candidate_id: null });
        if (preview?.candidates.length) openDialog({ kind: 'restore', preview, start: start.properties.id, end: feature.properties.id });
        else wb.dispatch({ type: 'status', value: '原始来源网络中没有可靠路径候选' });
      }
      return;
    }
    if (wb.tool === 'snap') {
      if (!machine.selection.length && isNode(feature)) { send({ type: 'SELECT', selection: [feature] }); wb.dispatch({ type: 'status', value: '请选择目标边' }); return; }
      if (machine.selection.length && !isNode(feature)) {
        const node = machine.selection[0] as GeoFeature<PointGeometry, NodeProperties>;
        const preview = await wb.previewGraphCommand('/api/manual-snap-preview', { node: node.properties.id, edge: feature.properties.id });
        if (preview) openDialog({ kind: 'snap', preview, node: node.properties.id, edge: feature.properties.id });
      }
    }
  }, [machine.selection, machine.drawPoints, drawAeroway, drawRef, wb, openDialog, reset]);

  const handleMapClick = useCallback(async (longitude: number, latitude: number) => {
    if (wb.tool === 'draw' && machine.phase === 'selecting') {
      send({ type: 'ADD_POINT', point: [longitude, latitude] });
      wb.dispatch({ type: 'status', value: `已添加 ${machine.drawPoints.length + 1} 个形状点，请选择终点` });
    }
    if (wb.tool === 'split' && machine.phase === 'selecting' && machine.selection.length && !isNode(machine.selection[0])) {
      const edge = machine.selection[0] as GeoFeature<LineGeometry, EdgeProperties>;
      const preview = await wb.previewGraphCommand('/api/split-source-preview', { edge: edge.properties.id, longitude, latitude, osm_node_id: null });
      if (preview) openDialog({ kind: 'split', preview, edge: edge.properties.id, longitude, latitude });
    }
  }, [machine, wb, openDialog]);

  const mergeNodeIds = machine.selection.reduce<NodeId[]>((ids, item) => { if (isNode(item)) ids.push(item.properties.id); return ids; }, []);
  const undoDrawPoint = useCallback(() => send({ type: 'UNDO_POINT' }), []);
  const setPreviewGeometry = useCallback((geometry: LineGeometry | null) => send({ type: 'SET_PREVIEW', geometry }), []);

  return {
    state: machine,
    selection: machine.selection,
    drawPoints: machine.drawPoints,
    drawAeroway,
    setDrawAeroway,
    drawRef,
    setDrawRef,
    dialog: machine.dialog,
    previewGeometry: machine.previewGeometry,
    mergeNodeIds,
    handleFeature,
    handleMapClick,
    reset,
    openMergeCandidates,
    previewMerge,
    confirmDialog,
    undoDrawPoint,
    setPreviewGeometry,
  };
}
