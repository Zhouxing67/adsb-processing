import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/api/client';
import type { RouteItem } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import type { MapRouteInput } from '@/app/WorkbenchContext';
import { runWithConcurrency } from '@/lib/async';

interface UseRouteBatchSelectionOptions {
  items: RouteItem[];
  splitView: boolean;
  labelFor(item: RouteItem): string;
}

export function useRouteBatchSelection({ items, splitView, labelFor }: UseRouteBatchSelectionOptions) {
  const wb = useWorkbench();
  const [selectedRoutes, setSelectedRoutes] = useState<Map<string, RouteItem>>(() => new Map());
  const [addingProgress, setAddingProgress] = useState<{ done: number; total: number } | null>(null);
  const batchAbortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const prevLibraryVersionRef = useRef(wb.routeLibraryVersion);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      batchAbortRef.current?.abort();
    };
  }, []);

  // Clear cross-page selection when the underlying route library version changes (e.g. re-import).
  useEffect(() => {
    if (prevLibraryVersionRef.current !== wb.routeLibraryVersion) {
      prevLibraryVersionRef.current = wb.routeLibraryVersion;
      setSelectedRoutes(new Map());
    }
  }, [wb.routeLibraryVersion]);

  // Keep cached selected RouteItem entries fresh as pages reload.
  useEffect(() => {
    if (items.length === 0) return;
    setSelectedRoutes(current => {
      if (current.size === 0) return current;
      let changed = false;
      const next = new Map(current);
      for (const item of items) {
        if (!next.has(item.route_id)) continue;
        if (!item.matches_current_graph) {
          next.delete(item.route_id);
          changed = true;
        } else if (next.get(item.route_id) !== item) {
          next.set(item.route_id, item);
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [items]);

  const syncSelectedItem = useCallback((updated: RouteItem) => {
    setSelectedRoutes(current => {
      if (!current.has(updated.route_id)) return current;
      const next = new Map(current);
      if (updated.matches_current_graph) next.set(updated.route_id, updated);
      else next.delete(updated.route_id);
      return next;
    });
  }, []);

  const selectablePageItems = useMemo(
    () => items.filter(item => item.matches_current_graph),
    [items],
  );

  const allPageSelected = useMemo(
    () =>
      selectablePageItems.length > 0 &&
      selectablePageItems.every(item => selectedRoutes.has(item.route_id)),
    [selectablePageItems, selectedRoutes],
  );

  const selectedOnMapCount = useMemo(() => {
    let count = 0;
    selectedRoutes.forEach((_item, routeId) => {
      if (wb.mapRoutes.has(routeId)) count += 1;
    });
    return count;
  }, [selectedRoutes, wb.mapRoutes]);

  const toggleSelectRoute = useCallback((item: RouteItem, checked: boolean) => {
    if (!item.matches_current_graph) return;
    setSelectedRoutes(current => {
      const next = new Map(current);
      if (checked) next.set(item.route_id, item);
      else next.delete(item.route_id);
      return next;
    });
  }, []);

  const toggleSelectPage = useCallback(() => {
    if (selectablePageItems.length === 0) return;
    setSelectedRoutes(current => {
      const next = new Map(current);
      if (allPageSelected) {
        selectablePageItems.forEach(item => next.delete(item.route_id));
      } else {
        selectablePageItems.forEach(item => next.set(item.route_id, item));
      }
      return next;
    });
  }, [selectablePageItems, allPageSelected]);

  const clearSelection = useCallback(() => setSelectedRoutes(new Map()), []);

  const addSelectedToMap = useCallback(async () => {
    const validItems = [...selectedRoutes.values()].filter(item => item.matches_current_graph);
    if (validItems.length === 0) return;
    const pending = validItems.filter(item => !wb.mapRoutes.has(item.route_id));
    if (pending.length === 0) {
      wb.dispatch({ type: 'fit-map-routes', preserveView: splitView });
      wb.dispatch({ type: 'status', value: `所选 ${validItems.length} 条路径均已在地图中` });
      return;
    }
    const controller = new AbortController();
    batchAbortRef.current?.abort();
    batchAbortRef.current = controller;
    let done = 0;
    setAddingProgress({ done: 0, total: pending.length });
    try {
      const entries: Array<{ routeId: string; value: MapRouteInput }> = [];
      await runWithConcurrency(
        pending,
        5,
        async candidate => {
          const geometry = await api.routeGeometry(candidate.route_id, controller.signal);
          if (controller.signal.aborted) return;
          entries.push({
            routeId: candidate.route_id,
            value: { geometry, label: labelFor(candidate), visible: true },
          });
          done += 1;
          if (mountedRef.current) setAddingProgress({ done, total: pending.length });
        },
        controller.signal,
      );
      if (controller.signal.aborted || !mountedRef.current) return;
      wb.dispatch({ type: 'map-routes-batch', entries });
      wb.dispatch({ type: 'fit-map-routes', preserveView: splitView });
      wb.dispatch({
        type: 'status',
        value: `已将 ${entries.length} 条路径批量加入地图`,
      });
    } catch (failure) {
      if ((failure as Error).name !== 'AbortError' && mountedRef.current) {
        wb.dispatch({ type: 'error', value: failure instanceof Error ? failure.message : '批量加载路径失败' });
      }
    } finally {
      if (batchAbortRef.current === controller) batchAbortRef.current = null;
      if (mountedRef.current) setAddingProgress(null);
    }
  }, [selectedRoutes, wb, splitView, labelFor]);

  const removeSelectedFromMap = useCallback(() => {
    const onMapIds = [...selectedRoutes.keys()].filter(routeId => wb.mapRoutes.has(routeId));
    if (onMapIds.length === 0) return;
    wb.dispatch({ type: 'remove-map-routes-batch', routeIds: onMapIds });
    wb.dispatch({ type: 'status', value: `已从地图移出 ${onMapIds.length} 条路径` });
  }, [selectedRoutes, wb]);

  const cancelAddToMap = useCallback(() => {
    batchAbortRef.current?.abort();
    batchAbortRef.current = null;
    setAddingProgress(null);
    wb.dispatch({ type: 'status', value: '已取消批量加入地图' });
  }, [wb]);

  return {
    selectedRoutes,
    addingProgress,
    selectablePageItems,
    allPageSelected,
    selectedOnMapCount,
    toggleSelectRoute,
    toggleSelectPage,
    clearSelection,
    syncSelectedItem,
    addSelectedToMap,
    removeSelectedFromMap,
    cancelAddToMap,
  };
}
