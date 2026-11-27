interface NetworkLegendProps {
  showOdBoundary: boolean;
}

export function NetworkLegend({ showOdBoundary }: NetworkLegendProps) {
  return (
    <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border/80 bg-background/90 px-2.5 py-1.5 text-[11px] text-muted-foreground shadow-2xs backdrop-blur-xs">
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-2 w-3.5 rounded-xs bg-slate-200 ring-1 ring-slate-300" />
        跑道
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-0.5 w-3.5 bg-slate-300" />
        滑行道
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-2 w-2 rounded-full bg-accent-teal" />
        机位
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-2 w-2 rounded-full bg-accent-amber" />
        跑道接口
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-foreground" />
        观测点
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-0.5 w-3.5 rounded-full bg-primary" />
        匹配路径
      </span>
      {showOdBoundary && (
        <>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-3 rounded-xs bg-accent-teal/25" />
            OD 起点
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-3 rounded-xs bg-accent-amber/25" />
            OD 终点
          </span>
        </>
      )}
    </div>
  );
}
