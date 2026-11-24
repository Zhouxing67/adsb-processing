import { useEffect, useRef, useState } from 'react';
import { Crosshair, Eye, FileText, GripHorizontal, LoaderCircle, Maximize2, Route, Trash2, X } from 'lucide-react';
import { api } from '@/api/client';
import type { FlightDetail, MapFlightEntry } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';

const colors = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#B77900', '#56B4E9', '#E69F00', '#6A3D9A', '#1B9E77', '#E7298A'];
const HEIGHT_STORAGE_KEY = 'airport-workbench.map-list-height';
const DEFAULT_HEIGHT_PCT = 58;
const MIN_HEIGHT_PCT = 20;
const MAX_HEIGHT_PCT = 85;

function readStoredHeight(): number {
  try {
    const value = Number(localStorage.getItem(HEIGHT_STORAGE_KEY));
    return Number.isFinite(value) && value >= MIN_HEIGHT_PCT && value <= MAX_HEIGHT_PCT ? value : DEFAULT_HEIGHT_PCT;
  } catch {
    return DEFAULT_HEIGHT_PCT;
  }
}

interface MapSelectionRailProps {
  submitMatches(keys: string[], force: boolean): Promise<void>;
  splitView: boolean;
  onDetail(detail: FlightDetail): void;
}

export function MapSelectionRail({ splitView, onDetail, submitMatches }: MapSelectionRailProps) {
  const wb = useWorkbench();
  const [listHeightPct, setListHeightPct] = useState<number>(readStoredHeight);
  const [flashingKey, setFlashingKey] = useState<string | null>(null);
  const [loadingDetailKey, setLoadingDetailKey] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<Set<string>>(new Set());
  const matchFlight = async (key: string, label: string) => {
    setSubmitting(current => new Set(current).add(key));
    try {
      await submitMatches([key], true);
      wb.dispatch({ type: 'status', value: `已提交 ${label} 的路径匹配` });
    } catch (failure) {
      wb.dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '匹配提交失败' });
    } finally {
      setSubmitting(current => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  };

  const railRef = useRef<HTMLElement>(null);
  const itemRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const dragRef = useRef<{ startY: number; startPct: number; railHeight: number } | null>(null);

  const updateHeight = (next: number) => {
    const clamped = Math.round(Math.max(MIN_HEIGHT_PCT, Math.min(MAX_HEIGHT_PCT, next)));
    setListHeightPct(clamped);
    try {
      localStorage.setItem(HEIGHT_STORAGE_KEY, String(clamped));
    } catch {
      /* storage is optional */
    }
  };

  useEffect(() => {
    const highlighted = wb.highlightedFlight;
    if (!highlighted) return;
    setFlashingKey(highlighted.key);
    const node = itemRefs.current.get(highlighted.key);
    node?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    const timer = window.setTimeout(() => {
      setFlashingKey(current => (current === highlighted.key ? null : current));
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [wb.highlightedFlight]);

  const updateMapEntry = (key: string, patch: Partial<MapFlightEntry>) => {
    const entry = wb.mapFlights.get(key);
    if (entry) wb.dispatch({ type: 'map-flight', key, value: { ...entry, ...patch } });
  };

  const openDetail = async (key: string) => {
    setLoadingDetailKey(key);
    try {
      const detail = await api.detail(key);
      onDetail(detail);
      wb.dispatch({ type: 'view', value: 'observations' });
    } catch (failure) {
      wb.dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '详情加载失败' });
    } finally {
      setLoadingDetailKey(current => (current === key ? null : current));
    }
  };

  const sortedFlights = [...wb.mapFlights].sort((a, b) => a[1].slot - b[1].slot);

  return (
    <aside
      ref={railRef}
      className="map-selection relative z-[900] col-start-1 row-start-2 flex h-full min-h-0 min-w-0 flex-col border-r border-border bg-muted"
    >
      <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-4">
        <div>
          <small className="block text-[11px] leading-tight font-medium text-muted-foreground">地图内容</small>
          <strong className="block text-[15px] leading-tight font-semibold text-foreground">地图展示</strong>
        </div>
        <span className="text-[11px] text-muted-foreground tabular-nums">{wb.mapFlights.size} 架航班</span>
      </div>

      <ScrollArea
        className="min-h-0 shrink-0 bg-background/55"
        style={{ height: `${listHeightPct}%` }}
      >
        <div className="divide-y divide-border/60 px-2 py-1">
          {wb.mapFlights.size === 0 && (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">尚无地图展示航班</p>
          )}
          {sortedFlights.map(([key, entry]) => {
            const isolated = wb.isolatedFlightKey === key;
            const highlighted = flashingKey === key;
            const slotColor = colors[entry.slot % colors.length];
            const hasPath = Boolean(entry.geometry.path);
            const match = entry.geometry.match;
            const matching = submitting.has(key) || match.status === 'queued' || match.status === 'matching';
            const matchLabel = matching ? '匹配中' : hasPath ? '重新匹配路径' : '匹配路径';
            return (
              <div
                key={key}
                ref={element => {
                  if (element) itemRefs.current.set(key, element);
                  else itemRefs.current.delete(key);
                }}
                data-highlighted={highlighted ? 'true' : undefined}
                className={cn(
                  'selected-chip group relative flex flex-col gap-1 rounded-md py-1.5 pl-3 pr-1.5 transition-all hover:bg-background',
                  isolated && 'bg-background shadow-2xs',
                  highlighted && 'bg-accent/80 ring-2 ring-primary/45',
                )}
              >
                <span
                  aria-hidden="true"
                  className="absolute bottom-1.5 left-1 top-1.5 w-[3px] rounded-full"
                  style={{ backgroundColor: slotColor }}
                />

                <div className="flex min-w-0 items-center gap-1.5">
                  <span className="w-4 shrink-0 text-[11px] font-medium text-muted-foreground tabular-nums">
                    {entry.slot + 1}
                  </span>
                  <span
                    className="min-w-0 flex-1 truncate text-[12px] font-medium text-foreground"
                    title={entry.label}
                  >
                    {entry.label}
                  </span>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      className={cn(
                        'flight-isolate-action h-5 w-5',
                        isolated
                          ? 'bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground'
                          : 'text-muted-foreground hover:text-foreground',
                      )}
                      aria-label={isolated ? '恢复全部航班' : `仅显示 ${entry.label}`}
                      aria-pressed={isolated}
                      title={isolated ? '恢复全部地图航班' : '仅显示此航班'}
                      onClick={() => wb.dispatch({ type: 'isolate-flight', key: isolated ? null : key })}
                    >
                      <Eye className="h-3 w-3" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      className={cn('h-5 w-5 text-muted-foreground', match.status === 'failed' && 'text-destructive')}
                      aria-label={`${matchLabel} ${entry.label}`}
                      title={match.status === 'failed' && !matching ? `上次匹配失败：${match.error ?? '未生成路径'}。点击重试` : matchLabel}
                      disabled={matching}
                      onClick={() => void matchFlight(key, entry.label)}
                    >
                      {matching ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Route className="h-3 w-3" />}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      className="flight-remove-action h-5 w-5 text-muted-foreground hover:text-destructive"
                      aria-label={`移除 ${entry.label}`}
                      title="移出地图"
                      onClick={() => wb.dispatch({ type: 'map-flight', key, value: null })}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                </div>

                <div className="flex items-center justify-between gap-1 pl-5">
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={entry.trajectoryVisible}
                      aria-label={`${entry.label} 轨迹`}
                      title="显示/隐藏原始轨迹"
                      className={cn(
                        'inline-flex h-5 items-center rounded px-1.5 text-[11px] transition-colors cursor-pointer',
                        entry.trajectoryVisible
                          ? 'bg-zinc-900/10 font-medium text-zinc-900'
                          : 'bg-transparent text-zinc-400 hover:bg-zinc-900/5 hover:text-zinc-600',
                      )}
                      onClick={() => updateMapEntry(key, { trajectoryVisible: !entry.trajectoryVisible })}
                    >
                      轨迹
                    </button>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={entry.pathVisible}
                      aria-label={`${entry.label} 路径`}
                      title={hasPath ? '显示/隐藏匹配路径' : '尚无匹配路径'}
                      disabled={!hasPath}
                      className={cn(
                        'inline-flex h-5 items-center rounded px-1.5 text-[11px] transition-colors',
                        !hasPath
                          ? 'cursor-not-allowed bg-transparent text-zinc-300 opacity-50'
                          : entry.pathVisible
                            ? 'cursor-pointer bg-zinc-900/10 font-medium text-zinc-900'
                            : 'cursor-pointer bg-transparent text-zinc-400 hover:bg-zinc-900/5 hover:text-zinc-600',
                      )}
                      onClick={() => hasPath && updateMapEntry(key, { pathVisible: !entry.pathVisible })}
                    >
                      路径
                    </button>
                  </div>

                  <div className="flex items-center gap-0.5">
                    <button
                      type="button"
                      className="inline-flex h-5 cursor-pointer items-center gap-0.5 rounded px-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-zinc-900/5 hover:text-foreground"
                      title="在地图中定位此航班"
                      onClick={() => wb.dispatch({ type: 'focus-flight', key, preserveView: splitView })}
                    >
                      <Crosshair className="h-3 w-3" />
                      定位
                    </button>
                    <button
                      type="button"
                      disabled={loadingDetailKey === key}
                      className="inline-flex h-5 cursor-pointer items-center gap-0.5 rounded px-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-zinc-900/5 hover:text-foreground disabled:opacity-50"
                      title="查看原始观测记录"
                      onClick={() => void openDetail(key)}
                    >
                      <FileText className="h-3 w-3" />
                      详情
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </ScrollArea>

      <button
        type="button"
        role="separator"
        aria-orientation="horizontal"
        aria-label="调整地图展示列表高度"
        aria-valuemin={MIN_HEIGHT_PCT}
        aria-valuemax={MAX_HEIGHT_PCT}
        aria-valuenow={listHeightPct}
        title="上下拖动调整列表高度 · 双击恢复默认"
        className="group flex h-2.5 shrink-0 cursor-row-resize items-center justify-center border-y border-border bg-muted/80 text-muted-foreground/50 transition-colors hover:bg-accent hover:text-muted-foreground focus-visible:bg-accent focus-visible:outline-none"
        onPointerDown={event => {
          const railHeight = railRef.current?.getBoundingClientRect().height || 600;
          dragRef.current = { startY: event.clientY, startPct: listHeightPct, railHeight };
          event.currentTarget.setPointerCapture(event.pointerId);
          event.preventDefault();
        }}
        onPointerMove={event => {
          if (!dragRef.current || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
          const deltaPct = ((event.clientY - dragRef.current.startY) / dragRef.current.railHeight) * 100;
          updateHeight(dragRef.current.startPct + deltaPct);
        }}
        onPointerUp={event => {
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
          dragRef.current = null;
        }}
        onLostPointerCapture={() => {
          dragRef.current = null;
        }}
        onDoubleClick={() => updateHeight(DEFAULT_HEIGHT_PCT)}
        onKeyDown={event => {
          if (event.key === 'ArrowUp') {
            event.preventDefault();
            updateHeight(listHeightPct - 5);
          } else if (event.key === 'ArrowDown') {
            event.preventDefault();
            updateHeight(listHeightPct + 5);
          } else if (event.key === 'Home') {
            event.preventDefault();
            updateHeight(DEFAULT_HEIGHT_PCT);
          }
        }}
      >
        <GripHorizontal className="h-3 w-3" />
      </button>

      <div className="flex shrink-0 items-center justify-between px-4 py-2 text-[11px] text-muted-foreground">
        <span className="tabular-nums">已显示 {wb.mapFlights.size} 架航班</span>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="xs"
            className="h-6 px-2 text-[11px] text-muted-foreground hover:text-foreground"
            disabled={!wb.mapFlights.size}
            title="缩放地图以显示全部已加入航班"
            onClick={() => wb.dispatch({ type: 'fit-map-flights', preserveView: splitView })}
          >
            <Maximize2 className="h-3 w-3" />
            适配全部
          </Button>
          <Button
            variant="ghost"
            size="xs"
            className="h-6 px-2 text-[11px] text-muted-foreground hover:text-destructive"
            disabled={!wb.mapFlights.size}
            onClick={() => wb.dispatch({ type: 'clear-map-flights' })}
          >
            <Trash2 className="h-3 w-3" />
            清空
          </Button>
        </div>
      </div>
    </aside>
  );
}
