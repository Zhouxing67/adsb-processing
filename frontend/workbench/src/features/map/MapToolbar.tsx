import { useSyncExternalStore } from 'react';
import { Button, ConfigProvider, Menu, Space } from 'antd';

interface MapState {
  ready: boolean; canEdit: boolean; editing: boolean; canUndo: boolean; canFinish: boolean;
  mode: string; nodeCount: number; edgeCount: number; flightCount: number;
}
interface MapController {
  snapshot(): MapState;
  setTool(mode: string): void;
  save(): Promise<void>; undo(): Promise<void>; finish(): Promise<void>;
  search(): void; topology(): void; toggleEditing(): void;
}
declare global { interface Window { workbenchMap: MapController } }
let snapshot: MapState;
const listeners = new Set<() => void>();
function refresh() {
  snapshot = window.workbenchMap.snapshot();
  listeners.forEach(listener => listener());
}
function subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }
export function initializeMapState() {
  refresh();
  window.addEventListener('map-controller-changed', refresh);
  return () => { window.removeEventListener('map-controller-changed', refresh); listeners.clear(); };
}
export function useMapState() { return useSyncExternalStore(subscribe, () => snapshot); }
const tools = [
  { key: 'inspect', label: '查看', symbol: '⌖' },
  { key: 'split', label: '补充分割点', symbol: '⊥' },
  { key: 'draw', label: '直接绘制连接', symbol: '＋' },
  { key: 'restore', label: '恢复来源连接', symbol: '⌁' },
  { key: 'merge', label: '合并重合节点', symbol: '⋈' },
  { key: 'snap', label: '人工吸附到边', symbol: '↦' },
  { key: 'delete', label: '删除 / 简化', symbol: '−' },
];
function ToolIcon({ kind }: { kind: 'search' | 'topology' }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
    {kind === 'search' ? <><circle cx="10" cy="10" r="7" /><path d="m15 15 6 6" /></> : <><path d="M8 6h8M6 8v8m12-8v8M8 18h8" /><path d="M3 3h5v5H3zM16 3h5v5h-5zM3 16h5v5H3zM16 16h5v5h-5z" /></>}
  </svg>;
}
export function MapToolbar({ dock = false, mapTools = false }: { dock?: boolean; mapTools?: boolean }) {
  const state = useMapState();
  const commands = window.workbenchMap;
  return <ConfigProvider theme={{ token: { colorPrimary: '#2563eb', borderRadius: 5, fontSize: 13, fontFamily: 'Segoe UI, Microsoft YaHei, sans-serif' } }}>
    {dock ? <Menu selectedKeys={[state.mode]} items={tools.flatMap((tool, index) => [
      ...([1, 4, 6].includes(index) ? [{ type: 'divider' as const, key: `divider-${index}` }] : []),
      { key: tool.key, label: tool.label, danger: tool.key === 'delete', icon: <span className="studio-tool-icon" aria-hidden="true">{tool.symbol}</span> },
    ])} onClick={({ key }) => commands.setTool(key)} /> : mapTools ? <Space size={4}>
      <Button className="studio-icon-button" aria-label="搜索" title="搜索图要素" onClick={() => commands.search()}><ToolIcon kind="search" /></Button>
      <Button className="studio-icon-button" aria-label="拓扑检查" title="拓扑检查" onClick={() => commands.topology()}><ToolIcon kind="topology" /></Button>
      {state.canEdit && <Button className="edit-graph-button" aria-pressed={state.editing} onClick={() => commands.toggleEditing()}>{state.editing ? '退出编辑' : '编辑图'}</Button>}
    </Space> : state.canEdit && state.editing ? <Space size={4}>
      <Button type="text" disabled={!state.canUndo} onClick={() => void commands.undo()}>撤销</Button>
      <Button type="primary" onClick={() => void commands.save()}>保存</Button>
      {state.canFinish && <Button type="primary" onClick={() => void commands.finish()}>完成</Button>}
    </Space> : null}
  </ConfigProvider>;
}
