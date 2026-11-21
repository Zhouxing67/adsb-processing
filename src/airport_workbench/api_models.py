"""Shared request-independent API error contracts."""

from __future__ import annotations

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
    node_id: NodeIdField
    node_type: str
    longitude: float
    latitude: float
    degree: int
    component: int
    topology_role: Literal["isolated", "dangling", "connected"]
    neighbours: str
    attributes: str
    editable_attributes: dict[str, JsonValue]
    manual: bool
    color: str
    radius: float


class EdgeProperties(ApiModel):
    id: EdgeIdentity
    edge_id: str
    u: NodeIdField
    v: NodeIdField
    u_id: NodeIdField
    v_id: NodeIdField
    key: int = Field(ge=0)
    validation_color: str
    geometry_length_m: float
    source_type: str | None = None
    osm_node_ids: str
    source_segments: str
    aeroway: str | None = None
    name: str | None = None
    ref: str | None = None
    attributes: str
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


class WorkbenchCapabilities(ApiModel):
    can_edit_graph: bool
    has_flights: bool
    can_match: bool


class WorkbenchStateResponse(ApiModel):
    nodes: NodeFeatureCollection
    edges: EdgeFeatureCollection
    flights: list[GeoJsonFeatureCollection]
    paths: list[GeoJsonFeatureCollection]
    node_count: int
    edge_count: int
    flight_count: int
    path_count: int
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
