import { memo, useEffect, useMemo, useState } from 'react';
import type { DemoTraceResponse } from '@/api/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { activeDecodeAttempt } from './types';
import type { DemoStage } from './types';

interface DemoInspectorPanelProps {
  trace: DemoTraceResponse;
  stage: DemoStage;
  selectedObsIndex: number;
  selectedDualEdge: string | null;
  onSelectObs(index: number): void;
  onSelectDualEdge(edge: string): void;
  onHoverEdge(edge: string | null): void;
  onHoverCandidateEdge(edgeId: string | null): void;
}

const DEFAULT_VISIBLE_ROWS = 6;

export const DemoInspectorPanel = memo(function DemoInspectorPanel({
  trace,
  stage,
  selectedObsIndex,
  selectedDualEdge,
  onSelectObs,
  onSelectDualEdge,
  onHoverEdge,
  onHoverCandidateEdge,
}: DemoInspectorPanelProps) {
  const obs = trace.observations[selectedObsIndex] ?? trace.observations[0];
  const attempt = activeDecodeAttempt(trace, stage);
  const attemptLayers = attempt.layers ?? [];
  const activeLayer = attemptLayers.find(layer => layer.observation_index === selectedObsIndex);
  const prevLayer =
    activeLayer && activeLayer.layer_index > 0
      ? attemptLayers[activeLayer.layer_index - 1]
      : null;

  const sortedStates = useMemo(() => {
    if (!activeLayer) return [];
    return [...activeLayer.states].sort((a, b) => {
      if (a.is_optimal !== b.is_optimal) return a.is_optimal ? -1 : 1;
      return (b.cumulative_score ?? -1e9) - (a.cumulative_score ?? -1e9);
    });
  }, [activeLayer]);

  const { minScore, scoreSpan } = useMemo(() => {
    const scores = sortedStates
      .map(s => s.cumulative_score)
      .filter((v): v is number => v != null);
    const max = scores.length ? Math.max(...scores) : 0;
    const min = scores.length ? Math.min(...scores) : -1;
    return { minScore: min, scoreSpan: Math.max(0.01, max - min) };
  }, [sortedStates]);

  const dualEdges = useMemo(
    () => Array.from(new Set(trace.dual_graph.transitions.map(item => item.from_edge))),
    [trace.dual_graph.transitions],
  );

  const dualRows = useMemo(
    () => trace.dual_graph.transitions.filter(item => item.from_edge === selectedDualEdge),
    [trace.dual_graph.transitions, selectedDualEdge],
  );

  const [focusedStateIndex, setFocusedStateIndex] = useState<number | null>(null);
  const [expandStates, setExpandStates] = useState(false);

  useEffect(() => {
    setFocusedStateIndex(null);
    setExpandStates(false);
  }, [selectedObsIndex, stage, trace]);

  const focusedState =
    sortedStates.find(s => s.state_index === focusedStateIndex) ??
    sortedStates.find(s => s.is_optimal) ??
    sortedStates[0] ??
    null;

  const prevStateForFocused =
    focusedState && prevLayer && focusedState.best_prev_index != null
      ? prevLayer.states[focusedState.best_prev_index] ?? null
      : null;

  const visibleStates = expandStates ? sortedStates : sortedStates.slice(0, DEFAULT_VISIBLE_ROWS);
  const finalEdges = trace.final_result.edges ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      {stage !== 'dual-graph' && stage !== 'final' && (
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-1.5">
          <div className="flex flex-wrap items-center gap-1">
            {trace.observations.map(item => (
              <Button
                key={item.index}
                variant={selectedObsIndex === item.index ? 'default' : 'ghost'}
                size="xs"
                className="h-6 min-w-[32px] px-2 font-mono text-[11px]"
                onClick={() => onSelectObs(item.index)}
              >
                P{item.index + 1}
              </Button>
            ))}
          </div>
          <span className="text-[11px] text-muted-foreground">
            {stage === 'candidates'
              ? `${obs?.candidates.length ?? 0} 条候选`
              : `${sortedStates.length} 个状态`}
          </span>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto">
        {stage === 'candidates' && obs && (
          <div className="space-y-1.5 p-3 text-xs">
            {obs.candidates.length === 0 ? (
              <div className="py-6 text-center text-muted-foreground">
                半径 {trace.config.candidate_radius}m 内无候选边
              </div>
            ) : (
              obs.candidates.map((cand, idx) => {
                const ratio = Math.max(
                  6,
                  Math.round((1 - cand.distance_m / trace.config.candidate_radius) * 100),
                );
                return (
                  <div
                    key={cand.edge_id}
                    className="rounded-md border border-transparent px-2 py-1.5 transition-colors hover:border-border hover:bg-muted/50"
                    onMouseEnter={() => onHoverCandidateEdge(cand.edge_id)}
                    onMouseLeave={() => onHoverCandidateEdge(null)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono font-medium text-foreground">
                          {cand.u}–{cand.v}
                        </span>
                        <span className="text-[11px] text-muted-foreground">
                          {cand.ref ?? cand.aeroway}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 font-mono text-[11px] tabular-nums">
                        <span className="text-foreground">{cand.distance_m}m</span>
                        <span className="w-[50px] text-right text-muted-foreground">
                          {cand.emission_score.toFixed(2)}
                        </span>
                      </div>
                    </div>
                    <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn(
                          'h-full rounded-full transition-all',
                          idx === 0 ? 'bg-primary' : 'bg-accent-teal/70',
                        )}
                        style={{ width: `${ratio}%` }}
                      />
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {stage === 'dual-graph' && (
          <div className="space-y-2.5 p-3 text-xs">
            <div className="flex flex-wrap items-center gap-1">
              {dualEdges.slice(0, 14).map(edgeId => (
                <Button
                  key={edgeId}
                  variant={selectedDualEdge === edgeId ? 'default' : 'outline'}
                  size="xs"
                  className="h-6 px-1.5 font-mono text-[11px]"
                  onClick={() => onSelectDualEdge(edgeId)}
                >
                  {edgeId.split('#')[0]}
                </Button>
              ))}
            </div>
            <div className="space-y-1.5">
              {dualRows.map(row => {
                const anglePct = Math.min(100, Math.round((row.turn_angle_deg / 180) * 100));
                return (
                  <div
                    key={`${row.from_edge}-${row.to_edge}`}
                    className="rounded-md border border-border/70 px-2.5 py-1.5 hover:bg-muted/50"
                    onMouseEnter={() => onHoverEdge(row.to_edge)}
                    onMouseLeave={() => onHoverEdge(null)}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-medium">{row.to_edge.split('#')[0]}</span>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[11px] tabular-nums">
                          {row.turn_angle_deg}°
                        </span>
                        <Badge variant={row.allowed ? 'success' : 'warning'}>
                          {row.allowed ? '允许' : '剪枝'}
                        </Badge>
                      </div>
                    </div>
                    <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn(
                          'h-full rounded-full',
                          row.allowed ? 'bg-accent-teal' : 'bg-accent-amber',
                        )}
                        style={{ width: `${anglePct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {(stage === 'phase1' || stage === 'phase2') && (
          <div className="space-y-2.5 p-3 text-xs">
            {focusedState && (
              <div className="rounded-md border border-border bg-muted/40 p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 font-mono font-semibold text-foreground">
                    <span>
                      {focusedState.u}→{focusedState.v}
                    </span>
                    {focusedState.is_optimal && <Badge variant="default">最优</Badge>}
                    {focusedState.used_reversal_step && <Badge variant="warning">推机反向</Badge>}
                  </div>
                  <span className="font-mono text-sm font-bold text-primary tabular-nums">
                    {focusedState.cumulative_score != null
                      ? focusedState.cumulative_score.toFixed(2)
                      : '-∞'}
                  </span>
                </div>

                {focusedState.cumulative_score != null ? (
                  <div className="mt-2 grid grid-cols-3 gap-1.5 text-[11px]">
                    <div className="rounded-sm bg-background px-2 py-1">
                      <div className="text-muted-foreground">前驱累计</div>
                      <div className="font-mono font-semibold text-foreground tabular-nums">
                        {prevStateForFocused?.cumulative_score != null
                          ? prevStateForFocused.cumulative_score.toFixed(2)
                          : '0.00'}
                      </div>
                    </div>
                    <div className="rounded-sm bg-background px-2 py-1">
                      <div className="text-muted-foreground">发射分</div>
                      <div className="font-mono font-semibold text-foreground tabular-nums">
                        {focusedState.emission_score.toFixed(2)}
                      </div>
                    </div>
                    <div className="rounded-sm bg-background px-2 py-1">
                      <div className="text-muted-foreground">
                        转移 ({focusedState.transition_distance_m ?? 0}m)
                      </div>
                      <div className="font-mono font-semibold text-foreground tabular-nums">
                        {focusedState.transition_score != null
                          ? focusedState.transition_score.toFixed(2)
                          : '0.00'}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="mt-1.5 text-[11px] text-muted-foreground">
                    无满足转角/推机约束的合法前驱
                  </div>
                )}
              </div>
            )}

            <div className="space-y-1.5">
              {visibleStates.map(state => {
                const score = state.cumulative_score;
                const barWidth =
                  score != null
                    ? Math.max(8, Math.round(((score - minScore) / scoreSpan) * 100))
                    : 0;
                const isFocused = focusedState?.state_index === state.state_index;
                return (
                  <div
                    key={state.state_index}
                    role="button"
                    tabIndex={0}
                    className={cn(
                      'cursor-pointer rounded-md border px-2.5 py-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40',
                      isFocused
                        ? 'border-primary/50 bg-primary/5'
                        : 'border-transparent hover:border-border hover:bg-muted/40',
                    )}
                    onClick={() => setFocusedStateIndex(state.state_index)}
                    onKeyDown={event => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        setFocusedStateIndex(state.state_index);
                      }
                    }}
                    onMouseEnter={() => onHoverEdge(state.directed_edge)}
                    onMouseLeave={() => onHoverEdge(null)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1 font-mono text-[11px] font-medium">
                        <span>
                          {state.u}→{state.v}
                        </span>
                        {state.reversed_used && (
                          <span className="text-accent-amber" title="已使用推机反向">
                            ↻
                          </span>
                        )}
                      </span>
                      <div className="flex items-center gap-2 font-mono text-[11px] tabular-nums">
                        <span className="text-muted-foreground">
                          {state.transition_distance_m != null
                            ? `${state.transition_distance_m}m`
                            : '—'}
                        </span>
                        <span
                          className={cn(
                            'w-[48px] text-right font-semibold',
                            state.is_optimal ? 'text-primary' : 'text-foreground',
                          )}
                        >
                          {score != null ? score.toFixed(2) : '-∞'}
                        </span>
                      </div>
                    </div>
                    {score != null && (
                      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
                        <div
                          className={cn(
                            'h-full rounded-full',
                            state.is_optimal ? 'bg-primary' : 'bg-slate-400/70',
                          )}
                          style={{ width: `${barWidth}%` }}
                        />
                      </div>
                    )}
                  </div>
                );
              })}

              {sortedStates.length > DEFAULT_VISIBLE_ROWS && (
                <Button
                  variant="ghost"
                  size="xs"
                  className="h-7 w-full text-[11px] text-muted-foreground"
                  onClick={() => setExpandStates(value => !value)}
                >
                  {expandStates
                    ? '收起'
                    : `展开其余 ${sortedStates.length - DEFAULT_VISIBLE_ROWS} 个状态`}
                </Button>
              )}
            </div>
          </div>
        )}

        {stage === 'final' && (
          <div className="space-y-3 p-3 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={trace.final_result.status === 'success' ? 'success' : 'destructive'}>
                {trace.final_result.status === 'success' ? '匹配成功' : '匹配失败'}
              </Badge>
              {trace.final_result.used_phase && (
                <Badge variant="secondary">
                  {trace.final_result.used_phase === 'phase1' ? 'Phase 1' : 'Phase 2'}
                </Badge>
              )}
            </div>
            {trace.final_result.error_message ? (
              <p className="text-destructive">{trace.final_result.error_message}</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {finalEdges.map((edgeId, idx) => (
                  <Badge
                    key={`${edgeId}-${idx}`}
                    variant="outline"
                    className="cursor-pointer font-mono"
                    onMouseEnter={() => onHoverEdge(edgeId)}
                    onMouseLeave={() => onHoverEdge(null)}
                  >
                    {idx + 1}. {edgeId.split('#')[0]}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
