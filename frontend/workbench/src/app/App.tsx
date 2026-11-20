import { useCallback, useEffect, useMemo, useState } from 'react';
import { WorkbenchProvider, useWorkbench } from './WorkbenchContext';
import type { EditorTool } from './WorkbenchContext';
import type { EdgeProperties, FlightDetail, GeoFeature, LineGeometry, NodeProperties, PointGeometry, SelectedFeature } from '../api/types';
import { FlightPanel } from '../features/flights/FlightPanel';
import { MapView } from '../features/map/MapView';
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
  if (!wb.topologyOpen || !topology) return null;
  const metrics = [['连通分量', topology.component_count], ['最大分量', topology.largest_component], ['孤立节点', topology.isolated_count], ['悬挂节点', topology.dangling_count], ['平行边组', topology.parallel_pair_count]];
  return <aside className="topology-panel panel"><div className="panel-heading"><h2>拓扑概览</h2><button className="panel-close" onClick={() => wb.dispatch({ type: 'panel', panel: 'topologyOpen', value: false })}>×</button></div><div className="metric-grid">{metrics.map(([label, value]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}</div><div className="topology-details"><h3>孤立节点</h3><p>{topology.isolated_nodes.slice(0, 20).join('、') || '无'}</p><h3>悬挂节点</h3><p>{topology.dangling_nodes.slice(0, 20).join('、') || '无'}</p></div></aside>;
}

function SearchPanel() {
  const wb = useWorkbench(); const [query, setQuery] = useState('');
  if (!wb.searchOpen || !wb.state) return null;
  const search = () => {
    const needle = query.trim().toLocaleLowerCase();
    const feature = wb.state!.nodes.features.find(item => item.properties.node_id.toLocaleLowerCase().includes(needle)) ?? wb.state!.edges.features.find(item => item.properties.edge_id.toLocaleLowerCase().includes(needle));
    if (feature) wb.dispatch({ type: 'selected', value: feature }); else wb.dispatch({ type: 'status', value: `未找到 ${query}` });
  };
  return <section className="search-panel panel"><div className="panel-heading"><div><small>快速定位</small><h2>搜索图要素</h2></div><button className="panel-close" onClick={() => wb.dispatch({ type: 'panel', panel: 'searchOpen', value: false })}>×</button></div><div className="input-action"><input value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') search(); }} placeholder="节点 ID 或边 ID" /><button onClick={search}>选中</button></div></section>;
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
  if (!detail) return <section className="main-view observations-view"><p className="field-note">请从航班目录打开详情。</p></section>;
  return <section className="main-view observations-view"><header className="observations-header"><button className="secondary-button" onClick={() => wb.dispatch({ type: 'view', value: 'flights' })}>← 航班列表</button><div><small>当前查看航班</small><h2>{detail.summary.flight_number || detail.summary.flight_id}</h2><p>{detail.observation_total} 个观测点</p></div></header><div className="observations-content"><table className="sheet-table"><thead><tr>{detail.observation_columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{detail.observations.map((row, index) => <tr key={index}>{detail.observation_columns.map(column => <td key={column}>{String(row[column] ?? '—')}</td>)}</tr>)}</tbody></table></div></section>;
}

function Workspace() {
  const wb = useWorkbench(); const state = wb.state;
  const [detail, setDetail] = useState<FlightDetail | null>(null);
  const [operation, setOperation] = useState<SelectedFeature[]>([]);
  const [drawPoints, setDrawPoints] = useState<Array<[number, number]>>([]);
  const [splitValidation, setSplitValidation] = useState(false);
  useEffect(() => { setOperation([]); setDrawPoints([]); }, [wb.tool]);
  useEffect(() => {
    document.body.classList.add('unified-workbench', 'react-workbench');
    document.body.classList.toggle('flight-mode', Boolean(state?.flight_mode));
    document.body.classList.toggle('read-only', Boolean(state?.flight_mode));
    return () => document.body.classList.remove('unified-workbench', 'react-workbench', 'flight-mode', 'read-only');
  }, [state?.flight_mode]);

  const finishOperation = useCallback(() => { setOperation([]); setDrawPoints([]); wb.dispatch({ type: 'selected', value: null }); }, [wb]);
  const handleFeature = useCallback(async (feature: SelectedFeature) => {
    if (!state?.capabilities.can_edit_graph || wb.tool === 'inspect') { wb.dispatch({ type: 'selected', value: feature }); return; }
    if (wb.tool === 'delete') {
      if (isNode(feature)) {
        const plan = await wb.runGraphCommand<{ pair_candidates: Array<{ pair_id: string; recommended: boolean }>; recommended_unpaired: string[] }>('/api/delete-node-preview', { node: feature.properties.id });
        if (!plan) return;
        const pairIds = plan.pair_candidates.filter(item => item.recommended).map(item => item.pair_id);
        const discard = plan.recommended_unpaired.length > 0;
        const warning = discard ? `推荐配对后仍有 ${plan.recommended_unpaired.length} 条半边会被丢弃。` : `将按推荐方案重组 ${pairIds.length} 组半边。`;
        if (window.confirm(`${warning}确认删除节点？`)) await wb.runGraphCommand('/api/delete-node-confirm', { node: feature.properties.id, pair_ids: pairIds, discard_unpaired: discard });
      } else if (window.confirm('确认删除这条边？')) await wb.runGraphCommand('/api/delete-edge-confirm', { edge: feature.properties.id });
      finishOperation(); return;
    }
    if (wb.tool === 'split') { if (!isNode(feature)) { setOperation([feature]); wb.dispatch({ type: 'status', value: '已选择目标边，请点击切分位置' }); } return; }
    if (wb.tool === 'draw' || wb.tool === 'restore' || wb.tool === 'merge') {
      if (!isNode(feature)) return;
      if (!operation.length) { setOperation([feature]); wb.dispatch({ type: 'status', value: '已选择起点，请选择终点' }); return; }
      const start = operation[0] as GeoFeature<PointGeometry, NodeProperties>;
      if (wb.tool === 'draw') await wb.runGraphCommand('/api/draw-connection', { start: start.properties.id, end: feature.properties.id, intermediate_points: drawPoints });
      if (wb.tool === 'merge' && window.confirm('确认合并这两个节点？')) await wb.runGraphCommand('/api/merge-nodes-confirm', { node_ids: [start.properties.id, feature.properties.id], canonical_node_id: start.properties.id });
      if (wb.tool === 'restore') {
        const options = await wb.runGraphCommand<{ candidates: Array<{ candidate_id: string }> }>('/api/restore-options', { start: start.properties.id, end: feature.properties.id });
        const candidate = options?.candidates[0];
        if (candidate && window.confirm('使用推荐来源路径恢复连接？')) await wb.runGraphCommand('/api/restore-confirm', { start: start.properties.id, end: feature.properties.id, candidate_id: candidate.candidate_id });
      }
      finishOperation(); return;
    }
    if (wb.tool === 'snap') {
      if (!operation.length && isNode(feature)) { setOperation([feature]); wb.dispatch({ type: 'status', value: '请选择目标边' }); return; }
      if (operation.length && !isNode(feature) && window.confirm('确认将节点吸附到目标边？')) {
        const node = operation[0] as GeoFeature<PointGeometry, NodeProperties>;
        await wb.runGraphCommand('/api/manual-snap-confirm', { node: node.properties.id, edge: feature.properties.id }); finishOperation();
      }
    }
  }, [state, wb, operation, drawPoints, finishOperation]);

  const handleMapClick = useCallback(async (longitude: number, latitude: number) => {
    if (wb.tool === 'draw' && operation.length) { setDrawPoints(points => [...points, [longitude, latitude]]); wb.dispatch({ type: 'status', value: `已添加 ${drawPoints.length + 1} 个形状点，请选择终点` }); }
    if (wb.tool === 'split' && operation.length && !isNode(operation[0])) {
      const edge = operation[0] as GeoFeature<LineGeometry, EdgeProperties>;
      const preview = await wb.runGraphCommand<{ recommended_node?: unknown }>('/api/split-source-preview', { edge: edge.properties.id, longitude, latitude });
      if (preview && window.confirm('确认在此位置切分来源边？')) await wb.runGraphCommand('/api/split-source-confirm', { edge: edge.properties.id, longitude, latitude, osm_node_id: preview.recommended_node ?? null });
      finishOperation();
    }
  }, [wb, operation, drawPoints.length, finishOperation]);

  if (!state) return <main className="loading-screen">{wb.error || '正在载入工作台…'}</main>;
  return <>
    <Header /><ToolDock />
    {state.flight_mode && <nav className="main-tabs" aria-label="航班主视图"><button className={wb.view === 'map' ? 'active' : ''} onClick={() => wb.dispatch({ type: 'view', value: 'map' })}>地图</button><button className={wb.view === 'flights' ? 'active' : ''} onClick={() => wb.dispatch({ type: 'view', value: 'flights' })}>航班</button>{detail && <button className={wb.view === 'observations' ? 'active' : ''} onClick={() => wb.dispatch({ type: 'view', value: 'observations' })}>观测记录</button>}</nav>}
    <main className="workspace react-workspace">
      <section className={`main-view map-view ${wb.view !== 'map' ? 'hidden' : ''}`}><MapView state={state} flights={wb.mapFlights} splitValidation={splitValidation} onFeature={handleFeature} onMapClick={handleMapClick} /><div className="map-overlay-stack"><div className="legend panel"><span>节点</span><span>派生边</span><span>虚线＝原始轨迹</span><span>实线＝匹配路径</span></div>{state.capabilities.can_edit_graph && <button className="secondary-button panel" onClick={() => setSplitValidation(value => !value)}>{splitValidation ? '关闭' : '开启'}相邻边辨色</button>}</div></section>
      {state.flight_mode && wb.view === 'flights' && <FlightPanel onDetail={setDetail} />}
      {state.flight_mode && wb.view === 'observations' && <ObservationView detail={detail} />}
    </main>
    <SearchPanel /><TopologyPanel /><FeatureDetails />
    <div className="status panel">{wb.error || wb.status}</div>{wb.busy && <div className="busy"><span /></div>}
  </>;
}

export function App() { return <WorkbenchProvider><Workspace /></WorkbenchProvider>; }
