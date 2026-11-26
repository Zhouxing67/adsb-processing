import { Crosshair } from 'lucide-react';
import type { WorkbenchState } from '@/api/types';
import { Checkbox } from '@/components/ui/checkbox';
import { Empty } from '@/components/ui/empty';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { StandClusterPanel } from './StandClusterPanel';

export interface LayerSettings {
  base: 'none' | 'osm' | 'satellite';
  edges: boolean;
  parking: boolean;
  nodes: boolean;
  spreadRoutes: boolean;
  colorByCluster: boolean;
}

interface InspectorProps {
  state: WorkbenchState;
  layers: LayerSettings;
  onLayers(value: LayerSettings): void;
  embedded?: boolean;
}

export function Inspector({ state, layers, onLayers, embedded = false }: InspectorProps) {
  const parkingEdges = state.edges.features.filter(item => item.properties.aeroway === 'parking_position');
  const parking = parkingEdges.length;
  const clusteredParking = parkingEdges.filter(item => item.properties.cluster_id != null).length;
  const derived = state.edges.features.length - parking;

  return (
    <aside className={embedded ? 'flex h-full min-h-0 w-full flex-col bg-transparent' : 'flex h-full min-h-0 w-full flex-col bg-background'}>
      {!embedded && (
        <div className="flex h-14 shrink-0 items-center border-b border-border px-5">
          <h1 className="m-0 text-[15px] font-semibold text-foreground">机场地面网络</h1>
        </div>
      )}
      <ScrollArea className="min-h-0 flex-1">
        <div className={embedded ? 'space-y-4 p-4' : 'space-y-5 p-5'}>
          <div className="flex items-center gap-6 border-b border-border pb-4 tabular-nums">
            <div className="grid gap-0.5">
              <strong className="text-xl font-semibold text-accent-teal">{state.node_count}</strong>
              <span className="text-[11px] text-muted-foreground">节点</span>
            </div>
            <div className="grid gap-0.5">
              <strong className="text-xl font-semibold text-accent-amber">{state.edge_count}</strong>
              <span className="text-[11px] text-muted-foreground">边</span>
            </div>
            {state.flight_mode && (
              <div className="grid gap-0.5">
                <strong className="text-xl font-semibold text-primary">{state.flight_count}</strong>
                <span className="text-[11px] text-muted-foreground">航班</span>
              </div>
            )}
          </div>

        <section className="space-y-3 border-b border-border pb-5">
          <h3 className="m-0 text-xs font-semibold text-foreground">图层与底图</h3>
          <div className="grid gap-2 text-xs text-muted-foreground">
            <RadioGroup
              value={layers.base}
              onValueChange={value => onLayers({ ...layers, base: value as LayerSettings['base'] })}
              className="gap-2"
            >
              <Label className="flex cursor-pointer items-center gap-2 font-normal text-foreground">
                <RadioGroupItem value="osm" aria-label="OpenStreetMap" />
                <span>OpenStreetMap</span>
              </Label>
              <Label className="flex cursor-pointer items-center gap-2 font-normal text-foreground">
                <RadioGroupItem value="satellite" aria-label="ESRI 卫星" />
                <span>ESRI 卫星</span>
              </Label>
              <Label className="flex cursor-pointer items-center gap-2 font-normal text-foreground">
                <RadioGroupItem value="none" aria-label="无底图（精细编辑）" />
                <span>无底图（精细编辑）</span>
              </Label>
            </RadioGroup>
            <Separator className="my-1" />
            <Label className="flex cursor-pointer items-center gap-2 font-normal text-foreground tabular-nums">
              <Checkbox
                checked={layers.edges}
                onCheckedChange={checked => onLayers({ ...layers, edges: checked === true })}
              />
              <span>派生边（{derived}）</span>
            </Label>
            <Label className="flex cursor-pointer items-center gap-2 font-normal text-foreground tabular-nums">
              <Checkbox
                checked={layers.parking}
                onCheckedChange={checked => onLayers({ ...layers, parking: checked === true })}
              />
              <span>停机位（{parking}）</span>
            </Label>
            <Label className="flex cursor-pointer items-center gap-2 font-normal text-foreground">
              <Checkbox
                checked={layers.colorByCluster}
                onCheckedChange={checked => onLayers({ ...layers, colorByCluster: checked === true })}
              />
              <span>按机位类别着色</span>
            </Label>
            <Label className="flex cursor-pointer items-center gap-2 font-normal text-foreground tabular-nums">
              <Checkbox
                checked={layers.nodes}
                onCheckedChange={checked => onLayers({ ...layers, nodes: checked === true })}
              />
              <span>图节点（{state.node_count}）</span>
            </Label>
            {state.flight_mode && (
              <Label className="flex cursor-pointer items-center gap-2 font-normal text-foreground">
                <Checkbox
                  checked={layers.spreadRoutes}
                  onCheckedChange={checked => onLayers({ ...layers, spreadRoutes: checked === true })}
                />
                <span>重叠路径分束展开</span>
              </Label>
            )}
          </div>
        </section>

        <section className="space-y-3 border-b border-border pb-5">
          <h3 className="m-0 text-xs font-semibold text-foreground">地图图例</h3>
          <div className="grid gap-2 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-2.5">
              <i className="h-2 w-2 rounded-full bg-[#416878]" />
              普通节点
            </span>
            <span className="flex items-center gap-2.5">
              <i className="h-[3px] w-4 rounded-full bg-[#dc6b32]" />
              停机位
            </span>
            <span className="flex items-center gap-2.5">
              <i className="grid h-4 w-4 place-items-center rounded-[3px] bg-[#d78816] text-[10px] font-bold not-italic text-white">
                R
              </i>
              跑道接口
            </span>
            <span className="flex items-center gap-2.5">
              <i className="h-[3px] w-4 rounded-full bg-[#9a684d]" />
              派生边
            </span>
            <span className="flex items-center gap-2.5">
              <i className="h-0 w-4 border-t-[3px] border-dashed border-[#0072b2]" />
              虚线＝原始轨迹
            </span>
            <span className="flex items-center gap-2.5">
              <i className="h-[3px] w-4 rounded-full bg-[#c2185b]" />
              实线＝匹配路径
            </span>
          </div>
        </section>

        {(state.capabilities.can_edit_graph || (state.stand_clusters?.length ?? 0) > 0) && (
          <StandClusterPanel
            clusters={state.stand_clusters ?? []}
            totalParkingEdges={parking}
            clusteredParkingEdges={clusteredParking}
            canEdit={state.capabilities.can_edit_graph}
          />
        )}

        {!embedded && (
          <Empty className="gap-2 py-8">
            <Crosshair className="h-5 w-5 opacity-50" />
            <h3 className="m-0 text-xs font-normal text-muted-foreground">选择一个图要素</h3>
          </Empty>
        )}
        </div>
      </ScrollArea>
    </aside>
  );
}
