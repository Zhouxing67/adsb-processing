import { MapPinOff, MapPinPlus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { IconActionButton } from '@/components/ui/workbench-shell';

interface RouteBulkBarProps {
  selectedCount: number;
  selectedOnMapCount: number;
  selectablePageCount: number;
  allPageSelected: boolean;
  addingProgress: { done: number; total: number } | null;
  onTogglePage(): void;
  onClearSelection(): void;
  onAddSelectedToMap(): void;
  onRemoveSelectedFromMap(): void;
  onCancelAddToMap(): void;
}

export function RouteBulkBar({
  selectedCount,
  selectedOnMapCount,
  selectablePageCount,
  allPageSelected,
  addingProgress,
  onTogglePage,
  onClearSelection,
  onAddSelectedToMap,
  onRemoveSelectedFromMap,
  onCancelAddToMap,
}: RouteBulkBarProps) {
  return (
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-1.5">
      <div className="flex flex-wrap items-center gap-3">
        <Label className="inline-flex cursor-pointer items-center gap-1.5 font-normal text-foreground">
          <Checkbox
            aria-label="选择本页可叠加路径"
            disabled={selectablePageCount === 0}
            checked={selectablePageCount > 0 && allPageSelected}
            onCheckedChange={onTogglePage}
          />
          <span>选择本页</span>
        </Label>
        <IconActionButton
          variant="ghost"
          size="icon-xs"
          label="清空所选路径"
          tooltip="清空所选路径"
          disabled={!selectedCount}
          onClick={onClearSelection}
        >
          <X className="h-3.5 w-3.5" />
        </IconActionButton>
        <span className="text-[11px] text-muted-foreground tabular-nums">已选 {selectedCount} 条</span>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          variant="default"
          size="sm"
          disabled={!selectedCount || Boolean(addingProgress)}
          onClick={onAddSelectedToMap}
        >
          <MapPinPlus className="h-3.5 w-3.5" />
          {addingProgress ? (
            <span className="tabular-nums">
              加入中 {addingProgress.done}/{addingProgress.total}
            </span>
          ) : (
            <span>所选加入地图</span>
          )}
        </Button>
        {addingProgress && (
          <Button variant="ghost" size="sm" onClick={onCancelAddToMap}>
            取消
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          disabled={!selectedOnMapCount || Boolean(addingProgress)}
          onClick={onRemoveSelectedFromMap}
        >
          <MapPinOff className="h-3.5 w-3.5" />
          <span>移出地图</span>
        </Button>
      </div>
    </div>
  );
}
