import { useEffect, useState } from 'react';
import { useWorkbench } from '@/app/WorkbenchContext';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { aerowayTypes } from '@/domain/properties';
import type { Aeroway } from '@/domain/properties';
import type { EdgeIdentity, NodeId, StandCluster } from '@/api/types';

interface EditorToolOverlayProps {
  revision: number;
  mergeNodeIds: NodeId[];
  clusterEdges: EdgeIdentity[];
  standClusters: StandCluster[];
  selectionCount: number;
  drawAeroway: Aeroway;
  drawRef: string;
  onDrawAerowayChange(value: Aeroway): void;
  onDrawRefChange(value: string): void;
  onOpenMergeCandidates(): Promise<void>;
  onPreviewMerge(nodeIds: NodeId[], revision: number): Promise<void>;
  onCreateCluster(name: string): Promise<boolean>;
  onAssignCluster(cId: number | null): Promise<boolean>;
  onUndoDrawPoint(): void;
  onReset(): void;
}

export function EditorToolOverlay({
  revision,
  mergeNodeIds,
  clusterEdges,
  standClusters,
  selectionCount,
  drawAeroway,
  drawRef,
  onDrawAerowayChange,
  onDrawRefChange,
  onOpenMergeCandidates,
  onPreviewMerge,
  onCreateCluster,
  onAssignCluster,
  onUndoDrawPoint,
  onReset,
}: EditorToolOverlayProps) {
  const wb = useWorkbench();
  const [newClusterName, setNewClusterName] = useState('');
  const [targetClusterId, setTargetClusterId] = useState('');

  const targetStillExists =
    targetClusterId !== '' && standClusters.some(cluster => String(cluster.c_id) === targetClusterId);
  const effectiveTargetClusterId = targetStillExists ? targetClusterId : '';

  useEffect(() => {
    if (targetClusterId !== '' && !targetStillExists) {
      setTargetClusterId('');
    }
  }, [targetClusterId, targetStillExists]);

  if (wb.tool !== 'merge' && wb.tool !== 'draw' && wb.tool !== 'cluster') return null;

  const handleCreateCluster = async () => {
    if (await onCreateCluster(newClusterName)) {
      setNewClusterName('');
    }
  };

  const handleAssignCluster = async () => {
    const parsed = Number(effectiveTargetClusterId);
    if (!Number.isInteger(parsed) || parsed < 1) return;
    await onAssignCluster(parsed);
  };

  return (
    <div className="pointer-events-none absolute left-[224px] top-3.5 z-[700] flex max-w-[calc(100%-240px)] flex-wrap items-start gap-2">
      {wb.tool === 'merge' && (
        <Card className="pointer-events-auto flex flex-wrap items-center gap-1.5 bg-background/95 p-1.5 shadow-sm">
          <Button variant="outline" size="sm" onClick={() => void onOpenMergeCandidates()}>
            重复节点候选
          </Button>
          <Button
            variant="default"
            size="sm"
            disabled={mergeNodeIds.length < 2}
            onClick={() => void onPreviewMerge(mergeNodeIds, revision)}
          >
            检查并合并（{mergeNodeIds.length}）
          </Button>
          <Button variant="ghost" size="sm" onClick={onReset}>
            清空选择
          </Button>
        </Card>
      )}
      {wb.tool === 'cluster' && (
        <Card className="pointer-events-auto flex flex-wrap items-center gap-1.5 bg-background/95 p-1.5 shadow-sm">
          <Badge variant="secondary" className="h-7 px-2 text-xs tabular-nums">
            已选 {clusterEdges.length} 条机位
          </Badge>
          <Input
            aria-label="新类别名称"
            placeholder="新类别名称（可选）"
            className="h-7 w-36 text-xs"
            value={newClusterName}
            onChange={event => setNewClusterName(event.target.value)}
          />
          <Button
            variant="default"
            size="sm"
            disabled={wb.busy || clusterEdges.length === 0}
            onClick={() => void handleCreateCluster()}
          >
            加入新类别
          </Button>
          {standClusters.length > 0 && (
            <>
              <Select value={effectiveTargetClusterId} onValueChange={setTargetClusterId}>
                <SelectTrigger aria-label="选择已有类别" className="h-7 w-[150px] text-xs">
                  <SelectValue placeholder="选择已有类别" />
                </SelectTrigger>
                <SelectContent>
                  {standClusters.map(cluster => (
                    <SelectItem key={cluster.c_id} value={String(cluster.c_id)}>
                      #{cluster.c_id} {cluster.name ? `· ${cluster.name}` : ''}（{cluster.stands.length}）
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="outline"
                size="sm"
                disabled={wb.busy || clusterEdges.length === 0 || !effectiveTargetClusterId}
                onClick={() => void handleAssignCluster()}
              >
                加入已有类别
              </Button>
            </>
          )}
          <Button
            variant="outline"
            size="sm"
            disabled={wb.busy || clusterEdges.length === 0}
            onClick={() => void onAssignCluster(null)}
          >
            移出类别
          </Button>
          <Button variant="ghost" size="sm" disabled={wb.busy || clusterEdges.length === 0} onClick={onReset}>
            清空
          </Button>
        </Card>
      )}
      {wb.tool === 'draw' && (
        <Card className="pointer-events-auto flex flex-wrap items-center gap-1.5 bg-background/95 p-1.5 shadow-sm">
          <Select value={drawAeroway} onValueChange={value => onDrawAerowayChange(value as Aeroway)}>
            <SelectTrigger aria-label="绘制边类型" className="h-7 w-[140px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {aerowayTypes.map(item => (
                <SelectItem key={item} value={item}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            aria-label="绘制边编号"
            placeholder="编号 ref（可选）"
            className="h-7 w-32 text-xs"
            value={drawRef}
            onChange={event => onDrawRefChange(event.target.value)}
          />
          {selectionCount > 0 && (
            <Button variant="outline" size="sm" onClick={onUndoDrawPoint}>
              撤销形状点
            </Button>
          )}
          {selectionCount > 0 && (
            <Button variant="ghost" size="sm" onClick={onReset}>
              取消
            </Button>
          )}
        </Card>
      )}
    </div>
  );
}
