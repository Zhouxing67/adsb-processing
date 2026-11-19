import { useState, useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';

interface FlightRow {
  flight_key: string;
  flight_id: string;
  flight_number?: string;
  movement_type: string;
  point_count: number;
  stand_position?: string | null;
  can_edit_stand?: boolean;
  inconsistent_fields?: string[];
  start_time?: string;
  selected: boolean;
  onMap: boolean;
  result: { status: string };
}
interface FlightController {
  timezone(): string;
  snapshot(): FlightRow[];
  select(key: string, checked: boolean): void;
  saveStand(key: string, value: string): Promise<void>;
  detail(key: string): void;
  toggleMap(key: string): void;
  focus(key: string): void;
}
declare global { interface Window { workbenchFlights: FlightController } }
const labels: Record<string, string> = {
  unmatched: '未匹配', queued: '排队中', matching: '匹配中', success: '成功', failed: '失败', stale: '已失效',
};
let rows: FlightRow[] = [];
const listeners = new Set<() => void>();
function refresh() {
  rows = window.workbenchFlights.snapshot();
  listeners.forEach(listener => listener());
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
function StandCell({ item }: { item: FlightRow }) {
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const inconsistent = item.inconsistent_fields?.some(field => field.endsWith('_stand_position'));
  if (draft === null) return <>
    <span>{inconsistent ? '机位不一致' : item.stand_position || '—'}</span>
    {item.can_edit_stand && <button className="secondary-button" aria-label={`编辑机位 ${item.flight_id}`}
      onClick={() => setDraft(item.stand_position ?? '')}>编辑</button>}
  </>;
  return <form className="stand-editor" onSubmit={async event => {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError('');
    try {
      await window.workbenchFlights.saveStand(item.flight_key, draft);
      setDraft(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '机位保存失败');
    } finally {
      setSaving(false);
    }
  }}>
    <input autoFocus aria-label={`机位 ${item.flight_id}`} value={draft} placeholder="留空可清除" disabled={saving}
      onChange={event => setDraft(event.target.value)} />
    <button className="secondary-button" disabled={saving} type="submit">{saving ? '保存中' : '保存'}</button>
    <button className="secondary-button" disabled={saving} type="button"
      onClick={() => { setDraft(null); setError(''); }}>取消</button>
    {error && <p className="field-error" role="alert">{error}</p>}
  </form>;
}
function FlightTable() {
  const items = useSyncExternalStore(subscribe, () => rows);
  const controller = window.workbenchFlights;
  return <table className="sheet-table">
    <thead><tr><th>选择</th><th>航班</th><th>进出港</th><th>机位</th><th>状态</th><th>观测点</th><th>开始时间 <small>{controller.timezone()}</small></th><th>操作</th></tr></thead>
    <tbody>{items.map(item => <tr key={item.flight_key}>
      <td><input type="checkbox" aria-label={`选择航班 ${item.flight_id}`} checked={item.selected} onChange={event => controller.select(item.flight_key, event.target.checked)} /></td>
      <td><strong>{item.flight_id}</strong></td>
      <td>{item.movement_type === 'arrival' ? '进港' : item.movement_type === 'departure' ? '离港' : '未知'}</td>
      <td className="stand-cell"><StandCell item={item} /></td>
      <td><span className={`flight-status ${item.result.status}`}>{labels[item.result.status] || item.result.status}</span></td>
      <td>{item.point_count}</td><td>{item.start_time?.replace('T', ' ').replace(/(?:Z|[+-]\d{2}:\d{2})$/, '')}</td>
      <td><button className="secondary-button" onClick={() => controller.detail(item.flight_key)}>详情</button><button className="secondary-button" onClick={() => controller.toggleMap(item.flight_key)}>{item.onMap ? '移出地图' : '加入地图'}</button><button disabled={!item.onMap} onClick={() => controller.focus(item.flight_key)} className="flight-locate-action" title="在地图中突出显示此航班">⌖ 定位</button></td>
    </tr>)}</tbody>
  </table>;
}
export function mountFlightTable() {
  const element = document.getElementById('flight-table-root');
  if (!element) throw new Error('Flight table mount is missing');
  refresh();
  window.addEventListener('flight-table-changed', refresh);
  window.addEventListener('flight-selection-changed', refresh);
  const root = createRoot(element);
  root.render(<FlightTable />);
  return () => {
    window.removeEventListener('flight-table-changed', refresh);
    window.removeEventListener('flight-selection-changed', refresh);
    listeners.clear();
    root.unmount();
  };
}
