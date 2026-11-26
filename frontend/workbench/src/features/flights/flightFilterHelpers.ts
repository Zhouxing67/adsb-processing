import type { FlightCatalogueQuery } from '@/api/client';
import type { FlightCatalogue } from '@/api/types';
import { MATCH_STATUS_LABELS as statusLabels, MOVEMENT_LABELS as movementLabels } from '@/domain/palette';
import type { DraftFilters } from './FlightFilterBar';
import type { FlightFilters } from './storage';

export function toFlightDraft(value: FlightFilters): DraftFilters {
  return {
    ...value,
    minimum: String(value.minimum),
    maximum: value.maximum === null ? '' : String(value.maximum),
  };
}

export function buildFlightQueryParams(
  filters: FlightFilters,
  page?: number,
  pageSize = 20,
): FlightCatalogueQuery {
  return {
    q: filters.query || undefined,
    movement_type: filters.movement || undefined,
    match_status: filters.status || undefined,
    min_points: filters.minimum,
    max_points: filters.maximum,
    stands: filters.stands,
    start_date: filters.start || undefined,
    end_date: filters.end || undefined,
    validation_only: filters.validation || undefined,
    issues_only: filters.issues || undefined,
    page,
    page_size: page === undefined ? undefined : pageSize,
  };
}

export function validateFlightDraft(
  draft: DraftFilters,
  catalogue: FlightCatalogue | null,
): { filters?: FlightFilters; error?: string } {
  const minText = draft.minimum.trim();
  const maxText = draft.maximum.trim();
  const minimum = minText === '' ? 0 : Number(minText);
  const maximum = maxText === '' ? (catalogue?.dataset_max_points ?? null) : Number(maxText);
  if (
    !Number.isSafeInteger(minimum) ||
    minimum < 0 ||
    maximum === null ||
    !Number.isSafeInteger(maximum) ||
    maximum < 0
  ) {
    return { error: '观测点数必须是非负整数' };
  }
  if (minimum > maximum) return { error: '最小观测点数不得大于最大观测点数' };
  if (catalogue && maximum > catalogue.dataset_max_points) {
    return { error: `最大观测点数不得超过 ${catalogue.dataset_max_points}` };
  }
  if (draft.start && draft.end && draft.start > draft.end) {
    return { error: '起始日期不得晚于终止日期' };
  }
  const minDate = catalogue?.dataset_min_date ?? '';
  const maxDate = catalogue?.dataset_max_date ?? '';
  const isFullDateRange = Boolean(minDate && maxDate) && draft.start === minDate && draft.end === maxDate;
  return {
    filters: {
      ...draft,
      minimum,
      maximum,
      start: isFullDateRange ? '' : draft.start,
      end: isFullDateRange ? '' : draft.end,
    },
  };
}

export function countAdvancedFlightFilters(filters: FlightFilters, datasetMax: number | null): number {
  let count = 0;
  if (filters.stands.length > 0) count += 1;
  if (filters.minimum > 0) count += 1;
  if (filters.maximum !== null && datasetMax !== null && filters.maximum < datasetMax) count += 1;
  if (filters.start || filters.end) count += 1;
  if (filters.validation) count += 1;
  if (filters.issues) count += 1;
  return count;
}

export function buildFlightFilterChips(
  filters: FlightFilters,
  datasetMax: number | null,
  applyFilterPatch: (patch: Partial<FlightFilters>) => void,
): Array<{ id: string; label: string; clear: () => void }> {
  const chips: Array<{ id: string; label: string; clear: () => void }> = [];
  if (filters.query) chips.push({ id: 'q', label: `搜索: ${filters.query}`, clear: () => applyFilterPatch({ query: '' }) });
  if (filters.movement) {
    chips.push({ id: 'movement', label: `进出港: ${movementLabels[filters.movement] ?? filters.movement}`, clear: () => applyFilterPatch({ movement: '' }) });
  }
  if (filters.status) {
    chips.push({ id: 'status', label: `状态: ${statusLabels[filters.status] ?? filters.status}`, clear: () => applyFilterPatch({ status: '' }) });
  }
  if (filters.stands.length) {
    chips.push({ id: 'stands', label: `机位: ${filters.stands.map(s => s || '空机位').join(', ')}`, clear: () => applyFilterPatch({ stands: [] }) });
  }
  if (filters.minimum > 0) chips.push({ id: 'min', label: `观测点 ≥ ${filters.minimum}`, clear: () => applyFilterPatch({ minimum: 0 }) });
  if (filters.maximum !== null && datasetMax !== null && filters.maximum < datasetMax) {
    chips.push({ id: 'max', label: `观测点 ≤ ${filters.maximum}`, clear: () => applyFilterPatch({ maximum: datasetMax }) });
  }
  if (filters.start || filters.end) {
    chips.push({ id: 'date', label: `日期: ${filters.start || '不限'} ~ ${filters.end || '不限'}`, clear: () => applyFilterPatch({ start: '', end: '' }) });
  }
  if (filters.validation) chips.push({ id: 'validation', label: '仅验证航班', clear: () => applyFilterPatch({ validation: false }) });
  if (filters.issues) chips.push({ id: 'issues', label: '仅异常归档航班', clear: () => applyFilterPatch({ issues: false }) });
  return chips;
}
