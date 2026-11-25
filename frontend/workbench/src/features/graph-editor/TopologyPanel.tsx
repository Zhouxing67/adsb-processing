import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, Crosshair, Play, RotateCcw, Square, X } from 'lucide-react';
import type { EdgeProperties, GeoFeature, LineGeometry, SelectedFeature } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Toggle } from '@/components/ui/toggle';
import { IconActionButton } from '@/components/ui/workbench-shell';
import { formatEdgeId } from '@/domain/features';
import { computeConnectedEdgesAngles } from '@/domain/geometry';
import type { LngLat } from '@/domain/geometry';
import { cn } from '@/lib/utils';

export type AngleMeasureEdge = GeoFeature<LineGeometry, EdgeProperties>;

interface TopologyPanelProps {
  splitValidation: boolean;
  onSplitValidation(): void;
  angleMeasureActive: boolean;
  angleEdges: AngleMeasureEdge[];
  onToggleAngleMeasure(): void;
  onClearAngleEdges(): void;
}

type AnomalyKey = 'isolated' | 'parallel' | 'deadend' | 'islands';

interface AnomalyItem {
  id: string;
  label: string;
  meta?: string;
  feature: SelectedFeature;
}

export function TopologyPanel({
  splitValidation,
  onSplitValidation,
  angleMeasureActive,
  angleEdges,
  onToggleAngleMeasure,
  onClearAngleEdges,
}: TopologyPanelProps) {
  const wb = useWorkbench();
  const topology = wb.state?.topology;
  const [reviewIndex, setReviewIndex] = useState(-1);
  const [openGroup, setOpenGroup] = useState<AnomalyKey | null>(null);
  const [groupCursor, setGroupCursor] = useState<Record<AnomalyKey, number>>({
    isolated: 0,
    parallel: 0,
    deadend: 0,
    islands: 0,
  });

  const nodes = useMemo(
    () => [...(wb.state?.nodes.features ?? [])].sort((a, b) => a.properties.id.localeCompare(b.properties.id)),
    [wb.state?.nodes.features],
  );

  const edges = wb.state?.edges.features ?? [];

  const anomalyGroups = useMemo(() => {
    const isolated: AnomalyItem[] = [];
    const deadend: AnomalyItem[] = [];
    const incidentAeroways = new Map<string, Set<string>>();
    const pairBuckets = new Map<string, typeof edges>();

    for (const edge of edges) {
      const u = String(edge.properties.u);
      const v = String(edge.properties.v);
      const aeroway = String(edge.properties.aeroway ?? '');
      if (!incidentAeroways.has(u)) incidentAeroways.set(u, new Set());
      if (!incidentAeroways.has(v)) incidentAeroways.set(v, new Set());
      incidentAeroways.get(u)!.add(aeroway);
      incidentAeroways.get(v)!.add(aeroway);

      const pairKey = u <= v ? `${u}—${v}` : `${v}—${u}`;
      const bucket = pairBuckets.get(pairKey) ?? [];
      bucket.push(edge);
      pairBuckets.set(pairKey, bucket);
    }

    for (const node of nodes) {
      const id = node.properties.id;
      const deg = Number(node.properties.degree ?? 0);
      if (deg === 0) {
        isolated.push({ id, label: id, feature: node });
      } else if (deg === 1 && node.properties.node_type !== 'runway_interface') {
        const types = incidentAeroways.get(id);
        if (!types?.has('parking_position')) {
          deadend.push({ id, label: id, feature: node });
        }
      }
    }

    const parallel: AnomalyItem[] = [];
    for (const [pairKey, bucket] of [...pairBuckets.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      if (bucket.length >= 2) {
        parallel.push({
          id: pairKey,
          label: pairKey,
          meta: `${bucket.length} 条`,
          feature: bucket[0],
        });
      }
    }

    const islands: AnomalyItem[] = [];
    if (topology && topology.component_count > 1) {
      const sortedComponents = [...topology.components].sort((a, b) => b.size - a.size);
      for (const comp of sortedComponents.slice(1)) {
        const node = nodes.find(item => comp.node_ids.includes(item.properties.id));
        if (node) {
          islands.push({
            id: `comp-${comp.index}`,
            label: `分量 ${comp.index}`,
            meta: `${comp.size} 节点`,
            feature: node,
          });
        }
      }
    }

    return { isolated, parallel, deadend, islands };
  }, [nodes, edges, topology]);

  const nodePositions = useMemo(() => {
    const map = new Map<string, LngLat>();
    for (const node of nodes) {
      map.set(node.properties.id, node.geometry.coordinates);
    }
    return map;
  }, [nodes]);

  const angleResults = useMemo(() => {
    if (angleEdges.length !== 2) return null;
    const [first, second] = angleEdges;
    return computeConnectedEdgesAngles(
      { u: String(first.properties.u), v: String(first.properties.v), coordinates: first.geometry.coordinates },
      { u: String(second.properties.u), v: String(second.properties.v), coordinates: second.geometry.coordinates },
      nodePositions,
    );
  }, [angleEdges, nodePositions]);

  useEffect(() => {
    setReviewIndex(current => (current >= nodes.length ? (nodes.length ? nodes.length - 1 : -1) : current));
  }, [nodes.length]);

  const focusAnomaly = (key: AnomalyKey, index: number) => {
    const list = anomalyGroups[key];
    const item = list[index];
    if (!item) return;
    setGroupCursor(current => ({ ...current, [key]: index }));
    wb.dispatch({ type: 'selected', value: item.feature, focus: true });
  };

  const showReview = (index: number) => {
    const feature = nodes[index];
    if (!feature) return;
    setReviewIndex(index);
    wb.dispatch({ type: 'selected', value: feature, focus: true });
    wb.dispatch({
      type: 'status',
      value:
        index === nodes.length - 1
          ? '已到最后一个节点；这不表示全部复核通过'
          : `遍历位置 ${index + 1} / ${nodes.length} · 节点 ${feature.properties.id}`,
    });
  };

  if (!wb.topologyOpen || !topology) return null;

  const anomalyRows: Array<{ key: AnomalyKey; label: string; items: AnomalyItem[] }> = [
    { key: 'isolated', label: '孤立节点', items: anomalyGroups.isolated },
    { key: 'parallel', label: '平行边组', items: anomalyGroups.parallel },
    { key: 'deadend', label: '断头滑行道', items: anomalyGroups.deadend },
    ...(anomalyGroups.islands.length > 0
      ? [{ key: 'islands' as const, label: '离散孤岛', items: anomalyGroups.islands }]
      : []),
  ];

  const reviewing = reviewIndex >= 0;

  return (
    <aside className="relative z-[900] col-start-1 row-start-2 flex h-full min-h-0 min-w-0 flex-col border-r border-border bg-muted">
      <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-4">
        <h2 className="m-0 text-[15px] font-semibold text-foreground">拓扑概览</h2>
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label="关闭拓扑概览"
          onClick={() => wb.dispatch({ type: 'panel', panel: 'topologyOpen', value: false })}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="divide-y divide-border px-4">
          <div className="grid grid-cols-3 gap-2 py-4 tabular-nums">
            <div className="rounded-md border border-border/70 bg-background px-2.5 py-2">
              <strong
                className={cn(
                  'block text-lg leading-tight font-semibold',
                  topology.component_count > 1 ? 'text-accent-amber' : 'text-accent-teal',
                )}
              >
                {topology.component_count}
              </strong>
              <span className="mt-0.5 block text-[11px] text-muted-foreground">连通分量</span>
            </div>
            <div className="rounded-md border border-border/70 bg-background px-2.5 py-2">
              <strong className="block text-lg leading-tight font-semibold text-accent-teal">
                {topology.largest_component}
              </strong>
              <span className="mt-0.5 block text-[11px] text-muted-foreground">最大分量</span>
            </div>
            <div className="rounded-md border border-border/70 bg-background px-2.5 py-2">
              <strong className="block text-lg leading-tight font-semibold text-accent-amber">
                {topology.dangling_count}
              </strong>
              <span className="mt-0.5 block text-[11px] text-muted-foreground">度为 1</span>
            </div>
          </div>

          <section className="space-y-1.5 py-4">
            <h3 className="m-0 text-xs font-semibold text-foreground">异常定位</h3>
            <div className="space-y-1 text-xs tabular-nums">
              {anomalyRows.map(({ key, label, items }) => {
                const count = items.length;
                const isOpen = openGroup === key && count > 0;
                const cursor = Math.min(groupCursor[key] ?? 0, Math.max(0, count - 1));
                return (
                  <div key={key} className="rounded-md">
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={count === 0}
                      className={cn(
                        'h-7 w-full justify-between px-2 font-normal',
                        isOpen && 'bg-background shadow-2xs',
                        count === 0 && 'opacity-70',
                      )}
                      onClick={() => {
                        if (isOpen) {
                          setOpenGroup(null);
                        } else {
                          setOpenGroup(key);
                          focusAnomaly(key, cursor);
                        }
                      }}
                    >
                      <span className="flex items-center gap-1 text-muted-foreground">
                        {count > 0 && (
                          <ChevronDown
                            className={cn('h-3 w-3 transition-transform', !isOpen && '-rotate-90')}
                          />
                        )}
                        {label}
                      </span>
                      <span
                        className={cn(
                          count > 0 ? 'font-semibold text-accent-amber' : 'text-muted-foreground',
                        )}
                      >
                        {count}
                      </span>
                    </Button>

                    {isOpen && (() => {
                      const pageSize = 50;
                      const windowStart = count > pageSize ? Math.max(0, Math.min(cursor - 20, count - pageSize)) : 0;
                      const windowEnd = Math.min(count, windowStart + pageSize);
                      const visibleItems = items.slice(windowStart, windowEnd);
                      return (
                      <div className="mt-1 space-y-1 rounded-md border border-border/70 bg-background p-1.5">
                        <div className="flex items-center justify-between px-1 text-[11px] text-muted-foreground">
                          <span>
                            {cursor + 1} / {count}
                            {count > pageSize ? ` · 第 ${windowStart + 1}–${windowEnd} 项` : ''}
                          </span>
                          <div className="flex items-center gap-0.5">
                            <IconActionButton
                              size="icon-xs"
                              className="h-5 w-5"
                              label={`上一个${label}`}
                              disabled={cursor <= 0}
                              onClick={() => focusAnomaly(key, cursor - 1)}
                            >
                              <ChevronLeft className="h-3 w-3" />
                            </IconActionButton>
                            <IconActionButton
                              size="icon-xs"
                              className="h-5 w-5"
                              label={`下一个${label}`}
                              disabled={cursor >= count - 1}
                              onClick={() => focusAnomaly(key, cursor + 1)}
                            >
                              <ChevronRight className="h-3 w-3" />
                            </IconActionButton>
                          </div>
                        </div>
                        <div className="max-h-36 space-y-0.5 overflow-auto">
                          {visibleItems.map((item, offset) => {
                            const idx = windowStart + offset;
                            return (
                              <Button
                                key={item.id}
                                variant={idx === cursor ? 'secondary' : 'ghost'}
                                size="xs"
                                className="h-6 w-full justify-between px-2 font-normal"
                                onClick={() => focusAnomaly(key, idx)}
                              >
                                <span className="truncate font-mono text-[11px]">{item.label}</span>
                                <span className="flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
                                  {item.meta}
                                  <Crosshair className="h-3 w-3 opacity-60" />
                                </span>
                              </Button>
                            );
                          })}
                        </div>
                      </div>
                      );
                    })()}
                  </div>
                );
              })}
            </div>
          </section>

          <section className="flex items-center justify-between gap-3 py-3.5">
            <span className="text-xs font-medium text-foreground">相邻边辨色</span>
            <Toggle
              variant="outline"
              size="sm"
              pressed={splitValidation}
              aria-label={`${splitValidation ? '关闭' : '开启'}相邻边辨色`}
              aria-pressed={splitValidation}
              onClick={onSplitValidation}
            >
              {splitValidation ? '已开启' : '开启'}
            </Toggle>
          </section>

          <section className="space-y-2.5 py-4">
            <div className="flex items-center justify-between gap-2">
              <h3 className="m-0 text-xs font-semibold text-foreground">转角测量</h3>
              <div className="flex items-center gap-1">
                {angleEdges.length > 0 && (
                  <IconActionButton
                    variant="ghost"
                    size="icon-xs"
                    className="h-6 w-6 text-muted-foreground hover:text-foreground"
                    label="清空测角边"
                    tooltip="清空已选边"
                    onClick={onClearAngleEdges}
                  >
                    <RotateCcw className="h-3 w-3" />
                  </IconActionButton>
                )}
                <Toggle
                  variant="outline"
                  size="sm"
                  pressed={angleMeasureActive}
                  aria-label={`${angleMeasureActive ? '关闭' : '开启'}转角测量`}
                  aria-pressed={angleMeasureActive}
                  onClick={onToggleAngleMeasure}
                >
                  {angleMeasureActive ? '测角中' : '开启'}
                </Toggle>
              </div>
            </div>
            {(angleMeasureActive || angleEdges.length > 0) && (
              <div className="space-y-2 rounded-md border border-border/70 bg-background p-2.5 text-xs">
                {angleEdges.length === 0 && (
                  <p className="m-0 text-[11px] text-muted-foreground">请在地图上依次点击两条相连的边</p>
                )}
                {angleEdges.length >= 1 && (
                  <div className="space-y-1 font-mono text-[11px] text-muted-foreground">
                    <div className="flex items-center justify-between gap-2">
                      <span>边 1</span>
                      <span className="truncate text-foreground">{formatEdgeId(angleEdges[0].properties.id)}</span>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span>边 2</span>
                      <span className="truncate text-foreground">
                        {angleEdges[1] ? formatEdgeId(angleEdges[1].properties.id) : '待选择…'}
                      </span>
                    </div>
                  </div>
                )}
                {angleResults !== null && angleResults.length === 0 && (
                  <p className="m-0 text-[11px] text-destructive">两条边没有共享节点，请重新选择相连的边</p>
                )}
                {angleResults !== null && angleResults.length > 0 && (
                  <div className="space-y-1.5 border-t border-border/60 pt-2 tabular-nums">
                    {angleResults.map(item => (
                      <div key={item.sharedNodeId} className="space-y-0.5">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-[11px] text-muted-foreground">转角（偏转）</span>
                          <strong className="text-sm font-semibold text-primary">{item.turnDegrees.toFixed(1)}°</strong>
                        </div>
                        <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                          <span>夹角 {item.interiorDegrees.toFixed(1)}°</span>
                          <span className="font-mono">节点 {item.sharedNodeId}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="space-y-2.5 py-4">
            <div className="flex items-center justify-between gap-2">
              <h3 className="m-0 text-xs font-semibold text-foreground">逐点检查</h3>
              {reviewing && (
                <span className="truncate text-[11px] text-primary tabular-nums">
                  {reviewIndex + 1} / {nodes.length} · {nodes[reviewIndex]?.properties.id}
                </span>
              )}
            </div>
            <div className="flex items-center justify-between gap-2">
              <Button
                variant={reviewing ? 'outline' : 'default'}
                size="sm"
                disabled={!nodes.length}
                onClick={() => {
                  if (reviewing) {
                    setReviewIndex(-1);
                    wb.dispatch({ type: 'selected', value: null });
                  } else {
                    showReview(0);
                  }
                }}
              >
                {reviewing ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                {reviewing ? '结束' : '开始'}
              </Button>
              <div className="flex items-center gap-1">
                <IconActionButton
                  variant="outline"
                  label="上一个"
                  disabled={reviewIndex <= 0}
                  onClick={() => showReview(reviewIndex - 1)}
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </IconActionButton>
                <IconActionButton
                  variant="outline"
                  label="下一个"
                  disabled={!reviewing || reviewIndex >= nodes.length - 1}
                  onClick={() => showReview(reviewIndex + 1)}
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </IconActionButton>
              </div>
            </div>
          </section>
        </div>
      </ScrollArea>
    </aside>
  );
}
