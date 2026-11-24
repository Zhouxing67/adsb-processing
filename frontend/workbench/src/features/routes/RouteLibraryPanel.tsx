import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Check,
  Crosshair,
  Layers,
  MapPinPlus,
  MessageSquare,
  RefreshCw,
  RotateCcw,
  Search,
  X,
} from 'lucide-react';
import { ApiError, api } from '@/api/client';
import type { RouteListQuery } from '@/api/client';
import type { MapRouteEntry, RouteItem, RouteList } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  MOVEMENT_LABELS as movementLabels,
  ROUTE_SOURCE_LABELS as sourceLabels,
  ROUTE_STATUS_LABELS as statusLabels,
} from '@/domain/palette';
import { cn } from '@/lib/utils';

const ALL_VALUE = '__all__';
const NULL_RUNWAY_VALUE = '__null__';

const STATUS_ORDER = ['candidate', 'verified', 'rejected', 'manual'] as const;

function routeLabel(item: RouteItem): string {
  const dir = movementLabels[item.movement] ?? item.movement;
  const rwy = item.runway_ref ?? '无跑道';
  const od = item.movement === 'departure' ? `${item.stand_ref} → ${rwy}` : `${rwy} → ${item.stand_ref}`;
  return `${dir} ${od}`;
}

function statusBadgeVariant(status: string) {
  if (status === 'verified' || status === 'manual') return 'success' as const;
  if (status === 'rejected') return 'destructive' as const;
  return 'secondary' as const;
}

interface RouteFilters {
  query: string;
  movement: string;
  stand: string;
  runway: string;
  status: string;
  allGraphs: boolean;
}

const defaultRouteFilters: RouteFilters = {
  query: '',
  movement: '',
  stand: '',
  runway: '',
  status: '',
  allGraphs: false,
};

function paramsFor(filters: RouteFilters, page: number): RouteListQuery {
  return {
    q: filters.query.trim() || undefined,
    movement: filters.movement || undefined,
    stand_ref: filters.stand || undefined,
    runway_ref: filters.runway && filters.runway !== NULL_RUNWAY_VALUE ? filters.runway : undefined,
    runway_is_null: filters.runway === NULL_RUNWAY_VALUE ? true : undefined,
    status: filters.status || undefined,
    all_graphs: filters.allGraphs || undefined,
    page,
    page_size: 20,
  };
}

interface RouteLibraryPanelProps {
  active?: boolean;
  splitView?: boolean;
}

export function RouteLibraryPanel({ active = true, splitView = false }: RouteLibraryPanelProps) {
  const wb = useWorkbench();
  const [draft, setDraft] = useState<RouteFilters>(defaultRouteFilters);
  const [filters, setFilters] = useState<RouteFilters>(defaultRouteFilters);
  const [data, setData] = useState<RouteList | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busyRouteId, setBusyRouteId] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<{ routeId: string; status: string; note: string } | null>(null);
  const [savingReview, setSavingReview] = useState(false);
  const nextSlotRef = useRef(0);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError('');
      try {
        const result = await api.routes(paramsFor(filters, page), signal);
        setData(result);
        if (result.page > 0 && result.page !== page) setPage(result.page);
      } catch (failure) {
        if ((failure as Error).name !== 'AbortError') {
          if (failure instanceof ApiError && failure.detail?.context?.total_pages !== undefined) {
            setPage(Math.max(1, Number(failure.detail.context.total_pages)));
          } else {
            setError(failure instanceof Error ? failure.message : '路径库加载失败');
          }
        }
      } finally {
        setLoading(false);
      }
    },
    [filters, page],
  );

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [active, load]);

  const allocateSlot = () => {
    let maxSlot = nextSlotRef.current - 1;
    wb.mapRoutes.forEach(entry => {
      if (entry.slot > maxSlot) maxSlot = entry.slot;
    });
    nextSlotRef.current = maxSlot + 1;
    return nextSlotRef.current++;
  };

  const toggleOnMap = async (item: RouteItem, focus = false) => {
    if (wb.mapRoutes.has(item.route_id)) {
      if (focus) {
        wb.dispatch({ type: 'focus-route', routeId: item.route_id, preserveView: splitView });
      } else {
        wb.dispatch({ type: 'map-route', routeId: item.route_id, value: null });
      }
      return;
    }
    if (!item.matches_current_graph) {
      wb.dispatch({ type: 'error', value: '该路径属于历史机场图版本，无法在当前地图上渲染' });
      return;
    }
    setBusyRouteId(item.route_id);
    try {
      const geometry = await api.routeGeometry(item.route_id);
      const entry: MapRouteEntry = {
        geometry,
        label: routeLabel(item),
        slot: allocateSlot(),
        visible: true,
      };
      wb.dispatch({ type: 'map-route', routeId: item.route_id, value: entry });
      if (focus) {
        wb.dispatch({ type: 'focus-route', routeId: item.route_id, preserveView: splitView });
      } else {
        wb.dispatch({ type: 'status', value: `已将路径 ${entry.label} 加入地图` });
      }
    } catch (failure) {
      wb.dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '路径几何加载失败' });
    } finally {
      setBusyRouteId(current => (current === item.route_id ? null : current));
    }
  };

  const overlaySameOd = async (item: RouteItem) => {
    if (!data) return;
    const peers = data.items.filter(
      candidate =>
        candidate.matches_current_graph &&
        candidate.movement === item.movement &&
        candidate.stand_ref === item.stand_ref &&
        candidate.runway_ref === item.runway_ref,
    );
    const pending = peers.filter(candidate => !wb.mapRoutes.has(candidate.route_id));
    if (pending.length === 0) {
      wb.dispatch({ type: 'fit-map-routes', preserveView: splitView });
      return;
    }
    setBusyRouteId(item.route_id);
    try {
      const geometries = await Promise.all(pending.map(candidate => api.routeGeometry(candidate.route_id)));
      const entries = geometries.map((geometry, idx) => ({
        routeId: pending[idx].route_id,
        value: {
          geometry,
          label: routeLabel(pending[idx]),
          slot: allocateSlot(),
          visible: true,
        },
      }));
      wb.dispatch({ type: 'map-routes-batch', entries });
      wb.dispatch({ type: 'fit-map-routes', preserveView: splitView });
      wb.dispatch({
        type: 'status',
        value: `已将 ${routeLabel(item)} 下的 ${peers.length} 条路径叠加到地图`,
      });
    } catch (failure) {
      wb.dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '批量加载路径失败' });
    } finally {
      setBusyRouteId(current => (current === item.route_id ? null : current));
    }
  };

  const applyReview = async (routeId: string, status: string, note: string | null) => {
    setSavingReview(true);
    try {
      const updated = await api.updateRouteReview(routeId, { status, note });
      setData(current => {
        if (!current) return current;
        const prev = current.items.find(item => item.route_id === routeId);
        const nextCounts = { ...current.status_counts };
        if (prev && prev.status !== updated.status) {
          nextCounts[prev.status] = Math.max(0, (nextCounts[prev.status] ?? 0) - 1);
          nextCounts[updated.status] = (nextCounts[updated.status] ?? 0) + 1;
        }
        return {
          ...current,
          status_counts: nextCounts,
          items: current.items.map(item => (item.route_id === routeId ? updated : item)),
        };
      });
      const existingMapRoute = wb.mapRoutes.get(routeId);
      if (existingMapRoute) {
        wb.dispatch({
          type: 'map-route',
          routeId,
          value: {
            ...existingMapRoute,
            geometry: { ...existingMapRoute.geometry, route: updated },
          },
        });
      }
      setReviewing(null);
      wb.dispatch({ type: 'status', value: `已更新路径状态为「${statusLabels[updated.status] ?? updated.status}」` });
    } catch (failure) {
      wb.dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '路径审校更新失败' });
    } finally {
      setSavingReview(false);
    }
  };

  const applyFilters = () => {
    setPage(1);
    setFilters(draft);
  };

  const resetFilters = () => {
    setDraft(defaultRouteFilters);
    setFilters(defaultRouteFilters);
    setPage(1);
  };

  const odCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of data?.items ?? []) {
      const key = `${item.movement}\0${item.stand_ref}\0${item.runway_ref ?? ''}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [data]);

  const totalAllStatuses = useMemo(
    () => Object.values(data?.status_counts ?? {}).reduce((sum, count) => sum + count, 0),
    [data],
  );

  return (
    <section
      className={cn(
        'route-library-panel flex h-full w-full flex-col bg-background',
        !active && 'hidden',
      )}
    >
      <div className="flex flex-col gap-2 border-b border-border px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[180px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="搜索路径库"
              placeholder="搜索机位、跑道、路径 ID 或备注…"
              className="h-8 pl-8 text-xs"
              value={draft.query}
              onChange={event => setDraft(current => ({ ...current, query: event.target.value }))}
              onKeyDown={event => {
                if (event.key === 'Enter') applyFilters();
              }}
            />
          </div>

          <Select
            value={draft.movement || ALL_VALUE}
            onValueChange={value => {
              const next = value === ALL_VALUE ? '' : value;
              setDraft(current => ({ ...current, movement: next }));
              setFilters(current => ({ ...current, movement: next }));
              setPage(1);
            }}
          >
            <SelectTrigger aria-label="路径进出港" className="h-8 w-[96px] text-xs">
              <SelectValue placeholder="进出港" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUE}>全部方向</SelectItem>
              <SelectItem value="departure">离港</SelectItem>
              <SelectItem value="arrival">进港</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={draft.stand || ALL_VALUE}
            onValueChange={value => {
              const next = value === ALL_VALUE ? '' : value;
              setDraft(current => ({ ...current, stand: next }));
              setFilters(current => ({ ...current, stand: next }));
              setPage(1);
            }}
          >
            <SelectTrigger aria-label="路径机位" className="h-8 w-[108px] text-xs">
              <SelectValue placeholder="机位" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUE}>全部机位</SelectItem>
              {(data?.stand_options ?? []).map(stand => (
                <SelectItem key={stand} value={stand}>
                  {stand}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={draft.runway || ALL_VALUE}
            onValueChange={value => {
              const next = value === ALL_VALUE ? '' : value;
              setDraft(current => ({ ...current, runway: next }));
              setFilters(current => ({ ...current, runway: next }));
              setPage(1);
            }}
          >
            <SelectTrigger aria-label="路径跑道" className="h-8 w-[108px] text-xs">
              <SelectValue placeholder="跑道" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_VALUE}>全部跑道</SelectItem>
              <SelectItem value={NULL_RUNWAY_VALUE}>缺失跑道</SelectItem>
              {(data?.runway_options ?? []).map(rwy => (
                <SelectItem key={rwy} value={rwy}>
                  {rwy}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button variant="default" size="sm" className="h-8" onClick={applyFilters}>
            过滤
          </Button>
          <Button variant="ghost" size="sm" className="h-8 px-2" title="重置筛选" onClick={resetFilters}>
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 px-2"
            title="刷新路径库"
            disabled={loading}
            onClick={() => void load()}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </Button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex flex-wrap items-center gap-1">
            <button
              type="button"
              className={cn(
                'inline-flex h-6 cursor-pointer items-center gap-1 rounded-full border px-2.5 text-[11px] transition-colors',
                filters.status === ''
                  ? 'border-zinc-900 bg-zinc-900 text-white'
                  : 'border-border bg-background text-muted-foreground hover:text-foreground',
              )}
              onClick={() => {
                setDraft(current => ({ ...current, status: '' }));
                setFilters(current => ({ ...current, status: '' }));
                setPage(1);
              }}
            >
              全部
              <span className="tabular-nums opacity-75">{totalAllStatuses}</span>
            </button>
            {STATUS_ORDER.map(status => (
              <button
                key={status}
                type="button"
                className={cn(
                  'inline-flex h-6 cursor-pointer items-center gap-1 rounded-full border px-2.5 text-[11px] transition-colors',
                  filters.status === status
                    ? 'border-zinc-900 bg-zinc-900 text-white'
                    : 'border-border bg-background text-muted-foreground hover:text-foreground',
                )}
                onClick={() => {
                  setDraft(current => ({ ...current, status }));
                  setFilters(current => ({ ...current, status }));
                  setPage(1);
                }}
              >
                {statusLabels[status]}
                <span className="tabular-nums opacity-75">{data?.status_counts[status] ?? 0}</span>
              </button>
            ))}
          </div>

          <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-muted-foreground">
            <Checkbox
              checked={filters.allGraphs}
              onCheckedChange={checked => {
                const next = checked === true;
                setDraft(current => ({ ...current, allGraphs: next }));
                setFilters(current => ({ ...current, allGraphs: next }));
                setPage(1);
              }}
            />
            <span>显示全部图版本</span>
          </label>
        </div>
      </div>

      {error && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700" role="alert">
          {error}
        </div>
      )}

      <ScrollArea className="min-h-0 flex-1">
        {!loading && data && !data.has_route_library ? (
          <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center text-xs text-muted-foreground">
            <p className="text-sm font-medium text-foreground">当前数据库尚未初始化路径库</p>
            <p>批量匹配完成后，可运行以下命令将去重路径导入到 DuckDB：</p>
            <code className="rounded bg-muted px-2.5 py-1 font-mono text-[11px] text-foreground">
              uv run --extra stand-editing python -m route_library import outputs/path_map/&lt;run_id&gt;
            </code>
          </div>
        ) : !loading && data && data.items.length === 0 ? (
          <div className="px-6 py-16 text-center text-xs text-muted-foreground">
            当前筛选条件下暂无路径记录
          </div>
        ) : (
          <table className="w-full border-collapse text-left text-xs">
            <thead className="sticky top-0 z-10 border-b border-border bg-muted/90 text-[11px] font-medium text-muted-foreground backdrop-blur-xs">
              <tr>
                <th className="px-3 py-2">方向 / OD</th>
                <th className="px-3 py-2">规模</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">备注</th>
                <th className="px-3 py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/70">
              {(data?.items ?? []).map(item => {
                const onMap = wb.mapRoutes.has(item.route_id);
                const busy = busyRouteId === item.route_id;
                const odKey = `${item.movement}\0${item.stand_ref}\0${item.runway_ref ?? ''}`;
                const sameOdCount = odCounts.get(odKey) ?? 1;
                const isReviewOpen = reviewing?.routeId === item.route_id;
                return (
                  <tr
                    key={item.route_id}
                    className={cn(
                      'transition-colors hover:bg-muted/40',
                      onMap && 'bg-violet-50/45',
                    )}
                  >
                    <td className="px-3 py-2 align-middle">
                      <div className="flex items-center gap-1.5">
                        <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                          {movementLabels[item.movement] ?? item.movement}
                        </Badge>
                        <span className="font-medium text-foreground">
                          {item.movement === 'departure'
                            ? `${item.stand_ref} → ${item.runway_ref ?? '无跑道'}`
                            : `${item.runway_ref ?? '无跑道'} → ${item.stand_ref}`}
                        </span>
                        {!item.matches_current_graph && (
                          <Badge variant="warning" className="h-5 px-1.5 text-[10px]">
                            旧图
                          </Badge>
                        )}
                      </div>
                      <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                        {item.route_id} · {sourceLabels[item.source] ?? item.source}
                      </div>
                    </td>

                    <td className="px-3 py-2 align-middle tabular-nums">
                      <div className="font-medium text-foreground">{Math.round(item.total_length_m)} m</div>
                      <div className="text-[11px] text-muted-foreground">{item.edge_count} 条有向边</div>
                    </td>

                    <td className="px-3 py-2 align-middle">
                      <Badge variant={statusBadgeVariant(item.status)} className="text-[10px]">
                        {statusLabels[item.status] ?? item.status}
                      </Badge>
                    </td>

                    <td className="max-w-[200px] px-3 py-2 align-middle">
                      <span className="block truncate text-[11px] text-muted-foreground" title={item.note ?? ''}>
                        {item.note || '—'}
                      </span>
                    </td>

                    <td className="px-3 py-2 text-right align-middle">
                      <div className="inline-flex flex-wrap items-center justify-end gap-1">
                        <Button
                          variant={onMap ? 'secondary' : 'outline'}
                          size="xs"
                          className="h-6 px-2 text-[11px]"
                          disabled={busy || !item.matches_current_graph}
                          title={
                            !item.matches_current_graph
                              ? '路径所属图版本与当前图不一致'
                              : onMap
                                ? '从地图移除此路径'
                                : '叠加此路径到地图'
                          }
                          onClick={() => void toggleOnMap(item, false)}
                        >
                          <MapPinPlus className="h-3 w-3" />
                          {onMap ? '已在地图' : '上地图'}
                        </Button>

                        <Button
                          variant="ghost"
                          size="xs"
                          className="h-6 px-1.5 text-[11px]"
                          disabled={busy || !item.matches_current_graph}
                          title="在地图中定位此路径"
                          onClick={() => void toggleOnMap(item, true)}
                        >
                          <Crosshair className="h-3 w-3" />
                        </Button>

                        {sameOdCount > 1 && (
                          <Button
                            variant="ghost"
                            size="xs"
                            className="h-6 px-1.5 text-[11px]"
                            disabled={busy || !item.matches_current_graph}
                            title={`将该 OD 下本页 ${sameOdCount} 条路径同时叠加到地图对比`}
                            onClick={() => void overlaySameOd(item)}
                          >
                            <Layers className="h-3 w-3" />
                            同OD({sameOdCount})
                          </Button>
                        )}

                        {data?.can_edit && (
                          <>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              className={cn(
                                'h-6 w-6',
                                item.status === 'verified'
                                  ? 'text-emerald-600'
                                  : 'text-muted-foreground hover:text-emerald-600',
                              )}
                              disabled={savingReview}
                              title="标记为已通过（verified）"
                              aria-label={`通过路径 ${item.route_id}`}
                              onClick={() => void applyReview(item.route_id, 'verified', item.note)}
                            >
                              <Check className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              className={cn(
                                'h-6 w-6',
                                item.status === 'rejected'
                                  ? 'text-destructive'
                                  : 'text-muted-foreground hover:text-destructive',
                              )}
                              disabled={savingReview}
                              title="标记为已驳回（rejected）"
                              aria-label={`驳回路径 ${item.route_id}`}
                              onClick={() => void applyReview(item.route_id, 'rejected', item.note)}
                            >
                              <X className="h-3.5 w-3.5" />
                            </Button>
                            <Popover
                              open={isReviewOpen}
                              onOpenChange={open => {
                                if (open) {
                                  setReviewing({
                                    routeId: item.route_id,
                                    status: item.status,
                                    note: item.note ?? '',
                                  });
                                } else if (isReviewOpen) {
                                  setReviewing(null);
                                }
                              }}
                            >
                              <PopoverTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon-xs"
                                  className="h-6 w-6 text-muted-foreground hover:text-foreground"
                                  title="编辑审校状态与备注"
                                  aria-label={`编辑路径 ${item.route_id} 审校信息`}
                                >
                                  <MessageSquare className="h-3 w-3" />
                                </Button>
                              </PopoverTrigger>
                              <PopoverContent align="end" className="w-64 space-y-2.5 p-3">
                                <div className="text-xs font-medium text-foreground">路径审校</div>
                                <Select
                                  value={reviewing?.status ?? item.status}
                                  onValueChange={value =>
                                    setReviewing(current => (current ? { ...current, status: value } : null))
                                  }
                                >
                                  <SelectTrigger className="h-8 text-xs">
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {STATUS_ORDER.map(status => (
                                      <SelectItem key={status} value={status}>
                                        {statusLabels[status]}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                                <Input
                                  placeholder="填写审校备注（留空清空）"
                                  className="h-8 text-xs"
                                  value={reviewing?.note ?? ''}
                                  onChange={event =>
                                    setReviewing(current =>
                                      current ? { ...current, note: event.target.value } : null,
                                    )
                                  }
                                />
                                <div className="flex justify-end gap-1.5">
                                  <Button
                                    variant="ghost"
                                    size="xs"
                                    onClick={() => setReviewing(null)}
                                  >
                                    取消
                                  </Button>
                                  <Button
                                    variant="default"
                                    size="xs"
                                    disabled={savingReview}
                                    onClick={() =>
                                      reviewing &&
                                      void applyReview(reviewing.routeId, reviewing.status, reviewing.note)
                                    }
                                  >
                                    保存
                                  </Button>
                                </div>
                              </PopoverContent>
                            </Popover>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </ScrollArea>

      <div className="flex shrink-0 items-center justify-between border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
        <span className="tabular-nums">
          共 {data?.total ?? 0} 条路径
          {data && data.total_pages > 0 ? ` · 第 ${data.page} / ${data.total_pages} 页` : ''}
        </span>
        <div className="flex items-center gap-1.5">
          <Button
            variant="outline"
            size="xs"
            disabled={!data || data.page <= 1}
            onClick={() => setPage(current => Math.max(1, current - 1))}
          >
            上一页
          </Button>
          <Button
            variant="outline"
            size="xs"
            disabled={!data || data.page >= data.total_pages}
            onClick={() => setPage(current => current + 1)}
          >
            下一页
          </Button>
        </div>
      </div>
    </section>
  );
}
