import { Ban, CheckCircle2, MapPinPlus, ShieldAlert, X } from 'lucide-react';
import type { RouteAnomalyItem, RouteAnomalyResult } from '@/api/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { IconActionButton } from '@/components/ui/workbench-shell';
import { formatRouteOd } from '@/domain/features';
import { ROUTE_ANOMALY_LABELS } from '@/domain/palette';

interface RouteAnomalyBarProps {
  result: RouteAnomalyResult | null;
  canEdit: boolean;
  rejecting: boolean;
  onAddAnomaliesToMap(items: RouteAnomalyItem[]): void;
  onRejectAnomalies(routeIds: string[]): void;
  onDismiss(): void;
}

export function RouteAnomalyBar({
  result,
  canEdit,
  rejecting,
  onAddAnomaliesToMap,
  onRejectAnomalies,
  onDismiss,
}: RouteAnomalyBarProps) {
  if (!result) return null;

  const rejectableIds = result.items
    .filter(item => item.status !== 'rejected')
    .map(item => item.route_id);

  return (
    <section
      aria-label="异常路径检测结果"
      className="shrink-0 border-b border-border bg-accent/40 px-4 py-2 text-xs"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 tabular-nums">
          {result.anomalous_count === 0 ? (
            <>
              <CheckCircle2 className="h-4 w-4 text-accent-teal" />
              <span className="text-foreground">
                已检测 {result.checked_count} 条路径，未发现明显异常路径
              </span>
            </>
          ) : (
            <>
              <ShieldAlert className="h-4 w-4 text-accent-amber" />
              <span className="font-medium text-foreground">
                已检测 {result.checked_count} 条路径，发现 {result.anomalous_count} 条明显异常
              </span>
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {result.anomalous_count > 0 && (
            <>
              <Button
                variant="outline"
                size="xs"
                className="h-6 gap-1 px-2 text-xs"
                onClick={() => onAddAnomaliesToMap(result.items)}
              >
                <MapPinPlus className="h-3.5 w-3.5" />
                <span>异常加入地图</span>
              </Button>
              {canEdit && (
                <Button
                  variant="destructive"
                  size="xs"
                  className="h-6 gap-1 px-2 text-xs"
                  disabled={rejecting || rejectableIds.length === 0}
                  onClick={() => onRejectAnomalies(rejectableIds)}
                >
                  <Ban className="h-3.5 w-3.5" />
                  <span>
                    {rejectableIds.length === 0
                      ? '均已驳回'
                      : `一键驳回（${rejectableIds.length}）`}
                  </span>
                </Button>
              )}
            </>
          )}
          <IconActionButton
            variant="ghost"
            size="icon-xs"
            label="关闭异常检测结果"
            tooltip="关闭"
            onClick={onDismiss}
          >
            <X className="h-3.5 w-3.5" />
          </IconActionButton>
        </div>
      </div>

      {result.anomalous_count > 0 && (
        <ul className="m-0 mt-2 grid max-h-36 list-none gap-1 overflow-y-auto border-t border-border/70 p-0 pt-2">
          {result.items.map(item => (
            <li
              key={item.route_id}
              className="flex flex-wrap items-center justify-between gap-2 rounded bg-background/80 px-2 py-1 text-[11px]"
            >
              <div className="flex flex-wrap items-center gap-2 tabular-nums">
                <strong className="font-medium text-foreground">{formatRouteOd(item)}</strong>
                <span className="text-muted-foreground">
                  {Math.round(item.total_length_m)} m · {item.flight_count} 架次
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-1">
                {item.reasons.map(reason => (
                  <Tooltip key={reason.code}>
                    <TooltipTrigger asChild>
                      <Badge variant="warning" className="h-5 cursor-default px-1.5 text-[11px]">
                        {ROUTE_ANOMALY_LABELS[reason.code] ?? reason.code}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent side="left" className="max-w-xs text-xs">
                      {reason.message}
                    </TooltipContent>
                  </Tooltip>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
