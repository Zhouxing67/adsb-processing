"""Source-chain algorithms and edge geometry reconstruction."""

from __future__ import annotations

from typing import Any

from shapely.geometry import LineString, Point
from shapely.ops import substring

from .models import AirportGraph, SourceSegment

ENDPOINT_TOLERANCE_M = 1e-3


def cumulative_distances(airport_graph: AirportGraph, geometry: LineString) -> list[float]:
    """Return cumulative metric station distances along ``geometry`` vertices."""
    projected = airport_graph.project_shape(geometry)
    distances = [0.0]
    for left, right in zip(projected.coords, projected.coords[1:]):
        distances.append(distances[-1] + Point(left).distance(Point(right)))
    return distances


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


def split_source_chain(
    segments: tuple[SourceSegment, ...], segment_index: int, station: float
) -> tuple[tuple[SourceSegment, ...], tuple[SourceSegment, ...]]:
    """Split at a station within the selected source interval.

    Preserve traversal order and compact adjacent intervals. Pieces within
    1 mm of the boundary are omitted, matching existing editor behavior.
    Either half may be empty; callers decide whether that is allowed.
    The input and immutable source records are not modified.
    """
    segment = segments[segment_index]
    before, after = list(segments[:segment_index]), list(segments[segment_index + 1 :])
    if segment.reversed:
        if station < segment.source_end_m - ENDPOINT_TOLERANCE_M:
            before.append(SourceSegment(segment.source_id, station, segment.source_end_m, True))
        if station > segment.source_start_m + ENDPOINT_TOLERANCE_M:
            after.insert(
                0,
                SourceSegment(segment.source_id, segment.source_start_m, station, True),
            )
    else:
        if station > segment.source_start_m + ENDPOINT_TOLERANCE_M:
            before.append(SourceSegment(segment.source_id, segment.source_start_m, station))
        if station < segment.source_end_m - ENDPOINT_TOLERANCE_M:
            after.insert(0, SourceSegment(segment.source_id, station, segment.source_end_m))
    return compact_source_segments(before), compact_source_segments(after)


def _projected_source_piece(
    airport_graph: AirportGraph,
    source_id: str,
    start_m: float,
    end_m: float,
) -> LineString:
    source = airport_graph.get_source_edge(source_id)
    projected = airport_graph.project_shape(source.geometry)
    piece = substring(projected, start_m, end_m)
    if not isinstance(piece, LineString):
        raise ValueError(f"Source interval {(start_m, end_m)!r} has no length")
    return piece


def _snap_projected_endpoints(
    airport_graph: AirportGraph,
    coordinates: list[tuple[float, ...]],
    start_node: Any | None,
    end_node: Any | None,
) -> None:
    if start_node is not None:
        coordinates[0] = airport_graph.project.transform(
            *airport_graph.graph.nodes[start_node]["pos"][:2]
        )
    if end_node is not None:
        coordinates[-1] = airport_graph.project.transform(
            *airport_graph.graph.nodes[end_node]["pos"][:2]
        )


def geometry_from_source_interval(
    airport_graph: AirportGraph,
    source_id: str,
    start_m: float,
    end_m: float,
    start_node: Any | None = None,
    end_node: Any | None = None,
) -> LineString:
    """Extract one interval from a source edge in WGS84 coordinates."""
    piece = _projected_source_piece(airport_graph, source_id, start_m, end_m)
    coordinates = list(piece.coords)
    _snap_projected_endpoints(airport_graph, coordinates, start_node, end_node)
    return airport_graph.to_wgs84_shape(LineString(coordinates))


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
        piece = _projected_source_piece(
            airport_graph,
            segment.source_id,
            segment.source_start_m,
            segment.source_end_m,
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
    _snap_projected_endpoints(airport_graph, coordinates, start_node, end_node)
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
