import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import type { FlightDetail } from '../../api/types';
import { useWorkbench } from '../../app/WorkbenchContext';

interface ObservationViewProps {
  detail: FlightDetail | null;
  splitView: boolean;
}

export function ObservationView({ detail, splitView }: ObservationViewProps) {
  const wb = useWorkbench();
  const [current, setCurrent] = useState(detail);
  const [allFields, setAllFields] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setCurrent(detail);
    setAllFields(Boolean(detail?.all_fields));
    setError('');
  }, [detail]);

  if (!detail) {
    return (
      <section className="main-view observations-view">
        <p className="field-note">请从航班目录打开详情。</p>
      </section>
    );
  }
  if (!current) return null;

  const load = async (page: number, expanded = allFields) => {
    setLoading(true);
    setError('');
    try {
      const value = await api.detail(detail.summary.flight_key, page, expanded);
      setCurrent(value);
      setAllFields(expanded);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '观测记录加载失败');
    } finally {
      setLoading(false);
    }
  };

  const locate = (row: Record<string, unknown>) => {
    const find = (...names: string[]) => {
      const key = Object.keys(row).find(item => names.includes(item.toLowerCase()));
      return key ? row[key] : undefined;
    };
    const longitude = Number(find('longitude', 'lon'));
    const latitude = Number(find('latitude', 'lat'));
    if (Number.isFinite(longitude) && Number.isFinite(latitude)) {
      wb.dispatch({ type: 'observation-location', value: [latitude, longitude], preserveView: splitView });
    }
  };

  return (
    <section className="main-view observations-view">
      <header className="observations-header">
        <button className="secondary-button" onClick={() => wb.dispatch({ type: 'view', value: 'flights' })}>
          ← 航班列表
        </button>
        <div>
          <small>当前查看航班</small>
          <h2>{current.summary.flight_number || current.summary.flight_id}</h2>
          <p>{current.observation_total} 个观测点</p>
        </div>
        <button
          className="secondary-button"
          disabled={!wb.observationLocation}
          onClick={() => wb.dispatch({ type: 'observation-location', value: null, preserveView: splitView })}
        >
          清除地图定位点
        </button>
      </header>
      <div className="observations-content">
        <div className="observation-toolbar">
          <button className="secondary-button" disabled={loading} onClick={() => void load(1, !allFields)}>
            {allFields ? '显示默认字段' : '显示全部字段'}
          </button>
          <span>
            第 {current.observation_page || 0} / {current.observation_pages} 页，共 {current.observation_total} 条
          </span>
        </div>
        {error && <p className="field-error" role="alert">{error}</p>}
        <table className="sheet-table observation-table">
          <thead>
            <tr>
              {current.observation_columns.map(column => (
                <th key={column}>{column}</th>
              ))}
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {current.observations.map((row, index) => (
              <tr key={index}>
                {current.observation_columns.map(column => (
                  <td key={column}>{String(row[column] ?? '—')}</td>
                ))}
                <td>
                  <button className="secondary-button" onClick={() => locate(row)}>
                    在地图中定位
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="observation-pager">
          <button disabled={loading || current.observation_page <= 1} onClick={() => void load(current.observation_page - 1)}>
            上一页
          </button>
          <button
            disabled={loading || current.observation_page >= current.observation_pages}
            onClick={() => void load(current.observation_page + 1)}
          >
            下一页
          </button>
        </div>
        {loading && <div className="busy"><span /></div>}
      </div>
    </section>
  );
}
