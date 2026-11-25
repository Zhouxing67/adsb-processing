import { useEffect, useRef } from 'react';

export interface KeyboardShortcutBinding {
  /** Key value matched against KeyboardEvent.key (case-insensitive for single letters). */
  key: string;
  /** Handler invoked when the shortcut matches. */
  onTrigger(event: KeyboardEvent): void;
  /** Prevent browser default scrolling/behavior when matched (default true). */
  preventDefault?: boolean;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (target.closest('[role="dialog"], [role="alertdialog"], [role="listbox"]')) return true;
  return false;
}

function matchesKey(eventKey: string, bindingKey: string): boolean {
  if (bindingKey.length === 1) {
    return eventKey.toLowerCase() === bindingKey.toLowerCase();
  }
  return eventKey === bindingKey;
}

export function useKeyboardShortcuts(
  bindings: KeyboardShortcutBinding[],
  enabled = true,
): void {
  const bindingsRef = useRef(bindings);
  bindingsRef.current = bindings;

  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
      if (isEditableTarget(event.target)) return;
      for (const binding of bindingsRef.current) {
        if (!matchesKey(event.key, binding.key)) continue;
        if (binding.preventDefault !== false) event.preventDefault();
        binding.onTrigger(event);
        return;
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [enabled]);
}

interface KeyboardShortcutsProps {
  enabled?: boolean;
  bindings: KeyboardShortcutBinding[];
}

/** Declarative shared keyboard-shortcut listener component. */
export function KeyboardShortcuts({ enabled = true, bindings }: KeyboardShortcutsProps) {
  useKeyboardShortcuts(bindings, enabled);
  return null;
}
