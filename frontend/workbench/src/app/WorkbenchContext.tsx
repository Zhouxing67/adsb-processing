import { createContext, useCallback, useContext, useEffect, useMemo, useReducer } from 'react';
import type { Dispatch, ReactNode } from 'react';
import { ApiError, api } from '../api/client';
import type { GraphPostInput, GraphPostPath, GraphPostRequest, GraphPostResponse } from '../api/client';
import type { MapFlightEntry, MapRouteEntry, SelectedFeature, WorkbenchState } from '../api/types';
import { readStoredFlightState } from '../features/flights/storage';

export type EditorTool = 'inspect' | 'split' | 'draw' | 'restore' | 'merge' | 'snap' | 'delete';
export type MainView = 'map' | 'route-map' | 'flights' | 'observations' | 'routes';
export interface FocusFlightRequest { key: string; seq: number }
export interface FocusFeatureRequest { feature: SelectedFeature; seq: number }
export type MapFlightInput = Omit<MapFlightEntry, 'slot'> & { slot?: number };
export type MapRouteInput = Omit<MapRouteEntry, 'slot'> & { slot?: number };

function allocateFreeSlot(map: Map<string, { slot: number }>): number {
  const used = new Set<number>();
  map.forEach(entry => used.add(entry.slot));
  let slot = 0;
  while (used.has(slot)) slot += 1;
  return slot;
}

interface UiState {
  state: WorkbenchState | null; loading: boolean; busy: boolean; error: string;
  status: string; tool: EditorTool; view: MainView; selected: SelectedFeature | null;
  focusFeatureRequest: FocusFeatureRequest | null;
  hasUnsavedChanges: boolean;
  matchSelection: Set<string>; mapFlights: Map<string, MapFlightEntry>; isolatedFlightKey: string | null;
  highlightedFlight: FocusFlightRequest | null;
  mapFocusRequest: FocusFlightRequest | null; fitMapVersion: number; observationLocation: [number, number] | null;
  showMapFlights: boolean;
  mapRoutes: Map<string, MapRouteEntry>; isolatedRouteId: string | null;
  highlightedRoute: FocusFlightRequest | null;
  routeFocusRequest: FocusFlightRequest | null; fitRoutesVersion: number;
  showMapRoutes: boolean;
  flightCatalogueVersion: number;
  routeLibraryVersion: number;
  issueKeys: Set<string>;
  topologyOpen: boolean; searchOpen: boolean; detailsOpen: boolean;
}
type Action =
  | { type: 'loaded'; value: WorkbenchState }
  | { type: 'loading'; value: boolean }
  | { type: 'busy'; value: boolean }
  | { type: 'error'; value: string }
  | { type: 'clear-error' }
  | { type: 'status'; value: string }
  | { type: 'unsaved'; value: boolean }
  | { type: 'tool'; value: EditorTool }
  | { type: 'view'; value: MainView }
  | { type: 'selected'; value: SelectedFeature | null; focus?: boolean }
  | { type: 'toggle-match'; key: string; checked: boolean }
  | { type: 'set-match-selection'; keys: string[] }
  | { type: 'merge-match-selection'; keys: string[] }
  | { type: 'remove-match-selection'; keys: string[] }
  | { type: 'prune-match-selection'; keys: string[] }
  | { type: 'map-flight'; key: string; value: MapFlightInput | null }
  | { type: 'map-flights-batch'; entries: Array<{ key: string; value: MapFlightInput }> }
  | { type: 'clear-map-flights' }
  | { type: 'isolate-flight'; key: string | null }
  | { type: 'highlight-flight'; key: string | null }
  | { type: 'focus-flight'; key: string; preserveView?: boolean }
  | { type: 'fit-map-flights'; preserveView?: boolean }
  | { type: 'toggle-map-flights-group' }
  | { type: 'map-route'; routeId: string; value: MapRouteInput | null }
  | { type: 'map-routes-batch'; entries: Array<{ routeId: string; value: MapRouteInput }> }
  | { type: 'remove-map-routes-batch'; routeIds: string[] }
  | { type: 'clear-map-routes' }
  | { type: 'isolate-route'; routeId: string | null }
  | { type: 'highlight-route'; routeId: string | null }
  | { type: 'focus-route'; routeId: string; preserveView?: boolean }
  | { type: 'fit-map-routes'; preserveView?: boolean }
  | { type: 'toggle-map-routes-group' }
  | { type: 'flights-updated' }
  | { type: 'routes-updated' }
  | { type: 'set-issue-keys'; keys: string[] }
  | { type: 'observation-location'; value: [number, number] | null; preserveView?: boolean }
  | { type: 'panel'; panel: 'topologyOpen' | 'searchOpen' | 'detailsOpen'; value: boolean };

const initial: UiState = {
  state: null, loading: true, busy: false, error: '', status: '正在载入工作台…', tool: 'inspect',
  view: 'map', selected: null, focusFeatureRequest: null, hasUnsavedChanges: false,
  matchSelection: new Set(readStoredFlightState().matchSelection ?? []), mapFlights: new Map(), isolatedFlightKey: null,
  highlightedFlight: null,
  mapFocusRequest: null, fitMapVersion: 0, observationLocation: null,
  showMapFlights: true,
  mapRoutes: new Map(), isolatedRouteId: null, highlightedRoute: null,
  routeFocusRequest: null, fitRoutesVersion: 0, showMapRoutes: true,
  flightCatalogueVersion: 0,
  routeLibraryVersion: 0,
  issueKeys: new Set(),
  topologyOpen: false, searchOpen: false, detailsOpen: false,
};
function reducer(state: UiState, action: Action): UiState {
  switch (action.type) {
    case 'loaded': return { ...state, state: action.value, loading: false, error: '' };
    case 'loading': return { ...state, loading: action.value };
    case 'busy': return { ...state, busy: action.value };
    case 'error': return { ...state, error: action.value, loading: false, busy: false };
    case 'clear-error': return { ...state, error: '' };
    case 'status': return { ...state, status: action.value, error: '' };
    case 'unsaved': return { ...state, hasUnsavedChanges: action.value };
    case 'tool': return { ...state, tool: action.value, selected: null, error: '' };
    case 'view': return { ...state, view: action.value };
    case 'selected': return {
      ...state,
      selected: action.value,
      detailsOpen: Boolean(action.value),
      error: '',
      focusFeatureRequest: action.value && action.focus
        ? { feature: action.value, seq: (state.focusFeatureRequest?.seq ?? 0) + 1 }
        : state.focusFeatureRequest,
    };
    case 'toggle-match': {
      const next = new Set(state.matchSelection); action.checked ? next.add(action.key) : next.delete(action.key);
      return { ...state, matchSelection: next };
    }
    case 'set-match-selection': return { ...state, matchSelection: new Set(action.keys) };
    case 'merge-match-selection': {
      const next = new Set(state.matchSelection);
      action.keys.forEach(key => next.add(key));
      return { ...state, matchSelection: next };
    }
    case 'remove-match-selection': {
      const removed = new Set(action.keys);
      return { ...state, matchSelection: new Set([...state.matchSelection].filter(key => !removed.has(key))) };
    }
    case 'prune-match-selection': {
      const valid = new Set(action.keys);
      return { ...state, matchSelection: new Set([...state.matchSelection].filter(key => valid.has(key))) };
    }
    case 'map-flight': {
      const next = new Map(state.mapFlights);
      if (action.value) {
        const existing = next.get(action.key);
        const slot = action.value.slot ?? existing?.slot ?? allocateFreeSlot(next);
        next.set(action.key, { ...action.value, slot });
      } else {
        next.delete(action.key);
      }
      return { ...state, mapFlights: next, isolatedFlightKey: !action.value && state.isolatedFlightKey === action.key ? null : state.isolatedFlightKey };
    }
    case 'map-flights-batch': {
      if (!action.entries.length) return state;
      const next = new Map(state.mapFlights);
      action.entries.forEach(({ key, value }) => {
        const existing = next.get(key);
        const slot = value.slot ?? existing?.slot ?? allocateFreeSlot(next);
        next.set(key, { ...value, slot });
      });
      return { ...state, mapFlights: next };
    }
    case 'clear-map-flights': return { ...state, mapFlights: new Map(), isolatedFlightKey: null, highlightedFlight: null, mapFocusRequest: null };
    case 'isolate-flight': return { ...state, isolatedFlightKey: action.key, status: action.key ? '仅显示所选航班' : '已恢复全部地图航班', error: '' };
    case 'highlight-flight': return {
      ...state,
      highlightedFlight: action.key ? { key: action.key, seq: (state.highlightedFlight?.seq ?? 0) + 1 } : null,
    };
    case 'focus-flight': return {
      ...state,
      mapFocusRequest: { key: action.key, seq: (state.mapFocusRequest?.seq ?? 0) + 1 },
      view: action.preserveView ? state.view : 'map',
      status: '已定位航班',
      error: '',
    };
    case 'fit-map-flights': return {
      ...state,
      fitMapVersion: state.fitMapVersion + 1,
      view: action.preserveView ? state.view : 'map',
      status: '已适配全部地图航班',
      error: '',
    };
    case 'toggle-map-flights-group': return {
      ...state,
      showMapFlights: !state.showMapFlights,
      status: state.showMapFlights ? '已隐藏地图航班图层' : '已显示地图航班图层',
      error: '',
    };
    case 'map-route': {
      const next = new Map(state.mapRoutes);
      if (action.value) {
        const existing = next.get(action.routeId);
        const slot = action.value.slot ?? existing?.slot ?? allocateFreeSlot(next);
        next.set(action.routeId, { ...action.value, slot });
      } else {
        next.delete(action.routeId);
      }
      return {
        ...state,
        mapRoutes: next,
        showMapRoutes: action.value ? true : state.showMapRoutes,
        isolatedRouteId: !action.value && state.isolatedRouteId === action.routeId ? null : state.isolatedRouteId,
      };
    }
    case 'map-routes-batch': {
      if (!action.entries.length) return state;
      const next = new Map(state.mapRoutes);
      action.entries.forEach(({ routeId, value }) => {
        const existing = next.get(routeId);
        const slot = value.slot ?? existing?.slot ?? allocateFreeSlot(next);
        next.set(routeId, { ...value, slot });
      });
      return { ...state, mapRoutes: next, showMapRoutes: true };
    }
    case 'remove-map-routes-batch': {
      if (!action.routeIds.length) return state;
      const next = new Map(state.mapRoutes);
      const removed = new Set(action.routeIds);
      removed.forEach(routeId => next.delete(routeId));
      return {
        ...state,
        mapRoutes: next,
        isolatedRouteId: state.isolatedRouteId && removed.has(state.isolatedRouteId) ? null : state.isolatedRouteId,
      };
    }
    case 'clear-map-routes': return {
      ...state,
      mapRoutes: new Map(),
      isolatedRouteId: null,
      highlightedRoute: null,
      routeFocusRequest: null,
    };
    case 'isolate-route': return {
      ...state,
      isolatedRouteId: action.routeId,
      status: action.routeId ? '仅显示所选路径' : '已恢复全部地图路径',
      error: '',
    };
    case 'highlight-route': return {
      ...state,
      highlightedRoute: action.routeId ? { key: action.routeId, seq: (state.highlightedRoute?.seq ?? 0) + 1 } : null,
    };
    case 'focus-route': return {
      ...state,
      routeFocusRequest: { key: action.routeId, seq: (state.routeFocusRequest?.seq ?? 0) + 1 },
      showMapRoutes: true,
      view: action.preserveView ? state.view : state.mapFlights.size > 0 && state.mapRoutes.size > 0 ? 'route-map' : 'map',
      status: '已定位路径',
      error: '',
    };
    case 'fit-map-routes': return {
      ...state,
      fitRoutesVersion: state.fitRoutesVersion + 1,
      showMapRoutes: true,
      view: action.preserveView ? state.view : state.mapFlights.size > 0 && state.mapRoutes.size > 0 ? 'route-map' : 'map',
      status: '已适配全部地图路径',
      error: '',
    };
    case 'toggle-map-routes-group': return {
      ...state,
      showMapRoutes: !state.showMapRoutes,
      status: state.showMapRoutes ? '已隐藏地图路径图层' : '已显示地图路径图层',
      error: '',
    };
    case 'flights-updated': return {
      ...state,
      flightCatalogueVersion: state.flightCatalogueVersion + 1,
    };
    case 'routes-updated': return {
      ...state,
      routeLibraryVersion: state.routeLibraryVersion + 1,
    };
    case 'set-issue-keys': return {
      ...state,
      issueKeys: new Set(action.keys),
    };
    case 'observation-location': return {
      ...state,
      observationLocation: action.value,
      view: action.value && !action.preserveView ? 'map' : state.view,
      status: action.value ? '已在地图中定位观测点' : '已清除地图定位点',
      error: '',
    };
    case 'panel': return { ...state, [action.panel]: action.value };
  }
}
interface ContextValue extends UiState {
  dispatch: Dispatch<Action>;
  refresh(options?: { preserveStatus?: boolean; signal?: AbortSignal }): Promise<WorkbenchState | null>;
  runGraphCommand<P extends GraphPostPath>(path: P, body?: GraphPostInput<P>): Promise<GraphPostResponse<P> | null>;
  previewGraphCommand<P extends GraphPostPath>(path: P, body?: GraphPostInput<P>): Promise<GraphPostResponse<P> | null>;
}
const WorkbenchContext = createContext<ContextValue | null>(null);

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const [model, dispatch] = useReducer(reducer, initial);
  const refresh = useCallback(async (options?: { preserveStatus?: boolean; signal?: AbortSignal }) => {
    try {
      const value = await api.state(options?.signal);
      dispatch({ type: 'loaded', value });
      if (value.flight_mode) {
        api.matchIssues(options?.signal).then(res => {
          dispatch({ type: 'set-issue-keys', keys: res.flight_keys });
        }).catch(() => {
          /* ignore non-fatal issue preload error */
        });
      }
      if (!options?.preserveStatus) {
        dispatch({ type: 'status', value: value.flight_mode ? '航班工作台' : '查看模式 · 点击图层要素查看详情' });
      }
      return value;
    } catch (error) {
      if ((error as Error).name !== 'AbortError') dispatch({ type: 'error', value: error instanceof Error ? error.message : '工作台加载失败' });
      return null;
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void refresh({ signal: controller.signal });
    return () => controller.abort();
  }, [refresh]);

  const graphRequest = useCallback(async <P extends GraphPostPath,>(path: P, body: GraphPostInput<P>, refreshAfter: boolean) => {
    if (!model.state) return null;
    dispatch({ type: 'busy', value: true });
    try {
      const request = { expected_revision: model.state.revision, ...body } as GraphPostRequest<P>;
      const result = await api.graphCommand(path, request);
      const message = result && typeof result === 'object' && 'message' in result && typeof (result as { message?: unknown }).message === 'string'
        ? (result as { message: string }).message
        : null;
      if (message) dispatch({ type: 'status', value: message });
      if (refreshAfter) {
        if (path === '/api/save' || path === '/api/finish') dispatch({ type: 'unsaved', value: false });
        else dispatch({ type: 'unsaved', value: true });
      }
      if (refreshAfter && path !== '/api/finish') {
        await refresh({ preserveStatus: Boolean(message) });
      }
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        dispatch({ type: 'status', value: '图已变更，操作已取消并刷新' });
        dispatch({ type: 'selected', value: null });
        await refresh({ preserveStatus: true });
      } else dispatch({ type: 'error', value: error instanceof Error ? error.message : '操作失败' });
      return null;
    } finally { dispatch({ type: 'busy', value: false }); }
  }, [model.state, refresh]);
  const runGraphCommand = useCallback(<P extends GraphPostPath,>(path: P, body: GraphPostInput<P> = {} as GraphPostInput<P>) => graphRequest(path, body, true), [graphRequest]);
  const previewGraphCommand = useCallback(<P extends GraphPostPath,>(path: P, body: GraphPostInput<P> = {} as GraphPostInput<P>) => graphRequest(path, body, false), [graphRequest]);

  useEffect(() => {
    if (!model.hasUnsavedChanges) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [model.hasUnsavedChanges]);

  const value = useMemo(() => ({ ...model, dispatch, refresh, runGraphCommand, previewGraphCommand }), [model, refresh, runGraphCommand, previewGraphCommand]);
  return <WorkbenchContext.Provider value={value}>{children}</WorkbenchContext.Provider>;
}
export function useWorkbench() {
  const context = useContext(WorkbenchContext);
  if (!context) throw new Error('WorkbenchProvider is missing');
  return context;
}
