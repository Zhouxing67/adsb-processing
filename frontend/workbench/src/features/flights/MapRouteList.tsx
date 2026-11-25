import { Crosshair, Eye, X } from 'lucide-react';
import type { MapRouteEntry } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { Empty, EmptyDescription } from '@/components/ui/empty';
import { InspectionStepper, MapRailFooter } from '@/components/ui/inspection-stepper';
import { KeyboardShortcuts } from '@/components/ui/keyboard-shortcuts';
import { ScrollArea } from '@/components/ui/scroll-area';
import { IconActionButton, RAIL_ACTION_REVEAL } from '@/components/ui/workbench-shell';
import { ROUTE_COLORS as routeColors, ROUTE_STATUS_LABELS as routeStatusLabels } from '@/domain/palette';
import { useRailInspection } from '@/features/map/useRailInspection';
import { cn } from '@/lib/utils';

interface MapRouteListProps {
  sortedRoutes: Array<[string, MapRouteEntry]>;
  splitView: boolean;
}

export function MapRouteList({ sortedRoutes, splitView }: MapRouteListProps) {
  const wb = useWorkbench();
  const inspection = useRailInspection({
    kind: 'routes',
    sortedEntries: sortedRoutes,
    isolatedKey: wb.isolatedRouteId,
    highlighted: wb.highlightedRoute,
    onIsolate: routeId => wb.dispatch({ type: 'isolate-route', routeId }),
    onFocus: routeId => wb.dispatch({ type: 'focus-route', routeId, preserveView: splitView }),
    onFitAll: () => wb.dispatch({ type: 'fit-map-routes', preserveView: splitView }),
  });

  return (
    <>
      <KeyboardShortcuts bindings={inspection.bindings} />
      <InspectionStepper
        total={sortedRoutes.length}
        currentIndex={inspection.currentIndex}
        onPrev={() => inspection.step(-1)}
        onNext={() => inspection.step(1)}
        onShowAll={inspection.showAll}
      />
      <ScrollArea className="min-h-0 flex-1 bg-background/60">
        <div className="divide-y divide-border/60 px-2 py-1">
          {sortedRoutes.length === 0 && (
            <Empty className="py-12">
              <EmptyDescription>尚无地图展示路径</EmptyDescription>
            </Empty>
          )}
          {sortedRoutes.map(([routeId, entry]) => {
            const isolated = wb.isolatedRouteId === routeId;
            const highlighted = inspection.flashingKey === routeId;
            const slotColor = routeColors[entry.slot % routeColors.length];
            const route = entry.geometry.route;
            return (
              <div
                key={routeId}
                ref={element => inspection.setItemRef(routeId, element)}
                data-highlighted={highlighted ? 'true' : undefined}
                className={cn(
                  'group relative flex flex-col gap-1 rounded-md py-1.5 pl-3 pr-1.5 transition-all hover:bg-background',
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
                  <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground" title={routeId}>
                    {entry.label}
                  </span>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      className={cn(
                        'h-5 w-5',
                        isolated
                          ? 'bg-primary text-primary-foreground opacity-100 hover:bg-primary/90 hover:text-primary-foreground'
                          : RAIL_ACTION_REVEAL,
                      )}
                      aria-label={isolated ? '恢复全部路径' : `仅显示 ${entry.label}`}
                      aria-pressed={isolated}
                      title={isolated ? '恢复全部地图路径' : '仅显示此路径'}
                      onClick={() => wb.dispatch({ type: 'isolate-route', routeId: isolated ? null : routeId })}
                    >
                      <Eye className="h-3 w-3" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      className={cn('h-5 w-5', RAIL_ACTION_REVEAL, 'hover:text-destructive')}
                      aria-label={`移除路径 ${entry.label}`}
                      title="移出地图"
                      onClick={() => wb.dispatch({ type: 'map-route', routeId, value: null })}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
                <div className="flex items-center justify-between gap-1 text-[11px] text-muted-foreground">
                  <span className="truncate tabular-nums">
                    {Math.round(route.total_length_m)} m · {routeStatusLabels[route.status] ?? route.status}
                  </span>
                  <IconActionButton
                    size="icon-xs"
                    reveal="rail"
                    className="h-5 w-5 [&_svg]:size-3"
                    label="定位"
                    tooltip="在地图中定位"
                    onClick={() => wb.dispatch({ type: 'focus-route', routeId, preserveView: splitView })}
                  >
                    <Crosshair />
                  </IconActionButton>
                </div>
              </div>
            );
          })}
        </div>
      </ScrollArea>

      <MapRailFooter
        disabled={!wb.mapRoutes.size}
        fitLabel="适配全部路径"
        clearLabel="清空地图路径"
        onFitAll={() => wb.dispatch({ type: 'fit-map-routes', preserveView: splitView })}
        onClear={() => wb.dispatch({ type: 'clear-map-routes' })}
      />
    </>
  );
}
