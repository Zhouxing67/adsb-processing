"""Shared graph geometry operations, validation, and JSON persistence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import networkx as nx
from pyproj import Proj
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import substring

from utils.json_value import to_json_value

from .models import (
    AirportGraph,
    GraphMetadata,
    SourceEdge,
    SourceNode,
    SourceSegment,
    edge_source_segments,
)

DEFAULT_GRAPH_PATH = Path("data/graphs/zbaa_final.json")
GRAPH_SCHEMA_VERSION = 2
ENDPOINT_TOLERANCE_M = 1e-3


def geometry_from_source_interval(
    airport_graph: AirportGraph,
    source_id: str,
    start_m: float,
    end_m: float,
    start_node: Any | None = None,
    end_node: Any | None = None,
) -> LineString:
    source = airport_graph.get_source_edge(source_id)
    projected = airport_graph.project_shape(source.geometry)
    piece = substring(projected, start_m, end_m)
    if not isinstance(piece, LineString):
        raise ValueError(f"Source interval {(start_m, end_m)!r} has no length")
    coordinates = list(piece.coords)
    if start_node is not None:
        coordinates[0] = airport_graph.project.transform(
            *airport_graph.graph.nodes[start_node]["pos"][:2]
        )
    if end_node is not None:
        coordinates[-1] = airport_graph.project.transform(
            *airport_graph.graph.nodes[end_node]["pos"][:2]
        )
    return airport_graph.to_wgs84_shape(LineString(coordinates))


def reverse_source_segments(
    segments: tuple[SourceSegment, ...] | list[SourceSegment],
) -> tuple[SourceSegment, ...]:
    """Reverse the traversal direction of a complete source chain."""
    return tuple(
        SourceSegment(
            segment.source_id,
            segment.source_start_m,
            segment.source_end_m,
            not segment.reversed,
        )
        for segment in reversed(segments)
    )


def compact_source_segments(
    segments: tuple[SourceSegment, ...] | list[SourceSegment],
    tolerance_m: float = ENDPOINT_TOLERANCE_M,
) -> tuple[SourceSegment, ...]:
    """Combine adjacent intervals of the same source without changing traversal."""
    compacted: list[SourceSegment] = []
    for segment in segments:
        if not compacted:
            compacted.append(segment)
            continue
        previous = compacted[-1]
        if previous.source_id != segment.source_id or previous.reversed != segment.reversed:
            compacted.append(segment)
            continue
        if (
            not segment.reversed
            and abs(previous.source_end_m - segment.source_start_m) <= tolerance_m
        ):
            compacted[-1] = SourceSegment(
                segment.source_id, previous.source_start_m, segment.source_end_m
            )
        elif (
            segment.reversed and abs(previous.source_start_m - segment.source_end_m) <= tolerance_m
        ):
            compacted[-1] = SourceSegment(
                segment.source_id,
                segment.source_start_m,
                previous.source_end_m,
                True,
            )
        else:
            compacted.append(segment)
    return tuple(compacted)


def geometry_from_source_segments(
    airport_graph: AirportGraph,
    segments: tuple[SourceSegment, ...] | list[SourceSegment],
    start_node: Any | None = None,
    end_node: Any | None = None,
    tolerance_m: float = ENDPOINT_TOLERANCE_M,
) -> LineString:
    """Rebuild one graph edge from an ordered chain of immutable source intervals."""
    normalized = tuple(segments)
    if not normalized:
        raise ValueError("A derived edge requires at least one SourceSegment")
    projected_pieces: list[LineString] = []
    for segment in normalized:
        piece = airport_graph.project_shape(
            geometry_from_source_interval(
                airport_graph,
                segment.source_id,
                segment.source_start_m,
                segment.source_end_m,
            )
        )
        if segment.reversed:
            piece = LineString(reversed(piece.coords))
        if projected_pieces:
            gap = Point(projected_pieces[-1].coords[-1]).distance(Point(piece.coords[0]))
            if gap > tolerance_m:
                raise ValueError(
                    f"Source segments are discontinuous by {gap:.3f} m: "
                    f"{projected_pieces[-1].coords[-1]!r} -> {piece.coords[0]!r}"
                )
        projected_pieces.append(piece)
    coordinates = list(projected_pieces[0].coords)
    for piece in projected_pieces[1:]:
        coordinates.extend(list(piece.coords)[1:])
    if start_node is not None:
        coordinates[0] = airport_graph.project.transform(
            *airport_graph.graph.nodes[start_node]["pos"][:2]
        )
    if end_node is not None:
        coordinates[-1] = airport_graph.project.transform(
            *airport_graph.graph.nodes[end_node]["pos"][:2]
        )
    return airport_graph.to_wgs84_shape(LineString(coordinates))


def apply_source_segments(data: dict[str, Any], segments: tuple[SourceSegment, ...]) -> None:
    """Store the sole authoritative source chain for an edge."""
    normalized = compact_source_segments(segments)
    data["source_segments"] = normalized
    for name in ("source_id", "source_start_m", "source_end_m"):
        data.pop(name, None)
    if len(normalized) > 1:
        data["source_type"] = "composite"
        data.pop("osm_node_ids", None)


def validate_edge_endpoints(
    airport_graph: AirportGraph,
    tolerance_m: float = ENDPOINT_TOLERANCE_M,
    edge_ids: Iterable[tuple[Any, Any, Any]] | None = None,
) -> None:
    records = (
        airport_graph.graph.edges(keys=True, data=True)
        if edge_ids is None
        else ((u, v, key, airport_graph.graph.edges[u, v, key]) for u, v, key in edge_ids)
    )
    for u, v, key, data in records:
        geometry = data.get("geometry")
        if not isinstance(geometry, LineString) or geometry.is_empty:
            raise ValueError(f"Edge {(u, v, key)!r} has no valid LineString geometry")
        projected = airport_graph.project_shape(geometry)
        endpoints = (Point(projected.coords[0]), Point(projected.coords[-1]))
        node_points = tuple(
            Point(airport_graph.project.transform(*airport_graph.graph.nodes[node]["pos"][:2]))
            for node in (u, v)
        )
        forward = max(endpoints[index].distance(node_points[index]) for index in (0, 1))
        reverse = max(endpoints[index].distance(node_points[1 - index]) for index in (0, 1))
        if min(forward, reverse) > tolerance_m:
            raise ValueError(f"Edge {(u, v, key)!r} geometry endpoints do not match its nodes")


def validate_edge_sources(
    airport_graph: AirportGraph,
    tolerance_m: float = ENDPOINT_TOLERANCE_M,
    edge_ids: Iterable[tuple[Any, Any, Any]] | None = None,
) -> None:
    """Require every attributed edge geometry to be reproducible from its source chain."""
    records = (
        airport_graph.graph.edges(keys=True, data=True)
        if edge_ids is None
        else ((u, v, key, airport_graph.graph.edges[u, v, key]) for u, v, key in edge_ids)
    )
    for u, v, key, data in records:
        segments = edge_source_segments(data)
        if not segments:
            raise ValueError(f"Edge {(u, v, key)!r} has no source segments")
        for segment in segments:
            if segment.source_id not in airport_graph.source_edges:
                raise ValueError(
                    f"Edge {(u, v, key)!r} references unknown source {segment.source_id!r}"
                )
            source_length = airport_graph.length(
                airport_graph.get_source_edge(segment.source_id).geometry
            )
            if segment.source_end_m > source_length + tolerance_m:
                raise ValueError(
                    f"Edge {(u, v, key)!r} interval exceeds source {segment.source_id!r}"
                )
        rebuilt = geometry_from_source_segments(
            airport_graph, segments, data["first"], data["last"]
        )
        saved = airport_graph.project_shape(data["geometry"])
        expected = airport_graph.project_shape(rebuilt)
        if (
            saved.hausdorff_distance(expected) > tolerance_m
            or abs(saved.length - expected.length) > tolerance_m
        ):
            raise ValueError(f"Edge {(u, v, key)!r} geometry does not match its source segments")


def validate_source_intervals(
    airport_graph: AirportGraph, tolerance_m: float = ENDPOINT_TOLERANCE_M
) -> None:
    """Require native derived pieces to continuously cover every complete source."""
    for source_id, source in airport_graph.source_edges.items():
        pieces = sorted(
            (
                (segment.source_start_m, segment.source_end_m)
                for *_edge, data in airport_graph.derived_edges(source_id)
                for segment in edge_source_segments(data)
                if segment.source_id == source_id
            ),
            key=lambda interval: interval[0],
        )
        if not pieces:
            raise ValueError(f"Source {source_id!r} has no derived edges")
        source_length = airport_graph.length(source.geometry)
        if abs(pieces[0][0]) > tolerance_m or abs(pieces[-1][1] - source_length) > tolerance_m:
            raise ValueError(f"Source {source_id!r} intervals do not cover its complete geometry")
        for left, right in zip(pieces, pieces[1:]):
            if abs(left[1] - right[0]) > tolerance_m:
                raise ValueError(f"Source {source_id!r} has a gap or overlap in its intervals")


def _graph_document(airport_graph: AirportGraph) -> dict[str, Any]:
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "airport": airport_graph.metadata.airport,
        "projection": airport_graph.projection.srs,
        "build_issues": list(airport_graph.metadata.build_issues),
        "source_nodes": {
            str(node_id): {
                "node_id": to_json_value(source.node_id),
                "position": to_json_value(source.position),
                "osm_node_ids": to_json_value(source.osm_node_ids),
                "attributes": to_json_value(dict(source.attributes)),
            }
            for node_id, source in airport_graph.source_nodes.items()
        },
        "node_aliases": [
            [to_json_value(alias), to_json_value(canonical)]
            for alias, canonical in airport_graph.node_aliases.items()
        ],
        "source_edges": {
            source_id: {
                "geometry": mapping(source.geometry),
                "source_type": source.source_type,
                "osm_way_id": to_json_value(source.osm_way_id),
                "osm_node_ids": to_json_value(source.osm_node_ids),
                "attributes": to_json_value(dict(source.attributes)),
            }
            for source_id, source in airport_graph.source_edges.items()
        },
        "nodes": [
            {
                "id": to_json_value(node),
                "pos": to_json_value(data["pos"]),
                "attributes": to_json_value(
                    {key: value for key, value in data.items() if key != "pos"}
                ),
            }
            for node, data in airport_graph.graph.nodes(data=True)
        ],
        "edges": [
            {
                "u": to_json_value(u),
                "v": to_json_value(v),
                "key": to_json_value(key),
                "geometry": mapping(data["geometry"]),
                "attributes": to_json_value(
                    {name: value for name, value in data.items() if name != "geometry"}
                ),
            }
            for u, v, key, data in airport_graph.graph.edges(keys=True, data=True)
        ],
    }


def _document_graph_id(document: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "graph_id"}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def graph_id(airport_graph: AirportGraph) -> str:
    """Return the content identity of the graph in its persistent representation."""
    return _document_graph_id(_graph_document(airport_graph))


def save_graph(airport_graph: AirportGraph, path: str | Path = DEFAULT_GRAPH_PATH) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    document = _graph_document(airport_graph)
    document["graph_id"] = _document_graph_id(document)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


def load_graph(path: str | Path = DEFAULT_GRAPH_PATH) -> AirportGraph:

    source_path = Path(path)
    document = json.loads(source_path.read_text(encoding="utf-8"))
    schema_version = document.get("schema_version")
    if schema_version != GRAPH_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported airport graph schema version: {schema_version!r}; "
            f"expected {GRAPH_SCHEMA_VERSION}"
        )
    declared_graph_id = document.get("graph_id")
    if declared_graph_id is not None:
        actual_graph_id = _document_graph_id(document)
        if declared_graph_id != actual_graph_id:
            raise ValueError(
                f"Airport graph content does not match graph_id: "
                f"expected {declared_graph_id!r}, got {actual_graph_id!r}"
            )
    # Legacy top-level business collections are deliberately ignored after hash validation.
    # Semantic attributes are authoritative; old collections must not create new labels.
    graph = nx.MultiGraph()
    for node in document["nodes"]:
        graph.add_node(node["id"], pos=tuple(node["pos"]), **node["attributes"])
    for edge in document["edges"]:
        attributes = edge["attributes"]
        if "source_segments" in attributes:
            attributes["source_segments"] = tuple(
                SourceSegment(
                    segment["source_id"],
                    segment["source_start_m"],
                    segment["source_end_m"],
                    segment.get("reversed", False),
                )
                for segment in attributes["source_segments"]
            )
        graph.add_edge(
            edge["u"],
            edge["v"],
            key=edge["key"],
            geometry=shape(edge["geometry"]),
            **attributes,
        )
    source_nodes = {
        item["node_id"]: SourceNode(
            item["node_id"],
            tuple(item["position"]),
            tuple(item.get("osm_node_ids", (item["node_id"],))),
            item.get("attributes", {}),
        )
        for item in document.get("source_nodes", {}).values()
    }
    source_edges: dict[str, SourceEdge] = {}
    for source_id, item in document.get("source_edges", {}).items():
        geometry = shape(item["geometry"])
        if not isinstance(geometry, LineString):
            raise ValueError(
                f"Source {source_id!r} requires LineString geometry, got {geometry.geom_type}"
            )
        source_edges[source_id] = SourceEdge(
            source_id,
            geometry,
            item["source_type"],
            item.get("osm_way_id"),
            tuple(item.get("osm_node_ids", ())),
            item.get("attributes", {}),
        )
    metadata = GraphMetadata(
        airport=document.get("airport", "ZBAA"),
        build_issues=tuple(document.get("build_issues", ())),
    )
    projection_value = document.get("projection", "UTM zone 50")
    projection = Proj("EPSG:32650") if projection_value == "UTM zone 50" else Proj(projection_value)
    return AirportGraph(
        graph,
        projection,
        source_nodes=source_nodes,
        source_edges=source_edges,
        node_aliases=dict(document.get("node_aliases", ())),
        metadata=metadata,
    )
