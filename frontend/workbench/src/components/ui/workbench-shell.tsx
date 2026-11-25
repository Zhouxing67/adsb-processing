import * as React from 'react';
import { cn } from '@/lib/utils';
import { Button } from './button';
import type { ButtonProps } from './button';
import { Input } from './input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './select';
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

export interface TablePaginationProps {
  page: number;
  totalPages: number;
  totalItems: number;
  itemLabel?: string;
  pageSize?: number;
  pageSizeOptions?: readonly number[];
  disabled?: boolean;
  onPageChange(nextPage: number): void;
  onPageSizeChange?(nextSize: number): void;
}

const DEFAULT_PAGE_SIZE_OPTIONS = [20, 50, 100] as const;

/** Shared table pagination controls with first/prev/jump/next/last buttons and optional page-size selector. */
export function TablePagination({
  page,
  totalPages,
  totalItems,
  itemLabel = '条',
  pageSize,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  disabled = false,
  onPageChange,
  onPageSizeChange,
}: TablePaginationProps) {
  const safeTotalPages = Math.max(0, totalPages);
  const [draft, setDraft] = React.useState(String(page));
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    setDraft(String(page));
    setError('');
  }, [page]);

  const jump = () => {
    const value = Number(draft);
    if (!Number.isSafeInteger(value) || value < 1 || safeTotalPages < 1 || value > safeTotalPages) {
      setError(`页码范围为 1～${Math.max(1, safeTotalPages)}`);
      return;
    }
    setError('');
    if (value !== page) onPageChange(value);
  };

  const atFirst = disabled || page <= 1;
  const atLast = disabled || safeTotalPages <= 1 || page >= safeTotalPages;

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-muted-foreground tabular-nums">
          共 {totalItems} {itemLabel}
          {safeTotalPages > 0 ? ` · 第 ${page} / ${safeTotalPages} 页` : ''}
        </span>
        {pageSize !== undefined && onPageSizeChange && (
          <Select
            value={String(pageSize)}
            disabled={disabled}
            onValueChange={value => {
              const nextSize = Number(value);
              if (Number.isSafeInteger(nextSize) && nextSize > 0 && nextSize !== pageSize) {
                onPageSizeChange(nextSize);
              }
            }}
          >
            <SelectTrigger aria-label="每页条数" className="h-7 w-[92px] text-xs tabular-nums">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {pageSizeOptions.map(option => (
                <SelectItem key={option} value={String(option)}>
                  {option} 条/页
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Button variant="outline" size="sm" disabled={atFirst} onClick={() => onPageChange(1)}>
          首页
        </Button>
        <Button variant="outline" size="sm" disabled={atFirst} onClick={() => onPageChange(Math.max(1, page - 1))}>
          上一页
        </Button>
        <Input
          type="number"
          min={1}
          max={Math.max(1, safeTotalPages)}
          value={draft}
          disabled={disabled || safeTotalPages <= 1}
          aria-label="跳转页码"
          className="h-7 w-16 text-center text-xs tabular-nums"
          onChange={event => setDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') jump();
          }}
        />
        <Button variant="outline" size="sm" disabled={disabled || safeTotalPages <= 1} onClick={jump}>
          跳转
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={atLast}
          onClick={() => onPageChange(Math.min(safeTotalPages, page + 1))}
        >
          下一页
        </Button>
        <Button variant="outline" size="sm" disabled={atLast} onClick={() => onPageChange(safeTotalPages)}>
          尾页
        </Button>
        {error && <p className="m-0 text-xs text-destructive">{error}</p>}
      </div>
    </>
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
