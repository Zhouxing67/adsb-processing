"""Structural and geometric invariant checks for AirportGraph."""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from shapely.geometry import LineString, Point

from .models import AirportGraph, edge_source_segments
from .source_chain import ENDPOINT_TOLERANCE_M, geometry_from_source_segments


def _iter_edges(
    airport_graph: AirportGraph,
    edge_ids: Iterable[tuple[Any, Any, Any]] | None,
) -> Iterator[tuple[Any, Any, Any, dict[str, Any]]]:
    if edge_ids is None:
        yield from airport_graph.graph.edges(keys=True, data=True)
        return
    for u, v, key in edge_ids:
        yield u, v, key, airport_graph.graph.edges[u, v, key]


def validate_edge_endpoints(
    airport_graph: AirportGraph,
    tolerance_m: float = ENDPOINT_TOLERANCE_M,
    edge_ids: Iterable[tuple[Any, Any, Any]] | None = None,
) -> None:
    """Require every edge geometry's endpoints to match its incident graph nodes."""
    for u, v, key, data in _iter_edges(airport_graph, edge_ids):
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
    for u, v, key, data in _iter_edges(airport_graph, edge_ids):
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
    pieces_by_source: dict[str, list[tuple[float, float]]] = {
        source_id: [] for source_id in airport_graph.source_edges
    }
    for _u, _v, data in airport_graph.graph.edges(data=True):
        for segment in edge_source_segments(data):
            if segment.source_id in pieces_by_source:
                pieces_by_source[segment.source_id].append(
                    (segment.source_start_m, segment.source_end_m)
                )

    for source_id, source in airport_graph.source_edges.items():
        pieces = sorted(pieces_by_source[source_id], key=lambda interval: interval[0])
        if not pieces:
            raise ValueError(f"Source {source_id!r} has no derived edges")
        source_length = airport_graph.length(source.geometry)
        if abs(pieces[0][0]) > tolerance_m or abs(pieces[-1][1] - source_length) > tolerance_m:
            raise ValueError(f"Source {source_id!r} intervals do not cover its complete geometry")
        for left, right in zip(pieces, pieces[1:]):
            if abs(left[1] - right[0]) > tolerance_m:
                raise ValueError(f"Source {source_id!r} has a gap or overlap in its intervals")
