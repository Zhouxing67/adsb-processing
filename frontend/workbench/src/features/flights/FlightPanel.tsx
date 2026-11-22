import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Calendar as CalendarIcon, Crosshair, Filter, MapPinPlus, RotateCcw, Search, X } from 'lucide-react';
import { format, isValid, parseISO } from 'date-fns';
import type { DateRange } from 'react-day-picker';
import { ApiError, api } from '@/api/client';
import type { FlightCatalogueQuery } from '@/api/client';
import type { FlightCatalogue, FlightDetail, FlightItem, MapFlightEntry, MatchStatus } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
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

const movementLabels: Record<string, string> = {
  arrival: '进港',
  departure: '离港',
  unknown: '未知',
};

const ALL_VALUE = '__all__';

function toDate(value: string): Date | undefined {
  if (!value) return undefined;
  const parsed = parseISO(value);
  return isValid(parsed) ? parsed : undefined;
}

function toIsoDate(value?: Date): string {
  return value && isValid(value) ? format(value, 'yyyy-MM-dd') : '';
}

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

type ConfirmDialogState =
  | { kind: 'match'; keys: string[]; force: boolean }
  | { kind: 'bulk-map'; pending: string[] }
  | null;

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
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [standSearch, setStandSearch] = useState('');
  const [editingStand, setEditingStand] = useState<{ key: string; value: string } | null>(null);
  const [standEditSearch, setStandEditSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [addingProgress, setAddingProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState('');
  const [pageError, setPageError] = useState('');
  const [progress, setProgress] = useState<MatchStatus['progress'] | null>(null);
  const [tracking, setTracking] = useState(false);
  const [allResultsIntent, setAllResultsIntent] = useState<boolean | null>(null);
  const [filteredKeys, setFilteredKeys] = useState<string[] | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState>(null);

  const restored = useRef(false);
  const mounted = useRef(true);
  const addAbortRef = useRef<AbortController | null>(null);
  const toggleFilteredSeqRef = useRef(0);
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
    if (restored.current) return;
    restored.current = true;
    void (async () => {
      const valid = new Set((await api.filteredFlights({})).flight_keys);
      dispatch({ type: 'prune-match-selection', keys: [...valid] });
      const displayed = (saved.displayed ?? []).filter(item => valid.has(item.key));
      const concurrency = 5;
      let cursor = 0;
      const restoredEntries: Array<{ key: string; value: MapFlightEntry }> = [];
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

  const applyFilterPatch = (patch: Partial<FlightFilters>) => {
    const next = { ...filters, ...patch };
    setFilters(next);
    const nextDraft = toDraft(next);
    if (!nextDraft.start && !nextDraft.end && catalogue?.dataset_min_date && catalogue?.dataset_max_date) {
      nextDraft.start = catalogue.dataset_min_date;
      nextDraft.end = catalogue.dataset_max_date;
    }
    setDraft(nextDraft);
    setPage(1);
    setError('');
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
    let buffer: Array<{ key: string; value: MapFlightEntry }> = [];
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
      setConfirmDialog({ kind: 'bulk-map', pending });
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
      await api.submitMatches(dialog.keys, dialog.force);
      setTracking(true);
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

  const datasetMax = catalogue?.dataset_max_points ?? null;
  const advancedActiveCount = useMemo(() => {
    let count = 0;
    if (filters.stands.length > 0) count += 1;
    if (filters.minimum > 0) count += 1;
    if (filters.maximum !== null && datasetMax !== null && filters.maximum < datasetMax) count += 1;
    if (filters.start || filters.end) count += 1;
    if (filters.validation) count += 1;
    return count;
  }, [filters, datasetMax]);

  const activeChips = useMemo(() => {
    const chips: Array<{ id: string; label: string; clear: () => void }> = [];
    if (filters.query) {
      chips.push({ id: 'q', label: `搜索: ${filters.query}`, clear: () => applyFilterPatch({ query: '' }) });
    }
    if (filters.movement) {
      chips.push({
        id: 'movement',
        label: `进出港: ${movementLabels[filters.movement] ?? filters.movement}`,
        clear: () => applyFilterPatch({ movement: '' }),
      });
    }
    if (filters.status) {
      chips.push({
        id: 'status',
        label: `状态: ${statusLabels[filters.status] ?? filters.status}`,
        clear: () => applyFilterPatch({ status: '' }),
      });
    }
    if (filters.stands.length) {
      const standText = filters.stands.map(s => s || '空机位').join(', ');
      chips.push({
        id: 'stands',
        label: `机位: ${standText}`,
        clear: () => applyFilterPatch({ stands: [] }),
      });
    }
    if (filters.minimum > 0) {
      chips.push({
        id: 'min',
        label: `观测点 ≥ ${filters.minimum}`,
        clear: () => applyFilterPatch({ minimum: 0 }),
      });
    }
    if (filters.maximum !== null && datasetMax !== null && filters.maximum < datasetMax) {
      chips.push({
        id: 'max',
        label: `观测点 ≤ ${filters.maximum}`,
        clear: () => applyFilterPatch({ maximum: datasetMax }),
      });
    }
    if (filters.start || filters.end) {
      chips.push({
        id: 'date',
        label: `日期: ${filters.start || '不限'} ~ ${filters.end || '不限'}`,
        clear: () => applyFilterPatch({ start: '', end: '' }),
      });
    }
    if (filters.validation) {
      chips.push({
        id: 'validation',
        label: '仅验证航班',
        clear: () => applyFilterPatch({ validation: false }),
      });
    }
    return chips;
  }, [filters, datasetMax]);

  const hasProgressActivity = Boolean(
    progress && progress.waiting + progress.running + progress.success + progress.failed > 0,
  );

  const statusBadgeVariant = (status: string) => {
    if (status === 'success') return 'success' as const;
    if (status === 'failed') return 'destructive' as const;
    if (status === 'matching' || status === 'queued') return 'warning' as const;
    return 'secondary' as const;
  };

  return (
    <section
      id="flight-sheet"
      className={cn(
        'main-view flight-sheet absolute inset-0 flex h-full w-full min-h-0 min-w-0 flex-col overflow-hidden bg-background',
        !active && 'hidden',
      )}
    >
      <header className="flex shrink-0 items-baseline justify-between border-b border-border px-4 py-2.5">
        <h2 className="m-0 text-[15px] font-semibold text-foreground">航班</h2>
        <span className="text-[11px] text-muted-foreground tabular-nums">
          {catalogue ? `第 ${catalogue.page || 0} / ${catalogue.total_pages} 页（${catalogue.total} 条）` : ''}
        </span>
      </header>

      <div className="shrink-0 space-y-2 border-b border-border bg-muted/60 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[140px] max-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={draft.query}
              placeholder="航班号 / ID"
              className="pl-8"
              onChange={event => setDraft({ ...draft, query: event.target.value })}
              onKeyDown={event => {
                if (event.key === 'Enter') validateAndApply();
              }}
            />
          </div>

          <Select
            value={draft.movement || ALL_VALUE}
            onValueChange={value => setDraft({ ...draft, movement: value === ALL_VALUE ? '' : value })}
          >
            <SelectTrigger aria-label="进出港" className="w-[104px] shrink-0">
              <SelectValue placeholder="进出港" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUE}>全部进出港</SelectItem>
              <SelectItem value="arrival">进港</SelectItem>
              <SelectItem value="departure">离港</SelectItem>
              <SelectItem value="unknown">未知</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={draft.status || ALL_VALUE}
            onValueChange={value => setDraft({ ...draft, status: value === ALL_VALUE ? '' : value })}
          >
            <SelectTrigger aria-label="匹配状态" className="w-[104px] shrink-0">
              <SelectValue placeholder="匹配状态" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUE}>全部状态</SelectItem>
              {Object.entries(statusLabels).map(([key, label]) => (
                <SelectItem key={key} value={key}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Popover open={advancedOpen} onOpenChange={setAdvancedOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" size="default" className="shrink-0">
                <Filter className="h-3.5 w-3.5 text-muted-foreground" />
                更多筛选
                {advancedActiveCount > 0 && (
                  <Badge variant="default" className="ml-0.5 rounded-full px-1.5 py-0 text-[10px]">
                    {advancedActiveCount}
                  </Badge>
                )}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-80 space-y-3 p-3.5">
              <div className="space-y-1.5">
                <span className="text-xs font-medium text-foreground">机位筛选</span>
                <Input
                  type="search"
                  aria-label="搜索机位"
                  placeholder="搜索机位…"
                  value={standSearch}
                  onChange={event => setStandSearch(event.target.value)}
                />
                <ScrollArea className="h-32 rounded-md border border-border bg-muted/30 p-1">
                  <div className="space-y-0.5">
                    {visibleStands.map(stand => {
                      const checked = draft.stands.includes(stand);
                      const label = stand || '空机位';
                      return (
                        <label
                          key={stand || '__empty'}
                          className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs text-foreground hover:bg-accent"
                        >
                          <Checkbox
                            aria-label={label}
                            checked={checked}
                            onCheckedChange={next => {
                              const isChecked = next === true;
                              setDraft(value => ({
                                ...value,
                                stands: isChecked
                                  ? [...value.stands, stand]
                                  : value.stands.filter(item => item !== stand),
                              }));
                            }}
                          />
                          <span>{label}</span>
                        </label>
                      );
                    })}
                  </div>
                </ScrollArea>
              </div>

              <Separator />

              <div className="grid grid-cols-2 gap-2">
                <label className="space-y-1">
                  <span className="text-xs text-muted-foreground">最小观测点数</span>
                  <Input
                    type="number"
                    min={0}
                    aria-label="最小观测点数"
                    placeholder="最小值"
                    value={draft.minimum}
                    onChange={event => setDraft({ ...draft, minimum: event.target.value })}
                    onKeyDown={event => {
                      if (event.key === 'Enter' && validateAndApply()) setAdvancedOpen(false);
                    }}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-xs text-muted-foreground">最大观测点数</span>
                  <Input
                    type="number"
                    min={0}
                    aria-label="最大观测点数"
                    placeholder="最大值"
                    value={draft.maximum}
                    onChange={event => setDraft({ ...draft, maximum: event.target.value })}
                    onKeyDown={event => {
                      if (event.key === 'Enter' && validateAndApply()) setAdvancedOpen(false);
                    }}
                  />
                </label>
              </div>

              <div className="space-y-1">
                <span className="text-xs text-muted-foreground">日期范围</span>
                <Popover open={datePickerOpen} onOpenChange={setDatePickerOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      variant="outline"
                      size="default"
                      aria-label="日期范围"
                      className="w-full justify-start gap-2 font-normal text-foreground tabular-nums"
                    >
                      <CalendarIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate">
                        {draft.start && draft.end
                          ? `${draft.start} 至 ${draft.end}`
                          : draft.start
                            ? `${draft.start} 起`
                            : draft.end
                              ? `至 ${draft.end}`
                              : '选择日期范围'}
                      </span>
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="start" className="w-auto p-0">
                    <Calendar
                      mode="range"
                      defaultMonth={toDate(draft.start) ?? toDate(catalogue?.dataset_min_date ?? '')}
                      selected={{ from: toDate(draft.start), to: toDate(draft.end) } as DateRange}
                      onSelect={range => {
                        setDraft(current => ({
                          ...current,
                          start: toIsoDate(range?.from),
                          end: toIsoDate(range?.to ?? range?.from),
                        }));
                      }}
                    />
                    <div className="flex items-center justify-between border-t border-border px-3 py-2">
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => {
                          setDraft(current => ({
                            ...current,
                            start: catalogue?.dataset_min_date ?? '',
                            end: catalogue?.dataset_max_date ?? '',
                          }));
                        }}
                      >
                        恢复全部日期
                      </Button>
                      <Button variant="default" size="xs" onClick={() => setDatePickerOpen(false)}>
                        确定
                      </Button>
                    </div>
                  </PopoverContent>
                </Popover>
              </div>

              {catalogue?.supports_validation_filter && (
                <label className="flex cursor-pointer items-center gap-2 text-xs text-foreground">
                  <Checkbox
                    checked={draft.validation}
                    onCheckedChange={checked => setDraft({ ...draft, validation: checked === true })}
                  />
                  <span>验证航班（≥30 点）</span>
                </label>
              )}

              <div className="flex items-center justify-end gap-1.5 border-t border-border pt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    resetFilters();
                    setAdvancedOpen(false);
                  }}
                >
                  重置
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => {
                    if (validateAndApply()) setAdvancedOpen(false);
                  }}
                >
                  应用
                </Button>
              </div>
            </PopoverContent>
          </Popover>

          <Button variant="default" size="default" className="shrink-0" onClick={validateAndApply}>
            过滤
          </Button>
        </div>

        {activeChips.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            {activeChips.map(chip => (
              <Badge key={chip.id} variant="outline" className="gap-1 bg-background pr-1 text-[11px] font-normal">
                <span>{chip.label}</span>
                <button
                  type="button"
                  aria-label={`移除筛选 ${chip.label}`}
                  className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground cursor-pointer"
                  onClick={chip.clear}
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </Badge>
            ))}
            <Button variant="ghost" size="xs" className="h-5 px-1.5 text-[11px] text-muted-foreground" onClick={resetFilters}>
              <RotateCcw className="h-3 w-3" />
              重置
            </Button>
          </div>
        )}

        {error && (
          <p className="m-0 text-xs font-medium text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>

      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-1.5">
        <div className="flex flex-wrap items-center gap-3">
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-foreground">
            <Checkbox
              aria-label="选择本页航班"
              checked={allPageSelected}
              onCheckedChange={() =>
                catalogue?.items.forEach(item =>
                  dispatch({ type: 'toggle-match', key: item.flight_key, checked: !allPageSelected }),
                )
              }
            />
            <span>选择本页</span>
          </label>
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-foreground">
            <Checkbox
              aria-label="选择全部结果"
              checked={allResultsIntent ?? allResultsSelected}
              onCheckedChange={checked => {
                const next = checked === true;
                setAllResultsIntent(next);
                void toggleFiltered(next);
              }}
            />
            <span>选择全部结果</span>
          </label>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="清空所选航班"
            title="清空所选航班"
            disabled={!wb.matchSelection.size}
            onClick={() => dispatch({ type: 'set-match-selection', keys: [] })}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
          <span className="text-[11px] text-muted-foreground tabular-nums">已选 {wb.matchSelection.size} 条</span>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            variant="outline"
            size="sm"
            disabled={!wb.matchSelection.size || Boolean(addingProgress)}
            onClick={addSelectedToMap}
          >
            <MapPinPlus className="h-3.5 w-3.5" />
            {addingProgress ? `加入中 (${addingProgress.done}/${addingProgress.total})` : '所选加入地图'}
          </Button>
          {addingProgress && (
            <Button variant="ghost" size="sm" onClick={() => addAbortRef.current?.abort()}>
              取消加入
            </Button>
          )}
          <Button
            variant="default"
            size="sm"
            disabled={!wb.matchSelection.size || tracking}
            onClick={() => requestSubmit()}
          >
            {tracking ? '匹配中…' : '匹配所选航班'}
          </Button>
        </div>
      </div>

      {hasProgressActivity && progress && (
        <section className="flex shrink-0 items-center gap-4 border-b border-border bg-muted/70 px-4 py-1.5 text-[11px]">
          <strong className="font-medium text-foreground">批量任务</strong>
          <dl className="m-0 flex items-center gap-4 tabular-nums">
            <div className="flex items-baseline gap-1">
              <dt className="text-muted-foreground">等待</dt>
              <dd className="m-0 font-semibold text-foreground">{progress.waiting}</dd>
            </div>
            <div className="flex items-baseline gap-1">
              <dt className="text-muted-foreground">运行</dt>
              <dd className="m-0 font-semibold text-amber-700">{progress.running}</dd>
            </div>
            <div className="flex items-baseline gap-1">
              <dt className="text-muted-foreground">成功</dt>
              <dd className="m-0 font-semibold text-emerald-700">{progress.success}</dd>
            </div>
            <div className="flex items-baseline gap-1">
              <dt className="text-muted-foreground">失败</dt>
              <dd className="m-0 font-semibold text-destructive">{progress.failed}</dd>
            </div>
          </dl>
        </section>
      )}

      <div className="relative min-h-0 flex-1 overflow-auto">
        <table className="sheet-table w-full min-w-[740px] border-collapse text-left">
          <thead>
            <tr className="border-b border-border bg-muted text-xs font-medium text-muted-foreground">
              <th className="sticky top-0 z-[2] bg-muted px-3 py-2 whitespace-nowrap">选择</th>
              <th className="sticky top-0 z-[2] bg-muted px-3 py-2 whitespace-nowrap">航班</th>
              <th className="sticky top-0 z-[2] bg-muted px-3 py-2 whitespace-nowrap">进出港</th>
              <th className="sticky top-0 z-[2] bg-muted px-3 py-2 whitespace-nowrap">机位</th>
              <th className="sticky top-0 z-[2] bg-muted px-3 py-2 whitespace-nowrap">状态</th>
              <th className="sticky top-0 z-[2] bg-muted px-3 py-2 whitespace-nowrap">观测点</th>
              <th className="sticky top-0 z-[2] bg-muted px-3 py-2 whitespace-nowrap">开始时间</th>
              <th className="sticky top-0 z-[2] bg-muted px-3 py-2 whitespace-nowrap">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/70">
            {catalogue?.items.map(item => {
              const onMap = wb.mapFlights.has(item.flight_key);
              const standOpen = editingStand?.key === item.flight_key;
              return (
                <tr key={item.flight_key} className="transition-colors hover:bg-muted/40">
                  <td className="px-3 py-2 align-middle">
                    <Checkbox
                      aria-label={`选择航班 ${item.flight_id}`}
                      checked={wb.matchSelection.has(item.flight_key)}
                      onCheckedChange={checked =>
                        dispatch({ type: 'toggle-match', key: item.flight_key, checked: checked === true })
                      }
                    />
                  </td>
                  <td className="px-3 py-2 align-middle whitespace-nowrap">
                    <strong className="block font-medium text-foreground">{item.flight_number || item.flight_id}</strong>
                    <small className="block text-[11px] text-muted-foreground">{item.flight_id}</small>
                  </td>
                  <td className="px-3 py-2 align-middle whitespace-nowrap text-foreground">
                    {movementLabels[item.movement_type] ?? '未知'}
                  </td>
                  <td className="px-3 py-2 align-middle whitespace-nowrap">
                    {item.can_edit_stand ? (
                      <Popover
                        open={standOpen}
                        onOpenChange={open => {
                          if (open) {
                            setEditingStand({ key: item.flight_key, value: item.stand_position ?? '' });
                            setStandEditSearch('');
                          } else if (standOpen) {
                            setEditingStand(null);
                          }
                        }}
                      >
                        <PopoverTrigger asChild>
                          <button
                            type="button"
                            className="stand-edit-trigger cursor-pointer border-0 border-b border-dashed border-zinc-400 bg-transparent px-0 py-0.5 text-[13px] text-foreground transition-colors hover:border-foreground"
                            title="点击编辑机位"
                          >
                            {item.stand_position || '选择机位'}
                          </button>
                        </PopoverTrigger>
                        <PopoverContent
                          role="dialog"
                          aria-label={`编辑 ${item.flight_id} 机位`}
                          className="w-60 space-y-2 p-2.5"
                        >
                          <Input
                            type="search"
                            aria-label="搜索可选机位"
                            placeholder="搜索机位"
                            value={standEditSearch}
                            onChange={event => setStandEditSearch(event.target.value)}
                          />
                          <ScrollArea className="h-44">
                            <RadioGroup
                              value={editingStand?.value ? editingStand.value : '__empty__'}
                              onValueChange={value =>
                                setEditingStand({ key: item.flight_key, value: value === '__empty__' ? '' : value })
                              }
                              className="gap-0.5 pr-2"
                            >
                              {editableStands.map(stand => {
                                const label = stand || '空机位';
                                return (
                                  <label
                                    key={stand || '__empty'}
                                    className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs text-foreground hover:bg-accent"
                                  >
                                    <RadioGroupItem value={stand || '__empty__'} aria-label={label} />
                                    <span>{label}</span>
                                  </label>
                                );
                              })}
                            </RadioGroup>
                          </ScrollArea>
                          <div className="flex justify-end gap-1.5 border-t border-border pt-2">
                            <Button variant="ghost" size="sm" onClick={() => setEditingStand(null)}>
                              取消
                            </Button>
                            <Button variant="default" size="sm" onClick={() => void saveStand()}>
                              保存
                            </Button>
                          </div>
                        </PopoverContent>
                      </Popover>
                    ) : (
                      <span className="text-muted-foreground">{item.stand_position || '—'}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 align-middle whitespace-nowrap">
                    <Badge variant={statusBadgeVariant(item.match.status)}>
                      {statusLabels[item.match.status] || item.match.status}
                    </Badge>
                    {item.match.error && (
                      <small className="ml-1.5 text-[11px] text-destructive" title={item.match.error}>
                        {item.match.failure_type}
                      </small>
                    )}
                  </td>
                  <td className="px-3 py-2 align-middle whitespace-nowrap tabular-nums text-foreground">
                    {item.point_count}
                  </td>
                  <td className="px-3 py-2 align-middle whitespace-nowrap tabular-nums text-muted-foreground">
                    {item.start_time.replace('T', ' ').slice(0, 19)}
                  </td>
                  <td className="px-3 py-2 align-middle whitespace-nowrap">
                    <div className="flex items-center gap-0.5">
                      <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => void showDetail(item)}>
                        详情
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => void toggleMap(item)}>
                        {onMap ? '移出地图' : '加入地图'}
                      </Button>
                      {onMap && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="flight-locate-action h-7 px-2"
                          onClick={() => dispatch({ type: 'focus-flight', key: item.flight_key, preserveView: splitView })}
                        >
                          <Crosshair className="h-3.5 w-3.5" />
                          定位
                        </Button>
                      )}
                      {item.match.status === 'failed' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-destructive hover:text-destructive"
                          onClick={() => requestSubmit([item.flight_key], true)}
                        >
                          重试
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {loading && (
          <div className="absolute inset-0 z-10 grid cursor-wait place-items-center bg-white/40">
            <span className="h-6 w-6 animate-spin rounded-full border-[3px] border-zinc-200 border-t-zinc-900" />
          </div>
        )}
      </div>

      <footer className="flex shrink-0 flex-wrap items-center justify-center gap-2 border-t border-border bg-background px-4 py-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>
          上一页
        </Button>
        <span className="text-xs text-muted-foreground tabular-nums">
          {catalogue ? `${catalogue.page || 0}/${catalogue.total_pages}` : '—'}
        </span>
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
      </footer>

      <AlertDialog open={confirmDialog !== null} onOpenChange={open => { if (!open) setConfirmDialog(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirmDialog?.kind === 'bulk-map' ? '批量加入地图确认' : '提交航班匹配'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirmDialog?.kind === 'bulk-map'
                ? `即将向地图加入 ${confirmDialog.pending.length} 架航班，数量较大可能影响地图流畅度，是否继续？`
                : `确认提交 ${confirmDialog?.keys.length ?? 0} 条航班进行路径匹配？`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={() => void executeConfirm()}>
              {confirmDialog?.kind === 'bulk-map' ? '继续加入' : '确认提交'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
