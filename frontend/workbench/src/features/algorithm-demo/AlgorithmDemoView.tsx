import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, RotateCcw, SlidersHorizontal } from 'lucide-react';
import { api } from '@/api/client';
import type {
  DemoMatchConfig,
  DemoPointInput,
  DemoScenarioSummary,
  DemoTraceResponse,
} from '@/api/types';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Spinner } from '@/components/ui/spinner';
import { IconActionButton } from '@/components/ui/workbench-shell';
import { DemoInspectorPanel } from './DemoInspectorPanel';
import { NetworkCanvas } from './NetworkCanvas';
import { TrellisCanvas } from './TrellisCanvas';
import { DEMO_STAGES, activeDecodeAttempt } from './types';
import type { DemoStage } from './types';

interface AlgorithmDemoViewProps {
  onClose(): void;
}

interface ConfigDraftText {
  gps_sigma: string;
  candidate_radius: string;
  max_transition_turn_angle_deg: string;
  max_pushback_radius_m: string;
}

function configToDraft(config: DemoMatchConfig): ConfigDraftText {
  return {
    gps_sigma: String(config.gps_sigma),
    candidate_radius: String(config.candidate_radius),
    max_transition_turn_angle_deg: String(config.max_transition_turn_angle_deg),
    max_pushback_radius_m: String(config.max_pushback_radius_m),
  };
}

function parseConfigDraft(
  draft: ConfigDraftText,
  base: DemoMatchConfig,
): { config: DemoMatchConfig | null; error: string | null } {
  const sigma = Number(draft.gps_sigma);
  const radius = Number(draft.candidate_radius);
  const angle = Number(draft.max_transition_turn_angle_deg);
  const pushback = Number(draft.max_pushback_radius_m);

  if (!Number.isFinite(sigma) || sigma <= 0) return { config: null, error: 'GPS σ 需大于 0' };
  if (!Number.isFinite(radius) || radius <= 0) return { config: null, error: '召回半径需大于 0' };
  if (!Number.isFinite(angle) || angle <= 0 || angle > 180) {
    return { config: null, error: '最大转角需在 (0, 180] 内' };
  }
  if (!Number.isFinite(pushback) || pushback <= 0) {
    return { config: null, error: '推机半径需大于 0' };
  }
  return {
    config: {
      ...base,
      gps_sigma: sigma,
      candidate_radius: radius,
      max_transition_turn_angle_deg: angle,
      max_pushback_radius_m: pushback,
    },
    error: null,
  };
}

export function AlgorithmDemoView({ onClose }: AlgorithmDemoViewProps) {
  const [scenarios, setScenarios] = useState<DemoScenarioSummary[]>([]);
  const [scenarioId, setScenarioId] = useState<string>('');
  const [trace, setTrace] = useState<DemoTraceResponse | null>(null);
  const [committedPoints, setCommittedPoints] = useState<DemoPointInput[] | null>(null);
  const [configDraft, setConfigDraft] = useState<ConfigDraftText | null>(null);
  const [paramsOpen, setParamsOpen] = useState(false);
  const [stage, setStage] = useState<DemoStage>('candidates');
  const [selectedObsIndex, setSelectedObsIndex] = useState(0);
  const [selectedDualEdge, setSelectedDualEdge] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const [hoveredCandidateEdgeId, setHoveredCandidateEdgeId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const activeTraceControllerRef = useRef<AbortController | null>(null);

  const runTrace = useCallback(
    async (id: string, observations?: DemoPointInput[] | null, config?: DemoMatchConfig | null) => {
      activeTraceControllerRef.current?.abort();
      const controller = new AbortController();
      activeTraceControllerRef.current = controller;
      setLoading(true);
      setError('');
      try {
        const result = await api.demoTrace(
          {
            scenario_id: id,
            observations: observations ?? null,
            config: config ?? null,
          },
          controller.signal,
        );
        if (activeTraceControllerRef.current !== controller) return;
        setTrace(result);
        setCommittedPoints(result.observations.map(item => ({ x: item.x, y: item.y })));
        setConfigDraft(configToDraft(result.config));
        setSelectedDualEdge(current => {
          if (current && result.dual_graph.transitions.some(t => t.from_edge === current)) {
            return current;
          }
          return result.dual_graph.transitions[0]?.from_edge ?? null;
        });
      } catch (err) {
        if ((err as Error).name !== 'AbortError' && activeTraceControllerRef.current === controller) {
          setError(err instanceof Error ? err.message : '加载算法演示失败');
        }
      } finally {
        if (activeTraceControllerRef.current === controller) {
          setLoading(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    const scenariosController = new AbortController();
    api
      .demoScenarios(scenariosController.signal)
      .then(resp => {
        setScenarios(resp.scenarios);
        const first = resp.scenarios[0];
        if (first) {
          setScenarioId(first.id);
          void runTrace(first.id);
        }
      })
      .catch(err => {
        if ((err as Error).name !== 'AbortError') {
          setError(err instanceof Error ? err.message : '无法获取演示场景');
          setLoading(false);
        }
      });
    return () => {
      scenariosController.abort();
      activeTraceControllerRef.current?.abort();
    };
  }, [runTrace]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !paramsOpen) onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose, paramsOpen]);

  const handleScenarioChange = (nextId: string) => {
    setScenarioId(nextId);
    setSelectedObsIndex(0);
    setHoveredEdge(null);
    setHoveredCandidateEdgeId(null);
    setStage(nextId === 'phase2_fallback' ? 'phase2' : 'candidates');
    void runTrace(nextId);
  };

  const handleReset = () => {
    if (!scenarioId) return;
    setSelectedObsIndex(0);
    setHoveredEdge(null);
    setHoveredCandidateEdgeId(null);
    void runTrace(scenarioId);
  };

  const handleCommitPoints = useCallback(
    (points: DemoPointInput[]) => {
      if (!scenarioId || !trace) return;
      void runTrace(scenarioId, points, trace.config);
    },
    [scenarioId, trace, runTrace],
  );

  const parsedDraft = useMemo(
    () => (configDraft && trace ? parseConfigDraft(configDraft, trace.config) : null),
    [configDraft, trace],
  );

  const attempt = trace ? activeDecodeAttempt(trace, stage) : null;
  const trellisTitle =
    stage === 'phase1'
      ? 'Phase 1 状态转移'
      : stage === 'phase2'
        ? trace?.phase2
          ? 'Phase 2 状态转移'
          : 'Phase 1 已通过（跳过 Phase 2）'
        : trace?.final_result.used_phase === 'phase2'
          ? 'Phase 2 状态转移'
          : 'Phase 1 状态转移';

  return (
    <div className="fixed inset-0 z-[1600] flex flex-col bg-background">
      <header className="flex h-[46px] shrink-0 items-center justify-between gap-3 border-b border-border bg-background px-3">
        <div className="flex items-center gap-2">
          <IconActionButton
            label="返回工作台"
            tooltip="返回工作台（Esc）"
            className="text-muted-foreground hover:text-foreground"
            onClick={onClose}
          >
            <ArrowLeft className="h-4 w-4" />
          </IconActionButton>
          {scenarios.length > 0 && (
            <Select value={scenarioId} onValueChange={handleScenarioChange}>
              <SelectTrigger className="h-8 w-[220px] text-xs font-medium">
                <SelectValue placeholder="选择场景" />
              </SelectTrigger>
              <SelectContent>
                {scenarios.map(item => (
                  <SelectItem key={item.id} value={item.id} className="text-xs">
                    {item.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        <div className="flex items-center rounded-md border border-border bg-muted/60 p-0.5">
          {DEMO_STAGES.map(item => {
            const active = stage === item.key;
            const phase2Skipped = item.key === 'phase2' && trace && !trace.phase2;
            return (
              <Button
                key={item.key}
                variant={active ? 'default' : 'ghost'}
                size="xs"
                className="h-7 gap-1 px-2.5 text-xs"
                onClick={() => setStage(item.key)}
              >
                <span className="font-mono text-[11px] opacity-70">{item.step}</span>
                <span className={phase2Skipped && !active ? 'opacity-50' : undefined}>
                  {item.label}
                </span>
              </Button>
            );
          })}
        </div>

        <div className="flex items-center gap-1.5">
          {trace && (
            <Badge
              variant={trace.final_result.status === 'success' ? 'success' : 'destructive'}
              className="tabular-nums"
            >
              {trace.final_result.status === 'success'
                ? `${trace.final_result.used_phase === 'phase2' ? 'P2' : 'P1'} · ${(trace.final_result.edges ?? []).length}段`
                : trace.final_result.error_code ?? '失败'}
            </Badge>
          )}

          {configDraft && trace && (
            <Popover open={paramsOpen} onOpenChange={setParamsOpen}>
              <PopoverTrigger asChild>
                <Button variant="outline" size="xs" className="h-7 gap-1 px-2 text-xs">
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                  参数
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-[260px] space-y-3 p-3">
                <div className="grid grid-cols-2 gap-2.5">
                  <div className="space-y-1">
                    <Label htmlFor="demo-sigma" className="text-[11px]">
                      GPS σ (m)
                    </Label>
                    <Input
                      id="demo-sigma"
                      type="number"
                      step="1"
                      min="1"
                      value={configDraft.gps_sigma}
                      onChange={e =>
                        setConfigDraft(cur => (cur ? { ...cur, gps_sigma: e.target.value } : cur))
                      }
                      className="h-7 text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="demo-radius" className="text-[11px]">
                      召回半径 (m)
                    </Label>
                    <Input
                      id="demo-radius"
                      type="number"
                      step="10"
                      min="10"
                      value={configDraft.candidate_radius}
                      onChange={e =>
                        setConfigDraft(cur =>
                          cur ? { ...cur, candidate_radius: e.target.value } : cur,
                        )
                      }
                      className="h-7 text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="demo-angle" className="text-[11px]">
                      最大转角 (°)
                    </Label>
                    <Input
                      id="demo-angle"
                      type="number"
                      step="5"
                      min="10"
                      max="180"
                      value={configDraft.max_transition_turn_angle_deg}
                      onChange={e =>
                        setConfigDraft(cur =>
                          cur ? { ...cur, max_transition_turn_angle_deg: e.target.value } : cur,
                        )
                      }
                      className="h-7 text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="demo-pushback" className="text-[11px]">
                      推机半径 (m)
                    </Label>
                    <Input
                      id="demo-pushback"
                      type="number"
                      step="20"
                      min="20"
                      value={configDraft.max_pushback_radius_m}
                      onChange={e =>
                        setConfigDraft(cur =>
                          cur ? { ...cur, max_pushback_radius_m: e.target.value } : cur,
                        )
                      }
                      className="h-7 text-xs"
                    />
                  </div>
                </div>
                {parsedDraft?.error && (
                  <p className="text-[11px] text-destructive">{parsedDraft.error}</p>
                )}
                <div className="flex justify-end gap-1.5">
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => setConfigDraft(configToDraft(trace.scenario.default_config))}
                  >
                    默认
                  </Button>
                  <Button
                    size="xs"
                    disabled={!parsedDraft?.config}
                    onClick={() => {
                      if (!parsedDraft?.config) return;
                      setParamsOpen(false);
                      void runTrace(scenarioId, committedPoints, parsedDraft.config);
                    }}
                  >
                    应用
                  </Button>
                </div>
              </PopoverContent>
            </Popover>
          )}

          <IconActionButton
            label="重置场景"
            tooltip="重置观测点与参数"
            className="text-muted-foreground hover:text-foreground"
            onClick={handleReset}
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </IconActionButton>
        </div>
      </header>

      {error && (
        <Alert variant="destructive" className="mx-3 mt-2">
          {error}
        </Alert>
      )}

      <div className="relative min-h-0 flex-1">
        {trace && attempt ? (
          <ResizablePanelGroup orientation="horizontal" className="h-full w-full">
            <ResizablePanel defaultSize="58%" minSize="38%" maxSize="75%">
              <NetworkCanvas
                trace={trace}
                stage={stage}
                selectedObsIndex={selectedObsIndex}
                selectedDualEdge={selectedDualEdge}
                highlightedDirectedEdge={hoveredEdge}
                hoveredCandidateEdgeId={hoveredCandidateEdgeId}
                onSelectObs={setSelectedObsIndex}
                onSelectDualEdge={setSelectedDualEdge}
                onCommitPoints={handleCommitPoints}
              />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize="42%" minSize="25%" maxSize="62%">
              <div className="flex h-full min-h-0 flex-col divide-y divide-border">
                <div className="h-[46%] min-h-[200px] shrink-0 overflow-hidden">
                  <TrellisCanvas
                    attempt={attempt}
                    title={trellisTitle}
                    selectedObsIndex={selectedObsIndex}
                    hoveredEdge={hoveredEdge}
                    onHoverEdge={setHoveredEdge}
                    onSelectObs={setSelectedObsIndex}
                  />
                </div>
                <div className="min-h-0 flex-1 overflow-hidden">
                  <DemoInspectorPanel
                    trace={trace}
                    stage={stage}
                    selectedObsIndex={selectedObsIndex}
                    selectedDualEdge={selectedDualEdge}
                    onSelectObs={setSelectedObsIndex}
                    onSelectDualEdge={setSelectedDualEdge}
                    onHoverEdge={setHoveredEdge}
                    onHoverCandidateEdge={setHoveredCandidateEdgeId}
                  />
                </div>
              </div>
            </ResizablePanel>
          </ResizablePanelGroup>
        ) : (
          <div className="grid h-full place-items-center">
            <Spinner className="h-7 w-7" />
          </div>
        )}

        {loading && trace && (
          <div className="pointer-events-none absolute right-3 top-3 flex items-center gap-1.5 rounded-md border border-border bg-background/90 px-2 py-1 text-[11px] text-muted-foreground shadow-2xs">
            <Spinner className="h-3 w-3" />
            <span>重算中</span>
          </div>
        )}
      </div>
    </div>
  );
}
