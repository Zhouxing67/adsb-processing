export interface PixelPoint { x: number; y: number }
export interface PopupSize { width: number; height: number; gap: number }
/** Geometry only. It never moves the map or changes application state. */
export function popupPosition(point: PixelPoint, viewport: PixelPoint, popup: PopupSize): PixelPoint {
  let x = point.x - popup.width / 2;
  let y = point.y - popup.height - popup.gap;
  if (y < 8) {
    y = point.y + popup.gap;
    if (y + popup.height > viewport.y - 8) {
      y = Math.max(8, Math.min(viewport.y - popup.height - 8, point.y - popup.height / 2));
      x = point.x + popup.gap;
      if (x + popup.width > viewport.x - 8) x = point.x - popup.width - popup.gap;
    }
  }
  return { x: Math.max(8, Math.min(viewport.x - popup.width - 8, x)), y };
}
