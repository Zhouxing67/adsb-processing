import { useEffect, useMemo, useState } from 'react';
import type { GraphPostInput, GraphPostPath } from '../../api/client';
import type { LineGeometry, NodeId } from '../../api/types';
import type { GraphDialogState } from './types';

interface Props {
  dialog: GraphDialogState;
  onClose(): void;
  onPreview(geometry: LineGeometry | null): void;
  onConfirm<P extends GraphPostPath>(path: P, body: GraphPostInput<P>): Promise<void>;
  onMergeCandidate(nodeIds: NodeId[], revision: number): Promise<void>;
}
export function GraphDialog({ dialog, onClose, onPreview, onConfirm, onMergeCandidate }: Props) {
  const [choice, setChoice] = useState(0);
  const [pairs, setPairs] = useState<Set<string>>(new Set());
  const [discard, setDiscard] = useState(false);
  useEffect(() => {
    const preferred = dialog.kind === 'merge'
      ? dialog.preview.nodes.findIndex(node => node.node_id === dialog.preview.canonical_node_id)
      : dialog.kind === 'split' && dialog.preview.recommended_node
        ? dialog.preview.candidates.findIndex(candidate => candidate.id === dialog.preview.recommended_node)
        : 0;
    setChoice(Math.max(0, preferred)); setDiscard(false);
    if (dialog.kind === 'delete-node') {
      const used = new Set<string>(), selected = new Set<string>();
      dialog.preview.pair_candidates.filter(item => item.recommended).forEach(item => {
        if (!used.has(item.left) && !used.has(item.right)) { selected.add(item.pair_id); used.add(item.left); used.add(item.right); }
      });
      setPairs(selected);
    } else setPairs(new Set());
    if (dialog.kind === 'restore') onPreview(dialog.preview.candidates[0]?.geometry ?? null);
    else if (dialog.kind === 'snap') onPreview(dialog.preview.connector_geometry);
    else onPreview(null);
    return () => onPreview(null);
  }, [dialog, onPreview]);
  const unpaired = useMemo(() => {
    if (dialog.kind !== 'delete-node') return [];
    const used = new Set<string>();
    dialog.preview.pair_candidates.filter(item => pairs.has(item.pair_id)).forEach(item => { used.add(item.left); used.add(item.right); });
    return dialog.preview.half_edges.filter(item => !used.has(item.half_id)).map(item => item.half_id);
  }, [dialog, pairs]);
  const confirm = async () => {
    if (dialog.kind === 'restore') {
      const candidate = dialog.preview.candidates[choice];
      await onConfirm('/api/restore-confirm', { start: dialog.start, end: dialog.end, candidate_id: candidate.candidate_id, expected_revision: dialog.preview.revision });
    } else if (dialog.kind === 'merge') {
      await onConfirm('/api/merge-nodes-confirm', { node_ids: dialog.preview.node_ids, canonical_node_id: dialog.preview.nodes[choice].node_id, expected_revision: dialog.preview.revision });
    } else if (dialog.kind === 'delete-edge') {
      await onConfirm('/api/delete-edge-confirm', { edge: dialog.edge, expected_revision: dialog.preview.revision });
    } else if (dialog.kind === 'delete-node') {
      await onConfirm('/api/delete-node-confirm', { node: dialog.node, pair_ids: [...pairs], discard_unpaired: discard, expected_revision: dialog.preview.revision });
    } else if (dialog.kind === 'split') {
      await onConfirm('/api/split-source-confirm', { edge: dialog.edge, longitude: dialog.longitude, latitude: dialog.latitude, osm_node_id: dialog.preview.candidates[choice]?.id ?? null, expected_revision: dialog.preview.revision });
    } else if (dialog.kind === 'snap') {
      await onConfirm('/api/manual-snap-confirm', { node: dialog.node, edge: dialog.edge, expected_revision: dialog.preview.revision });
    }
  };
  if (dialog.kind === 'merge-candidates') return <aside className="details panel graph-dialog"><button className="panel-close" onClick={onClose}>×</button><h2>疑似重复图节点</h2><p className="field-note">候选距离 ≤ 0.5 m</p><div className="source-options">{dialog.preview.candidates.map((candidate, index) => <div className="merge-candidate" key={index}><strong>候选 {index + 1} · 最大距离 {candidate.max_distance_m.toFixed(3)} m</strong><p>{candidate.nodes.map(node => node.node_id).join('、')}</p><button className="primary-button" onClick={() => void onMergeCandidate(candidate.node_ids, dialog.preview.revision)}>检查并合并</button></div>)}</div></aside>;
  return <aside className="details panel graph-dialog"><button className="panel-close" onClick={onClose}>×</button>
    {dialog.kind === 'restore' && <><h2>从 OSM 恢复连接</h2><p>{dialog.preview.current_endpoints.join(' — ')}</p><div className="source-options">{dialog.preview.candidates.map((candidate, index) => <label className="source-option" key={candidate.candidate_id} onMouseEnter={() => onPreview(candidate.geometry)}><input type="radio" checked={choice === index} onChange={() => { setChoice(index); onPreview(candidate.geometry); }} /><span>{candidate.source_ids.join(' + ')}<br />OSM way {candidate.osm_way_ids.join(' + ')} · {candidate.length_m.toFixed(2)} m</span></label>)}</div></>}
    {dialog.kind === 'merge' && <><h2>合并节点预览</h2><dl><div><dt>最大距离</dt><dd>{dialog.preview.max_distance_m.toFixed(3)} m</dd></div><div><dt>受影响边</dt><dd>{dialog.preview.affected_edges.length}</dd></div></dl><h3>选择规范节点</h3>{dialog.preview.nodes.map((node, index) => <label className="source-option" key={node.node_id}><input type="radio" checked={choice === index} onChange={() => setChoice(index)} /><span>{node.node_id} · {node.manual ? '人工图节点' : 'OSM 图节点'} · 度 {node.degree}</span></label>)}{dialog.preview.warnings.map(item => <p className="warning" key={item}>{item}</p>)}</>}
    {dialog.kind === 'delete-edge' && <><h2>删除派生边</h2><p>{dialog.preview.edge}</p>{dialog.preview.source_segments.map(segment => <p key={`${segment.source_id}-${segment.source_start_m}`}>{segment.source_id} [{segment.source_start_m.toFixed(2)}, {segment.source_end_m.toFixed(2)}]{segment.reversed ? ' 反向' : ''}</p>)}<p className="field-note">SourceEdge 不会被删除。</p></>}
    {dialog.kind === 'delete-node' && <><h2>半边配对</h2><p>节点 {dialog.preview.node} · {dialog.preview.half_edges.length} 条关联半边</p><div className="source-options">{dialog.preview.pair_candidates.map(pair => <label className="source-option pair-option" key={pair.pair_id} onMouseEnter={() => onPreview(pair.geometry)}><input type="checkbox" checked={pairs.has(pair.pair_id)} onChange={event => setPairs(value => { const next = new Set(value); if (event.target.checked) { dialog.preview.pair_candidates.filter(item => item.pair_id !== pair.pair_id && (item.left === pair.left || item.left === pair.right || item.right === pair.left || item.right === pair.right)).forEach(item => next.delete(item.pair_id)); next.add(pair.pair_id); } else next.delete(pair.pair_id); return next; })} /><span><strong>{pair.endpoints.join(' ↔ ')}</strong><br />{pair.source_ids.join(' + ')} · 转角 {pair.angle_degrees}° · {pair.same_source ? '同源' : '跨来源'}</span></label>)}</div><p className="field-note">已选择 {pairs.size} 组连接 · 未使用：{unpaired.join(', ') || '无'}</p>{unpaired.length > 0 && <label className="source-option"><input type="checkbox" checked={discard} onChange={event => setDiscard(event.target.checked)} /><span>明确删除未配对半边</span></label>}</>}
    {dialog.kind === 'split' && <><h2>补充图分割点</h2><p>命中来源：{dialog.preview.source_id}</p>{dialog.preview.candidates.length ? dialog.preview.candidates.map((candidate, index) => <label className="source-option" key={candidate.id}><input type="radio" checked={choice === index} onChange={() => setChoice(index)} /><span>OSM Node {candidate.id} · 距离 {candidate.distance_m.toFixed(2)} m</span></label>) : <p>没有合适 OSM Node，将创建人工节点。</p>}</>}
    {dialog.kind === 'snap' && <><h2>人工吸附预览</h2><dl><div><dt>节点</dt><dd>{dialog.preview.node}</dd></div><div><dt>目标边</dt><dd>{dialog.preview.edge}</dd></div><div><dt>移动距离</dt><dd>{dialog.preview.distance_m.toFixed(3)} m</dd></div><div><dt>目标来源</dt><dd>{dialog.preview.target_source_id}</dd></div></dl><p className="field-note">确认后将移动图节点、重建关联边，并切分目标来源区间。</p></>}
    <div className="dialog-actions"><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" disabled={dialog.kind === 'delete-node' && unpaired.length > 0 && !discard} onClick={() => void confirm()}>确认</button></div>
  </aside>;
}
