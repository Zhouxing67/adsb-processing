import { useEffect, useMemo, useState } from 'react';
import { X } from 'lucide-react';
import type { GraphPostInput, GraphPostPath } from '@/api/client';
import type { NodeId } from '@/api/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { ScrollArea } from '@/components/ui/scroll-area';
import { PAIR_PREVIEW_COLORS } from '@/domain/palette';
import type { MapPreviewLine } from '@/features/map/MapView';
import type { GraphDialogState } from './types';

interface Props {
  dialog: GraphDialogState;
  onClose(): void;
  onPreview(overlays: MapPreviewLine[]): void;
  onConfirm<P extends GraphPostPath>(path: P, body: GraphPostInput<P>): Promise<void>;
  onMergeCandidate(nodeIds: NodeId[], revision: number): Promise<void>;
}

function recommendedPairIds(dialog: GraphDialogState): Set<string> {
  if (dialog.kind !== 'delete-node') return new Set();
  const used = new Set<string>();
  const selected = new Set<string>();
  dialog.preview.pair_candidates
    .filter(item => item.recommended)
    .forEach(item => {
      if (!used.has(item.left) && !used.has(item.right)) {
        selected.add(item.pair_id);
        used.add(item.left);
        used.add(item.right);
      }
    });
  return selected;
}

export function GraphDialog({ dialog, onClose, onPreview, onConfirm, onMergeCandidate }: Props) {
  const [choice, setChoice] = useState(0);
  const [pairsState, setPairsState] = useState<{ dialog: GraphDialogState; selected: Set<string> }>(() => ({
    dialog,
    selected: recommendedPairIds(dialog),
  }));
  const [hoveredPairId, setHoveredPairId] = useState<string | null>(null);
  const [discard, setDiscard] = useState(false);

  const pairs = useMemo(
    () => (pairsState.dialog === dialog ? pairsState.selected : recommendedPairIds(dialog)),
    [pairsState, dialog],
  );

  const setPairs = (updater: (value: Set<string>) => Set<string>) => {
    setPairsState(current => {
      const base = current.dialog === dialog ? current.selected : recommendedPairIds(dialog);
      return { dialog, selected: updater(base) };
    });
  };

  const pairColorMap = useMemo(() => {
    const map = new Map<string, string>();
    if (dialog.kind !== 'delete-node') return map;
    dialog.preview.pair_candidates.forEach((pair, index) => {
      map.set(pair.pair_id, PAIR_PREVIEW_COLORS[index % PAIR_PREVIEW_COLORS.length]);
    });
    return map;
  }, [dialog]);

  useEffect(() => {
    const preferred =
      dialog.kind === 'merge'
        ? dialog.preview.nodes.findIndex(node => node.node_id === dialog.preview.canonical_node_id)
        : dialog.kind === 'split' && dialog.preview.recommended_node
          ? dialog.preview.candidates.findIndex(candidate => candidate.id === dialog.preview.recommended_node)
          : 0;
    setChoice(Math.max(0, preferred));
    setHoveredPairId(null);
    setDiscard(false);
    setPairsState({ dialog, selected: recommendedPairIds(dialog) });
    if (dialog.kind === 'restore') {
      const first = dialog.preview.candidates[0]?.geometry;
      onPreview(first ? [{ geometry: first }] : []);
    } else if (dialog.kind === 'snap') {
      onPreview([{ geometry: dialog.preview.connector_geometry }]);
    } else if (dialog.kind !== 'delete-node') {
      onPreview([]);
    }
    return () => onPreview([]);
  }, [dialog, onPreview]);

  useEffect(() => {
    if (dialog.kind !== 'delete-node') return;
    const overlays: MapPreviewLine[] = [];
    for (const pair of dialog.preview.pair_candidates) {
      const checked = pairs.has(pair.pair_id);
      const hovered = hoveredPairId === pair.pair_id;
      if (!checked && !hovered) continue;
      overlays.push({
        geometry: pair.geometry,
        color: pairColorMap.get(pair.pair_id),
        emphasis: hovered,
        dashed: !checked && hovered,
      });
    }
    onPreview(overlays);
  }, [dialog, pairs, hoveredPairId, pairColorMap, onPreview]);

  const unpaired = useMemo(() => {
    if (dialog.kind !== 'delete-node') return [];
    const used = new Set<string>();
    dialog.preview.pair_candidates
      .filter(item => pairs.has(item.pair_id))
      .forEach(item => {
        used.add(item.left);
        used.add(item.right);
      });
    return dialog.preview.half_edges.filter(item => !used.has(item.half_id)).map(item => item.half_id);
  }, [dialog, pairs]);

  const confirm = async () => {
    if (dialog.kind === 'restore') {
      const candidate = dialog.preview.candidates[choice];
      await onConfirm('/api/restore-confirm', {
        start: dialog.start,
        end: dialog.end,
        candidate_id: candidate.candidate_id,
        expected_revision: dialog.preview.revision,
      });
    } else if (dialog.kind === 'merge') {
      await onConfirm('/api/merge-nodes-confirm', {
        node_ids: dialog.preview.node_ids,
        canonical_node_id: dialog.preview.nodes[choice].node_id,
        expected_revision: dialog.preview.revision,
      });
    } else if (dialog.kind === 'delete-edge') {
      await onConfirm('/api/delete-edge-confirm', {
        edge: dialog.edge,
        expected_revision: dialog.preview.revision,
      });
    } else if (dialog.kind === 'delete-node') {
      await onConfirm('/api/delete-node-confirm', {
        node: dialog.node,
        pair_ids: [...pairs],
        discard_unpaired: discard,
        expected_revision: dialog.preview.revision,
      });
    } else if (dialog.kind === 'split') {
      await onConfirm('/api/split-source-confirm', {
        edge: dialog.edge,
        longitude: dialog.longitude,
        latitude: dialog.latitude,
        osm_node_id: dialog.preview.candidates[choice]?.id ?? null,
        expected_revision: dialog.preview.revision,
      });
    } else if (dialog.kind === 'snap') {
      await onConfirm('/api/manual-snap-confirm', {
        node: dialog.node,
        edge: dialog.edge,
        expected_revision: dialog.preview.revision,
      });
    }
  };

  if (dialog.kind === 'merge-candidates') {
    return (
      <aside className="details relative flex h-full w-full flex-col bg-background">
        <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-5">
          <div>
            <h2 className="m-0 text-[15px] leading-tight font-semibold text-foreground">疑似重复图节点</h2>
            <p className="mt-0.5 text-[11px] leading-tight text-muted-foreground">候选距离 ≤ 0.5 m</p>
          </div>
          <Button variant="ghost" size="icon-xs" aria-label="关闭" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-2.5 p-4">
            {dialog.preview.candidates.map((candidate, index) => (
              <Card key={index} className="space-y-2 bg-muted/40 p-3 text-xs shadow-none">
                <strong className="block font-medium text-foreground tabular-nums">
                  候选 {index + 1} · 最大距离 {candidate.max_distance_m.toFixed(3)} m
                </strong>
                <p className="m-0 break-words text-muted-foreground">
                  {candidate.nodes.map(node => node.node_id).join('、')}
                </p>
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => void onMergeCandidate(candidate.node_ids, dialog.preview.revision)}
                >
                  检查并合并
                </Button>
              </Card>
            ))}
          </div>
        </ScrollArea>
      </aside>
    );
  }

  const dialogTitles: Record<Exclude<GraphDialogState['kind'], 'merge-candidates'>, string> = {
    restore: '从 OSM 恢复连接',
    merge: '合并节点预览',
    'delete-edge': '删除派生边',
    'delete-node': '半边配对',
    split: '补充图分割点',
    snap: '人工吸附预览',
  };

  return (
    <aside className="details relative flex h-full w-full flex-col bg-background">
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-5">
        <h2 className="m-0 text-[15px] font-semibold text-foreground">{dialogTitles[dialog.kind]}</h2>
        <Button variant="ghost" size="icon-xs" aria-label="关闭" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-3 p-5 text-[13px]">
          {dialog.kind === 'restore' && (
            <>
              <p className="m-0 text-xs text-muted-foreground">{dialog.preview.current_endpoints.join(' — ')}</p>
              <RadioGroup
                value={String(choice)}
                onValueChange={value => {
                  const index = Number(value);
                  setChoice(index);
                  const geometry = dialog.preview.candidates[index]?.geometry;
                  onPreview(geometry ? [{ geometry }] : []);
                }}
                className="gap-2"
              >
                {dialog.preview.candidates.map((candidate, index) => (
                  <Label
                    key={candidate.candidate_id}
                    className="flex cursor-pointer items-start gap-2 rounded-lg border border-border bg-muted/40 p-2.5 font-normal hover:bg-accent/50"
                    onMouseEnter={() => onPreview([{ geometry: candidate.geometry }])}
                  >
                    <RadioGroupItem value={String(index)} className="mt-0.5" />
                    <span className="min-w-0 break-words leading-normal text-foreground tabular-nums">
                      {candidate.source_ids.join(' + ')}
                      <br />
                      <span className="text-muted-foreground">
                        OSM way {candidate.osm_way_ids.join(' + ')} · {candidate.length_m.toFixed(2)} m
                      </span>
                    </span>
                  </Label>
                ))}
              </RadioGroup>
            </>
          )}

          {dialog.kind === 'merge' && (
            <>
              <dl className="m-0 divide-y divide-border/70 text-xs tabular-nums">
                <div className="flex justify-between py-1.5">
                  <dt className="text-muted-foreground">最大距离</dt>
                  <dd className="m-0 font-medium">{dialog.preview.max_distance_m.toFixed(3)} m</dd>
                </div>
                <div className="flex justify-between py-1.5">
                  <dt className="text-muted-foreground">受影响边</dt>
                  <dd className="m-0 font-medium">{dialog.preview.affected_edges.length}</dd>
                </div>
              </dl>
              <h3 className="m-0 pt-2 text-xs font-semibold text-foreground">选择规范节点</h3>
              <RadioGroup value={String(choice)} onValueChange={value => setChoice(Number(value))} className="gap-2">
                {dialog.preview.nodes.map((node, index) => (
                  <Label
                    key={node.node_id}
                    className="flex cursor-pointer items-start gap-2 rounded-lg border border-border bg-muted/40 p-2.5 font-normal hover:bg-accent/50"
                  >
                    <RadioGroupItem value={String(index)} className="mt-0.5" />
                    <span className="min-w-0 break-words leading-normal">
                      {node.node_id} · {node.manual ? '人工图节点' : 'OSM 图节点'} · 度 {node.degree}
                    </span>
                  </Label>
                ))}
              </RadioGroup>
              {dialog.preview.warnings.map(item => (
                <p className="m-0 text-xs text-destructive" key={item}>
                  {item}
                </p>
              ))}
            </>
          )}

          {dialog.kind === 'delete-edge' && (
            <>
              <p className="m-0 break-words text-xs font-medium text-foreground">{dialog.preview.edge}</p>
              <div className="space-y-1 text-xs text-muted-foreground tabular-nums">
                {dialog.preview.source_segments.map(segment => (
                  <p className="m-0" key={`${segment.source_id}-${segment.source_start_m}`}>
                    {segment.source_id} [{segment.source_start_m.toFixed(2)}, {segment.source_end_m.toFixed(2)}]
                    {segment.reversed ? ' 反向' : ''}
                  </p>
                ))}
              </div>
              <p className="m-0 text-[11px] text-muted-foreground">SourceEdge 不会被删除。</p>
            </>
          )}

          {dialog.kind === 'delete-node' && (
            <>
              <div className="flex items-center justify-between text-xs text-muted-foreground tabular-nums">
                <span>
                  节点 <strong className="font-medium text-foreground">{dialog.preview.node}</strong>
                </span>
                <span>{dialog.preview.half_edges.length} 条关联半边</span>
              </div>
              <div className="space-y-2">
                {dialog.preview.pair_candidates.map(pair => {
                  const checked = pairs.has(pair.pair_id);
                  const pairColor = pairColorMap.get(pair.pair_id);
                  return (
                    <Label
                      key={pair.pair_id}
                      className={`flex cursor-pointer items-start gap-2.5 rounded-lg border p-2.5 font-normal transition-colors ${
                        checked
                          ? 'border-primary/40 bg-background shadow-2xs'
                          : 'border-border bg-muted/35 hover:bg-accent/50'
                      }`}
                      onMouseEnter={() => setHoveredPairId(pair.pair_id)}
                      onMouseLeave={() => setHoveredPairId(current => (current === pair.pair_id ? null : current))}
                    >
                      <Checkbox
                        className="mt-0.5"
                        checked={checked}
                        onCheckedChange={next =>
                          setPairs(value => {
                            const updated = new Set(value);
                            if (next === true) {
                              dialog.preview.pair_candidates
                                .filter(
                                  item =>
                                    item.pair_id !== pair.pair_id &&
                                    (item.left === pair.left ||
                                      item.left === pair.right ||
                                      item.right === pair.left ||
                                      item.right === pair.right),
                                )
                                .forEach(item => updated.delete(item.pair_id));
                              updated.add(pair.pair_id);
                            } else {
                              updated.delete(pair.pair_id);
                            }
                            return updated;
                          })
                        }
                      />
                      <div className="min-w-0 flex-1 space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="flex min-w-0 items-center gap-1.5">
                            <span
                              className="inline-block h-2.5 w-2.5 shrink-0 rounded-full border border-border/60"
                              style={{ backgroundColor: pairColor, opacity: checked ? 1 : 0.45 }}
                              aria-hidden="true"
                            />
                            <strong className="truncate text-xs font-semibold text-foreground tabular-nums">
                              {pair.endpoints.join(' ↔ ')}
                            </strong>
                          </span>
                          <span className="shrink-0 text-[11px] font-medium text-foreground tabular-nums">
                            {pair.angle_degrees}°
                          </span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground" title={pair.source_ids.join(' → ')}>
                            {pair.source_ids.join(' → ')}
                          </span>
                          <div className="flex shrink-0 items-center gap-1">
                            {pair.recommended && (
                              <Badge variant="default" className="px-1.5 py-0 text-[11px] font-normal">
                                推荐
                              </Badge>
                            )}
                            <Badge
                              variant={pair.same_source ? 'secondary' : 'outline'}
                              className="px-1.5 py-0 text-[11px] font-normal"
                            >
                              {pair.same_source ? '同源' : '跨来源'}
                            </Badge>
                          </div>
                        </div>
                      </div>
                    </Label>
                  );
                })}
              </div>
              <div className="flex items-center justify-between pt-1 text-[11px] text-muted-foreground tabular-nums">
                <span>已选 {pairs.size} 组配对</span>
                <span>未配对：{unpaired.length ? unpaired.join(', ') : '无'}</span>
              </div>
              {unpaired.length > 0 && (
                <Label className="flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-muted/40 p-2.5 font-normal">
                  <Checkbox checked={discard} onCheckedChange={checked => setDiscard(checked === true)} />
                  <span>明确删除未配对半边</span>
                </Label>
              )}
            </>
          )}

          {dialog.kind === 'split' && (
            <>
              <p className="m-0 text-xs text-muted-foreground">命中来源：{dialog.preview.source_id}</p>
              {dialog.preview.candidates.length ? (
                <RadioGroup value={String(choice)} onValueChange={value => setChoice(Number(value))} className="gap-2">
                  {dialog.preview.candidates.map((candidate, index) => (
                    <Label
                      key={candidate.id}
                      className="flex cursor-pointer items-start gap-2 rounded-lg border border-border bg-muted/40 p-2.5 font-normal hover:bg-accent/50"
                    >
                      <RadioGroupItem value={String(index)} className="mt-0.5" />
                      <span className="leading-normal tabular-nums">
                        OSM Node {candidate.id} · 距离 {candidate.distance_m.toFixed(2)} m
                      </span>
                    </Label>
                  ))}
                </RadioGroup>
              ) : (
                <p className="m-0 text-xs text-muted-foreground">没有合适 OSM Node，将创建人工节点。</p>
              )}
            </>
          )}

          {dialog.kind === 'snap' && (
            <>
              <dl className="m-0 divide-y divide-border/70 text-xs tabular-nums">
                <div className="flex justify-between py-1.5">
                  <dt className="text-muted-foreground">节点</dt>
                  <dd className="m-0 font-medium">{dialog.preview.node}</dd>
                </div>
                <div className="flex justify-between py-1.5">
                  <dt className="text-muted-foreground">目标边</dt>
                  <dd className="m-0 font-medium">{dialog.preview.edge}</dd>
                </div>
                <div className="flex justify-between py-1.5">
                  <dt className="text-muted-foreground">移动距离</dt>
                  <dd className="m-0 font-medium">{dialog.preview.distance_m.toFixed(3)} m</dd>
                </div>
                <div className="flex justify-between py-1.5">
                  <dt className="text-muted-foreground">目标来源</dt>
                  <dd className="m-0 font-medium">{dialog.preview.target_source_id}</dd>
                </div>
              </dl>
              <p className="m-0 text-[11px] text-muted-foreground">
                确认后将移动图节点、重建关联边，并切分目标来源区间。
              </p>
            </>
          )}
        </div>
      </ScrollArea>

      <div className="flex shrink-0 justify-end gap-2 border-t border-border bg-background px-4 py-3">
        <Button variant="outline" size="sm" onClick={onClose}>
          取消
        </Button>
        <Button
          variant="default"
          size="sm"
          disabled={dialog.kind === 'delete-node' && unpaired.length > 0 && !discard}
          onClick={() => void confirm()}
        >
          确认
        </Button>
      </div>
    </aside>
  );
}
