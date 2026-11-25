import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Crosshair, FileText, MapPinOff, MapPinPlus, RotateCw } from 'lucide-react';
import { ApiError, api } from '@/api/client';
import type { FlightCatalogue, FlightItem, MatchStatus } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import type { MapFlightInput } from '@/app/WorkbenchContext';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  DataTableContainer,
  IconActionButton,
  PaginationFooter,
  TablePagination,
  ViewHeader,
} from '@/components/ui/workbench-shell';
import { MATCH_STATUS_LABELS as statusLabels, MOVEMENT_LABELS as movementLabels } from '@/domain/palette';
import { MapBatchConfirmDialog } from '@/features/map/MapBatchConfirmDialog';
import { useMapBatchLoader } from '@/features/map/useMapBatchLoader';
import { cn } from '@/lib/utils';
import { FlightBulkBar } from './FlightBulkBar';
import { FlightConfirmDialog } from './FlightConfirmDialog';
import type { ConfirmDialogState } from './FlightConfirmDialog';
import { FlightFilterBar } from './FlightFilterBar';
import type { DraftFilters } from './FlightFilterBar';
import {
  buildFlightFilterChips,
  buildFlightQueryParams as paramsFor,
  countAdvancedFlightFilters,
  toFlightDraft as toDraft,
  validateFlightDraft,
} from './flightFilterHelpers';
import { StandEditorCell } from './StandEditorCell';
import { defaultFlightFilters, patchStoredFlightState, readStoredFlightState } from './storage';
import type { FlightFilters } from './storage';

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
  const [pageSize, setPageSize] = useState(
    Number.isInteger(saved.pageSize) && saved.pageSize! > 0 ? saved.pageSize! : 20,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [allResultsIntent, setAllResultsIntent] = useState<boolean | null>(null);
  const [filteredKeys, setFilteredKeys] = useState<{ catalogue: FlightCatalogue; keys: string[] } | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState>(null);
  const [mutatingIssues, setMutatingIssues] = useState(false);

  const mounted = useRef(true);
  const toggleFilteredSeqRef = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError('');
      try {
        const value = await api.catalogue(paramsFor(filters, page, pageSize), signal);
        setCatalogue(value);
        setPage(value.page || 1);
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
    [filters, page, pageSize],
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
    patchStoredFlightState({ filters, page, pageSize });
  }, [filters, page, pageSize]);

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
    const result = validateFlightDraft(draft, catalogue);
    if (result.error || !result.filters) {
      setError(result.error ?? '筛选条件无效');
      return false;
    }
    setError('');
    setFilters(result.filters);
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

  const mapLoader = useMapBatchLoader<{ flight_key: string; label?: string }, MapFlightInput>({
    kind: 'flights',
    unitLabel: '航班',
    page,
    totalPages: catalogue?.total_pages ?? 0,
    getKey: item => item.flight_key,
    fetchEntry: async (item, signal) => {
      const geometry = await api.geometry(item.flight_key, signal);
      return {
        geometry,
        label: item.label || geometry.flight_id,
        trajectoryVisible: true,
        pathVisible: true,
      };
    },
    onCommitAdd: entries => dispatch({ type: 'map-flights-batch', entries }),
    onCommitReplace: entries =>
      dispatch({
        type: 'replace-map-flights-batch',
        entries,
        isolateFirst: true,
        preserveView: splitView,
      }),
    fetchPage: async targetPage => {
      const nextCatalogue = await api.catalogue(paramsFor(filters, targetPage, pageSize));
      if (mounted.current) {
        setCatalogue(nextCatalogue);
        setPage(nextCatalogue.page || targetPage);
      }
      return {
        items: nextCatalogue.items.map(item => ({ flight_key: item.flight_key, label: item.flight_id })),
        page: nextCatalogue.page || targetPage,
      };
    },
    onError: setError,
  });

  const addSelectedToMap = () => {
    const pending = [...wb.matchSelection]
      .filter(key => !wb.mapFlights.has(key))
      .map(flight_key => ({ flight_key }));
    if (!pending.length) {
      if (wb.matchSelection.size > 0) {
        dispatch({ type: 'fit-map-flights', preserveView: splitView });
        dispatch({ type: 'status', value: `所选 ${wb.matchSelection.size} 条航班均已在地图中` });
      }
      return;
    }
    mapLoader.addItems(pending);
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
    if (!dialog || dialog.kind !== 'match') return;
    try {
      await submitMatches(dialog.keys, dialog.force);
      await load();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '任务提交失败');
    }
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
  const advancedActiveCount = useMemo(
    () => countAdvancedFlightFilters(filters, datasetMax),
    [filters, datasetMax],
  );
  const activeChips = useMemo(
    () => buildFlightFilterChips(filters, datasetMax, applyFilterPatch),
    [filters, datasetMax, applyFilterPatch],
  );

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
        pageCount={catalogue?.items.length ?? 0}
        allPageSelected={allPageSelected}
        allResultsChecked={allResultsIntent ?? allResultsSelected}
        canEditIssues={Boolean(catalogue?.can_edit_issues)}
        mutatingIssues={mutatingIssues}
        addingProgress={mapLoader.addingProgress}
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
        onReplacePageToMap={() =>
          void mapLoader.replaceItems(
            (catalogue?.items ?? []).map(item => ({ flight_key: item.flight_key, label: item.flight_id })),
            catalogue?.page || page,
          )
        }
        onCancelAddToMap={mapLoader.cancel}
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
        <TablePagination
          page={catalogue?.page || 0}
          totalPages={catalogue?.total_pages ?? 0}
          totalItems={catalogue?.total ?? 0}
          itemLabel="条"
          pageSize={pageSize}
          disabled={loading}
          onPageChange={setPage}
          onPageSizeChange={nextSize => {
            setPageSize(nextSize);
            setPage(1);
          }}
        />
      </PaginationFooter>

      <FlightConfirmDialog
        dialog={confirmDialog}
        onClose={() => setConfirmDialog(null)}
        onConfirm={() => void executeConfirm()}
      />
      <MapBatchConfirmDialog dialog={mapLoader.confirmDialog} onClose={mapLoader.dismissConfirm} />
    </section>
  );
}
