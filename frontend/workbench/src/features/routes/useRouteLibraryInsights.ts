import { useCallback, useMemo, useState } from 'react';
import type { MutableRefObject } from 'react';
import { api } from '@/api/client';
import type { DetectRouteAnomaliesRequest, RouteAnomalyResult } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';

interface UseRouteLibraryInsightsOptions {
  mountedRef: MutableRefObject<boolean>;
  onReloadRoutes(): Promise<void>;
}

export function useRouteLibraryInsights({
  mountedRef,
  onReloadRoutes,
}: UseRouteLibraryInsightsOptions) {
  const wb = useWorkbench();
  const [anomalyResult, setAnomalyResult] = useState<RouteAnomalyResult | null>(null);
  const [detectingAnomalies, setDetectingAnomalies] = useState(false);
  const [rejectingAnomalies, setRejectingAnomalies] = useState(false);

  const detectAnomalies = useCallback(
    async (payload: DetectRouteAnomaliesRequest) => {
      if (payload.route_ids && payload.route_ids.length === 0) return;
      setDetectingAnomalies(true);
      try {
        const result = await api.detectRouteAnomalies(payload);
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
        wb.dispatch({ type: 'routes-updated' });
        void onReloadRoutes();
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
    [mountedRef, onReloadRoutes, wb],
  );

  const anomalousIdSet = useMemo(
    () => new Set((anomalyResult?.items ?? []).map(item => item.route_id)),
    [anomalyResult],
  );

  const dismissAnomalies = useCallback(() => setAnomalyResult(null), []);

  return {
    anomalyResult,
    anomalousIdSet,
    detectingAnomalies,
    rejectingAnomalies,
    detectAnomalies,
    rejectAnomalies,
    dismissAnomalies,
  };
}
