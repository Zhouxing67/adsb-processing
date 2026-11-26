import { useMemo, useState } from 'react';
import { Calendar as CalendarIcon, Filter, RotateCcw, Search, X } from 'lucide-react';
import { format, isValid, parseISO } from 'date-fns';
import type { DateRange } from 'react-day-picker';
import type { FlightCatalogue } from '@/api/types';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { FilterBar, PopoverFooter } from '@/components/ui/workbench-shell';
import { MATCH_STATUS_LABELS as statusLabels } from '@/domain/palette';

const ALL_VALUE = '__all__';

function toDate(value: string): Date | undefined {
  if (!value) return undefined;
  const parsed = parseISO(value);
  return isValid(parsed) ? parsed : undefined;
}

function toIsoDate(value?: Date): string {
  return value && isValid(value) ? format(value, 'yyyy-MM-dd') : '';
}

export interface DraftFilters {
  query: string;
  movement: string;
  status: string;
  minimum: string;
  maximum: string;
  stands: string[];
  start: string;
  end: string;
  validation: boolean;
  issues: boolean;
}

export interface ActiveFilterChip {
  id: string;
  label: string;
  clear(): void;
}

interface FlightFilterBarProps {
  draft: DraftFilters;
  catalogue: FlightCatalogue | null;
  issueCount: number;
  advancedActiveCount: number;
  activeChips: ActiveFilterChip[];
  error: string;
  onDraftChange(next: DraftFilters | ((current: DraftFilters) => DraftFilters)): void;
  onValidateAndApply(): boolean;
  onReset(): void;
}

export function FlightFilterBar({
  draft,
  catalogue,
  issueCount,
  advancedActiveCount,
  activeChips,
  error,
  onDraftChange,
  onValidateAndApply,
  onReset,
}: FlightFilterBarProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [standSearch, setStandSearch] = useState('');

  const visibleStands = useMemo(
    () =>
      ['', ...(catalogue?.stand_options ?? [])].filter(stand =>
        (stand || '空机位').toLowerCase().includes(standSearch.toLowerCase()),
      ),
    [catalogue, standSearch],
  );

  return (
    <FilterBar>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[140px] max-w-[240px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={draft.query}
            placeholder="航班号 / ID"
            className="pl-8"
            onChange={event => onDraftChange({ ...draft, query: event.target.value })}
            onKeyDown={event => {
              if (event.key === 'Enter') onValidateAndApply();
            }}
          />
        </div>

        <Select
          value={draft.movement || ALL_VALUE}
          onValueChange={value => onDraftChange({ ...draft, movement: value === ALL_VALUE ? '' : value })}
        >
          <SelectTrigger aria-label="进出港" className="w-[118px] shrink-0">
            <SelectValue placeholder="进出港" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>全部进出港</SelectItem>
            <SelectItem value="arrival">进港</SelectItem>
            <SelectItem value="departure">离港</SelectItem>
            <SelectItem value="unknown">未知</SelectItem>
          </SelectContent>
        </Select>

        <Select
          value={draft.status || ALL_VALUE}
          onValueChange={value => onDraftChange({ ...draft, status: value === ALL_VALUE ? '' : value })}
        >
          <SelectTrigger aria-label="匹配状态" className="w-[104px] shrink-0">
            <SelectValue placeholder="匹配状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>全部状态</SelectItem>
            {Object.entries(statusLabels).map(([key, label]) => (
              <SelectItem key={key} value={key}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Popover open={advancedOpen} onOpenChange={setAdvancedOpen}>
          <PopoverTrigger asChild>
            <Button variant="outline" size="default" className="shrink-0">
              <Filter className="h-3.5 w-3.5 text-muted-foreground" />
              更多筛选
              {advancedActiveCount > 0 && (
                <Badge variant="default" className="ml-0.5 rounded-full px-1.5 py-0 text-[11px]">
                  {advancedActiveCount}
                </Badge>
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80 space-y-3 p-3">
            <div className="space-y-1.5">
              <span className="text-xs font-semibold text-foreground">机位筛选</span>
              <Input
                type="search"
                aria-label="搜索机位"
                placeholder="搜索机位…"
                value={standSearch}
                onChange={event => setStandSearch(event.target.value)}
              />
              <ScrollArea className="h-32 rounded-md border border-border bg-muted/40 p-1">
                <div className="space-y-0.5">
                  {visibleStands.map(stand => {
                    const checked = draft.stands.includes(stand);
                    const label = stand || '空机位';
                    return (
                      <Label
                        key={stand || '__empty'}
                        className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 font-normal text-foreground hover:bg-accent"
                      >
                        <Checkbox
                          aria-label={label}
                          checked={checked}
                          onCheckedChange={next => {
                            const isChecked = next === true;
                            onDraftChange(value => ({
                              ...value,
                              stands: isChecked
                                ? [...value.stands, stand]
                                : value.stands.filter(item => item !== stand),
                            }));
                          }}
                        />
                        <span>{label}</span>
                      </Label>
                    );
                  })}
                </div>
              </ScrollArea>
            </div>

            <Separator />

            <div className="grid grid-cols-2 gap-2">
              <Label className="grid gap-1 font-normal">
                <span className="text-muted-foreground">最小观测点数</span>
                <Input
                  type="number"
                  min={0}
                  aria-label="最小观测点数"
                  placeholder="最小值"
                  value={draft.minimum}
                  onChange={event => onDraftChange({ ...draft, minimum: event.target.value })}
                  onKeyDown={event => {
                    if (event.key === 'Enter' && onValidateAndApply()) setAdvancedOpen(false);
                  }}
                />
              </Label>
              <Label className="grid gap-1 font-normal">
                <span className="text-muted-foreground">最大观测点数</span>
                <Input
                  type="number"
                  min={0}
                  aria-label="最大观测点数"
                  placeholder="最大值"
                  value={draft.maximum}
                  onChange={event => onDraftChange({ ...draft, maximum: event.target.value })}
                  onKeyDown={event => {
                    if (event.key === 'Enter' && onValidateAndApply()) setAdvancedOpen(false);
                  }}
                />
              </Label>
            </div>

            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">日期范围</span>
              <Popover open={datePickerOpen} onOpenChange={setDatePickerOpen}>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    size="default"
                    aria-label="日期范围"
                    className="w-full justify-start gap-2 font-normal text-foreground tabular-nums"
                  >
                    <CalendarIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">
                      {draft.start && draft.end
                        ? `${draft.start} 至 ${draft.end}`
                        : draft.start
                          ? `${draft.start} 起`
                          : draft.end
                            ? `至 ${draft.end}`
                            : '选择日期范围'}
                    </span>
                  </Button>
                </PopoverTrigger>
                <PopoverContent align="start" className="w-auto p-0">
                  <Calendar
                    mode="range"
                    defaultMonth={toDate(draft.start) ?? toDate(catalogue?.dataset_min_date ?? '')}
                    selected={{ from: toDate(draft.start), to: toDate(draft.end) } as DateRange}
                    onSelect={range => {
                      onDraftChange(current => ({
                        ...current,
                        start: toIsoDate(range?.from),
                        end: toIsoDate(range?.to ?? range?.from),
                      }));
                    }}
                  />
                  <div className="flex items-center justify-between border-t border-border px-3 py-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        onDraftChange(current => ({
                          ...current,
                          start: catalogue?.dataset_min_date ?? '',
                          end: catalogue?.dataset_max_date ?? '',
                        }));
                      }}
                    >
                      恢复全部日期
                    </Button>
                    <Button variant="default" size="sm" onClick={() => setDatePickerOpen(false)}>
                      确定
                    </Button>
                  </div>
                </PopoverContent>
              </Popover>
            </div>

            {catalogue?.supports_validation_filter && (
              <Label className="flex cursor-pointer items-center gap-2 font-normal text-foreground">
                <Checkbox
                  checked={draft.validation}
                  onCheckedChange={checked => onDraftChange({ ...draft, validation: checked === true })}
                />
                <span>验证航班（≥30 点）</span>
              </Label>
            )}

            {catalogue && (
              <Label
                className="flex cursor-pointer items-center gap-2 font-normal text-foreground"
                title="仅显示已归档到 match_issues 表的异常航班"
              >
                <Checkbox
                  checked={draft.issues}
                  onCheckedChange={checked => onDraftChange({ ...draft, issues: checked === true })}
                />
                <span>异常归档航班（{issueCount}）</span>
              </Label>
            )}

            <PopoverFooter>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  onReset();
                  setAdvancedOpen(false);
                }}
              >
                重置
              </Button>
              <Button
                variant="default"
                size="sm"
                onClick={() => {
                  if (onValidateAndApply()) setAdvancedOpen(false);
                }}
              >
                应用
              </Button>
            </PopoverFooter>
          </PopoverContent>
        </Popover>

        <Button variant="default" size="default" className="shrink-0" onClick={onValidateAndApply}>
          过滤
        </Button>
      </div>

      {activeChips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {activeChips.map(chip => (
            <Badge key={chip.id} variant="outline" className="gap-1 bg-background pr-1 text-[11px] font-normal">
              <span>{chip.label}</span>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`移除筛选 ${chip.label}`}
                className="h-3.5 w-3.5 rounded-sm text-muted-foreground hover:text-foreground [&_svg]:size-2.5"
                onClick={chip.clear}
              >
                <X />
              </Button>
            </Badge>
          ))}
          <Button variant="ghost" size="xs" className="h-5 px-1.5 text-[11px] text-muted-foreground" onClick={onReset}>
            <RotateCcw className="h-3 w-3" />
            重置
          </Button>
        </div>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </FilterBar>
  );
}
