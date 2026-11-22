import { Network, Pencil, Search } from 'lucide-react';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';

interface MapToolbarProps {
  editing: boolean;
  onEditing(): void;
}

export function MapToolbar({ editing, onEditing }: MapToolbarProps) {
  const wb = useWorkbench();
  return (
    <div className="map-tools absolute left-3.5 top-3.5 z-[800] flex items-center gap-1 rounded-lg border border-border bg-background/95 p-1 shadow-sm backdrop-blur-xs">
      <Button
        variant={wb.searchOpen ? 'secondary' : 'ghost'}
        size="icon"
        aria-label="搜索"
        title="搜索图要素"
        onClick={() => wb.dispatch({ type: 'panel', panel: 'searchOpen', value: !wb.searchOpen })}
      >
        <Search className="h-4 w-4" />
      </Button>
      <Button
        variant={wb.topologyOpen ? 'secondary' : 'ghost'}
        size="icon"
        aria-label="拓扑检查"
        title="拓扑检查"
        onClick={() => wb.dispatch({ type: 'panel', panel: 'topologyOpen', value: !wb.topologyOpen })}
      >
        <Network className="h-4 w-4" />
      </Button>
      {wb.state?.capabilities.can_edit_graph && (
        <Button
          variant={editing ? 'default' : 'ghost'}
          size="sm"
          className="h-8 px-2.5"
          aria-pressed={editing}
          onClick={onEditing}
        >
          <Pencil className="h-3.5 w-3.5" />
          {editing ? '退出编辑' : '编辑图'}
        </Button>
      )}
    </div>
  );
}
