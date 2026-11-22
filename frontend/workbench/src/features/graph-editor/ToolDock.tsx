import { useWorkbench } from '../../app/WorkbenchContext';
import type { EditorTool } from '../../app/WorkbenchContext';

const tools: Array<{ key: EditorTool; label: string; symbol: string }> = [
  { key: 'inspect', label: '查看', symbol: '⌖' },
  { key: 'split', label: '补充分割点', symbol: '✂' },
  { key: 'draw', label: '直接绘制连接', symbol: '＋' },
  { key: 'restore', label: '恢复来源连接', symbol: '⌁' },
  { key: 'merge', label: '合并重合节点', symbol: '◎' },
  { key: 'snap', label: '人工吸附到边', symbol: '↦' },
  { key: 'delete', label: '删除 / 简化', symbol: '×' },
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
    <nav className="tool-dock panel react-tool-dock" aria-label="编辑工具">
      <div className="dock-title">编辑工具</div>
      {tools.map(tool => (
        <button
          key={tool.key}
          className={`tool ${wb.tool === tool.key ? 'active' : ''} ${tool.key === 'delete' ? 'danger' : ''}`}
          onClick={() => {
            wb.dispatch({ type: 'tool', value: tool.key });
            wb.dispatch({ type: 'status', value: toolMessages[tool.key] });
          }}
        >
          <span>{tool.symbol}</span>
          <em>{tool.label}</em>
        </button>
      ))}
    </nav>
  );
}
