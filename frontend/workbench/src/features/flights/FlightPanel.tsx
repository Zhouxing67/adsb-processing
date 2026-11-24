import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Crosshair, FileText, MapPinOff, MapPinPlus, RotateCw } from 'lucide-react';
import { ApiError, api } from '@/api/client';
import type { FlightCatalogueQuery } from '@/api/client';
import type { FlightCatalogue, FlightItem, MatchStatus } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import type { MapFlightInput } from '@/app/WorkbenchContext';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  DataTableContainer,
  IconActionButton,
  PaginationFooter,
  ViewHeader,
} from '@/components/ui/workbench-shell';
import { MATCH_STATUS_LABELS as statusLabels, MOVEMENT_LABELS as movementLabels } from '@/domain/palette';
import { runWithConcurrency } from '@/lib/async';
import { cn } from '@/lib/utils';
import { FlightBulkBar } from './FlightBulkBar';
import { FlightConfirmDialog } from './FlightConfirmDialog';
import type { ConfirmDialogState } from './FlightConfirmDialog';
import { FlightFilterBar } from './FlightFilterBar';
import type { DraftFilters } from './FlightFilterBar';
import { StandEditorCell } from './StandEditorCell';
import { defaultFlightFilters, patchStoredFlightState, readStoredFlightState } from './storage';
import type { FlightFilters } from './storage';

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
    whitelist_only: filters.whitelist || undefined,
    issues_only: filters.issues || undefined,
    page,
    page_size: page === undefined ? undefined : 15,
  };
}

function statusBadgeVariant(status: string) {
  if (status === 'success') return 'success' as const;
  if (status === 'failed') return 'destructive' as const;
  if (status === 'matching' || status === 'queued') return 'warning' as const;
  return 'secondary' as const;
}

interface FlightPanelProps {
  tracking: boolean;
  progress: MatchStatus['progress'] | null;
  submitMatches(keys: string[], force: boolean): Promise<void>;
  onOpenDetail(flightKey: string, onError?: (message: string) => void): Promise<void>;
  active?: boolean;
  splitView?: boolean;
  activeDetailKey?: string | null;
}

export function FlightPanel({
  tracking,
  progress,
  submitMatches,
  onOpenDetail,
  active = true,
  splitView = false,
  activeDetailKey = null,
}: FlightPanelProps) {
  const wb = useWorkbench();
  const dispatch = wb.dispatch;
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
  const [loading, setLoading] = useState(false);
  const [addingProgress, setAddingProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState('');
  const [pageError, setPageError] = useState('');
  const [allResultsIntent, setAllResultsIntent] = useState<boolean | null>(null);
  const [filteredKeys, setFilteredKeys] = useState<{ catalogue: FlightCatalogue; keys: string[] } | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState>(null);
  const [mutatingIssues, setMutatingIssues] = useState(false);

  const mounted = useRef(true);
  const addAbortRef = useRef<AbortController | null>(null);
  const toggleFilteredSeqRef = useRef(0);

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
        setDraft(current => ({
          ...current,
          maximum: current.maximum === '' ? String(value.dataset_max_points) : current.maximum,
          start: !current.start && !current.end && value.dataset_min_date ? value.dataset_min_date : current.start,
          end: !current.start && !current.end && value.dataset_max_date ? value.dataset_max_date : current.end,
        }));
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
  }, [load, wb.flightCatalogueVersion]);

  useEffect(() => {
    toggleFilteredSeqRef.current += 1;
    setAllResultsIntent(null);
  }, [filters]);

  useEffect(() => {
    patchStoredFlightState({ filters, page });
  }, [filters, page]);

  const mutateIssues = async (mode: 'add' | 'remove') => {
    const keys = [...wb.matchSelection];
    if (!keys.length) return;
    setMutatingIssues(true);
    try {
      const res = mode === 'add' ? await api.addMatchIssues(keys) : await api.removeMatchIssues(keys);
      dispatch({ type: 'set-issue-keys', keys: res.issue_flight_keys });
      dispatch({
        type: 'status',
        value:
          mode === 'add'
            ? `异常归档完成：新增 ${res.inserted} 条，已存在 ${res.existing} 条`
            : `已从异常归档移出 ${res.deleted} 条航班`,
      });
      await load();
    } catch (failure) {
      dispatch({
        type: 'error',
        value: failure instanceof Error ? failure.message : mode === 'add' ? '加入异常归档失败' : '移出异常归档失败',
      });
    } finally {
      setMutatingIssues(false);
    }
  };

  const validateAndApply = () => {
    const minText = draft.minimum.trim();
    const maxText = draft.maximum.trim();
    const minimum = minText === '' ? 0 : Number(minText);
    const maximum = maxText === '' ? (catalogue?.dataset_max_points ?? null) : Number(maxText);
    if (!Number.isSafeInteger(minimum) || minimum < 0 || maximum === null || !Number.isSafeInteger(maximum) || maximum < 0) {
      setError('观测点数必须是非负整数');
      return false;
    }
    if (minimum > maximum) {
      setError('最小观测点数不得大于最大观测点数');
      return false;
    }
    if (catalogue && maximum > catalogue.dataset_max_points) {
      setError(`最大观测点数不得超过 ${catalogue.dataset_max_points}`);
      return false;
    }
    if (draft.start && draft.end && draft.start > draft.end) {
      setError('起始日期不得晚于终止日期');
      return false;
    }
    const minDate = catalogue?.dataset_min_date ?? '';
    const maxDate = catalogue?.dataset_max_date ?? '';
    const isFullDateRange = Boolean(minDate && maxDate) && draft.start === minDate && draft.end === maxDate;
    setError('');
    setFilters({
      ...draft,
      minimum,
      maximum,
      start: isFullDateRange ? '' : draft.start,
      end: isFullDateRange ? '' : draft.end,
    });
    setPage(1);
    return true;
  };

  const resetFilters = () => {
    const value = { ...defaultFlightFilters, maximum: catalogue?.dataset_max_points ?? null };
    setDraft({
      ...toDraft(value),
      start: catalogue?.dataset_min_date ?? '',
      end: catalogue?.dataset_max_date ?? '',
    });
    setFilters(value);
    setPage(1);
    setError('');
  };

  const applyFilterPatch = useCallback(
    (patch: Partial<FlightFilters>) => {
      setFilters(current => {
        const next = { ...current, ...patch };
        const nextDraft = toDraft(next);
        if (!nextDraft.start && !nextDraft.end && catalogue?.dataset_min_date && catalogue?.dataset_max_date) {
          nextDraft.start = catalogue.dataset_min_date;
          nextDraft.end = catalogue.dataset_max_date;
        }
        setDraft(nextDraft);
        return next;
      });
      setPage(1);
      setError('');
    },
    [catalogue?.dataset_min_date, catalogue?.dataset_max_date],
  );

  const toggleMap = async (item: FlightItem) => {
    if (wb.mapFlights.has(item.flight_key)) {
      return dispatch({ type: 'map-flight', key: item.flight_key, value: null });
    }
    try {
      const geometry = await api.geometry(item.flight_key);
      if (!mounted.current) return;
      dispatch({
        type: 'map-flight',
        key: item.flight_key,
        value: {
          geometry,
          label: item.flight_id || geometry.flight_id,
          trajectoryVisible: true,
          pathVisible: true,
        },
      });
    } catch (failure) {
      if (mounted.current) setError(failure instanceof Error ? failure.message : '轨迹加载失败');
    }
  };

  const runAddSelectedToMap = async (pending: string[]) => {
    const controller = new AbortController();
    addAbortRef.current?.abort();
    addAbortRef.current = controller;
    const batchSize = 10;
    let done = 0;
    let buffer: Array<{ key: string; value: MapFlightInput }> = [];
    const flush = () => {
      if (!buffer.length || !mounted.current) return;
      const entries = buffer;
      buffer = [];
      dispatch({ type: 'map-flights-batch', entries });
    };
    setAddingProgress({ done: 0, total: pending.length });
    await runWithConcurrency(
      pending,
      5,
      async key => {
        try {
          const geometry = await api.geometry(key, controller.signal);
          if (!mounted.current || controller.signal.aborted) return;
          buffer.push({
            key,
            value: { geometry, label: geometry.flight_id, trajectoryVisible: true, pathVisible: true },
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
      },
      controller.signal,
    );
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
      setConfirmDialog({ kind: 'bulk-map', pending });
      return;
    }
    void runAddSelectedToMap(pending);
  };

  const saveStand = async (flightKey: string, standValue: string | null) => {
    try {
      await api.updateStand(flightKey, standValue);
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
      if (catalogue) setFilteredKeys({ catalogue, keys: result.flight_keys });
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

  const requestSubmit = (keys = [...wb.matchSelection], force = false) => {
    if (!keys.length) return;
    setConfirmDialog({ kind: 'match', keys, force });
  };

  const executeConfirm = async () => {
    const dialog = confirmDialog;
    setConfirmDialog(null);
    if (!dialog) return;
    if (dialog.kind === 'bulk-map') {
      await runAddSelectedToMap(dialog.pending);
      return;
    }
    try {
      await submitMatches(dialog.keys, dialog.force);
      await load();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '任务提交失败');
    }
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

  const needsFilteredKeys = Boolean(
    catalogue && catalogue.total > catalogue.items.length && allPageSelected && wb.matchSelection.size >= catalogue.total,
  );
  useEffect(() => {
    if (!needsFilteredKeys || !catalogue || filteredKeys?.catalogue === catalogue) return;
    let live = true;
    api
      .filteredFlights(paramsFor(filters))
      .then(result => {
        if (live) setFilteredKeys({ catalogue, keys: result.flight_keys });
      })
      .catch(failure => {
        if (live) setError(failure instanceof Error ? failure.message : '无法读取筛选结果');
      });
    return () => {
      live = false;
    };
  }, [needsFilteredKeys, filters, catalogue, filteredKeys]);

  const allResultsSelected =
    allPageSelected &&
    (catalogue?.total === catalogue?.items.length ||
      (needsFilteredKeys &&
        filteredKeys?.catalogue === catalogue &&
        filteredKeys.keys.every(key => wb.matchSelection.has(key))));

  const datasetMax = catalogue?.dataset_max_points ?? null;
  const advancedActiveCount = useMemo(() => {
    let count = 0;
    if (filters.stands.length > 0) count += 1;
    if (filters.minimum > 0) count += 1;
    if (filters.maximum !== null && datasetMax !== null && filters.maximum < datasetMax) count += 1;
    if (filters.start || filters.end) count += 1;
    if (filters.validation) count += 1;
    if (filters.whitelist) count += 1;
    if (filters.issues) count += 1;
    return count;
  }, [filters, datasetMax]);

  const activeChips = useMemo(() => {
    const chips: Array<{ id: string; label: string; clear: () => void }> = [];
    if (filters.query) chips.push({ id: 'q', label: `搜索: ${filters.query}`, clear: () => applyFilterPatch({ query: '' }) });
    if (filters.movement) {
      chips.push({ id: 'movement', label: `进出港: ${movementLabels[filters.movement] ?? filters.movement}`, clear: () => applyFilterPatch({ movement: '' }) });
    }
    if (filters.status) {
      chips.push({ id: 'status', label: `状态: ${statusLabels[filters.status] ?? filters.status}`, clear: () => applyFilterPatch({ status: '' }) });
    }
    if (filters.stands.length) {
      chips.push({ id: 'stands', label: `机位: ${filters.stands.map(s => s || '空机位').join(', ')}`, clear: () => applyFilterPatch({ stands: [] }) });
    }
    if (filters.minimum > 0) chips.push({ id: 'min', label: `观测点 ≥ ${filters.minimum}`, clear: () => applyFilterPatch({ minimum: 0 }) });
    if (filters.maximum !== null && datasetMax !== null && filters.maximum < datasetMax) {
      chips.push({ id: 'max', label: `观测点 ≤ ${filters.maximum}`, clear: () => applyFilterPatch({ maximum: datasetMax }) });
    }
    if (filters.start || filters.end) {
      chips.push({ id: 'date', label: `日期: ${filters.start || '不限'} ~ ${filters.end || '不限'}`, clear: () => applyFilterPatch({ start: '', end: '' }) });
    }
    if (filters.validation) chips.push({ id: 'validation', label: '仅验证航班', clear: () => applyFilterPatch({ validation: false }) });
    if (filters.whitelist) chips.push({ id: 'whitelist', label: '仅白名单航班', clear: () => applyFilterPatch({ whitelist: false }) });
    if (filters.issues) chips.push({ id: 'issues', label: '仅异常归档航班', clear: () => applyFilterPatch({ issues: false }) });
    return chips;
  }, [filters, datasetMax, applyFilterPatch]);

  return (
    <section
      id="flight-sheet"
      className={cn(
        'main-view flight-sheet absolute inset-0 flex h-full w-full min-h-0 min-w-0 flex-col overflow-hidden bg-background',
        !active && 'hidden',
      )}
    >
      <ViewHeader>
        <h2 className="m-0 text-[15px] font-semibold text-foreground">航班</h2>
      </ViewHeader>

      <FlightFilterBar
        draft={draft}
        catalogue={catalogue}
        issueCount={wb.issueKeys.size || catalogue?.issue_count || 0}
        advancedActiveCount={advancedActiveCount}
        activeChips={activeChips}
        error={error}
        onDraftChange={setDraft}
        onValidateAndApply={validateAndApply}
        onReset={resetFilters}
      />

      <FlightBulkBar
        selectedCount={wb.matchSelection.size}
        allPageSelected={allPageSelected}
        allResultsChecked={allResultsIntent ?? allResultsSelected}
        canEditIssues={Boolean(catalogue?.can_edit_issues)}
        mutatingIssues={mutatingIssues}
        addingProgress={addingProgress}
        tracking={tracking}
        progress={progress}
        onTogglePage={() =>
          catalogue?.items.forEach(item =>
            dispatch({ type: 'toggle-match', key: item.flight_key, checked: !allPageSelected }),
          )
        }
        onToggleAllResults={next => {
          setAllResultsIntent(next);
          void toggleFiltered(next);
        }}
        onClearSelection={() => dispatch({ type: 'set-match-selection', keys: [] })}
        onArchiveIssues={() => void mutateIssues('add')}
        onRemoveIssues={() => void mutateIssues('remove')}
        onAddSelectedToMap={addSelectedToMap}
        onCancelAddToMap={() => addAbortRef.current?.abort()}
        onRequestSubmit={() => requestSubmit()}
      />

      <DataTableContainer loading={loading}>
        <Table className="min-w-[740px]">
          <TableHeader>
            <TableRow className="bg-muted hover:bg-muted">
              <TableHead>选择</TableHead>
              <TableHead>航班</TableHead>
              <TableHead>进出港</TableHead>
              <TableHead>机位</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>观测点</TableHead>
              <TableHead>开始时间</TableHead>
              <TableHead>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {catalogue?.items.map(item => {
              const onMap = wb.mapFlights.has(item.flight_key);
              const isInspecting = activeDetailKey === item.flight_key;
              return (
                <TableRow
                  key={item.flight_key}
                  data-state={onMap ? 'selected' : undefined}
                  className={cn('group', isInspecting && 'bg-primary/5 shadow-[inset_3px_0_0_0_var(--primary)]')}
                >
                  <TableCell>
                    <Checkbox
                      aria-label={`选择航班 ${item.flight_id}`}
                      checked={wb.matchSelection.has(item.flight_key)}
                      onCheckedChange={checked =>
                        dispatch({ type: 'toggle-match', key: item.flight_key, checked: checked === true })
                      }
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <strong className="cursor-default font-medium text-foreground">
                            {item.flight_number || item.flight_id}
                          </strong>
                        </TooltipTrigger>
                        <TooltipContent side="right" className="font-mono text-[11px]">
                          {item.flight_id}
                        </TooltipContent>
                      </Tooltip>
                      {(wb.issueKeys.has(item.flight_key) || item.is_issue) && (
                        <Badge
                          variant="destructive"
                          className="h-4 px-1.5 text-[11px]"
                          title={item.issue_reason || '已归档到 match_issues'}
                        >
                          异常
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-foreground">{movementLabels[item.movement_type] ?? '未知'}</TableCell>
                  <TableCell>
                    <StandEditorCell item={item} standOptions={catalogue?.stand_options ?? []} onSave={saveStand} />
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusBadgeVariant(item.match.status)}>
                      {statusLabels[item.match.status] || item.match.status}
                    </Badge>
                    {item.match.error && (
                      <small className="ml-1.5 text-[11px] text-destructive" title={item.match.error}>
                        {item.match.failure_type}
                      </small>
                    )}
                  </TableCell>
                  <TableCell className="tabular-nums text-foreground">{item.point_count}</TableCell>
                  <TableCell className="tabular-nums text-muted-foreground">
                    {item.start_time.replace('T', ' ').slice(0, 19)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-0.5">
                      <IconActionButton
                        reveal="table"
                        label="详情"
                        tooltip="查看观测记录"
                        onClick={() => void onOpenDetail(item.flight_key, setError)}
                      >
                        <FileText className="h-3.5 w-3.5" />
                      </IconActionButton>
                      <IconActionButton
                        variant={onMap ? 'secondary' : 'ghost'}
                        reveal={!onMap ? 'table' : undefined}
                        label={onMap ? '移出地图' : '加入地图'}
                        onClick={() => void toggleMap(item)}
                      >
                        {onMap ? <MapPinOff className="h-3.5 w-3.5" /> : <MapPinPlus className="h-3.5 w-3.5" />}
                      </IconActionButton>
                      {onMap && (
                        <IconActionButton
                          reveal="table"
                          className="flight-locate-action"
                          label="定位"
                          tooltip="在地图中定位"
                          onClick={() => dispatch({ type: 'focus-flight', key: item.flight_key, preserveView: splitView })}
                        >
                          <Crosshair className="h-3.5 w-3.5" />
                        </IconActionButton>
                      )}
                      {item.match.status === 'failed' && (
                        <IconActionButton
                          className="text-destructive hover:text-destructive"
                          label="重试"
                          tooltip="重新匹配"
                          onClick={() => requestSubmit([item.flight_key], true)}
                        >
                          <RotateCw className="h-3.5 w-3.5" />
                        </IconActionButton>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </DataTableContainer>

      <PaginationFooter>
        <span className="text-xs text-muted-foreground tabular-nums">
          {catalogue ? `共 ${catalogue.total} 条 · 第 ${catalogue.page || 0} / ${catalogue.total_pages} 页` : '—'}
        </span>
        <div className="flex flex-wrap items-center gap-1.5">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>
            上一页
          </Button>
          <Input
            type="number"
            min={1}
            value={pageDraft}
            aria-label="跳转页码"
            className="h-7 w-16 text-center text-xs tabular-nums"
            onChange={event => setPageDraft(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') jump();
            }}
          />
          <Button variant="outline" size="sm" onClick={jump}>
            跳转
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!catalogue || page >= catalogue.total_pages}
            onClick={() => setPage(value => value + 1)}
          >
            下一页
          </Button>
          {pageError && <p className="m-0 text-xs text-destructive">{pageError}</p>}
        </div>
      </PaginationFooter>

      <FlightConfirmDialog
        dialog={confirmDialog}
        onClose={() => setConfirmDialog(null)}
        onConfirm={() => void executeConfirm()}
      />
    </section>
  );
}
