import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BarChart3, Crosshair, Layers, MapPinOff, MapPinPlus } from 'lucide-react';
import { ApiError, api } from '@/api/client';
import type { RouteListQuery } from '@/api/client';
import type { RouteAnomalyItem, RouteItem, RouteList } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import type { MapRouteInput } from '@/app/WorkbenchContext';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Empty, EmptyDescription, EmptyTitle } from '@/components/ui/empty';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  DataTableContainer,
  IconActionButton,
  PaginationFooter,
  TablePagination,
  ViewHeader,
} from '@/components/ui/workbench-shell';
import { formatRouteOd } from '@/domain/features';
import { ROUTE_STATUS_LABELS as statusLabels } from '@/domain/palette';
import { MapBatchConfirmDialog } from '@/features/map/MapBatchConfirmDialog';
import { cn } from '@/lib/utils';
import { RouteAnomalyBar } from './RouteAnomalyBar';
import { RouteBulkBar } from './RouteBulkBar';
import { RouteFilterBar, defaultRouteFilters } from './RouteFilterBar';
import type { RouteFilters } from './RouteFilterBar';
import { RouteNoteCell, RouteStatusCell } from './RouteReviewCells';
import { useRouteBatchSelection } from './useRouteBatchSelection';
import { useRouteLibraryInsights } from './useRouteLibraryInsights';

function paramsFor(filters: RouteFilters, page: number, pageSize: number): RouteListQuery {
  return {
    q: filters.query.trim() || undefined,
    movement: filters.movement || undefined,
    stand_ref: filters.stand || undefined,
    runway_ref: filters.runway || undefined,
    status: filters.status || undefined,
    all_graphs: filters.allGraphs || undefined,
    page,
    page_size: pageSize,
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
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busyRouteId, setBusyRouteId] = useState<string | null>(null);
  const [savingReview, setSavingReview] = useState(false);
  const mountedRef = useRef(true);

  const batch = useRouteBatchSelection({
    items: data?.items ?? [],
    page,
    totalPages: data?.total_pages ?? 0,
    splitView,
    labelFor: formatRouteOd,
    fetchPage: async targetPage => {
      const nextData = await api.routes(paramsFor(filters, targetPage, pageSize));
      if (mountedRef.current) {
        setData(nextData);
        setPage(nextData.page || targetPage);
      }
      return { items: nextData.items, page: nextData.page || targetPage };
    },
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError('');
      try {
        const result = await api.routes(paramsFor(filters, page, pageSize), signal);
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
    [filters, page, pageSize],
  );

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [active, load, wb.routeLibraryVersion]);

  const insights = useRouteLibraryInsights({
    mountedRef,
    onReloadRoutes: () => load(),
  });

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
      if (!mountedRef.current) return;
      const entry: MapRouteInput = {
        geometry,
        label: formatRouteOd(item),
        visible: true,
      };
      wb.dispatch({ type: 'map-route', routeId: item.route_id, value: entry });
      if (focus) {
        wb.dispatch({ type: 'focus-route', routeId: item.route_id, preserveView: splitView });
      } else {
        wb.dispatch({ type: 'status', value: `已将路径 ${entry.label} 加入地图` });
      }
    } catch (failure) {
      if (mountedRef.current) {
        wb.dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '路径几何加载失败' });
      }
    } finally {
      if (mountedRef.current) setBusyRouteId(current => (current === item.route_id ? null : current));
    }
  };

  const overlaySameOd = (item: RouteItem) => {
    if (!data) return;
    const peers = data.items.filter(
      candidate =>
        candidate.matches_current_graph &&
        candidate.movement === item.movement &&
        candidate.stand_ref === item.stand_ref &&
        candidate.runway_ref === item.runway_ref,
    );
    batch.addRouteItemsToMap(peers);
  };

  const applyReview = async (routeId: string, status: string, note: string | null): Promise<boolean> => {
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
      batch.syncSelectedItem(updated);
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
      wb.dispatch({ type: 'status', value: `已更新路径状态为「${statusLabels[updated.status] ?? updated.status}」` });
      wb.dispatch({ type: 'routes-updated' });
      return true;
    } catch (failure) {
      wb.dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '路径审校更新失败' });
      return false;
    } finally {
      setSavingReview(false);
    }
  };

  const applyFilters = () => {
    setPage(1);
    setFilters(draft);
  };

  const applyImmediatePatch = (patch: Partial<RouteFilters>) => {
    setDraft(current => ({ ...current, ...patch }));
    setFilters(current => ({ ...current, ...patch }));
    setPage(1);
  };

  const resetFilters = () => {
    setDraft(defaultRouteFilters);
    setFilters(defaultRouteFilters);
    setPage(1);
  };

  const handleAddAnomaliesToMap = (items: RouteAnomalyItem[]) => {
    const candidates: RouteItem[] = items.map(
      item =>
        batch.selectedRoutes.get(item.route_id) ??
        data?.items.find(row => row.route_id === item.route_id) ?? {
          route_id: item.route_id,
          graph_id: data?.current_graph_id ?? '',
          matches_current_graph: true,
          movement: item.movement,
          stand_ref: item.stand_ref,
          runway_ref: item.runway_ref,
          runway_interface_node: '',
          edge_count: 0,
          total_length_m: item.total_length_m,
          flight_count: item.flight_count,
          status: item.status,
          source: 'matched',
          note: null,
          created_at: null,
          updated_at: null,
        },
    );
    const valid = candidates.filter(item => item.matches_current_graph);
    if (valid.length) {
      batch.addRouteItemsToMap(valid);
    }
  };

  const handleDetectAllAnomalies = () => {
    void insights.detectAnomalies({
      q: filters.query.trim(),
      movement: filters.movement || null,
      stand_ref: filters.stand || null,
      runway_ref: filters.runway || null,
      status: filters.status || null,
      all_graphs: filters.allGraphs,
    });
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
        'main-view route-library-panel absolute inset-0 flex h-full w-full min-h-0 min-w-0 flex-col overflow-hidden bg-background',
        !active && 'hidden',
      )}
    >
      <ViewHeader>
        <h2 className="m-0 text-[15px] font-semibold text-foreground">路径库</h2>
        {data?.has_route_library && (
          <Button
            variant={wb.coverageOpen ? 'secondary' : 'outline'}
            size="sm"
            onClick={() =>
              wb.dispatch({ type: 'panel', panel: 'coverageOpen', value: !wb.coverageOpen })
            }
          >
            <BarChart3 className="h-3.5 w-3.5" />
            <span>覆盖率</span>
          </Button>
        )}
      </ViewHeader>

      <RouteFilterBar
        draft={draft}
        filters={filters}
        data={data}
        totalAllStatuses={totalAllStatuses}
        loading={loading}
        error={error}
        onDraftChange={setDraft}
        onImmediatePatch={applyImmediatePatch}
        onApply={applyFilters}
        onReset={resetFilters}
        onRefresh={() => {
          void load();
          wb.dispatch({ type: 'routes-updated' });
        }}
      />

      {data?.has_route_library && (
        <RouteBulkBar
          selectedCount={batch.selectedRoutes.size}
          selectedOnMapCount={batch.selectedOnMapCount}
          selectablePageCount={batch.selectablePageItems.length}
          totalFilteredCount={data.total}
          allPageSelected={batch.allPageSelected}
          addingProgress={batch.addingProgress}
          detectingAnomalies={insights.detectingAnomalies}
          onTogglePage={batch.toggleSelectPage}
          onClearSelection={batch.clearSelection}
          onAddSelectedToMap={() => void batch.addSelectedToMap()}
          onReplacePageToMap={() => void batch.replaceItemsOnMap(batch.selectablePageItems, data.page || page)}
          onRemoveSelectedFromMap={batch.removeSelectedFromMap}
          onCancelAddToMap={batch.cancelAddToMap}
          onDetectSelectedAnomalies={() =>
            void insights.detectAnomalies({ route_ids: [...batch.selectedRoutes.keys()] })
          }
          onDetectAllAnomalies={handleDetectAllAnomalies}
        />
      )}

      <RouteAnomalyBar
        result={insights.anomalyResult}
        canEdit={Boolean(data?.can_edit)}
        rejecting={insights.rejectingAnomalies}
        onAddAnomaliesToMap={handleAddAnomaliesToMap}
        onRejectAnomalies={routeIds => void insights.rejectAnomalies(routeIds)}
        onDismiss={insights.dismissAnomalies}
      />

      <DataTableContainer loading={loading}>
        {!loading && data && !data.has_route_library ? (
          <Empty className="py-16">
            <EmptyTitle>当前数据库尚未初始化路径库</EmptyTitle>
            <EmptyDescription>批量匹配完成后，可运行以下命令将去重路径导入到 DuckDB：</EmptyDescription>
            <code className="rounded bg-muted px-2.5 py-1 font-mono text-[11px] text-foreground">
              uv run --extra stand-editing python -m route_library import outputs/path_map/&lt;run_id&gt;
            </code>
          </Empty>
        ) : !loading && data && data.items.length === 0 ? (
          <Empty className="py-16">
            <EmptyDescription>当前筛选条件下暂无路径记录</EmptyDescription>
          </Empty>
        ) : (
          <Table className="min-w-[720px]">
            <TableHeader>
              <TableRow className="bg-muted hover:bg-muted">
                <TableHead className="w-9">
                  <Checkbox
                    aria-label="全选本页路径"
                    disabled={batch.selectablePageItems.length === 0}
                    checked={batch.selectablePageItems.length > 0 && batch.allPageSelected}
                    onCheckedChange={batch.toggleSelectPage}
                  />
                </TableHead>
                <TableHead>OD</TableHead>
                <TableHead>长度</TableHead>
                <TableHead>边数</TableHead>
                <TableHead>架次</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>备注</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data?.items ?? []).map(item => {
                const onMap = wb.mapRoutes.has(item.route_id);
                const checked = batch.selectedRoutes.has(item.route_id);
                const busy = busyRouteId === item.route_id || batch.addingProgress !== null;
                const odKey = `${item.movement}\0${item.stand_ref}\0${item.runway_ref ?? ''}`;
                const sameOdCount = odCounts.get(odKey) ?? 1;
                return (
                  <TableRow
                    key={item.route_id}
                    data-state={onMap || checked ? 'selected' : undefined}
                    className="group"
                  >
                    <TableCell>
                      <Checkbox
                        aria-label={`选择路径 ${formatRouteOd(item)}`}
                        disabled={!item.matches_current_graph}
                        checked={checked}
                        onCheckedChange={next => batch.toggleSelectRoute(item, next === true)}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <strong className="cursor-default font-medium text-foreground">
                              {formatRouteOd(item)}
                            </strong>
                          </TooltipTrigger>
                          <TooltipContent side="right" className="font-mono text-[11px]">
                            {item.route_id}
                          </TooltipContent>
                        </Tooltip>
                        {insights.anomalousIdSet.has(item.route_id) && (
                          <Badge variant="warning" className="h-5 px-1.5 text-[11px]">
                            异常
                          </Badge>
                        )}
                        {!item.matches_current_graph && (
                          <Badge variant="warning" className="h-5 px-1.5 text-[11px]">
                            旧图
                          </Badge>
                        )}
                      </div>
                    </TableCell>

                    <TableCell className="tabular-nums text-foreground">
                      {Math.round(item.total_length_m)} m
                    </TableCell>

                    <TableCell className="tabular-nums text-muted-foreground">{item.edge_count}</TableCell>

                    <TableCell className="tabular-nums text-foreground">{item.flight_count ?? 0}</TableCell>

                    <TableCell>
                      <RouteStatusCell
                        item={item}
                        canEdit={Boolean(data?.can_edit)}
                        saving={savingReview}
                        onSave={applyReview}
                      />
                    </TableCell>

                    <TableCell className="max-w-[220px]">
                      <RouteNoteCell
                        item={item}
                        canEdit={Boolean(data?.can_edit)}
                        saving={savingReview}
                        onSave={applyReview}
                      />
                    </TableCell>

                    <TableCell>
                      <div className="flex items-center gap-0.5">
                        <IconActionButton
                          variant={onMap ? 'secondary' : 'ghost'}
                          reveal={!onMap ? 'table' : undefined}
                          disabled={busy || !item.matches_current_graph}
                          label={onMap ? '移出地图' : '加入地图'}
                          tooltip={
                            !item.matches_current_graph
                              ? '路径所属图版本与当前图不一致'
                              : onMap
                                ? '移出地图'
                                : '加入地图'
                          }
                          onClick={() => void toggleOnMap(item, false)}
                        >
                          {onMap ? <MapPinOff className="h-3.5 w-3.5" /> : <MapPinPlus className="h-3.5 w-3.5" />}
                        </IconActionButton>

                        <IconActionButton
                          reveal="table"
                          disabled={busy || !item.matches_current_graph}
                          label="定位"
                          tooltip="在地图中定位"
                          onClick={() => void toggleOnMap(item, true)}
                        >
                          <Crosshair className="h-3.5 w-3.5" />
                        </IconActionButton>

                        {sameOdCount > 1 && (
                          <IconActionButton
                            size="xs"
                            reveal="table"
                            className="h-7 gap-1 px-1.5 text-xs [&_svg]:size-3.5"
                            disabled={busy || !item.matches_current_graph}
                            label={`同 OD 对比（${sameOdCount} 条）`}
                            tooltip={`叠加本页同 OD 的 ${sameOdCount} 条路径对比`}
                            onClick={() => overlaySameOd(item)}
                          >
                            <Layers />
                            <span className="tabular-nums">{sameOdCount}</span>
                          </IconActionButton>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </DataTableContainer>

      <PaginationFooter>
        <TablePagination
          page={data?.page ?? 0}
          totalPages={data?.total_pages ?? 0}
          totalItems={data?.total ?? 0}
          itemLabel="条路径"
          pageSize={pageSize}
          disabled={loading}
          onPageChange={setPage}
          onPageSizeChange={nextSize => {
            setPageSize(nextSize);
            setPage(1);
          }}
        />
      </PaginationFooter>

      <MapBatchConfirmDialog dialog={batch.confirmDialog} onClose={batch.dismissConfirm} />
    </section>
  );
}
