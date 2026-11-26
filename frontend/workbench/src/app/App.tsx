import { useEffect, useMemo, useRef, useState } from 'react';
import { X } from 'lucide-react';
import type { MapFlightEntry, MapRouteEntry, SelectedFeature } from '@/api/types';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable';
import { Spinner } from '@/components/ui/spinner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { isNodeFeature } from '@/domain/features';
import { lineIntersectsBounds } from '@/domain/geometry';
import type { GeoBounds } from '@/domain/geometry';
import { FlightPanel } from '@/features/flights/FlightPanel';
import { MapSelectionRail } from '@/features/flights/MapSelectionRail';
import { ObservationView } from '@/features/flights/ObservationView';
import { useFlightSession } from '@/features/flights/useFlightSession';
import { RouteLibraryPanel } from '@/features/routes/RouteLibraryPanel';
import { EditorToolOverlay } from '@/features/graph-editor/EditorToolOverlay';
import { FeatureDetails } from '@/features/graph-editor/FeatureDetails';
import { GraphDialog } from '@/features/graph-editor/GraphDialog';
import { Inspector } from '@/features/graph-editor/Inspector';
import type { LayerSettings } from '@/features/graph-editor/Inspector';
import { SearchPanel } from '@/features/graph-editor/SearchPanel';
import { ToolDock } from '@/features/graph-editor/ToolDock';
import { TopologyPanel } from '@/features/graph-editor/TopologyPanel';
import type { AngleMeasureEdge } from '@/features/graph-editor/TopologyPanel';
import { useGraphEditorMachine } from '@/features/graph-editor/useGraphEditorMachine';
import { Header } from '@/features/layout/Header';
import { MapToolbar } from '@/features/layout/MapToolbar';
import { RailResizer, RestoreRailWidth } from '@/features/layout/RailResizer';
import { MapView } from '@/features/map/MapView';
import { cn } from '@/lib/utils';
import { ErrorBoundary } from './ErrorBoundary';
import { WorkbenchProvider, useWorkbench } from './WorkbenchContext';
import type { MainView } from './WorkbenchContext';

const EMPTY_FLIGHTS: Map<string, MapFlightEntry> = new Map();
const EMPTY_ROUTES: Map<string, MapRouteEntry> = new Map();

function Workspace() {
  const wb = useWorkbench();
  const state = wb.state;
  const flightMode = Boolean(state?.flight_mode);
  const session = useFlightSession(flightMode);
  const [splitValidation, setSplitValidation] = useState(false);
  const [angleMeasureActive, setAngleMeasureActive] = useState(false);
  const [angleEdges, setAngleEdges] = useState<AngleMeasureEdge[]>([]);
  const [graphEditing, setGraphEditing] = useState(false);
  const [splitViews, setSplitViews] = useState<[MainView, MainView] | null>(null);
  const splitView = splitViews !== null;
  const [splitLeftSize, setSplitLeftSize] = useState(() => {
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
  const [layers, setLayers] = useState<LayerSettings>({
    base: 'none',
    edges: true,
    parking: true,
    nodes: false,
    spreadRoutes: true,
    colorByCluster: false,
  });
  const [flightMapOverlayRoutes, setFlightMapOverlayRoutes] = useState(false);
  const [routeMapOverlayFlights, setRouteMapOverlayFlights] = useState(false);

  const workspaceRef = useRef<HTMLElement>(null);
  const editor = useGraphEditorMachine();

  const hasRightContext = Boolean(editor.dialog || (wb.selected && wb.detailsOpen));
  const dualMap = flightMode && wb.mapFlights.size > 0 && wb.mapRoutes.size > 0;
  const showRightRail = flightMode ? rightOpen && hasRightContext : rightOpen;

  const visibleMapFlights = useMemo(() => {
    if (!wb.showMapFlights) return EMPTY_FLIGHTS;
    if (wb.isolatedFlightKey && wb.mapFlights.has(wb.isolatedFlightKey)) {
      return new Map([[wb.isolatedFlightKey, wb.mapFlights.get(wb.isolatedFlightKey)!]]);
    }
    return wb.mapFlights;
  }, [wb.showMapFlights, wb.isolatedFlightKey, wb.mapFlights]);

  const visibleMapRoutes = useMemo(() => {
    if (!wb.showMapRoutes) return EMPTY_ROUTES;
    if (wb.isolatedRouteId && wb.mapRoutes.has(wb.isolatedRouteId)) {
      return new Map([[wb.isolatedRouteId, wb.mapRoutes.get(wb.isolatedRouteId)!]]);
    }
    return wb.mapRoutes;
  }, [wb.showMapRoutes, wb.isolatedRouteId, wb.mapRoutes]);

  const selectedFeatures = useMemo(() => {
    const base = wb.selected ? [...editor.selection, wb.selected] : [...editor.selection];
    return angleEdges.length ? [...base, ...angleEdges] : base;
  }, [editor.selection, wb.selected, angleEdges]);

  useEffect(() => {
    if (!dualMap) {
      if (wb.view === 'route-map') wb.dispatch({ type: 'view', value: 'map' });
      setSplitViews(current => (current && current.includes('route-map') ? null : current));
    }
  }, [dualMap, wb.view, wb.dispatch]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    return () => window.cancelAnimationFrame(frame);
  }, [splitView, leftOpen, showRightRail, flightMode]);

  useEffect(() => {
    if (wb.topologyOpen) {
      setLeftOpen(true);
    } else {
      setAngleMeasureActive(false);
      setAngleEdges([]);
    }
  }, [wb.topologyOpen]);

  useEffect(() => {
    if (hasRightContext) {
      setRightOpen(true);
    } else if (flightMode) {
      setRightOpen(false);
    }
  }, [hasRightContext, flightMode]);

  useEffect(() => {
    if (!flightMode || wb.error || !wb.status || wb.status === '航班工作台') return;
    const timer = window.setTimeout(() => {
      wb.dispatch({ type: 'status', value: '航班工作台' });
    }, 3500);
    return () => window.clearTimeout(timer);
  }, [flightMode, wb.error, wb.status, wb.dispatch]);

  useEffect(() => {
    if (!splitViews) return;
    if (!splitViews.includes(wb.view)) {
      setSplitViews(current => {
        if (!current || current.includes(wb.view)) return current;
        const [left, right] = current;
        return left === 'map' ? [left, wb.view] : right === 'map' ? [wb.view, right] : [left, wb.view];
      });
    }
  }, [wb.view, splitViews]);

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
        setSplitViews(null);
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
  const flightLeft = state.flight_mode && leftOpen && !topologyLeft;
  const shellLeft = topologyLeft || flightLeft;

  const rightContent = editor.dialog ? (
    <GraphDialog
      dialog={editor.dialog}
      onClose={editor.reset}
      onPreview={editor.setPreviewOverlays}
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
    if (!next) {
      wb.dispatch({ type: 'tool', value: 'inspect' });
      editor.reset();
    }
  };

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
    setSplitViews(current => {
      if (current) {
        const [left, right] = current;
        if (side === 'left') {
          return draggedView === right ? [right, left] : [draggedView, right];
        }
        return draggedView === left ? [right, left] : [left, draggedView];
      }
      const other: MainView =
        wb.view !== draggedView ? wb.view : draggedView === 'map' ? 'flights' : 'map';
      return side === 'left' ? [draggedView, other] : [other, draggedView];
    });
    wb.dispatch({ type: 'view', value: draggedView });
    setDraggedView(null);
    setDropSide(null);
  };

  const returnToSingleView = (event: React.DragEvent) => {
    if (!draggedView) return;
    event.preventDefault();
    setSplitViews(null);
    wb.dispatch({ type: 'view', value: draggedView });
    setDraggedView(null);
    setDropSide(null);
  };

  const handleSplitLayoutChange = (layout: Record<string, number>) => {
    const next = layout.left;
    if (typeof next === 'number' && Number.isFinite(next) && next >= 25 && next <= 75) {
      setSplitLeftSize(next);
      try {
        localStorage.setItem('airport-workbench.map-split-width', String(next));
      } catch {
        /* storage is optional */
      }
    }
  };

  const handleMapFeature = (feature: SelectedFeature, clickPoint?: [number, number]) => {
    if (wb.topologyOpen && angleMeasureActive) {
      if (!isNodeFeature(feature)) {
        setAngleEdges(current => {
          if (
            current.length === 1 &&
            current[0].properties.u === feature.properties.u &&
            current[0].properties.v === feature.properties.v &&
            current[0].properties.key === feature.properties.key
          ) {
            return current;
          }
          return current.length === 1 ? [current[0], feature] : [feature];
        });
      } else {
        wb.dispatch({ type: 'status', value: '转角测量 · 请点击两条相连的边' });
      }
      return;
    }
    void editor.handleFeature(feature, clickPoint);
  };

  const handleBoxSelect = (bounds: GeoBounds) => {
    const matched = state.edges.features.filter(
      edge =>
        edge.properties.aeroway === 'parking_position' &&
        lineIntersectsBounds(edge.geometry.coordinates, bounds),
    );
    editor.addClusterFeatures(matched);
  };

  const renderMapView = (kind: 'flight' | 'route', active: boolean) => {
    const isRouteMap = kind === 'route';
    const mapFlightsForKind = !dualMap
      ? visibleMapFlights
      : isRouteMap
        ? routeMapOverlayFlights
          ? visibleMapFlights
          : EMPTY_FLIGHTS
        : visibleMapFlights;
    const mapRoutesForKind = !dualMap
      ? visibleMapRoutes
      : isRouteMap
        ? visibleMapRoutes
        : flightMapOverlayRoutes
          ? visibleMapRoutes
          : EMPTY_ROUTES;
    return (
      <section
        className={cn(
          'main-view absolute inset-0 h-full w-full',
          isRouteMap ? 'route-map-view' : 'map-view',
          !active && 'hidden',
        )}
      >
        <MapView
          mapId={isRouteMap ? 'route-map' : 'map'}
          state={state}
          flights={mapFlightsForKind}
          routes={mapRoutesForKind}
          splitValidation={splitValidation}
          baseLayer={layers.base}
          showEdges={layers.edges}
          showParking={layers.parking || wb.tool === 'cluster'}
          showNodes={layers.nodes || wb.topologyOpen || graphEditing}
          spreadRoutes={layers.spreadRoutes}
          colorByCluster={layers.colorByCluster || wb.tool === 'cluster'}
          boxSelectEnabled={wb.tool === 'cluster'}
          boxSelectSticky={editor.clusterBoxSelect}
          selected={selectedFeatures}
          drawPoints={editor.drawPoints}
          previewOverlays={editor.previewOverlays}
          focusFlightRequest={!dualMap || !isRouteMap || routeMapOverlayFlights ? wb.mapFocusRequest : null}
          focusRouteRequest={!dualMap || isRouteMap || flightMapOverlayRoutes ? wb.routeFocusRequest : null}
          focusFeatureRequest={wb.focusFeatureRequest}
          fitMapVersion={!dualMap || !isRouteMap || routeMapOverlayFlights ? wb.fitMapVersion : 0}
          fitRoutesVersion={!dualMap || isRouteMap || flightMapOverlayRoutes ? wb.fitRoutesVersion : 0}
          observationLocation={!isRouteMap ? wb.observationLocation : null}
          onFeature={handleMapFeature}
          onMapClick={editor.handleMapClick}
          onBoxSelect={handleBoxSelect}
          onFlightClick={key => {
            setLeftOpen(true);
            wb.dispatch({ type: 'highlight-flight', key });
          }}
          onRouteClick={routeId => {
            setLeftOpen(true);
            wb.dispatch({ type: 'highlight-route', routeId });
          }}
        />
        <MapToolbar
          editing={graphEditing}
          onEditing={toggleEditing}
          dualMap={dualMap}
          mapKind={kind}
          overlayOther={isRouteMap ? routeMapOverlayFlights : flightMapOverlayRoutes}
          onToggleOverlayOther={() =>
            isRouteMap
              ? setRouteMapOverlayFlights(value => !value)
              : setFlightMapOverlayRoutes(value => !value)
          }
          spreadRoutes={layers.spreadRoutes}
          onToggleSpreadRoutes={() => setLayers(current => ({ ...current, spreadRoutes: !current.spreadRoutes }))}
        />
        {!state.flight_mode && graphEditing && <ToolDock />}
        <EditorToolOverlay
          revision={state.revision}
          mergeNodeIds={editor.mergeNodeIds}
          clusterEdges={editor.clusterEdges}
          standClusters={state.stand_clusters ?? []}
          clusterBoxSelect={editor.clusterBoxSelect}
          selectionCount={editor.selection.length}
          drawAeroway={editor.drawAeroway}
          drawRef={editor.drawRef}
          onDrawAerowayChange={editor.setDrawAeroway}
          onDrawRefChange={editor.setDrawRef}
          onClusterBoxSelectChange={editor.setClusterBoxSelect}
          onOpenMergeCandidates={editor.openMergeCandidates}
          onPreviewMerge={editor.previewMerge}
          onCreateCluster={editor.createCluster}
          onAssignCluster={editor.assignCluster}
          onUndoDrawPoint={editor.undoDrawPoint}
          onReset={editor.reset}
        />
      </section>
    );
  };

  const renderSplitPane = (view: MainView) => {
    if (view === 'map') return renderMapView('flight', true);
    if (view === 'route-map') return renderMapView('route', true);
    if (view === 'flights') {
      return (
        <FlightPanel
          tracking={session.tracking}
          progress={session.progress}
          submitMatches={session.submitMatches}
          active
          splitView
          activeDetailKey={session.detail?.summary.flight_key ?? null}
          onOpenDetail={session.openFlightDetail}
        />
      );
    }
    if (view === 'routes') return <RouteLibraryPanel active splitView />;
    return <ObservationView detail={session.detail} splitView />;
  };

  const showFlightBanner = state.flight_mode && (Boolean(wb.error) || (Boolean(wb.status) && wb.status !== '航班工作台'));
  const tabTitle = splitView ? '拖回标签栏退出分屏，或拖到内容区切换左右分屏' : '拖到内容区左侧或右侧分屏';

  const gridTemplateColumns =
    shellLeft && showRightRail
      ? 'var(--left-sidebar-width, var(--sidebar-width)) minmax(0, 1fr) var(--right-sidebar-width, var(--sidebar-width))'
      : shellLeft
        ? 'var(--left-sidebar-width, var(--sidebar-width)) minmax(0, 1fr)'
        : showRightRail
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
        rightOpen={showRightRail}
        showRightToggle={!flightMode || hasRightContext}
        onLeft={() => setLeftOpen(value => !value)}
        onRight={() => setRightOpen(value => !value)}
      />

      {topologyLeft ? (
        <TopologyPanel
          splitValidation={splitValidation}
          onSplitValidation={() => setSplitValidation(value => !value)}
          angleMeasureActive={angleMeasureActive}
          angleEdges={angleEdges}
          onToggleAngleMeasure={() => {
            setAngleMeasureActive(active => {
              const next = !active;
              if (!next) setAngleEdges([]);
              else wb.dispatch({ type: 'status', value: '转角测量 · 请在地图上依次点击两条相连的边' });
              return next;
            });
          }}
          onClearAngleEdges={() => setAngleEdges([])}
        />
      ) : (
        flightLeft && (
          <MapSelectionRail
            state={state}
            layers={layers}
            onLayers={setLayers}
            splitView={splitView}
            onOpenDetail={session.openFlightDetail}
            submitMatches={session.submitMatches}
          />
        )
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
        {state.flight_mode && splitViews ? (
          <>
            <ResizablePanelGroup
              orientation="horizontal"
              onLayoutChanged={handleSplitLayoutChange}
              className="h-full w-full"
            >
              <ResizablePanel
                id="left"
                defaultSize={`${splitLeftSize}%`}
                minSize="25%"
                maxSize="75%"
                className="workspace-pane relative h-full"
              >
                {renderSplitPane(splitViews[0])}
              </ResizablePanel>
              <ResizableHandle
                withHandle
                data-testid="workspace-split-handle"
                onPointerDown={() => setSplitterResizing(true)}
              />
              <ResizablePanel
                id="right"
                defaultSize={`${100 - splitLeftSize}%`}
                minSize="25%"
                maxSize="75%"
                className="workspace-pane relative h-full"
              >
                {renderSplitPane(splitViews[1])}
              </ResizablePanel>
            </ResizablePanelGroup>
            {!splitViews.includes('flights') && (
              <FlightPanel
                tracking={session.tracking}
                progress={session.progress}
                submitMatches={session.submitMatches}
                active={false}
                splitView
                activeDetailKey={session.detail?.summary.flight_key ?? null}
                onOpenDetail={session.openFlightDetail}
              />
            )}
            {!splitViews.includes('routes') && <RouteLibraryPanel active={false} splitView />}
          </>
        ) : (
          <>
            {renderMapView('flight', wb.view === 'map')}
            {dualMap && renderMapView('route', wb.view === 'route-map')}
            {state.flight_mode && (
              <FlightPanel
                tracking={session.tracking}
                progress={session.progress}
                submitMatches={session.submitMatches}
                active={wb.view === 'flights'}
                splitView={false}
                activeDetailKey={session.detail?.summary.flight_key ?? null}
                onOpenDetail={session.openFlightDetail}
              />
            )}
            {state.flight_mode && <RouteLibraryPanel active={wb.view === 'routes'} splitView={false} />}
            {state.flight_mode && wb.view === 'observations' && <ObservationView detail={session.detail} splitView={false} />}
          </>
        )}

        {dropSide && (
          <div
            className={cn(
              'pointer-events-none absolute bottom-3 top-3 z-[1400] grid w-[calc(50%-18px)] place-items-center rounded-lg border-2 border-dashed border-muted-foreground bg-primary/10 text-sm font-semibold text-foreground backdrop-blur-[1px]',
              dropSide === 'left' ? 'left-3' : 'right-3',
            )}
          >
            在{dropSide === 'left' ? '左' : '右'}侧打开
          </div>
        )}

        {showFlightBanner && (
          <Alert
            variant={wb.error ? 'destructive' : 'default'}
            className="flight-status-toast absolute left-1/2 top-3 z-[1350] w-auto max-w-[min(420px,calc(100%-28px))] -translate-x-1/2 bg-background/95 py-1.5 shadow-md backdrop-blur-xs"
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
          </Alert>
        )}
      </main>

      <SearchPanel leftOffset={shellLeft} />

      {showRightRail && (
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
      {showRightRail && <RailResizer side="right" />}

      {state.flight_mode ? (
        <nav
          className={cn(
            'main-tabs relative z-[1300] row-start-3 flex h-[34px] items-stretch justify-center border-t border-border bg-muted transition-colors',
            shellLeft ? 'col-start-2' : 'col-start-1',
            splitView && draggedView && 'tabs-drop-target bg-accent ring-2 ring-inset ring-muted-foreground',
          )}
          aria-label="航班主视图"
          onDragOver={event => {
            if (draggedView) event.preventDefault();
          }}
          onDrop={returnToSingleView}
        >
          {(
            [
              { key: 'map' as const, label: dualMap ? '航班地图' : '地图', visible: true },
              { key: 'flights' as const, label: '航班', visible: true },
              { key: 'route-map' as const, label: '路径地图', visible: dualMap },
              { key: 'routes' as const, label: '路径库', visible: true },
              { key: 'observations' as const, label: '观测记录', visible: Boolean(session.detail) },
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
                  'min-w-[88px] cursor-grab border-x border-border/70 px-5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30 active:cursor-grabbing',
                  (splitViews ? splitViews.includes(tab.key) : wb.view === tab.key)
                    ? 'bg-background text-foreground shadow-[inset_0_-2px_0_0_var(--primary)]'
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
              ? 'bg-red-50 text-destructive'
              : 'pointer-events-none bg-background text-muted-foreground',
          )}
        >
          <span>{wb.error || wb.status}</span>
          {wb.error && (
            <Button
              variant="ghost"
              size="icon-xs"
              className="h-5 w-5 text-destructive hover:bg-destructive/10"
              aria-label="清除错误"
              onClick={() => wb.dispatch({ type: 'clear-error' })}
            >
              <X className="h-3 w-3" />
            </Button>
          )}
        </div>
      )}

      {wb.busy && (
        <div className="absolute inset-0 z-[1500] grid cursor-wait place-items-center bg-background/35">
          <Spinner className="h-7 w-7" />
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
