export interface FocusRequest {
  key: string;
  seq: number;
}

export interface MapLayerCollection<TEntry extends { slot: number }> {
  entries: Map<string, TEntry>;
  visible: boolean;
  isolatedKey: string | null;
  highlighted: FocusRequest | null;
  focusRequest: FocusRequest | null;
  fitVersion: number;
}

export type MapLayerInput<TEntry extends { slot: number }> = Omit<TEntry, 'slot'> & {
  slot?: number;
};

function allocateFreeSlot(map: Map<string, { slot: number }>): number {
  const used = new Set<number>();
  map.forEach(entry => used.add(entry.slot));
  let slot = 0;
  while (used.has(slot)) slot += 1;
  return slot;
}

export function createMapLayerCollection<TEntry extends { slot: number }>(): MapLayerCollection<TEntry> {
  return {
    entries: new Map(),
    visible: true,
    isolatedKey: null,
    highlighted: null,
    focusRequest: null,
    fitVersion: 0,
  };
}

export function upsertLayerEntry<TEntry extends { slot: number }>(
  collection: MapLayerCollection<TEntry>,
  key: string,
  value: MapLayerInput<TEntry> | null,
): MapLayerCollection<TEntry> {
  const next = new Map(collection.entries);
  if (value) {
    const existing = next.get(key);
    const slot = value.slot ?? existing?.slot ?? allocateFreeSlot(next);
    next.set(key, { ...value, slot } as TEntry);
  } else {
    next.delete(key);
  }
  return {
    ...collection,
    entries: next,
    visible: value ? true : collection.visible,
    isolatedKey: !value && collection.isolatedKey === key ? null : collection.isolatedKey,
  };
}

export function addLayerBatch<TEntry extends { slot: number }>(
  collection: MapLayerCollection<TEntry>,
  items: Array<{ key: string; value: MapLayerInput<TEntry> }>,
): MapLayerCollection<TEntry> {
  if (!items.length) return collection;
  const next = new Map(collection.entries);
  items.forEach(({ key, value }) => {
    const existing = next.get(key);
    const slot = value.slot ?? existing?.slot ?? allocateFreeSlot(next);
    next.set(key, { ...value, slot } as TEntry);
  });
  return {
    ...collection,
    entries: next,
    visible: true,
  };
}

export function replaceLayerBatch<TEntry extends { slot: number }>(
  collection: MapLayerCollection<TEntry>,
  items: Array<{ key: string; value: MapLayerInput<TEntry> }>,
  options: { isolateFirst?: boolean } = {},
): MapLayerCollection<TEntry> {
  const next = new Map<string, TEntry>();
  items.forEach(({ key, value }, index) => {
    next.set(key, { ...value, slot: value.slot ?? index } as TEntry);
  });
  const firstKey = options.isolateFirst && items.length > 0 ? items[0].key : null;
  return {
    ...collection,
    entries: next,
    visible: true,
    isolatedKey: firstKey,
    highlighted: null,
    focusRequest: firstKey ? { key: firstKey, seq: (collection.focusRequest?.seq ?? 0) + 1 } : null,
    fitVersion: !firstKey && items.length > 0 ? collection.fitVersion + 1 : collection.fitVersion,
  };
}

export function removeLayerBatch<TEntry extends { slot: number }>(
  collection: MapLayerCollection<TEntry>,
  keys: string[],
): MapLayerCollection<TEntry> {
  if (!keys.length) return collection;
  const next = new Map(collection.entries);
  const removed = new Set(keys);
  removed.forEach(key => next.delete(key));
  return {
    ...collection,
    entries: next,
    isolatedKey: collection.isolatedKey && removed.has(collection.isolatedKey) ? null : collection.isolatedKey,
  };
}

export function clearLayerCollection<TEntry extends { slot: number }>(
  collection: MapLayerCollection<TEntry>,
): MapLayerCollection<TEntry> {
  return {
    ...collection,
    entries: new Map(),
    isolatedKey: null,
    highlighted: null,
    focusRequest: null,
  };
}

export function isolateLayerEntry<TEntry extends { slot: number }>(
  collection: MapLayerCollection<TEntry>,
  key: string | null,
): MapLayerCollection<TEntry> {
  return { ...collection, isolatedKey: key };
}

export function highlightLayerEntry<TEntry extends { slot: number }>(
  collection: MapLayerCollection<TEntry>,
  key: string | null,
): MapLayerCollection<TEntry> {
  return {
    ...collection,
    highlighted: key ? { key, seq: (collection.highlighted?.seq ?? 0) + 1 } : null,
  };
}

export function focusLayerEntry<TEntry extends { slot: number }>(
  collection: MapLayerCollection<TEntry>,
  key: string,
): MapLayerCollection<TEntry> {
  return {
    ...collection,
    visible: true,
    focusRequest: { key, seq: (collection.focusRequest?.seq ?? 0) + 1 },
  };
}

export function fitLayerCollection<TEntry extends { slot: number }>(
  collection: MapLayerCollection<TEntry>,
): MapLayerCollection<TEntry> {
  return {
    ...collection,
    visible: true,
    fitVersion: collection.fitVersion + 1,
  };
}

export function toggleLayerVisible<TEntry extends { slot: number }>(
  collection: MapLayerCollection<TEntry>,
): MapLayerCollection<TEntry> {
  return { ...collection, visible: !collection.visible };
}
