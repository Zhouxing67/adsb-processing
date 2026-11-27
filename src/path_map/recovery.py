"""Observation projection and matched path post-processing utilities."""

from __future__ import annotations

from collections.abc import Sequence

from shapely.geometry import Point

from airport_surface import AirportGraph
from flight import Flight

from .path import DirectedEdge, EdgeId


def project_observations(airport_graph: AirportGraph, flight: Flight) -> list[Point]:
    """Project WGS84 flight observations into the airport graph's metric plane."""
    coordinates = [(point.longitude, point.latitude) for point in flight.observations]
    longitude, latitude = zip(*coordinates)
    x, y = airport_graph.project.transform(longitude, latitude)
    return [Point(float(px), float(py)) for px, py in zip(x, y)]


def trim_runway_edges(
    edges: Sequence[DirectedEdge],
    runway_edges: frozenset[EdgeId],
    *,
    is_departure: bool,
) -> list[DirectedEdge]:
    """Trim runway-roll edges on the runway side so the path ends at the interface taxiway."""
    if is_departure:
        trimmed = list(edges)
        while trimmed and trimmed[-1].id in runway_edges:
            trimmed.pop()
        return trimmed
    first_taxi = next(
        (i for i, edge in enumerate(edges) if edge.id not in runway_edges),
        len(edges),
    )
    return list(edges[first_taxi:])
