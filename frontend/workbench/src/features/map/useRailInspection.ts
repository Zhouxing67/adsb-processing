import { useEffect, useRef, useState } from 'react';
import type { FocusRequest } from '@/app/mapLayerCollection';
import type { PageStepperKind } from '@/app/WorkbenchContext';
import { useWorkbench } from '@/app/WorkbenchContext';
import type { KeyboardShortcutBinding } from '@/components/ui/keyboard-shortcuts';

interface UseRailInspectionOptions<TEntry> {
  kind: PageStepperKind;
  sortedEntries: Array<[string, TEntry]>;
  isolatedKey: string | null;
  highlighted: FocusRequest | null;
  onIsolate(key: string | null): void;
  onFocus(key: string): void;
  onFitAll(): void;
  onHighlightMatch?(): void;
  extraBindings?: KeyboardShortcutBinding[];
}

export function useRailInspection<TEntry>({
  kind,
  sortedEntries,
  isolatedKey,
  highlighted,
  onIsolate,
  onFocus,
  onFitAll,
  onHighlightMatch,
  extraBindings = [],
}: UseRailInspectionOptions<TEntry>) {
  const wb = useWorkbench();
  const [flashingKey, setFlashingKey] = useState<string | null>(null);
  const itemRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const onHighlightMatchRef = useRef(onHighlightMatch);
  onHighlightMatchRef.current = onHighlightMatch;

  useEffect(() => {
    if (!highlighted) return;
    onHighlightMatchRef.current?.();
    setFlashingKey(highlighted.key);
    const frame = window.requestAnimationFrame(() => {
      itemRefs.current.get(highlighted.key)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
    const timer = window.setTimeout(() => {
      setFlashingKey(current => (current === highlighted.key ? null : current));
    }, 1800);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [highlighted]);

  const currentIndex = isolatedKey
    ? sortedEntries.findIndex(([key]) => key === isolatedKey)
    : -1;

  const step = (delta: -1 | 1) => {
    if (sortedEntries.length === 0) return;
    const nextIndex =
      currentIndex < 0
        ? delta > 0
          ? 0
          : sortedEntries.length - 1
        : (currentIndex + delta + sortedEntries.length) % sortedEntries.length;
    const [nextKey] = sortedEntries[nextIndex];
    onIsolate(nextKey);
    onFocus(nextKey);
    window.requestAnimationFrame(() => {
      itemRefs.current.get(nextKey)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  };

  const showAll = () => {
    onIsolate(null);
    onFitAll();
  };

  const setItemRef = (key: string, element: HTMLDivElement | null) => {
    if (element) itemRefs.current.set(key, element);
    else itemRefs.current.delete(key);
  };

  const bindings: KeyboardShortcutBinding[] = [
    { key: 'ArrowUp', onTrigger: () => step(-1) },
    { key: 'ArrowLeft', onTrigger: () => step(-1) },
    { key: 'ArrowDown', onTrigger: () => step(1) },
    { key: 'ArrowRight', onTrigger: () => step(1) },
    {
      key: 'Escape',
      onTrigger: () => {
        if (isolatedKey) showAll();
      },
    },
    { key: 'PageUp', onTrigger: () => void wb.stepPage(kind, -1) },
    { key: 'PageDown', onTrigger: () => void wb.stepPage(kind, 1) },
    ...extraBindings,
  ];

  return {
    currentIndex,
    flashingKey,
    setItemRef,
    step,
    showAll,
    bindings,
  };
}
