"""Local browser application for airport graph editing and visualization."""

from __future__ import annotations

import argparse
import threading
import time
import webbrowser
from collections import defaultdict
from pathlib import Path as FilePath
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

import networkx as nx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from shapely.geometry import LineString, mapping

from adsb import Flight
from airport_surface import edge_source_segments
from airport_surface.graph import (
    DEFAULT_GRAPH_PATH,
    _json_value,
    load_graph,
    save_graph,
    validate_edge_endpoints,
    validate_edge_sources,
)

from .editor import EditorSession
from .flights import CataloguePageOutOfRange, FlightWorkbench
from .serializers import serialize_flights, serialize_paths

if TYPE_CHECKING:
    from path_map import Path

STATIC_DIRECTORY = FilePath(__file__).with_name("static")
NO_CACHE_HEADERS = {"Cache-Control": "no-store"}
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


class Token(BaseModel):
    token: str


class RestoreRequest(BaseModel):
    start: str
    end: str
    candidate_id: str | None = None


class MergeNodesRequest(BaseModel):
    node_ids: list[Any] = Field(default_factory=list)
    node_tokens: list[str] = Field(default_factory=list)
    canonical_node_id: Any | None = None


class UpdatedAttributes(BaseModel):
    token: str
    attributes: dict[str, Any]


class NodeDeletionRequest(BaseModel):
    token: str
    pair_ids: list[str] = Field(default_factory=list)
    discard_unpaired: bool = False


class SourceSplitRequest(BaseModel):
    edge: str
    longitude: float
    latitude: float
    osm_node_id: Any | None = None


class ManualSnapRequest(BaseModel):
    node: str
    edge: str


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
        self.nodes: dict[str, Any] = {}
        self.edges: dict[str, tuple[Any, Any, Any]] = {}

    def state(
        self, can_finish: bool, save_path: FilePath, *, read_only: bool = False
    ) -> dict[str, Any]:
        with self.session.lock:
            return self._state(can_finish, save_path, read_only=read_only)

    def _state(
        self, can_finish: bool, save_path: FilePath, *, read_only: bool = False
    ) -> dict[str, Any]:
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
        self.nodes = {}
        self.edges = {}
        node_features = []
        for index, (node, data) in enumerate(graph.nodes(data=True)):
            token = f"n{index}"
            self.nodes[token] = node
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
                        "token": token,
                        "node_id": repr(node),
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
                        "neighbours": ", ".join(repr(item) for item in graph.neighbors(node)),
                        "attributes": repr(
                            {key: value for key, value in data.items() if key != "pos"}
                        ),
                        "editable_attributes": _json_value(
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
        for index, (u, v, key, data) in enumerate(graph.edges(keys=True, data=True)):
            token = f"e{index}"
            self.edges[token] = (u, v, key)
            geometry = data.get("geometry") or LineString(
                [graph.nodes[u]["pos"][:2], graph.nodes[v]["pos"][:2]]
            )
            edge_features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geometry),
                    "properties": {
                        "token": token,
                        "edge_id": repr((u, v, key)),
                        "u": repr(u),
                        "v": repr(v),
                        "key": repr(key),
                        "validation_color": edge_colors[(u, v, key)],
                        "geometry_length_m": round(self.session.airport_graph.length(geometry), 2),
                        "source_id": data.get("source_id"),
                        "source_type": data.get("source_type"),
                        "source_start_m": data.get("source_start_m"),
                        "source_end_m": data.get("source_end_m"),
                        "osm_node_ids": repr(data.get("osm_node_ids", ())),
                        "source_segments": repr(edge_source_segments(data)),
                        "aeroway": data.get("aeroway"),
                        "name": data.get("name"),
                        "ref": data.get("ref"),
                        "attributes": repr(
                            {name: value for name, value in data.items() if name != "geometry"}
                        ),
                        "editable_attributes": _json_value(
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
                "isolated_nodes": [repr(node) for node in isolated_nodes[:100]],
                "dangling_nodes": [repr(node) for node in dangling_nodes[:100]],
                "components": [
                    {
                        "index": index,
                        "size": len(members),
                        "node_tokens": [
                            token for token, node in self.nodes.items() if node in members
                        ],
                    }
                    for index, members in enumerate(components, start=1)
                ],
                "parallel_groups": [
                    {
                        "u": repr(u),
                        "v": repr(v),
                        "edge_tokens": [
                            token
                            for token, edge in self.edges.items()
                            if edge[2] in keys
                            and ({edge[0], edge[1]} == {u, v})
                        ],
                    }
                    for u, v, keys in parallel_groups
                ],
            },
            "can_undo": self.session.can_undo,
            "can_finish": can_finish,
            "read_only": read_only,
            "save_path": str(save_path),
        }

    def node(self, token: str) -> Any:
        if token not in self.nodes:
            raise HTTPException(409, "图已更新，请重试")
        return self.nodes[token]

    def edge(self, token: str) -> tuple[Any, Any, Any]:
        if token not in self.edges:
            raise HTTPException(409, "图已更新，请重试")
        return self.edges[token]

    def node_token(self, node: Any) -> str:
        for token, value in self.nodes.items():
            if value == node:
                return token
        raise HTTPException(409, "图已更新，请重试")


def create_app(
    session: EditorSession,
    save_path: FilePath = DEFAULT_GRAPH_PATH,
    on_finish: Callable[[], None] | None = None,
    *,
    flights: Sequence[Flight] = (),
    paths_by_flight_key: Mapping[str, Path] | None = None,
    read_only: bool = False,
    match_config: Any | None = None,
    flight_sources: Sequence[str] | None = None,
    movement_types: Sequence[str] | None = None,
    input_time_semantics: str = "UTC",
    display_timezone: str = "UTC",
) -> FastAPI:
    browser = BrowserState(session)
    flight_workbench = FlightWorkbench(
        session.airport_graph,
        flights,
        sources=flight_sources,
        movement_types=movement_types,
        paths_by_flight_key=paths_by_flight_key,
        match_config=match_config,
        input_time_semantics=input_time_semantics,
        display_timezone=display_timezone,
        graph_lock=session.lock,
        graph_provider=lambda: session.airport_graph,
        revision_provider=lambda: getattr(session, "revision", 0),
    )
    flight_mode = bool(flights)
    app = FastAPI(title="Airport Graph Viewer" if read_only else "Airport Workbench")

    @app.middleware("http")
    async def enforce_read_only(request: Request, call_next: Callable[..., Any]) -> Any:
        read_only_match_api = request.url.path == "/api/matches" and request.method == "POST"
        safe_method = request.method in {"GET", "HEAD", "OPTIONS"}
        graph_write_blocked = (read_only or flight_mode) and not read_only_match_api
        if graph_write_blocked and not safe_method:
            return JSONResponse(
                status_code=405,
                content={"detail": "当前为只读可视化模式，不允许修改机场图"},
            )
        return await call_next(request)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIRECTORY / "index.html", headers=NO_CACHE_HEADERS)

    @app.get("/app.css")
    def stylesheet() -> FileResponse:
        return FileResponse(
            STATIC_DIRECTORY / "app.css", media_type="text/css", headers=NO_CACHE_HEADERS
        )

    @app.get("/flight-layout.css")
    def flight_layout_stylesheet() -> FileResponse:
        return FileResponse(
            STATIC_DIRECTORY / "flight-layout.css",
            media_type="text/css",
            headers=NO_CACHE_HEADERS,
        )

    @app.get("/app.js")
    def javascript() -> FileResponse:
        return FileResponse(
            STATIC_DIRECTORY / "app.js",
            media_type="text/javascript",
            headers=NO_CACHE_HEADERS,
        )

    @app.get("/flights-v2.js")
    def flight_javascript_v2() -> FileResponse:
        return FileResponse(
            STATIC_DIRECTORY / "flights-v2.js",
            media_type="text/javascript",
            headers=NO_CACHE_HEADERS,
        )

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        flight_workbench.sync_graph()
        value = browser.state(on_finish is not None, save_path, read_only=read_only)
        value["flight_count"] = len(flight_workbench.flights)
        value["flight_mode"] = flight_mode
        value["path_count"] = sum(
            result.status == "success" for result in flight_workbench.results.values()
        )
        return value

    @app.get("/api/flights")
    def flights_catalogue(
        q: str = "",
        movement_type: str | None = None,
        match_status: str | None = None,
        min_points: int = 0,
        max_points: int | None = None,
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

    @app.get("/api/flights/{flight_key}")
    def flight_detail(flight_key: str) -> dict[str, Any]:
        try:
            return flight_workbench.detail(flight_key)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.get("/api/flights/{flight_key}/geometry")
    def flight_geometry(flight_key: str) -> dict[str, Any]:
        try:
            return flight_workbench.geometry(flight_key)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.post("/api/matches")
    def match_flights(item: MatchFlightsRequest) -> dict[str, Any]:
        try:
            return flight_workbench.submit(item.flight_keys, force=item.force)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/api/matches")
    def match_status() -> dict[str, Any]:
        current_graph_id = flight_workbench.sync_graph()
        with flight_workbench.lock:
            return {
                "graph_id": current_graph_id,
                "items": [result.public() for result in flight_workbench.results.values()],
            }

    @app.post("/api/restore-options")
    def restore_options(item: RestoreRequest) -> dict[str, Any]:
        start = browser.node(item.start)
        end = browser.node(item.end)
        if start == end:
            raise HTTPException(400, "起点和终点不能相同")
        candidates = session.connection_candidates(start, end)
        return {
            "current_endpoints": [repr(start), repr(end)],
            "candidates": [
                {
                    **{
                        name: _json_value(value)
                        for name, value in candidate.items()
                        if name != "geometry"
                    },
                    "geometry": mapping(candidate["geometry"]),
                }
                for candidate in candidates
            ],
        }

    @app.post("/api/restore-confirm")
    def restore_confirm(item: RestoreRequest) -> dict[str, Any]:
        if item.candidate_id is None:
            raise HTTPException(400, "必须选择一个来源路径")
        start, end = browser.node(item.start), browser.node(item.end)
        try:
            key = session.restore_source_connection(start, end, item.candidate_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"message": f"已从原始来源路径恢复派生边，key={key!r}"}

    @app.get("/api/merge-candidates")
    def merge_candidates() -> dict[str, Any]:
        return {"candidates": _json_value(session.merge_candidates())}

    @app.post("/api/merge-nodes-preview")
    def merge_nodes_preview(item: MergeNodesRequest) -> dict[str, Any]:
        node_ids = item.node_ids or [browser.node(token) for token in item.node_tokens]
        try:
            return _json_value(
                session.merge_nodes_preview(node_ids, item.canonical_node_id)
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/api/merge-nodes-confirm")
    def merge_nodes_confirm(item: MergeNodesRequest) -> dict[str, Any]:
        node_ids = item.node_ids or [browser.node(token) for token in item.node_tokens]
        try:
            canonical = session.merge_nodes(node_ids, item.canonical_node_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"message": f"已合并节点，规范节点为 {canonical!r}"}

    @app.post("/api/delete-edge-preview")
    def delete_edge_preview(item: Token) -> dict[str, Any]:
        edge = browser.edge(item.token)
        data = session.graph.edges[edge]
        segments = edge_source_segments(data)
        return {
            "edge": repr(edge),
            "endpoints": [repr(edge[0]), repr(edge[1])],
            "source_id": data.get("source_id"),
            "source_interval": [data.get("source_start_m"), data.get("source_end_m")],
            "source_segments": [
                {
                    "source_id": segment.source_id,
                    "source_start_m": segment.source_start_m,
                    "source_end_m": segment.source_end_m,
                    "reversed": segment.reversed,
                }
                for segment in segments
            ],
            "source_preserved": True,
        }

    @app.post("/api/delete-edge-confirm")
    def delete_edge_confirm(item: Token) -> dict[str, Any]:
        edge = browser.edge(item.token)
        session.remove_derived_edge(*edge)
        return {"message": f"已删除派生边 {edge!r}，SourceEdge 保持不变"}

    @app.post("/api/delete-node-preview")
    def delete_node_preview(item: Token) -> dict[str, Any]:
        return session.node_deletion_plan(browser.node(item.token))

    @app.post("/api/delete-node-confirm")
    def delete_node_confirm(item: NodeDeletionRequest) -> dict[str, Any]:
        node = browser.node(item.token)
        try:
            session.remove_node_with_pairs(node, item.pair_ids, item.discard_unpaired)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"message": f"已按所选来源策略删除节点 {node!r}"}

    @app.post("/api/split-source-preview")
    def split_source_preview(item: SourceSplitRequest) -> dict[str, Any]:
        try:
            return session.source_split_preview(
                *browser.edge(item.edge), item.longitude, item.latitude
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/api/split-source-confirm")
    def split_source_confirm(item: SourceSplitRequest) -> dict[str, Any]:
        try:
            node = session.split_source_edge(
                *browser.edge(item.edge),
                item.longitude,
                item.latitude,
                item.osm_node_id,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"message": f"已在 SourceEdge 上使用节点 {node!r} 切分"}

    @app.post("/api/manual-snap-preview")
    def manual_snap_preview(item: ManualSnapRequest) -> dict[str, Any]:
        node = browser.node(item.node)
        edge = browser.edge(item.edge)
        try:
            return _json_value(session.manual_snap_preview(node, *edge))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/api/manual-snap-confirm")
    def manual_snap_confirm(item: ManualSnapRequest) -> dict[str, Any]:
        node = browser.node(item.node)
        edge = browser.edge(item.edge)
        try:
            session.manual_snap_node_to_edge(node, *edge)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"message": f"已将节点 {node!r} 人工接入目标边"}

    @app.post("/api/update-node")
    def update_node(item: UpdatedAttributes) -> dict[str, Any]:
        node = browser.node(item.token)
        session.update_node_attributes(node, item.attributes)
        return {"message": f"已更新节点 {node!r} 的属性"}

    @app.post("/api/update-edge")
    def update_edge(item: UpdatedAttributes) -> dict[str, Any]:
        edge = browser.edge(item.token)
        session.update_edge_attributes(*edge, item.attributes)
        return {"message": f"已更新边 {edge!r} 的属性"}

    @app.post("/api/save")
    def save() -> dict[str, Any]:
        with session.lock:
            validate_edge_endpoints(session.airport_graph)
            validate_edge_sources(session.airport_graph)
            output = save_graph(session.airport_graph, save_path)
        return {
            "message": (
                f"已保存 {output} · {session.graph.number_of_nodes()} 节点 · "
                f"{session.graph.number_of_edges()} 边"
            )
        }

    @app.post("/api/undo")
    def undo() -> dict[str, Any]:
        try:
            session.undo()
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"message": "已撤销上一步操作"}

    @app.post("/api/finish")
    def finish() -> dict[str, Any]:
        if on_finish is None:
            raise HTTPException(400, "当前为独立编辑模式")
        with session.lock:
            validate_edge_endpoints(session.airport_graph)
            validate_edge_sources(session.airport_graph)
            output = save_graph(session.airport_graph, save_path)
        on_finish()
        return {"message": f"已保存 {output}，编辑完成，正在返回 AirportGraph"}

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
