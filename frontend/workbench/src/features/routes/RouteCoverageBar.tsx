import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { RouteCoverage } from '@/api/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { MOVEMENT_LABELS } from '@/domain/palette';

interface RouteCoverageBarProps {
  coverage: RouteCoverage | null;
  loading?: boolean;
}

function formatPercent(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

export function RouteCoverageBar({ coverage, loading = false }: RouteCoverageBarProps) {
  const [expanded, setExpanded] = useState(false);

  if (!coverage) return null;

  const uplift = coverage.effective_od_rate - coverage.fine_od_rate;
  const hasDetails =
    coverage.by_movement.length > 0 ||
    coverage.uncovered_stands.length > 0 ||
    coverage.uncovered_runways.length > 0;

  return (
    <section
      aria-label="路径库覆盖率摘要"
      className="shrink-0 border-b border-border bg-muted/35 px-4 py-2 text-xs"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 tabular-nums">
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">细粒度 OD</span>
            <strong className="font-semibold text-foreground">
              {coverage.fine_covered_ods} / {coverage.total_ods}
            </strong>
            <span className="text-muted-foreground">({formatPercent(coverage.fine_od_rate)})</span>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">聚类后 OD</span>
            <strong className="font-semibold text-primary">
              {coverage.effective_covered_ods} / {coverage.total_ods}
            </strong>
            <span className="text-foreground">({formatPercent(coverage.effective_od_rate)})</span>
            {uplift > 0.0005 && (
              <Badge variant="secondary" className="h-5 px-1.5 text-[11px] text-accent-teal">
                +{formatPercent(uplift)}
              </Badge>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">机位覆盖</span>
            <strong className="font-medium text-foreground">
              {coverage.effective_covered_stands} / {coverage.total_stands}
            </strong>
            <span className="text-muted-foreground">
              （已聚类 {coverage.clustered_stands} · {coverage.cluster_count} 类）
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">跑道覆盖</span>
            <strong className="font-medium text-foreground">
              {coverage.covered_runways} / {coverage.total_runways}
            </strong>
          </div>
        </div>

        {hasDetails && (
          <Button
            variant="ghost"
            size="xs"
            disabled={loading}
            className="h-6 gap-1 px-2 text-xs text-muted-foreground"
            onClick={() => setExpanded(value => !value)}
          >
            <span>{expanded ? '收起覆盖详情' : '覆盖详情'}</span>
            {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </Button>
        )}
      </div>

      {expanded && (
        <div className="mt-2 grid gap-2 border-t border-border/70 pt-2 text-[11px]">
          <div className="flex flex-wrap items-center gap-4 tabular-nums">
            {coverage.by_movement.map(item => (
              <span key={item.movement} className="text-muted-foreground">
                <strong className="font-medium text-foreground">
                  {MOVEMENT_LABELS[item.movement] ?? item.movement}
                </strong>{' '}
                细粒度 {item.fine_covered_ods}/{item.total_ods} ({formatPercent(item.fine_od_rate)}) ·
                聚类后 {item.effective_covered_ods}/{item.total_ods} ({formatPercent(item.effective_od_rate)})
              </span>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-muted-foreground">
              未覆盖跑道（{coverage.uncovered_runways.length}）：
            </span>
            {coverage.uncovered_runways.length === 0 ? (
              <span className="text-accent-teal">全部已覆盖</span>
            ) : (
              coverage.uncovered_runways.map(runway => (
                <Badge key={runway} variant="outline" className="h-5 px-1.5 text-[11px]">
                  {runway}
                </Badge>
              ))
            )}
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-muted-foreground">
              未覆盖机位（{coverage.uncovered_stands.length}）：
            </span>
            {coverage.uncovered_stands.length === 0 ? (
              <span className="text-accent-teal">全部已覆盖</span>
            ) : (
              <>
                {coverage.uncovered_stands.slice(0, 30).map(stand => (
                  <Badge key={stand} variant="outline" className="h-5 px-1.5 text-[11px] tabular-nums">
                    {stand}
                  </Badge>
                ))}
                {coverage.uncovered_stands.length > 30 && (
                  <span className="text-muted-foreground">
                    等共 {coverage.uncovered_stands.length} 个
                  </span>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
