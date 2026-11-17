"""Offline airport graph construction backed by the optional traffic package."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any, Hashable, Mapping

import networkx as nx
import numpy as np
from pyproj import CRS, Proj
from shapely import STRtree
from shapely.geometry import LineString, Point

from .graph import (
    ENDPOINT_TOLERANCE_M,
    validate_edge_endpoints,
    validate_edge_sources,
    validate_source_intervals,
)
from .models import AirportGraph, GraphMetadata, SourceEdge, SourceNode, SourceSegment


def _source_identifier(
    registry: Mapping[str, SourceEdge], way_id: Any, u: Any, v: Any, key: Any
) -> str:
    preferred = f"osm-way-{way_id}" if way_id is not None else f"osm-edge-{u}-{v}-{key}"
    if preferred not in registry:
        return preferred
    index = 2
    while f"{preferred}-{index}" in registry:
        index += 1
    return f"{preferred}-{index}"


def _source_attributes(data: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {
        "geometry",
        "first",
        "last",
        "id_",
        "nodes",
        "source_id",
        "source_type",
        "source_start_m",
        "source_end_m",
        "split_from",
    }
    return {name: deepcopy(value) for name, value in data.items() if name not in excluded}


def _extract_sources(
    raw_graph: nx.MultiGraph,
) -> tuple[dict[str, SourceEdge], dict[Hashable, tuple[float, float]], list[str]]:
    source_edges: dict[str, SourceEdge] = {}
    node_positions: dict[Hashable, tuple[float, float]] = {}
    issues: list[str] = []
    for u, v, key, data in raw_graph.edges(keys=True, data=True):
        geometry = data.get("geometry")
        if not isinstance(geometry, LineString) or geometry.is_empty:
            issues.append(f"raw edge {(u, v, key)!r} has no non-empty LineString")
            continue
        raw_node_ids = data.get("nodes")
        node_ids = tuple(
            raw_node_ids
            if raw_node_ids is not None
            else (data.get("first", u), data.get("last", v))
        )
        coordinates = tuple(tuple(coordinate[:2]) for coordinate in geometry.coords)
        if len(node_ids) != len(coordinates):
            issues.append(
                f"raw edge {(u, v, key)!r} has {len(node_ids)} OSM nodes but "
                f"{len(coordinates)} geometry coordinates"
            )
            continue
        for node_id, coordinate in zip(node_ids, coordinates):
            previous = node_positions.setdefault(node_id, coordinate)
            if previous != coordinate:
                issues.append(f"OSM node {node_id!r} has inconsistent coordinates")
        way_id = data.get("id_", data.get("osm_way_id"))
        source_id = _source_identifier(source_edges, way_id, u, v, key)
        source_edges[source_id] = SourceEdge(
            source_id,
            geometry,
            "osm",
            way_id,
            node_ids,
            _source_attributes(data),
        )
    return source_edges, node_positions, issues


def _canonicalize_source_nodes(
    node_positions: Mapping[Hashable, tuple[float, float]],
    node_attributes: Mapping[Hashable, Mapping[str, Any]] | None = None,
) -> tuple[dict[Hashable, SourceNode], dict[Hashable, Hashable]]:
    groups: dict[tuple[float, float], list[Hashable]] = defaultdict(list)
    for node_id, position in node_positions.items():
        groups[position].append(node_id)
    source_nodes: dict[Hashable, SourceNode] = {}
    aliases: dict[Hashable, Hashable] = {}
    node_attributes = node_attributes or {}
    for position, node_ids in groups.items():
        canonical = node_ids[0]
        attributes = {
            "osm_node_attributes": {
                str(node_id): deepcopy(dict(node_attributes.get(node_id, {})))
                for node_id in node_ids
            }
        }
        source_nodes[canonical] = SourceNode(canonical, position, tuple(node_ids), attributes)
        aliases.update({node_id: canonical for node_id in node_ids if node_id != canonical})
    return source_nodes, aliases


def _topology_nodes(
    source_edges: Mapping[str, SourceEdge], aliases: Mapping[Hashable, Hashable]
) -> set[Hashable]:
    node_sources: dict[Hashable, set[str]] = defaultdict(set)
    repeated: set[Hashable] = set()
    endpoints: set[Hashable] = set()
    for source_id, source in source_edges.items():
        canonical = [aliases.get(node, node) for node in source.osm_node_ids]
        endpoints.update((canonical[0], canonical[-1]))
        repeated.update(node for node, count in Counter(canonical).items() if count > 1)
        for node in set(canonical):
            node_sources[node].add(source_id)
    shared = {node for node, sources in node_sources.items() if len(sources) > 1}
    return endpoints | shared | repeated


def _geometric_crossing_issues(
    source_edges: Mapping[str, SourceEdge], aliases: Mapping[Hashable, Hashable]
) -> list[str]:
    identifiers = list(source_edges)
    geometries = [source_edges[identifier].geometry for identifier in identifiers]
    if not geometries:
        return []
    tree = STRtree(geometries)
    issues: list[str] = []
    for left_index, left_geometry in enumerate(geometries):
        for raw_right_index in np.asarray(tree.query(left_geometry)).tolist():
            right_index = int(raw_right_index)
            if right_index <= left_index:
                continue
            left_id, right_id = identifiers[left_index], identifiers[right_index]
            left_nodes = {aliases.get(node, node) for node in source_edges[left_id].osm_node_ids}
            right_nodes = {aliases.get(node, node) for node in source_edges[right_id].osm_node_ids}
            intersection = left_geometry.intersection(geometries[right_index])
            if left_geometry.equals(geometries[right_index]):
                issues.append(f"sources {left_id!r} and {right_id!r} have duplicate geometry")
                continue
            if intersection.is_empty or left_nodes & right_nodes:
                continue
            issues.append(
                f"sources {left_id!r} and {right_id!r} intersect geometrically "
                "without a shared OSM node"
            )
    return issues


def _node_attributes_from_osm(osm: Any) -> dict[Hashable, dict[str, Any]]:
    """Extract available OSM node tags without making them topology evidence."""
    frame = osm.parse()
    if not {"type_", "id_"} <= set(frame.columns):
        return {}
    excluded = {
        "_parent",
        "id_",
        "type_",
        "geometry",
        "latitude",
        "longitude",
        "nodes",
    }
    attributes: dict[Hashable, dict[str, Any]] = {}
    for _index, row in frame.loc[frame["type_"] == "node"].iterrows():
        attributes[row["id_"]] = {
            name: value
            for name, value in row.items()
            if name not in excluded
            and value is not None
            and not (isinstance(value, float) and math.isnan(value))
        }
    return attributes


def _cumulative_distances(graph: AirportGraph, geometry: LineString) -> list[float]:
    projected = graph.project_shape(geometry)
    distances = [0.0]
    for left, right in zip(projected.coords, projected.coords[1:]):
        distances.append(distances[-1] + Point(left).distance(Point(right)))
    return distances


def _build_derived_graph(
    source_edges: Mapping[str, SourceEdge],
    source_nodes: Mapping[Hashable, SourceNode],
    aliases: Mapping[Hashable, Hashable],
    projection: Any,
    airport: str,
    initial_issues: list[str],
) -> AirportGraph:
    graph = nx.MultiGraph()
    topology_nodes = _topology_nodes(source_edges, aliases)
    for node_id in topology_nodes:
        source_node = source_nodes[node_id]
        graph.add_node(
            node_id,
            pos=source_node.position,
            source_type="osm",
            osm_node_ids=source_node.osm_node_ids,
        )
    airport_graph = AirportGraph(
        graph,
        projection,
        source_nodes=source_nodes,
        source_edges=source_edges,
        node_aliases=aliases,
        metadata=GraphMetadata(airport=airport),
    )
    issues = list(initial_issues)
    for source_id, source in source_edges.items():
        original_nodes = source.osm_node_ids
        canonical_nodes = tuple(aliases.get(node, node) for node in original_nodes)
        coordinates = tuple(source.geometry.coords)
        distances = _cumulative_distances(airport_graph, source.geometry)
        split_indices = [
            index
            for index, node_id in enumerate(canonical_nodes)
            if index in {0, len(canonical_nodes) - 1} or node_id in topology_nodes
        ]
        if source.attributes.get("aeroway") == "parking_position":
            split_indices = [0, len(canonical_nodes) - 1]
        for start_index, end_index in zip(split_indices, split_indices[1:]):
            first, last = canonical_nodes[start_index], canonical_nodes[end_index]
            geometry = LineString(coordinates[start_index : end_index + 1])
            data = dict(source.attributes)
            data.update(
                geometry=geometry,
                first=first,
                last=last,
                source_id=source_id,
                source_type=source.source_type,
                source_start_m=distances[start_index],
                source_end_m=distances[end_index],
                osm_node_ids=original_nodes[start_index : end_index + 1],
                source_segments=(
                    SourceSegment(source_id, distances[start_index], distances[end_index]),
                ),
            )
            graph.add_edge(first, last, **data)
            if first == last:
                issues.append(f"source {source_id!r} produced self-loop at node {first!r}")
            if airport_graph.length(geometry) <= ENDPOINT_TOLERANCE_M:
                issues.append(f"source {source_id!r} produced a zero-length derived edge")
    airport_graph.metadata = GraphMetadata(
        airport=airport,
        build_issues=tuple(issues),
    )
    airport_graph.rebuild_stand_index()
    airport_graph.rebuild_runway_interfaces()
    return airport_graph


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
    frame = osm.parse()
    if {"aeroway", "geometry", "id_"} <= set(frame.columns):
        for _, row in frame.loc[frame["aeroway"] == "parking_position"].iterrows():
            geometry = row["geometry"]
            if getattr(geometry, "geom_type", None) == "Point":
                node_positions[row["id_"]] = (geometry.x, geometry.y)
        source_nodes, aliases = _canonicalize_source_nodes(
            node_positions, _node_attributes_from_osm(osm)
        )
    graph = _build_derived_graph(
        sources,
        source_nodes,
        aliases,
        projection,
        airport.icao,
        issues,
    )
    for node, source in source_nodes.items():
        tags = source.attributes.get("osm_node_attributes", {})
        if any(value.get("aeroway") == "parking_position" for value in tags.values()):
            if node not in graph.graph:
                graph.graph.add_node(
                    node, pos=source.position, source_type="osm", osm_node_ids=source.osm_node_ids
                )
            graph.graph.nodes[node]["aeroway"] = "parking_position"
    validate_edge_endpoints(graph)
    validate_edge_sources(graph)
    validate_source_intervals(graph)
    graph.rebuild_stand_index()
    graph.rebuild_runway_interfaces()
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
