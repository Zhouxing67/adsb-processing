import { useEffect, useState } from 'react';
import type { GeoFeature, NodeProperties, PointGeometry, SelectedFeature } from '../../api/types';
import { useWorkbench } from '../../app/WorkbenchContext';
import { aerowayTypes, propertyPatch } from '../../domain/properties';
import type { Aeroway } from '../../domain/properties';

function isNode(feature: SelectedFeature): feature is GeoFeature<PointGeometry, NodeProperties> {
  return feature.geometry.type === 'Point';
}

function edgeLabel(id: { u: string; v: string; key: number }) {
  return `${id.u}—${id.v} · ${id.key}`;
}

const fieldLabels: Record<string, string> = {
  aeroway: '类型',
  name: '名称',
  ref: '编号',
  source_type: '来源',
  u: '起点',
  v: '终点',
  key: 'Key',
  geometry_length_m: '长度',
  validation_color: '验证颜色',
  degree: '连接数',
  longitude: '经度',
  latitude: '纬度',
};

const basicKeys = new Set(['aeroway', 'name', 'ref', 'source_type']);
const topologyKeys = new Set(['u', 'v', 'key', 'geometry_length_m', 'degree', 'longitude', 'latitude']);

export function FeatureDetails() {
  const wb = useWorkbench();
  const feature = wb.selected;
  const attributes = feature?.properties.editable_attributes ?? {};
  const [aeroway, setAeroway] = useState('');
  const [name, setName] = useState('');
  const [ref, setRef] = useState('');
  const [validationError, setValidationError] = useState('');

  useEffect(() => {
    setAeroway(String(attributes.aeroway ?? ''));
    setName(String(attributes.name ?? ''));
    setRef(String(attributes.ref ?? ''));
    setValidationError('');
  }, [feature, attributes.aeroway, attributes.name, attributes.ref]);

  if (!feature || !wb.detailsOpen) return null;

  const node = isNode(feature);
  const entries = Object.entries(feature.properties).filter(([key]) => !['editable_attributes', 'id'].includes(key));
  const basicEntries = entries.filter(([key]) => basicKeys.has(key));
  const topologyEntries = entries.filter(([key]) => topologyKeys.has(key));
  const inspectionEntries = entries.filter(([key]) => key.startsWith('validation'));
  const otherEntries = entries.filter(
    ([key]) => !basicKeys.has(key) && !topologyKeys.has(key) && !key.startsWith('validation'),
  );

  const formatValue = (key: string, value: unknown) =>
    key === 'geometry_length_m' && value != null
      ? `${value} m`
      : key === 'source_type' && typeof value === 'string'
        ? value.toUpperCase()
        : String(value ?? '—');

  const renderFields = (title: string, fields: Array<[string, unknown]>) =>
    fields.length ? (
      <section className="details-section">
        <h3>{title}</h3>
        <dl>
          {fields.map(([key, value]) => (
            <div key={key}>
              <dt>
                <span>{fieldLabels[key] ?? key}</span>
                {fieldLabels[key] && <small>{key}</small>}
              </dt>
              <dd>
                {key === 'validation_color' && typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) && (
                  <i className="property-color" style={{ background: value }} />
                )}
                {formatValue(key, value)}
              </dd>
            </div>
          ))}
        </dl>
      </section>
    ) : null;

  const save = async () => {
    let patch: Record<string, unknown>;
    try {
      patch = propertyPatch({ aeroway, name, ref }) as unknown as Record<string, unknown>;
      setValidationError('');
    } catch (error) {
      setValidationError(error instanceof Error ? error.message : '属性校验失败');
      return;
    }
    const body = node
      ? { node: feature.properties.id, attributes: patch }
      : { edge: feature.properties.id, attributes: patch };
    const result = await wb.runGraphCommand(node ? '/api/update-node' : '/api/update-edge', body);
    if (result !== null) wb.dispatch({ type: 'selected', value: null });
  };

  const customAeroway = aeroway && !aerowayTypes.includes(aeroway as Aeroway);

  return (
    <aside className="details panel">
      <button className="panel-close" onClick={() => wb.dispatch({ type: 'selected', value: null })}>
        ×
      </button>
      <div className="details-content">
        <small>图要素详情 · {node ? '节点' : '边'}</small>
        <h2>{node ? feature.properties.id : edgeLabel(feature.properties.id)}</h2>
        {renderFields('基本信息', basicEntries)}
        {renderFields('拓扑信息', topologyEntries)}
        {renderFields('检查状态', inspectionEntries)}
        {renderFields('其他属性', otherEntries)}
        {wb.state?.capabilities.can_edit_graph && (
          <section className="details-section property-form">
            <h3>可编辑属性</h3>
            <label>
              <span>类型 <small>aeroway</small></span>
              <select
                value={aeroway}
                onChange={event => {
                  setAeroway(event.target.value);
                  setValidationError('');
                }}
              >
                <option value="">（无）</option>
                {aerowayTypes.map(item => (
                  <option key={item} value={item}>{item}</option>
                ))}
                {customAeroway && <option value={aeroway}>{aeroway}（非标准）</option>}
              </select>
            </label>
            <label>
              <span>名称 <small>name</small></span>
              <input value={name} onChange={event => setName(event.target.value)} />
            </label>
            <label>
              <span>编号 <small>ref</small></span>
              <input value={ref} onChange={event => setRef(event.target.value)} />
            </label>
            {validationError && <p className="field-error" role="alert">{validationError}</p>}
            <button className="primary-button" onClick={() => void save()}>
              保存属性
            </button>
          </section>
        )}
      </div>
    </aside>
  );
}
