import { useMemo } from 'react';
import type {
  DemoDecodeAttempt,
  DemoGraphEdge,
  DemoObservationTrace,
  DemoTraceResponse,
} from '@/api/types';
import {
  DEMO_SVG_COLORS,
  closestPointOnSegment,
  directedEdgeCoords,
} from './types';
import type { DemoStage } from './types';

interface NetworkStageOverlaysProps {
  trace: DemoTraceResponse;
  stage: DemoStage;
  attempt: DemoDecodeAttempt;
  selectedObs: DemoObservationTrace | undefined;
  selectedDualEdge: string | null;
  highlightedDirectedEdge: string | null;
  hoveredCandidateEdgeId: string | null;
  edgeMap: Map<string, DemoGraphEdge>;
  toSvgX(x: number): number;
  toSvgY(y: number): number;
}

function segmentMidAndAngle(x1: number, y1: number, x2: number, y2: number) {
  return {
    mx: (x1 + x2) / 2,
    my: (y1 + y2) / 2,
    angleDeg: (Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI,
  };
}

export function NetworkStageOverlays({
  trace,
  stage,
  attempt,
  selectedObs,
  selectedDualEdge,
  highlightedDirectedEdge,
  hoveredCandidateEdgeId,
  edgeMap,
  toSvgX,
  toSvgY,
}: NetworkStageOverlaysProps) {
  const { edges } = trace.graph;

  const dualTransitions = useMemo(() => {
    if (stage !== 'dual-graph' || !selectedDualEdge) return [];
    return trace.dual_graph.transitions.filter(item => item.from_edge === selectedDualEdge);
  }, [stage, selectedDualEdge, trace.dual_graph.transitions]);

  const highlightedTarget = highlightedDirectedEdge ?? (stage === 'dual-graph' ? selectedDualEdge : null);
  const highlightedCoords = useMemo(
    () => (highlightedTarget ? directedEdgeCoords(highlightedTarget, edges) : null),
    [highlightedTarget, edges],
  );

  const candidateItems = useMemo(() => {
    if (stage !== 'candidates' || !selectedObs) return [];
    return selectedObs.candidates
      .map((cand, idx) => {
        const edge = edgeMap.get(cand.edge_id);
        if (!edge || edge.coords.length < 2) return null;
        const a = edge.coords[0];
        const b = edge.coords[edge.coords.length - 1];
        const [projX, projY] = closestPointOnSegment(
          selectedObs.x,
          selectedObs.y,
          a[0],
          a[1],
          b[0],
          b[1],
        );
        return { cand, idx, a, b, projX, projY };
      })
      .filter((item): item is NonNullable<typeof item> => item !== null);
  }, [stage, selectedObs, edgeMap]);

  const activeProjection = useMemo(() => {
    if (candidateItems.length === 0) return null;
    if (hoveredCandidateEdgeId) {
      return (
        candidateItems.find(item => item.cand.edge_id === hoveredCandidateEdgeId) ??
        candidateItems[0]
      );
    }
    return candidateItems[0];
  }, [candidateItems, hoveredCandidateEdgeId]);

  const showPushbackCircle = useMemo(() => {
    if (stage !== 'phase1' && stage !== 'phase2') return false;
    if (!attempt.reversal_origin || !attempt.pushback_radius_m) return false;
    if (trace.scenario.id === 'departure_pushback') return true;
    return (attempt.layers ?? []).some(layer =>
      layer.states.some(state => state.is_optimal && state.used_reversal_step),
    );
  }, [stage, attempt, trace.scenario.id]);

  const renderDirectedTrack = (
    directedId: string,
    color: string,
    strokeWidth: number,
    keyPrefix: string,
    options?: { dashed?: boolean; opacity?: number; chevron?: boolean },
  ) => {
    const coords = directedEdgeCoords(directedId, edges);
    if (!coords || coords.length < 2) return null;
    const x1 = toSvgX(coords[0][0]);
    const y1 = toSvgY(coords[0][1]);
    const x2 = toSvgX(coords[coords.length - 1][0]);
    const y2 = toSvgY(coords[coords.length - 1][1]);
    const { mx, my, angleDeg } = segmentMidAndAngle(x1, y1, x2, y2);
    return (
      <g
        key={`${keyPrefix}-${directedId}`}
        className="pointer-events-none"
        opacity={options?.opacity ?? 1}
      >
        <line
          x1={x1}
          y1={y1}
          x2={x2}
          y2={y2}
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={options?.dashed ? '5 4' : undefined}
        />
        {options?.chevron && (
          <path
            d="M -4.2 -3.4 L 4.4 0 L -4.2 3.4 L -2.2 0 z"
            fill={color}
            stroke={DEMO_SVG_COLORS.background}
            strokeWidth={0.9}
            strokeLinejoin="round"
            transform={`translate(${mx}, ${my}) rotate(${angleDeg})`}
          />
        )}
      </g>
    );
  };

  return (
    <>
      {(stage === 'phase1' || stage === 'phase2') && (
        <g className="pointer-events-none">
          {(attempt.start_edges ?? []).map(edgeId =>
            renderDirectedTrack(edgeId, DEMO_SVG_COLORS.teal, 9, 'start-halo', { opacity: 0.18 }),
          )}
          {(attempt.end_edges ?? []).map(edgeId =>
            renderDirectedTrack(edgeId, DEMO_SVG_COLORS.amber, 9, 'end-halo', { opacity: 0.14 }),
          )}
          {showPushbackCircle && attempt.reversal_origin && attempt.pushback_radius_m && (
            <g>
              <circle
                cx={toSvgX(attempt.reversal_origin.x)}
                cy={toSvgY(attempt.reversal_origin.y)}
                r={attempt.pushback_radius_m}
                fill="none"
                stroke={DEMO_SVG_COLORS.amber}
                strokeWidth={1}
                strokeDasharray="5 5"
                opacity={0.45}
              />
              <path
                d={`M ${toSvgX(attempt.reversal_origin.x) - 3.5} ${toSvgY(attempt.reversal_origin.y)} h 7 M ${toSvgX(attempt.reversal_origin.x)} ${toSvgY(attempt.reversal_origin.y) - 3.5} v 7`}
                stroke={DEMO_SVG_COLORS.amber}
                strokeWidth={1.1}
                opacity={0.7}
              />
            </g>
          )}
        </g>
      )}

      {stage === 'candidates' && selectedObs && (
        <g className="pointer-events-none">
          <circle
            cx={toSvgX(selectedObs.x)}
            cy={toSvgY(selectedObs.y)}
            r={trace.config.candidate_radius}
            fill={DEMO_SVG_COLORS.primary}
            fillOpacity={0.03}
            stroke={DEMO_SVG_COLORS.primary}
            strokeWidth={0.9}
            strokeDasharray="4 4"
            opacity={0.55}
          />
          {candidateItems.map(({ cand, idx, a, b }) => {
            const isFocused = activeProjection?.cand.edge_id === cand.edge_id;
            const color = isFocused ? DEMO_SVG_COLORS.primary : DEMO_SVG_COLORS.teal;
            const opacity = isFocused ? 0.92 : Math.max(0.28, 0.58 - idx * 0.08);
            return (
              <line
                key={`cand-${cand.edge_id}`}
                x1={toSvgX(a[0])}
                y1={toSvgY(a[1])}
                x2={toSvgX(b[0])}
                y2={toSvgY(b[1])}
                stroke={color}
                strokeWidth={isFocused ? 2.8 : 2.1}
                strokeLinecap="round"
                opacity={opacity}
              />
            );
          })}
          {activeProjection && (
            <g>
              <line
                x1={toSvgX(selectedObs.x)}
                y1={toSvgY(selectedObs.y)}
                x2={toSvgX(activeProjection.projX)}
                y2={toSvgY(activeProjection.projY)}
                stroke={DEMO_SVG_COLORS.primary}
                strokeWidth={1.1}
                strokeDasharray="3 2.5"
              />
              <circle
                cx={toSvgX(activeProjection.projX)}
                cy={toSvgY(activeProjection.projY)}
                r={2.5}
                fill={DEMO_SVG_COLORS.primary}
              />
              <text
                x={(toSvgX(selectedObs.x) + toSvgX(activeProjection.projX)) / 2 + 6}
                y={(toSvgY(selectedObs.y) + toSvgY(activeProjection.projY)) / 2 - 4}
                fontSize={9}
                fontWeight={600}
                fill={DEMO_SVG_COLORS.primary}
              >
                {activeProjection.cand.distance_m}m
              </text>
            </g>
          )}
        </g>
      )}

      {stage === 'dual-graph' &&
        dualTransitions.map(tr => {
          const coords = directedEdgeCoords(tr.to_edge, edges);
          if (!coords || coords.length < 2) return null;
          const x1 = toSvgX(coords[0][0]);
          const y1 = toSvgY(coords[0][1]);
          const x2 = toSvgX(coords[coords.length - 1][0]);
          const y2 = toSvgY(coords[coords.length - 1][1]);
          const color = tr.allowed ? DEMO_SVG_COLORS.teal : DEMO_SVG_COLORS.amber;
          return (
            <g key={`dual-${tr.from_edge}-${tr.to_edge}`} className="pointer-events-none">
              {renderDirectedTrack(tr.to_edge, color, tr.allowed ? 2.4 : 1.8, 'dual-out', {
                dashed: !tr.allowed,
                chevron: tr.allowed,
                opacity: tr.allowed ? 0.92 : 0.78,
              })}
              <text
                x={(x1 + x2) / 2}
                y={(y1 + y2) / 2 + 13}
                textAnchor="middle"
                fontSize={9}
                fontWeight={600}
                fill={color}
              >
                {tr.turn_angle_deg}° {tr.allowed ? '✓' : '✕'}
              </text>
            </g>
          );
        })}

      {(stage === 'phase1' || stage === 'phase2') && (
        <g className="pointer-events-none">
          {(attempt.decoded_edges ?? []).map(edgeId =>
            renderDirectedTrack(
              edgeId,
              attempt.status === 'accepted' ? DEMO_SVG_COLORS.primary : DEMO_SVG_COLORS.amber,
              2.2,
              'decoded',
              {
                dashed: attempt.status !== 'accepted',
                chevron: true,
              },
            ),
          )}
        </g>
      )}

      {stage === 'final' && (
        <g className="pointer-events-none">
          {(attempt.decoded_edges ?? [])
            .filter(edgeId => !(trace.final_result.edges ?? []).includes(edgeId))
            .map(edgeId =>
              renderDirectedTrack(edgeId, DEMO_SVG_COLORS.subtleLabel, 2.2, 'trimmed-out', {
                dashed: true,
                opacity: 0.65,
              }),
            )}
          {(trace.final_result.edges ?? []).map(edgeId =>
            renderDirectedTrack(edgeId, DEMO_SVG_COLORS.primary, 2.4, 'final', { chevron: true }),
          )}
        </g>
      )}

      {highlightedCoords && highlightedCoords.length >= 2 && highlightedTarget && (
        <g className="pointer-events-none">
          {renderDirectedTrack(highlightedTarget, DEMO_SVG_COLORS.primary, 3, 'highlight', {
            chevron: true,
          })}
        </g>
      )}
    </>
  );
}
