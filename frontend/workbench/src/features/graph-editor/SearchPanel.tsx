import { useState } from 'react';
import { X } from 'lucide-react';
import type { SelectedFeature } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function edgeLabel(id: { u: string; v: string; key: number }) {
  return `${id.u}—${id.v} · ${id.key}`;
}

export function SearchPanel() {
  const wb = useWorkbench();
  const [query, setQuery] = useState('');
  const [stand, setStand] = useState('');
  const [edgeU, setEdgeU] = useState('');
  const [edgeV, setEdgeV] = useState('');

  if (!wb.searchOpen || !wb.state) return null;

  const select = (feature: SelectedFeature | undefined, label: string) => {
    if (feature) wb.dispatch({ type: 'selected', value: feature, focus: true });
    else wb.dispatch({ type: 'status', value: `未找到 ${label}` });
  };

  const search = () => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) {
      wb.dispatch({ type: 'status', value: '请输入节点 ID 或边 ID' });
      return;
    }
    select(
      wb.state!.nodes.features.find(item => item.properties.id.toLocaleLowerCase().includes(needle)) ??
        wb.state!.edges.features.find(item => edgeLabel(item.properties.id).toLocaleLowerCase().includes(needle)),
      query.trim(),
    );
  };

  const searchStand = () => {
    const needle = stand.trim().toLocaleLowerCase();
    if (!needle) {
      wb.dispatch({ type: 'status', value: '请输入机位编号' });
      return;
    }
    select(
      wb.state!.edges.features.find(item => String(item.properties.ref ?? '').toLocaleLowerCase() === needle),
      `机位 ${stand.trim()}`,
    );
  };

  const searchEdge = () => {
    const u = edgeU.trim();
    const v = edgeV.trim();
    if (!u || !v) {
      wb.dispatch({ type: 'status', value: '请输入边的两个端点 ID' });
      return;
    }
    const pair = [u, v].sort().join('|');
    select(
      wb.state!.edges.features.find(item => [item.properties.u, item.properties.v].map(String).sort().join('|') === pair),
      `边 ${u}—${v}`,
    );
  };

  return (
    <section
      className="fixed top-[70px] z-[1050] max-h-[calc(100vh-120px)] w-80 space-y-3.5 overflow-auto rounded-lg border border-border bg-background/95 p-4 shadow-lg backdrop-blur-xs"
      style={{ left: 'calc(var(--left-sidebar-width, var(--sidebar-width)) + 14px)' }}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <small className="block text-[11px] text-muted-foreground">快速定位</small>
          <h2 className="m-0 text-[15px] font-semibold text-foreground">搜索图要素</h2>
        </div>
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label="关闭搜索面板"
          onClick={() => wb.dispatch({ type: 'panel', panel: 'searchOpen', value: false })}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <label className="grid gap-1.5 text-xs text-muted-foreground">
        <span>节点或边 ID</span>
        <div className="flex items-center gap-1.5">
          <Input
            value={query}
            onChange={event => setQuery(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') search();
            }}
            placeholder="节点 ID 或完整边 ID"
          />
          <Button variant="outline" size="default" onClick={search}>
            选中
          </Button>
        </div>
      </label>

      <label className="grid gap-1.5 text-xs text-muted-foreground">
        <span>机位编号</span>
        <div className="flex items-center gap-1.5">
          <Input
            value={stand}
            onChange={event => setStand(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') searchStand();
            }}
            placeholder="例如 A01"
          />
          <Button variant="outline" size="default" onClick={searchStand}>
            定位机位
          </Button>
        </div>
      </label>

      <label className="grid gap-1.5 text-xs text-muted-foreground">
        <span>边的两个端点</span>
        <div className="flex items-center gap-1.5">
          <Input
            value={edgeU}
            onChange={event => setEdgeU(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') searchEdge();
            }}
            placeholder="端点 A"
          />
          <span className="text-muted-foreground">—</span>
          <Input
            value={edgeV}
            onChange={event => setEdgeV(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') searchEdge();
            }}
            placeholder="端点 B"
          />
          <Button variant="outline" size="default" onClick={searchEdge}>
            选中边
          </Button>
        </div>
      </label>
    </section>
  );
}
