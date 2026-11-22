import { useWorkbench } from '../../app/WorkbenchContext';
import { StudioIcon } from './StudioIcon';

interface MapToolbarProps {
  editing: boolean;
  onEditing(): void;
}

export function MapToolbar({ editing, onEditing }: MapToolbarProps) {
  const wb = useWorkbench();
  return (
    <div className="map-tools panel">
      <button
        aria-label="搜索"
        title="搜索图要素"
        onClick={() => wb.dispatch({ type: 'panel', panel: 'searchOpen', value: !wb.searchOpen })}
      >
        <StudioIcon name="search" />
      </button>
      <button
        aria-label="拓扑检查"
        title="拓扑检查"
        onClick={() => wb.dispatch({ type: 'panel', panel: 'topologyOpen', value: !wb.topologyOpen })}
      >
        <StudioIcon name="topology" />
      </button>
      {wb.state?.capabilities.can_edit_graph && (
        <button className={editing ? 'active' : ''} aria-pressed={editing} onClick={onEditing}>
          {editing ? '退出编辑' : '编辑图'}
        </button>
      )}
    </div>
  );
}
