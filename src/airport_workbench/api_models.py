"""Shared API request, response, and error contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .identifiers import EdgeIdentity, NodeIdField


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PointGeometry(ApiModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]


class LineStringGeometry(ApiModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[float, float]]


class NodeProperties(ApiModel):
    id: NodeIdField
    node_type: str
    longitude: float
    latitude: float
    degree: int
    component: int
    topology_role: Literal["isolated", "dangling", "connected"]
    neighbours: str
    editable_attributes: dict[str, JsonValue]
    manual: bool
    color: str
    radius: float


class EdgeProperties(ApiModel):
    id: EdgeIdentity
    u: NodeIdField
    v: NodeIdField
    key: int = Field(ge=0)
    validation_color: str
    geometry_length_m: float
    source_type: str | None = None
    aeroway: str | None = None
    name: str | None = None
    ref: str | None = None
    cluster_id: int | None = None
    editable_attributes: dict[str, JsonValue]


class NodeFeature(ApiModel):
    type: Literal["Feature"] = "Feature"
    geometry: PointGeometry
    properties: NodeProperties


class EdgeFeature(ApiModel):
    type: Literal["Feature"] = "Feature"
    geometry: LineStringGeometry
    properties: EdgeProperties


class NodeFeatureCollection(ApiModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[NodeFeature]


class EdgeFeatureCollection(ApiModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[EdgeFeature]


class GeoJsonFeature(ApiModel):
    type: Literal["Feature"] = "Feature"
    geometry: PointGeometry | LineStringGeometry
    properties: dict[str, JsonValue]


class GeoJsonFeatureCollection(ApiModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJsonFeature]


class TopologyComponent(ApiModel):
    index: int
    size: int
    node_ids: list[NodeIdField]


class ParallelEdgeGroup(ApiModel):
    u: NodeIdField
    v: NodeIdField
    edge_ids: list[EdgeIdentity]


class TopologySummary(ApiModel):
    component_count: int
    largest_component: int
    isolated_count: int
    dangling_count: int
    parallel_pair_count: int
    isolated_nodes: list[NodeIdField]
    dangling_nodes: list[NodeIdField]
    components: list[TopologyComponent]
    parallel_groups: list[ParallelEdgeGroup]


class StandClusterResponse(ApiModel):
    c_id: int = Field(ge=1)
    name: str | None = None
    stands: list[EdgeIdentity]
    stand_refs: list[str]


class WorkbenchCapabilities(ApiModel):
    can_edit_graph: bool
    has_flights: bool
    can_match: bool


class WorkbenchStateResponse(ApiModel):
    nodes: NodeFeatureCollection
    edges: EdgeFeatureCollection
    stand_clusters: list[StandClusterResponse] = Field(default_factory=list)
    node_count: int
    edge_count: int
    flight_count: int
    topology: TopologySummary
    can_undo: bool
    can_finish: bool
    revision: int
    topology_revision: int
    save_path: str
    flight_mode: bool
    capabilities: WorkbenchCapabilities


class GraphCommandResponse(ApiModel):
    message: str
    revision: int


class SourceSegmentResponse(ApiModel):
    source_id: str
    source_start_m: float
    source_end_m: float
    reversed: bool


class RestoreCandidateResponse(ApiModel):
    candidate_id: str
    source_ids: list[str]
    osm_way_ids: list[str]
    refs: list[JsonValue]
    length_m: float
    first: NodeIdField
    last: NodeIdField
    segments: list[SourceSegmentResponse]
    geometry: LineStringGeometry


class RestoreOptionsResponse(ApiModel):
    revision: int
    current_endpoints: list[NodeIdField]
    candidates: list[RestoreCandidateResponse]


class MergeNodeResponse(ApiModel):
    node_id: NodeIdField
    position: tuple[float, float]
    is_graph_node: bool
    manual: bool
    degree: int
    source_ids: list[str] = Field(default_factory=list)


class MergeCandidateResponse(ApiModel):
    candidate_id: str
    node_ids: list[NodeIdField]
    max_distance_m: float
    nodes: list[MergeNodeResponse]


class MergeCandidatesResponse(ApiModel):
    revision: int
    candidates: list[MergeCandidateResponse]


class MergeNodesPreviewResponse(ApiModel):
    revision: int
    node_ids: list[NodeIdField]
    canonical_node_id: NodeIdField
    max_distance_m: float
    nodes: list[MergeNodeResponse]
    affected_edges: list[str]
    removed_self_loop_edges: list[str]
    warnings: list[str]
    source_edges_unchanged: bool


class DeleteEdgePreviewResponse(ApiModel):
    revision: int
    edge: str
    endpoints: list[NodeIdField]
    source_segments: list[SourceSegmentResponse]
    source_preserved: bool


class NodeHalfEdgeResponse(ApiModel):
    half_id: str
    edge: str
    outer_node: NodeIdField
    source_ids: list[str]


class NodePairCandidateResponse(ApiModel):
    pair_id: str
    left: str
    right: str
    endpoints: list[NodeIdField]
    source_ids: list[str]
    same_source: bool
    angle_degrees: float
    geometry: LineStringGeometry
    recommended: bool


class DeleteNodePreviewResponse(ApiModel):
    revision: int
    node: NodeIdField
    degree: int
    half_edges: list[NodeHalfEdgeResponse]
    pair_candidates: list[NodePairCandidateResponse]
    recommended_unpaired: list[str]


class SplitCandidateResponse(ApiModel):
    osm_node_id: NodeIdField
    id: NodeIdField
    source_index: int
    distance_m: float
    source_station_m: float
    position: tuple[float, float]


class SplitSourcePreviewResponse(ApiModel):
    revision: int
    source_id: str
    segment_index: int
    source_reversed: bool
    edge: str
    candidates: list[SplitCandidateResponse]
    recommended_node: NodeIdField | None
    manual_position: tuple[float, float]
    manual_station_m: float


class ManualSnapPreviewResponse(ApiModel):
    revision: int
    node: str
    edge: str
    original_position: tuple[float, float]
    snapped_position: tuple[float, float]
    distance_m: float
    target_source_id: str
    target_station_m: float
    segment_index: int
    target_geometry: LineStringGeometry
    connector_geometry: LineStringGeometry
    source_edge_unchanged: bool


class FlightFilterRequest(ApiModel):
    q: str = ""
    movement_type: str | None = None
    match_status: str | None = None
    min_points: int = Field(default=0, ge=0)
    max_points: int | None = Field(default=None, ge=0)
    stands: list[str] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    validation_only: bool = False
    issues_only: bool = False


class FlightCatalogueRequest(FlightFilterRequest):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)


class MatchResultResponse(ApiModel):
    flight_key: str
    graph_id: str | None
    config: dict[str, JsonValue]
    status: str
    error: str | None
    error_kind: str | None
    failure_type: str | None
    elapsed_seconds: float
    task_id: str | None
    updated_at: str | None
    has_path: bool


class FlightSummaryResponse(ApiModel):
    flight_key: str
    source: str
    flight_id: str
    flight_number: str | int | float | bool | None
    movement_type: str
    start_time: str
    end_time: str
    point_count: int
    inconsistent_fields: list[str]
    stand_position: str | None
    can_edit_stand: bool
    is_issue: bool = False
    issue_reason: str | None = None


class FlightCatalogueItemResponse(FlightSummaryResponse):
    match: MatchResultResponse


class TimeDisplayResponse(ApiModel):
    input_semantics: str
    display_timezone: str


class FlightCatalogueResponse(ApiModel):
    items: list[FlightCatalogueItemResponse]
    stand_options: list[str]
    supports_validation_filter: bool
    issue_count: int = 0
    can_edit_issues: bool = True
    total: int
    total_pages: int
    page: int
    page_size: int
    dataset_max_points: int
    dataset_min_date: str | None = None
    dataset_max_date: str | None = None
    min_points: int
    max_points: int
    graph_id: str
    time: TimeDisplayResponse


class FlightSelectionResponse(ApiModel):
    flight_keys: list[str]
    count: int


class SpatialStandCandidate(ApiModel):
    stand: str
    consecutive_points: int
    nearest_m: float


class HistoricalStandCandidate(ApiModel):
    stand: str
    uses: int
    total: int


class StandRecommendations(ApiModel):
    high: list[SpatialStandCandidate]
    medium: list[HistoricalStandCandidate]


class RouteListRequest(ApiModel):
    q: str = ""
    movement: str | None = None
    stand_ref: str | None = None
    runway_ref: str | None = None
    runway_is_null: bool = False
    status: str | None = None
    all_graphs: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class RouteItemResponse(ApiModel):
    route_id: str
    graph_id: str
    matches_current_graph: bool
    movement: str
    stand_ref: str
    runway_ref: str | None
    runway_interface_node: str
    edge_count: int
    total_length_m: float
    flight_count: int = 0
    status: str
    source: str
    note: str | None
    created_at: str | None
    updated_at: str | None


class RouteListResponse(ApiModel):
    items: list[RouteItemResponse]
    has_route_library: bool
    current_graph_id: str
    can_edit: bool
    stand_options: list[str]
    runway_options: list[str]
    status_counts: dict[str, int]
    total: int
    total_pages: int
    page: int
    page_size: int


class MovementCoverageSummary(ApiModel):
    movement: str
    total_ods: int
    fine_covered_ods: int
    effective_covered_ods: int
    fine_od_rate: float
    effective_od_rate: float


class RouteCoverageResponse(ApiModel):
    graph_id: str
    total_stands: int
    clustered_stands: int
    cluster_count: int
    fine_covered_stands: int
    effective_covered_stands: int
    total_runways: int
    covered_runways: int
    total_ods: int
    fine_covered_ods: int
    effective_covered_ods: int
    fine_od_rate: float
    effective_od_rate: float
    by_movement: list[MovementCoverageSummary]
    uncovered_stands: list[str]
    unclustered_stands: list[str]
    uncovered_runways: list[str]


class RouteGeometryResponse(ApiModel):
    route: RouteItemResponse
    path: GeoJsonFeatureCollection


class UpdateRouteReviewRequest(ApiModel):
    status: str
    note: str | None = None


class BatchUpdateRouteReviewRequest(ApiModel):
    route_ids: list[str] = Field(min_length=1)
    status: str
    note: str | None = None


class BatchUpdateRouteReviewResponse(ApiModel):
    updated_count: int
    route_ids: list[str]
    status: str


class DetectRouteAnomaliesRequest(ApiModel):
    route_ids: list[str] = Field(min_length=1)


class RouteAnomalyReasonResponse(ApiModel):
    code: str
    message: str


class RouteAnomalyItemResponse(ApiModel):
    route_id: str
    movement: str
    stand_ref: str
    runway_ref: str | None
    total_length_m: float
    flight_count: int
    status: str
    reasons: list[RouteAnomalyReasonResponse]


class DetectRouteAnomaliesResponse(ApiModel):
    checked_count: int
    anomalous_count: int
    items: list[RouteAnomalyItemResponse]


class ImportMatchesToRouteLibraryRequest(ApiModel):
    flight_keys: list[str] | None = None
    replace_candidates: bool = False


class ImportRoutesSummaryResponse(ApiModel):
    graph_id: str
    evaluated_flights: int
    unique_routes: int
    deleted_candidates: int
    inserted_routes: int
    existing_routes: int
    skipped_missing_stand: int
    skipped_invalid_path: int


class MatchIssueKeysRequest(ApiModel):
    flight_keys: list[str] = Field(default_factory=list)
    reason: str | None = None


class MatchIssueListResponse(ApiModel):
    flight_keys: list[str]
    count: int


class MatchIssueMutationResponse(ApiModel):
    inserted: int = 0
    existing: int = 0
    deleted: int = 0
    issue_flight_keys: list[str]


class FlightDetailResponse(ApiModel):
    summary: FlightSummaryResponse
    fields: dict[str, JsonValue]
    inconsistent_fields: dict[str, list[JsonValue]]
    observations: list[dict[str, JsonValue]]
    observation_columns: list[str]
    observation_page: int
    observation_pages: int
    observation_total: int
    observation_page_size: int
    all_fields: bool
    match: MatchResultResponse


class FlightGeometryResponse(ApiModel):
    flight_key: str
    flight_id: str
    flight: GeoJsonFeatureCollection
    path: GeoJsonFeatureCollection | None
    match: MatchResultResponse


class MatchSkippedResponse(ApiModel):
    flight_key: str
    reason: str


class MatchSubmissionResponse(ApiModel):
    task_id: str
    requested_count: int
    queued: list[str]
    queued_count: int
    skipped: list[MatchSkippedResponse]
    skipped_count: int


class MatchSummaryResponse(ApiModel):
    total_flights: int
    matched_flights: int
    failed_flights: int
    success_rate: float | None
    failure_counts: dict[str, int]
    matching_seconds: float


class MatchProgressResponse(ApiModel):
    total: int
    waiting: int
    running: int
    success: int
    failed: int
    complete: bool
    summary: MatchSummaryResponse


class MatchTaskResponse(MatchProgressResponse):
    task_id: str
    flight_keys: list[str]
    items: list[MatchResultResponse]


class MatchStatusResponse(ApiModel):
    graph_id: str
    tasks: list[MatchTaskResponse]
    progress: MatchProgressResponse


class ApiErrorCode(StrEnum):
    BAD_REQUEST = "bad_request"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    SERVICE_UNAVAILABLE = "service_unavailable"
    VALIDATION_ERROR = "validation_error"
    REVISION_CONFLICT = "revision_conflict"
    OBJECT_NOT_FOUND = "object_not_found"
    PAGE_OUT_OF_RANGE = "page_out_of_range"


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    context: dict[str, JsonValue] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: ErrorDetail


DEFAULT_ERROR_CODE = {
    400: ApiErrorCode.BAD_REQUEST,
    404: ApiErrorCode.NOT_FOUND,
    405: ApiErrorCode.METHOD_NOT_ALLOWED,
    422: ApiErrorCode.VALIDATION_ERROR,
    503: ApiErrorCode.SERVICE_UNAVAILABLE,
}


def error_detail(
    code: str | ApiErrorCode,
    message: str,
    context: Mapping[str, JsonValue] | None = None,
) -> ErrorDetail:
    return ErrorDetail(code=str(code), message=message, context=dict(context or {}))


def normalize_error_detail(status_code: int, detail: Any) -> ErrorDetail:
    """Normalize legacy HTTPException details at the one API error boundary."""
    default_code = DEFAULT_ERROR_CODE.get(status_code, ApiErrorCode.BAD_REQUEST)
    if isinstance(detail, ErrorDetail):
        return detail
    if isinstance(detail, Mapping):
        code = detail.get("code", default_code)
        message = detail.get("message")
        if message is not None:
            nested = detail.get("context")
            context = dict(nested) if isinstance(nested, Mapping) else {}
            context.update(
                {
                    str(key): value
                    for key, value in detail.items()
                    if key not in {"code", "message", "context"}
                }
            )
            return error_detail(str(code), str(message), context)
    return error_detail(default_code, str(detail))


ERROR_RESPONSES = {
    "default": {"model": ErrorResponse, "description": "Error response"},
    422: {"model": ErrorResponse, "description": "Request validation error"},
}
