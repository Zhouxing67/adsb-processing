import { useEffect, useRef, useState } from 'react';
import { Splitter } from 'antd';
import type { FlightDetail } from '../api/types';
import { aerowayTypes } from '../domain/properties';
import type { Aeroway } from '../domain/properties';
import { FlightPanel } from '../features/flights/FlightPanel';
import { MapSelectionRail } from '../features/flights/MapSelectionRail';
import { ObservationView } from '../features/flights/ObservationView';
import { FeatureDetails } from '../features/graph-editor/FeatureDetails';
import { GraphDialog } from '../features/graph-editor/GraphDialog';
import { Inspector } from '../features/graph-editor/Inspector';
import type { LayerSettings } from '../features/graph-editor/Inspector';
import { SearchPanel } from '../features/graph-editor/SearchPanel';
import { ToolDock } from '../features/graph-editor/ToolDock';
import { TopologyPanel } from '../features/graph-editor/TopologyPanel';
import { useGraphEditorMachine } from '../features/graph-editor/useGraphEditorMachine';
import { Header } from '../features/layout/Header';
import { MapToolbar } from '../features/layout/MapToolbar';
import { RailResizer, RestoreRailWidth } from '../features/layout/RailResizer';
import { MapView } from '../features/map/MapView';
import { ErrorBoundary } from './ErrorBoundary';
import { WorkbenchProvider, useWorkbench } from './WorkbenchContext';
import type { MainView } from './WorkbenchContext';
import '../styles/react-app.css';

function Workspace() {
  const wb = useWorkbench();
  const state = wb.state;
  const [detail, setDetail] = useState<FlightDetail | null>(null);
  const [splitValidation, setSplitValidation] = useState(false);
  const [graphEditing, setGraphEditing] = useState(false);
  const [splitView, setSplitView] = useState(false);
  const [mapRight, setMapRight] = useState(false);
  const [mapSize, setMapSize] = useState(() => {
    try {
      const value = Number(localStorage.getItem('airport-workbench.map-split-width'));
      return value >= 25 && value <= 75 ? value : 50;
    } catch {
      return 50;
    }
  });
  const [draggedView, setDraggedView] = useState<MainView | null>(null);
  const [dropSide, setDropSide] = useState<'left' | 'right' | null>(null);
  const [splitterResizing, setSplitterResizing] = useState(false);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [layers, setLayers] = useState<LayerSettings>({ base: 'none', edges: true, parking: true, nodes: false });
  const workspaceRef = useRef<HTMLElement>(null);
  const editor = useGraphEditorMachine();

  useEffect(() => {
    document.body.classList.add('unified-workbench', 'react-workbench');
    document.body.classList.toggle('flight-mode', Boolean(state?.flight_mode));
    document.body.classList.toggle('read-only', Boolean(state?.flight_mode));
    return () => document.body.classList.remove('unified-workbench', 'react-workbench', 'flight-mode', 'read-only');
  }, [state?.flight_mode]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    return () => window.cancelAnimationFrame(frame);
  }, [splitView, leftOpen, rightOpen, state?.flight_mode]);

  useEffect(() => {
    if (editor.dialog || (wb.selected && wb.detailsOpen)) setRightOpen(true);
  }, [editor.dialog, wb.selected, wb.detailsOpen]);

  useEffect(() => {
    if (!splitView) setSplitterResizing(false);
  }, [splitView]);

  useEffect(() => {
    const target = workspaceRef.current;
    if (!target || !splitView) return;
    const observer = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width ?? 0;
      if (width > 0 && width < 640) {
        setSplitView(false);
        setSplitterResizing(false);
      }
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, [splitView]);

  if (!state) return <main className="loading-screen">{wb.error || '正在载入工作台…'}</main>;

  const topologyLeft = leftOpen && wb.topologyOpen;
  const editorLeft = !state.flight_mode && leftOpen && graphEditing;
  const flightLeft = state.flight_mode && leftOpen && !topologyLeft;
  const shellLeft = topologyLeft || editorLeft || flightLeft;

  const rightContent = editor.dialog ? (
    <GraphDialog
      dialog={editor.dialog}
      onClose={editor.reset}
      onPreview={editor.setPreviewGeometry}
      onConfirm={editor.confirmDialog}
      onMergeCandidate={editor.previewMerge}
    />
  ) : wb.selected && wb.detailsOpen ? (
    <FeatureDetails />
  ) : (
    <Inspector state={state} layers={layers} onLayers={setLayers} />
  );

  const toggleEditing = () => {
    const next = !graphEditing;
    setGraphEditing(next);
    if (next) {
      setLeftOpen(true);
    } else {
      wb.dispatch({ type: 'tool', value: 'inspect' });
      editor.reset();
    }
  };

  const visibleMapFlights =
    wb.isolatedFlightKey && wb.mapFlights.has(wb.isolatedFlightKey)
      ? new Map([[wb.isolatedFlightKey, wb.mapFlights.get(wb.isolatedFlightKey)!]])
      : wb.mapFlights;

  const startDrag = (event: React.DragEvent, view: MainView) => {
    setDraggedView(view);
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', view);
  };

  const dropIntoWorkspace = (event: React.DragEvent<HTMLElement>) => {
    if (!draggedView) return;
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const side = event.clientX < rect.left + rect.width / 2 ? 'left' : 'right';
    setSplitView(true);
    setMapRight(draggedView === 'map' ? side === 'right' : side === 'left');
    wb.dispatch({ type: 'view', value: draggedView === 'map' ? (wb.view === 'map' ? 'flights' : wb.view) : draggedView });
    setDraggedView(null);
    setDropSide(null);
  };

  const returnToSingleView = (event: React.DragEvent) => {
    if (!draggedView) return;
    event.preventDefault();
    setSplitView(false);
    setMapRight(false);
    wb.dispatch({ type: 'view', value: draggedView });
    setDraggedView(null);
    setDropSide(null);
  };

  const mapContent = (
    <section className={`main-view map-view ${wb.view !== 'map' && !splitView ? 'hidden' : ''}`}>
      <MapView
        state={state}
        flights={visibleMapFlights}
        splitValidation={splitValidation}
        baseLayer={layers.base}
        showEdges={layers.edges}
        showParking={layers.parking}
        showNodes={layers.nodes || wb.topologyOpen || graphEditing}
        selected={[...editor.selection, ...(wb.selected ? [wb.selected] : [])]}
        drawPoints={editor.drawPoints}
        previewGeometry={editor.previewGeometry}
        focusFlightRequest={wb.mapFocusRequest}
        focusFeatureRequest={wb.focusFeatureRequest}
        fitMapVersion={wb.fitMapVersion}
        observationLocation={wb.observationLocation}
        onFeature={editor.handleFeature}
        onMapClick={editor.handleMapClick}
      />
      <MapToolbar editing={graphEditing} onEditing={toggleEditing} />
      <div className="map-overlay-stack">
        {wb.tool === 'merge' && (
          <>
            <button className="secondary-button panel" onClick={() => void editor.openMergeCandidates()}>
              重复节点候选
            </button>
            <button
              className="primary-button panel"
              disabled={editor.mergeNodeIds.length < 2}
              onClick={() => void editor.previewMerge(editor.mergeNodeIds, state.revision)}
            >
              检查并合并（{editor.mergeNodeIds.length}）
            </button>
            <button className="secondary-button panel" onClick={editor.reset}>
              清空选择
            </button>
          </>
        )}
        {wb.tool === 'draw' && (
          <div className="draw-options panel">
            <select
              aria-label="绘制边类型"
              value={editor.drawAeroway}
              onChange={event => editor.setDrawAeroway(event.target.value as Aeroway)}
            >
              {aerowayTypes.map(item => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
            <input
              aria-label="绘制边编号"
              placeholder="编号 ref（可选）"
              value={editor.drawRef}
              onChange={event => editor.setDrawRef(event.target.value)}
            />
            {editor.selection.length > 0 && (
              <button className="secondary-button" onClick={editor.undoDrawPoint}>
                撤销形状点
              </button>
            )}
            {editor.selection.length > 0 && (
              <button className="secondary-button" onClick={editor.reset}>
                取消
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );

  const secondaryContent = (
    <>
      {state.flight_mode && (
        <FlightPanel
          active={wb.view === 'flights' || (splitView && wb.view !== 'observations')}
          splitView={splitView}
          onDetail={setDetail}
        />
      )}
      {state.flight_mode && wb.view === 'observations' && <ObservationView detail={detail} splitView={splitView} />}
    </>
  );

  const splitPanels = mapRight
    ? [
        <Splitter.Panel className="workspace-pane" key="secondary" defaultSize={`${100 - mapSize}%`} min="25%" max="75%">
          {secondaryContent}
        </Splitter.Panel>,
        <Splitter.Panel className="workspace-pane" key="map" defaultSize={`${mapSize}%`} min="25%" max="75%">
          {mapContent}
        </Splitter.Panel>,
      ]
    : [
        <Splitter.Panel className="workspace-pane" key="map" defaultSize={`${mapSize}%`} min="25%" max="75%">
          {mapContent}
        </Splitter.Panel>,
        <Splitter.Panel className="workspace-pane" key="secondary" defaultSize={`${100 - mapSize}%`} min="25%" max="75%">
          {secondaryContent}
        </Splitter.Panel>,
      ];

  const showFlightBanner = state.flight_mode && (Boolean(wb.error) || (Boolean(wb.status) && wb.status !== '航班工作台'));
  const tabTitle = splitView ? '拖回标签栏退出分屏，或拖到内容区切换左右分屏' : '拖到内容区左侧或右侧分屏';

  return (
    <div
      className={`app-shell ${state.flight_mode ? 'flight-shell' : ''} ${splitView ? 'flight-split-view' : ''} ${mapRight ? 'flight-map-right' : ''} ${shellLeft ? 'with-left-rail' : ''} ${rightOpen ? 'with-right-rail' : ''}`}
    >
      <RestoreRailWidth />
      <Header
        editing={graphEditing}
        leftOpen={leftOpen}
        rightOpen={rightOpen}
        onLeft={() => setLeftOpen(value => !value)}
        onRight={() => setRightOpen(value => !value)}
      />
      {topologyLeft ? (
        <TopologyPanel splitValidation={splitValidation} onSplitValidation={() => setSplitValidation(value => !value)} />
      ) : editorLeft ? (
        <ToolDock />
      ) : (
        flightLeft && <MapSelectionRail splitView={splitView} />
      )}
      {state.flight_mode && (
        <nav
          className={`main-tabs ${splitView && draggedView ? 'tabs-drop-target' : ''}`}
          aria-label="航班主视图"
          onDragOver={event => { if (draggedView) event.preventDefault(); }}
          onDrop={returnToSingleView}
        >
          <button
            draggable
            title={tabTitle}
            className={wb.view === 'map' ? 'active' : ''}
            onDragStart={event => startDrag(event, 'map')}
            onDragEnd={() => { setDraggedView(null); setDropSide(null); }}
            onClick={() => wb.dispatch({ type: 'view', value: 'map' })}
          >
            地图
          </button>
          <button
            draggable
            title={tabTitle}
            className={wb.view === 'flights' ? 'active' : ''}
            onDragStart={event => startDrag(event, 'flights')}
            onDragEnd={() => { setDraggedView(null); setDropSide(null); }}
            onClick={() => wb.dispatch({ type: 'view', value: 'flights' })}
          >
            航班
          </button>
          {detail && (
            <button
              draggable
              title={tabTitle}
              className={wb.view === 'observations' ? 'active' : ''}
              onDragStart={event => startDrag(event, 'observations')}
              onDragEnd={() => { setDraggedView(null); setDropSide(null); }}
              onClick={() => wb.dispatch({ type: 'view', value: 'observations' })}
            >
              观测记录
            </button>
          )}
        </nav>
      )}
      <main
        ref={workspaceRef}
        className={`workspace react-workspace ${splitterResizing ? 'splitter-resizing' : ''}`}
        onDragOver={event => {
          if (!draggedView) return;
          event.preventDefault();
          const rect = event.currentTarget.getBoundingClientRect();
          setDropSide(event.clientX < rect.left + rect.width / 2 ? 'left' : 'right');
        }}
        onDragLeave={event => {
          if (!event.currentTarget.contains(event.relatedTarget as Node)) setDropSide(null);
        }}
        onDrop={dropIntoWorkspace}
      >
        {state.flight_mode && splitView ? (
          <Splitter
            className="flight-workspace-splitter"
            onResizeStart={() => setSplitterResizing(true)}
            onResizeEnd={sizes => {
              setSplitterResizing(false);
              const total = sizes.reduce((sum, size) => sum + size, 0);
              const mapPixels = mapRight ? sizes[1] : sizes[0];
              const next = total > 0 ? (mapPixels / total) * 100 : 50;
              setMapSize(next);
              try {
                localStorage.setItem('airport-workbench.map-split-width', String(next));
              } catch {
                /* storage is optional */
              }
            }}
          >
            {splitPanels}
          </Splitter>
        ) : (
          <>
            {mapContent}
            {secondaryContent}
          </>
        )}
        {dropSide && <div className={`workspace-drop-hint drop-${dropSide}`}>在{dropSide === 'left' ? '左' : '右'}侧打开</div>}
        {showFlightBanner && (
          <div className={`flight-status-toast panel ${wb.error ? 'is-error' : ''}`} role={wb.error ? 'alert' : 'status'}>
            <span>{wb.error || wb.status}</span>
            <button
              className="panel-close"
              aria-label="关闭提示"
              onClick={() => wb.dispatch({ type: 'status', value: '航班工作台' })}
            >
              ×
            </button>
          </div>
        )}
      </main>
      <SearchPanel />
      {rightOpen && <div className="right-rail">{rightContent}</div>}
      {shellLeft && <RailResizer side="left" />}
      {rightOpen && <RailResizer side="right" />}
      <div className={`status panel ${wb.error ? 'is-error' : ''}`}>
        <span>{wb.error || wb.status}</span>
        {wb.error && (
          <button
            className="status-dismiss"
            aria-label="清除错误"
            onClick={() => wb.dispatch({ type: 'clear-error' })}
          >
            ×
          </button>
        )}
      </div>
      {wb.busy && <div className="busy"><span /></div>}
    </div>
  );
}

export function App() {
  return (
    <ErrorBoundary>
      <WorkbenchProvider>
        <Workspace />
      </WorkbenchProvider>
    </ErrorBoundary>
  );
}
