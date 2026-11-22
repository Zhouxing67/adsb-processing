import { useEffect, useMemo, useState } from 'react';
import { X } from 'lucide-react';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';

interface TopologyPanelProps {
  splitValidation: boolean;
  onSplitValidation(): void;
}

export function TopologyPanel({ splitValidation, onSplitValidation }: TopologyPanelProps) {
  const wb = useWorkbench();
  const topology = wb.state?.topology;
  const [reviewIndex, setReviewIndex] = useState(-1);

  const nodes = useMemo(
    () => [...(wb.state?.nodes.features ?? [])].sort((a, b) => a.properties.id.localeCompare(b.properties.id)),
    [wb.state?.nodes.features],
  );

  useEffect(() => {
    setReviewIndex(current => (current >= nodes.length ? (nodes.length ? nodes.length - 1 : -1) : current));
  }, [nodes.length]);

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

  const summary: Array<[string, number]> = [
    ['连通分量', topology.component_count],
    ['最大分量', topology.largest_component],
  ];
  const anomalies: Array<[string, number]> = [
    ['孤立节点', topology.isolated_count],
    ['悬挂节点', topology.dangling_count],
    ['平行边组', topology.parallel_pair_count],
  ];

  return (
    <aside className="relative z-[900] col-start-1 row-start-2 flex h-full min-h-0 min-w-0 flex-col border-r border-border bg-muted">
      <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3.5">
        <div>
          <small className="block text-[11px] text-muted-foreground">网络健康检查</small>
          <h2 className="m-0 text-[15px] font-semibold text-foreground">拓扑概览</h2>
        </div>
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
          <div className="flex gap-8 py-4 tabular-nums">
            {summary.map(([label, value]) => (
              <div key={label} className="grid gap-0.5">
                <strong className="text-xl font-medium text-foreground">{value}</strong>
                <span className="text-[11px] text-muted-foreground">{label}</span>
              </div>
            ))}
          </div>

          <section className="space-y-2.5 py-4">
            <h3 className="m-0 text-xs font-semibold text-foreground">异常</h3>
            <dl className="m-0 space-y-1.5 text-xs tabular-nums">
              {anomalies.map(([label, value]) => (
                <div key={label} className="flex items-center justify-between">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className={cn('m-0 font-medium', value > 0 ? 'text-amber-700' : 'text-foreground')}>{value}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="space-y-2.5 py-4">
            <h3 className="m-0 text-xs font-semibold text-foreground">辅助检查</h3>
            <div className="flex items-center justify-between gap-3">
              <div className="grid gap-0.5">
                <strong className="text-xs font-medium text-foreground">相邻边辨色</strong>
                <small className="text-[11px] text-muted-foreground">提高共享节点附近边的辨识度</small>
              </div>
              <Button
                variant={splitValidation ? 'default' : 'outline'}
                size="sm"
                aria-label={`${splitValidation ? '关闭' : '开启'}相邻边辨色`}
                aria-pressed={splitValidation}
                onClick={onSplitValidation}
              >
                {splitValidation ? '关闭' : '开启'}
              </Button>
            </div>
          </section>

          {topology.component_count > 1 && (
            <section className="space-y-2.5 py-4">
              <h3 className="m-0 text-xs font-semibold text-foreground">连通分量</h3>
              <div className="flex flex-wrap gap-1.5">
                {topology.components.slice(0, 20).map(component => (
                  <Button
                    variant="outline"
                    size="xs"
                    key={component.index}
                    onClick={() => {
                      const node = wb.state?.nodes.features.find(item => component.node_ids.includes(item.properties.id));
                      if (node) wb.dispatch({ type: 'selected', value: node, focus: true });
                    }}
                  >
                    分量 {component.index} · {component.size} 节点
                  </Button>
                ))}
              </div>
            </section>
          )}

          <section className="space-y-2.5 py-4">
            <h3 className="m-0 text-xs font-semibold text-foreground">逐点检查</h3>
            <p className="m-0 text-[11px] text-muted-foreground tabular-nums">
              {reviewIndex >= 0
                ? `遍历位置 ${reviewIndex + 1} / ${nodes.length} · 节点 ${nodes[reviewIndex]?.properties.id}`
                : '尚未开始'}
            </p>
            <div className="flex flex-wrap gap-1.5">
              <Button variant="outline" size="sm" disabled={!nodes.length} onClick={() => showReview(0)}>
                开始
              </Button>
              <Button variant="outline" size="sm" disabled={reviewIndex <= 0} onClick={() => showReview(reviewIndex - 1)}>
                上一个
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={reviewIndex < 0 || reviewIndex >= nodes.length - 1}
                onClick={() => showReview(reviewIndex + 1)}
              >
                下一个
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={reviewIndex < 0}
                onClick={() => {
                  setReviewIndex(-1);
                  wb.dispatch({ type: 'selected', value: null });
                }}
              >
                结束
              </Button>
            </div>
          </section>
        </div>
      </ScrollArea>
    </aside>
  );
}
