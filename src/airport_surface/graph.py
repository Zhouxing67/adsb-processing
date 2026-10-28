"""Build, validate, save, and load the airport surface graph."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Hashable, Iterable, Mapping

import networkx as nx
import numpy as np
from cartes.crs import UTM
from pyproj import Proj
from shapely import STRtree
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import substring

from .models import (
    AirportGraph,
    GraphMetadata,
    NodeMergeGroup,
    NodeSnapRecord,
    SourceEdge,
    SourceNode,
    SourceSegment,
    edge_source_segments,
)

DEFAULT_GRAPH_PATH = Path("data/graphs/zbaa_final.json")
GRAPH_SCHEMA_VERSION = 1
ENDPOINT_TOLERANCE_M = 1e-3


def source_registry(airport_graph: AirportGraph) -> dict[str, SourceEdge]:
    return airport_graph.source_edges


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
        node_merge_groups={},
        node_snap_records=[],
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
    return airport_graph


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
    """Store a source chain and maintain legacy scalar fields for a single interval."""
    normalized = compact_source_segments(segments)
    data["source_segments"] = normalized
    if len(normalized) == 1:
        segment = normalized[0]
        source = segment.source_id
        data.update(
            source_id=source,
            source_start_m=segment.source_start_m,
            source_end_m=segment.source_end_m,
        )
    else:
        data["source_type"] = "composite"
        for name in ("source_id", "source_start_m", "source_end_m", "osm_node_ids"):
            data.pop(name, None)


def source_boundaries(airport_graph: AirportGraph, source_id: str) -> list[tuple[float, Any]]:
    boundaries: dict[float, Any] = {}
    for _u, _v, data in airport_graph.graph.edges(data=True):
        if data.get("source_id") == source_id:
            boundaries[float(data["source_start_m"])] = data["first"]
            boundaries[float(data["source_end_m"])] = data["last"]
    return sorted(boundaries.items())


def rebuild_source_edges(
    airport_graph: AirportGraph,
    source_id: str,
    boundaries: list[tuple[float, Any]],
) -> None:
    source = airport_graph.get_source_edge(source_id)
    for u, v, key, _data in airport_graph.derived_edges(source_id):
        airport_graph.graph.remove_edge(u, v, key)
    for (start_m, first), (end_m, last) in zip(boundaries, boundaries[1:]):
        data = dict(source.attributes)
        data.update(
            geometry=geometry_from_source_interval(
                airport_graph, source_id, start_m, end_m, first, last
            ),
            first=first,
            last=last,
            source_id=source_id,
            source_type=source.source_type,
            source_start_m=start_m,
            source_end_m=end_m,
            source_segments=(SourceSegment(source_id, start_m, end_m),),
        )
        airport_graph.graph.add_edge(first, last, **data)


def validate_edge_endpoints(
    airport_graph: AirportGraph,
    tolerance_m: float = ENDPOINT_TOLERANCE_M,
    edge_ids: Iterable[tuple[Any, Any, Any]] | None = None,
) -> None:
    records = (
        airport_graph.graph.edges(keys=True, data=True)
        if edge_ids is None
        else (
            (u, v, key, airport_graph.graph.edges[u, v, key]) for u, v, key in edge_ids
        )
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
        else (
            (u, v, key, airport_graph.graph.edges[u, v, key]) for u, v, key in edge_ids
        )
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


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "item"):
        return _json_value(value.item())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _graph_document(airport_graph: AirportGraph) -> dict[str, Any]:
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "airport": airport_graph.metadata.airport,
        "projection": airport_graph.projection.srs,
        "build_issues": list(airport_graph.metadata.build_issues),
        "source_nodes": {
            str(node_id): {
                "node_id": _json_value(source.node_id),
                "position": _json_value(source.position),
                "osm_node_ids": _json_value(source.osm_node_ids),
                "attributes": _json_value(dict(source.attributes)),
            }
            for node_id, source in airport_graph.source_nodes.items()
        },
        "node_aliases": [
            [_json_value(alias), _json_value(canonical)]
            for alias, canonical in airport_graph.node_aliases.items()
        ],
        "node_merge_groups": [
            {
                "canonical_node_id": _json_value(group.canonical_node_id),
                "member_node_ids": _json_value(group.member_node_ids),
                "original_positions": [
                    [_json_value(node), _json_value(position)]
                    for node, position in group.original_positions.items()
                ],
                "merge_type": group.merge_type,
            }
            for group in airport_graph.node_merge_groups.values()
        ],
        "node_snap_records": [_json_value(record) for record in airport_graph.node_snap_records],
        "source_edges": {
            source_id: {
                "geometry": mapping(source.geometry),
                "source_type": source.source_type,
                "osm_way_id": _json_value(source.osm_way_id),
                "osm_node_ids": _json_value(source.osm_node_ids),
                "attributes": _json_value(dict(source.attributes)),
            }
            for source_id, source in airport_graph.source_edges.items()
        },
        "nodes": [
            {
                "id": _json_value(node),
                "pos": _json_value(data["pos"]),
                "attributes": _json_value(
                    {key: value for key, value in data.items() if key != "pos"}
                ),
            }
            for node, data in airport_graph.graph.nodes(data=True)
        ],
        "edges": [
            {
                "u": _json_value(u),
                "v": _json_value(v),
                "key": _json_value(key),
                "geometry": mapping(data["geometry"]),
                "attributes": _json_value(
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
    schema_version = document.get("schema_version", GRAPH_SCHEMA_VERSION)
    if schema_version != GRAPH_SCHEMA_VERSION:
        raise ValueError(f"Unsupported airport graph schema version: {schema_version!r}")
    declared_graph_id = document.get("graph_id")
    if declared_graph_id is not None:
        actual_graph_id = _document_graph_id(document)
        if declared_graph_id != actual_graph_id:
            raise ValueError(
                f"Airport graph content does not match graph_id: "
                f"expected {declared_graph_id!r}, got {actual_graph_id!r}"
            )
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
    source_edges = {
        source_id: SourceEdge(
            source_id,
            shape(item["geometry"]),
            item["source_type"],
            item.get("osm_way_id"),
            tuple(item.get("osm_node_ids", ())),
            item.get("attributes", {}),
        )
        for source_id, item in document.get("source_edges", {}).items()
    }
    metadata = GraphMetadata(
        airport=document.get("airport", "ZBAA"),
        build_issues=tuple(document.get("build_issues", ())),
    )
    merge_groups = {
        item["canonical_node_id"]: NodeMergeGroup(
            item["canonical_node_id"],
            tuple(item["member_node_ids"]),
            {node: tuple(position) for node, position in item["original_positions"]},
            item.get("merge_type", "manual"),
        )
        for item in document.get("node_merge_groups", ())
    }
    snap_records = [
        NodeSnapRecord(
            item["node_id"],
            tuple(item["original_position"]),
            tuple(item["snapped_position"]),
            item["target_source_id"],
            item["target_station_m"],
            item["distance_m"],
        )
        for item in document.get("node_snap_records", ())
    ]
    projection_value = document.get("projection", "UTM zone 50")
    projection = UTM(zone=50) if projection_value == "UTM zone 50" else Proj(projection_value)
    return AirportGraph(
        graph,
        projection,
        source_nodes=source_nodes,
        source_edges=source_edges,
        node_aliases=dict(document.get("node_aliases", ())),
        node_merge_groups=merge_groups,
        node_snap_records=snap_records,
        metadata=metadata,
    )
