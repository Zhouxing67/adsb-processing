import type { components as GraphApi } from './generated/graph';
import type { components as FlightApi } from './generated/flight';

export type PointGeometry = GraphApi['schemas']['PointGeometry'];
export type LineGeometry = GraphApi['schemas']['LineStringGeometry'];
export interface GeoFeature<G, P = Record<string, unknown>> { type: 'Feature'; geometry: G; properties: P }

export type NodeId = GraphApi['schemas']['NodeIdField'];
export type EdgeIdentity = GraphApi['schemas']['EdgeIdentity'];
export type NodeProperties = GraphApi['schemas']['NodeProperties'];
export type EdgeProperties = GraphApi['schemas']['EdgeProperties'];
export type StandCluster = GraphApi['schemas']['StandClusterResponse'];
export type TopologySummary = GraphApi['schemas']['TopologySummary'];
export type WorkbenchState = GraphApi['schemas']['WorkbenchStateResponse'];
export type FlightItem = FlightApi['schemas']['FlightCatalogueItemResponse'];
export type FlightCatalogue = FlightApi['schemas']['FlightCatalogueResponse'];
export type FlightGeometry = FlightApi['schemas']['FlightGeometryResponse'];
export interface MapFlightEntry {
  geometry: FlightGeometry; label: string; slot: number;
  trajectoryVisible: boolean; pathVisible: boolean;
}
export type FlightDetail = FlightApi['schemas']['FlightDetailResponse'];
export type MatchStatus = FlightApi['schemas']['MatchStatusResponse'];
export type RouteItem = FlightApi['schemas']['RouteItemResponse'];
export type RouteList = FlightApi['schemas']['RouteListResponse'];
export type RouteCoverage = FlightApi['schemas']['RouteCoverageResponse'];
export type UncoveredClusterSummary = FlightApi['schemas']['UncoveredClusterSummary'];
export type DetectRouteAnomaliesRequest = Partial<FlightApi['schemas']['DetectRouteAnomaliesRequest']>;
export type RouteAnomalyResult = FlightApi['schemas']['DetectRouteAnomaliesResponse'];
export type RouteAnomalyItem = FlightApi['schemas']['RouteAnomalyItemResponse'];
export type BatchRouteReviewResponse = FlightApi['schemas']['BatchUpdateRouteReviewResponse'];
export type RouteGeometry = FlightApi['schemas']['RouteGeometryResponse'];
export type RouteReviewUpdate = FlightApi['schemas']['UpdateRouteReviewRequest'];
export type ImportRoutesRequest = FlightApi['schemas']['ImportMatchesToRouteLibraryRequest'];
export type ImportRoutesSummary = FlightApi['schemas']['ImportRoutesSummaryResponse'];
export type MatchIssueList = FlightApi['schemas']['MatchIssueListResponse'];
export type MatchIssueMutation = FlightApi['schemas']['MatchIssueMutationResponse'];
export interface MapRouteEntry {
  geometry: RouteGeometry; label: string; slot: number; visible: boolean;
}
export type SelectedFeature = GeoFeature<PointGeometry, NodeProperties> | GeoFeature<LineGeometry, EdgeProperties>;

export type DemoMatchConfig = GraphApi['schemas']['DemoMatchConfig'];
export type DemoPointInput = GraphApi['schemas']['DemoPointInput'];
export type DemoScenarioSummary = GraphApi['schemas']['DemoScenarioSummary'];
export type DemoScenariosResponse = GraphApi['schemas']['DemoScenariosResponse'];
export type DemoTraceRequest = GraphApi['schemas']['DemoTraceRequest'];
export type DemoGraph = GraphApi['schemas']['DemoGraph'];
export type DemoGraphEdge = GraphApi['schemas']['DemoGraphEdge'];
export type DemoGraphNode = GraphApi['schemas']['DemoGraphNode'];
export type DemoObservationTrace = GraphApi['schemas']['DemoObservationTrace'];
export type DemoDualTransition = GraphApi['schemas']['DemoDualTransition'];
export type DemoTrellisState = GraphApi['schemas']['DemoTrellisState'];
export type DemoTrellisLayer = GraphApi['schemas']['DemoTrellisLayer'];
export type DemoDecodeAttempt = GraphApi['schemas']['DemoDecodeAttempt'];
export type DemoTraceResponse = GraphApi['schemas']['DemoTraceResponse'];
