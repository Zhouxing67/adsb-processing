"""Offline airport graph construction backed by the optional traffic package."""

from __future__ import annotations

import math
from typing import Any

from pyproj import CRS, Proj

from .graph import (
    _build_derived_graph,
    _canonicalize_source_nodes,
    _extract_sources,
    _geometric_crossing_issues,
    _node_attributes_from_osm,
    validate_edge_endpoints,
    validate_edge_sources,
    validate_source_intervals,
)
from .models import AirportGraph


def build_airport_graph(airport: Any, projection: Proj) -> AirportGraph:
    """Build a graph from a traffic Airport in an explicit offline workflow."""
    osm = airport._openstreetmap()
    raw_graph = osm.network_graph(
        "geometry",
        "aeroway",
        "parking_position",
        "ref",
        "name",
        "id_",
        "nodes",
        query_str='aeroway == "taxiway" or aeroway == "runway" or aeroway == "parking_position"',
    )
    sources, node_positions, issues = _extract_sources(raw_graph)
    source_nodes, aliases = _canonicalize_source_nodes(
        node_positions, _node_attributes_from_osm(osm)
    )
    issues.extend(_geometric_crossing_issues(sources, aliases))
    graph = _build_derived_graph(
        sources,
        source_nodes,
        aliases,
        projection,
        airport.icao,
        issues,
    )
    validate_edge_endpoints(graph)
    validate_edge_sources(graph)
    validate_source_intervals(graph)
    return graph


def resolve_projection(specification: str) -> Proj:
    """Resolve and validate an explicitly selected metric projected CRS."""
    try:
        crs = CRS.from_user_input(specification)
    except Exception as error:
        raise ValueError(f"Invalid projection: {specification!r}") from error

    if not crs.is_projected:
        raise ValueError(f"Projection must be a projected CRS, got {crs.name!r}")
    horizontal_axes = crs.axis_info[:2]
    if len(horizontal_axes) != 2 or any(
        not math.isclose(axis.unit_conversion_factor or 0, 1.0) for axis in horizontal_axes
    ):
        raise ValueError("Projection horizontal units must be metres")
    return Proj(crs)


def build_graph(icao: str, projection: str) -> AirportGraph:
    """Load one airport from traffic's registry and build its surface graph."""
    from traffic.data import airports

    normalized_icao = icao.strip().upper()
    if not normalized_icao:
        raise ValueError("ICAO airport code must not be empty")
    try:
        airport = airports[normalized_icao]
    except KeyError as error:
        raise ValueError(f"Airport is not available from traffic: {normalized_icao}") from error
    return build_airport_graph(airport, resolve_projection(projection))
