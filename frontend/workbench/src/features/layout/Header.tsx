import { useState } from 'react';
import { PanelLeft, PanelRight, Undo2 } from 'lucide-react';
import { useWorkbench } from '@/app/WorkbenchContext';
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
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { IconActionButton } from '@/components/ui/workbench-shell';

interface HeaderProps {
  editing: boolean;
  leftOpen: boolean;
  rightOpen: boolean;
  showRightToggle?: boolean;
  onLeft(): void;
  onRight(): void;
}

export function Header({ editing, leftOpen, rightOpen, showRightToggle = true, onLeft, onRight }: HeaderProps) {
  const wb = useWorkbench();
  const state = wb.state;
  const [finishOpen, setFinishOpen] = useState(false);

  const command = async (path: '/api/undo' | '/api/save' | '/api/finish') => {
    await wb.runGraphCommand(path);
  };

  return (
    <header className="relative z-[1200] col-span-full row-start-1 flex h-14 items-center gap-2.5 border-b border-border bg-background px-4">
      <IconActionButton
        className="text-muted-foreground hover:text-foreground"
        label="切换左侧栏"
        tooltip={leftOpen ? '收起左侧栏' : '展开左侧栏'}
        aria-expanded={leftOpen}
        onClick={onLeft}
      >
        <PanelLeft className="h-4 w-4" />
      </IconActionButton>

      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-primary text-xs font-bold tracking-tight text-primary-foreground shadow-xs">
        AW
      </div>

      <div className="flex min-w-0 flex-col leading-tight">
        <div className="flex items-center gap-2">
          <strong className="truncate text-sm font-semibold text-foreground">Airport Workbench</strong>
          {wb.hasUnsavedChanges && (
            <Badge variant="warning" title="有未保存的图修改">
              未保存
            </Badge>
          )}
        </div>
        <span className="truncate text-[11px] text-muted-foreground tabular-nums">
          {!state
            ? '载入中…'
            : state.flight_mode
              ? '航班工作台'
              : `${state.node_count} 节点 · ${state.edge_count} 边`}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        {state?.capabilities.can_edit_graph && editing && (
          <>
            <Button
              variant="ghost"
              size="sm"
              disabled={!state.can_undo}
              onClick={() => void command('/api/undo')}
            >
              <Undo2 className="h-3.5 w-3.5" />
              撤销
            </Button>
            <Button variant="default" size="sm" onClick={() => void command('/api/save')}>
              保存
            </Button>
            {state.can_finish && (
              <Button variant="secondary" size="sm" onClick={() => setFinishOpen(true)}>
                完成
              </Button>
            )}
          </>
        )}
      </div>

      {showRightToggle && (
        <IconActionButton
          className="text-muted-foreground hover:text-foreground"
          label="切换右侧栏"
          tooltip={rightOpen ? '收起右侧栏' : '展开右侧栏'}
          aria-expanded={rightOpen}
          onClick={onRight}
        >
          <PanelRight className="h-4 w-4" />
        </IconActionButton>
      )}

      <AlertDialog open={finishOpen} onOpenChange={setFinishOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>完成并保存机场图？</AlertDialogTitle>
            <AlertDialogDescription>确认后将保存当前修改并结束编辑会话。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setFinishOpen(false);
                void command('/api/finish');
              }}
            >
              确认完成
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </header>
  );
}
