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

export type ConfirmDialogState =
  | { kind: 'match'; keys: string[]; force: boolean }
  | { kind: 'bulk-map'; pending: string[] }
  | null;

interface FlightConfirmDialogProps {
  dialog: ConfirmDialogState;
  onClose(): void;
  onConfirm(): void;
}

export function FlightConfirmDialog({ dialog, onClose, onConfirm }: FlightConfirmDialogProps) {
  return (
    <AlertDialog open={dialog !== null} onOpenChange={open => { if (!open) onClose(); }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {dialog?.kind === 'bulk-map' ? '批量加入地图确认' : '提交航班匹配'}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {dialog?.kind === 'bulk-map'
              ? `即将向地图加入 ${dialog.pending.length} 架航班，数量较大可能影响地图流畅度，是否继续？`
              : `确认提交 ${dialog?.keys.length ?? 0} 条航班进行路径匹配？`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>
            {dialog?.kind === 'bulk-map' ? '继续加入' : '确认提交'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
