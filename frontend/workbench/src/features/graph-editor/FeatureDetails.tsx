import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { formatEdgeId, isNodeFeature } from '@/domain/features';
import { aerowayTypes, propertyPatch } from '@/domain/properties';
import type { Aeroway } from '@/domain/properties';

const fieldLabels: Record<string, string> = {
  aeroway: '类型',
  name: '名称',
  ref: '编号',
  cluster_id: '机位类别',
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

const basicKeys = new Set(['aeroway', 'name', 'ref', 'cluster_id', 'source_type']);
const topologyKeys = new Set(['u', 'v', 'key', 'geometry_length_m', 'degree', 'longitude', 'latitude']);

export function FeatureDetails() {
  const wb = useWorkbench();
  const feature = wb.selected;
  const attributes = feature?.properties.editable_attributes ?? {};
  const [aeroway, setAeroway] = useState('');
  const [name, setName] = useState('');
  const [ref, setRef] = useState('');
  const [clusterIdValue, setClusterIdValue] = useState('__none__');
  const [validationError, setValidationError] = useState('');

  useEffect(() => {
    setAeroway(String(attributes.aeroway ?? ''));
    setName(String(attributes.name ?? ''));
    setRef(String(attributes.ref ?? ''));
    const currentCluster =
      feature && !isNodeFeature(feature) && feature.properties.cluster_id != null
        ? String(feature.properties.cluster_id)
        : '__none__';
    setClusterIdValue(currentCluster);
    setValidationError('');
  }, [feature, attributes.aeroway, attributes.name, attributes.ref]);

  if (!feature || !wb.detailsOpen) return null;

  const node = isNodeFeature(feature);
  const entries = Object.entries(feature.properties).filter(([key]) => !['editable_attributes', 'id'].includes(key));
  const basicEntries = entries.filter(([key]) => basicKeys.has(key));
  const topologyEntries = entries.filter(([key]) => topologyKeys.has(key));
  const inspectionEntries = entries.filter(([key]) => key.startsWith('validation'));
  const otherEntries = entries.filter(
    ([key]) => !basicKeys.has(key) && !topologyKeys.has(key) && !key.startsWith('validation'),
  );

  const standClusters = wb.state?.stand_clusters ?? [];
  const currentClusterId = !node ? (feature.properties.cluster_id ?? null) : null;
  const clusterValueExists =
    clusterIdValue === '__none__' || standClusters.some(cluster => String(cluster.c_id) === clusterIdValue);
  const effectiveClusterValue = clusterValueExists ? clusterIdValue : '__none__';

  const formatValue = (key: string, value: unknown) => {
    if (key === 'geometry_length_m' && value != null) return `${value} m`;
    if (key === 'source_type' && typeof value === 'string') return value.toUpperCase();
    if (key === 'cluster_id') {
      if (typeof value !== 'number') return '未分类';
      const found = standClusters.find(cluster => cluster.c_id === value);
      return found?.name ? `#${value} · ${found.name}` : `#${value}`;
    }
    return String(value ?? '—');
  };

  const renderFields = (title: string, fields: Array<[string, unknown]>) =>
    fields.length ? (
      <section className="border-t border-border py-4">
        <h3 className="mb-2.5 text-xs font-semibold text-foreground">{title}</h3>
        <dl className="m-0 divide-y divide-border/60 text-xs">
          {fields.map(([key, value]) => (
            <div key={key} className="grid grid-cols-[minmax(90px,40%)_minmax(0,1fr)] gap-2 py-1.5">
              <dt className="text-muted-foreground">
                <span className="block">{fieldLabels[key] ?? key}</span>
                {fieldLabels[key] && <small className="block text-[11px] text-muted-foreground/75">{key}</small>}
              </dt>
              <dd className="m-0 flex items-center gap-1.5 break-words text-foreground tabular-nums">
                {key === 'validation_color' && typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) && (
                  <i className="h-3 w-3 shrink-0 rounded-[2px] border border-border" style={{ background: value }} />
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

  const isParkingEdge = !node && feature.properties.aeroway === 'parking_position';
  const nextClusterId = effectiveClusterValue === '__none__' ? null : Number(effectiveClusterValue);
  const clusterUnchanged = nextClusterId === currentClusterId;
  const saveCluster = async () => {
    if (node || clusterUnchanged) return;
    const result = await wb.runGraphCommand('/api/stand-clusters/assign', {
      edges: [feature.properties.id],
      c_id: nextClusterId,
    });
    if (result !== null) wb.dispatch({ type: 'selected', value: null });
  };

  const customAeroway = aeroway && !aerowayTypes.includes(aeroway as Aeroway);

  return (
    <aside className="details relative flex h-full min-h-0 w-full flex-col bg-background">
      <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-5">
        <div className="flex min-w-0 items-center gap-2">
          <h2 className="m-0 truncate text-[15px] font-semibold text-foreground" title={node ? feature.properties.id : formatEdgeId(feature.properties.id)}>
            {node ? feature.properties.id : formatEdgeId(feature.properties.id)}
          </h2>
          <Badge variant="secondary" className="shrink-0">
            {node ? '节点' : '边'}
          </Badge>
        </div>
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label="关闭要素详情"
          onClick={() => wb.dispatch({ type: 'selected', value: null })}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="px-5 py-2">
        {renderFields('基本信息', basicEntries)}
        {renderFields('拓扑信息', topologyEntries)}
        {renderFields('检查状态', inspectionEntries)}
        {renderFields('其他属性', otherEntries)}

        {wb.state?.capabilities.can_edit_graph && isParkingEdge && (
          <section className="grid gap-3 border-t border-border py-4">
            <h3 className="m-0 text-xs font-semibold text-foreground">机位类别</h3>
            <div className="grid gap-1 text-xs text-muted-foreground">
              <span className="flex items-baseline gap-1">
                所属类别 <small className="text-[11px] text-muted-foreground/75">cluster_id</small>
              </span>
              <Select value={effectiveClusterValue} onValueChange={setClusterIdValue}>
                <SelectTrigger aria-label="所属类别" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">（未分类）</SelectItem>
                  {standClusters.map(cluster => (
                    <SelectItem key={cluster.c_id} value={String(cluster.c_id)}>
                      #{cluster.c_id}
                      {cluster.name ? ` · ${cluster.name}` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button variant="outline" disabled={wb.busy || clusterUnchanged} onClick={() => void saveCluster()}>
              更新类别
            </Button>
          </section>
        )}

        {wb.state?.capabilities.can_edit_graph && (
          <section className="property-form grid gap-3 border-t border-border py-4">
            <h3 className="m-0 text-xs font-semibold text-foreground">可编辑属性</h3>
            <div className="grid gap-1 text-xs text-muted-foreground">
              <span className="flex items-baseline gap-1">
                类型 <small className="text-[11px] text-muted-foreground/75">aeroway</small>
              </span>
              <Select
                value={aeroway || '__empty__'}
                onValueChange={value => {
                  setAeroway(value === '__empty__' ? '' : value);
                  setValidationError('');
                }}
              >
                <SelectTrigger aria-label="类型" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__empty__">（无）</SelectItem>
                  {aerowayTypes.map(item => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                  {customAeroway && <SelectItem value={aeroway}>{aeroway}（非标准）</SelectItem>}
                </SelectContent>
              </Select>
            </div>
            <Label className="grid gap-1 font-normal text-muted-foreground">
              <span className="flex items-baseline gap-1">
                名称 <small className="text-[11px] text-muted-foreground/75">name</small>
              </span>
              <Input value={name} onChange={event => setName(event.target.value)} />
            </Label>
            <Label className="grid gap-1 font-normal text-muted-foreground">
              <span className="flex items-baseline gap-1">
                编号 <small className="text-[11px] text-muted-foreground/75">ref</small>
              </span>
              <Input value={ref} onChange={event => setRef(event.target.value)} />
            </Label>
            {validationError && (
              <Alert variant="destructive">
                <AlertDescription>{validationError}</AlertDescription>
              </Alert>
            )}
            <Button variant="default" onClick={() => void save()}>
              保存属性
            </Button>
          </section>
        )}
        </div>
      </ScrollArea>
    </aside>
  );
}
