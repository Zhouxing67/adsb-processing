import { ChevronLeft, ChevronRight, Layers, Maximize2, Trash2 } from 'lucide-react';
import { Button } from './button';
import { IconActionButton } from './workbench-shell';

interface InspectionStepperProps {
  total: number;
  currentIndex: number;
  onPrev(): void;
  onNext(): void;
  onShowAll(): void;
}

/** Compact sequential inspection bar for stepping through map flights or routes one by one. */
export function InspectionStepper({
  total,
  currentIndex,
  onPrev,
  onNext,
  onShowAll,
}: InspectionStepperProps) {
  if (total === 0) return null;
  const isolated = currentIndex >= 0;

  return (
    <div className="flex shrink-0 items-center justify-between gap-1.5 border-b border-border bg-background px-2.5 py-1.5">
      <div className="flex items-center gap-0.5">
        <IconActionButton
          variant="outline"
          size="icon-xs"
          className="h-6 w-6"
          label="上一条"
          tooltip="上一条（↑ / ←）"
          onClick={onPrev}
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </IconActionButton>
        <span className="min-w-[64px] px-1.5 text-center text-xs font-medium text-foreground tabular-nums">
          {isolated ? `${currentIndex + 1} / ${total}` : `全部 ${total}`}
        </span>
        <IconActionButton
          variant="outline"
          size="icon-xs"
          className="h-6 w-6"
          label="下一条"
          tooltip="下一条（↓ / →）"
          onClick={onNext}
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </IconActionButton>
      </div>
      <Button
        variant={isolated ? 'secondary' : 'ghost'}
        size="xs"
        disabled={!isolated}
        className="h-6 gap-1 px-2 text-[11px]"
        title="恢复显示全部（Esc）"
        onClick={onShowAll}
      >
        <Layers className="h-3 w-3" />
        <span>全部</span>
      </Button>
    </div>
  );
}

interface MapRailFooterProps {
  disabled: boolean;
  fitLabel: string;
  clearLabel: string;
  onFitAll(): void;
  onClear(): void;
}

/** Shared bottom action bar for map selection rails (fit all + clear). */
export function MapRailFooter({ disabled, fitLabel, clearLabel, onFitAll, onClear }: MapRailFooterProps) {
  return (
    <div className="flex shrink-0 items-center justify-end gap-1 border-t border-border bg-muted/70 px-3 py-1.5">
      <IconActionButton
        size="icon-xs"
        className="text-muted-foreground hover:text-foreground [&_svg]:size-3.5"
        label={fitLabel}
        tooltipSide="top"
        disabled={disabled}
        onClick={onFitAll}
      >
        <Maximize2 />
      </IconActionButton>
      <IconActionButton
        size="icon-xs"
        className="text-muted-foreground hover:text-destructive [&_svg]:size-3.5"
        label={clearLabel}
        tooltipSide="top"
        disabled={disabled}
        onClick={onClear}
      >
        <Trash2 />
      </IconActionButton>
    </div>
  );
}
