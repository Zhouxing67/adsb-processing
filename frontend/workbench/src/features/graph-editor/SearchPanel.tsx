import { useState } from 'react';
import type { SelectedFeature } from '../../api/types';
import { useWorkbench } from '../../app/WorkbenchContext';

function edgeLabel(id: { u: string; v: string; key: number }) {
  return `${id.u}—${id.v} · ${id.key}`;
}

export function SearchPanel() {
  const wb = useWorkbench();
  const [query, setQuery] = useState('');
  const [stand, setStand] = useState('');
  const [edgeU, setEdgeU] = useState('');
  const [edgeV, setEdgeV] = useState('');

  if (!wb.searchOpen || !wb.state) return null;

  const select = (feature: SelectedFeature | undefined, label: string) => {
    if (feature) wb.dispatch({ type: 'selected', value: feature, focus: true });
    else wb.dispatch({ type: 'status', value: `未找到 ${label}` });
  };

  const search = () => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) {
      wb.dispatch({ type: 'status', value: '请输入节点 ID 或边 ID' });
      return;
    }
    select(
      wb.state!.nodes.features.find(item => item.properties.id.toLocaleLowerCase().includes(needle)) ??
        wb.state!.edges.features.find(item => edgeLabel(item.properties.id).toLocaleLowerCase().includes(needle)),
      query.trim(),
    );
  };

  const searchStand = () => {
    const needle = stand.trim().toLocaleLowerCase();
    if (!needle) {
      wb.dispatch({ type: 'status', value: '请输入机位编号' });
      return;
    }
    select(
      wb.state!.edges.features.find(item => String(item.properties.ref ?? '').toLocaleLowerCase() === needle),
      `机位 ${stand.trim()}`,
    );
  };

  const searchEdge = () => {
    const u = edgeU.trim();
    const v = edgeV.trim();
    if (!u || !v) {
      wb.dispatch({ type: 'status', value: '请输入边的两个端点 ID' });
      return;
    }
    const pair = [u, v].sort().join('|');
    select(
      wb.state!.edges.features.find(item => [item.properties.u, item.properties.v].map(String).sort().join('|') === pair),
      `边 ${u}—${v}`,
    );
  };

  return (
    <section className="search-panel panel">
      <div className="panel-heading">
        <div>
          <small>快速定位</small>
          <h2>搜索图要素</h2>
        </div>
        <button className="panel-close" onClick={() => wb.dispatch({ type: 'panel', panel: 'searchOpen', value: false })}>
          ×
        </button>
      </div>
      <label>
        节点或边 ID
        <div className="input-action">
          <input
            value={query}
            onChange={event => setQuery(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') search(); }}
            placeholder="节点 ID 或完整边 ID"
          />
          <button onClick={search}>选中</button>
        </div>
      </label>
      <label>
        机位编号
        <div className="input-action">
          <input
            value={stand}
            onChange={event => setStand(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') searchStand(); }}
            placeholder="例如 A01"
          />
          <button onClick={searchStand}>定位机位</button>
        </div>
      </label>
      <label>
        边的两个端点
        <div className="edge-inputs">
          <input
            value={edgeU}
            onChange={event => setEdgeU(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') searchEdge(); }}
            placeholder="端点 A"
          />
          <span>—</span>
          <input
            value={edgeV}
            onChange={event => setEdgeV(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') searchEdge(); }}
            placeholder="端点 B"
          />
          <button onClick={searchEdge}>选中边</button>
        </div>
      </label>
    </section>
  );
}
