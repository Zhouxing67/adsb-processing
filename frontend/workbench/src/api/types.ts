import type { components as GraphApi } from './generated/graph';
import type { components as FlightApi } from './generated/flight';

export type PointGeometry = GraphApi['schemas']['PointGeometry'];
export type LineGeometry = GraphApi['schemas']['LineStringGeometry'];
export interface GeoFeature<G, P = Record<string, unknown>> { type: 'Feature'; geometry: G; properties: P }

export type NodeId = GraphApi['schemas']['NodeIdField'];
export type EdgeIdentity = GraphApi['schemas']['EdgeIdentity'];
export type NodeProperties = GraphApi['schemas']['NodeProperties'];
export type EdgeProperties = GraphApi['schemas']['EdgeProperties'];
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
export type SelectedFeature = GeoFeature<PointGeometry, NodeProperties> | GeoFeature<LineGeometry, EdgeProperties>;
