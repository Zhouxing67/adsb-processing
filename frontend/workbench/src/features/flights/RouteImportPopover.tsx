import { useState } from 'react';
import { Database } from 'lucide-react';
import { api } from '@/api/client';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { cn } from '@/lib/utils';

interface RouteImportPopoverProps {
  disabled: boolean;
}

export function RouteImportPopover({ disabled }: RouteImportPopoverProps) {
  const wb = useWorkbench();
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<'all' | 'selected'>('all');
  const [replaceCandidates, setReplaceCandidates] = useState(false);
  const [importing, setImporting] = useState(false);

  const importToRouteLibrary = async () => {
    setImporting(true);
    try {
      const summary = await api.importMatchedRoutes({
        flight_keys: scope === 'selected' ? [...wb.matchSelection] : null,
        replace_candidates: replaceCandidates,
      });
      setOpen(false);
      if (summary.evaluated_flights === 0) {
        wb.dispatch({ type: 'status', value: '当前范围内尚无匹配成功的航班可入库' });
      } else {
        const extra = summary.deleted_candidates > 0 ? `，清理旧候选 ${summary.deleted_candidates} 条` : '';
        wb.dispatch({
          type: 'status',
          value: `路径库入库完成：评估 ${summary.evaluated_flights} 架次，去重 ${summary.unique_routes} 条（新增 ${summary.inserted_routes}、已存在 ${summary.existing_routes}${extra}）`,
        });
      }
    } catch (failure) {
      wb.dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '入路径库失败' });
    } finally {
      setImporting(false);
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled || importing}
          title="将工作台匹配成功的航班路径写入 DuckDB 路径库"
        >
          <Database className="h-3.5 w-3.5" />
          {importing ? '入库中…' : '入路径库'}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 space-y-3 p-3 text-xs">
        <div>
          <div className="font-medium text-foreground">匹配结果写入路径库</div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            将当前图下匹配成功的航班按 OD 去重后写入 DuckDB（main.route_library）。
          </p>
        </div>
        <RadioGroup
          value={scope}
          onValueChange={value => setScope(value as 'all' | 'selected')}
          className="space-y-1.5"
        >
          <label className="flex cursor-pointer items-center gap-2">
            <RadioGroupItem value="all" />
            <span>全部已匹配成功航班</span>
          </label>
          <label
            className={cn(
              'flex items-center gap-2',
              wb.matchSelection.size > 0
                ? 'cursor-pointer text-foreground'
                : 'cursor-not-allowed text-muted-foreground',
            )}
          >
            <RadioGroupItem value="selected" disabled={wb.matchSelection.size === 0} />
            <span>仅当前已勾选航班（{wb.matchSelection.size} 条）</span>
          </label>
        </RadioGroup>
        <label className="flex cursor-pointer items-center gap-2 border-t border-border pt-2">
          <Checkbox
            checked={replaceCandidates}
            onCheckedChange={checked => setReplaceCandidates(checked === true)}
          />
          <span>先清理当前图旧的待审校候选（保留已审校）</span>
        </label>
        <div className="flex justify-end gap-1.5 pt-1">
          <Button variant="ghost" size="xs" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            variant="default"
            size="xs"
            disabled={importing || (scope === 'selected' && wb.matchSelection.size === 0)}
            onClick={() => void importToRouteLibrary()}
          >
            确认入库
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
