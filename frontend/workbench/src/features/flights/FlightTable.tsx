import { useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';

interface FlightRow {
  flight_key: string;
  flight_id: string;
  flight_number?: string;
  movement_type: string;
  point_count: number;
  start_time?: string;
  selected: boolean;
  onMap: boolean;
  result: { status: string };
}
interface FlightController {
  snapshot(): FlightRow[];
  select(key: string, checked: boolean): void;
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
function FlightTable() {
  const items = useSyncExternalStore(subscribe, () => rows);
  const controller = window.workbenchFlights;
  return <table className="sheet-table">
    <thead><tr><th>选择</th><th>航班</th><th>进出港</th><th>状态</th><th>观测点</th><th>开始时间 <small>UTC</small></th><th>操作</th></tr></thead>
    <tbody>{items.map(item => <tr key={item.flight_key}>
      <td><input type="checkbox" aria-label={`选择航班 ${item.flight_id}`} checked={item.selected} onChange={event => controller.select(item.flight_key, event.target.checked)} /></td>
      <td><strong>{item.flight_number || item.flight_id}</strong><small>{item.flight_id}</small></td>
      <td>{item.movement_type === 'arrival' ? '进港' : item.movement_type === 'departure' ? '离港' : '未知'}</td>
      <td><span className={`flight-status ${item.result.status}`}>{labels[item.result.status] || item.result.status}</span></td>
      <td>{item.point_count}</td><td>{item.start_time?.replace('T', ' ').replace(/\+00:00$/, '')}</td>
      <td><button className="secondary-button" onClick={() => controller.detail(item.flight_key)}>详情</button><button className="secondary-button" onClick={() => controller.toggleMap(item.flight_key)}>{item.onMap ? '移出地图' : '加入地图'}</button><button className="secondary-button" disabled={!item.onMap} onClick={() => controller.focus(item.flight_key)}>定位</button></td>
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
