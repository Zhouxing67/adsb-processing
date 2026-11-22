import { Modal } from 'antd';
import { useWorkbench } from '../../app/WorkbenchContext';
import { StudioIcon } from './StudioIcon';

interface HeaderProps {
  editing: boolean;
  leftOpen: boolean;
  rightOpen: boolean;
  onLeft(): void;
  onRight(): void;
}

export function Header({ editing, leftOpen, rightOpen, onLeft, onRight }: HeaderProps) {
  const wb = useWorkbench();
  const state = wb.state;
  const command = async (path: '/api/undo' | '/api/save' | '/api/finish') => {
    await wb.runGraphCommand(path);
  };

  const confirmFinish = () => {
    Modal.confirm({
      title: '完成并保存机场图？',
      content: '确认后将保存当前修改并结束编辑会话。',
      okText: '确认完成',
      cancelText: '取消',
      onOk: () => command('/api/finish'),
    });
  };

  return (
    <header className="topbar panel">
      <button className="rail-toggle" aria-label="切换左侧栏" aria-expanded={leftOpen} onClick={onLeft}>
        <StudioIcon name="leftRail" />
      </button>
      <div className="brand-mark">AW</div>
      <div className="brand-copy">
        <strong>
          Airport Workbench
          {wb.hasUnsavedChanges && <em className="unsaved-dot" title="有未保存的图修改"> · 未保存</em>}
        </strong>
        <span>
          {state
            ? `${state.node_count} 节点 · ${state.edge_count} 边${state.flight_mode ? ` · ${state.flight_count} 航班` : ''}`
            : '载入中…'}
        </span>
      </div>
      <div className="top-actions">
        {state?.capabilities.can_edit_graph && editing && (
          <>
            <button className="text-button" disabled={!state.can_undo} onClick={() => void command('/api/undo')}>
              撤销
            </button>
            <button className="save-button" onClick={() => void command('/api/save')}>
              保存
            </button>
            {state.can_finish && (
              <button className="finish-button" onClick={confirmFinish}>
                完成
              </button>
            )}
          </>
        )}
      </div>
      <button className="rail-toggle" aria-label="切换右侧栏" aria-expanded={rightOpen} onClick={onRight}>
        <StudioIcon name="rightRail" />
      </button>
    </header>
  );
}
