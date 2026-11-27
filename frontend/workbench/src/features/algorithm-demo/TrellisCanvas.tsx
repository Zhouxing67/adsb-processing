import { memo, useMemo, useState } from 'react';
import type { DemoDecodeAttempt, DemoTrellisLayer, DemoTrellisState } from '@/api/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DEMO_SVG_COLORS } from './types';

interface TrellisCanvasProps {
  attempt: DemoDecodeAttempt;
  title: string;
  selectedObsIndex: number;
  hoveredEdge: string | null;
  onHoverEdge(directedEdge: string | null): void;
  onSelectObs(obsIndex: number): void;
}

const COMPACT_LIMIT = 6;

function pickDisplayStates(layer: DemoTrellisLayer, showAll: boolean): DemoTrellisState[] {
  if (showAll || layer.states.length <= COMPACT_LIMIT) return layer.states;
  const sorted = [...layer.states].sort((a, b) => {
    if (a.is_optimal !== b.is_optimal) return a.is_optimal ? -1 : 1;
    const scoreA = a.cumulative_score ?? -1e9;
    const scoreB = b.cumulative_score ?? -1e9;
    return scoreB - scoreA;
  });
  return sorted.slice(0, COMPACT_LIMIT).sort((a, b) => a.state_index - b.state_index);
}

export const TrellisCanvas = memo(function TrellisCanvas({
  attempt,
  title,
  selectedObsIndex,
  hoveredEdge,
  onHoverEdge,
  onSelectObs,
}: TrellisCanvasProps) {
  const [showAll, setShowAll] = useState(false);
  const attemptLayers = attempt.layers ?? [];
  const hasHiddenStates = attemptLayers.some(layer => layer.states.length > COMPACT_LIMIT);

  const layout = useMemo(() => {
    const layers = attemptLayers;
    if (layers.length === 0) return null;

    const displayLayers = layers.map(layer => ({
      layer,
      states: pickDisplayStates(layer, showAll),
    }));
    const maxStates = Math.max(1, ...displayLayers.map(item => item.states.length));
    const colGap = 108;
    const rowGap = 34;
    const padX = 56;
    const padTop = 32;
    const padBottom = 18;
    const width = Math.max(360, padX * 2 + (layers.length - 1) * colGap);
    const height = Math.max(190, padTop + padBottom + (maxStates - 1) * rowGap);

    const posMap = new Map<string, { x: number; y: number }>();
    displayLayers.forEach(({ layer, states }, colIdx) => {
      const x = padX + colIdx * colGap;
      const totalH = (states.length - 1) * rowGap;
      const startY = padTop + (height - padTop - padBottom - totalH) / 2;
      states.forEach((state, rowIdx) => {
        posMap.set(`${layer.layer_index}:${state.state_index}`, {
          x,
          y: startY + rowIdx * rowGap,
        });
      });
    });

    return { displayLayers, posMap, width, height, colGap, padX };
  }, [attemptLayers, showAll]);

  const statusBadge =
    attempt.status === 'accepted'
      ? { label: '通过', variant: 'success' as const }
      : attempt.status === 'rejected'
        ? { label: '校验未通过', variant: 'warning' as const }
        : { label: '无合法路径', variant: 'destructive' as const };

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-xs font-medium text-foreground">{title}</span>
          <Badge variant={statusBadge.variant}>{statusBadge.label}</Badge>
        </div>
        {hasHiddenStates && (
          <Button
            variant="ghost"
            size="xs"
            className="h-6 px-2 text-[11px] text-muted-foreground"
            onClick={() => setShowAll(value => !value)}
          >
            {showAll ? '精简显示' : '显示全部'}
          </Button>
        )}
      </div>

      {attempt.rejection_reason && (
        <div className="shrink-0 border-b border-border bg-amber-50/60 px-3 py-1 text-[11px] text-accent-amber">
          {attempt.rejection_reason}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto p-2.5">
        {!layout ? (
          <div className="grid h-full place-items-center text-xs text-muted-foreground">
            当前阶段无状态转移数据
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            className="h-full min-h-[180px] w-full select-none"
          >
            {layout.displayLayers.map(({ layer }, colIdx) => {
              const x = layout.padX + colIdx * layout.colGap;
              const isObsSelected =
                layer.observation_index != null && layer.observation_index === selectedObsIndex;
              return (
                <g key={`col-${layer.layer_index}`}>
                  <line
                    x1={x}
                    y1={22}
                    x2={x}
                    y2={layout.height - 8}
                    stroke={isObsSelected ? DEMO_SVG_COLORS.primary : DEMO_SVG_COLORS.muted}
                    strokeWidth={isObsSelected ? 1.4 : 1}
                    strokeDasharray="3 3"
                  />
                  <text
                    x={x}
                    y={14}
                    textAnchor="middle"
                    fontSize={10}
                    fontWeight={isObsSelected ? 700 : 500}
                    fill={isObsSelected ? DEMO_SVG_COLORS.primary : DEMO_SVG_COLORS.mutedForeground}
                    className={layer.observation_index != null ? 'cursor-pointer' : undefined}
                    onClick={() => {
                      const obsIdx = layer.observation_index;
                      if (obsIdx != null) onSelectObs(obsIdx);
                    }}
                  >
                    {layer.label}
                  </text>
                </g>
              );
            })}

            {layout.displayLayers.map(({ layer, states }) =>
              states.map(state => {
                const prevIdx = state.best_prev_index;
                if (layer.layer_index === 0 || prevIdx == null) return null;
                const from = layout.posMap.get(`${layer.layer_index - 1}:${prevIdx}`);
                const to = layout.posMap.get(`${layer.layer_index}:${state.state_index}`);
                if (!from || !to) return null;
                const prevLayer = attemptLayers[layer.layer_index - 1];
                const prevState = prevLayer?.states[prevIdx];
                const isOptimalLink = Boolean(state.is_optimal && prevState?.is_optimal);
                const stroke =
                  isOptimalLink && state.used_reversal_step
                    ? DEMO_SVG_COLORS.amber
                    : isOptimalLink
                      ? DEMO_SVG_COLORS.primary
                      : DEMO_SVG_COLORS.border;
                return (
                  <g key={`link-${layer.layer_index}-${state.state_index}`}>
                    <line
                      x1={from.x + 34}
                      y1={from.y}
                      x2={to.x - 34}
                      y2={to.y}
                      stroke={stroke}
                      strokeWidth={isOptimalLink ? 2.2 : 1}
                      strokeDasharray={isOptimalLink && state.used_reversal_step ? '5 3' : undefined}
                      opacity={isOptimalLink ? 1 : 0.7}
                    />
                    {isOptimalLink && state.used_reversal_step && (
                      <text
                        x={(from.x + to.x) / 2}
                        y={(from.y + to.y) / 2 - 6}
                        textAnchor="middle"
                        fontSize={8.5}
                        fontWeight={700}
                        fill={DEMO_SVG_COLORS.amber}
                      >
                        推机反向
                      </text>
                    )}
                  </g>
                );
              }),
            )}

            {layout.displayLayers.map(({ layer, states }) =>
              states.map(state => {
                const pos = layout.posMap.get(`${layer.layer_index}:${state.state_index}`);
                if (!pos) return null;
                const isHovered = hoveredEdge === state.directed_edge;
                const reachable = state.cumulative_score != null;
                const borderColor = state.is_optimal
                  ? DEMO_SVG_COLORS.primary
                  : isHovered
                    ? DEMO_SVG_COLORS.teal
                    : state.reversed_used
                      ? DEMO_SVG_COLORS.reversedBorder
                      : DEMO_SVG_COLORS.border;
                const fillColor = state.is_optimal
                  ? DEMO_SVG_COLORS.optimalFill
                  : reachable
                    ? DEMO_SVG_COLORS.background
                    : DEMO_SVG_COLORS.muted;
                return (
                  <g
                    key={`node-${layer.layer_index}-${state.state_index}`}
                    className="cursor-pointer"
                    onMouseEnter={() => onHoverEdge(state.directed_edge)}
                    onMouseLeave={() => onHoverEdge(null)}
                    onClick={() => {
                      const obsIdx = layer.observation_index;
                      if (obsIdx != null) onSelectObs(obsIdx);
                    }}
                  >
                    <rect
                      x={pos.x - 34}
                      y={pos.y - 11}
                      width={68}
                      height={22}
                      rx={4}
                      fill={fillColor}
                      stroke={borderColor}
                      strokeWidth={state.is_optimal || isHovered ? 1.7 : 1}
                    />
                    <text
                      x={pos.x}
                      y={pos.y + 3}
                      textAnchor="middle"
                      fontSize={9}
                      fontWeight={state.is_optimal ? 700 : 500}
                      fill={reachable ? DEMO_SVG_COLORS.foreground : DEMO_SVG_COLORS.subtleLabel}
                    >
                      {state.u}→{state.v}
                      {state.reversed_used ? ' ↻' : ''}
                    </text>
                  </g>
                );
              }),
            )}
          </svg>
        )}
      </div>
    </div>
  );
});
