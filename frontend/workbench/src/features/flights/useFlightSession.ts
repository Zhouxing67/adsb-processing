import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/api/client';
import type { FlightDetail, MapFlightEntry, MatchStatus } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { runWithConcurrency } from '@/lib/async';
import { patchStoredFlightState, readStoredFlightState } from './storage';
import { useMatchPolling } from './useMatchPolling';

export function useFlightSession(enabled: boolean) {
  const wb = useWorkbench();
  const dispatch = wb.dispatch;
  const saved = useMemo(readStoredFlightState, []);
  const [detail, setDetail] = useState<FlightDetail | null>(null);
  const [matchRun, setMatchRun] = useState('');
  const [progress, setProgress] = useState<MatchStatus['progress'] | null>(null);
  const restoredRef = useRef(false);
  const restoreCompleteRef = useRef(false);

  const submitMatches = useCallback(async (keys: string[], force: boolean) => {
    const result = await api.submitMatches(keys, force);
    setMatchRun(result.task_id);
  }, []);

  const openFlightDetail = useCallback(
    async (flightKey: string, onError?: (message: string) => void) => {
      try {
        const loaded = await api.detail(flightKey);
        setDetail(loaded);
        dispatch({ type: 'view', value: 'observations' });
      } catch (failure) {
        const message = failure instanceof Error ? failure.message : '详情加载失败';
        if (onError) onError(message);
        else dispatch({ type: 'error', value: message });
      }
    },
    [dispatch],
  );

  useEffect(() => {
    if (!enabled || !restoreCompleteRef.current) return;
    const displayed = [...wb.mapFlights].map(([key, entry]) => ({
      key,
      label: entry.label,
      slot: entry.slot,
      trajectoryVisible: entry.trajectoryVisible,
      pathVisible: entry.pathVisible,
    }));
    patchStoredFlightState({ matchSelection: [...wb.matchSelection], displayed });
  }, [enabled, wb.mapFlights, wb.matchSelection]);

  useEffect(() => {
    if (!enabled || restoredRef.current) return;
    restoredRef.current = true;
    const controller = new AbortController();

    void (async () => {
      const valid = new Set((await api.filteredFlights({})).flight_keys);
      if (controller.signal.aborted) return;
      dispatch({ type: 'prune-match-selection', keys: [...valid] });

      const displayed = (saved.displayed ?? []).filter(item => valid.has(item.key));
      const restoredEntries: Array<{ key: string; value: MapFlightEntry }> = [];
      await runWithConcurrency(
        displayed,
        5,
        async item => {
          try {
            const geometry = await api.geometry(item.key, controller.signal);
            if (controller.signal.aborted) return;
            restoredEntries.push({
              key: item.key,
              value: {
                geometry,
                label: item.label || geometry.flight_id,
                slot: item.slot,
                trajectoryVisible: item.trajectoryVisible,
                pathVisible: item.pathVisible,
              },
            });
          } catch {
            /* stale saved selection or aborted */
          }
        },
        controller.signal,
      );
      if (!controller.signal.aborted) {
        restoreCompleteRef.current = true;
        if (restoredEntries.length) {
          dispatch({ type: 'map-flights-batch', entries: restoredEntries });
        }
      }

      const status = await api.matchStatus();
      if (controller.signal.aborted) return;
      setProgress(status.progress);
      if (!status.progress.complete) {
        setMatchRun(status.tasks.at(-1)?.task_id || 'restored');
      }
    })().catch(failure => {
      restoreCompleteRef.current = true;
      if ((failure as Error).name !== 'AbortError') {
        dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '会话恢复失败' });
      }
    });

    return () => {
      controller.abort();
    };
  }, [enabled, saved, dispatch]);

  const handleComplete = useCallback(async () => {
    dispatch({ type: 'flights-updated' });
  }, [dispatch]);

  const handleStop = useCallback(() => {
    setMatchRun('');
  }, []);

  const handleError = useCallback(
    (message: string) => {
      dispatch({ type: 'error', value: message });
    },
    [dispatch],
  );

  useMatchPolling({
    matchRun: enabled ? matchRun : '',
    onProgress: setProgress,
    onComplete: handleComplete,
    onStop: handleStop,
    onError: handleError,
  });

  return {
    detail,
    openFlightDetail,
    matchRun,
    tracking: Boolean(matchRun),
    progress,
    submitMatches,
  };
}
