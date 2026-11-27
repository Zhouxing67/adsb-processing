import type { DemoGraphEdge, DemoTraceResponse } from '@/api/types';

export type DemoStage = 'candidates' | 'dual-graph' | 'phase1' | 'phase2' | 'final';

export interface StageDefinition {
  key: DemoStage;
  step: number;
  label: string;
}

export const DEMO_STAGES: readonly StageDefinition[] = [
  { key: 'candidates', step: 1, label: '召回' },
  { key: 'dual-graph', step: 2, label: '转向' },
  { key: 'phase1', step: 3, label: 'Phase 1' },
  { key: 'phase2', step: 4, label: 'Phase 2' },
  { key: 'final', step: 5, label: '结果' },
];

/** Centralized SVG semantic palette aligned with src/styles/index.css tokens. */
export const DEMO_SVG_COLORS = {
  primary: 'var(--primary)',
  teal: 'var(--accent-teal)',
  amber: 'var(--accent-amber)',
  foreground: 'var(--foreground)',
  mutedForeground: 'var(--muted-foreground)',
  background: 'var(--background)',
  muted: 'var(--muted)',
  border: 'var(--border)',
  runwayDeck: 'var(--border)',
  taxiwayStroke: '#cbd5e1',
  subtleLabel: '#94a3b8',
  optimalFill: '#eff6ff',
  reversedBorder: '#e5c1a6',
} as const;

export function parseDirectedEdge(
  directedId: string,
): { u: string; v: string; key: number } | null {
  const [nodesPart, keyPart] = directedId.split('#');
  if (!nodesPart || keyPart === undefined) return null;
  const [u, v] = nodesPart.split('→');
  if (!u || !v) return null;
  return { u, v, key: Number(keyPart) };
}

export function directedEdgeCoords(
  directedId: string,
  edges: DemoGraphEdge[],
): Array<[number, number]> | null {
  const parsed = parseDirectedEdge(directedId);
  if (!parsed) return null;
  for (const edge of edges) {
    if (edge.key !== parsed.key) continue;
    if (edge.u === parsed.u && edge.v === parsed.v) return edge.coords;
    if (edge.u === parsed.v && edge.v === parsed.u) return [...edge.coords].reverse();
  }
  return null;
}

export function closestPointOnSegment(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): [number, number] {
  const dx = bx - ax;
  const dy = by - ay;
  const lenSq = dx * dx + dy * dy;
  if (lenSq <= 1e-9) return [ax, ay];
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lenSq));
  return [ax + t * dx, ay + t * dy];
}

export function activeDecodeAttempt(trace: DemoTraceResponse, stage: DemoStage) {
  if (stage === 'phase1') return trace.phase1;
  if (stage === 'phase2') return trace.phase2 ?? trace.phase1;
  if (trace.final_result.used_phase === 'phase2' && trace.phase2) return trace.phase2;
  return trace.phase1;
}
