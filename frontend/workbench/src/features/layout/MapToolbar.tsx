import { GitFork, Network, Pencil, Plane, Route, Search } from 'lucide-react';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { IconActionButton } from '@/components/ui/workbench-shell';

interface MapToolbarProps {
  editing: boolean;
  onEditing(): void;
  dualMap?: boolean;
  mapKind?: 'flight' | 'route';
  overlayOther?: boolean;
  onToggleOverlayOther?(): void;
  spreadRoutes?: boolean;
  onToggleSpreadRoutes?(): void;
}

export function MapToolbar({
  editing,
  onEditing,
  dualMap = false,
  mapKind,
  overlayOther = false,
  onToggleOverlayOther,
  spreadRoutes = true,
  onToggleSpreadRoutes,
}: MapToolbarProps) {
  const wb = useWorkbench();
  return (
    <Card className="map-tools absolute left-3.5 top-3.5 z-[800] flex items-center gap-1 bg-background/95 p-1 shadow-sm backdrop-blur-xs">
      <IconActionButton
        variant={wb.searchOpen ? 'secondary' : 'ghost'}
        size="icon"
        label="搜索"
        tooltip="搜索图要素"
        onClick={() => wb.dispatch({ type: 'panel', panel: 'searchOpen', value: !wb.searchOpen })}
      >
        <Search className="h-4 w-4" />
      </IconActionButton>
      <IconActionButton
        variant={wb.topologyOpen ? 'secondary' : 'ghost'}
        size="icon"
        label="拓扑检查"
        tooltip="拓扑检查"
        onClick={() => wb.dispatch({ type: 'panel', panel: 'topologyOpen', value: !wb.topologyOpen })}
      >
        <Network className="h-4 w-4" />
      </IconActionButton>
      {wb.state?.flight_mode && (
        <>
          <Separator orientation="vertical" className="mx-0.5 h-5" />
          {dualMap && mapKind && onToggleOverlayOther && (
            <IconActionButton
              variant={overlayOther ? 'secondary' : 'ghost'}
              size="icon"
              className={overlayOther ? 'text-primary' : 'text-muted-foreground hover:text-foreground'}
              aria-pressed={overlayOther}
              label={mapKind === 'flight' ? '叠加路径库图层' : '叠加航班图层'}
              tooltip={
                mapKind === 'flight'
                  ? overlayOther
                    ? '取消叠加路径库图层'
                    : '临时叠加路径库图层'
                  : overlayOther
                    ? '取消叠加航班图层'
                    : '临时叠加航班图层'
              }
              onClick={onToggleOverlayOther}
            >
              {mapKind === 'flight' ? <Route className="h-4 w-4" /> : <Plane className="h-4 w-4" />}
            </IconActionButton>
          )}
          {onToggleSpreadRoutes && (
            <IconActionButton
              variant={spreadRoutes ? 'secondary' : 'ghost'}
              size="icon"
              className={spreadRoutes ? 'text-accent-teal' : 'text-muted-foreground hover:text-foreground'}
              aria-pressed={spreadRoutes}
              label="重叠路径分束展开"
              tooltip={spreadRoutes ? '关闭重叠路径分束（切回重合模式）' : '开启重叠路径分束展开'}
              onClick={onToggleSpreadRoutes}
            >
              <GitFork className="h-4 w-4" />
            </IconActionButton>
          )}
        </>
      )}
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
    </Card>
  );
}
