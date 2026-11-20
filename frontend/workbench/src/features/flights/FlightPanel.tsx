import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type * as React from 'react';
import { ApiError, api } from '../../api/client';
import type { FlightCatalogue, FlightDetail, FlightItem, MapFlightEntry, MatchStatus } from '../../api/types';
import { useWorkbench } from '../../app/WorkbenchContext';

const statusLabels: Record<string, string> = { unmatched: '未匹配', queued: '排队中', matching: '匹配中', success: '成功', failed: '失败', stale: '已失效' };
const colors = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#B77900', '#56B4E9', '#E69F00', '#6A3D9A', '#1B9E77', '#E7298A'];
const storageKey = `airport-flight-workbench:${new URLSearchParams(location.search).get('session') || 'default'}`;
interface Filters { query: string; movement: string; status: string; minimum: number; maximum: number | null; stands: string[]; start: string; end: string; validation: boolean }
interface StoredDisplay { key: string; label: string; slot: number; trajectoryVisible: boolean; pathVisible: boolean }
interface StoredState { filters?: Partial<Filters>; page?: number; matchSelection?: string[]; displayed?: StoredDisplay[] }
const defaults: Filters = { query: '', movement: '', status: '', minimum: 0, maximum: null, stands: [], start: '', end: '', validation: false };
function stored(): StoredState { try { return JSON.parse(sessionStorage.getItem(storageKey) || '{}'); } catch { return {}; } }
function paramsFor(filters: Filters, page?: number) {
  const params = new URLSearchParams({ min_points: String(filters.minimum) });
  if (page !== undefined) { params.set('page', String(page)); params.set('page_size', '15'); }
  if (filters.query) params.set('q', filters.query);
  if (filters.movement) params.set('movement_type', filters.movement);
  if (filters.status) params.set('match_status', filters.status);
  if (filters.maximum !== null) params.set('max_points', String(filters.maximum));
  filters.stands.forEach(stand => params.append('stands', stand));
  if (filters.start) params.set('start_date', filters.start);
  if (filters.end) params.set('end_date', filters.end);
  if (filters.validation) params.set('validation_only', 'true');
  return params;
}

export function FlightPanel({ onDetail, active = true }: { onDetail(detail: FlightDetail): void; active?: boolean }) {
  const wb = useWorkbench(), saved = useMemo(stored, []);
  const initialFilters = useMemo(() => ({ ...defaults, ...saved.filters, stands: saved.filters?.stands ?? [] }), [saved]);
  const [draft, setDraft] = useState<Filters>(initialFilters), [filters, setFilters] = useState<Filters>(initialFilters);
  const [catalogue, setCatalogue] = useState<FlightCatalogue | null>(null);
  const [page, setPage] = useState(Number.isInteger(saved.page) && saved.page! > 0 ? saved.page! : 1);
  const [pageDraft, setPageDraft] = useState(String(page));
  const [standSearch, setStandSearch] = useState('');
  const [loading, setLoading] = useState(false), [error, setError] = useState(''), [pageError, setPageError] = useState('');
  const [progress, setProgress] = useState<MatchStatus['progress'] | null>(null);
  const [tracking, setTracking] = useState(false);
  const restored = useRef(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError('');
    try {
      const value = await api.catalogue(paramsFor(filters, page), signal);
      setCatalogue(value); setPage(value.page || 1); setPageDraft(String(value.page || 1));
      if (draft.maximum === null) setDraft(current => ({ ...current, maximum: value.dataset_max_points }));
      return value;
    } catch (failure) {
      if ((failure as Error).name !== 'AbortError') {
        if (failure instanceof ApiError && failure.detail?.context?.total_pages !== undefined) setPage(Math.max(1, Number(failure.detail.context.total_pages)));
        else setError(failure instanceof Error ? failure.message : '航班目录加载失败');
      }
      return null;
    } finally { setLoading(false); }
  }, [filters, page, draft.maximum]);
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);

  const persist = useCallback(() => {
    const displayed = [...wb.mapFlights].map(([key, entry]) => ({ key, label: entry.label, slot: entry.slot, trajectoryVisible: entry.trajectoryVisible, pathVisible: entry.pathVisible }));
    sessionStorage.setItem(storageKey, JSON.stringify({ filters, page, matchSelection: [...wb.matchSelection], displayed }));
  }, [filters, page, wb.mapFlights, wb.matchSelection]);
  useEffect(() => { persist(); }, [persist]);
  useEffect(() => {
    if (restored.current) return; restored.current = true;
    void (async () => {
      const valid = new Set((await api.filteredFlights(new URLSearchParams())).flight_keys);
      wb.dispatch({ type: 'set-match-selection', keys: [...wb.matchSelection].filter(key => valid.has(key)) });
      for (const item of saved.displayed ?? []) if (valid.has(item.key)) {
        try { wb.dispatch({ type: 'map-flight', key: item.key, value: { geometry: await api.geometry(item.key), label: item.label, slot: item.slot, trajectoryVisible: item.trajectoryVisible, pathVisible: item.pathVisible } }); } catch { /* stale saved selection */ }
      }
      const status = await api.matchStatus(); setProgress(status.progress); if (!status.progress.complete) setTracking(true);
    })().catch(failure => setError(failure instanceof Error ? failure.message : '会话恢复失败'));
  }, [saved.displayed, wb]);

  useEffect(() => {
    if (!tracking) return;
    const poll = window.setInterval(async () => {
      try {
        const status = await api.matchStatus(); setProgress(status.progress);
        for (const task of status.tasks) for (const result of task.items) if (wb.mapFlights.has(result.flight_key)) {
          const previous = wb.mapFlights.get(result.flight_key)!;
          if (previous.geometry.match.status !== result.status || previous.geometry.match.graph_id !== result.graph_id) wb.dispatch({ type: 'map-flight', key: result.flight_key, value: { ...previous, geometry: await api.geometry(result.flight_key) } });
        }
        if (status.progress.complete) { setTracking(false); await load(); }
      } catch (failure) { setError(failure instanceof Error ? failure.message : '任务状态读取失败'); }
    }, 1000);
    return () => window.clearInterval(poll);
  }, [tracking, load, wb]);

  const validateAndApply = () => {
    if (!Number.isSafeInteger(draft.minimum) || draft.minimum < 0 || draft.maximum === null || !Number.isSafeInteger(draft.maximum) || draft.maximum < 0) return setError('观测点数必须是非负整数');
    if (draft.minimum > draft.maximum) return setError('最小观测点数不得大于最大观测点数');
    if (catalogue && draft.maximum > catalogue.dataset_max_points) return setError(`最大观测点数不得超过 ${catalogue.dataset_max_points}`);
    if (draft.start && draft.end && draft.start > draft.end) return setError('起始日期不得晚于终止日期');
    setError(''); setFilters({ ...draft }); setPage(1);
  };
  const nextSlot = () => { const used = new Set([...wb.mapFlights.values()].map(entry => entry.slot)); let slot = 0; while (used.has(slot)) slot += 1; return slot; };
  const toggleMap = async (item: FlightItem) => {
    if (wb.mapFlights.has(item.flight_key)) return wb.dispatch({ type: 'map-flight', key: item.flight_key, value: null });
    try { wb.dispatch({ type: 'map-flight', key: item.flight_key, value: { geometry: await api.geometry(item.flight_key), label: item.flight_id, slot: nextSlot(), trajectoryVisible: true, pathVisible: true } }); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '轨迹加载失败'); }
  };
  const addSelectedToMap = async () => {
    const used = new Set([...wb.mapFlights.values()].map(entry => entry.slot));
    const allocate = () => { let slot = 0; while (used.has(slot)) slot += 1; used.add(slot); return slot; };
    const capacity = Math.max(0, (catalogue?.max_map_flights ?? wb.matchSelection.size) - wb.mapFlights.size);
    const pending = [...wb.matchSelection].filter(key => !wb.mapFlights.has(key));
    if (pending.length > capacity) setError(`地图最多同时展示 ${catalogue?.max_map_flights} 条航班，本次仅加入前 ${capacity} 条`);
    for (const key of pending.slice(0, capacity)) {
      if (wb.mapFlights.has(key)) continue;
      const item = catalogue?.items.find(row => row.flight_key === key);
      try {
        const [geometry, label] = await Promise.all([api.geometry(key), item ? Promise.resolve(item.flight_id) : api.detail(key).then(value => value.summary.flight_id)]);
        wb.dispatch({ type: 'map-flight', key, value: { geometry, label, slot: allocate(), trajectoryVisible: true, pathVisible: true } });
      } catch (failure) { setError(failure instanceof Error ? failure.message : '批量轨迹加载失败'); }
    }
  };
  const updateMapEntry = (key: string, patch: Partial<MapFlightEntry>) => { const entry = wb.mapFlights.get(key); if (entry) wb.dispatch({ type: 'map-flight', key, value: { ...entry, ...patch } }); };
  const showDetail = async (item: FlightItem) => { try { onDetail(await api.detail(item.flight_key)); wb.dispatch({ type: 'view', value: 'observations' }); } catch (failure) { setError(failure instanceof Error ? failure.message : '详情加载失败'); } };
  const editStand = async (item: FlightItem) => { const value = window.prompt('输入机位，留空可清除', item.stand_position ?? ''); if (value === null) return; try { await api.updateStand(item.flight_key, value.trim() || null); await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : '机位保存失败'); } };
  const selectFiltered = async () => { try { const result = await api.filteredFlights(paramsFor(filters)); wb.dispatch({ type: 'set-match-selection', keys: [...new Set([...wb.matchSelection, ...result.flight_keys])] }); wb.dispatch({ type: 'status', value: `已按当前筛选固定选择 ${result.count} 条航班` }); } catch (failure) { setError(failure instanceof Error ? failure.message : '选择失败'); } };
  const submit = async (keys = [...wb.matchSelection], force = false) => { if (!keys.length || !window.confirm(`确认提交 ${keys.length} 条航班进行匹配？`)) return; try { await api.submitMatches(keys, force); setTracking(true); await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : '任务提交失败'); } };
  const jump = () => { const value = Number(pageDraft); if (!Number.isSafeInteger(value) || value < 1 || !catalogue || value > catalogue.total_pages) return setPageError(`页码范围为 1～${catalogue?.total_pages ?? 1}`); setPageError(''); setPage(value); };
  const allPageSelected = useMemo(() => Boolean(catalogue?.items.length) && catalogue!.items.every(item => wb.matchSelection.has(item.flight_key)), [catalogue, wb.matchSelection]);
  const visibleStands = useMemo(() => ['', ...(catalogue?.stand_options ?? [])].filter(stand => (stand || '空机位').toLowerCase().includes(standSearch.toLowerCase())), [catalogue, standSearch]);

  return <section id="flight-sheet" className={`main-view flight-sheet ${active ? '' : 'catalogue-hidden'}`}>
    <header className="sheet-heading"><h2>航班</h2><span>{catalogue ? `第 ${catalogue.page || 0} / ${catalogue.total_pages} 页（${catalogue.total} 条）` : ''}</span></header>
    <div className="flight-query"><input value={draft.query} placeholder="航班号 / ID" onChange={event => setDraft({ ...draft, query: event.target.value })} onKeyDown={event => { if (event.key === 'Enter') validateAndApply(); }} />
      <div className="flight-filters"><select value={draft.movement} onChange={event => setDraft({ ...draft, movement: event.target.value })}><option value="">全部进出港</option><option value="arrival">进港</option><option value="departure">离港</option><option value="unknown">未知</option></select><select value={draft.status} onChange={event => setDraft({ ...draft, status: event.target.value })}><option value="">全部状态</option>{Object.entries(statusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><input type="number" min={0} aria-label="最小观测点数" value={draft.minimum} onChange={event => setDraft({ ...draft, minimum: Number(event.target.value) })} /><input type="number" min={0} aria-label="最大观测点数" value={draft.maximum ?? catalogue?.dataset_max_points ?? ''} onChange={event => setDraft({ ...draft, maximum: Number(event.target.value) })} /><input type="date" aria-label="起始日期" value={draft.start} onChange={event => setDraft({ ...draft, start: event.target.value })} /><input type="date" aria-label="结束日期" value={draft.end} onChange={event => setDraft({ ...draft, end: event.target.value })} /><button className="primary-button" onClick={validateAndApply}>过滤</button><button className="text-button" onClick={() => { const value = { ...defaults, maximum: catalogue?.dataset_max_points ?? null }; setDraft(value); setFilters(value); setPage(1); }}>重置</button></div>
      <details className="stand-picker"><summary className="secondary-button">机位{draft.stands.length ? `（${draft.stands.length}）` : ''}</summary><div className="stand-options-panel"><input type="search" aria-label="搜索机位" value={standSearch} onChange={event => setStandSearch(event.target.value)} />{visibleStands.map(stand => <label key={stand || '__empty'}><input type="checkbox" aria-label={stand || '空机位'} checked={draft.stands.includes(stand)} onChange={event => setDraft(value => ({ ...value, stands: event.target.checked ? [...value.stands, stand] : value.stands.filter(item => item !== stand) }))} />{stand || '空机位'}</label>)}</div></details>
      {catalogue?.supports_validation_filter && <label><input type="checkbox" checked={draft.validation} onChange={event => setDraft({ ...draft, validation: event.target.checked })} /> 验证航班（≥30 点）</label>}{error && <p className="field-error" role="alert">{error}</p>}</div>
    <div className="sheet-batch-tools"><label><input type="checkbox" aria-label="选择本页航班" checked={allPageSelected} onChange={event => catalogue?.items.forEach(item => wb.dispatch({ type: 'toggle-match', key: item.flight_key, checked: event.target.checked }))} /> 本页</label><button className="secondary-button" onClick={() => void selectFiltered()}>选择全部结果</button><button className="text-button" onClick={() => wb.dispatch({ type: 'set-match-selection', keys: [] })}>清空</button><span>已选 {wb.matchSelection.size} 条</span><button className="secondary-button" onClick={() => void addSelectedToMap()}>所选加入地图</button><button className="primary-button" disabled={!wb.matchSelection.size || tracking} onClick={() => void submit()}>{tracking ? '匹配中…' : '匹配所选航班'}</button></div>
    {progress && <section className="match-progress"><strong>批量任务</strong><span>等待 {progress.waiting} · 运行 {progress.running} · 成功 {progress.success} · 失败 {progress.failed}</span></section>}
    <section className="selected-section map-selection"><div className="section-title"><strong>地图展示</strong></div><div className="selected-flights">{wb.mapFlights.size === 0 && <p className="field-note">尚无地图展示航班</p>}{[...wb.mapFlights].sort((a, b) => a[1].slot - b[1].slot).map(([key, entry]) => <div className="selected-chip" key={key} style={{ '--slot-color': colors[entry.slot % colors.length] } as React.CSSProperties}><b>{entry.slot + 1}</b><span>{entry.label}</span><label><input type="checkbox" checked={entry.trajectoryVisible} onChange={event => updateMapEntry(key, { trajectoryVisible: event.target.checked })} />轨迹</label><label><input type="checkbox" checked={entry.pathVisible} disabled={!entry.geometry.path} onChange={event => updateMapEntry(key, { pathVisible: event.target.checked })} />路径</label><button onClick={() => wb.dispatch({ type: 'focus-flight', key })}>⌖</button><button onClick={() => wb.dispatch({ type: 'map-flight', key, value: null })}>×</button></div>)}</div><div className="selection-actions"><button onClick={() => [...wb.mapFlights.keys()].forEach(key => wb.dispatch({ type: 'map-flight', key, value: null }))}>清空</button><button onClick={() => wb.dispatch({ type: 'fit-map-flights' })}>定位</button></div></section>
    <div className="sheet-table-scroll"><table className="sheet-table"><thead><tr><th>选择</th><th>航班</th><th>进出港</th><th>机位</th><th>状态</th><th>观测点</th><th>开始时间</th><th>操作</th></tr></thead><tbody>{catalogue?.items.map(item => <tr key={item.flight_key}><td><input type="checkbox" checked={wb.matchSelection.has(item.flight_key)} onChange={event => wb.dispatch({ type: 'toggle-match', key: item.flight_key, checked: event.target.checked })} /></td><td><strong>{item.flight_number || item.flight_id}</strong><small>{item.flight_id}</small></td><td>{item.movement_type === 'arrival' ? '进港' : item.movement_type === 'departure' ? '离港' : '未知'}</td><td className="stand-cell">{item.stand_position || '—'} {item.can_edit_stand && <button className="secondary-button" onClick={() => void editStand(item)}>编辑</button>}</td><td><span className={`flight-status ${item.match.status}`}>{statusLabels[item.match.status] || item.match.status}</span>{item.match.error && <small title={item.match.error}>{item.match.failure_type}</small>}</td><td>{item.point_count}</td><td>{item.start_time.replace('T', ' ').slice(0, 19)}</td><td><button className="secondary-button" onClick={() => void showDetail(item)}>详情</button><button className="secondary-button" onClick={() => void toggleMap(item)}>{wb.mapFlights.has(item.flight_key) ? '移出地图' : '加入地图'}</button>{wb.mapFlights.has(item.flight_key) && <button className="flight-locate-action" onClick={() => wb.dispatch({ type: 'focus-flight', key: item.flight_key })}>⌖ 定位</button>}{['failed', 'stale'].includes(item.match.status) && <button onClick={() => void submit([item.flight_key], true)}>重试</button>}</td></tr>)}</tbody></table>{loading && <div className="busy"><span /></div>}</div>
    <footer className="sheet-pagination"><button disabled={page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button><span>{catalogue ? `${catalogue.page || 0}/${catalogue.total_pages}` : '—'}</span><input type="number" min={1} value={pageDraft} aria-label="跳转页码" onChange={event => setPageDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') jump(); }} /><button onClick={jump}>跳转</button><button disabled={!catalogue || page >= catalogue.total_pages} onClick={() => setPage(value => value + 1)}>下一页</button>{pageError && <p className="field-error">{pageError}</p>}</footer>
  </section>;
}
