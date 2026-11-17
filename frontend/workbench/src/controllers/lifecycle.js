/** Owns resources created by one application boot. Disposal is idempotent. */
export function createLifecycle() {
  const cleanups = [];
  let disposed = false;
  const frames = new Set();
  const timers = new Set();
  return {
    get disposed() { return disposed; },
    own(cleanup) { if (disposed) cleanup(); else cleanups.push(cleanup); return cleanup; },
    listen(target, type, listener, options) {
      target.addEventListener(type, listener, options);
      this.own(() => target.removeEventListener(type, listener, options));
    },
    observe(target, callback) {
      const observer = new ResizeObserver(callback);
      observer.observe(target);
      this.own(() => observer.disconnect());
      return observer;
    },
    frame(callback) {
      if (disposed) return;
      const id = requestAnimationFrame(() => { frames.delete(id); if (!disposed) callback(); });
      frames.add(id);
      return id;
    },
    timeout(callback, delay = 0) {
      if (disposed) return;
      const id = setTimeout(() => { timers.delete(id); if (!disposed) callback(); }, delay);
      timers.add(id);
      return id;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      frames.forEach(id => cancelAnimationFrame(id)); frames.clear();
      timers.forEach(clearTimeout); timers.clear();
      const errors = [];
      for (const cleanup of cleanups.splice(0).reverse()) {
        try { cleanup(); } catch (error) { errors.push(error); }
      }
      if (errors.length) console.error('Workbench cleanup failed', errors);
    },
  };
}
export const applicationLifecycle = createLifecycle();
