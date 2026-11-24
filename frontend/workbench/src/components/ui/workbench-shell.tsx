import * as React from 'react';
import { cn } from '@/lib/utils';
import { Button } from './button';
import type { ButtonProps } from './button';
import { Spinner } from './spinner';
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip';

/** Standard 56px (h-14) top header shared by center views and rails to keep horizontal hairlines aligned. */
export function ViewHeader({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLElement>) {
  return (
    <header
      className={cn(
        'flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-background px-4',
        className,
      )}
      {...props}
    >
      {children}
    </header>
  );
}

/** Standard muted filter/toolbar strip positioned directly beneath ViewHeader. */
export function FilterBar({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'shrink-0 space-y-2 border-b border-border bg-muted/60 px-4 py-2.5',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

/** Native scrollable data-table wrapper that avoids Radix ScrollArea table-display quirks and preserves sticky headers. */
export function DataTableContainer({
  loading = false,
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { loading?: boolean }) {
  return (
    <div className={cn('relative min-h-0 flex-1 overflow-auto', className)} {...props}>
      {children}
      {loading && <LoadingOverlay />}
    </div>
  );
}

/** Unified loading overlay for async table/view fetches. */
export function LoadingOverlay({ className }: { className?: string }) {
  return (
    <div className={cn('absolute inset-0 z-10 grid cursor-wait place-items-center bg-background/45', className)}>
      <Spinner className="h-6 w-6" />
    </div>
  );
}

/** Standard bordered pagination footer for data views. */
export function PaginationFooter({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLElement>) {
  return (
    <footer
      className={cn(
        'flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-border bg-background px-4 py-2',
        className,
      )}
      {...props}
    >
      {children}
    </footer>
  );
}

/** Standard footer row for popovers with right-aligned action buttons. */
export function PopoverFooter({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex items-center justify-end gap-1.5 border-t border-border pt-2', className)}
      {...props}
    >
      {children}
    </div>
  );
}

/** Standard dashed-underline trigger for inline-editable table cells. */
export const InlineEditTrigger = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'ghost', size = 'xs', ...props }, ref) => (
    <Button
      ref={ref}
      variant={variant}
      size={size}
      className={cn(
        'h-auto rounded-none border-b border-dashed border-muted-foreground/60 px-0 py-0.5 text-[13px] font-normal text-foreground hover:border-foreground hover:bg-transparent',
        className,
      )}
      {...props}
    />
  ),
);
InlineEditTrigger.displayName = 'InlineEditTrigger';

export const TABLE_ACTION_REVEAL =
  'text-muted-foreground/60 opacity-50 transition-opacity hover:text-foreground group-hover:opacity-100 group-focus-within:opacity-100';

export const RAIL_ACTION_REVEAL =
  'text-muted-foreground opacity-25 transition-opacity hover:text-foreground group-hover:opacity-100 group-focus-within:opacity-100';

export interface IconActionButtonProps extends Omit<ButtonProps, 'aria-label'> {
  label: string;
  tooltip?: React.ReactNode;
  tooltipSide?: 'top' | 'right' | 'bottom' | 'left';
  reveal?: 'table' | 'rail';
}

/** Standard icon-only action button paired with a shadcn Tooltip and mandatory aria-label. */
export const IconActionButton = React.forwardRef<HTMLButtonElement, IconActionButtonProps>(
  ({ label, tooltip, tooltipSide = 'bottom', reveal, variant = 'ghost', size = 'icon-sm', className, ...props }, ref) => (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          ref={ref}
          variant={variant}
          size={size}
          aria-label={label}
          className={cn(
            reveal === 'table' && TABLE_ACTION_REVEAL,
            reveal === 'rail' && RAIL_ACTION_REVEAL,
            className,
          )}
          {...props}
        />
      </TooltipTrigger>
      <TooltipContent side={tooltipSide}>{tooltip ?? label}</TooltipContent>
    </Tooltip>
  ),
);
IconActionButton.displayName = 'IconActionButton';
