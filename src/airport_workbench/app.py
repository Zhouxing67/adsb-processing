"""Local browser application for airport graph editing and visualization."""

from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path as FilePath
from typing import Any, Callable

import networkx as nx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictInt
from shapely.geometry import LineString, mapping
from starlette.exceptions import HTTPException as StarletteHTTPException

from airport_surface import DEFAULT_GRAPH_PATH
from flight.flight_repository import FlightDatabase
from utils.json_value import to_json_value

from .api_models import (
    ERROR_RESPONSES,
    ApiErrorCode,
    DeleteEdgePreviewResponse,
    DeleteNodePreviewResponse,
    ErrorResponse,
    GraphCommandResponse,
    ManualSnapPreviewResponse,
    MergeCandidatesResponse,
    MergeNodesPreviewResponse,
    RestoreOptionsResponse,
    SplitSourcePreviewResponse,
    WorkbenchStateResponse,
    error_detail,
    normalize_error_detail,
)
from .editor import EditorSession, GraphObjectNotFound, RevisionConflict
from .flights import FlightWorkbench
from .identifiers import EdgeIdentity, NodeIdField
from .routes_flights import build_flights_router
from .routes_issues import build_match_issues_router
from .routes_library import build_route_library_router

VALIDATION_EDGE_COLORS = (
    "#406c80",
    "#9a684d",
    "#5f7660",
    "#765f7f",
    "#9a7b3f",
    "#4f6287",
    "#8a5968",
    "#4f7b78",
)


def _edge_colors(graph: Any) -> dict[tuple[Any, Any, Any], str]:
    """Greedily give incident edges strongly contrasting validation colors."""
    used_at_node: dict[Any, set[int]] = defaultdict(set)
    result: dict[tuple[Any, Any, Any], str] = {}
    for u, v, key in graph.edges(keys=True):
        unavailable = used_at_node[u] | used_at_node[v]
        color_index = 0
        while color_index in unavailable:
            color_index += 1
        used_at_node[u].add(color_index)
        used_at_node[v].add(color_index)
        result[(u, v, key)] = (
            VALIDATION_EDGE_COLORS[color_index]
            if color_index < len(VALIDATION_EDGE_COLORS)
            else f"hsl({(18 + color_index * 47) % 360} 38% 42%)"
        )
    return result


class VersionedRequest(BaseModel):
    expected_revision: StrictInt


class DrawConnectionRequest(VersionedRequest):
    start: NodeIdField
    end: NodeIdField
    intermediate_points: list[tuple[float, float]] = Field(default_factory=list, max_length=10000)
    aeroway: str = "taxiway"
    ref: str | None = None


class RestoreRequest(VersionedRequest):
    start: NodeIdField
    end: NodeIdField
    candidate_id: str | None = None


class MergeNodesRequest(VersionedRequest):
    node_ids: list[NodeIdField] = Field(default_factory=list)
    canonical_node_id: NodeIdField | None = None


class UpdatedNodeAttributes(VersionedRequest):
    node: NodeIdField
    attributes: dict[str, Any]


class UpdatedEdgeAttributes(VersionedRequest):
    edge: EdgeIdentity
    attributes: dict[str, Any]


class EdgeRequest(VersionedRequest):
    edge: EdgeIdentity


class NodeDeletionRequest(VersionedRequest):
    node: NodeIdField
    pair_ids: list[str] = Field(default_factory=list)
    discard_unpaired: bool = False


class SourceSplitRequest(VersionedRequest):
    edge: EdgeIdentity
    longitude: float
    latitude: float
    osm_node_id: NodeIdField | None = None


class ManualSnapRequest(VersionedRequest):
    node: NodeIdField
    edge: EdgeIdentity


class BrowserState:
    def __init__(self, session: EditorSession) -> None:
        self.session = session

    def state(self, can_finish: bool, save_path: FilePath) -> dict[str, Any]:
        with self.session.lock:
            return self._state(can_finish, save_path)

    def _state(self, can_finish: bool, save_path: FilePath) -> dict[str, Any]:
        graph = self.session.graph
        components = sorted(nx.connected_components(graph), key=len, reverse=True)
        component_by_node = {
            node: index + 1 for index, members in enumerate(components) for node in members
        }
        isolated_nodes = [node for node, degree in graph.degree if degree == 0]
        dangling_nodes = [node for node, degree in graph.degree if degree == 1]
        parallel_groups = [
            (u, v, tuple(keyed_edges))
            for u, neighbours in graph.adjacency()
            for v, keyed_edges in neighbours.items()
            if repr(u) <= repr(v) and len(keyed_edges) > 1
        ]
        node_features = []
        for node, data in graph.nodes(data=True):
            longitude, latitude = data["pos"][:2]
            degree = graph.degree(node)
            color = (
                "#a34f6a"
                if degree == 0
                else "#808080"
                if data.get("source") == "manual"
                else "#b56f38"
                if degree == 1
                else "#416878"
            )
            node_features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                    "properties": {
                        "id": node,
                        "node_type": (
                            "runway_interface"
                            if node in getattr(self.session.airport_graph, "runway_interfaces", {})
                            else "unclassified"
                        ),
                        "longitude": longitude,
                        "latitude": latitude,
                        "degree": degree,
                        "component": component_by_node[node],
                        "topology_role": (
                            "isolated"
                            if degree == 0
                            else "dangling"
                            if degree == 1
                            else "connected"
                        ),
                        "neighbours": ", ".join(graph.neighbors(node)),
                        "editable_attributes": to_json_value(
                            {key: value for key, value in data.items() if key != "pos"}
                        ),
                        "manual": data.get("source") == "manual",
                        "color": color,
                        "radius": 5 if degree == 0 else 4 if degree == 1 else 2.75,
                    },
                }
            )

        edge_features = []
        edge_colors = _edge_colors(graph)
        for u, v, key, data in graph.edges(keys=True, data=True):
            geometry = data.get("geometry") or LineString(
                [graph.nodes[u]["pos"][:2], graph.nodes[v]["pos"][:2]]
            )
            edge_features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geometry),
                    "properties": {
                        "id": {"u": u, "v": v, "key": key},
                        "u": u,
                        "v": v,
                        "key": key,
                        "validation_color": edge_colors[(u, v, key)],
                        "geometry_length_m": round(self.session.airport_graph.length(geometry), 2),
                        "source_type": data.get("source_type"),
                        "aeroway": data.get("aeroway"),
                        "name": data.get("name"),
                        "ref": data.get("ref"),
                        "editable_attributes": to_json_value(
                            {
                                name: value
                                for name, value in data.items()
                                if name not in {"geometry", "first", "last"}
                            }
                        ),
                    },
                }
            )
        return {
            "nodes": {"type": "FeatureCollection", "features": node_features},
            "edges": {"type": "FeatureCollection", "features": edge_features},
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "flight_count": 0,
            "topology": {
                "component_count": len(components),
                "largest_component": max((len(item) for item in components), default=0),
                "isolated_count": len(isolated_nodes),
                "dangling_count": len(dangling_nodes),
                "parallel_pair_count": len(parallel_groups),
                "isolated_nodes": isolated_nodes[:100],
                "dangling_nodes": dangling_nodes[:100],
                "components": [
                    {
                        "index": index,
                        "size": len(members),
                        "node_ids": list(members),
                    }
                    for index, members in enumerate(components, start=1)
                ],
                "parallel_groups": [
                    {
                        "u": u,
                        "v": v,
                        "edge_ids": [
                            {"u": u, "v": v, "key": edge_key}
                            for edge_key in keys
                        ],
                    }
                    for u, v, keys in parallel_groups
                ],
            },
            "can_undo": self.session.can_undo,
            "can_finish": can_finish,
            "revision": getattr(self.session, "revision", 0),
            "topology_revision": getattr(self.session, "topology_revision", 0),
            "save_path": str(save_path),
        }


def create_app(
    session: EditorSession,
    save_path: FilePath = DEFAULT_GRAPH_PATH,
    on_finish: Callable[[], None] | None = None,
    *,
    match_config: Any | None = None,
    input_time_semantics: str = "UTC",
    display_timezone: str = "UTC",
    flight_database: FlightDatabase | None = None,
) -> FastAPI:
    browser = BrowserState(session)
    flight_mode = flight_database is not None
    flight_workbench = None
    if flight_database is not None:
        flight_workbench = FlightWorkbench(
            session.airport_graph,
            flight_database,
            match_config=match_config,
            input_time_semantics=input_time_semantics,
            display_timezone=display_timezone,
        )
        if not flight_workbench.items:
            flight_workbench.close()
            raise ValueError("DuckDB 中没有可用的航班")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            if flight_workbench is not None:
                await run_in_threadpool(flight_workbench.close)

    app = FastAPI(
        title="Airport Workbench",
        lifespan=lifespan,
        responses=ERROR_RESPONSES,
    )
    graph_routes = APIRouter()

    @app.exception_handler(RevisionConflict)
    async def revision_conflict_handler(_request: Request, error: RevisionConflict) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                detail=error_detail(
                    ApiErrorCode.REVISION_CONFLICT,
                    str(error),
                    {"current_revision": error.current_revision},
                )
            ).model_dump(mode="json"),
        )

    @app.exception_handler(GraphObjectNotFound)
    async def object_not_found_handler(
        _request: Request, error: GraphObjectNotFound
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                detail=error_detail(ApiErrorCode.OBJECT_NOT_FOUND, str(error))
            ).model_dump(mode="json"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
        detail = error.detail
        if (
            flight_mode
            and error.status_code == 405
            and request.url.path in {getattr(route, "path", None) for route in graph_routes.routes}
        ):
            detail = "航班工作台不允许修改机场图"
        return JSONResponse(
            status_code=error.status_code,
            content=ErrorResponse(
                detail=normalize_error_detail(error.status_code, detail)
            ).model_dump(mode="json"),
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                detail=error_detail(
                    ApiErrorCode.VALIDATION_ERROR,
                    "请求参数验证失败",
                    {
                        "errors": [
                            {
                                str(key): list(value) if key == "loc" else value
                                for key, value in item.items()
                                if key not in {"ctx", "input", "url"}
                            }
                            for item in error.errors()
                        ]
                    },
                )
            ).model_dump(mode="json"),
        )

    @app.get("/api/state")
    def state() -> WorkbenchStateResponse:
        value = browser.state(not flight_mode and on_finish is not None, save_path)
        value["flight_mode"] = flight_mode
        value["capabilities"] = {
            "can_edit_graph": not flight_mode,
            "has_flights": flight_mode,
            "can_match": flight_mode,
        }
        if flight_workbench is not None:
            value["flight_count"] = len(flight_workbench.items)
        return WorkbenchStateResponse.model_validate(value)

    @graph_routes.post("/api/draw-connection")
    def draw_connection(item: DrawConnectionRequest) -> GraphCommandResponse:
        try:
            result = session.draw_connection(
                item.start,
                item.end,
                item.intermediate_points,
                aeroway=item.aeroway,
                ref=item.ref,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message="已添加人工连接，可撤销；点击保存持久化",
            revision=result.revision,
        )

    @graph_routes.post("/api/restore-options")
    def restore_options(item: RestoreRequest) -> RestoreOptionsResponse:
        if item.start == item.end:
            raise HTTPException(400, "起点和终点不能相同")
        result = session.connection_candidates(
            item.start, item.end, expected_revision=item.expected_revision
        )
        return RestoreOptionsResponse.model_validate(
            {
                "revision": result.revision,
                "current_endpoints": [item.start, item.end],
                "candidates": [
                    {
                        **{
                            name: to_json_value(value)
                            for name, value in candidate.items()
                            if name != "geometry"
                        },
                        "geometry": mapping(candidate["geometry"]),
                    }
                    for candidate in result.value
                ],
            }
        )

    @graph_routes.post("/api/restore-confirm")
    def restore_confirm(item: RestoreRequest) -> GraphCommandResponse:
        if item.candidate_id is None:
            raise HTTPException(400, "必须选择一个来源路径")
        try:
            result = session.restore_source_connection(
                item.start,
                item.end,
                item.candidate_id,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message=f"已从原始来源路径恢复派生边，key={result.value!r}",
            revision=result.revision,
        )

    @graph_routes.get("/api/merge-candidates")
    def merge_candidates() -> MergeCandidatesResponse:
        with session.lock:
            candidates = session.merge_candidates()
            return MergeCandidatesResponse.model_validate(
                {
                    "revision": session.revision,
                    "candidates": to_json_value(candidates),
                }
            )

    @graph_routes.post("/api/merge-nodes-preview")
    def merge_nodes_preview(item: MergeNodesRequest) -> MergeNodesPreviewResponse:
        try:
            result = session.merge_nodes_preview(
                item.node_ids,
                item.canonical_node_id,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        value = to_json_value(result.value)
        value["revision"] = result.revision
        return MergeNodesPreviewResponse.model_validate(value)

    @graph_routes.post("/api/merge-nodes-confirm")
    def merge_nodes_confirm(item: MergeNodesRequest) -> GraphCommandResponse:
        try:
            result = session.merge_nodes(
                item.node_ids,
                item.canonical_node_id,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message=f"已合并节点，规范节点为 {result.value!r}",
            revision=result.revision,
        )

    @graph_routes.post("/api/delete-edge-preview")
    def delete_edge_preview(item: EdgeRequest) -> DeleteEdgePreviewResponse:
        result = session.derived_edge_removal_preview(
            *item.edge.as_tuple(), expected_revision=item.expected_revision
        )
        return DeleteEdgePreviewResponse.model_validate(
            {**result.value, "revision": result.revision}
        )

    @graph_routes.post("/api/delete-edge-confirm")
    def delete_edge_confirm(item: EdgeRequest) -> GraphCommandResponse:
        edge = item.edge.as_tuple()
        result = session.remove_derived_edge(*edge, expected_revision=item.expected_revision)
        return GraphCommandResponse(
            message=f"已删除派生边 {edge!r}，SourceEdge 保持不变",
            revision=result.revision,
        )

    @graph_routes.post("/api/delete-node-preview")
    def delete_node_preview(item: NodeDeletionRequest) -> DeleteNodePreviewResponse:
        try:
            result = session.node_deletion_plan(item.node, expected_revision=item.expected_revision)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return DeleteNodePreviewResponse.model_validate(
            {**result.value, "revision": result.revision}
        )

    @graph_routes.post("/api/delete-node-confirm")
    def delete_node_confirm(item: NodeDeletionRequest) -> GraphCommandResponse:
        try:
            result = session.remove_node_with_pairs(
                item.node,
                item.pair_ids,
                item.discard_unpaired,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message=f"已按所选来源策略删除节点 {item.node!r}",
            revision=result.revision,
        )

    @graph_routes.post("/api/split-source-preview")
    def split_source_preview(item: SourceSplitRequest) -> SplitSourcePreviewResponse:
        try:
            result = session.source_split_preview(
                *item.edge.as_tuple(),
                item.longitude,
                item.latitude,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        value = to_json_value(result.value)
        value["revision"] = result.revision
        for candidate in value["candidates"]:
            candidate["id"] = candidate.pop("canonical_node_id")
        return SplitSourcePreviewResponse.model_validate(value)

    @graph_routes.post("/api/split-source-confirm")
    def split_source_confirm(item: SourceSplitRequest) -> GraphCommandResponse:
        try:
            node = session.split_source_edge(
                *item.edge.as_tuple(),
                item.longitude,
                item.latitude,
                item.osm_node_id,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message=f"已在 SourceEdge 上使用节点 {node.value!r} 切分",
            revision=node.revision,
        )

    @graph_routes.post("/api/manual-snap-preview")
    def manual_snap_preview(item: ManualSnapRequest) -> ManualSnapPreviewResponse:
        edge = item.edge.as_tuple()
        try:
            result = session.manual_snap_preview(
                item.node, *edge, expected_revision=item.expected_revision
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return ManualSnapPreviewResponse.model_validate(
            {**to_json_value(result.value), "revision": result.revision}
        )

    @graph_routes.post("/api/manual-snap-confirm")
    def manual_snap_confirm(item: ManualSnapRequest) -> GraphCommandResponse:
        edge = item.edge.as_tuple()
        try:
            result = session.manual_snap_node_to_edge(
                item.node, *edge, expected_revision=item.expected_revision
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message=f"已将节点 {item.node!r} 人工接入目标边",
            revision=result.revision,
        )

    @graph_routes.post("/api/update-node")
    def update_node(item: UpdatedNodeAttributes) -> GraphCommandResponse:
        result = session.update_node_attributes(
            item.node, item.attributes, expected_revision=item.expected_revision
        )
        return GraphCommandResponse(
            message=f"已更新节点 {item.node!r} 的属性",
            revision=result.revision,
        )

    @graph_routes.post("/api/update-edge")
    def update_edge(item: UpdatedEdgeAttributes) -> GraphCommandResponse:
        edge = item.edge.as_tuple()
        result = session.update_edge_attributes(
            *edge, item.attributes, expected_revision=item.expected_revision
        )
        return GraphCommandResponse(message=f"已更新边 {edge!r} 的属性", revision=result.revision)

    @graph_routes.post("/api/save")
    def save(item: VersionedRequest) -> GraphCommandResponse:
        result = session.save(save_path, expected_revision=item.expected_revision)
        output = result.value
        return GraphCommandResponse(
            message=(
                f"已保存 {output} · {session.graph.number_of_nodes()} 节点 · "
                f"{session.graph.number_of_edges()} 边"
            ),
            revision=result.revision,
        )

    @graph_routes.post("/api/undo")
    def undo(item: VersionedRequest) -> GraphCommandResponse:
        try:
            result = session.undo(expected_revision=item.expected_revision)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(message="已撤销上一步操作", revision=result.revision)

    @graph_routes.post("/api/finish")
    def finish(item: VersionedRequest) -> GraphCommandResponse:
        if on_finish is None:
            raise HTTPException(400, "当前为独立编辑模式")
        result = session.finish(save_path, on_finish, expected_revision=item.expected_revision)
        output = result.value
        return GraphCommandResponse(
            message=f"已保存 {output}，编辑完成，正在返回 AirportGraph",
            revision=result.revision,
        )

    if flight_mode:
        assert flight_workbench is not None
        app.include_router(build_flights_router(flight_workbench))
        app.include_router(build_route_library_router(flight_workbench))
        app.include_router(build_match_issues_router(flight_workbench))
    else:
        app.include_router(graph_routes)

    from .frontend import mount_frontend

    mount_frontend(app)
    return app
