import * as React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { DayPicker } from 'react-day-picker';
import { zhCN } from 'date-fns/locale';
import { cn } from '@/lib/utils';

export type CalendarProps = React.ComponentProps<typeof DayPicker>;

export function Calendar({ className, classNames, showOutsideDays = true, locale = zhCN, ...props }: CalendarProps) {
  return (
    <DayPicker
      locale={locale}
      showOutsideDays={showOutsideDays}
      className={cn('p-2.5 text-xs', className)}
      classNames={{
        months: 'flex flex-col gap-3 sm:flex-row',
        month: 'space-y-2.5',
        month_caption: 'relative flex h-7 items-center justify-center',
        caption_label: 'text-xs font-medium text-foreground',
        nav: 'absolute inset-x-0 top-0 flex h-7 items-center justify-between',
        button_previous:
          'inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-md border border-border bg-background text-muted-foreground hover:bg-accent hover:text-foreground',
        button_next:
          'inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-md border border-border bg-background text-muted-foreground hover:bg-accent hover:text-foreground',
        month_grid: 'w-full border-collapse',
        weekdays: 'flex',
        weekday: 'w-8 text-center text-[11px] font-normal text-muted-foreground',
        week: 'mt-1 flex w-full',
        day: 'relative h-8 w-8 p-0 text-center text-xs focus-within:relative focus-within:z-20',
        day_button:
          'inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md font-normal text-foreground tabular-nums transition-colors hover:bg-accent hover:text-foreground aria-selected:opacity-100',
        selected:
          '[&>button]:bg-primary [&>button]:text-primary-foreground [&>button]:hover:bg-primary [&>button]:hover:text-primary-foreground',
        range_start:
          'rounded-l-md bg-accent [&>button]:bg-primary [&>button]:text-primary-foreground [&>button]:hover:bg-primary [&>button]:hover:text-primary-foreground',
        range_end:
          'rounded-r-md bg-accent [&>button]:bg-primary [&>button]:text-primary-foreground [&>button]:hover:bg-primary [&>button]:hover:text-primary-foreground',
        range_middle:
          'bg-accent [&>button]:rounded-none [&>button]:bg-transparent [&>button]:text-foreground [&>button]:hover:bg-accent/80',
        today: '[&>button]:border [&>button]:border-primary/40 [&>button]:font-medium',
        outside: 'text-muted-foreground/50 [&>button]:text-muted-foreground/50',
        disabled: 'opacity-40 [&>button]:cursor-not-allowed',
        hidden: 'invisible',
        ...classNames,
      }}
      components={{
        Chevron: ({ orientation }) =>
          orientation === 'left' ? <ChevronLeft className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />,
      }}
      {...props}
    />
  );
}
