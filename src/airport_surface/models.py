"""Project-owned airport surface graph and immutable OSM source records."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Self, overload

import networkx as nx
from pyproj import Proj, Transformer
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from .identifiers import (
    EdgeId,
    EdgeKey,
    NodeId,
    OsmId,
    normalize_osm_id,
    validate_edge_key,
    validate_node_id,
)


def _freeze_source_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {deepcopy(key): _freeze_source_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_source_value(item) for item in value)
    return deepcopy(value)


def mutable_source_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached mutable copy of recursively frozen source attributes."""

    def thaw(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {deepcopy(key): thaw(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return [thaw(item) for item in value]
        return deepcopy(value)

    return {key: thaw(value) for key, value in attributes.items()}


@dataclass(frozen=True, slots=True)
class SourceNode:
    """One canonical OSM node and any exactly colocated OSM aliases."""

    node_id: NodeId
    position: tuple[float, float]
    osm_node_ids: tuple[NodeId, ...]
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", validate_node_id(self.node_id))
        object.__setattr__(self, "position", tuple(self.position[:2]))
        object.__setattr__(
            self,
            "osm_node_ids",
            tuple(normalize_osm_id(node_id) for node_id in self.osm_node_ids),
        )
        object.__setattr__(self, "attributes", _freeze_source_value(self.attributes))


@dataclass(frozen=True, slots=True)
class SourceEdge:
    """An immutable complete OSM way or explicitly created manual source."""

    source_id: str
    geometry: LineString
    source_type: str
    osm_way_id: OsmId | None = None
    osm_node_ids: tuple[NodeId, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.osm_way_id is not None:
            object.__setattr__(self, "osm_way_id", normalize_osm_id(self.osm_way_id))
        object.__setattr__(
            self,
            "osm_node_ids",
            tuple(normalize_osm_id(node_id) for node_id in self.osm_node_ids),
        )
        object.__setattr__(self, "attributes", _freeze_source_value(self.attributes))


@dataclass(frozen=True, slots=True)
class SourceSegment:
    """One ordered interval of an immutable SourceEdge used by a graph edge."""

    source_id: str
    source_start_m: float
    source_end_m: float
    reversed: bool = False

    def __post_init__(self) -> None:
        start = float(self.source_start_m)
        end = float(self.source_end_m)
        if start < 0 or end <= start:
            raise ValueError(f"Invalid source interval: {(start, end)!r}")
        object.__setattr__(self, "source_start_m", start)
        object.__setattr__(self, "source_end_m", end)


def edge_source_segments(data: Mapping[str, Any]) -> tuple[SourceSegment, ...]:
    """Read the authoritative source chain stored on a schema-v2 edge."""
    raw_segments = data.get("source_segments")
    if raw_segments is None:
        return ()
    return tuple(
        item
        if isinstance(item, SourceSegment)
        else SourceSegment(
            item["source_id"],
            item["source_start_m"],
            item["source_end_m"],
            item.get("reversed", False),
        )
        for item in raw_segments
    )


@dataclass(frozen=True, slots=True)
class GraphMetadata:
    airport: str
    build_issues: tuple[str, ...] = ()

    @classmethod
    def unknown_airport(cls) -> Self:
        return cls(airport="UNKNOWN")


class AirportGraph:
    """Airport topology, projection helpers, and authoritative source registries."""

    wgs84 = Proj("EPSG:4326")

    def __init__(
        self,
        graph: nx.MultiGraph,
        projection: Any,
        *,
        source_nodes: Mapping[NodeId, SourceNode] | None = None,
        source_edges: Mapping[str, SourceEdge] | None = None,
        node_aliases: Mapping[NodeId, NodeId] | None = None,
        metadata: GraphMetadata | None = None,
    ) -> None:
        self.graph = graph
        for node in self.graph:
            validate_node_id(node)
        for _u, _v, key in self.graph.edges(keys=True):
            validate_edge_key(key)
        self.projection = projection
        self.project = Transformer.from_proj(self.wgs84, projection, always_xy=True)
        self.to_wgs84 = Transformer.from_proj(projection, self.wgs84, always_xy=True)
        self.source_nodes = dict(source_nodes or {})
        self.source_edges = dict(source_edges or {})
        self.node_aliases = dict(node_aliases or {})
        self.metadata = GraphMetadata.unknown_airport() if metadata is None else metadata
        for _, _, data in self.graph.edges(data=True):
            segments = edge_source_segments(data)
            if segments:
                data["source_segments"] = segments
        self.rebuild_stand_index()
        self.rebuild_runway_interfaces()

    def rebuild_runway_interfaces(self) -> None:
        """Index runway-taxiway interface nodes and symmetric runway boundary edges.

        - ``runway_interfaces`` maps each node incident to both runway and taxiway
          edges to ``{"runway": ..., "taxiway": ...}``.
        - ``runway_to_edges`` maps each uppercase runway designator (e.g. ``"01"``)
          to the incident taxiway boundary edges (symmetric with ``stand_to_edges``).
        - ``edge_to_runways`` maps each runway-interface taxiway edge to the
          ``frozenset`` of connected uppercase runway designators (empty when the
          connected runway edge has no ``ref``).
        """
        incident: dict[NodeId, dict[str, list[EdgeId]]] = {}
        for u, v, key, data in self.graph.edges(keys=True, data=True):
            kind = data.get("aeroway")
            if kind in ("runway", "taxiway"):
                for node in {u, v}:
                    incident.setdefault(node, {"runway": [], "taxiway": []})[kind].append(
                        (u, v, key)
                    )
        self.runway_interfaces = {
            node: {kind: tuple(edges) for kind, edges in kinds.items()}
            for node, kinds in incident.items()
            if kinds["runway"] and kinds["taxiway"]
        }
        forward: dict[str, list[EdgeId]] = {}
        reverse: dict[EdgeId, set[str]] = {}
        for interface in self.runway_interfaces.values():
            refs: set[str] = set()
            for edge_id in interface["runway"]:
                raw_ref = str(self.graph.edges[edge_id].get("ref") or "").upper()
                refs.update(part.strip() for part in raw_ref.split("/") if part.strip())
            for taxiway_edge in interface["taxiway"]:
                reverse.setdefault(taxiway_edge, set()).update(refs)
                for ref in refs:
                    forward.setdefault(ref, []).append(taxiway_edge)
        self.runway_to_edges: dict[str, tuple[EdgeId, ...]] = {
            ref: tuple(dict.fromkeys(edges)) for ref, edges in forward.items()
        }
        self.edge_to_runways: dict[EdgeId, frozenset[str]] = {
            edge_id: frozenset(refs) for edge_id, refs in reverse.items()
        }

    def stand_for_edge(self, edge: EdgeId) -> str | None:
        """Return the stand ref for an undirected edge, regardless of orientation."""
        stand = self.edge_to_stand.get(edge)
        if stand is not None:
            return stand
        u, v, key = edge
        return self.edge_to_stand.get((v, u, key))

    def runways_for_edge(self, edge: EdgeId) -> frozenset[str] | None:
        """Return connected runway refs if ``edge`` is a runway-interface taxiway edge."""
        runways = self.edge_to_runways.get(edge)
        if runways is not None:
            return runways
        u, v, key = edge
        return self.edge_to_runways.get((v, u, key))

    def rebuild_stand_index(self) -> None:
        """Map OSM stand refs to edge IDs and back; unlabelled stands are omitted.

        The forward index groups every labelled edge by ref.
        Direct graph mutations require an explicit rebuild. Edge IDs use the
        orientation returned by graph.edges(), independent of travel direction.
        """
        forward: dict[str, list[EdgeId]] = {}
        reverse: dict[EdgeId, str] = {}
        for u, v, key, data in self.graph.edges(keys=True, data=True):
            if data.get("aeroway") != "parking_position":
                continue
            ref = data.get("ref")
            if ref is None or not str(ref).strip():
                continue
            stand_id = str(ref)
            edge_id = (u, v, key)
            forward.setdefault(stand_id, []).append(edge_id)
            reverse[edge_id] = stand_id
        self.stand_to_edges = {stand_id: tuple(edges) for stand_id, edges in forward.items()}
        self.edge_to_stand = reverse

    @property
    def components(self) -> list[int]:
        return [len(component) for component in nx.connected_components(self.graph)]

    @overload
    def project_shape(self, geometry: LineString) -> LineString: ...

    @overload
    def project_shape(self, geometry: BaseGeometry) -> BaseGeometry: ...

    def project_shape(self, geometry: BaseGeometry) -> BaseGeometry:
        """Transform coordinates while preserving the input geometry kind."""
        return transform(self.project.transform, geometry)

    @overload
    def to_wgs84_shape(self, geometry: LineString) -> LineString: ...

    @overload
    def to_wgs84_shape(self, geometry: BaseGeometry) -> BaseGeometry: ...

    def to_wgs84_shape(self, geometry: BaseGeometry) -> BaseGeometry:
        """Transform coordinates while preserving the input geometry kind."""
        return transform(self.to_wgs84.transform, geometry)

    def length(self, geometry: BaseGeometry) -> float:
        return self.project_shape(geometry).length

    def oriented_edge_geometry(self, u: NodeId, v: NodeId, key: EdgeKey) -> LineString:
        """Return edge geometry oriented along ``u -> v`` in WGS84 coordinates."""
        data = self.graph.edges[u, v, key]
        geometry = data["geometry"]
        if not isinstance(geometry, LineString):
            raise ValueError(f"Edge {(u, v, key)} geometry must be a LineString")
        node_position = self.graph.nodes[u].get("pos")
        if node_position is None:
            forward = data.get("first") == u if "first" in data else True
        else:
            forward = geometry.coords[0][:2] == tuple(node_position)[:2]
            if not forward:
                # OSM coordinates can differ by tiny floating point noise.
                node_point = Point(node_position)
                forward = Point(geometry.coords[0]).distance(node_point) <= Point(
                    geometry.coords[-1]
                ).distance(node_point)
        return geometry if forward else LineString(reversed(geometry.coords))

    def canonical_node_id(self, node_id: NodeId) -> NodeId:
        return self.node_aliases.get(node_id, node_id)

    def get_source_node(self, node_id: NodeId) -> SourceNode:
        return self.source_nodes[self.canonical_node_id(node_id)]

    def get_source_edge(self, source_id: str) -> SourceEdge:
        return self.source_edges[source_id]

    def derived_edges(self, source_id: str) -> list[tuple[Any, Any, Any, dict[str, Any]]]:
        return [
            (u, v, key, data)
            for u, v, key, data in self.graph.edges(keys=True, data=True)
            if any(segment.source_id == source_id for segment in edge_source_segments(data))
        ]

    def copy(self) -> AirportGraph:
        return AirportGraph(
            deepcopy(self.graph),
            self.projection,
            source_nodes=self.source_nodes,
            source_edges=self.source_edges,
            node_aliases=self.node_aliases,
            metadata=self.metadata,
        )
