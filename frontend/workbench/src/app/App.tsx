import { useEffect, useMemo, useState } from 'react';
import { WorkbenchProvider, useWorkbench } from './WorkbenchContext';
import type { EditorTool } from './WorkbenchContext';
import type { FlightDetail, GeoFeature, NodeProperties, PointGeometry, SelectedFeature, WorkbenchState } from '../api/types';
import { FlightPanel } from '../features/flights/FlightPanel';
import { MapView } from '../features/map/MapView';
import { GraphDialog } from '../features/graph-editor/GraphDialog';
import { useGraphEditorMachine } from '../features/graph-editor/useGraphEditorMachine';
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
function edgeLabel(id: { u: string; v: string; key: number }) { return `${id.u}—${id.v} · ${id.key}`; }

interface LayerSettings { base: 'none' | 'osm' | 'satellite'; edges: boolean; parking: boolean; nodes: boolean }

function Header({ editing, leftOpen, rightOpen, onLeft, onRight }: { editing: boolean; leftOpen: boolean; rightOpen: boolean; onLeft(): void; onRight(): void }) {
  const wb = useWorkbench(), state = wb.state;
  const command = async (path: '/api/undo' | '/api/save' | '/api/finish') => { await wb.runGraphCommand(path); };
  return <header className="topbar panel">
    <button className="rail-toggle" aria-label="切换左侧栏" aria-expanded={leftOpen} onClick={onLeft}>◫</button>
    <div className="brand-mark">AW</div><div className="brand-copy"><strong>Airport Workbench</strong><span>{state ? `${state.node_count} 节点 · ${state.edge_count} 边${state.flight_mode ? ` · ${state.flight_count} 航班` : ''}` : '载入中…'}</span></div>
    <div className="top-actions">
      {state?.capabilities.can_edit_graph && editing && <><button className="text-button" disabled={!state.can_undo} onClick={() => void command('/api/undo')}>撤销</button><button className="save-button" onClick={() => void command('/api/save')}>保存</button>{state.can_finish && <button className="finish-button" onClick={() => void command('/api/finish')}>完成</button>}</>}
    </div>
    <button className="rail-toggle" aria-label="切换右侧栏" aria-expanded={rightOpen} onClick={onRight}>◧</button>
  </header>;
}

function MapToolbar({ editing, onEditing }: { editing: boolean; onEditing(): void }) {
  const wb = useWorkbench();
  return <div className="map-tools panel"><button aria-label="搜索" title="搜索图要素" onClick={() => wb.dispatch({ type: 'panel', panel: 'searchOpen', value: !wb.searchOpen })}>⌕</button><button aria-label="拓扑检查" title="拓扑检查" onClick={() => wb.dispatch({ type: 'panel', panel: 'topologyOpen', value: !wb.topologyOpen })}>◇</button>{wb.state?.capabilities.can_edit_graph && <button className={editing ? 'active' : ''} aria-pressed={editing} onClick={onEditing}>{editing ? '退出编辑' : '编辑图'}</button>}</div>;
}

function Inspector({ state, layers, onLayers }: { state: WorkbenchState; layers: LayerSettings; onLayers(value: LayerSettings): void }) {
  const parking = state.edges.features.filter(item => item.properties.aeroway === 'parking_position').length;
  const derived = state.edges.features.length - parking;
  return <aside className="studio-inspector"><div className="inspector-inner"><h1>机场地面网络</h1><div className="studio-metrics"><div><strong>{state.node_count}</strong><span>节点</span></div><div><strong>{state.edge_count}</strong><span>边</span></div>{state.flight_mode && <div><strong>{state.flight_count}</strong><span>航班</span></div>}</div><section><h3>图层与底图</h3><div className="layer-options"><label><input type="radio" name="base-layer" checked={layers.base === 'osm'} onChange={() => onLayers({ ...layers, base: 'osm' })} />OpenStreetMap</label><label><input type="radio" name="base-layer" checked={layers.base === 'satellite'} onChange={() => onLayers({ ...layers, base: 'satellite' })} />ESRI 卫星</label><label><input type="radio" name="base-layer" checked={layers.base === 'none'} onChange={() => onLayers({ ...layers, base: 'none' })} />无底图（精细编辑）</label><hr /><label><input type="checkbox" checked={layers.edges} onChange={event => onLayers({ ...layers, edges: event.target.checked })} />派生边（{derived}）</label><label><input type="checkbox" checked={layers.parking} onChange={event => onLayers({ ...layers, parking: event.target.checked })} />停机位（{parking}）</label><label><input type="checkbox" checked={layers.nodes} onChange={event => onLayers({ ...layers, nodes: event.target.checked })} />图节点（{state.node_count}）</label></div></section><section><h3>地图图例</h3><div className="inspector-legend"><span><i className="legend-dot" />普通节点</span><span><i className="legend-line parking" />停机位</span><span><i className="legend-badge">R</i>跑道接口</span><span><i className="legend-line derived" />派生边</span><span><i className="legend-line flight" />虚线＝原始轨迹</span><span><i className="legend-line path" />实线＝匹配路径</span></div></section><section className="inspector-empty"><div>⌖</div><h3>选择一个图要素</h3></section></div></aside>;
}

function ToolDock() {
  const wb = useWorkbench();
  if (!wb.state?.capabilities.can_edit_graph) return null;
  return <nav className="tool-dock panel react-tool-dock" aria-label="编辑工具"><div className="dock-title">编辑工具</div>{tools.map(tool => <button key={tool.key} className={`tool ${wb.tool === tool.key ? 'active' : ''} ${tool.key === 'delete' ? 'danger' : ''}`} onClick={() => { wb.dispatch({ type: 'tool', value: tool.key }); wb.dispatch({ type: 'status', value: toolMessages[tool.key] }); }}><span>{tool.symbol}</span><em>{tool.label}</em></button>)}</nav>;
}

function TopologyPanel({ splitValidation, onSplitValidation }: { splitValidation: boolean; onSplitValidation(): void }) {
  const wb = useWorkbench(), topology = wb.state?.topology;
  const [reviewIndex, setReviewIndex] = useState(-1);
  const nodes = useMemo(() => [...(wb.state?.nodes.features ?? [])].sort((a, b) => a.properties.id.localeCompare(b.properties.id)), [wb.state?.topology_revision]);
  const showReview = (index: number) => { const feature = nodes[index]; if (!feature) return; setReviewIndex(index); wb.dispatch({ type: 'selected', value: feature }); wb.dispatch({ type: 'status', value: index === nodes.length - 1 ? '已到最后一个节点；这不表示全部复核通过' : `遍历位置 ${index + 1} / ${nodes.length} · 节点 ${feature.properties.id}` }); };
  if (!wb.topologyOpen || !topology) return null;
  const metrics = [['连通分量', topology.component_count], ['最大分量', topology.largest_component], ['孤立节点', topology.isolated_count], ['悬挂节点', topology.dangling_count], ['平行边组', topology.parallel_pair_count]];
  return <aside className="topology-panel panel">
    <div className="panel-heading"><h2>拓扑概览</h2><button className="panel-close" onClick={() => wb.dispatch({ type: 'panel', panel: 'topologyOpen', value: false })}>×</button></div>
    <div className="metric-grid">{metrics.map(([label, value]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>
    <button className="secondary-button topology-validation" onClick={onSplitValidation}>{splitValidation ? '关闭' : '开启'}相邻边辨色</button>
    <div className="topology-details">
      <h3>孤立节点</h3><p>{topology.isolated_nodes.slice(0, 20).join('、') || '无'}</p>
      <h3>悬挂节点</h3><p>{topology.dangling_nodes.slice(0, 20).join('、') || '无'}</p>
      <h3>分量</h3>{topology.components.slice(0, 20).map(component => <button className="secondary-button" key={component.index} onClick={() => { const node = wb.state?.nodes.features.find(item => component.node_ids.includes(item.properties.id)); if (node) wb.dispatch({ type: 'selected', value: node }); }}>分量 {component.index} · {component.size} 节点</button>)}
    </div>
    <section className="node-review"><h3>逐点检查</h3><p className="field-note">{reviewIndex >= 0 ? `遍历位置 ${reviewIndex + 1} / ${nodes.length} · 节点 ${nodes[reviewIndex]?.properties.id}` : '尚未开始'}</p><div className="node-review-actions"><button disabled={!nodes.length} onClick={() => showReview(0)}>开始</button><button disabled={reviewIndex <= 0} onClick={() => showReview(reviewIndex - 1)}>上一个</button><button disabled={reviewIndex < 0 || reviewIndex >= nodes.length - 1} onClick={() => showReview(reviewIndex + 1)}>下一个</button><button disabled={reviewIndex < 0} onClick={() => { setReviewIndex(-1); wb.dispatch({ type: 'selected', value: null }); }}>结束</button></div></section>
  </aside>;
}

function SearchPanel() {
  const wb = useWorkbench(); const [query, setQuery] = useState(''), [stand, setStand] = useState(''), [edgeU, setEdgeU] = useState(''), [edgeV, setEdgeV] = useState('');
  if (!wb.searchOpen || !wb.state) return null;
  const select = (feature: SelectedFeature | undefined, label: string) => { if (feature) wb.dispatch({ type: 'selected', value: feature }); else wb.dispatch({ type: 'status', value: `未找到 ${label}` }); };
  const search = () => { const needle = query.trim().toLocaleLowerCase(); select(wb.state!.nodes.features.find(item => item.properties.id.toLocaleLowerCase().includes(needle)) ?? wb.state!.edges.features.find(item => edgeLabel(item.properties.id).toLocaleLowerCase().includes(needle)), query); };
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
  return <aside className="details panel"><button className="panel-close" onClick={() => wb.dispatch({ type: 'selected', value: null })}>×</button><div className="details-content"><small>{node ? '节点' : '边'}</small><h2>{node ? feature.properties.id : edgeLabel(feature.properties.id)}</h2><dl>{Object.entries(feature.properties).filter(([key]) => !['editable_attributes', 'id'].includes(key)).slice(0, 12).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value ?? '—')}</dd></div>)}</dl>{wb.state?.capabilities.can_edit_graph && <div className="property-form"><label>aeroway<input value={aeroway} onChange={event => setAeroway(event.target.value)} /></label><label>name<input value={name} onChange={event => setName(event.target.value)} /></label><label>ref<input value={ref} onChange={event => setRef(event.target.value)} /></label><button className="primary-button" onClick={() => void save()}>保存属性</button></div>}</div></aside>;
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
  const [splitValidation, setSplitValidation] = useState(false);
  const [graphEditing, setGraphEditing] = useState(false);
  const [leftOpen, setLeftOpen] = useState(true), [rightOpen, setRightOpen] = useState(true);
  const [layers, setLayers] = useState<LayerSettings>({ base: 'none', edges: true, parking: true, nodes: false });
  const editor = useGraphEditorMachine();
  useEffect(() => {
    document.body.classList.add('unified-workbench', 'react-workbench');
    document.body.classList.toggle('flight-mode', Boolean(state?.flight_mode));
    document.body.classList.toggle('read-only', Boolean(state?.flight_mode));
    return () => document.body.classList.remove('unified-workbench', 'react-workbench', 'flight-mode', 'read-only');
  }, [state?.flight_mode]);

  if (!state) return <main className="loading-screen">{wb.error || '正在载入工作台…'}</main>;
  const editorLeft = !state.flight_mode && leftOpen && (graphEditing || wb.topologyOpen);
  const shellLeft = leftOpen && (state.flight_mode || editorLeft);
  const rightContent = editor.dialog
    ? <GraphDialog dialog={editor.dialog} onClose={editor.reset} onPreview={editor.setPreviewGeometry} onConfirm={editor.confirmDialog} onMergeCandidate={editor.previewMerge} />
    : wb.selected && wb.detailsOpen ? <FeatureDetails /> : <Inspector state={state} layers={layers} onLayers={setLayers} />;
  const toggleEditing = () => { const next = !graphEditing; setGraphEditing(next); if (next) setLeftOpen(true); else { wb.dispatch({ type: 'tool', value: 'inspect' }); editor.reset(); } };
  return <div className={`app-shell ${state.flight_mode ? 'flight-shell' : ''} ${shellLeft ? 'with-left-rail' : ''} ${rightOpen ? 'with-right-rail' : ''}`}>
    <Header editing={graphEditing} leftOpen={leftOpen} rightOpen={rightOpen} onLeft={() => setLeftOpen(value => !value)} onRight={() => setRightOpen(value => !value)} />
    {editorLeft && (wb.topologyOpen ? <TopologyPanel splitValidation={splitValidation} onSplitValidation={() => setSplitValidation(value => !value)} /> : <ToolDock />)}
    {state.flight_mode && <nav className="main-tabs" aria-label="航班主视图"><button className={wb.view === 'map' ? 'active' : ''} onClick={() => wb.dispatch({ type: 'view', value: 'map' })}>地图</button><button className={wb.view === 'flights' ? 'active' : ''} onClick={() => wb.dispatch({ type: 'view', value: 'flights' })}>航班</button>{detail && <button className={wb.view === 'observations' ? 'active' : ''} onClick={() => wb.dispatch({ type: 'view', value: 'observations' })}>观测记录</button>}</nav>}
    <main className="workspace react-workspace">
      <section className={`main-view map-view ${wb.view !== 'map' ? 'hidden' : ''}`}><MapView state={state} flights={wb.mapFlights} splitValidation={splitValidation} baseLayer={layers.base} showEdges={layers.edges} showParking={layers.parking} showNodes={layers.nodes} selected={[...editor.selection, ...(wb.selected ? [wb.selected] : [])]} drawPoints={editor.drawPoints} previewGeometry={editor.previewGeometry} focusFlightKey={wb.mapFocusKey} fitMapVersion={wb.fitMapVersion} observationLocation={wb.observationLocation} onFeature={editor.handleFeature} onMapClick={editor.handleMapClick} /><MapToolbar editing={graphEditing} onEditing={toggleEditing} /><div className="map-overlay-stack">{wb.tool === 'merge' && <><button className="secondary-button panel" onClick={() => void editor.openMergeCandidates()}>重复节点候选</button><button className="primary-button panel" disabled={editor.mergeNodeIds.length < 2} onClick={() => void editor.previewMerge(editor.mergeNodeIds, state.revision)}>检查并合并（{editor.mergeNodeIds.length}）</button><button className="secondary-button panel" onClick={editor.reset}>清空选择</button></>}{wb.tool === 'draw' && editor.selection.length > 0 && <button className="secondary-button panel" onClick={editor.undoDrawPoint}>撤销形状点</button>}</div></section>
      {state.flight_mode && <FlightPanel active={wb.view === 'flights'} onDetail={setDetail} />}
      {state.flight_mode && wb.view === 'observations' && <ObservationView detail={detail} />}
    </main>
    <SearchPanel />{rightOpen && <div className="right-rail">{rightContent}</div>}
    <div className="status panel">{wb.error || wb.status}</div>{wb.busy && <div className="busy"><span /></div>}
  </div>;
}

export function App() { return <WorkbenchProvider><Workspace /></WorkbenchProvider>; }
