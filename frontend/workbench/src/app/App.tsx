import { useCallback, useEffect, useMemo, useState } from 'react';
import { WorkbenchProvider, useWorkbench } from './WorkbenchContext';
import type { EditorTool } from './WorkbenchContext';
import type { EdgeProperties, FlightDetail, GeoFeature, LineGeometry, NodeProperties, PointGeometry, SelectedFeature } from '../api/types';
import { FlightPanel } from '../features/flights/FlightPanel';
import { MapView } from '../features/map/MapView';
import { GraphDialog } from '../features/graph-editor/GraphDialog';
import type { EdgeDeletePreview, GraphDialogState, MergeCandidates, MergePreview, NodeDeletePreview, RestorePreview, SnapPreview, SplitPreview } from '../features/graph-editor/types';
import { api } from '../api/client';
import '../styles/react-app.css';

const tools: Array<{ key: EditorTool; label: string; symbol: string }> = [
  { key: 'inspect', label: '查看', symbol: '⌖' }, { key: 'split', label: '补充分割点', symbol: '✂' },
  { key: 'draw', label: '直接绘制连接', symbol: '＋' }, { key: 'restore', label: '恢复来源连接', symbol: '⌁' },
  { key: 'merge', label: '合并重合节点', symbol: '◎' }, { key: 'snap', label: '人工吸附到边', symbol: '↦' },
  { key: 'delete', label: '删除 / 简化', symbol: '×' },
];
const toolMessages: Record<EditorTool, string> = {
  inspect: '查看模式 · 点击节点或派生边查看详情', split: '补充分割点 · 选择边后点击切分位置',
  draw: '直接绘制连接 · 选择起点、点击地图添加形状点、再选择终点', restore: '恢复来源连接 · 依次选择两个节点',
  merge: '合并节点 · 依次选择两个节点', snap: '人工吸附 · 先选择节点，再选择目标边', delete: '删除 / 简化 · 点击节点或边',
};
function isNode(feature: SelectedFeature): feature is GeoFeature<PointGeometry, NodeProperties> { return feature.geometry.type === 'Point'; }

function Header() {
  const wb = useWorkbench(), state = wb.state;
  const command = async (path: string) => { await wb.runGraphCommand(path); };
  return <header className="topbar panel">
    <div className="brand-mark">AW</div><div className="brand-copy"><strong>Airport Workbench</strong><span>{state ? `${state.node_count} 节点 · ${state.edge_count} 边${state.flight_mode ? ` · ${state.flight_count} 航班` : ''}` : '载入中…'}</span></div>
    <div className="top-actions">
      <button className="text-button" onClick={() => wb.dispatch({ type: 'panel', panel: 'searchOpen', value: !wb.searchOpen })}>⌕ 搜索</button>
      <button className="text-button" onClick={() => wb.dispatch({ type: 'panel', panel: 'topologyOpen', value: !wb.topologyOpen })}>◇ 拓扑检查</button>
      {state?.capabilities.can_edit_graph && <><button className="text-button" disabled={!state.can_undo} onClick={() => void command('/api/undo')}>↶ 撤销</button><button className="save-button" onClick={() => void command('/api/save')}>✓ 保存</button>{state.can_finish && <button className="finish-button" onClick={() => void command('/api/finish')}>→ 完成</button>}</>}
    </div>
  </header>;
}

function ToolDock() {
  const wb = useWorkbench();
  if (!wb.state?.capabilities.can_edit_graph) return null;
  return <nav className="tool-dock panel react-tool-dock" aria-label="编辑工具"><div className="dock-title">编辑工具</div>{tools.map(tool => <button key={tool.key} className={`tool ${wb.tool === tool.key ? 'active' : ''} ${tool.key === 'delete' ? 'danger' : ''}`} onClick={() => { wb.dispatch({ type: 'tool', value: tool.key }); wb.dispatch({ type: 'status', value: toolMessages[tool.key] }); }}><span>{tool.symbol}</span><em>{tool.label}</em></button>)}</nav>;
}

function TopologyPanel() {
  const wb = useWorkbench(), topology = wb.state?.topology;
  const [reviewIndex, setReviewIndex] = useState(-1);
  const nodes = useMemo(() => [...(wb.state?.nodes.features ?? [])].sort((a, b) => JSON.stringify(a.properties.id).localeCompare(JSON.stringify(b.properties.id))), [wb.state?.topology_revision]);
  const showReview = (index: number) => { const feature = nodes[index]; if (!feature) return; setReviewIndex(index); wb.dispatch({ type: 'selected', value: feature }); wb.dispatch({ type: 'status', value: index === nodes.length - 1 ? '已到最后一个节点；这不表示全部复核通过' : `遍历位置 ${index + 1} / ${nodes.length} · 节点 ${feature.properties.node_id}` }); };
  if (!wb.topologyOpen || !topology) return null;
  const metrics = [['连通分量', topology.component_count], ['最大分量', topology.largest_component], ['孤立节点', topology.isolated_count], ['悬挂节点', topology.dangling_count], ['平行边组', topology.parallel_pair_count]];
  return <aside className="topology-panel panel"><div className="panel-heading"><h2>拓扑概览</h2><button className="panel-close" onClick={() => wb.dispatch({ type: 'panel', panel: 'topologyOpen', value: false })}>×</button></div><div className="metric-grid">{metrics.map(([label, value]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}</div><div className="topology-details"><h3>孤立节点</h3><p>{topology.isolated_nodes.slice(0, 20).join('、') || '无'}</p><h3>悬挂节点</h3><p>{topology.dangling_nodes.slice(0, 20).join('、') || '无'}</p><h3>分量</h3>{topology.components.slice(0, 20).map(component => <button className="secondary-button" key={component.index} onClick={() => { const node = wb.state?.nodes.features.find(item => component.node_ids.some(id => JSON.stringify(id) === JSON.stringify(item.properties.id))); if (node) wb.dispatch({ type: 'selected', value: node }); }}>分量 {component.index} · {component.size} 节点</button>)}</div><section className="node-review"><h3>逐点检查</h3><p className="field-note">{reviewIndex >= 0 ? `遍历位置 ${reviewIndex + 1} / ${nodes.length} · 节点 ${nodes[reviewIndex]?.properties.node_id}` : '尚未开始'}</p><div className="node-review-actions"><button disabled={!nodes.length} onClick={() => showReview(0)}>开始</button><button disabled={reviewIndex <= 0} onClick={() => showReview(reviewIndex - 1)}>上一个</button><button disabled={reviewIndex < 0 || reviewIndex >= nodes.length - 1} onClick={() => showReview(reviewIndex + 1)}>下一个</button><button disabled={reviewIndex < 0} onClick={() => { setReviewIndex(-1); wb.dispatch({ type: 'selected', value: null }); }}>结束</button></div></section></aside>;
}

function SearchPanel() {
  const wb = useWorkbench(); const [query, setQuery] = useState(''), [stand, setStand] = useState(''), [edgeU, setEdgeU] = useState(''), [edgeV, setEdgeV] = useState('');
  if (!wb.searchOpen || !wb.state) return null;
  const select = (feature: SelectedFeature | undefined, label: string) => { if (feature) wb.dispatch({ type: 'selected', value: feature }); else wb.dispatch({ type: 'status', value: `未找到 ${label}` }); };
  const search = () => { const needle = query.trim().toLocaleLowerCase(); select(wb.state!.nodes.features.find(item => item.properties.node_id.toLocaleLowerCase().includes(needle)) ?? wb.state!.edges.features.find(item => item.properties.edge_id.toLocaleLowerCase().includes(needle)), query); };
  const searchStand = () => select(wb.state!.edges.features.find(item => String(item.properties.ref ?? '').toLocaleLowerCase() === stand.trim().toLocaleLowerCase()), `机位 ${stand}`);
  const searchEdge = () => { const pair = [edgeU.trim(), edgeV.trim()].sort().join('|'); select(wb.state!.edges.features.find(item => [item.properties.u, item.properties.v].map(String).sort().join('|') === pair), `边 ${edgeU}—${edgeV}`); };
  return <section className="search-panel panel"><div className="panel-heading"><div><small>快速定位</small><h2>搜索图要素</h2></div><button className="panel-close" onClick={() => wb.dispatch({ type: 'panel', panel: 'searchOpen', value: false })}>×</button></div><label>节点或边 ID<div className="input-action"><input value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') search(); }} placeholder="节点 ID 或完整边 ID" /><button onClick={search}>选中</button></div></label><label>机位编号<div className="input-action"><input value={stand} onChange={event => setStand(event.target.value)} placeholder="例如 A01" /><button onClick={searchStand}>定位机位</button></div></label><label>边的两个端点<div className="edge-inputs"><input value={edgeU} onChange={event => setEdgeU(event.target.value)} placeholder="端点 A" /><span>—</span><input value={edgeV} onChange={event => setEdgeV(event.target.value)} placeholder="端点 B" /><button onClick={searchEdge}>选中边</button></div></label></section>;
}

function FeatureDetails() {
  const wb = useWorkbench(), feature = wb.selected;
  const attributes = feature?.properties.editable_attributes ?? {};
  const [aeroway, setAeroway] = useState(''), [name, setName] = useState(''), [ref, setRef] = useState('');
  useEffect(() => { setAeroway(String(attributes.aeroway ?? '')); setName(String(attributes.name ?? '')); setRef(String(attributes.ref ?? '')); }, [feature, attributes.aeroway, attributes.name, attributes.ref]);
  if (!feature || !wb.detailsOpen) return null;
  const node = isNode(feature);
  const save = async () => {
    const body = node ? { node: feature.properties.id, attributes: { aeroway: aeroway || null, name: name || null, ref: ref || null } } : { edge: feature.properties.id, attributes: { aeroway: aeroway || null, name: name || null, ref: ref || null } };
    await wb.runGraphCommand(node ? '/api/update-node' : '/api/update-edge', body);
    wb.dispatch({ type: 'selected', value: null });
  };
  return <aside className="details panel"><button className="panel-close" onClick={() => wb.dispatch({ type: 'selected', value: null })}>×</button><div className="details-content"><small>{node ? '节点' : '边'}</small><h2>{node ? feature.properties.node_id : feature.properties.edge_id}</h2><dl>{Object.entries(feature.properties).filter(([key]) => !['editable_attributes', 'id'].includes(key)).slice(0, 12).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value ?? '—')}</dd></div>)}</dl>{wb.state?.capabilities.can_edit_graph && <div className="property-form"><label>aeroway<input value={aeroway} onChange={event => setAeroway(event.target.value)} /></label><label>name<input value={name} onChange={event => setName(event.target.value)} /></label><label>ref<input value={ref} onChange={event => setRef(event.target.value)} /></label><button className="primary-button" onClick={() => void save()}>保存属性</button></div>}</div></aside>;
}

function ObservationView({ detail }: { detail: FlightDetail | null }) {
  const wb = useWorkbench();
  const [current, setCurrent] = useState(detail);
  const [allFields, setAllFields] = useState(false);
  useEffect(() => { setCurrent(detail); setAllFields(Boolean(detail?.all_fields)); }, [detail]);
  if (!detail) return <section className="main-view observations-view"><p className="field-note">请从航班目录打开详情。</p></section>;
  if (!current) return null;
  const load = async (page: number, expanded = allFields) => { const value = await api.detail(detail.summary.flight_key, page, expanded); setCurrent(value); setAllFields(expanded); };
  const locate = (row: Record<string, unknown>) => {
    const find = (...names: string[]) => { const key = Object.keys(row).find(item => names.includes(item.toLowerCase())); return key ? row[key] : undefined; };
    const longitude = Number(find('longitude', 'lon')), latitude = Number(find('latitude', 'lat'));
    if (Number.isFinite(longitude) && Number.isFinite(latitude)) wb.dispatch({ type: 'observation-location', value: [latitude, longitude] });
  };
  return <section className="main-view observations-view"><header className="observations-header"><button className="secondary-button" onClick={() => wb.dispatch({ type: 'view', value: 'flights' })}>← 航班列表</button><div><small>当前查看航班</small><h2>{current.summary.flight_number || current.summary.flight_id}</h2><p>{current.observation_total} 个观测点</p></div><button className="secondary-button" disabled={!wb.observationLocation} onClick={() => wb.dispatch({ type: 'observation-location', value: null })}>清除地图定位点</button></header><div className="observations-content"><div className="observation-toolbar"><button className="secondary-button" onClick={() => void load(1, !allFields)}>{allFields ? '显示默认字段' : '显示全部字段'}</button><span>第 {current.observation_page || 0} / {current.observation_pages} 页，共 {current.observation_total} 条</span></div><table className="sheet-table observation-table"><thead><tr>{current.observation_columns.map(column => <th key={column}>{column}</th>)}<th>操作</th></tr></thead><tbody>{current.observations.map((row, index) => <tr key={index}>{current.observation_columns.map(column => <td key={column}>{String(row[column] ?? '—')}</td>)}<td><button className="secondary-button" onClick={() => locate(row)}>在地图中定位</button></td></tr>)}</tbody></table><div className="observation-pager"><button disabled={current.observation_page <= 1} onClick={() => void load(current.observation_page - 1)}>上一页</button><button disabled={current.observation_page >= current.observation_pages} onClick={() => void load(current.observation_page + 1)}>下一页</button></div></div></section>;
}

function Workspace() {
  const wb = useWorkbench(); const state = wb.state;
  const [detail, setDetail] = useState<FlightDetail | null>(null);
  const [operation, setOperation] = useState<SelectedFeature[]>([]);
  const [drawPoints, setDrawPoints] = useState<Array<[number, number]>>([]);
  const [splitValidation, setSplitValidation] = useState(false);
  const [dialog, setDialog] = useState<GraphDialogState | null>(null);
  const [previewGeometry, setPreviewGeometry] = useState<LineGeometry | null>(null);
  useEffect(() => { setOperation([]); setDrawPoints([]); setDialog(null); setPreviewGeometry(null); }, [wb.tool]);
  useEffect(() => {
    document.body.classList.add('unified-workbench', 'react-workbench');
    document.body.classList.toggle('flight-mode', Boolean(state?.flight_mode));
    document.body.classList.toggle('read-only', Boolean(state?.flight_mode));
    return () => document.body.classList.remove('unified-workbench', 'react-workbench', 'flight-mode', 'read-only');
  }, [state?.flight_mode]);

  const finishOperation = useCallback(() => { setOperation([]); setDrawPoints([]); setDialog(null); setPreviewGeometry(null); wb.dispatch({ type: 'selected', value: null }); }, [wb]);
  const confirmDialog = useCallback(async (path: string, body: Record<string, unknown>) => { const result = await wb.runGraphCommand(path, body); if (result !== null) finishOperation(); }, [wb, finishOperation]);
  const previewMerge = useCallback(async (nodeIds: import('../api/types').EncodedValue[], revision: number) => {
    const preview = await wb.previewGraphCommand<MergePreview>('/api/merge-nodes-preview', { node_ids: nodeIds, expected_revision: revision });
    if (preview) setDialog({ kind: 'merge', preview });
  }, [wb]);
  const openMergeCandidates = useCallback(async () => {
    try { const preview = await api.mergeCandidates<MergeCandidates>(); setDialog({ kind: 'merge-candidates', preview }); }
    catch (error) { wb.dispatch({ type: 'error', value: error instanceof Error ? error.message : '候选节点读取失败' }); }
  }, [wb]);
  const handleFeature = useCallback(async (feature: SelectedFeature) => {
    if (!state?.capabilities.can_edit_graph || wb.tool === 'inspect') { wb.dispatch({ type: 'selected', value: feature }); return; }
    if (wb.tool === 'delete') {
      if (isNode(feature)) {
        const preview = await wb.previewGraphCommand<NodeDeletePreview>('/api/delete-node-preview', { node: feature.properties.id });
        if (preview) setDialog({ kind: 'delete-node', preview, node: feature.properties.id });
      } else {
        const preview = await wb.previewGraphCommand<EdgeDeletePreview>('/api/delete-edge-preview', { edge: feature.properties.id });
        if (preview) setDialog({ kind: 'delete-edge', preview, edge: feature.properties.id });
      }
      return;
    }
    if (wb.tool === 'split') { if (!isNode(feature)) { setOperation([feature]); wb.dispatch({ type: 'status', value: '已选择目标边，请点击切分位置' }); } return; }
    if (wb.tool === 'merge') {
      if (isNode(feature) && !operation.some(item => isNode(item) && JSON.stringify(item.properties.id) === JSON.stringify(feature.properties.id))) setOperation(items => [...items, feature]);
      wb.dispatch({ type: 'status', value: `已选择 ${operation.length + 1} 个待合并节点` });
      return;
    }
    if (wb.tool === 'draw' || wb.tool === 'restore') {
      if (!isNode(feature)) return;
      if (!operation.length) { setOperation([feature]); wb.dispatch({ type: 'status', value: '已选择起点，请选择终点' }); return; }
      const start = operation[0] as GeoFeature<PointGeometry, NodeProperties>;
      if (wb.tool === 'draw') await wb.runGraphCommand('/api/draw-connection', { start: start.properties.id, end: feature.properties.id, intermediate_points: drawPoints });
      if (wb.tool === 'restore') {
        const preview = await wb.previewGraphCommand<RestorePreview>('/api/restore-options', { start: start.properties.id, end: feature.properties.id });
        if (preview?.candidates.length) setDialog({ kind: 'restore', preview, start: start.properties.id, end: feature.properties.id });
        else wb.dispatch({ type: 'status', value: '原始来源网络中没有可靠路径候选' });
      }
      if (wb.tool === 'draw') finishOperation(); else setOperation([]);
      return;
    }
    if (wb.tool === 'snap') {
      if (!operation.length && isNode(feature)) { setOperation([feature]); wb.dispatch({ type: 'status', value: '请选择目标边' }); return; }
      if (operation.length && !isNode(feature)) {
        const node = operation[0] as GeoFeature<PointGeometry, NodeProperties>;
        const preview = await wb.previewGraphCommand<SnapPreview>('/api/manual-snap-preview', { node: node.properties.id, edge: feature.properties.id });
        if (preview) setDialog({ kind: 'snap', preview, node: node.properties.id, edge: feature.properties.id });
      }
    }
  }, [state, wb, operation, drawPoints, finishOperation]);

  const handleMapClick = useCallback(async (longitude: number, latitude: number) => {
    if (wb.tool === 'draw' && operation.length) { setDrawPoints(points => [...points, [longitude, latitude]]); wb.dispatch({ type: 'status', value: `已添加 ${drawPoints.length + 1} 个形状点，请选择终点` }); }
    if (wb.tool === 'split' && operation.length && !isNode(operation[0])) {
      const edge = operation[0] as GeoFeature<LineGeometry, EdgeProperties>;
      const preview = await wb.previewGraphCommand<SplitPreview>('/api/split-source-preview', { edge: edge.properties.id, longitude, latitude });
      if (preview) setDialog({ kind: 'split', preview, edge: edge.properties.id, longitude, latitude });
      setOperation([]);
    }
  }, [wb, operation, drawPoints.length, finishOperation]);

  if (!state) return <main className="loading-screen">{wb.error || '正在载入工作台…'}</main>;
  return <>
    <Header /><ToolDock />
    {state.flight_mode && <nav className="main-tabs" aria-label="航班主视图"><button className={wb.view === 'map' ? 'active' : ''} onClick={() => wb.dispatch({ type: 'view', value: 'map' })}>地图</button><button className={wb.view === 'flights' ? 'active' : ''} onClick={() => wb.dispatch({ type: 'view', value: 'flights' })}>航班</button>{detail && <button className={wb.view === 'observations' ? 'active' : ''} onClick={() => wb.dispatch({ type: 'view', value: 'observations' })}>观测记录</button>}</nav>}
    <main className="workspace react-workspace">
      <section className={`main-view map-view ${wb.view !== 'map' ? 'hidden' : ''}`}><MapView state={state} flights={wb.mapFlights} splitValidation={splitValidation} selected={[...operation, ...(wb.selected ? [wb.selected] : [])]} drawPoints={drawPoints} previewGeometry={previewGeometry} focusFlightKey={wb.mapFocusKey} fitMapVersion={wb.fitMapVersion} observationLocation={wb.observationLocation} onFeature={handleFeature} onMapClick={handleMapClick} /><div className="map-overlay-stack"><div className="legend panel"><span>节点</span><span>派生边</span><span>虚线＝原始轨迹</span><span>实线＝匹配路径</span></div>{state.capabilities.can_edit_graph && <button className="secondary-button panel" onClick={() => setSplitValidation(value => !value)}>{splitValidation ? '关闭' : '开启'}相邻边辨色</button>}{wb.tool === 'merge' && <><button className="secondary-button panel" onClick={() => void openMergeCandidates()}>重复节点候选</button><button className="primary-button panel" disabled={operation.length < 2} onClick={() => void previewMerge(operation.filter(isNode).map(item => item.properties.id), state.revision)}>检查并合并（{operation.length}）</button><button className="secondary-button panel" onClick={() => setOperation([])}>清空选择</button></>}{wb.tool === 'draw' && operation.length > 0 && <button className="secondary-button panel" onClick={() => { setDrawPoints(points => points.slice(0, -1)); }}>撤销形状点</button>}</div></section>
      {state.flight_mode && wb.view === 'flights' && <FlightPanel onDetail={setDetail} />}
      {state.flight_mode && wb.view === 'observations' && <ObservationView detail={detail} />}
    </main>
    <SearchPanel /><TopologyPanel />{!dialog && <FeatureDetails />}{dialog && <GraphDialog dialog={dialog} onClose={finishOperation} onPreview={setPreviewGeometry} onConfirm={confirmDialog} onMergeCandidate={previewMerge} />}
    <div className="status panel">{wb.error || wb.status}</div>{wb.busy && <div className="busy"><span /></div>}
  </>;
}

export function App() { return <WorkbenchProvider><Workspace /></WorkbenchProvider>; }
