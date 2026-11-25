import { Flag, FlagOff, MapPinPlus, RefreshCw, X } from 'lucide-react';
import type { MatchStatus } from '@/api/types';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { IconActionButton } from '@/components/ui/workbench-shell';
import { RouteImportPopover } from './RouteImportPopover';

interface FlightBulkBarProps {
  selectedCount: number;
  pageCount: number;
  allPageSelected: boolean;
  allResultsChecked: boolean;
  canEditIssues: boolean;
  mutatingIssues: boolean;
  addingProgress: { done: number; total: number } | null;
  tracking: boolean;
  progress: MatchStatus['progress'] | null;
  onTogglePage(): void;
  onToggleAllResults(checked: boolean): void;
  onClearSelection(): void;
  onArchiveIssues(): void;
  onRemoveIssues(): void;
  onAddSelectedToMap(): void;
  onReplacePageToMap(): void;
  onCancelAddToMap(): void;
  onRequestSubmit(): void;
}

export function FlightBulkBar({
  selectedCount,
  pageCount,
  allPageSelected,
  allResultsChecked,
  canEditIssues,
  mutatingIssues,
  addingProgress,
  tracking,
  progress,
  onTogglePage,
  onToggleAllResults,
  onClearSelection,
  onArchiveIssues,
  onRemoveIssues,
  onAddSelectedToMap,
  onReplacePageToMap,
  onCancelAddToMap,
  onRequestSubmit,
}: FlightBulkBarProps) {
  const hasProgressActivity = Boolean(
    progress && progress.waiting + progress.running + progress.success + progress.failed > 0,
  );

  return (
    <>
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-1.5">
        <div className="flex flex-wrap items-center gap-3">
          <Label className="inline-flex cursor-pointer items-center gap-1.5 font-normal text-foreground">
            <Checkbox
              aria-label="选择本页航班"
              checked={allPageSelected}
              onCheckedChange={onTogglePage}
            />
            <span>选择本页</span>
          </Label>
          <Label className="inline-flex cursor-pointer items-center gap-1.5 font-normal text-foreground">
            <Checkbox
              aria-label="选择全部结果"
              checked={allResultsChecked}
              onCheckedChange={checked => onToggleAllResults(checked === true)}
            />
            <span>选择全部结果</span>
          </Label>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="清空所选航班"
            title="清空所选航班"
            disabled={!selectedCount}
            onClick={onClearSelection}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
          <span className="text-[11px] text-muted-foreground tabular-nums">已选 {selectedCount} 条</span>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {canEditIssues && (
            <>
              <IconActionButton
                variant="outline"
                disabled={!selectedCount || mutatingIssues}
                label="加入异常"
                tooltip="加入异常归档"
                onClick={onArchiveIssues}
              >
                <Flag className="h-3.5 w-3.5" />
              </IconActionButton>
              <IconActionButton
                disabled={!selectedCount || mutatingIssues}
                label="移出异常"
                tooltip="移出异常归档"
                onClick={onRemoveIssues}
              >
                <FlagOff className="h-3.5 w-3.5" />
              </IconActionButton>
            </>
          )}
          <Button
            variant="outline"
            size="sm"
            disabled={!pageCount || Boolean(addingProgress)}
            title="清空当前地图航班，加载本页全部航班并进入逐条巡检"
            onClick={onReplacePageToMap}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>本页替换到地图</span>
          </Button>
          <IconActionButton
            variant="outline"
            size={addingProgress ? 'sm' : 'icon-sm'}
            disabled={!selectedCount || Boolean(addingProgress)}
            label="所选加入地图"
            onClick={onAddSelectedToMap}
          >
            <MapPinPlus className="h-3.5 w-3.5" />
            {addingProgress && (
              <span className="tabular-nums">
                {addingProgress.done}/{addingProgress.total}
              </span>
            )}
          </IconActionButton>
          {addingProgress && (
            <Button variant="ghost" size="sm" onClick={onCancelAddToMap}>
              取消
            </Button>
          )}
          <RouteImportPopover disabled={tracking} />
          <Button
            variant="default"
            size="sm"
            disabled={!selectedCount || tracking}
            onClick={onRequestSubmit}
          >
            {tracking ? '匹配中…' : '匹配所选航班'}
          </Button>
        </div>
      </div>

      {hasProgressActivity && progress && (
        <section className="flex shrink-0 items-center gap-4 border-b border-border bg-muted/70 px-4 py-1.5 text-[11px]">
          <strong className="font-medium text-foreground">批量任务</strong>
          <dl className="m-0 flex items-center gap-4 tabular-nums">
            <div className="flex items-baseline gap-1">
              <dt className="text-muted-foreground">等待</dt>
              <dd className="m-0 font-semibold text-foreground">{progress.waiting}</dd>
            </div>
            <div className="flex items-baseline gap-1">
              <dt className="text-muted-foreground">运行</dt>
              <dd className="m-0 font-semibold text-amber-700">{progress.running}</dd>
            </div>
            <div className="flex items-baseline gap-1">
              <dt className="text-muted-foreground">成功</dt>
              <dd className="m-0 font-semibold text-emerald-700">{progress.success}</dd>
            </div>
            <div className="flex items-baseline gap-1">
              <dt className="text-muted-foreground">失败</dt>
              <dd className="m-0 font-semibold text-destructive">{progress.failed}</dd>
            </div>
          </dl>
        </section>
      )}
    </>
  );
}
