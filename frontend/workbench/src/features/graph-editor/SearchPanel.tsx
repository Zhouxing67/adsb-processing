import { useState } from 'react';
import { X } from 'lucide-react';
import type { SelectedFeature } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

import { formatEdgeId } from '@/domain/features';

interface SearchPanelProps {
  leftOffset?: boolean;
}

export function SearchPanel({ leftOffset = true }: SearchPanelProps) {
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
        wb.state!.edges.features.find(item => formatEdgeId(item.properties.id).toLocaleLowerCase().includes(needle)),
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
    <Card
      className="fixed top-[70px] z-[1050] max-h-[calc(100vh-120px)] w-80 space-y-3.5 overflow-auto bg-background/95 p-4 shadow-lg backdrop-blur-xs"
      style={{
        left: leftOffset
          ? 'calc(var(--left-sidebar-width, var(--sidebar-width)) + 14px)'
          : '14px',
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="m-0 text-[15px] font-semibold text-foreground">搜索图要素</h2>
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label="关闭搜索面板"
          onClick={() => wb.dispatch({ type: 'panel', panel: 'searchOpen', value: false })}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <Label className="grid gap-1.5 font-normal text-muted-foreground">
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
      </Label>

      <Label className="grid gap-1.5 font-normal text-muted-foreground">
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
      </Label>

      <Label className="grid gap-1.5 font-normal text-muted-foreground">
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
      </Label>
    </Card>
  );
}
