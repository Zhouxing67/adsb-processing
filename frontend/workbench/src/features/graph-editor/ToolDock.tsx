import { Crosshair, GitMerge, Layers, Magnet, PenLine, Route, Scissors, Trash2 } from 'lucide-react';
import type { ComponentType } from 'react';
import { useWorkbench } from '@/app/WorkbenchContext';
import type { EditorTool } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';

const tools: Array<{ key: EditorTool; label: string; icon: ComponentType<{ className?: string }> }> = [
  { key: 'inspect', label: '查看', icon: Crosshair },
  { key: 'split', label: '补充分割点', icon: Scissors },
  { key: 'draw', label: '直接绘制连接', icon: PenLine },
  { key: 'restore', label: '恢复来源连接', icon: Route },
  { key: 'merge', label: '合并重合节点', icon: GitMerge },
  { key: 'snap', label: '人工吸附到边', icon: Magnet },
  { key: 'cluster', label: '机位聚类', icon: Layers },
  { key: 'delete', label: '删除 / 简化', icon: Trash2 },
];

const toolMessages: Record<EditorTool, string> = {
  inspect: '查看模式 · 点击节点或派生边查看详情',
  split: '补充分割点 · 选择边后点击边上或附近切分位置',
  draw: '直接绘制连接 · 选择起点、点击地图添加形状点、再选择终点',
  restore: '恢复来源连接 · 依次选择两个节点',
  merge: '合并节点 · 依次选择两个节点',
  snap: '人工吸附 · 先选择节点，再选择目标边',
  cluster: '机位聚类 · 点击多选机位边，或按住 Shift + 拖拽（/开启框选）批量选择',
  delete: '删除 / 简化 · 点击节点或边',
};

export function ToolDock() {
  const wb = useWorkbench();
  if (!wb.state?.capabilities.can_edit_graph) return null;

  return (
    <Card className="absolute left-3.5 top-[62px] z-[800] w-[156px] bg-background/95 p-1.5 shadow-sm backdrop-blur-xs">
      <nav className="flex flex-col gap-0.5" aria-label="编辑工具">
        {tools.map(tool => {
          const Icon = tool.icon;
          const active = wb.tool === tool.key;
          const danger = tool.key === 'delete';
          return (
            <Button
              key={tool.key}
              variant={active && !danger ? 'default' : 'ghost'}
              size="sm"
              className={cn(
                'h-8 w-full justify-start gap-2 px-2.5 text-left text-xs font-normal',
                active && !danger && 'font-medium',
                danger &&
                  (active
                    ? 'bg-red-50 font-medium text-destructive ring-1 ring-inset ring-destructive/30 hover:bg-red-50 hover:text-destructive'
                    : 'text-destructive hover:bg-red-50/70 hover:text-destructive'),
              )}
              onClick={() => {
                wb.dispatch({ type: 'tool', value: tool.key });
                wb.dispatch({ type: 'status', value: toolMessages[tool.key] });
              }}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{tool.label}</span>
            </Button>
          );
        })}
      </nav>
    </Card>
  );
}
