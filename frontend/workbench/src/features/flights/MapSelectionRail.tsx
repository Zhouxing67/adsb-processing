import type * as React from 'react';
import type { MapFlightEntry } from '../../api/types';
import { useWorkbench } from '../../app/WorkbenchContext';
import { StudioIcon } from '../layout/StudioIcon';

const colors = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#B77900', '#56B4E9', '#E69F00', '#6A3D9A', '#1B9E77', '#E7298A'];

interface MapSelectionRailProps {
  splitView: boolean;
}

export function MapSelectionRail({ splitView }: MapSelectionRailProps) {
  const wb = useWorkbench();

  const updateMapEntry = (key: string, patch: Partial<MapFlightEntry>) => {
    const entry = wb.mapFlights.get(key);
    if (entry) wb.dispatch({ type: 'map-flight', key, value: { ...entry, ...patch } });
  };

  const sortedFlights = [...wb.mapFlights].sort((a, b) => a[1].slot - b[1].slot);

  return (
    <aside className="selected-section map-selection left-rail-panel">
      <div className="section-title">
        <div>
          <small>地图内容</small>
          <strong>地图展示</strong>
        </div>
        <span>{wb.mapFlights.size} 架航班</span>
      </div>
      <div className="selected-flights">
        {wb.mapFlights.size === 0 && <p className="field-note">尚无地图展示航班</p>}
        {sortedFlights.map(([key, entry]) => {
          const isolated = wb.isolatedFlightKey === key;
          return (
            <div
              className="selected-chip"
              key={key}
              style={{ '--slot-color': colors[entry.slot % colors.length] } as React.CSSProperties}
            >
              <div className="selected-flight-main">
                <b>{entry.slot + 1}</b>
                <span>{entry.label}</span>
                <div>
                  <button
                    className="flight-isolate-action"
                    aria-label={isolated ? '恢复全部航班' : `仅显示 ${entry.label}`}
                    aria-pressed={isolated}
                    title={isolated ? '恢复全部地图航班' : '仅显示此航班'}
                    onClick={() => wb.dispatch({ type: 'isolate-flight', key: isolated ? null : key })}
                  >
                    <StudioIcon name="visibility" />
                  </button>
                  <button
                    className="flight-remove-action"
                    aria-label={`移除 ${entry.label}`}
                    title="移出地图"
                    onClick={() => wb.dispatch({ type: 'map-flight', key, value: null })}
                  >
                    <StudioIcon name="close" />
                  </button>
                </div>
              </div>
              <div className="selected-flight-options">
                <label>
                  <input
                    type="checkbox"
                    checked={entry.trajectoryVisible}
                    onChange={event => updateMapEntry(key, { trajectoryVisible: event.target.checked })}
                  />
                  轨迹
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={entry.pathVisible}
                    disabled={!entry.geometry.path}
                    onChange={event => updateMapEntry(key, { pathVisible: event.target.checked })}
                  />
                  路径
                </label>
              </div>
            </div>
          );
        })}
      </div>
      <div className="selection-actions">
        <span>已显示 {wb.mapFlights.size} 架航班</span>
        <div className="selection-action-buttons">
          <button
            className="text-button"
            disabled={!wb.mapFlights.size}
            title="缩放地图以显示全部已加入航班"
            onClick={() => wb.dispatch({ type: 'fit-map-flights', preserveView: splitView })}
          >
            适配全部
          </button>
          <button
            className="text-button"
            disabled={!wb.mapFlights.size}
            onClick={() => wb.dispatch({ type: 'clear-map-flights' })}
          >
            清空
          </button>
        </div>
      </div>
    </aside>
  );
}
