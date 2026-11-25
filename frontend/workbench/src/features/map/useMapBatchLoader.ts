import { useCallback, useEffect, useRef, useState } from 'react';
import { useWorkbench } from '@/app/WorkbenchContext';
import type { PageStepperKind } from '@/app/WorkbenchContext';
import { runWithConcurrency } from '@/lib/async';

export const BULK_MAP_CONFIRM_THRESHOLD = 50;

export interface PendingBulkMapConfirm {
  count: number;
  unitLabel: string;
  onConfirm(): void;
}

interface UseMapBatchLoaderOptions<TItem, TEntry> {
  kind: PageStepperKind;
  unitLabel: string;
  concurrency?: number;
  page: number;
  totalPages: number;
  getKey(item: TItem): string;
  fetchEntry(item: TItem, signal: AbortSignal): Promise<TEntry>;
  onCommitAdd(entries: Array<{ key: string; value: TEntry }>): void;
  onCommitReplace(entries: Array<{ key: string; value: TEntry }>, pageNumber?: number): void;
  fetchPage(targetPage: number): Promise<{ items: TItem[]; page: number }>;
  onError?(message: string): void;
}

export function useMapBatchLoader<TItem, TEntry>({
  kind,
  unitLabel,
  concurrency = 5,
  page,
  totalPages,
  getKey,
  fetchEntry,
  onCommitAdd,
  onCommitReplace,
  fetchPage,
  onError,
}: UseMapBatchLoaderOptions<TItem, TEntry>) {
  const wb = useWorkbench();
  const [addingProgress, setAddingProgress] = useState<{ done: number; total: number } | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<PendingBulkMapConfirm | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const pageSteppingRef = useRef(false);
  const mountedRef = useRef(true);

  const callbacksRef = useRef({
    getKey,
    fetchEntry,
    onCommitAdd,
    onCommitReplace,
    fetchPage,
    onError,
  });
  callbacksRef.current = { getKey, fetchEntry, onCommitAdd, onCommitReplace, fetchPage, onError };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  const runBatch = useCallback(
    async (
      items: TItem[],
      mode: 'add' | 'replace',
      pageNumber?: number,
    ): Promise<void> => {
      if (items.length === 0) {
        wb.dispatch({ type: 'status', value: `没有可加入地图的${unitLabel}` });
        return;
      }
      const controller = new AbortController();
      abortRef.current?.abort();
      abortRef.current = controller;

      const results = new Array<{ key: string; value: TEntry } | null>(items.length).fill(null);
      let done = 0;
      let failed = 0;
      setAddingProgress({ done: 0, total: items.length });

      try {
        await runWithConcurrency(
          items.map((item, index) => ({ item, index })),
          concurrency,
          async ({ item, index }) => {
            try {
              const value = await callbacksRef.current.fetchEntry(item, controller.signal);
              if (!mountedRef.current || controller.signal.aborted) return;
              results[index] = { key: callbacksRef.current.getKey(item), value };
            } catch (failure) {
              if ((failure as Error).name !== 'AbortError' && mountedRef.current) {
                failed += 1;
                const message = failure instanceof Error ? failure.message : `批量加载${unitLabel}失败`;
                callbacksRef.current.onError?.(message);
              }
            } finally {
              done += 1;
              if (mountedRef.current && !controller.signal.aborted) {
                setAddingProgress({ done, total: items.length });
              }
            }
          },
          controller.signal,
        );

        if (!mountedRef.current || controller.signal.aborted) return;
        const entries = results.filter(
          (entry): entry is { key: string; value: TEntry } => entry !== null,
        );
        if (entries.length === 0) {
          if (failed > 0) {
            wb.dispatch({ type: 'error', value: `批量加载${unitLabel}失败（${failed} 条失败）` });
          }
          return;
        }
        if (mode === 'replace') {
          callbacksRef.current.onCommitReplace(entries, pageNumber);
          const suffix = failed > 0 ? `（${failed} 条加载失败）` : '';
          wb.dispatch({
            type: 'status',
            value: pageNumber
              ? `已将第 ${pageNumber} 页 ${entries.length} 条${unitLabel}替换到地图${suffix}`
              : `已将 ${entries.length} 条${unitLabel}替换到地图${suffix}`,
          });
        } else {
          callbacksRef.current.onCommitAdd(entries);
          const suffix = failed > 0 ? `（${failed} 条加载失败）` : '';
          wb.dispatch({
            type: 'status',
            value: `已将 ${entries.length} 条${unitLabel}批量加入地图${suffix}`,
          });
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        if (mountedRef.current) {
          setAddingProgress(null);
          if (controller.signal.aborted) {
            wb.dispatch({ type: 'status', value: `已取消加载${unitLabel}` });
          }
        }
      }
    },
    [wb, unitLabel, concurrency],
  );

  const addItems = useCallback(
    (items: TItem[]) => {
      if (items.length === 0) return;
      if (items.length > BULK_MAP_CONFIRM_THRESHOLD) {
        setConfirmDialog({
          count: items.length,
          unitLabel,
          onConfirm: () => {
            setConfirmDialog(null);
            void runBatch(items, 'add');
          },
        });
        return;
      }
      void runBatch(items, 'add');
    },
    [unitLabel, runBatch],
  );

  const replaceItems = useCallback(
    (items: TItem[], pageNumber?: number) => runBatch(items, 'replace', pageNumber),
    [runBatch],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setAddingProgress(null);
  }, []);

  useEffect(() => {
    const handler = async (delta: -1 | 1) => {
      if (pageSteppingRef.current) return;
      if (totalPages <= 0) return;
      const targetPage = page + delta;
      if (targetPage < 1) {
        wb.dispatch({ type: 'status', value: `已是第一页${unitLabel}` });
        return;
      }
      if (targetPage > totalPages) {
        wb.dispatch({ type: 'status', value: `已是最后一页${unitLabel}` });
        return;
      }
      pageSteppingRef.current = true;
      try {
        const result = await callbacksRef.current.fetchPage(targetPage);
        if (!mountedRef.current) return;
        await runBatch(result.items, 'replace', result.page || targetPage);
      } catch (failure) {
        if (mountedRef.current) {
          wb.dispatch({
            type: 'error',
            value: failure instanceof Error ? failure.message : `翻页加载${unitLabel}失败`,
          });
        }
      } finally {
        pageSteppingRef.current = false;
      }
    };
    wb.registerPageStepper(kind, handler);
    return () => wb.registerPageStepper(kind, null);
  }, [wb, kind, unitLabel, page, totalPages, runBatch]);

  return {
    addingProgress,
    confirmDialog,
    dismissConfirm: () => setConfirmDialog(null),
    addItems,
    replaceItems,
    cancel,
  };
}
