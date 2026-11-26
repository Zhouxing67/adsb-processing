import { useEffect, useState } from 'react';
import { Check, Pencil, Trash2, X } from 'lucide-react';
import type { StandCluster } from '@/api/types';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { IconActionButton } from '@/components/ui/workbench-shell';
import { formatClusterLabel } from '@/domain/features';
import { standClusterColor } from '@/domain/palette';

interface StandClusterPanelProps {
  clusters: StandCluster[];
  totalParkingEdges: number;
  clusteredParkingEdges: number;
  canEdit: boolean;
}

export function StandClusterPanel({
  clusters,
  totalParkingEdges,
  clusteredParkingEdges,
  canEdit,
}: StandClusterPanelProps) {
  const wb = useWorkbench();
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftName, setDraftName] = useState('');

  useEffect(() => {
    if (editingId !== null && !clusters.some(cluster => cluster.c_id === editingId)) {
      setEditingId(null);
      setDraftName('');
    }
  }, [clusters, editingId]);

  const startRename = (cluster: StandCluster) => {
    setEditingId(cluster.c_id);
    setDraftName(cluster.name ?? '');
  };

  const commitRename = async (cId: number) => {
    const result = await wb.runGraphCommand('/api/stand-clusters/rename', {
      c_id: cId,
      name: draftName.trim() || null,
    });
    if (result !== null) {
      setEditingId(null);
      setDraftName('');
    }
  };

  const removeCluster = async (cId: number) => {
    await wb.runGraphCommand('/api/stand-clusters/delete', { c_id: cId });
    if (editingId === cId) setEditingId(null);
  };

  return (
    <section className="space-y-3 border-b border-border pb-5">
      <div className="flex items-center justify-between gap-2">
        <h3 className="m-0 text-xs font-semibold text-foreground">机位类别</h3>
        <Badge variant="secondary" className="h-5 px-1.5 text-[11px] tabular-nums">
          {clusteredParkingEdges} / {totalParkingEdges}
        </Badge>
      </div>
      {clusters.length === 0 ? (
        <p className="m-0 text-[11px] text-muted-foreground">
          暂无机位类别{canEdit ? '，可在左侧「机位聚类」工具中多选机位创建' : ''}
        </p>
      ) : (
        <ul className="m-0 grid list-none gap-1.5 p-0">
          {clusters.map(cluster => {
            const editing = editingId === cluster.c_id;
            return (
              <li
                key={cluster.c_id}
                className="flex items-center justify-between gap-1.5 rounded-md border border-border/70 bg-muted/30 px-2 py-1.5 text-xs"
              >
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <i
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ background: standClusterColor(cluster.c_id) }}
                  />
                  {editing ? (
                    <Input
                      aria-label={`编辑类别 #${cluster.c_id} 名称`}
                      className="h-6 text-xs"
                      value={draftName}
                      onChange={event => setDraftName(event.target.value)}
                      onKeyDown={event => {
                        if (event.key === 'Enter') void commitRename(cluster.c_id);
                        if (event.key === 'Escape') setEditingId(null);
                      }}
                    />
                  ) : (
                    <span className="truncate text-foreground" title={cluster.stand_refs.join(', ')}>
                      {formatClusterLabel(cluster)}
                    </span>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-0.5">
                  {editing ? (
                    <>
                      <IconActionButton
                        size="icon-xs"
                        disabled={wb.busy}
                        label="保存类别名称"
                        tooltip="保存"
                        onClick={() => void commitRename(cluster.c_id)}
                      >
                        <Check className="h-3.5 w-3.5" />
                      </IconActionButton>
                      <IconActionButton
                        size="icon-xs"
                        disabled={wb.busy}
                        label="取消编辑"
                        tooltip="取消"
                        onClick={() => setEditingId(null)}
                      >
                        <X className="h-3.5 w-3.5" />
                      </IconActionButton>
                    </>
                  ) : (
                    <>
                      <Badge variant="outline" className="h-5 px-1.5 text-[11px] tabular-nums">
                        {cluster.stands.length}
                      </Badge>
                      {canEdit && (
                        <>
                          <IconActionButton
                            size="icon-xs"
                            disabled={wb.busy}
                            label={`重命名类别 #${cluster.c_id}`}
                            tooltip="重命名"
                            onClick={() => startRename(cluster)}
                          >
                            <Pencil className="h-3 w-3" />
                          </IconActionButton>
                          <IconActionButton
                            size="icon-xs"
                            disabled={wb.busy}
                            label={`删除类别 #${cluster.c_id}`}
                            tooltip="删除类别"
                            onClick={() => void removeCluster(cluster.c_id)}
                          >
                            <Trash2 className="h-3 w-3 text-destructive" />
                          </IconActionButton>
                        </>
                      )}
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
