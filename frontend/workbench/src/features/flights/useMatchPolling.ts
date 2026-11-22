import { useEffect, useRef } from 'react';
import { api } from '../../api/client';
import type { MapFlightEntry, MatchStatus } from '../../api/types';
import { useWorkbench } from '../../app/WorkbenchContext';

interface UseMatchPollingOptions {
  tracking: boolean;
  onProgress(progress: MatchStatus['progress']): void;
  onComplete(): Promise<unknown>;
  onStop(): void;
  onError(message: string): void;
}

export function useMatchPolling({
  tracking,
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
    if (!tracking) return;
    let cancelled = false;
    let timer = 0;
    let consecutiveErrors = 0;

    const poll = async () => {
      if (cancelled) return;
      try {
        const status = await api.matchStatus();
        if (cancelled) return;
        consecutiveErrors = 0;
        callbacksRef.current.onProgress(status.progress);

        for (const task of status.tasks) {
          for (const result of task.items) {
            const currentFlights = mapFlightsRef.current;
            if (!currentFlights.has(result.flight_key)) continue;
            const previous = currentFlights.get(result.flight_key)!;
            if (
              previous.geometry.match.status !== result.status ||
              previous.geometry.match.graph_id !== result.graph_id
            ) {
              const geometry = await api.geometry(result.flight_key);
              if (cancelled) return;
              const latest = mapFlightsRef.current.get(result.flight_key);
              if (latest) {
                dispatch({ type: 'map-flight', key: result.flight_key, value: { ...latest, geometry } });
              }
            }
          }
        }

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
  }, [tracking, dispatch]);
}
