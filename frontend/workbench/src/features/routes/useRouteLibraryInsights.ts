import { useCallback, useEffect, useMemo, useState } from 'react';
import type { MutableRefObject } from 'react';
import { api } from '@/api/client';
import type { RouteAnomalyResult, RouteCoverage } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';

interface UseRouteLibraryInsightsOptions {
  active: boolean;
  mountedRef: MutableRefObject<boolean>;
  onReloadRoutes(): Promise<void>;
}

export function useRouteLibraryInsights({
  active,
  mountedRef,
  onReloadRoutes,
}: UseRouteLibraryInsightsOptions) {
  const wb = useWorkbench();
  const [coverage, setCoverage] = useState<RouteCoverage | null>(null);
  const [anomalyResult, setAnomalyResult] = useState<RouteAnomalyResult | null>(null);
  const [detectingAnomalies, setDetectingAnomalies] = useState(false);
  const [rejectingAnomalies, setRejectingAnomalies] = useState(false);

  const loadCoverage = useCallback(async (signal?: AbortSignal) => {
    try {
      const summary = await api.routeCoverage(signal);
      if (mountedRef.current) setCoverage(summary);
    } catch (failure) {
      if ((failure as Error).name !== 'AbortError' && mountedRef.current) {
        setCoverage(null);
      }
    }
  }, [mountedRef]);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    void loadCoverage(controller.signal);
    return () => controller.abort();
  }, [active, loadCoverage, wb.routeLibraryVersion]);

  const detectAnomalies = useCallback(
    async (routeIds: string[]) => {
      if (!routeIds.length) return;
      setDetectingAnomalies(true);
      try {
        const result = await api.detectRouteAnomalies(routeIds);
        if (!mountedRef.current) return;
        setAnomalyResult(result);
        wb.dispatch({
          type: 'status',
          value:
            result.anomalous_count > 0
              ? `异常检测完成：${result.checked_count} 条中发现 ${result.anomalous_count} 条明显异常`
              : `异常检测完成：${result.checked_count} 条路径未发现明显异常`,
        });
      } catch (failure) {
        if (mountedRef.current) {
          wb.dispatch({
            type: 'error',
            value: failure instanceof Error ? failure.message : '异常检测失败',
          });
        }
      } finally {
        if (mountedRef.current) setDetectingAnomalies(false);
      }
    },
    [mountedRef, wb],
  );

  const rejectAnomalies = useCallback(
    async (routeIds: string[]) => {
      if (!routeIds.length) return;
      setRejectingAnomalies(true);
      try {
        const summary = await api.batchUpdateRouteReview(routeIds, 'rejected', '异常检测驳回');
        if (!mountedRef.current) return;
        const rejectedSet = new Set(summary.route_ids);
        setAnomalyResult(current =>
          current
            ? {
                ...current,
                items: current.items.map(item =>
                  rejectedSet.has(item.route_id) ? { ...item, status: 'rejected' } : item,
                ),
              }
            : current,
        );
        wb.dispatch({ type: 'status', value: `已批量驳回 ${summary.updated_count} 条异常路径` });
        void onReloadRoutes();
        void loadCoverage();
      } catch (failure) {
        if (mountedRef.current) {
          wb.dispatch({
            type: 'error',
            value: failure instanceof Error ? failure.message : '批量驳回失败',
          });
        }
      } finally {
        if (mountedRef.current) setRejectingAnomalies(false);
      }
    },
    [loadCoverage, mountedRef, onReloadRoutes, wb],
  );

  const anomalousIdSet = useMemo(
    () => new Set((anomalyResult?.items ?? []).map(item => item.route_id)),
    [anomalyResult],
  );

  const dismissAnomalies = useCallback(() => setAnomalyResult(null), []);

  return {
    coverage,
    loadCoverage,
    anomalyResult,
    anomalousIdSet,
    detectingAnomalies,
    rejectingAnomalies,
    detectAnomalies,
    rejectAnomalies,
    dismissAnomalies,
  };
}
