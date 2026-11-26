import { useEffect, useState } from 'react';
import { ChevronDown, Crosshair, RefreshCw, X } from 'lucide-react';
import { api } from '@/api/client';
import type { RouteCoverage } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Spinner } from '@/components/ui/spinner';
import { IconActionButton } from '@/components/ui/workbench-shell';
import { formatClusterLabel } from '@/domain/features';
import { MOVEMENT_LABELS } from '@/domain/palette';
import { cn } from '@/lib/utils';

type GapGroupKey = 'clusters' | 'stands' | 'runways';

interface RouteCoveragePanelProps {
  onFocusStand(standRef: string): void;
  onFocusCluster(clusterId: number): void;
  onClose(): void;
}

function formatPercent(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

export function RouteCoveragePanel({
  onFocusStand,
  onFocusCluster,
  onClose,
}: RouteCoveragePanelProps) {
  const wb = useWorkbench();
  const [coverage, setCoverage] = useState<RouteCoverage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [openGroup, setOpenGroup] = useState<GapGroupKey | null>('clusters');

  const load = async (signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    try {
      const data = await api.routeCoverage(signal);
      setCoverage(data);
    } catch (failure) {
      if ((failure as Error).name !== 'AbortError') {
        setError(failure instanceof Error ? failure.message : '覆盖率加载失败');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [wb.routeLibraryVersion]);

  const metrics = coverage
    ? [
        {
          label: '细粒度 OD',
          value: formatPercent(coverage.fine_od_rate),
          sub: `${coverage.fine_covered_ods} / ${coverage.total_ods}`,
          tone: 'text-foreground',
        },
        {
          label: '聚类后 OD',
          value: formatPercent(coverage.effective_od_rate),
          sub: `${coverage.effective_covered_ods} / ${coverage.total_ods}`,
          tone: 'text-primary',
        },
        {
          label: '机位覆盖',
          value: `${coverage.effective_covered_stands} / ${coverage.total_stands}`,
          sub: `已聚类 ${coverage.clustered_stands} · ${coverage.cluster_count} 类`,
          tone: 'text-accent-teal',
        },
        {
          label: '跑道覆盖',
          value: `${coverage.covered_runways} / ${coverage.total_runways}`,
          sub: coverage.uncovered_runways.length === 0 ? '全部已覆盖' : `缺 ${coverage.uncovered_runways.length} 条`,
          tone: coverage.uncovered_runways.length > 0 ? 'text-accent-amber' : 'text-accent-teal',
        },
      ]
    : [];

  const uncoveredClusters = coverage?.uncovered_clusters ?? [];
  const uncoveredUnclusteredStands = coverage?.uncovered_unclustered_stands ?? [];
  const uncoveredRunways = coverage?.uncovered_runways ?? [];

  const toggleGroup = (key: GapGroupKey, count: number) => {
    if (count === 0) return;
    setOpenGroup(current => (current === key ? null : key));
  };

  return (
    <aside className="relative flex h-full min-h-0 w-full flex-col bg-muted">
      <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-4">
        <h2 className="m-0 text-[15px] font-semibold text-foreground">覆盖率概览</h2>
        <div className="flex items-center gap-0.5">
          <IconActionButton
            variant="ghost"
            size="icon-xs"
            label="刷新覆盖率"
            tooltip="刷新覆盖率"
            disabled={loading}
            onClick={() => void load()}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </IconActionButton>
          <Button variant="ghost" size="icon-xs" aria-label="关闭覆盖率概览" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        {loading && !coverage ? (
          <div className="grid place-items-center py-12">
            <Spinner className="h-5 w-5" />
          </div>
        ) : error ? (
          <div className="p-4 text-xs text-destructive">{error}</div>
        ) : coverage ? (
          <div className="divide-y divide-border px-4">
            <div className="grid grid-cols-2 gap-2 py-4 tabular-nums">
              {metrics.map(metric => (
                <div key={metric.label} className="rounded-md border border-border/70 bg-background px-2.5 py-2">
                  <strong className={cn('block text-base leading-tight font-semibold', metric.tone)}>
                    {metric.value}
                  </strong>
                  <span className="mt-0.5 block text-[11px] text-muted-foreground">{metric.label}</span>
                  <span className="mt-0.5 block truncate text-[11px] text-muted-foreground/80">
                    {metric.sub}
                  </span>
                </div>
              ))}
            </div>

            <section className="space-y-2 py-4">
              <h3 className="m-0 text-xs font-semibold text-foreground">分方向 OD 覆盖</h3>
              <dl className="m-0 divide-y divide-border/60 text-xs tabular-nums">
                {coverage.by_movement.map(item => {
                  const uplift = item.effective_od_rate - item.fine_od_rate;
                  return (
                    <div key={item.movement} className="flex items-baseline justify-between gap-2 py-2">
                      <dt className="font-medium text-foreground">
                        {MOVEMENT_LABELS[item.movement] ?? item.movement}
                      </dt>
                      <dd className="m-0 text-right text-muted-foreground">
                        <span>{formatPercent(item.fine_od_rate)}</span>
                        <span className="mx-1.5 text-border">→</span>
                        <strong className="font-semibold text-primary">
                          {formatPercent(item.effective_od_rate)}
                        </strong>
                        {uplift > 0.0005 && (
                          <span className="ml-1 text-[11px] text-accent-teal">
                            +{formatPercent(uplift)}
                          </span>
                        )}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </section>

            <section className="space-y-1.5 py-4">
              <h3 className="m-0 text-xs font-semibold text-foreground">缺失定位</h3>
              <div className="space-y-1 text-xs tabular-nums">
                <div className="rounded-md">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={uncoveredClusters.length === 0}
                    className={cn(
                      'h-7 w-full justify-between px-2 font-normal',
                      openGroup === 'clusters' && uncoveredClusters.length > 0 && 'bg-background shadow-2xs',
                      uncoveredClusters.length === 0 && 'opacity-70',
                    )}
                    onClick={() => toggleGroup('clusters', uncoveredClusters.length)}
                  >
                    <span className="flex items-center gap-1 text-muted-foreground">
                      {uncoveredClusters.length > 0 && (
                        <ChevronDown
                          className={cn(
                            'h-3 w-3 transition-transform',
                            openGroup !== 'clusters' && '-rotate-90',
                          )}
                        />
                      )}
                      未覆盖机位组
                    </span>
                    <span
                      className={cn(
                        uncoveredClusters.length > 0 ? 'font-semibold text-accent-amber' : 'text-muted-foreground',
                      )}
                    >
                      {uncoveredClusters.length}
                    </span>
                  </Button>
                  {openGroup === 'clusters' && uncoveredClusters.length > 0 && (
                    <div className="mt-1 max-h-48 space-y-0.5 overflow-auto rounded-md border border-border/70 bg-background p-1.5">
                      {uncoveredClusters.map(cluster => (
                        <Button
                          key={cluster.c_id}
                          variant="ghost"
                          size="xs"
                          className="h-6 w-full justify-between px-2 font-normal"
                          title={cluster.stand_refs.join(', ')}
                          onClick={() => onFocusCluster(cluster.c_id)}
                        >
                          <span className="truncate text-[11px] text-foreground">
                            {formatClusterLabel(cluster)}
                          </span>
                          <span className="flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
                            {cluster.stand_refs.length} 机位
                            <Crosshair className="h-3 w-3 opacity-60" />
                          </span>
                        </Button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="rounded-md">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={uncoveredUnclusteredStands.length === 0}
                    className={cn(
                      'h-7 w-full justify-between px-2 font-normal',
                      openGroup === 'stands' && uncoveredUnclusteredStands.length > 0 && 'bg-background shadow-2xs',
                      uncoveredUnclusteredStands.length === 0 && 'opacity-70',
                    )}
                    onClick={() => toggleGroup('stands', uncoveredUnclusteredStands.length)}
                  >
                    <span className="flex items-center gap-1 text-muted-foreground">
                      {uncoveredUnclusteredStands.length > 0 && (
                        <ChevronDown
                          className={cn(
                            'h-3 w-3 transition-transform',
                            openGroup !== 'stands' && '-rotate-90',
                          )}
                        />
                      )}
                      未归类未覆盖机位
                    </span>
                    <span
                      className={cn(
                        uncoveredUnclusteredStands.length > 0
                          ? 'font-semibold text-accent-amber'
                          : 'text-muted-foreground',
                      )}
                    >
                      {uncoveredUnclusteredStands.length}
                    </span>
                  </Button>
                  {openGroup === 'stands' && uncoveredUnclusteredStands.length > 0 && (
                    <div className="mt-1 max-h-48 space-y-0.5 overflow-auto rounded-md border border-border/70 bg-background p-1.5">
                      {uncoveredUnclusteredStands.map(standRef => (
                        <Button
                          key={standRef}
                          variant="ghost"
                          size="xs"
                          className="h-6 w-full justify-between px-2 font-normal"
                          onClick={() => onFocusStand(standRef)}
                        >
                          <span className="truncate font-mono text-[11px] text-foreground">{standRef}</span>
                          <Crosshair className="h-3 w-3 text-muted-foreground opacity-60" />
                        </Button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="rounded-md">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={uncoveredRunways.length === 0}
                    className={cn(
                      'h-7 w-full justify-between px-2 font-normal',
                      openGroup === 'runways' && uncoveredRunways.length > 0 && 'bg-background shadow-2xs',
                      uncoveredRunways.length === 0 && 'opacity-70',
                    )}
                    onClick={() => toggleGroup('runways', uncoveredRunways.length)}
                  >
                    <span className="flex items-center gap-1 text-muted-foreground">
                      {uncoveredRunways.length > 0 && (
                        <ChevronDown
                          className={cn(
                            'h-3 w-3 transition-transform',
                            openGroup !== 'runways' && '-rotate-90',
                          )}
                        />
                      )}
                      未覆盖跑道
                    </span>
                    <span
                      className={cn(
                        uncoveredRunways.length > 0 ? 'font-semibold text-accent-amber' : 'text-muted-foreground',
                      )}
                    >
                      {uncoveredRunways.length}
                    </span>
                  </Button>
                  {openGroup === 'runways' && uncoveredRunways.length > 0 && (
                    <div className="mt-1 space-y-0.5 rounded-md border border-border/70 bg-background px-2.5 py-2 font-mono text-[11px] text-foreground">
                      {uncoveredRunways.join(' · ')}
                    </div>
                  )}
                </div>
              </div>
            </section>
          </div>
        ) : null}
      </ScrollArea>
    </aside>
  );
}
