import { useEffect, useRef } from 'react';
import { api } from '../../api/client';
import type { MapFlightEntry, MatchStatus } from '../../api/types';
import { useWorkbench } from '../../app/WorkbenchContext';

interface UseMatchPollingOptions {
  matchRun: string;
  onProgress(progress: MatchStatus['progress']): void;
  onComplete(): Promise<unknown>;
  onStop(): void;
  onError(message: string): void;
}

export function useMatchPolling({
  matchRun,
  onProgress,
  onComplete,
  onStop,
  onError,
}: UseMatchPollingOptions) {
  const wb = useWorkbench();
  const mapFlightsRef = useRef<Map<string, MapFlightEntry>>(wb.mapFlights);
  mapFlightsRef.current = wb.mapFlights;

  const callbacksRef = useRef({ onProgress, onComplete, onStop, onError });
  callbacksRef.current = { onProgress, onComplete, onStop, onError };

  const dispatch = wb.dispatch;

  useEffect(() => {
    if (!matchRun) return;
    let cancelled = false;
    let timer = 0;
    let consecutiveErrors = 0;

    const poll = async () => {
      if (cancelled) return;
      try {
        const trackedKeys = [...mapFlightsRef.current.keys()];
        const status = await api.matchStatus({
          include_items: false,
          flight_key: trackedKeys.length ? trackedKeys : undefined,
        });
        if (cancelled) return;
        callbacksRef.current.onProgress(status.progress);

        const latestResults = new Map(status.tasks.flatMap(task =>
          task.items.map(result => [result.flight_key, result] as const)));
        for (const result of latestResults.values()) {
          const previous = mapFlightsRef.current.get(result.flight_key);
          if (!previous) continue;
          if (previous.geometry.match.status === result.status && previous.geometry.match.task_id === result.task_id) continue;
          const geometry = await api.geometry(result.flight_key);
          if (cancelled) return;
          const latest = mapFlightsRef.current.get(result.flight_key);
          if (latest) {
            dispatch({ type: 'map-flight', key: result.flight_key, value: { ...latest, geometry } });
          }
        }

        consecutiveErrors = 0;
        if (status.progress.complete) {
          callbacksRef.current.onStop();
          await callbacksRef.current.onComplete();
          return;
        }
      } catch (failure) {
        if (cancelled) return;
        consecutiveErrors += 1;
        const message = failure instanceof Error ? failure.message : '任务状态读取失败';
        if (consecutiveErrors >= 3) {
          callbacksRef.current.onStop();
          callbacksRef.current.onError(`${message}（已停止轮询，请稍后重试）`);
          return;
        }
        callbacksRef.current.onError(message);
      }
      if (!cancelled) {
        timer = window.setTimeout(() => {
          void poll();
        }, 1000);
      }
    };

    timer = window.setTimeout(() => {
      void poll();
    }, 1000);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [matchRun, dispatch]);
}
