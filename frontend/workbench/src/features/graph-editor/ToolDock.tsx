import { Crosshair, GitMerge, Magnet, PenLine, Route, Scissors, Trash2 } from 'lucide-react';
import type { ComponentType } from 'react';
import { useWorkbench } from '@/app/WorkbenchContext';
import type { EditorTool } from '@/app/WorkbenchContext';
import { cn } from '@/lib/utils';

const tools: Array<{ key: EditorTool; label: string; icon: ComponentType<{ className?: string }> }> = [
  { key: 'inspect', label: '查看', icon: Crosshair },
  { key: 'split', label: '补充分割点', icon: Scissors },
  { key: 'draw', label: '直接绘制连接', icon: PenLine },
  { key: 'restore', label: '恢复来源连接', icon: Route },
  { key: 'merge', label: '合并重合节点', icon: GitMerge },
  { key: 'snap', label: '人工吸附到边', icon: Magnet },
  { key: 'delete', label: '删除 / 简化', icon: Trash2 },
];

const toolMessages: Record<EditorTool, string> = {
  inspect: '查看模式 · 点击节点或派生边查看详情',
  split: '补充分割点 · 选择边后点击切分位置',
  draw: '直接绘制连接 · 选择起点、点击地图添加形状点、再选择终点',
  restore: '恢复来源连接 · 依次选择两个节点',
  merge: '合并节点 · 依次选择两个节点',
  snap: '人工吸附 · 先选择节点，再选择目标边',
  delete: '删除 / 简化 · 点击节点或边',
};

export function ToolDock() {
  const wb = useWorkbench();
  if (!wb.state?.capabilities.can_edit_graph) return null;

  return (
    <nav
      className="relative z-[900] col-start-1 row-start-2 flex h-full min-h-0 min-w-0 flex-col gap-1 overflow-auto border-r border-border bg-muted px-3 py-4"
      aria-label="编辑工具"
    >
      <div className="px-2 pb-1.5 text-[11px] font-semibold tracking-wider text-muted-foreground">编辑工具</div>
      {tools.map(tool => {
        const Icon = tool.icon;
        const active = wb.tool === tool.key;
        const danger = tool.key === 'delete';
        return (
          <button
            key={tool.key}
            type="button"
            className={cn(
              'flex w-full cursor-pointer items-center gap-2.5 rounded-md px-3 py-2 text-left text-[13px] transition-colors',
              active
                ? danger
                  ? 'bg-red-50 font-medium text-red-700 ring-1 ring-inset ring-red-200'
                  : 'bg-zinc-900 text-white font-medium'
                : danger
                  ? 'text-red-600 hover:bg-red-50/70'
                  : 'text-foreground hover:bg-accent',
            )}
            onClick={() => {
              wb.dispatch({ type: 'tool', value: tool.key });
              wb.dispatch({ type: 'status', value: toolMessages[tool.key] });
            }}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="truncate">{tool.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
