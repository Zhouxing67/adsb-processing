import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import type { PendingBulkMapConfirm } from './useMapBatchLoader';

interface MapBatchConfirmDialogProps {
  dialog: PendingBulkMapConfirm | null;
  onClose(): void;
}

export function MapBatchConfirmDialog({ dialog, onClose }: MapBatchConfirmDialogProps) {
  return (
    <AlertDialog open={dialog !== null} onOpenChange={open => { if (!open) onClose(); }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>批量加入地图确认</AlertDialogTitle>
          <AlertDialogDescription>
            {dialog
              ? `即将向地图加入 ${dialog.count} 条${dialog.unitLabel}，数量较大可能影响地图流畅度，是否继续？`
              : ''}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction onClick={() => dialog?.onConfirm()}>
            继续加入
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
