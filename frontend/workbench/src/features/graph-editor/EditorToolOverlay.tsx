import { useWorkbench } from '@/app/WorkbenchContext';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { aerowayTypes } from '@/domain/properties';
import type { Aeroway } from '@/domain/properties';
import type { NodeId } from '@/api/types';

interface EditorToolOverlayProps {
  revision: number;
  mergeNodeIds: NodeId[];
  selectionCount: number;
  drawAeroway: Aeroway;
  drawRef: string;
  onDrawAerowayChange(value: Aeroway): void;
  onDrawRefChange(value: string): void;
  onOpenMergeCandidates(): Promise<void>;
  onPreviewMerge(nodeIds: NodeId[], revision: number): Promise<void>;
  onUndoDrawPoint(): void;
  onReset(): void;
}

export function EditorToolOverlay({
  revision,
  mergeNodeIds,
  selectionCount,
  drawAeroway,
  drawRef,
  onDrawAerowayChange,
  onDrawRefChange,
  onOpenMergeCandidates,
  onPreviewMerge,
  onUndoDrawPoint,
  onReset,
}: EditorToolOverlayProps) {
  const wb = useWorkbench();
  if (wb.tool !== 'merge' && wb.tool !== 'draw') return null;

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
