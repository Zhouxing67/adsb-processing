import { useEffect } from 'react';
import type { MutableRefObject } from 'react';
import L from 'leaflet';
import type { Map as LeafletMap } from 'leaflet';
import type { GeoBounds } from '@/domain/geometry';
import { MAP_SELECTION_COLOR } from '@/domain/palette';

interface UseMapBoxSelectOptions {
  mapRef: MutableRefObject<LeafletMap | null>;
  previewRendererRef: MutableRefObject<L.Renderer | null>;
  boxSelectHandler: MutableRefObject<((bounds: GeoBounds) => void) | undefined>;
  enabled: boolean;
  sticky: boolean;
}

export function useMapBoxSelect({
  mapRef,
  previewRendererRef,
  boxSelectHandler,
  enabled,
  sticky,
}: UseMapBoxSelectOptions) {
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const container = map.getContainer();
    if (!enabled) {
      map.boxZoom.enable();
      map.dragging.enable();
      container.style.cursor = '';
      return;
    }

    map.boxZoom.disable();
    if (sticky) {
      map.dragging.disable();
      container.style.cursor = 'crosshair';
    } else {
      map.dragging.enable();
      container.style.cursor = '';
    }

    let startLatLng: L.LatLng | null = null;
    let startClient: { x: number; y: number } | null = null;
    let boxLayer: L.Rectangle | null = null;
    let moved = false;
    let suppressNextClick = false;

    const cleanupDrag = () => {
      if (boxLayer) {
        boxLayer.remove();
        boxLayer = null;
      }
      startLatLng = null;
      startClient = null;
      moved = false;
      if (!sticky) map.dragging.enable();
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };

    const onMouseMove = (event: MouseEvent) => {
      if (!startLatLng || !startClient) return;
      const dist = Math.hypot(event.clientX - startClient.x, event.clientY - startClient.y);
      if (dist >= 6) moved = true;
      if (!moved) return;
      const current = map.mouseEventToLatLng(event);
      const bounds = L.latLngBounds(startLatLng, current);
      if (!boxLayer) {
        boxLayer = L.rectangle(bounds, {
          pane: 'previewPane',
          renderer: previewRendererRef.current ?? undefined,
          color: MAP_SELECTION_COLOR,
          weight: 2,
          dashArray: '6 4',
          fillColor: MAP_SELECTION_COLOR,
          fillOpacity: 0.14,
          interactive: false,
        }).addTo(map);
      } else {
        boxLayer.setBounds(bounds);
      }
    };

    const onMouseUp = (event: MouseEvent) => {
      if (!startLatLng) return;
      const didMove = moved;
      const bounds = didMove ? L.latLngBounds(startLatLng, map.mouseEventToLatLng(event)) : null;
      cleanupDrag();
      if (didMove && bounds) {
        suppressNextClick = true;
        window.setTimeout(() => {
          suppressNextClick = false;
        }, 0);
        boxSelectHandler.current?.({
          minLng: bounds.getWest(),
          maxLng: bounds.getEast(),
          minLat: bounds.getSouth(),
          maxLat: bounds.getNorth(),
        });
      }
    };

    const onMouseDown = (event: MouseEvent) => {
      if (event.button !== 0) return;
      if (!sticky && !event.shiftKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('.leaflet-control')) return;
      event.preventDefault();
      map.dragging.disable();
      startLatLng = map.mouseEventToLatLng(event);
      startClient = { x: event.clientX, y: event.clientY };
      moved = false;
      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
    };

    const onClickCapture = (event: MouseEvent) => {
      if (!suppressNextClick) return;
      event.stopPropagation();
      event.preventDefault();
      suppressNextClick = false;
    };

    container.addEventListener('mousedown', onMouseDown);
    container.addEventListener('click', onClickCapture, true);
    return () => {
      cleanupDrag();
      container.removeEventListener('mousedown', onMouseDown);
      container.removeEventListener('click', onClickCapture, true);
      map.boxZoom.enable();
      map.dragging.enable();
      container.style.cursor = '';
    };
  }, [mapRef, previewRendererRef, boxSelectHandler, enabled, sticky]);
}
