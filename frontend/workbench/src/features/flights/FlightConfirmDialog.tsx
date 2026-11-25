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

export type ConfirmDialogState = { kind: 'match'; keys: string[]; force: boolean } | null;

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
          <AlertDialogTitle>提交航班匹配</AlertDialogTitle>
          <AlertDialogDescription>
            {`确认提交 ${dialog?.keys.length ?? 0} 条航班进行路径匹配？`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>确认提交</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
