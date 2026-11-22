import type { WorkbenchState } from '../../api/types';

export interface LayerSettings {
  base: 'none' | 'osm' | 'satellite';
  edges: boolean;
  parking: boolean;
  nodes: boolean;
}

interface InspectorProps {
  state: WorkbenchState;
  layers: LayerSettings;
  onLayers(value: LayerSettings): void;
}

export function Inspector({ state, layers, onLayers }: InspectorProps) {
  const parking = state.edges.features.filter(item => item.properties.aeroway === 'parking_position').length;
  const derived = state.edges.features.length - parking;

  return (
    <aside className="studio-inspector">
      <div className="inspector-inner">
        <h1>机场地面网络</h1>
        <div className="studio-metrics">
          <div>
            <strong>{state.node_count}</strong>
            <span>节点</span>
          </div>
          <div>
            <strong>{state.edge_count}</strong>
            <span>边</span>
          </div>
          {state.flight_mode && (
            <div>
              <strong>{state.flight_count}</strong>
              <span>航班</span>
            </div>
          )}
        </div>
        <section>
          <h3>图层与底图</h3>
          <div className="layer-options">
            <label>
              <input
                type="radio"
                name="base-layer"
                checked={layers.base === 'osm'}
                onChange={() => onLayers({ ...layers, base: 'osm' })}
              />
              OpenStreetMap
            </label>
            <label>
              <input
                type="radio"
                name="base-layer"
                checked={layers.base === 'satellite'}
                onChange={() => onLayers({ ...layers, base: 'satellite' })}
              />
              ESRI 卫星
            </label>
            <label>
              <input
                type="radio"
                name="base-layer"
                checked={layers.base === 'none'}
                onChange={() => onLayers({ ...layers, base: 'none' })}
              />
              无底图（精细编辑）
            </label>
            <hr />
            <label>
              <input
                type="checkbox"
                checked={layers.edges}
                onChange={event => onLayers({ ...layers, edges: event.target.checked })}
              />
              派生边（{derived}）
            </label>
            <label>
              <input
                type="checkbox"
                checked={layers.parking}
                onChange={event => onLayers({ ...layers, parking: event.target.checked })}
              />
              停机位（{parking}）
            </label>
            <label>
              <input
                type="checkbox"
                checked={layers.nodes}
                onChange={event => onLayers({ ...layers, nodes: event.target.checked })}
              />
              图节点（{state.node_count}）
            </label>
          </div>
        </section>
        <section>
          <h3>地图图例</h3>
          <div className="inspector-legend">
            <span><i className="legend-dot" />普通节点</span>
            <span><i className="legend-line parking" />停机位</span>
            <span><i className="legend-badge">R</i>跑道接口</span>
            <span><i className="legend-line derived" />派生边</span>
            <span><i className="legend-line flight" />虚线＝原始轨迹</span>
            <span><i className="legend-line path" />实线＝匹配路径</span>
          </div>
        </section>
        <section className="inspector-empty">
          <div>⌖</div>
          <h3>选择一个图要素</h3>
        </section>
      </div>
    </aside>
  );
}
