import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Crosshair, X } from 'lucide-react';
import { api } from '@/api/client';
import type { FlightDetail } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Empty, EmptyDescription } from '@/components/ui/empty';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  DataTableContainer,
  FilterBar,
  IconActionButton,
  PaginationFooter,
  ViewHeader,
} from '@/components/ui/workbench-shell';

interface ObservationViewProps {
  detail: FlightDetail | null;
  splitView: boolean;
}

const COLUMN_LABELS: Record<string, string> = {
  record_index: '序号',
  timestamp: '时间',
  longitude: '经度',
  latitude: '纬度',
  altitude: '高度',
  groundspeed: '地速',
  track: '航向',
  vertical_rate: '垂直速度',
  icao24: 'ICAO24',
  callsign: '呼号',
  flight_id: '航班 ID',
  flight_number: '航班号',
  onground: '接地',
};

function formatObservationCell(column: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const key = column.toLowerCase();
  if (key.includes('time') && typeof value === 'string') {
    return value.replace('T', ' ').replace(/(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/, '');
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (key === 'longitude' || key === 'lon' || key === 'latitude' || key === 'lat') {
      return value.toFixed(5);
    }
    if (Number.isInteger(value)) return String(value);
    return Number(value.toFixed(2)).toString();
  }
  return String(value);
}

export function ObservationView({ detail, splitView }: ObservationViewProps) {
  const wb = useWorkbench();
  const [current, setCurrent] = useState(detail);
  const [allFields, setAllFields] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const loadAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    loadAbortRef.current?.abort();
    loadAbortRef.current = null;
    setCurrent(detail);
    setAllFields(Boolean(detail?.all_fields));
    setLoading(false);
    setError('');
    return () => {
      loadAbortRef.current?.abort();
    };
  }, [detail]);

  if (!detail) {
    return (
      <section className="main-view observations-view absolute inset-0 flex h-full w-full items-center justify-center bg-background">
        <Empty>
          <EmptyDescription>请从航班目录打开详情。</EmptyDescription>
        </Empty>
      </section>
    );
  }
  if (!current) return null;

  const load = async (page: number, expanded = allFields) => {
    const controller = new AbortController();
    loadAbortRef.current?.abort();
    loadAbortRef.current = controller;
    setLoading(true);
    setError('');
    try {
      const value = await api.detail(detail.summary.flight_key, page, expanded, controller.signal);
      if (controller.signal.aborted) return;
      setCurrent(value);
      setAllFields(expanded);
    } catch (failure) {
      if ((failure as Error).name !== 'AbortError') {
        setError(failure instanceof Error ? failure.message : '观测记录加载失败');
      }
    } finally {
      if (loadAbortRef.current === controller) {
        loadAbortRef.current = null;
        setLoading(false);
      }
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
    <section className="main-view observations-view absolute inset-0 flex h-full w-full min-h-0 min-w-0 flex-col overflow-hidden bg-background">
      <ViewHeader className="gap-3">
        <Button variant="outline" size="sm" onClick={() => wb.dispatch({ type: 'view', value: 'flights' })}>
          <ArrowLeft className="h-3.5 w-3.5" />
          航班列表
        </Button>
        <div className="flex min-w-0 flex-1 items-baseline gap-2">
          <h2 className="m-0 truncate text-[15px] font-semibold text-foreground">
            {current.summary.flight_number || current.summary.flight_id}
          </h2>
          <span className="text-xs text-muted-foreground tabular-nums">{current.observation_total} 个观测点</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={!wb.observationLocation}
          onClick={() => wb.dispatch({ type: 'observation-location', value: null, preserveView: splitView })}
        >
          <X className="h-3.5 w-3.5" />
          清除定位点
        </Button>
      </ViewHeader>

      <FilterBar className="py-2">
        <div className="flex items-center justify-between gap-2">
          <Button variant="outline" size="sm" disabled={loading} onClick={() => void load(1, !allFields)}>
            {allFields ? '显示默认字段' : '显示全部字段'}
          </Button>
        </div>
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </FilterBar>

      <DataTableContainer loading={loading} className="observations-content">
        <Table className="min-w-[680px]">
          <TableHeader>
            <TableRow className="bg-muted hover:bg-muted">
              {current.observation_columns.map((column, columnIndex) => (
                <TableHead
                  key={column}
                  className={columnIndex === 0 ? 'left-0 z-[3] border-r border-border/70' : undefined}
                >
                  {COLUMN_LABELS[column.toLowerCase()] ?? column}
                </TableHead>
              ))}
              <TableHead className="right-0 z-[3] border-l border-border/70">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {current.observations.map((row, index) => (
              <TableRow key={index} className="group">
                {current.observation_columns.map((column, columnIndex) => (
                  <TableCell
                    key={column}
                    className={
                      columnIndex === 0
                        ? 'sticky left-0 z-[1] border-r border-border/60 bg-background tabular-nums group-hover:bg-muted'
                        : 'tabular-nums'
                    }
                  >
                    {formatObservationCell(column, row[column])}
                  </TableCell>
                ))}
                <TableCell className="sticky right-0 z-[1] border-l border-border/60 bg-background group-hover:bg-muted">
                  <IconActionButton
                    reveal="table"
                    label="在地图中定位"
                    tooltipSide="left"
                    onClick={() => locate(row)}
                  >
                    <Crosshair className="h-3.5 w-3.5" />
                  </IconActionButton>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableContainer>

      <PaginationFooter>
        <span className="text-xs text-muted-foreground tabular-nums">
          共 {current.observation_total} 条 · 第 {current.observation_page || 0} / {current.observation_pages} 页
        </span>
        <div className="flex items-center gap-1.5">
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
      </PaginationFooter>
    </section>
  );
}
