import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import type { FlightDetail } from '@/api/types';
import { api } from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { TooltipProvider } from '@/components/ui/tooltip';
import { aerowayTypes } from '@/domain/properties';
import type { Aeroway } from '@/domain/properties';
import { FlightPanel } from '@/features/flights/FlightPanel';
import { MapSelectionRail } from '@/features/flights/MapSelectionRail';
import { ObservationView } from '@/features/flights/ObservationView';
import { FeatureDetails } from '@/features/graph-editor/FeatureDetails';
import { GraphDialog } from '@/features/graph-editor/GraphDialog';
import { Inspector } from '@/features/graph-editor/Inspector';
import type { LayerSettings } from '@/features/graph-editor/Inspector';
import { SearchPanel } from '@/features/graph-editor/SearchPanel';
import { ToolDock } from '@/features/graph-editor/ToolDock';
import { TopologyPanel } from '@/features/graph-editor/TopologyPanel';
import { useGraphEditorMachine } from '@/features/graph-editor/useGraphEditorMachine';
import { Header } from '@/features/layout/Header';
import { MapToolbar } from '@/features/layout/MapToolbar';
import { RailResizer, RestoreRailWidth } from '@/features/layout/RailResizer';
import { MapView } from '@/features/map/MapView';
import { cn } from '@/lib/utils';
import { ErrorBoundary } from './ErrorBoundary';
import { WorkbenchProvider, useWorkbench } from './WorkbenchContext';
import type { MainView } from './WorkbenchContext';

function Workspace() {
  const wb = useWorkbench();
  const state = wb.state;
  const [detail, setDetail] = useState<FlightDetail | null>(null);
  const [matchRun, setMatchRun] = useState('');
  const submitMatches = async (keys: string[], force: boolean) => {
    const result = await api.submitMatches(keys, force);
    setMatchRun(result.task_id);
  };
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
  const rightOpenRef = useRef(rightOpen);
  rightOpenRef.current = rightOpen;
  const rightBeforeFullTableRef = useRef<boolean | null>(null);

  const editor = useGraphEditorMachine();

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    return () => window.cancelAnimationFrame(frame);
  }, [splitView, leftOpen, rightOpen, state?.flight_mode]);

  useEffect(() => {
    if (editor.dialog || (wb.selected && wb.detailsOpen)) setRightOpen(true);
  }, [editor.dialog, wb.selected, wb.detailsOpen]);

  const isFullTableView =
    Boolean(state?.flight_mode) && !splitView && (wb.view === 'flights' || wb.view === 'observations');

  useEffect(() => {
    if (isFullTableView) {
      if (rightBeforeFullTableRef.current === null) {
        rightBeforeFullTableRef.current = rightOpenRef.current;
        setRightOpen(false);
      }
    } else if (rightBeforeFullTableRef.current !== null) {
      const restore = rightBeforeFullTableRef.current;
      rightBeforeFullTableRef.current = null;
      setRightOpen(restore);
    }
  }, [isFullTableView]);

  useEffect(() => {
    if (!splitView) setSplitterResizing(false);
  }, [splitView]);

  useEffect(() => {
    if (!splitterResizing) return;
    const stop = () => setSplitterResizing(false);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    return () => {
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
    };
  }, [splitterResizing]);

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

  if (!state) {
    return (
      <main className="grid h-full w-full place-items-center bg-[var(--canvas)] text-[13px] text-muted-foreground">
        {wb.error || '正在载入工作台…'}
      </main>
    );
  }

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

  const handleSplitLayoutChange = (layout: Record<string, number>) => {
    const next = layout.map;
    if (typeof next === 'number' && Number.isFinite(next) && next >= 25 && next <= 75) {
      setMapSize(next);
      try {
        localStorage.setItem('airport-workbench.map-split-width', String(next));
      } catch {
        /* storage is optional */
      }
    }
  };

  const mapContent = (
    <section
      className={cn(
        'main-view map-view absolute inset-0 h-full w-full',
        wb.view !== 'map' && !splitView && 'hidden',
      )}
    >
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
        onFlightClick={key => {
          setLeftOpen(true);
          wb.dispatch({ type: 'highlight-flight', key });
        }}
      />
      <MapToolbar editing={graphEditing} onEditing={toggleEditing} />
      <div className="pointer-events-none absolute left-[172px] top-3.5 z-[700] flex max-w-[calc(100%-190px)] flex-wrap items-start gap-2">
        {wb.tool === 'merge' && (
          <div className="pointer-events-auto flex flex-wrap items-center gap-1.5 rounded-lg border border-border bg-background/95 p-1.5 shadow-sm">
            <Button variant="outline" size="sm" onClick={() => void editor.openMergeCandidates()}>
              重复节点候选
            </Button>
            <Button
              variant="default"
              size="sm"
              disabled={editor.mergeNodeIds.length < 2}
              onClick={() => void editor.previewMerge(editor.mergeNodeIds, state.revision)}
            >
              检查并合并（{editor.mergeNodeIds.length}）
            </Button>
            <Button variant="ghost" size="sm" onClick={editor.reset}>
              清空选择
            </Button>
          </div>
        )}
        {wb.tool === 'draw' && (
          <div className="pointer-events-auto flex flex-wrap items-center gap-1.5 rounded-lg border border-border bg-background/95 p-1.5 shadow-sm">
            <Select
              value={editor.drawAeroway}
              onValueChange={value => editor.setDrawAeroway(value as Aeroway)}
            >
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
              value={editor.drawRef}
              onChange={event => editor.setDrawRef(event.target.value)}
            />
            {editor.selection.length > 0 && (
              <Button variant="outline" size="sm" onClick={editor.undoDrawPoint}>
                撤销形状点
              </Button>
            )}
            {editor.selection.length > 0 && (
              <Button variant="ghost" size="sm" onClick={editor.reset}>
                取消
              </Button>
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
          matchRun={matchRun}
          setMatchRun={setMatchRun}
          submitMatches={submitMatches}
          active={wb.view === 'flights' || (splitView && wb.view !== 'observations')}
          splitView={splitView}
          onDetail={setDetail}
        />
      )}
      {state.flight_mode && wb.view === 'observations' && <ObservationView detail={detail} splitView={splitView} />}
    </>
  );

  const mapPanel = (
    <ResizablePanel id="map" defaultSize={`${mapSize}%`} minSize="25%" maxSize="75%" className="workspace-pane relative h-full">
      {mapContent}
    </ResizablePanel>
  );

  const secondaryPanel = (
    <ResizablePanel
      id="secondary"
      defaultSize={`${100 - mapSize}%`}
      minSize="25%"
      maxSize="75%"
      className="workspace-pane relative h-full"
    >
      {secondaryContent}
    </ResizablePanel>
  );

  const showFlightBanner = state.flight_mode && (Boolean(wb.error) || (Boolean(wb.status) && wb.status !== '航班工作台'));
  const tabTitle = splitView ? '拖回标签栏退出分屏，或拖到内容区切换左右分屏' : '拖到内容区左侧或右侧分屏';

  const gridTemplateColumns =
    shellLeft && rightOpen
      ? 'var(--left-sidebar-width, var(--sidebar-width)) minmax(0, 1fr) var(--right-sidebar-width, var(--sidebar-width))'
      : shellLeft
        ? 'var(--left-sidebar-width, var(--sidebar-width)) minmax(0, 1fr)'
        : rightOpen
          ? 'minmax(0, 1fr) var(--right-sidebar-width, var(--sidebar-width))'
          : 'minmax(0, 1fr)';

  return (
    <div
      className="grid h-full w-full grid-rows-[56px_minmax(0,1fr)_34px] overflow-hidden bg-[var(--canvas)]"
      style={{ gridTemplateColumns }}
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
        flightLeft && <MapSelectionRail splitView={splitView} onDetail={setDetail} submitMatches={submitMatches} />
      )}

      <main
        ref={workspaceRef}
        className={cn(
          'workspace relative z-[1] row-start-2 min-h-0 min-w-0',
          shellLeft ? 'col-start-2' : 'col-start-1',
          splitterResizing && 'splitter-resizing',
        )}
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
          <ResizablePanelGroup
            key={mapRight ? 'map-right' : 'map-left'}
            orientation="horizontal"
            onLayoutChanged={handleSplitLayoutChange}
            className="h-full w-full"
          >
            {mapRight ? secondaryPanel : mapPanel}
            <ResizableHandle
              withHandle
              data-testid="workspace-split-handle"
              onPointerDown={() => setSplitterResizing(true)}
            />
            {mapRight ? mapPanel : secondaryPanel}
          </ResizablePanelGroup>
        ) : (
          <>
            {mapContent}
            {secondaryContent}
          </>
        )}

        {dropSide && (
          <div
            className={cn(
              'pointer-events-none absolute bottom-3 top-3 z-[1400] grid w-[calc(50%-18px)] place-items-center rounded-lg border-2 border-dashed border-zinc-500 bg-zinc-900/10 text-sm font-semibold text-zinc-800 backdrop-blur-[1px]',
              dropSide === 'left' ? 'left-3' : 'right-3',
            )}
          >
            在{dropSide === 'left' ? '左' : '右'}侧打开
          </div>
        )}

        {showFlightBanner && (
          <div
            className={cn(
              'flight-status-toast absolute bottom-3.5 right-3.5 z-[1350] flex max-w-[min(420px,calc(100%-28px))] items-center gap-2 rounded-lg border px-3 py-1.5 text-xs shadow-md',
              wb.error
                ? 'border-red-200 bg-red-50 text-red-700'
                : 'border-border bg-background/95 text-foreground',
            )}
            role={wb.error ? 'alert' : 'status'}
          >
            <span>{wb.error || wb.status}</span>
            <Button
              variant="ghost"
              size="icon-xs"
              className="h-5 w-5 text-current opacity-70 hover:opacity-100"
              aria-label="关闭提示"
              onClick={() => wb.dispatch({ type: 'status', value: '航班工作台' })}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </main>

      <SearchPanel />

      {rightOpen && (
        <div
          className={cn(
            'right-rail row-start-2 min-h-0 min-w-0 overflow-hidden border-l border-border bg-background',
            shellLeft ? 'col-start-3' : 'col-start-2',
            'max-md:fixed max-md:bottom-[34px] max-md:right-0 max-md:top-14 max-md:z-[1250] max-md:w-[min(320px,85vw)] max-md:shadow-xl',
          )}
        >
          {rightContent}
        </div>
      )}

      {shellLeft && <RailResizer side="left" />}
      {rightOpen && <RailResizer side="right" />}

      {state.flight_mode ? (
        <nav
          className={cn(
            'main-tabs relative z-[1300] row-start-3 flex h-[34px] items-stretch justify-center border-t border-border bg-muted transition-colors',
            shellLeft ? 'col-start-2' : 'col-start-1',
            splitView && draggedView && 'tabs-drop-target bg-zinc-200/80 ring-2 ring-inset ring-zinc-500',
          )}
          aria-label="航班主视图"
          onDragOver={event => {
            if (draggedView) event.preventDefault();
          }}
          onDrop={returnToSingleView}
        >
          {(
            [
              { key: 'map' as const, label: '地图', visible: true },
              { key: 'flights' as const, label: '航班', visible: true },
              { key: 'observations' as const, label: '观测记录', visible: Boolean(detail) },
            ] as const
          )
            .filter(tab => tab.visible)
            .map(tab => (
              <button
                key={tab.key}
                type="button"
                draggable
                title={tabTitle}
                className={cn(
                  'min-w-[88px] cursor-grab border-x border-border/70 px-5 text-xs font-medium transition-colors active:cursor-grabbing',
                  wb.view === tab.key
                    ? 'bg-background text-foreground shadow-[inset_0_-2px_0_0_#18181b]'
                    : 'bg-transparent text-muted-foreground hover:bg-background/60 hover:text-foreground',
                )}
                onDragStart={event => startDrag(event, tab.key)}
                onDragEnd={() => {
                  setDraggedView(null);
                  setDropSide(null);
                }}
                onClick={() => wb.dispatch({ type: 'view', value: tab.key })}
              >
                {tab.label}
              </button>
            ))}
        </nav>
      ) : (
        <div
          className={cn(
            'status relative z-[1150] col-span-full row-start-3 flex h-[34px] items-center justify-center gap-2 border-t border-border px-3.5 text-[11px]',
            wb.error
              ? 'bg-red-50 text-red-700'
              : 'pointer-events-none bg-background text-muted-foreground',
          )}
        >
          <span>{wb.error || wb.status}</span>
          {wb.error && (
            <Button
              variant="ghost"
              size="icon-xs"
              className="h-5 w-5 text-red-700 hover:bg-red-100"
              aria-label="清除错误"
              onClick={() => wb.dispatch({ type: 'clear-error' })}
            >
              <X className="h-3 w-3" />
            </Button>
          )}
        </div>
      )}

      {wb.busy && (
        <div className="absolute inset-0 z-[1500] grid cursor-wait place-items-center bg-white/30">
          <span className="h-7 w-7 animate-spin rounded-full border-[3px] border-zinc-200 border-t-zinc-900" />
        </div>
      )}
    </div>
  );
}

export function App() {
  return (
    <ErrorBoundary>
      <TooltipProvider delayDuration={300}>
        <WorkbenchProvider>
          <Workspace />
        </WorkbenchProvider>
      </TooltipProvider>
    </ErrorBoundary>
  );
}
