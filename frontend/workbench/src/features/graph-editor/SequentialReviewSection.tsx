import { ChevronLeft, ChevronRight, Play, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { IconActionButton } from '@/components/ui/workbench-shell';

interface SequentialReviewSectionProps {
  title: string;
  total: number;
  currentIndex: number;
  currentLabel?: string;
  onStart(): void;
  onStop(): void;
  onPrev(): void;
  onNext(): void;
}

/** Shared sequential start/stop/prev/next inspection section for TopologyPanel. */
export function SequentialReviewSection({
  title,
  total,
  currentIndex,
  currentLabel,
  onStart,
  onStop,
  onPrev,
  onNext,
}: SequentialReviewSectionProps) {
  const reviewing = currentIndex >= 0;

  return (
    <section className="space-y-2.5 py-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="m-0 text-xs font-semibold text-foreground">{title}</h3>
        {reviewing && (
          <span className="truncate text-[11px] text-primary tabular-nums">
            {currentIndex + 1} / {total}
            {currentLabel ? ` · ${currentLabel}` : ''}
          </span>
        )}
      </div>
      <div className="flex items-center justify-between gap-2">
        <Button
          variant={reviewing ? 'outline' : 'default'}
          size="sm"
          disabled={total === 0}
          onClick={() => {
            if (reviewing) onStop();
            else onStart();
          }}
        >
          {reviewing ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
          {reviewing ? '结束' : '开始'}
        </Button>
        <div className="flex items-center gap-1">
          <IconActionButton
            variant="outline"
            label={`上一个${title}`}
            disabled={currentIndex <= 0}
            onClick={onPrev}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </IconActionButton>
          <IconActionButton
            variant="outline"
            label={`下一个${title}`}
            disabled={!reviewing || currentIndex >= total - 1}
            onClick={onNext}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </IconActionButton>
        </div>
      </div>
    </section>
  );
}
