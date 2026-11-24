import { RefreshCw, RotateCcw, Search } from 'lucide-react';
import type { RouteList } from '@/api/types';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Toggle } from '@/components/ui/toggle';
import { FilterBar } from '@/components/ui/workbench-shell';
import { ROUTE_STATUS_LABELS as statusLabels } from '@/domain/palette';
import { cn } from '@/lib/utils';

export const ALL_VALUE = '__all__';
export const NULL_RUNWAY_VALUE = '__null__';
export const STATUS_ORDER = ['candidate', 'verified', 'rejected', 'manual'] as const;

export interface RouteFilters {
  query: string;
  movement: string;
  stand: string;
  runway: string;
  status: string;
  allGraphs: boolean;
}

export const defaultRouteFilters: RouteFilters = {
  query: '',
  movement: '',
  stand: '',
  runway: '',
  status: '',
  allGraphs: false,
};

interface RouteFilterBarProps {
  draft: RouteFilters;
  filters: RouteFilters;
  data: RouteList | null;
  totalAllStatuses: number;
  loading: boolean;
  error: string;
  onDraftChange(updater: (current: RouteFilters) => RouteFilters): void;
  onImmediatePatch(patch: Partial<RouteFilters>): void;
  onApply(): void;
  onReset(): void;
  onRefresh(): void;
}

export function RouteFilterBar({
  draft,
  filters,
  data,
  totalAllStatuses,
  loading,
  error,
  onDraftChange,
  onImmediatePatch,
  onApply,
  onReset,
  onRefresh,
}: RouteFilterBarProps) {
  return (
    <FilterBar>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[160px] max-w-[280px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="搜索路径库"
            placeholder="搜索机位、跑道、路径 ID 或备注…"
            className="pl-8"
            value={draft.query}
            onChange={event => onDraftChange(current => ({ ...current, query: event.target.value }))}
            onKeyDown={event => {
              if (event.key === 'Enter') onApply();
            }}
          />
        </div>

        <Select
          value={draft.movement || ALL_VALUE}
          onValueChange={value => onImmediatePatch({ movement: value === ALL_VALUE ? '' : value })}
        >
          <SelectTrigger aria-label="路径进出港" className="w-[104px] shrink-0">
            <SelectValue placeholder="进出港" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>全部方向</SelectItem>
            <SelectItem value="departure">离港</SelectItem>
            <SelectItem value="arrival">进港</SelectItem>
          </SelectContent>
        </Select>

        <Select
          value={draft.stand || ALL_VALUE}
          onValueChange={value => onImmediatePatch({ stand: value === ALL_VALUE ? '' : value })}
        >
          <SelectTrigger aria-label="路径机位" className="w-[112px] shrink-0">
            <SelectValue placeholder="机位" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>全部机位</SelectItem>
            {(data?.stand_options ?? []).map(stand => (
              <SelectItem key={stand} value={stand}>
                {stand}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={draft.runway || ALL_VALUE}
          onValueChange={value => onImmediatePatch({ runway: value === ALL_VALUE ? '' : value })}
        >
          <SelectTrigger aria-label="路径跑道" className="w-[112px] shrink-0">
            <SelectValue placeholder="跑道" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>全部跑道</SelectItem>
            <SelectItem value={NULL_RUNWAY_VALUE}>缺失跑道</SelectItem>
            {(data?.runway_options ?? []).map(rwy => (
              <SelectItem key={rwy} value={rwy}>
                {rwy}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button variant="default" size="default" className="shrink-0" onClick={onApply}>
          过滤
        </Button>
        <Button variant="ghost" size="icon" className="shrink-0 text-muted-foreground hover:text-foreground" title="重置筛选" aria-label="重置筛选" onClick={onReset}>
          <RotateCcw className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="shrink-0 text-muted-foreground hover:text-foreground"
          title="刷新路径库"
          aria-label="刷新路径库"
          disabled={loading}
          onClick={onRefresh}
        >
          <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
        </Button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex flex-wrap items-center gap-1">
          <Toggle
            variant="outline"
            size="sm"
            pressed={filters.status === ''}
            onClick={() => onImmediatePatch({ status: '' })}
          >
            全部
            <span className="tabular-nums opacity-75">{totalAllStatuses}</span>
          </Toggle>
          {STATUS_ORDER.map(status => (
            <Toggle
              key={status}
              variant="outline"
              size="sm"
              pressed={filters.status === status}
              onClick={() => onImmediatePatch({ status })}
            >
              {statusLabels[status]}
              <span className="tabular-nums opacity-75">{data?.status_counts[status] ?? 0}</span>
            </Toggle>
          ))}
        </div>

        <Label className="flex cursor-pointer items-center gap-1.5 font-normal text-muted-foreground hover:text-foreground">
          <Checkbox
            checked={filters.allGraphs}
            onCheckedChange={checked => onImmediatePatch({ allGraphs: checked === true })}
          />
          <span>显示全部图版本</span>
        </Label>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </FilterBar>
  );
}
