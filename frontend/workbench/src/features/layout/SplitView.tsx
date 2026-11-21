import { useEffect, useRef } from 'react';

const storageKey = 'airport-workbench.map-split-width';

function setRatio(value: number) {
  const ratio = Math.max(25, Math.min(75, value));
  document.documentElement.style.setProperty('--map-split-width', `${ratio}%`);
  try { localStorage.setItem(storageKey, String(ratio)); } catch { /* storage is optional */ }
  window.dispatchEvent(new Event('resize'));
  return ratio;
}

export function RestoreSplitRatio() {
  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      const stored = raw === null ? Number.NaN : Number(raw);
      if (Number.isFinite(stored)) setRatio(stored);
    } catch { /* storage is optional */ }
  }, []);
  return null;
}

export function SplitViewGrip() {
  const handle = useRef<HTMLButtonElement>(null);
  const dragging = useRef(false);
  const ratioAt = (clientX: number) => {
    const workspace = handle.current?.parentElement?.getBoundingClientRect();
    if (!workspace?.width) return 50;
    return (clientX - workspace.left) / workspace.width * 100;
  };
  const updateAria = (ratio: number) => handle.current?.setAttribute('aria-valuenow', String(Math.round(ratio)));

  return <button
    ref={handle}
    className="workspace-split-grip"
    role="separator"
    aria-label="调整地图与航班比例"
    aria-orientation="vertical"
    aria-valuemin={25}
    aria-valuemax={75}
    onPointerDown={event => {
      dragging.current = true;
      event.currentTarget.setPointerCapture(event.pointerId);
      event.preventDefault();
    }}
    onPointerMove={event => {
      if (!dragging.current || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
      updateAria(setRatio(ratioAt(event.clientX)));
    }}
    onPointerUp={event => {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      dragging.current = false;
    }}
    onLostPointerCapture={() => { dragging.current = false; }}
    onKeyDown={event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return;
      event.preventDefault();
      const current = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--map-split-width')) || 50;
      updateAria(setRatio(event.key === 'Home' ? 50 : current + (event.key === 'ArrowRight' ? 5 : -5)));
    }}
  />;
}
