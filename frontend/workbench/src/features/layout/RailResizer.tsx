import { useEffect, useRef } from 'react';

type Side = 'left' | 'right';
const legacyStorageKey = 'airport-workbench.sidebar-width';
const defaultWidth = 304;

function cssVar(side: Side): string {
  return side === 'left' ? '--left-sidebar-width' : '--right-sidebar-width';
}

function storageKeyFor(side: Side): string {
  return `airport-workbench.${side}-sidebar-width`;
}

function limits() {
  const styles = getComputedStyle(document.documentElement);
  return {
    minimum: Number.parseFloat(styles.getPropertyValue('--sidebar-min-width')) || 240,
    maximum: Number.parseFloat(styles.getPropertyValue('--sidebar-max-width')) || 480,
  };
}

function setWidth(side: Side, value: number) {
  const { minimum, maximum } = limits();
  const width = Math.round(Math.max(minimum, Math.min(maximum, value)));
  document.documentElement.style.setProperty(cssVar(side), `${width}px`);
  try {
    localStorage.setItem(storageKeyFor(side), String(width));
  } catch {
    /* storage is optional */
  }
  window.dispatchEvent(new Event('resize'));
  return width;
}

export function RestoreRailWidth() {
  useEffect(() => {
    const restore = (side: Side) => {
      try {
        const raw = localStorage.getItem(storageKeyFor(side)) ?? localStorage.getItem(legacyStorageKey);
        const stored = raw === null ? Number.NaN : Number(raw);
        if (Number.isFinite(stored)) setWidth(side, stored);
      } catch {
        /* storage is optional */
      }
    };
    restore('left');
    restore('right');
  }, []);
  return null;
}

export function RailResizer({ side }: { side: Side }) {
  const handle = useRef<HTMLButtonElement>(null);
  const drag = useRef<{ x: number; width: number } | null>(null);
  const direction = side === 'left' ? 1 : -1;

  const updateAria = (width: number) => {
    const { minimum, maximum } = limits();
    handle.current?.setAttribute('aria-valuemin', String(minimum));
    handle.current?.setAttribute('aria-valuemax', String(maximum));
    handle.current?.setAttribute('aria-valuenow', String(width));
  };

  const currentWidth = () =>
    Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue(cssVar(side))) || defaultWidth;

  return (
    <button
      ref={handle}
      className={`sidebar-resizer sidebar-resizer-${side}`}
      role="separator"
      aria-label={side === 'left' ? '调整左侧栏宽度' : '调整右侧栏宽度'}
      aria-orientation="vertical"
      title="拖动调整侧栏宽度 · 方向键微调 · 双击恢复"
      onPointerDown={event => {
        drag.current = { x: event.clientX, width: currentWidth() };
        event.currentTarget.setPointerCapture(event.pointerId);
        document.body.classList.add('sidebar-resizing');
        event.preventDefault();
      }}
      onPointerMove={event => {
        if (!drag.current || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
        updateAria(setWidth(side, drag.current.width + (event.clientX - drag.current.x) * direction));
      }}
      onPointerUp={event => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
        drag.current = null;
        document.body.classList.remove('sidebar-resizing');
      }}
      onLostPointerCapture={() => {
        drag.current = null;
        document.body.classList.remove('sidebar-resizing');
      }}
      onDoubleClick={() => updateAria(setWidth(side, defaultWidth))}
      onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return;
        event.preventDefault();
        const step = event.shiftKey ? 32 : 8;
        const delta =
          event.key === 'Home'
            ? defaultWidth - currentWidth()
            : (event.key === 'ArrowRight' ? 1 : -1) * direction * step;
        updateAria(setWidth(side, currentWidth() + delta));
      }}
    />
  );
}
