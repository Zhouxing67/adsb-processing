import { Crosshair } from 'lucide-react';
import type { WorkbenchState } from '@/api/types';
import { Checkbox } from '@/components/ui/checkbox';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';

export interface LayerSettings {
  base: 'none' | 'osm' | 'satellite';
  edges: boolean;
  parking: boolean;
  nodes: boolean;
}

interface InspectorProps {
  state: WorkbenchState;
  layers: LayerSettings;
  onLayers(value: LayerSettings): void;
}

export function Inspector({ state, layers, onLayers }: InspectorProps) {
  const parking = state.edges.features.filter(item => item.properties.aeroway === 'parking_position').length;
  const derived = state.edges.features.length - parking;

  return (
    <ScrollArea className="h-full w-full bg-background">
      <aside className="space-y-5 p-5">
        <div>
          <h1 className="m-0 text-base font-semibold text-foreground">机场地面网络</h1>
          <div className="mt-4 flex items-center gap-6 border-b border-border pb-4 tabular-nums">
            <div className="grid gap-0.5">
              <strong className="text-xl font-medium text-foreground">{state.node_count}</strong>
              <span className="text-[11px] text-muted-foreground">节点</span>
            </div>
            <div className="grid gap-0.5">
              <strong className="text-xl font-medium text-foreground">{state.edge_count}</strong>
              <span className="text-[11px] text-muted-foreground">边</span>
            </div>
            {state.flight_mode && (
              <div className="grid gap-0.5">
                <strong className="text-xl font-medium text-foreground">{state.flight_count}</strong>
                <span className="text-[11px] text-muted-foreground">航班</span>
              </div>
            )}
          </div>
        </div>

        <section className="space-y-3 border-b border-border pb-5">
          <h3 className="m-0 text-xs font-semibold text-foreground">图层与底图</h3>
          <div className="grid gap-2 text-xs text-muted-foreground">
            <RadioGroup
              value={layers.base}
              onValueChange={value => onLayers({ ...layers, base: value as LayerSettings['base'] })}
              className="gap-2"
            >
              <label className="flex cursor-pointer items-center gap-2 text-foreground">
                <RadioGroupItem value="osm" aria-label="OpenStreetMap" />
                <span>OpenStreetMap</span>
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-foreground">
                <RadioGroupItem value="satellite" aria-label="ESRI 卫星" />
                <span>ESRI 卫星</span>
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-foreground">
                <RadioGroupItem value="none" aria-label="无底图（精细编辑）" />
                <span>无底图（精细编辑）</span>
              </label>
            </RadioGroup>
            <Separator className="my-1" />
            <label className="flex cursor-pointer items-center gap-2 text-foreground tabular-nums">
              <Checkbox
                checked={layers.edges}
                onCheckedChange={checked => onLayers({ ...layers, edges: checked === true })}
              />
              <span>派生边（{derived}）</span>
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-foreground tabular-nums">
              <Checkbox
                checked={layers.parking}
                onCheckedChange={checked => onLayers({ ...layers, parking: checked === true })}
              />
              <span>停机位（{parking}）</span>
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-foreground tabular-nums">
              <Checkbox
                checked={layers.nodes}
                onCheckedChange={checked => onLayers({ ...layers, nodes: checked === true })}
              />
              <span>图节点（{state.node_count}）</span>
            </label>
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

        <section className="flex flex-col items-center gap-2 py-8 text-center text-muted-foreground">
          <Crosshair className="h-5 w-5 opacity-50" />
          <h3 className="m-0 text-xs font-normal text-muted-foreground">选择一个图要素</h3>
        </section>
      </aside>
    </ScrollArea>
  );
}
