import * as React from 'react';
import { GripVertical } from 'lucide-react';
import { Group, Panel, Separator } from 'react-resizable-panels';
import type { GroupProps, PanelProps, SeparatorProps } from 'react-resizable-panels';
import { cn } from '@/lib/utils';

export function ResizablePanelGroup({ className, ...props }: GroupProps) {
  return (
    <Group
      className={cn('flex h-full w-full data-[orientation=vertical]:flex-col', className)}
      {...props}
    />
  );
}

export function ResizablePanel({ className, ...props }: PanelProps) {
  return <Panel className={cn('min-w-0 min-h-0', className)} {...props} />;
}

export function ResizableHandle({
  withHandle,
  className,
  ...props
}: SeparatorProps & { withHandle?: boolean }) {
  return (
    <Separator
      className={cn(
        'relative flex w-1.5 items-center justify-center bg-border/70 transition-colors hover:bg-zinc-400/70 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring data-[separator=active]:bg-zinc-500 cursor-col-resize',
        className,
      )}
      {...props}
    >
      {withHandle && (
        <div className="z-10 flex h-6 w-3 items-center justify-center rounded-xs border border-border bg-background shadow-xs">
          <GripVertical className="h-3 w-3 text-muted-foreground" />
        </div>
      )}
    </Separator>
  );
}
