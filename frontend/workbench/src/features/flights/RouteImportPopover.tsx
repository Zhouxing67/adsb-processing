import { useEffect, useRef, useState } from 'react';
import { Database } from 'lucide-react';
import { api } from '@/api/client';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Spinner } from '@/components/ui/spinner';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { PopoverFooter } from '@/components/ui/workbench-shell';
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
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && importing) return;
    if (nextOpen) setError('');
    setOpen(nextOpen);
  };

  const cancelImport = () => {
    if (importing) {
      abortRef.current?.abort();
      return;
    }
    setError('');
    setOpen(false);
  };

  const importToRouteLibrary = async () => {
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setImporting(true);
    setError('');
    try {
      const summary = await api.importMatchedRoutes(
        {
          flight_keys: scope === 'selected' ? [...wb.matchSelection] : null,
          replace_candidates: replaceCandidates,
        },
        controller.signal,
      );
      setOpen(false);
      if (summary.evaluated_flights === 0) {
        wb.dispatch({ type: 'status', value: '当前范围内尚无匹配成功的航班可入库' });
      } else {
        wb.dispatch({ type: 'routes-updated' });
        const extra = summary.deleted_candidates > 0 ? `，清理旧候选 ${summary.deleted_candidates} 条` : '';
        wb.dispatch({
          type: 'status',
          value: `路径库入库完成：评估 ${summary.evaluated_flights} 架次，去重 ${summary.unique_routes} 条（新增 ${summary.inserted_routes}、已存在 ${summary.existing_routes}${extra}）`,
        });
      }
    } catch (failure) {
      if ((failure as Error).name === 'AbortError') {
        wb.dispatch({ type: 'status', value: '已取消写入路径库' });
        setOpen(false);
        return;
      }
      const message = failure instanceof Error ? failure.message : '入路径库失败';
      setError(message);
      wb.dispatch({ type: 'error', value: message });
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setImporting(false);
    }
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              size="icon-sm"
              disabled={disabled || importing}
              aria-label="入路径库"
            >
              {importing ? <Spinner className="h-3.5 w-3.5" /> : <Database className="h-3.5 w-3.5" />}
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent side="bottom">{importing ? '入库中…' : '入路径库'}</TooltipContent>
      </Tooltip>
      <PopoverContent align="end" className="w-72 space-y-3 p-3 text-xs">
        <div className="font-semibold text-foreground">写入路径库</div>
        <RadioGroup
          value={scope}
          onValueChange={value => setScope(value as 'all' | 'selected')}
          className="space-y-1.5"
          disabled={importing}
        >
          <Label className="flex cursor-pointer items-center gap-2 font-normal">
            <RadioGroupItem value="all" disabled={importing} />
            <span>全部已匹配成功航班</span>
          </Label>
          <Label
            className={cn(
              'flex items-center gap-2 font-normal',
              wb.matchSelection.size > 0 && !importing
                ? 'cursor-pointer text-foreground'
                : 'cursor-not-allowed text-muted-foreground',
            )}
          >
            <RadioGroupItem value="selected" disabled={importing || wb.matchSelection.size === 0} />
            <span>仅当前已勾选航班（{wb.matchSelection.size} 条）</span>
          </Label>
        </RadioGroup>
        <Label className="flex cursor-pointer items-center gap-2 border-t border-border pt-2 font-normal">
          <Checkbox
            checked={replaceCandidates}
            disabled={importing}
            onCheckedChange={checked => setReplaceCandidates(checked === true)}
          />
          <span>先清理当前图旧的待审校候选（保留已审校）</span>
        </Label>
        {error && (
          <Alert variant="destructive" className="px-2.5 py-1.5 text-xs">
            {error}
          </Alert>
        )}
        <PopoverFooter>
          <Button variant="ghost" size="sm" onClick={cancelImport}>
            取消
          </Button>
          <Button
            variant="default"
            size="sm"
            disabled={importing || (scope === 'selected' && wb.matchSelection.size === 0)}
            onClick={() => void importToRouteLibrary()}
          >
            {importing && <Spinner className="h-3.5 w-3.5" />}
            {importing ? '入库中…' : '确认入库'}
          </Button>
        </PopoverFooter>
      </PopoverContent>
    </Popover>
  );
}
