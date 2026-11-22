import { useEffect, useState } from 'react';
import { ArrowLeft, Crosshair, X } from 'lucide-react';
import { api } from '@/api/client';
import type { FlightDetail } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';

interface ObservationViewProps {
  detail: FlightDetail | null;
  splitView: boolean;
}

export function ObservationView({ detail, splitView }: ObservationViewProps) {
  const wb = useWorkbench();
  const [current, setCurrent] = useState(detail);
  const [allFields, setAllFields] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setCurrent(detail);
    setAllFields(Boolean(detail?.all_fields));
    setError('');
  }, [detail]);

  if (!detail) {
    return (
      <section className="main-view observations-view absolute inset-0 flex h-full w-full items-center justify-center bg-background">
        <p className="text-xs text-muted-foreground">请从航班目录打开详情。</p>
      </section>
    );
  }
  if (!current) return null;

  const load = async (page: number, expanded = allFields) => {
    setLoading(true);
    setError('');
    try {
      const value = await api.detail(detail.summary.flight_key, page, expanded);
      setCurrent(value);
      setAllFields(expanded);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '观测记录加载失败');
    } finally {
      setLoading(false);
    }
  };

  const locate = (row: Record<string, unknown>) => {
    const find = (...names: string[]) => {
      const key = Object.keys(row).find(item => names.includes(item.toLowerCase()));
      return key ? row[key] : undefined;
    };
    const longitude = Number(find('longitude', 'lon'));
    const latitude = Number(find('latitude', 'lat'));
    if (Number.isFinite(longitude) && Number.isFinite(latitude)) {
      wb.dispatch({ type: 'observation-location', value: [latitude, longitude], preserveView: splitView });
    }
  };

  return (
    <section className="main-view observations-view absolute inset-0 flex h-full w-full flex-col bg-background">
      <header className="flex shrink-0 items-center gap-4 border-b border-border px-4 py-2.5">
        <Button variant="outline" size="sm" onClick={() => wb.dispatch({ type: 'view', value: 'flights' })}>
          <ArrowLeft className="h-3.5 w-3.5" />
          航班列表
        </Button>
        <div className="min-w-0 flex-1">
          <small className="block text-[11px] text-muted-foreground">当前查看航班</small>
          <div className="flex items-baseline gap-2">
            <h2 className="m-0 truncate text-[15px] font-semibold text-foreground">
              {current.summary.flight_number || current.summary.flight_id}
            </h2>
            <p className="m-0 text-xs text-muted-foreground tabular-nums">{current.observation_total} 个观测点</p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={!wb.observationLocation}
          onClick={() => wb.dispatch({ type: 'observation-location', value: null, preserveView: splitView })}
        >
          <X className="h-3.5 w-3.5" />
          清除地图定位点
        </Button>
      </header>

      <div className="observations-content relative flex min-h-0 flex-1 flex-col overflow-hidden p-4">
        <div className="mb-3 flex shrink-0 items-center justify-between gap-2">
          <Button variant="outline" size="sm" disabled={loading} onClick={() => void load(1, !allFields)}>
            {allFields ? '显示默认字段' : '显示全部字段'}
          </Button>
          <span className="text-xs text-muted-foreground tabular-nums">
            第 {current.observation_page || 0} / {current.observation_pages} 页，共 {current.observation_total} 条
          </span>
        </div>

        {error && (
          <p className="mb-2 shrink-0 text-xs text-destructive" role="alert">
            {error}
          </p>
        )}

        <div className="min-h-0 flex-1 overflow-auto rounded-md border border-border">
          <table className="sheet-table w-full min-w-[680px] border-collapse text-left">
            <thead>
              <tr className="border-b border-border bg-muted text-xs font-medium text-muted-foreground">
                {current.observation_columns.map((column, columnIndex) => (
                  <th
                    key={column}
                    className={
                      columnIndex === 0
                        ? 'sticky left-0 top-0 z-[3] border-r border-border/70 bg-muted px-3 py-2 whitespace-nowrap'
                        : 'sticky top-0 z-[2] bg-muted px-3 py-2 whitespace-nowrap'
                    }
                  >
                    {column}
                  </th>
                ))}
                <th className="sticky right-0 top-0 z-[3] border-l border-border/70 bg-muted px-3 py-2 whitespace-nowrap">
                  操作
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/70">
              {current.observations.map((row, index) => (
                <tr key={index} className="group hover:bg-muted/40">
                  {current.observation_columns.map((column, columnIndex) => (
                    <td
                      key={column}
                      className={
                        columnIndex === 0
                          ? 'sticky left-0 z-[1] border-r border-border/60 bg-background px-3 py-2 whitespace-nowrap text-[13px] tabular-nums group-hover:bg-[#f8fafc]'
                          : 'px-3 py-2 whitespace-nowrap text-[13px] tabular-nums'
                      }
                    >
                      {String(row[column] ?? '—')}
                    </td>
                  ))}
                  <td className="sticky right-0 z-[1] border-l border-border/60 bg-background px-3 py-2 whitespace-nowrap group-hover:bg-[#f8fafc]">
                    <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => locate(row)}>
                      <Crosshair className="h-3.5 w-3.5" />
                      在地图中定位
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-3 flex shrink-0 items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={loading || current.observation_page <= 1}
            onClick={() => void load(current.observation_page - 1)}
          >
            上一页
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={loading || current.observation_page >= current.observation_pages}
            onClick={() => void load(current.observation_page + 1)}
          >
            下一页
          </Button>
        </div>

        {loading && (
          <div className="absolute inset-0 z-10 grid cursor-wait place-items-center bg-white/40">
            <span className="h-6 w-6 animate-spin rounded-full border-[3px] border-zinc-200 border-t-zinc-900" />
          </div>
        )}
      </div>
    </section>
  );
}
