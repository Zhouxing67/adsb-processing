export interface FlightFilters {
  query: string;
  movement: string;
  status: string;
  minimum: number;
  maximum: number | null;
  stands: string[];
  start: string;
  end: string;
  validation: boolean;
  whitelist: boolean;
  issues: boolean;
}

export interface StoredDisplay {
  key: string;
  label: string;
  slot: number;
  trajectoryVisible: boolean;
  pathVisible: boolean;
}

export interface StoredFlightState {
  filters?: Partial<FlightFilters>;
  page?: number;
  matchSelection?: string[];
  displayed?: StoredDisplay[];
}

export const defaultFlightFilters: FlightFilters = {
  query: '',
  movement: '',
  status: '',
  minimum: 0,
  maximum: null,
  stands: [],
  start: '',
  end: '',
  validation: false,
  whitelist: false,
  issues: false,
};

function getStorageKey(): string {
  const session = new URLSearchParams(location.search).get('session') || 'default';
  return `airport-flight-workbench:${session}`;
}

export function readStoredFlightState(): StoredFlightState {
  try {
    return JSON.parse(sessionStorage.getItem(getStorageKey()) || '{}') as StoredFlightState;
  } catch {
    return {};
  }
}

export function writeStoredFlightState(value: StoredFlightState): void {
  try {
    sessionStorage.setItem(getStorageKey(), JSON.stringify(value));
  } catch {
    /* storage is optional */
  }
}
