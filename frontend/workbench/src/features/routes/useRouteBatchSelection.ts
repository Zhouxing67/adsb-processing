import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/api/client';
import type { RouteItem } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import type { MapRouteInput } from '@/app/WorkbenchContext';
import { useMapBatchLoader } from '@/features/map/useMapBatchLoader';

interface UseRouteBatchSelectionOptions {
  items: RouteItem[];
  page: number;
  totalPages: number;
  splitView: boolean;
  labelFor(item: RouteItem): string;
  fetchPage(targetPage: number): Promise<{ items: RouteItem[]; page: number }>;
}

export function useRouteBatchSelection({
  items,
  page,
  totalPages,
  splitView,
  labelFor,
  fetchPage,
}: UseRouteBatchSelectionOptions) {
  const wb = useWorkbench();
  const [selectedRoutes, setSelectedRoutes] = useState<Map<string, RouteItem>>(() => new Map());
  const prevLibraryVersionRef = useRef(wb.routeLibraryVersion);

  const mapLoader = useMapBatchLoader<RouteItem, MapRouteInput>({
    kind: 'routes',
    unitLabel: '路径',
    page,
    totalPages,
    getKey: item => item.route_id,
    fetchEntry: async (candidate, signal) => {
      const geometry = await api.routeGeometry(candidate.route_id, signal);
      return { geometry, label: labelFor(candidate), visible: true };
    },
    onCommitAdd: entries => {
      wb.dispatch({
        type: 'map-routes-batch',
        entries: entries.map(({ key, value }) => ({ routeId: key, value })),
      });
      wb.dispatch({ type: 'fit-map-routes', preserveView: splitView });
    },
    onCommitReplace: entries => {
      wb.dispatch({
        type: 'replace-map-routes-batch',
        entries: entries.map(({ key, value }) => ({ routeId: key, value })),
        isolateFirst: true,
        preserveView: splitView,
      });
    },
    fetchPage: async targetPage => {
      const result = await fetchPage(targetPage);
      return {
        items: result.items.filter(item => item.matches_current_graph),
        page: result.page,
      };
    },
  });

  useEffect(() => {
    if (prevLibraryVersionRef.current !== wb.routeLibraryVersion) {
      prevLibraryVersionRef.current = wb.routeLibraryVersion;
      setSelectedRoutes(new Map());
    }
  }, [wb.routeLibraryVersion]);

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

  const addRouteItemsToMap = useCallback(
    (targetItems: RouteItem[]) => {
      const validItems = targetItems.filter(item => item.matches_current_graph);
      if (validItems.length === 0) return;
      const pending = validItems.filter(item => !wb.mapRoutes.has(item.route_id));
      if (pending.length === 0) {
        wb.dispatch({ type: 'fit-map-routes', preserveView: splitView });
        wb.dispatch({ type: 'status', value: `所选 ${validItems.length} 条路径均已在地图中` });
        return;
      }
      mapLoader.addItems(pending);
    },
    [wb, splitView, mapLoader],
  );

  const addSelectedToMap = useCallback(() => {
    addRouteItemsToMap([...selectedRoutes.values()]);
  }, [selectedRoutes, addRouteItemsToMap]);

  const replaceItemsOnMap = useCallback(
    (targetItems: RouteItem[], pageNumber?: number) =>
      mapLoader.replaceItems(
        targetItems.filter(item => item.matches_current_graph),
        pageNumber,
      ),
    [mapLoader],
  );

  const removeSelectedFromMap = useCallback(() => {
    const onMapIds = [...selectedRoutes.keys()].filter(routeId => wb.mapRoutes.has(routeId));
    if (onMapIds.length === 0) return;
    wb.dispatch({ type: 'remove-map-routes-batch', routeIds: onMapIds });
    wb.dispatch({ type: 'status', value: `已从地图移出 ${onMapIds.length} 条路径` });
  }, [selectedRoutes, wb]);

  return {
    selectedRoutes,
    addingProgress: mapLoader.addingProgress,
    confirmDialog: mapLoader.confirmDialog,
    dismissConfirm: mapLoader.dismissConfirm,
    selectablePageItems,
    allPageSelected,
    selectedOnMapCount,
    toggleSelectRoute,
    toggleSelectPage,
    clearSelection,
    syncSelectedItem,
    addSelectedToMap,
    addRouteItemsToMap,
    replaceItemsOnMap,
    removeSelectedFromMap,
    cancelAddToMap: mapLoader.cancel,
  };
}
