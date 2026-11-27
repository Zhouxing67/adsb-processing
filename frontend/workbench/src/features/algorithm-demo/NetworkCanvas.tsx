import { useEffect, useMemo, useRef, useState } from 'react';
import type { DemoPointInput, DemoTraceResponse } from '@/api/types';
import { NetworkLegend } from './NetworkLegend';
import { NetworkStageOverlays } from './NetworkStageOverlays';
import { DEMO_SVG_COLORS, activeDecodeAttempt } from './types';
import type { DemoStage } from './types';

interface NetworkCanvasProps {
  trace: DemoTraceResponse;
  stage: DemoStage;
  selectedObsIndex: number;
  selectedDualEdge: string | null;
  highlightedDirectedEdge: string | null;
  hoveredCandidateEdgeId: string | null;
  onSelectObs(index: number): void;
  onSelectDualEdge(directedEdge: string): void;
  onCommitPoints(points: DemoPointInput[]): void;
}

export function NetworkCanvas({
  trace,
  stage,
  selectedObsIndex,
  selectedDualEdge,
  highlightedDirectedEdge,
  hoveredCandidateEdgeId,
  onSelectObs,
  onSelectDualEdge,
  onCommitPoints,
}: NetworkCanvasProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const didMoveRef = useRef(false);
  const dragOriginRef = useRef<DemoPointInput | null>(null);
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null);
  const [localPoints, setLocalPoints] = useState<DemoPointInput[]>(() =>
    trace.observations.map(item => ({ x: item.x, y: item.y })),
  );

  useEffect(() => {
    setLocalPoints(trace.observations.map(item => ({ x: item.x, y: item.y })));
    setDraggingIndex(null);
    didMoveRef.current = false;
  }, [trace.observations]);

  const { bounds, nodes, edges } = trace.graph;
  const pad = 22;
  const width = bounds.max_x - bounds.min_x + pad * 2;
  const height = bounds.max_y - bounds.min_y + pad * 2;
  const toSvgX = (x: number) => x - bounds.min_x + pad;
  const toSvgY = (y: number) => bounds.max_y - y + pad;

  const gridLines = useMemo(
    () => ({
      xs: Array.from({ length: Math.floor(width / 60) + 1 }, (_, i) => i * 60),
      ys: Array.from({ length: Math.floor(height / 60) + 1 }, (_, i) => i * 60),
    }),
    [width, height],
  );

  const edgeMap = useMemo(() => new Map(edges.map(edge => [edge.id, edge])), [edges]);

  const clientToWorld = (clientX: number, clientY: number): DemoPointInput | null => {
    const svg = svgRef.current;
    if (!svg) return null;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const local = pt.matrixTransform(ctm.inverse());
    return {
      x: Number(
        Math.max(bounds.min_x + 5, Math.min(bounds.max_x - 5, local.x - pad + bounds.min_x)).toFixed(
          1,
        ),
      ),
      y: Number(
        Math.max(bounds.min_y + 5, Math.min(bounds.max_y - 5, bounds.max_y - (local.y - pad))).toFixed(
          1,
        ),
      ),
    };
  };

  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (draggingIndex === null) return;
    const world = clientToWorld(event.clientX, event.clientY);
    if (!world) return;
    const origin = dragOriginRef.current;
    if (origin && Math.hypot(world.x - origin.x, world.y - origin.y) >= 1.5) {
      didMoveRef.current = true;
    }
    setLocalPoints(current => current.map((point, idx) => (idx === draggingIndex ? world : point)));
  };

  const finishDrag = () => {
    if (draggingIndex === null) return;
    const shouldCommit = didMoveRef.current;
    setDraggingIndex(null);
    didMoveRef.current = false;
    dragOriginRef.current = null;
    if (shouldCommit) {
      onCommitPoints(localPoints);
    }
  };

  const selectedObs = trace.observations[selectedObsIndex] ?? trace.observations[0];
  const attempt = activeDecodeAttempt(trace, stage);
  const showOdBoundary =
    (stage === 'phase1' || stage === 'phase2') && (attempt.start_edges ?? []).length > 0;

  return (
    <div className="relative h-full w-full overflow-hidden bg-background">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        className="h-full w-full select-none"
        onPointerMove={handlePointerMove}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
      >
        {/* Subtle blueprint grid */}
        {gridLines.xs.map(gx => (
          <line key={`gx-${gx}`} x1={gx} y1={0} x2={gx} y2={height} stroke={DEMO_SVG_COLORS.muted} strokeWidth={1} />
        ))}
        {gridLines.ys.map(gy => (
          <line key={`gy-${gy}`} x1={0} y1={gy} x2={width} y2={gy} stroke={DEMO_SVG_COLORS.muted} strokeWidth={1} />
        ))}

        {/* LAYER 1: Quiet blueprint airport surface */}
        {edges.map(edge => {
          if (edge.coords.length < 2) return null;
          const x1 = toSvgX(edge.coords[0][0]);
          const y1 = toSvgY(edge.coords[0][1]);
          const x2 = toSvgX(edge.coords[edge.coords.length - 1][0]);
          const y2 = toSvgY(edge.coords[edge.coords.length - 1][1]);
          const mx = (x1 + x2) / 2;
          const my = (y1 + y2) / 2;
          const isVertical = Math.abs(x2 - x1) < 12;
          const labelX = isVertical ? mx - 13 : mx;
          const labelY = isVertical ? my + 3 : my - (edge.aeroway === 'runway' ? 11 : 7);

          return (
            <g key={edge.id}>
              {edge.aeroway === 'runway' ? (
                <g
                  className={stage === 'dual-graph' ? 'cursor-pointer' : undefined}
                  onClick={() => {
                    if (stage === 'dual-graph') onSelectDualEdge(`${edge.u}→${edge.v}#${edge.key}`);
                  }}
                >
                  <line
                    x1={x1}
                    y1={y1}
                    x2={x2}
                    y2={y2}
                    stroke={DEMO_SVG_COLORS.runwayDeck}
                    strokeWidth={11}
                    strokeLinecap="butt"
                  />
                  <line
                    x1={x1}
                    y1={y1}
                    x2={x2}
                    y2={y2}
                    stroke={DEMO_SVG_COLORS.subtleLabel}
                    strokeWidth={0.9}
                    strokeDasharray="5 5"
                  />
                </g>
              ) : (
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={DEMO_SVG_COLORS.taxiwayStroke}
                  strokeWidth={edge.aeroway === 'parking_position' ? 2 : 2.4}
                  strokeDasharray={edge.aeroway === 'parking_position' ? '3.5 2.5' : undefined}
                  strokeLinecap="round"
                  className={stage === 'dual-graph' ? 'cursor-pointer hover:stroke-slate-500' : undefined}
                  onClick={() => {
                    if (stage === 'dual-graph') onSelectDualEdge(`${edge.u}→${edge.v}#${edge.key}`);
                  }}
                />
              )}
              {edge.ref && (
                <text
                  x={labelX}
                  y={labelY}
                  textAnchor="middle"
                  fontSize={8.5}
                  fontWeight={500}
                  fill={DEMO_SVG_COLORS.subtleLabel}
                  className="pointer-events-none"
                >
                  {edge.ref}
                </text>
              )}
            </g>
          );
        })}

        {/* LAYER 2 & 3: Stage constraints, candidates, turn-angles, and paths */}
        <NetworkStageOverlays
          trace={trace}
          stage={stage}
          attempt={attempt}
          selectedObs={selectedObs}
          selectedDualEdge={selectedDualEdge}
          highlightedDirectedEdge={highlightedDirectedEdge}
          hoveredCandidateEdgeId={hoveredCandidateEdgeId}
          edgeMap={edgeMap}
          toSvgX={toSvgX}
          toSvgY={toSvgY}
        />

        {/* Blueprint nodes */}
        {nodes.map(node => {
          const isStand = node.role === 'stand';
          const isInterface = node.role === 'runway_interface';
          const nx = toSvgX(node.x);
          const ny = toSvgY(node.y);
          return (
            <g key={node.id} className="pointer-events-none">
              <circle
                cx={nx}
                cy={ny}
                r={isStand || isInterface ? 4 : 2.8}
                fill={
                  isStand
                    ? DEMO_SVG_COLORS.teal
                    : isInterface
                      ? DEMO_SVG_COLORS.amber
                      : DEMO_SVG_COLORS.background
                }
                stroke={DEMO_SVG_COLORS.mutedForeground}
                strokeWidth={1.2}
              />
              <text
                x={nx}
                y={ny + (isStand ? -8 : 13)}
                textAnchor="middle"
                fontSize={8.5}
                fontWeight={500}
                fill={DEMO_SVG_COLORS.mutedForeground}
              >
                {node.id}
              </text>
            </g>
          );
        })}

        {/* LAYER 4: Raw GPS observations */}
        {localPoints.length >= 2 && (
          <polyline
            points={localPoints.map(pt => `${toSvgX(pt.x)},${toSvgY(pt.y)}`).join(' ')}
            fill="none"
            stroke={DEMO_SVG_COLORS.subtleLabel}
            strokeWidth={1}
            strokeDasharray="3 3"
            opacity={0.7}
            className="pointer-events-none"
          />
        )}

        {localPoints.map((pt, idx) => {
          const obsTrace = trace.observations[idx];
          const isSelected = idx === selectedObsIndex;
          const retained = obsTrace ? obsTrace.retained : true;
          const cx = toSvgX(pt.x);
          const cy = toSvgY(pt.y);
          return (
            <g
              key={`obs-${idx}`}
              className={draggingIndex === idx ? 'cursor-grabbing' : 'cursor-grab'}
              onPointerDown={event => {
                event.stopPropagation();
                event.currentTarget.setPointerCapture(event.pointerId);
                didMoveRef.current = false;
                dragOriginRef.current = pt;
                setDraggingIndex(idx);
                onSelectObs(idx);
              }}
            >
              <circle cx={cx} cy={cy} r={12} fill="transparent" />
              {isSelected && (
                <>
                  <circle cx={cx} cy={cy} r={9.5} fill={DEMO_SVG_COLORS.primary} fillOpacity={0.12} />
                  <circle
                    cx={cx}
                    cy={cy}
                    r={6.2}
                    fill="none"
                    stroke={DEMO_SVG_COLORS.primary}
                    strokeWidth={1.2}
                  />
                </>
              )}
              <circle
                cx={cx}
                cy={cy}
                r={3.2}
                fill={retained ? DEMO_SVG_COLORS.foreground : DEMO_SVG_COLORS.subtleLabel}
                stroke={DEMO_SVG_COLORS.background}
                strokeWidth={1.3}
              />
              <text
                x={cx + 5.5}
                y={cy - 4.5}
                fontSize={8.5}
                fontWeight={700}
                fill={isSelected ? DEMO_SVG_COLORS.primary : DEMO_SVG_COLORS.foreground}
                stroke={DEMO_SVG_COLORS.background}
                strokeWidth={2.2}
                paintOrder="stroke"
                className="pointer-events-none"
              >
                P{idx + 1}
              </text>
            </g>
          );
        })}
      </svg>

      <NetworkLegend showOdBoundary={showOdBoundary} />
    </div>
  );
}
