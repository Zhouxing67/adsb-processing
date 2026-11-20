import { createContext, useCallback, useContext, useEffect, useMemo, useReducer } from 'react';
import type { Dispatch, ReactNode } from 'react';
import { ApiError, api } from '../api/client';
import type { MapFlightEntry, SelectedFeature, WorkbenchState } from '../api/types';

export type EditorTool = 'inspect' | 'split' | 'draw' | 'restore' | 'merge' | 'snap' | 'delete';
export type MainView = 'map' | 'flights' | 'observations';
interface UiState {
  state: WorkbenchState | null; loading: boolean; busy: boolean; error: string;
  status: string; tool: EditorTool; view: MainView; selected: SelectedFeature | null;
  matchSelection: Set<string>; mapFlights: Map<string, MapFlightEntry>;
  mapFocusKey: string | null; fitMapVersion: number; observationLocation: [number, number] | null;
  topologyOpen: boolean; searchOpen: boolean; detailsOpen: boolean;
}
type Action =
  | { type: 'loaded'; value: WorkbenchState }
  | { type: 'loading'; value: boolean }
  | { type: 'busy'; value: boolean }
  | { type: 'error'; value: string }
  | { type: 'status'; value: string }
  | { type: 'tool'; value: EditorTool }
  | { type: 'view'; value: MainView }
  | { type: 'selected'; value: SelectedFeature | null }
  | { type: 'toggle-match'; key: string; checked: boolean }
  | { type: 'set-match-selection'; keys: string[] }
  | { type: 'map-flight'; key: string; value: MapFlightEntry | null }
  | { type: 'focus-flight'; key: string }
  | { type: 'fit-map-flights' }
  | { type: 'observation-location'; value: [number, number] | null }
  | { type: 'panel'; panel: 'topologyOpen' | 'searchOpen' | 'detailsOpen'; value: boolean };

const storageKey = `airport-flight-workbench:${new URLSearchParams(location.search).get('session') || 'default'}`;
function storedSelection(): string[] {
  try { return JSON.parse(sessionStorage.getItem(storageKey) || '{}').matchSelection || []; } catch { return []; }
}
const initial: UiState = {
  state: null, loading: true, busy: false, error: '', status: '正在载入工作台…', tool: 'inspect',
  view: 'map', selected: null, matchSelection: new Set(storedSelection()), mapFlights: new Map(),
  mapFocusKey: null, fitMapVersion: 0, observationLocation: null,
  topologyOpen: false, searchOpen: false, detailsOpen: false,
};
function reducer(state: UiState, action: Action): UiState {
  switch (action.type) {
    case 'loaded': return { ...state, state: action.value, loading: false, error: '' };
    case 'loading': return { ...state, loading: action.value };
    case 'busy': return { ...state, busy: action.value };
    case 'error': return { ...state, error: action.value, loading: false, busy: false };
    case 'status': return { ...state, status: action.value };
    case 'tool': return { ...state, tool: action.value, selected: null };
    case 'view': return { ...state, view: action.value };
    case 'selected': return { ...state, selected: action.value, detailsOpen: Boolean(action.value) };
    case 'toggle-match': {
      const next = new Set(state.matchSelection); action.checked ? next.add(action.key) : next.delete(action.key);
      return { ...state, matchSelection: next };
    }
    case 'set-match-selection': return { ...state, matchSelection: new Set(action.keys) };
    case 'map-flight': {
      const next = new Map(state.mapFlights); action.value ? next.set(action.key, action.value) : next.delete(action.key);
      return { ...state, mapFlights: next };
    }
    case 'focus-flight': return { ...state, mapFocusKey: action.key, view: 'map', status: `已定位航班` };
    case 'fit-map-flights': return { ...state, fitMapVersion: state.fitMapVersion + 1, view: 'map' };
    case 'observation-location': return { ...state, observationLocation: action.value, view: action.value ? 'map' : state.view };
    case 'panel': return { ...state, [action.panel]: action.value };
  }
}
interface ContextValue extends UiState {
  dispatch: Dispatch<Action>;
  refresh(): Promise<WorkbenchState | null>;
  runGraphCommand<T>(path: string, body?: Record<string, unknown>): Promise<T | null>;
  previewGraphCommand<T>(path: string, body?: Record<string, unknown>): Promise<T | null>;
}
const WorkbenchContext = createContext<ContextValue | null>(null);

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const [model, dispatch] = useReducer(reducer, initial);
  const refresh = useCallback(async () => {
    const controller = new AbortController();
    try {
      const value = await api.state(controller.signal);
      dispatch({ type: 'loaded', value });
      dispatch({ type: 'status', value: value.flight_mode ? '航班工作台' : '查看模式 · 点击图层要素查看详情' });
      return value;
    } catch (error) {
      if ((error as Error).name !== 'AbortError') dispatch({ type: 'error', value: error instanceof Error ? error.message : '工作台加载失败' });
      return null;
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const graphRequest = useCallback(async <T,>(path: string, body: Record<string, unknown>, refreshAfter: boolean) => {
    if (!model.state) return null;
    dispatch({ type: 'busy', value: true });
    try {
      const result = await api.graphCommand<T>(path, { expected_revision: model.state.revision, ...body });
      if (refreshAfter) await refresh();
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        dispatch({ type: 'status', value: '图已变更，操作已取消并刷新' });
        dispatch({ type: 'selected', value: null });
        await refresh();
      } else dispatch({ type: 'error', value: error instanceof Error ? error.message : '操作失败' });
      return null;
    } finally { dispatch({ type: 'busy', value: false }); }
  }, [model.state, refresh]);
  const runGraphCommand = useCallback(<T,>(path: string, body: Record<string, unknown> = {}) => graphRequest<T>(path, body, true), [graphRequest]);
  const previewGraphCommand = useCallback(<T,>(path: string, body: Record<string, unknown> = {}) => graphRequest<T>(path, body, false), [graphRequest]);

  const value = useMemo(() => ({ ...model, dispatch, refresh, runGraphCommand, previewGraphCommand }), [model, refresh, runGraphCommand, previewGraphCommand]);
  return <WorkbenchContext.Provider value={value}>{children}</WorkbenchContext.Provider>;
}
export function useWorkbench() {
  const context = useContext(WorkbenchContext);
  if (!context) throw new Error('WorkbenchProvider is missing');
  return context;
}
