import { useEffect, useState } from 'react';
import {
  Crosshair,
  Eye,
  EyeOff,
  FileText,
  Flag,
  Layers,
  LoaderCircle,
  Plane,
  Route,
  X,
} from 'lucide-react';
import { api } from '@/api/client';
import type { MapFlightEntry, WorkbenchState } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { Empty, EmptyDescription } from '@/components/ui/empty';
import { InspectionStepper, MapRailFooter } from '@/components/ui/inspection-stepper';
import { KeyboardShortcuts } from '@/components/ui/keyboard-shortcuts';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Toggle } from '@/components/ui/toggle';
import { IconActionButton, RAIL_ACTION_REVEAL } from '@/components/ui/workbench-shell';
import { FLIGHT_COLORS as colors } from '@/domain/palette';
import { Inspector } from '@/features/graph-editor/Inspector';
import type { LayerSettings } from '@/features/graph-editor/Inspector';
import { useRailInspection } from '@/features/map/useRailInspection';
import { cn } from '@/lib/utils';
import { MapRouteList } from './MapRouteList';

type RailTab = 'flights' | 'routes' | 'layers';

interface MapSelectionRailProps {
  state: WorkbenchState;
  layers: LayerSettings;
  onLayers(value: LayerSettings): void;
  submitMatches(keys: string[], force: boolean): Promise<void>;
  splitView: boolean;
  onOpenDetail(flightKey: string): Promise<void>;
}

export function MapSelectionRail({
  state,
  layers,
  onLayers,
  splitView,
  onOpenDetail,
  submitMatches,
}: MapSelectionRailProps) {
  const wb = useWorkbench();
  const [tab, setTab] = useState<RailTab>('flights');
  const [loadingDetailKey, setLoadingDetailKey] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<Set<string>>(new Set());
  const [togglingIssue, setTogglingIssue] = useState<Set<string>>(new Set());

  const toggleIssue = async (key: string, label: string, reason?: string | null) => {
    const archived = wb.issueKeys.has(key);
    setTogglingIssue(current => new Set(current).add(key));
    try {
      const res = archived
        ? await api.removeMatchIssues([key])
        : await api.addMatchIssues([key], reason ?? null);
      wb.dispatch({ type: 'set-issue-keys', keys: res.issue_flight_keys });
      wb.dispatch({
        type: 'status',
        value: archived ? `已将 ${label} 移出异常航班归档` : `已将 ${label} 加入异常航班归档`,
      });
    } catch (failure) {
      wb.dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '异常归档操作失败' });
    } finally {
      setTogglingIssue(current => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  };

  const matchFlight = async (key: string, label: string) => {
    setSubmitting(current => new Set(current).add(key));
    try {
      await submitMatches([key], true);
      wb.dispatch({ type: 'status', value: `已提交 ${label} 的路径匹配` });
    } catch (failure) {
      wb.dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '匹配提交失败' });
    } finally {
      setSubmitting(current => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  };

  useEffect(() => {
    if (wb.highlightedRoute || wb.routeFocusRequest) setTab('routes');
  }, [wb.highlightedRoute, wb.routeFocusRequest]);

  useEffect(() => {
    if (wb.mapFocusRequest) setTab('flights');
  }, [wb.mapFocusRequest]);

  useEffect(() => {
    if (wb.view === 'route-map') setTab('routes');
    else if (wb.view === 'map' && wb.mapFlights.size > 0) setTab('flights');
  }, [wb.view, wb.mapFlights.size]);

  const updateMapEntry = (key: string, patch: Partial<MapFlightEntry>) => {
    const entry = wb.mapFlights.get(key);
    if (entry) wb.dispatch({ type: 'map-flight', key, value: { ...entry, ...patch } });
  };

  const openDetail = async (key: string) => {
    setLoadingDetailKey(key);
    try {
      await onOpenDetail(key);
    } finally {
      setLoadingDetailKey(current => (current === key ? null : current));
    }
  };

  const sortedFlights = [...wb.mapFlights].sort((a, b) => a[1].slot - b[1].slot);
  const sortedRoutes = [...wb.mapRoutes].sort((a, b) => a[1].slot - b[1].slot);

  const toggleIsolatedFlightIssue = async () => {
    const currentIndex = wb.isolatedFlightKey
      ? sortedFlights.findIndex(([key]) => key === wb.isolatedFlightKey)
      : -1;
    if (currentIndex < 0) {
      if (sortedFlights.length > 0) {
        wb.dispatch({ type: 'status', value: '请先单独显示一条航班，再按 I 切换异常归档' });
      }
      return;
    }
    const [key, entry] = sortedFlights[currentIndex];
    if (togglingIssue.has(key)) return;
    await toggleIssue(key, entry.label, entry.geometry.match.error);
  };

  const flightInspection = useRailInspection({
    kind: 'flights',
    sortedEntries: sortedFlights,
    isolatedKey: wb.isolatedFlightKey,
    highlighted: wb.highlightedFlight,
    onIsolate: key => wb.dispatch({ type: 'isolate-flight', key }),
    onFocus: key => wb.dispatch({ type: 'focus-flight', key, preserveView: splitView }),
    onFitAll: () => wb.dispatch({ type: 'fit-map-flights', preserveView: splitView }),
    onHighlightMatch: () => setTab('flights'),
    extraBindings: [{ key: 'i', onTrigger: () => void toggleIsolatedFlightIssue() }],
  });

  const tabTitle = tab === 'flights' ? '地图航班' : tab === 'routes' ? '地图路径' : '机场网络与图层';

  return (
    <aside className="map-selection relative z-[900] col-start-1 row-start-2 flex h-full min-h-0 min-w-0 flex-col border-r border-border bg-muted">
      <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-4">
        <strong className="truncate text-[15px] font-semibold text-foreground">{tabTitle}</strong>
        {tab === 'flights' && (
          <div className="flex items-center gap-1">
            <span className="text-[11px] text-muted-foreground tabular-nums">{wb.mapFlights.size}</span>
            <IconActionButton
              size="icon-xs"
              className="text-muted-foreground hover:text-foreground"
              label={wb.showMapFlights ? '隐藏地图航班图层' : '显示地图航班图层'}
              tooltip={wb.showMapFlights ? '隐藏全部地图航班图层' : '显示全部地图航班图层'}
              aria-pressed={wb.showMapFlights}
              onClick={() => wb.dispatch({ type: 'toggle-map-flights-group' })}
            >
              {wb.showMapFlights ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5 opacity-60" />}
            </IconActionButton>
          </div>
        )}
        {tab === 'routes' && (
          <div className="flex items-center gap-1">
            <span className="text-[11px] text-muted-foreground tabular-nums">{wb.mapRoutes.size}</span>
            <IconActionButton
              size="icon-xs"
              className="text-muted-foreground hover:text-foreground"
              label={wb.showMapRoutes ? '隐藏地图路径图层' : '显示地图路径图层'}
              tooltip={wb.showMapRoutes ? '隐藏全部地图路径图层' : '显示全部地图路径图层'}
              aria-pressed={wb.showMapRoutes}
              onClick={() => wb.dispatch({ type: 'toggle-map-routes-group' })}
            >
              {wb.showMapRoutes ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5 opacity-60" />}
            </IconActionButton>
          </div>
        )}
      </div>

      {tab === 'flights' && (
        <>
          <KeyboardShortcuts enabled={tab === 'flights'} bindings={flightInspection.bindings} />
          <InspectionStepper
            total={sortedFlights.length}
            currentIndex={flightInspection.currentIndex}
            onPrev={() => flightInspection.step(-1)}
            onNext={() => flightInspection.step(1)}
            onShowAll={flightInspection.showAll}
          />
          <ScrollArea className="min-h-0 flex-1 bg-background/60">
            <div className="divide-y divide-border/60 px-2 py-1">
              {wb.mapFlights.size === 0 && (
                <Empty className="py-12">
                  <EmptyDescription>尚无地图展示航班</EmptyDescription>
                </Empty>
              )}
              {sortedFlights.map(([key, entry]) => {
                const isolated = wb.isolatedFlightKey === key;
                const highlighted = flightInspection.flashingKey === key;
                const slotColor = colors[entry.slot % colors.length];
                const hasPath = Boolean(entry.geometry.path);
                const match = entry.geometry.match;
                const matching = submitting.has(key) || match.status === 'queued' || match.status === 'matching';
                const matchLabel = matching ? '匹配中' : hasPath ? '重新匹配路径' : '匹配路径';
                return (
                  <div
                    key={key}
                    ref={element => flightInspection.setItemRef(key, element)}
                    data-highlighted={highlighted ? 'true' : undefined}
                    className={cn(
                      'selected-chip group relative flex flex-col gap-1 rounded-md py-1.5 pl-3 pr-1.5 transition-all hover:bg-background',
                      isolated && 'bg-background shadow-2xs',
                      highlighted && 'bg-accent/80 ring-2 ring-primary/45',
                    )}
                  >
                    <span
                      aria-hidden="true"
                      className="absolute bottom-1.5 left-1 top-1.5 w-[3px] rounded-full"
                      style={{ backgroundColor: slotColor }}
                    />

                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className="w-4 shrink-0 text-[11px] font-medium text-muted-foreground tabular-nums">
                        {entry.slot + 1}
                      </span>
                      <span
                        className="min-w-0 flex-1 truncate text-xs font-medium text-foreground"
                        title={entry.label}
                      >
                        {entry.label.includes('_') ? entry.label.split('_')[0] : entry.label}
                      </span>
                      <div className="flex shrink-0 items-center gap-0.5">
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          className={cn(
                            'flight-isolate-action h-5 w-5',
                            isolated
                              ? 'bg-primary text-primary-foreground opacity-100 hover:bg-primary/90 hover:text-primary-foreground'
                              : RAIL_ACTION_REVEAL,
                          )}
                          aria-label={isolated ? '恢复全部航班' : `仅显示 ${entry.label}`}
                          aria-pressed={isolated}
                          title={isolated ? '恢复全部地图航班' : '仅显示此航班'}
                          onClick={() => wb.dispatch({ type: 'isolate-flight', key: isolated ? null : key })}
                        >
                          <Eye className="h-3 w-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          className={cn(
                            'h-5 w-5',
                            match.status === 'failed'
                              ? 'text-destructive opacity-100'
                              : matching
                                ? 'text-primary opacity-100'
                                : RAIL_ACTION_REVEAL,
                          )}
                          aria-label={`${matchLabel} ${entry.label}`}
                          title={match.status === 'failed' && !matching ? `上次匹配失败：${match.error ?? '未生成路径'}。点击重试` : matchLabel}
                          disabled={matching}
                          onClick={() => void matchFlight(key, entry.label)}
                        >
                          {matching ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Route className="h-3 w-3" />}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          className={cn(
                            'h-5 w-5',
                            wb.issueKeys.has(key)
                              ? 'text-destructive opacity-100 hover:text-destructive/80'
                              : cn(RAIL_ACTION_REVEAL, 'hover:text-destructive'),
                          )}
                          aria-label={wb.issueKeys.has(key) ? `将 ${entry.label} 移出异常归档` : `将 ${entry.label} 加入异常归档`}
                          aria-pressed={wb.issueKeys.has(key)}
                          title={wb.issueKeys.has(key) ? '已在异常归档中（点击移出）' : '加入异常归档'}
                          disabled={togglingIssue.has(key)}
                          onClick={() => void toggleIssue(key, entry.label, match.error)}
                        >
                          <Flag className={cn('h-3 w-3', wb.issueKeys.has(key) && 'fill-current')} />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          className={cn('flight-remove-action h-5 w-5', RAIL_ACTION_REVEAL, 'hover:text-destructive')}
                          aria-label={`移除 ${entry.label}`}
                          title="移出地图"
                          onClick={() => wb.dispatch({ type: 'map-flight', key, value: null })}
                        >
                          <X className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>

                    <div className="flex items-center justify-between gap-1 pl-5">
                      <div className="flex items-center gap-1">
                        <Toggle
                          size="xs"
                          role="switch"
                          pressed={entry.trajectoryVisible}
                          aria-checked={entry.trajectoryVisible}
                          aria-label={`${entry.label} 轨迹`}
                          title="显示/隐藏原始轨迹"
                          onClick={() => updateMapEntry(key, { trajectoryVisible: !entry.trajectoryVisible })}
                        >
                          轨迹
                        </Toggle>
                        <Toggle
                          size="xs"
                          role="switch"
                          pressed={hasPath && entry.pathVisible}
                          aria-checked={entry.pathVisible}
                          aria-label={`${entry.label} 路径`}
                          title={hasPath ? '显示/隐藏匹配路径' : '尚无匹配路径'}
                          disabled={!hasPath}
                          onClick={() => hasPath && updateMapEntry(key, { pathVisible: !entry.pathVisible })}
                        >
                          路径
                        </Toggle>
                      </div>

                      <div className="flex items-center gap-0.5">
                        <IconActionButton
                          size="icon-xs"
                          reveal="rail"
                          className="h-5 w-5 [&_svg]:size-3"
                          label="定位"
                          tooltip="在地图中定位"
                          onClick={() => wb.dispatch({ type: 'focus-flight', key, preserveView: splitView })}
                        >
                          <Crosshair />
                        </IconActionButton>
                        <IconActionButton
                          size="icon-xs"
                          reveal="rail"
                          disabled={loadingDetailKey === key}
                          className="h-5 w-5 [&_svg]:size-3"
                          label="详情"
                          tooltip="查看观测记录"
                          onClick={() => void openDetail(key)}
                        >
                          <FileText />
                        </IconActionButton>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </ScrollArea>

          <MapRailFooter
            disabled={!wb.mapFlights.size}
            fitLabel="适配全部航班"
            clearLabel="清空地图航班"
            onFitAll={() => wb.dispatch({ type: 'fit-map-flights', preserveView: splitView })}
            onClear={() => wb.dispatch({ type: 'clear-map-flights' })}
          />
        </>
      )}

      {tab === 'routes' && <MapRouteList sortedRoutes={sortedRoutes} splitView={splitView} />}

      {tab === 'layers' && (
        <div className="min-h-0 flex-1 overflow-hidden bg-background/60">
          <Inspector state={state} layers={layers} onLayers={onLayers} embedded />
        </div>
      )}

      <div
        role="tablist"
        aria-label="左侧栏切换"
        className="grid shrink-0 grid-cols-3 gap-1 border-t border-border bg-muted p-1.5"
      >
        {(
          [
            { key: 'flights' as const, label: '航班', count: wb.mapFlights.size, icon: Plane },
            { key: 'routes' as const, label: '路径', count: wb.mapRoutes.size, icon: Route },
            { key: 'layers' as const, label: '图层', count: null, icon: Layers },
          ] as const
        ).map(item => {
          const Icon = item.icon;
          const active = tab === item.key;
          return (
            <Button
              key={item.key}
              role="tab"
              aria-selected={active}
              variant={active ? 'default' : 'ghost'}
              size="xs"
              className={cn(
                'h-7 gap-1 px-1.5 text-xs [&_svg]:size-3.5',
                !active && 'text-muted-foreground hover:text-foreground',
              )}
              onClick={() => setTab(item.key)}
            >
              <Icon />
              <span>{item.label}</span>
              {item.count !== null && item.count > 0 && (
                <span className="text-[11px] tabular-nums opacity-80">{item.count}</span>
              )}
            </Button>
          );
        })}
      </div>
    </aside>
  );
}
