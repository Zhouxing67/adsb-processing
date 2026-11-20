import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';
import type { FlightCatalogue, FlightDetail, FlightItem } from '../../api/types';
import { useWorkbench } from '../../app/WorkbenchContext';

const statusLabels: Record<string, string> = { unmatched: '未匹配', queued: '排队中', matching: '匹配中', success: '成功', failed: '失败', stale: '已失效' };
interface Filters { query: string; movement: string; status: string; minimum: number; maximum: number | null; start: string; end: string; validation: boolean }
const initialFilters: Filters = { query: '', movement: '', status: '', minimum: 0, maximum: null, start: '', end: '', validation: false };

function catalogueParams(filters: Filters, page: number) {
  const params = new URLSearchParams({ page: String(page), page_size: '20', min_points: String(filters.minimum) });
  if (filters.query) params.set('q', filters.query);
  if (filters.movement) params.set('movement_type', filters.movement);
  if (filters.status) params.set('match_status', filters.status);
  if (filters.maximum !== null) params.set('max_points', String(filters.maximum));
  if (filters.start) params.set('start_date', filters.start);
  if (filters.end) params.set('end_date', filters.end);
  if (filters.validation) params.set('validation_only', 'true');
  return params;
}

export function FlightPanel({ onDetail }: { onDetail(detail: FlightDetail): void }) {
  const workbench = useWorkbench();
  const [draft, setDraft] = useState(initialFilters);
  const [filters, setFilters] = useState(initialFilters);
  const [catalogue, setCatalogue] = useState<FlightCatalogue | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [matching, setMatching] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError('');
    try {
      const value = await api.catalogue(catalogueParams(filters, page), signal);
      setCatalogue(value);
      if (draft.maximum === null) setDraft(value => ({ ...value, maximum: catalogue?.dataset_max_points ?? value.maximum }));
    } catch (failure) {
      if ((failure as Error).name !== 'AbortError') setError(failure instanceof Error ? failure.message : '航班目录加载失败');
    } finally { setLoading(false); }
  }, [filters, page, catalogue?.dataset_max_points]);
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);

  useEffect(() => {
    if (!matching) return;
    const poll = window.setInterval(async () => {
      try {
        const status = await api.matchStatus();
        const active = status.tasks.some(task => !task.complete);
        if (!active) { setMatching(false); await load(); }
      } catch (failure) { setError(failure instanceof Error ? failure.message : '任务状态读取失败'); }
    }, 1200);
    return () => window.clearInterval(poll);
  }, [matching, load]);

  const apply = () => {
    if (draft.maximum !== null && draft.minimum > draft.maximum) { setError('最小观测点数不得大于最大观测点数'); return; }
    if (draft.start && draft.end && draft.start > draft.end) { setError('起始日期不得晚于终止日期'); return; }
    setFilters({ ...draft }); setPage(1);
  };
  const toggleMap = async (item: FlightItem) => {
    if (workbench.mapFlights.has(item.flight_key)) { workbench.dispatch({ type: 'map-flight', key: item.flight_key, value: null }); return; }
    if (catalogue && workbench.mapFlights.size >= catalogue.max_map_flights) { setError(`地图最多展示 ${catalogue.max_map_flights} 条航班`); return; }
    try { workbench.dispatch({ type: 'map-flight', key: item.flight_key, value: await api.geometry(item.flight_key) }); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '轨迹加载失败'); }
  };
  const showDetail = async (item: FlightItem) => {
    try { onDetail(await api.detail(item.flight_key)); workbench.dispatch({ type: 'view', value: 'observations' }); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '详情加载失败'); }
  };
  const editStand = async (item: FlightItem) => {
    const value = window.prompt('输入机位，留空可清除', item.stand_position ?? '');
    if (value === null) return;
    try { await api.updateStand(item.flight_key, value.trim() || null); await load(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '机位保存失败'); }
  };
  const selectFiltered = async () => {
    try {
      const result = await api.filteredFlights(catalogueParams(filters, 1));
      workbench.dispatch({ type: 'set-match-selection', keys: result.flight_keys });
    } catch (failure) { setError(failure instanceof Error ? failure.message : '选择失败'); }
  };
  const submit = async () => {
    try { await api.submitMatches([...workbench.matchSelection]); setMatching(true); await load(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '任务提交失败'); }
  };
  const allPageSelected = useMemo(() => Boolean(catalogue?.items.length) && catalogue!.items.every(item => workbench.matchSelection.has(item.flight_key)), [catalogue, workbench.matchSelection]);

  return <section id="flight-sheet" className="main-view flight-sheet">
    <header className="sheet-heading"><h2>航班</h2><span>{catalogue ? `共 ${catalogue.total} 条` : ''}</span></header>
    <div className="flight-query">
      <input value={draft.query} placeholder="航班号 / ID" onChange={event => setDraft({ ...draft, query: event.target.value })} onKeyDown={event => { if (event.key === 'Enter') apply(); }} />
      <div className="flight-filters">
        <select value={draft.movement} onChange={event => setDraft({ ...draft, movement: event.target.value })}><option value="">全部进出港</option><option value="arrival">进港</option><option value="departure">离港</option></select>
        <select value={draft.status} onChange={event => setDraft({ ...draft, status: event.target.value })}><option value="">全部状态</option>{Object.entries(statusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
        <input type="number" min={0} aria-label="最小观测点数" value={draft.minimum} onChange={event => setDraft({ ...draft, minimum: Number(event.target.value) })} />
        <input type="number" min={0} aria-label="最大观测点数" value={draft.maximum ?? catalogue?.dataset_max_points ?? ''} onChange={event => setDraft({ ...draft, maximum: Number(event.target.value) })} />
        <input type="date" aria-label="起始日期" value={draft.start} onChange={event => setDraft({ ...draft, start: event.target.value })} />
        <input type="date" aria-label="结束日期" value={draft.end} onChange={event => setDraft({ ...draft, end: event.target.value })} />
        <button className="primary-button" onClick={apply}>过滤</button>
        <button className="text-button" onClick={() => { setDraft(initialFilters); setFilters(initialFilters); setPage(1); }}>重置</button>
      </div>
      {catalogue?.supports_validation_filter && <label><input type="checkbox" checked={draft.validation} onChange={event => setDraft({ ...draft, validation: event.target.checked })} /> 验证航班（≥30 点）</label>}
      {error && <p className="field-error" role="alert">{error}</p>}
    </div>
    <div className="sheet-batch-tools">
      <label><input type="checkbox" checked={allPageSelected} onChange={event => catalogue?.items.forEach(item => workbench.dispatch({ type: 'toggle-match', key: item.flight_key, checked: event.target.checked }))} /> 本页</label>
      <button className="secondary-button" onClick={() => void selectFiltered()}>选择全部结果</button>
      <button className="text-button" onClick={() => workbench.dispatch({ type: 'set-match-selection', keys: [] })}>清空</button>
      <span>已选 {workbench.matchSelection.size} 条</span>
      <button className="primary-button" disabled={!workbench.matchSelection.size || matching} onClick={() => void submit()}>{matching ? '匹配中…' : '匹配所选航班'}</button>
    </div>
    <div className="sheet-table-scroll"><table className="sheet-table"><thead><tr><th>选择</th><th>航班</th><th>进出港</th><th>机位</th><th>状态</th><th>观测点</th><th>开始时间</th><th>操作</th></tr></thead>
      <tbody>{catalogue?.items.map(item => <tr key={item.flight_key}>
        <td><input type="checkbox" checked={workbench.matchSelection.has(item.flight_key)} onChange={event => workbench.dispatch({ type: 'toggle-match', key: item.flight_key, checked: event.target.checked })} /></td>
        <td><strong>{item.flight_number || item.flight_id}</strong><small>{item.flight_id}</small></td><td>{item.movement_type === 'arrival' ? '进港' : item.movement_type === 'departure' ? '离港' : '未知'}</td>
        <td>{item.stand_position || '—'} {item.can_edit_stand && <button className="secondary-button" onClick={() => void editStand(item)}>编辑</button>}</td>
        <td><span className={`flight-status ${item.match.status}`}>{statusLabels[item.match.status] || item.match.status}</span></td><td>{item.point_count}</td><td>{item.start_time.replace('T', ' ').slice(0, 19)}</td>
        <td><button className="secondary-button" onClick={() => void showDetail(item)}>详情</button><button className="secondary-button" onClick={() => void toggleMap(item)}>{workbench.mapFlights.has(item.flight_key) ? '移出地图' : '加入地图'}</button></td>
      </tr>)}</tbody></table>{loading && <div className="busy"><span /></div>}</div>
    <footer className="sheet-pagination"><button disabled={page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button><span>{catalogue ? `${catalogue.page}/${catalogue.total_pages}` : '—'}</span><button disabled={!catalogue || page >= catalogue.total_pages} onClick={() => setPage(value => value + 1)}>下一页</button></footer>
  </section>;
}
