import { useEffect, useMemo, useState } from 'react';
import { useWorkbench } from '../../app/WorkbenchContext';

interface TopologyPanelProps {
  splitValidation: boolean;
  onSplitValidation(): void;
}

export function TopologyPanel({ splitValidation, onSplitValidation }: TopologyPanelProps) {
  const wb = useWorkbench();
  const topology = wb.state?.topology;
  const [reviewIndex, setReviewIndex] = useState(-1);

  const nodes = useMemo(
    () => [...(wb.state?.nodes.features ?? [])].sort((a, b) => a.properties.id.localeCompare(b.properties.id)),
    [wb.state?.nodes.features],
  );

  useEffect(() => {
    setReviewIndex(current => (current >= nodes.length ? (nodes.length ? nodes.length - 1 : -1) : current));
  }, [nodes.length]);

  const showReview = (index: number) => {
    const feature = nodes[index];
    if (!feature) return;
    setReviewIndex(index);
    wb.dispatch({ type: 'selected', value: feature, focus: true });
    wb.dispatch({
      type: 'status',
      value:
        index === nodes.length - 1
          ? '已到最后一个节点；这不表示全部复核通过'
          : `遍历位置 ${index + 1} / ${nodes.length} · 节点 ${feature.properties.id}`,
    });
  };

  if (!wb.topologyOpen || !topology) return null;

  const summary: Array<[string, number]> = [
    ['连通分量', topology.component_count],
    ['最大分量', topology.largest_component],
  ];
  const anomalies: Array<[string, number]> = [
    ['孤立节点', topology.isolated_count],
    ['悬挂节点', topology.dangling_count],
    ['平行边组', topology.parallel_pair_count],
  ];

  return (
    <aside className="topology-panel panel">
      <div className="panel-heading">
        <div>
          <small>网络健康检查</small>
          <h2>拓扑概览</h2>
        </div>
        <button className="panel-close" onClick={() => wb.dispatch({ type: 'panel', panel: 'topologyOpen', value: false })}>
          ×
        </button>
      </div>
      <div className="topology-summary">
        {summary.map(([label, value]) => (
          <div key={label}>
            <strong>{value}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>
      <section className="topology-section">
        <h3>异常</h3>
        <dl className="topology-status-list">
          {anomalies.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd className={value > 0 ? 'has-issue' : ''}>{value}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="topology-section">
        <h3>辅助检查</h3>
        <div className="topology-setting">
          <span>
            <strong>相邻边辨色</strong>
            <small>提高共享节点附近边的辨识度</small>
          </span>
          <button
            className="secondary-button"
            aria-label={`${splitValidation ? '关闭' : '开启'}相邻边辨色`}
            aria-pressed={splitValidation}
            onClick={onSplitValidation}
          >
            {splitValidation ? '关闭' : '开启'}
          </button>
        </div>
      </section>
      {topology.component_count > 1 && (
        <section className="topology-section topology-details">
          <h3>连通分量</h3>
          {topology.components.slice(0, 20).map(component => (
            <button
              className="secondary-button"
              key={component.index}
              onClick={() => {
                const node = wb.state?.nodes.features.find(item => component.node_ids.includes(item.properties.id));
                if (node) wb.dispatch({ type: 'selected', value: node, focus: true });
              }}
            >
              分量 {component.index} · {component.size} 节点
            </button>
          ))}
        </section>
      )}
      <section className="topology-section node-review">
        <h3>逐点检查</h3>
        <p className="field-note">
          {reviewIndex >= 0 ? `遍历位置 ${reviewIndex + 1} / ${nodes.length} · 节点 ${nodes[reviewIndex]?.properties.id}` : '尚未开始'}
        </p>
        <div className="node-review-actions">
          <button disabled={!nodes.length} onClick={() => showReview(0)}>开始</button>
          <button disabled={reviewIndex <= 0} onClick={() => showReview(reviewIndex - 1)}>上一个</button>
          <button disabled={reviewIndex < 0 || reviewIndex >= nodes.length - 1} onClick={() => showReview(reviewIndex + 1)}>下一个</button>
          <button disabled={reviewIndex < 0} onClick={() => { setReviewIndex(-1); wb.dispatch({ type: 'selected', value: null }); }}>结束</button>
        </div>
      </section>
    </aside>
  );
}
