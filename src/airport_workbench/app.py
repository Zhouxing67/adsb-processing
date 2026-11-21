"""Local browser application for airport graph editing and visualization."""

from __future__ import annotations

import argparse
import threading
import time
import webbrowser
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path as FilePath
from typing import TYPE_CHECKING, Annotated, Any, Callable, Mapping, Sequence

import networkx as nx
import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, StrictInt
from shapely.geometry import LineString, mapping
from starlette.exceptions import HTTPException as StarletteHTTPException

from airport_surface import edge_source_segments
from airport_surface.graph import (
    DEFAULT_GRAPH_PATH,
    load_graph,
)
from flight import Flight
from flight.flight_repository import FlightDatabase
from utils.json_value import to_json_value

from .api_models import (
    ERROR_RESPONSES,
    ApiErrorCode,
    ErrorResponse,
    error_detail,
    normalize_error_detail,
)
from .editor import EditorSession, GraphObjectNotFound, RevisionConflict
from .flights import CataloguePageOutOfRange, FlightWorkbench
from .identifiers import EdgeIdentity, NodeIdField
from .serializers import serialize_flights, serialize_paths

if TYPE_CHECKING:
    from path_map import Path

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


class UpdateStandRequest(BaseModel):
    stand_position: str | None


class MatchFlightsRequest(BaseModel):
    flight_keys: list[str] = Field(default_factory=list)
    force: bool = False


class BrowserState:
    def __init__(
        self,
        session: EditorSession,
        flights: Sequence[Flight] = (),
        paths: Sequence[Path] = (),
    ) -> None:
        self.session = session
        self.flights = tuple(flights)
        self.paths = tuple(paths)

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
                        "node_id": node,
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
                        "attributes": repr(
                            {key: value for key, value in data.items() if key != "pos"}
                        ),
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
                        "edge_id": repr((u, v, key)),
                        "u": u,
                        "v": v,
                        "u_id": u,
                        "v_id": v,
                        "key": key,
                        "validation_color": edge_colors[(u, v, key)],
                        "geometry_length_m": round(self.session.airport_graph.length(geometry), 2),
                        "source_type": data.get("source_type"),
                        "osm_node_ids": repr(data.get("osm_node_ids", ())),
                        "source_segments": repr(edge_source_segments(data)),
                        "aeroway": data.get("aeroway"),
                        "name": data.get("name"),
                        "ref": data.get("ref"),
                        "attributes": repr(
                            {name: value for name, value in data.items() if name != "geometry"}
                        ),
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
            "flights": serialize_flights(self.flights),
            "paths": serialize_paths(self.paths),
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "flight_count": len(self.flights),
            "path_count": len(self.paths),
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
                            {"u": eu, "v": ev, "key": edge_key}
                            for eu, ev, edge_key in graph.edges(keys=True)
                            if edge_key in keys and ({eu, ev} == {u, v})
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
    flights: Sequence[Flight] = (),
    paths_by_flight_key: Mapping[str, Path] | None = None,
    match_config: Any | None = None,
    flight_sources: Sequence[str] | None = None,
    movement_types: Sequence[str] | None = None,
    input_time_semantics: str = "UTC",
    display_timezone: str = "UTC",
    flight_database: FlightDatabase | None = None,
) -> FastAPI:
    browser = BrowserState(session)
    flight_mode = bool(flights) or flight_database is not None
    flight_workbench = None
    if flight_mode:
        flight_workbench = FlightWorkbench(
            session.airport_graph,
            flights,
            sources=flight_sources,
            flight_database=flight_database,
            movement_types=movement_types,
            paths_by_flight_key=paths_by_flight_key,
            match_config=match_config,
            input_time_semantics=input_time_semantics,
            display_timezone=display_timezone,
            graph_lock=session.lock,
            graph_provider=lambda: session.airport_graph,
            revision_provider=lambda: getattr(session, "revision", 0),
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
    flight_routes = APIRouter()
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
    async def http_error_handler(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=ErrorResponse(
                detail=normalize_error_detail(error.status_code, error.detail)
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

    @app.middleware("http")
    async def enforce_flight_permissions(request: Request, call_next: Callable[..., Any]) -> Any:
        match_api = request.url.path == "/api/matches" and request.method == "POST"
        safe_method = request.method in {"GET", "HEAD", "OPTIONS"}
        route = request.url.path.split("/")
        stand_api = (
            request.method == "PATCH"
            and len(route) == 5
            and route[1:3] == ["api", "flights"]
            and route[4] == "stand"
        )
        graph_write_blocked = flight_mode and not (match_api or stand_api)
        if graph_write_blocked and not safe_method:
            return JSONResponse(
                status_code=405,
                content=ErrorResponse(
                    detail=error_detail(
                        ApiErrorCode.METHOD_NOT_ALLOWED,
                        "航班工作台不允许修改机场图",
                    )
                ).model_dump(mode="json"),
            )
        return await call_next(request)

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        value = browser.state(not flight_mode and on_finish is not None, save_path)
        value["flight_mode"] = flight_mode
        value["capabilities"] = {
            "can_edit_graph": not flight_mode,
            "has_flights": flight_mode,
            "can_match": flight_mode,
        }
        if flight_workbench is not None:
            flight_workbench.sync_graph()
            value["flight_count"] = len(flight_workbench.items)
            value["path_count"] = sum(
                result.status == "success" for result in flight_workbench.results.values()
            )
        return value

    @flight_routes.get("/api/flights")
    def flights_catalogue(
        q: str = "",
        movement_type: str | None = None,
        match_status: str | None = None,
        min_points: int = 0,
        max_points: int | None = None,
        stands: Annotated[list[str] | None, Query()] = None,
        start_date: date | None = None,
        end_date: date | None = None,
        validation_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        try:
            return flight_workbench.catalogue(
                query=q,
                movement_type=movement_type,
                status=match_status,
                min_points=min_points,
                max_points=max_points,
                stands=stands or (),
                start_date=start_date,
                end_date=end_date,
                validation_only=validation_only,
                page=page,
                page_size=page_size,
            )
        except CataloguePageOutOfRange as error:
            raise HTTPException(
                400,
                {
                    "code": "page_out_of_range",
                    "message": str(error),
                    "total_pages": error.total_pages,
                },
            ) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @flight_routes.patch(
        "/api/flights/{flight_key}/stand", status_code=204, response_class=Response
    )
    def update_stand(flight_key: str, item: UpdateStandRequest) -> None:
        try:
            flight_workbench.update_stand(flight_key, item.stand_position)
        except KeyError as error:
            raise HTTPException(404, "未知 flight_key") from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @flight_routes.get("/api/flights/{flight_key}")
    def flight_detail(
        flight_key: str,
        observation_page: int = 1,
        observation_page_size: int = 100,
        all_fields: bool = False,
    ) -> dict[str, Any]:
        try:
            return flight_workbench.detail(
                flight_key,
                observation_page=observation_page,
                observation_page_size=observation_page_size,
                all_fields=all_fields,
            )
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except (ValueError, CataloguePageOutOfRange) as error:
            raise HTTPException(400, str(error)) from error

    @flight_routes.get("/api/flight-selection")
    def flight_selection(
        q: str = "",
        movement_type: str | None = None,
        match_status: str | None = None,
        min_points: int = 0,
        max_points: int | None = None,
        stands: Annotated[list[str] | None, Query()] = None,
        start_date: date | None = None,
        end_date: date | None = None,
        validation_only: bool = False,
    ) -> dict[str, Any]:
        try:
            return flight_workbench.filtered_keys(
                query=q,
                movement_type=movement_type,
                status=match_status,
                min_points=min_points,
                max_points=max_points,
                stands=stands or (),
                start_date=start_date,
                end_date=end_date,
                validation_only=validation_only,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @flight_routes.get("/api/flights/{flight_key}/geometry")
    def flight_geometry(flight_key: str) -> dict[str, Any]:
        try:
            return flight_workbench.geometry(flight_key)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @flight_routes.post("/api/matches")
    def match_flights(item: MatchFlightsRequest) -> dict[str, Any]:
        try:
            return flight_workbench.submit(item.flight_keys, force=item.force)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @flight_routes.get("/api/matches")
    def match_status(task_id: Annotated[list[str] | None, Query()] = None) -> dict[str, Any]:
        return flight_workbench.task_status(task_id)

    @graph_routes.post("/api/draw-connection")
    def draw_connection(item: DrawConnectionRequest) -> dict[str, Any]:
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
        return {"message": "已添加人工连接，可撤销；点击保存持久化", "revision": result.revision}

    @graph_routes.post("/api/restore-options")
    def restore_options(item: RestoreRequest) -> dict[str, Any]:
        if item.start == item.end:
            raise HTTPException(400, "起点和终点不能相同")
        result = session.connection_candidates(
            item.start, item.end, expected_revision=item.expected_revision
        )
        return {
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

    @graph_routes.post("/api/restore-confirm")
    def restore_confirm(item: RestoreRequest) -> dict[str, Any]:
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
        return {
            "message": f"已从原始来源路径恢复派生边，key={result.value!r}",
            "revision": result.revision,
        }

    @graph_routes.get("/api/merge-candidates")
    def merge_candidates() -> dict[str, Any]:
        with session.lock:
            candidates = session.merge_candidates()
            return {
                "revision": session.revision,
                "candidates": to_json_value(candidates),
            }

    @graph_routes.post("/api/merge-nodes-preview")
    def merge_nodes_preview(item: MergeNodesRequest) -> dict[str, Any]:
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
        return value

    @graph_routes.post("/api/merge-nodes-confirm")
    def merge_nodes_confirm(item: MergeNodesRequest) -> dict[str, Any]:
        try:
            result = session.merge_nodes(
                item.node_ids,
                item.canonical_node_id,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {
            "message": f"已合并节点，规范节点为 {result.value!r}",
            "revision": result.revision,
        }

    @graph_routes.post("/api/delete-edge-preview")
    def delete_edge_preview(item: EdgeRequest) -> dict[str, Any]:
        result = session.derived_edge_removal_preview(
            *item.edge.as_tuple(), expected_revision=item.expected_revision
        )
        return {**result.value, "revision": result.revision}

    @graph_routes.post("/api/delete-edge-confirm")
    def delete_edge_confirm(item: EdgeRequest) -> dict[str, Any]:
        edge = item.edge.as_tuple()
        result = session.remove_derived_edge(*edge, expected_revision=item.expected_revision)
        return {
            "message": f"已删除派生边 {edge!r}，SourceEdge 保持不变",
            "revision": result.revision,
        }

    @graph_routes.post("/api/delete-node-preview")
    def delete_node_preview(item: NodeDeletionRequest) -> dict[str, Any]:
        try:
            result = session.node_deletion_plan(item.node, expected_revision=item.expected_revision)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {**result.value, "revision": result.revision}

    @graph_routes.post("/api/delete-node-confirm")
    def delete_node_confirm(item: NodeDeletionRequest) -> dict[str, Any]:
        try:
            result = session.remove_node_with_pairs(
                item.node,
                item.pair_ids,
                item.discard_unpaired,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {
            "message": f"已按所选来源策略删除节点 {item.node!r}",
            "revision": result.revision,
        }

    @graph_routes.post("/api/split-source-preview")
    def split_source_preview(item: SourceSplitRequest) -> dict[str, Any]:
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
        return value

    @graph_routes.post("/api/split-source-confirm")
    def split_source_confirm(item: SourceSplitRequest) -> dict[str, Any]:
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
        return {
            "message": f"已在 SourceEdge 上使用节点 {node.value!r} 切分",
            "revision": node.revision,
        }

    @graph_routes.post("/api/manual-snap-preview")
    def manual_snap_preview(item: ManualSnapRequest) -> dict[str, Any]:
        edge = item.edge.as_tuple()
        try:
            result = session.manual_snap_preview(
                item.node, *edge, expected_revision=item.expected_revision
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {**to_json_value(result.value), "revision": result.revision}

    @graph_routes.post("/api/manual-snap-confirm")
    def manual_snap_confirm(item: ManualSnapRequest) -> dict[str, Any]:
        edge = item.edge.as_tuple()
        try:
            result = session.manual_snap_node_to_edge(
                item.node, *edge, expected_revision=item.expected_revision
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {
            "message": f"已将节点 {item.node!r} 人工接入目标边",
            "revision": result.revision,
        }

    @graph_routes.post("/api/update-node")
    def update_node(item: UpdatedNodeAttributes) -> dict[str, Any]:
        result = session.update_node_attributes(
            item.node, item.attributes, expected_revision=item.expected_revision
        )
        return {
            "message": f"已更新节点 {item.node!r} 的属性",
            "revision": result.revision,
        }

    @graph_routes.post("/api/update-edge")
    def update_edge(item: UpdatedEdgeAttributes) -> dict[str, Any]:
        edge = item.edge.as_tuple()
        result = session.update_edge_attributes(
            *edge, item.attributes, expected_revision=item.expected_revision
        )
        return {"message": f"已更新边 {edge!r} 的属性", "revision": result.revision}

    @graph_routes.post("/api/save")
    def save(item: VersionedRequest) -> dict[str, Any]:
        result = session.save(save_path, expected_revision=item.expected_revision)
        output = result.value
        return {
            "message": (
                f"已保存 {output} · {session.graph.number_of_nodes()} 节点 · "
                f"{session.graph.number_of_edges()} 边"
            ),
            "revision": result.revision,
        }

    @graph_routes.post("/api/undo")
    def undo(item: VersionedRequest) -> dict[str, Any]:
        try:
            result = session.undo(expected_revision=item.expected_revision)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"message": "已撤销上一步操作", "revision": result.revision}

    @graph_routes.post("/api/finish")
    def finish(item: VersionedRequest) -> dict[str, Any]:
        if on_finish is None:
            raise HTTPException(400, "当前为独立编辑模式")
        result = session.finish(save_path, on_finish, expected_revision=item.expected_revision)
        output = result.value
        return {
            "message": f"已保存 {output}，编辑完成，正在返回 AirportGraph",
            "revision": result.revision,
        }

    app.include_router(flight_routes if flight_mode else graph_routes)

    from .frontend import mount_frontend

    mount_frontend(app)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the airport workbench.")
    parser.add_argument("--graph", type=FilePath, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    graph = load_graph(args.graph)
    session = EditorSession(graph)
    if not args.no_browser:
        url = f"http://{args.host}:{args.port}/?session={time.time_ns()}"
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(session, args.graph), host=args.host, port=args.port)
