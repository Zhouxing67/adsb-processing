import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Modal } from 'antd';
import { ApiError, api } from '../../api/client';
import type { FlightCatalogueQuery } from '../../api/client';
import type { FlightCatalogue, FlightDetail, FlightItem, MatchStatus } from '../../api/types';
import { useWorkbench } from '../../app/WorkbenchContext';
import { StudioIcon } from '../layout/StudioIcon';
import { defaultFlightFilters, readStoredFlightState, writeStoredFlightState } from './storage';
import type { FlightFilters } from './storage';
import { useMatchPolling } from './useMatchPolling';

const statusLabels: Record<string, string> = {
  unmatched: '未匹配',
  queued: '排队中',
  matching: '匹配中',
  success: '成功',
  failed: '失败',
};

interface DraftFilters {
  query: string;
  movement: string;
  status: string;
  minimum: string;
  maximum: string;
  stands: string[];
  start: string;
  end: string;
  validation: boolean;
}

function toDraft(value: FlightFilters): DraftFilters {
  return {
    ...value,
    minimum: String(value.minimum),
    maximum: value.maximum === null ? '' : String(value.maximum),
  };
}

function paramsFor(filters: FlightFilters, page?: number): FlightCatalogueQuery {
  return {
    q: filters.query || undefined,
    movement_type: filters.movement || undefined,
    match_status: filters.status || undefined,
    min_points: filters.minimum,
    max_points: filters.maximum,
    stands: filters.stands,
    start_date: filters.start || undefined,
    end_date: filters.end || undefined,
    validation_only: filters.validation || undefined,
    page,
    page_size: page === undefined ? undefined : 15,
  };
}

interface FlightPanelProps {
  onDetail(detail: FlightDetail): void;
  active?: boolean;
  splitView?: boolean;
}

export function FlightPanel({ onDetail, active = true, splitView = false }: FlightPanelProps) {
  const wb = useWorkbench();
  const saved = useMemo(readStoredFlightState, []);
  const initialFilters = useMemo(
    () => ({ ...defaultFlightFilters, ...saved.filters, stands: saved.filters?.stands ?? [] }),
    [saved],
  );
  const [draft, setDraft] = useState<DraftFilters>(() => toDraft(initialFilters));
  const [filters, setFilters] = useState<FlightFilters>(initialFilters);
  const [catalogue, setCatalogue] = useState<FlightCatalogue | null>(null);
  const [page, setPage] = useState(Number.isInteger(saved.page) && saved.page! > 0 ? saved.page! : 1);
  const [pageDraft, setPageDraft] = useState(String(page));
  const [standSearch, setStandSearch] = useState('');
  const [standPickerOpen, setStandPickerOpen] = useState(false);
  const [editingStand, setEditingStand] = useState<{ key: string; value: string; above: boolean } | null>(null);
  const [standEditSearch, setStandEditSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [addingProgress, setAddingProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState('');
  const [pageError, setPageError] = useState('');
  const [progress, setProgress] = useState<MatchStatus['progress'] | null>(null);
  const [tracking, setTracking] = useState(false);
  const [allResultsIntent, setAllResultsIntent] = useState<boolean | null>(null);
  const [filteredKeys, setFilteredKeys] = useState<string[] | null>(null);

  const restored = useRef(false);
  const mounted = useRef(true);
  const addAbortRef = useRef<AbortController | null>(null);
  const toggleFilteredSeqRef = useRef(0);
  const standPicker = useRef<HTMLDetailsElement>(null);
  const standEditor = useRef<HTMLDivElement>(null);
  const tableScroll = useRef<HTMLDivElement>(null);
  const dispatch = wb.dispatch;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      addAbortRef.current?.abort();
    };
  }, []);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError('');
      try {
        const value = await api.catalogue(paramsFor(filters, page), signal);
        setCatalogue(value);
        setPage(value.page || 1);
        setPageDraft(String(value.page || 1));
        setDraft(current => (current.maximum === '' ? { ...current, maximum: String(value.dataset_max_points) } : current));
        return value;
      } catch (failure) {
        if ((failure as Error).name !== 'AbortError') {
          if (failure instanceof ApiError && failure.detail?.context?.total_pages !== undefined) {
            setPage(Math.max(1, Number(failure.detail.context.total_pages)));
          } else {
            setError(failure instanceof Error ? failure.message : '航班目录加载失败');
          }
        }
        return null;
      } finally {
        setLoading(false);
      }
    },
    [filters, page],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    setFilteredKeys(null);
  }, [filters]);

  useEffect(() => {
    const displayed = [...wb.mapFlights].map(([key, entry]) => ({
      key,
      label: entry.label,
      slot: entry.slot,
      trajectoryVisible: entry.trajectoryVisible,
      pathVisible: entry.pathVisible,
    }));
    writeStoredFlightState({ filters, page, matchSelection: [...wb.matchSelection], displayed });
  }, [filters, page, wb.mapFlights, wb.matchSelection]);

  useEffect(() => {
    const closePopovers = (event: PointerEvent) => {
      const target = event.target as Node;
      if (standPicker.current && !standPicker.current.contains(target)) setStandPickerOpen(false);
      if (standEditor.current && !standEditor.current.contains(target)) setEditingStand(null);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setStandPickerOpen(false);
        setEditingStand(null);
      }
    };
    document.addEventListener('pointerdown', closePopovers);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', closePopovers);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    void (async () => {
      const valid = new Set((await api.filteredFlights({})).flight_keys);
      dispatch({ type: 'prune-match-selection', keys: [...valid] });
      const displayed = (saved.displayed ?? []).filter(item => valid.has(item.key));
      const concurrency = 5;
      let cursor = 0;
      const restoredEntries: Array<{ key: string; value: import('../../api/types').MapFlightEntry }> = [];
      const worker = async () => {
        while (cursor < displayed.length && mounted.current) {
          const item = displayed[cursor++];
          try {
            const geometry = await api.geometry(item.key);
            if (!mounted.current) return;
            restoredEntries.push({
              key: item.key,
              value: {
                geometry,
                label: item.label || geometry.flight_id,
                slot: item.slot,
                trajectoryVisible: item.trajectoryVisible,
                pathVisible: item.pathVisible,
              },
            });
          } catch {
            /* stale saved selection */
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(concurrency, displayed.length) }, worker));
      if (mounted.current && restoredEntries.length) {
        dispatch({ type: 'map-flights-batch', entries: restoredEntries });
      }
      const status = await api.matchStatus();
      if (!mounted.current) return;
      setProgress(status.progress);
      if (!status.progress.complete) setTracking(true);
    })().catch(failure => setError(failure instanceof Error ? failure.message : '会话恢复失败'));
  }, [saved.displayed, dispatch]);

  useMatchPolling({
    tracking,
    onProgress: setProgress,
    onComplete: load,
    onStop: () => setTracking(false),
    onError: setError,
  });

  const validateAndApply = () => {
    const minText = draft.minimum.trim();
    const maxText = draft.maximum.trim();
    const minimum = minText === '' ? 0 : Number(minText);
    const maximum = maxText === '' ? (catalogue?.dataset_max_points ?? null) : Number(maxText);
    if (!Number.isSafeInteger(minimum) || minimum < 0 || maximum === null || !Number.isSafeInteger(maximum) || maximum < 0) {
      return setError('观测点数必须是非负整数');
    }
    if (minimum > maximum) return setError('最小观测点数不得大于最大观测点数');
    if (catalogue && maximum > catalogue.dataset_max_points) {
      return setError(`最大观测点数不得超过 ${catalogue.dataset_max_points}`);
    }
    if (draft.start && draft.end && draft.start > draft.end) return setError('起始日期不得晚于终止日期');
    setError('');
    setFilters({ ...draft, minimum, maximum });
    setPage(1);
  };

  const nextSlot = () => {
    const used = new Set([...wb.mapFlights.values()].map(entry => entry.slot));
    let slot = 0;
    while (used.has(slot)) slot += 1;
    return slot;
  };

  const toggleMap = async (item: FlightItem) => {
    if (wb.mapFlights.has(item.flight_key)) {
      return dispatch({ type: 'map-flight', key: item.flight_key, value: null });
    }
    try {
      const geometry = await api.geometry(item.flight_key);
      dispatch({
        type: 'map-flight',
        key: item.flight_key,
        value: {
          geometry,
          label: item.flight_id || geometry.flight_id,
          slot: nextSlot(),
          trajectoryVisible: true,
          pathVisible: true,
        },
      });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '轨迹加载失败');
    }
  };

  const runAddSelectedToMap = async (pending: string[]) => {
    const used = new Set([...wb.mapFlights.values()].map(entry => entry.slot));
    const slots = pending.map(() => {
      let slot = 0;
      while (used.has(slot)) slot += 1;
      used.add(slot);
      return slot;
    });
    const controller = new AbortController();
    addAbortRef.current?.abort();
    addAbortRef.current = controller;
    const concurrency = 5;
    const batchSize = 10;
    let cursor = 0;
    let done = 0;
    let buffer: Array<{ key: string; value: import('../../api/types').MapFlightEntry }> = [];
    const flush = () => {
      if (!buffer.length || !mounted.current) return;
      const entries = buffer;
      buffer = [];
      dispatch({ type: 'map-flights-batch', entries });
    };
    setAddingProgress({ done: 0, total: pending.length });
    const worker = async () => {
      while (cursor < pending.length && mounted.current && !controller.signal.aborted) {
        const index = cursor++;
        const key = pending[index];
        try {
          const geometry = await api.geometry(key, controller.signal);
          if (!mounted.current || controller.signal.aborted) return;
          buffer.push({
            key,
            value: {
              geometry,
              label: geometry.flight_id,
              slot: slots[index],
              trajectoryVisible: true,
              pathVisible: true,
            },
          });
          if (buffer.length >= batchSize) flush();
        } catch (failure) {
          if ((failure as Error).name !== 'AbortError' && mounted.current) {
            setError(failure instanceof Error ? failure.message : '批量轨迹加载失败');
          }
        } finally {
          done += 1;
          if (mounted.current && !controller.signal.aborted) {
            setAddingProgress({ done, total: pending.length });
          }
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(concurrency, pending.length) }, worker));
    flush();
    if (addAbortRef.current === controller) addAbortRef.current = null;
    if (mounted.current) {
      setAddingProgress(null);
      if (controller.signal.aborted) dispatch({ type: 'status', value: '已取消批量加入地图' });
    }
  };

  const addSelectedToMap = () => {
    const pending = [...wb.matchSelection].filter(key => !wb.mapFlights.has(key));
    if (!pending.length) return;
    if (pending.length > 50) {
      Modal.confirm({
        title: '批量加入地图确认',
        content: `即将向地图加入 ${pending.length} 架航班，数量较大可能影响地图流畅度，是否继续？`,
        okText: '继续加入',
        cancelText: '取消',
        onOk: () => runAddSelectedToMap(pending),
      });
      return;
    }
    void runAddSelectedToMap(pending);
  };

  const showDetail = async (item: FlightItem) => {
    try {
      onDetail(await api.detail(item.flight_key));
      dispatch({ type: 'view', value: 'observations' });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '详情加载失败');
    }
  };

  const saveStand = async () => {
    if (!editingStand) return;
    try {
      await api.updateStand(editingStand.key, editingStand.value || null);
      setEditingStand(null);
      setStandEditSearch('');
      await load();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '机位保存失败');
    }
  };

  const toggleFiltered = async (checked: boolean) => {
    const seq = ++toggleFilteredSeqRef.current;
    try {
      const result = await api.filteredFlights(paramsFor(filters));
      if (seq !== toggleFilteredSeqRef.current) return;
      setFilteredKeys(result.flight_keys);
      dispatch({
        type: checked ? 'merge-match-selection' : 'remove-match-selection',
        keys: result.flight_keys,
      });
      dispatch({
        type: 'status',
        value: checked ? `已选择当前筛选的 ${result.count} 条航班` : `已取消当前筛选的 ${result.count} 条航班`,
      });
    } catch (failure) {
      if (seq === toggleFilteredSeqRef.current) setError(failure instanceof Error ? failure.message : '选择失败');
    } finally {
      if (seq === toggleFilteredSeqRef.current) setAllResultsIntent(null);
    }
  };

  const submit = (keys = [...wb.matchSelection], force = false) => {
    if (!keys.length) return;
    Modal.confirm({
      title: '提交航班匹配',
      content: `确认提交 ${keys.length} 条航班进行路径匹配？`,
      okText: '确认提交',
      cancelText: '取消',
      onOk: async () => {
        try {
          await api.submitMatches(keys, force);
          setTracking(true);
          await load();
        } catch (failure) {
          setError(failure instanceof Error ? failure.message : '任务提交失败');
        }
      },
    });
  };

  const jump = () => {
    const value = Number(pageDraft);
    if (!Number.isSafeInteger(value) || value < 1 || !catalogue || value > catalogue.total_pages) {
      return setPageError(`页码范围为 1～${catalogue?.total_pages ?? 1}`);
    }
    setPageError('');
    setPage(value);
  };

  const allPageSelected = useMemo(
    () => Boolean(catalogue?.items.length) && catalogue!.items.every(item => wb.matchSelection.has(item.flight_key)),
    [catalogue, wb.matchSelection],
  );

  const allResultsSelected = useMemo(() => {
    if (!catalogue?.total || !allPageSelected || wb.matchSelection.size < catalogue.total) return false;
    if (catalogue.total <= catalogue.items.length) return true;
    if (filteredKeys) return filteredKeys.every(key => wb.matchSelection.has(key));
    return wb.matchSelection.size === catalogue.total;
  }, [catalogue, allPageSelected, filteredKeys, wb.matchSelection]);

  const visibleStands = useMemo(
    () => ['', ...(catalogue?.stand_options ?? [])].filter(stand => (stand || '空机位').toLowerCase().includes(standSearch.toLowerCase())),
    [catalogue, standSearch],
  );

  const editableStands = useMemo(
    () => ['', ...(catalogue?.stand_options ?? [])].filter(stand => (stand || '空机位').toLowerCase().includes(standEditSearch.toLowerCase())),
    [catalogue, standEditSearch],
  );

  const openStandEditor = (item: FlightItem, trigger: HTMLButtonElement) => {
    const container = tableScroll.current;
    const above = container ? trigger.getBoundingClientRect().bottom + 260 > container.getBoundingClientRect().bottom : false;
    setEditingStand({ key: item.flight_key, value: item.stand_position ?? '', above });
    setStandEditSearch('');
  };

  return (
    <section id="flight-sheet" className={`main-view flight-sheet ${active ? '' : 'hidden'}`}>
      <header className="sheet-heading">
        <h2>航班</h2>
        <span>{catalogue ? `第 ${catalogue.page || 0} / ${catalogue.total_pages} 页（${catalogue.total} 条）` : ''}</span>
      </header>
      <div className="flight-query">
        <div className="flight-filters">
          <label className="filter-field">
            <span>航班号 / ID</span>
            <input
              value={draft.query}
              placeholder="航班号 / ID"
              onChange={event => setDraft({ ...draft, query: event.target.value })}
              onKeyDown={event => { if (event.key === 'Enter') validateAndApply(); }}
            />
          </label>
          <label className="filter-field">
            <span>进出港</span>
            <select value={draft.movement} onChange={event => setDraft({ ...draft, movement: event.target.value })}>
              <option value="">全部进出港</option>
              <option value="arrival">进港</option>
              <option value="departure">离港</option>
              <option value="unknown">未知</option>
            </select>
          </label>
          <label className="filter-field">
            <span>匹配状态</span>
            <select value={draft.status} onChange={event => setDraft({ ...draft, status: event.target.value })}>
              <option value="">全部状态</option>
              {Object.entries(statusLabels).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </label>
          <div className="filter-field">
            <span>机位</span>
            <details ref={standPicker} className="stand-picker" open={standPickerOpen}>
              <summary
                className="secondary-button"
                onClick={event => {
                  event.preventDefault();
                  setStandPickerOpen(value => !value);
                }}
              >
                {draft.stands.length ? `已选 ${draft.stands.length} 个机位` : '全部机位'}
              </summary>
              <div className="stand-options-panel">
                <input
                  type="search"
                  aria-label="搜索机位"
                  value={standSearch}
                  onChange={event => setStandSearch(event.target.value)}
                />
                {visibleStands.map(stand => (
                  <label key={stand || '__empty'}>
                    <input
                      type="checkbox"
                      aria-label={stand || '空机位'}
                      checked={draft.stands.includes(stand)}
                      onChange={event => {
                        setDraft(value => ({
                          ...value,
                          stands: event.target.checked
                            ? [...value.stands, stand]
                            : value.stands.filter(item => item !== stand),
                        }));
                      }}
                    />
                    {stand || '空机位'}
                  </label>
                ))}
              </div>
            </details>
          </div>
          <label className="filter-field">
            <span>最小观测点数</span>
            <input
              type="number"
              min={0}
              aria-label="最小观测点数"
              placeholder="最小值"
              value={draft.minimum}
              onChange={event => setDraft({ ...draft, minimum: event.target.value })}
              onKeyDown={event => { if (event.key === 'Enter') validateAndApply(); }}
            />
          </label>
          <label className="filter-field">
            <span>最大观测点数</span>
            <input
              type="number"
              min={0}
              aria-label="最大观测点数"
              placeholder="最大值"
              value={draft.maximum}
              onChange={event => setDraft({ ...draft, maximum: event.target.value })}
              onKeyDown={event => { if (event.key === 'Enter') validateAndApply(); }}
            />
          </label>
          <label className="filter-field">
            <span>起始日期</span>
            <span className={`date-filter ${draft.start ? 'has-value' : ''}`}>
              <i>{draft.start || '起始日期'}</i>
              <input
                type="date"
                aria-label="起始日期"
                value={draft.start}
                onClick={event => event.currentTarget.showPicker?.()}
                onChange={event => setDraft({ ...draft, start: event.target.value })}
              />
            </span>
          </label>
          <label className="filter-field">
            <span>终止日期</span>
            <span className={`date-filter ${draft.end ? 'has-value' : ''}`}>
              <i>{draft.end || '终止日期'}</i>
              <input
                type="date"
                aria-label="终止日期"
                value={draft.end}
                onClick={event => event.currentTarget.showPicker?.()}
                onChange={event => setDraft({ ...draft, end: event.target.value })}
              />
            </span>
          </label>
        </div>
        <div className="filter-actions">
          {catalogue?.supports_validation_filter ? (
            <label>
              <input
                type="checkbox"
                checked={draft.validation}
                onChange={event => setDraft({ ...draft, validation: event.target.checked })}
              />
              验证航班（≥30 点）
            </label>
          ) : (
            <span />
          )}
          <div>
            <button
              className="text-button"
              onClick={() => {
                const value = { ...defaultFlightFilters, maximum: catalogue?.dataset_max_points ?? null };
                setDraft(toDraft(value));
                setFilters(value);
                setPage(1);
                setError('');
              }}
            >
              重置
            </button>
            <button className="primary-button" onClick={validateAndApply}>
              过滤
            </button>
          </div>
        </div>
        {error && <p className="field-error" role="alert">{error}</p>}
      </div>
      <div className="sheet-batch-tools">
        <div className="selection-tools">
          <label className="batch-check">
            <input
              type="checkbox"
              aria-label="选择本页航班"
              checked={allPageSelected}
              onChange={() =>
                catalogue?.items.forEach(item =>
                  dispatch({ type: 'toggle-match', key: item.flight_key, checked: !allPageSelected }),
                )
              }
            />
            选择本页
          </label>
          <label className="batch-check">
            <input
              type="checkbox"
              aria-label="选择全部结果"
              checked={allResultsIntent ?? allResultsSelected}
              onChange={event => {
                setAllResultsIntent(event.target.checked);
                void toggleFiltered(event.target.checked);
              }}
            />
            选择全部结果
          </label>
          <button
            className="clear-selection-action"
            aria-label="清空所选航班"
            title="清空所选航班"
            disabled={!wb.matchSelection.size}
            onClick={() => dispatch({ type: 'set-match-selection', keys: [] })}
          >
            <StudioIcon name="close" />
          </button>
          <span>已选 {wb.matchSelection.size} 条</span>
        </div>
        <div className="batch-actions">
          <button
            className="secondary-button compact-action"
            disabled={!wb.matchSelection.size || Boolean(addingProgress)}
            onClick={addSelectedToMap}
          >
            <StudioIcon name="mapAdd" />
            {addingProgress ? `加入中 (${addingProgress.done}/${addingProgress.total})` : '所选加入地图'}
          </button>
          {addingProgress && (
            <button
              className="text-button compact-action"
              onClick={() => addAbortRef.current?.abort()}
            >
              取消加入
            </button>
          )}
          <button
            className="primary-button compact-action"
            disabled={!wb.matchSelection.size || tracking}
            onClick={() => submit()}
          >
            {tracking ? '匹配中…' : '匹配所选航班'}
          </button>
        </div>
      </div>
      {progress && (
        <section className="match-progress">
          <strong>批量任务</strong>
          <dl>
            <div><dt>等待</dt><dd>{progress.waiting}</dd></div>
            <div><dt>运行</dt><dd>{progress.running}</dd></div>
            <div className="success"><dt>成功</dt><dd>{progress.success}</dd></div>
            <div className="failed"><dt>失败</dt><dd>{progress.failed}</dd></div>
          </dl>
        </section>
      )}
      <div ref={tableScroll} className="sheet-table-scroll">
        <table className="sheet-table">
          <thead>
            <tr>
              <th>选择</th>
              <th>航班</th>
              <th>进出港</th>
              <th>机位</th>
              <th>状态</th>
              <th>观测点</th>
              <th>开始时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {catalogue?.items.map(item => (
              <tr key={item.flight_key}>
                <td>
                  <input
                    type="checkbox"
                    checked={wb.matchSelection.has(item.flight_key)}
                    onChange={event =>
                      dispatch({ type: 'toggle-match', key: item.flight_key, checked: event.target.checked })
                    }
                  />
                </td>
                <td>
                  <strong>{item.flight_number || item.flight_id}</strong>
                  <small>{item.flight_id}</small>
                </td>
                <td>{item.movement_type === 'arrival' ? '进港' : item.movement_type === 'departure' ? '离港' : '未知'}</td>
                <td className="stand-cell">
                  {item.can_edit_stand ? (
                    <button
                      className="stand-edit-trigger"
                      title="点击编辑机位"
                      onClick={event => openStandEditor(item, event.currentTarget)}
                    >
                      {item.stand_position || '选择机位'}
                    </button>
                  ) : (
                    <span>{item.stand_position || '—'}</span>
                  )}
                  {editingStand?.key === item.flight_key && (
                    <div
                      ref={standEditor}
                      className={`stand-editor ${editingStand.above ? 'open-above' : ''}`}
                      role="dialog"
                      aria-label={`编辑 ${item.flight_id} 机位`}
                    >
                      <input
                        type="search"
                        aria-label="搜索可选机位"
                        placeholder="搜索机位"
                        value={standEditSearch}
                        onChange={event => setStandEditSearch(event.target.value)}
                      />
                      <div className="stand-editor-options">
                        {editableStands.map(stand => (
                          <label key={stand || '__empty'}>
                            <input
                              type="radio"
                              name={`stand-${item.flight_key}`}
                              value={stand}
                              checked={editingStand.value === stand}
                              onChange={() => setEditingStand({ ...editingStand, value: stand })}
                            />
                            {stand || '空机位'}
                          </label>
                        ))}
                      </div>
                      <div className="stand-editor-actions">
                        <button className="text-button" onClick={() => setEditingStand(null)}>取消</button>
                        <button className="primary-button" onClick={() => void saveStand()}>保存</button>
                      </div>
                    </div>
                  )}
                </td>
                <td>
                  <span className={`flight-status ${item.match.status}`}>
                    {statusLabels[item.match.status] || item.match.status}
                  </span>
                  {item.match.error && <small title={item.match.error}>{item.match.failure_type}</small>}
                </td>
                <td>{item.point_count}</td>
                <td>{item.start_time.replace('T', ' ').slice(0, 19)}</td>
                <td>
                  <button className="secondary-button" onClick={() => void showDetail(item)}>详情</button>
                  <button className="secondary-button" onClick={() => void toggleMap(item)}>
                    {wb.mapFlights.has(item.flight_key) ? '移出地图' : '加入地图'}
                  </button>
                  {wb.mapFlights.has(item.flight_key) && (
                    <button
                      className="flight-locate-action"
                      onClick={() => dispatch({ type: 'focus-flight', key: item.flight_key, preserveView: splitView })}
                    >
                      ⌖ 定位
                    </button>
                  )}
                  {item.match.status === 'failed' && (
                    <button onClick={() => submit([item.flight_key], true)}>重试</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && <div className="busy"><span /></div>}
      </div>
      <footer className="sheet-pagination">
        <button disabled={page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button>
        <span>{catalogue ? `${catalogue.page || 0}/${catalogue.total_pages}` : '—'}</span>
        <input
          type="number"
          min={1}
          value={pageDraft}
          aria-label="跳转页码"
          onChange={event => setPageDraft(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter') jump(); }}
        />
        <button onClick={jump}>跳转</button>
        <button disabled={!catalogue || page >= catalogue.total_pages} onClick={() => setPage(value => value + 1)}>
          下一页
        </button>
        {pageError && <p className="field-error">{pageError}</p>}
      </footer>
    </section>
  );
}
