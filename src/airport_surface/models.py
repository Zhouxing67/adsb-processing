"""Project-owned airport surface graph and immutable OSM source records."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Hashable, Mapping

import networkx as nx
from pyproj import Proj, Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform


def _immutable_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(deepcopy(dict(value or {})))


@dataclass(frozen=True, slots=True)
class SourceNode:
    """One canonical OSM node and any exactly colocated OSM aliases."""

    node_id: Hashable
    position: tuple[float, float]
    osm_node_ids: tuple[Hashable, ...]
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", tuple(self.position[:2]))
        object.__setattr__(self, "osm_node_ids", tuple(self.osm_node_ids))
        object.__setattr__(self, "attributes", _immutable_mapping(self.attributes))


@dataclass(frozen=True, slots=True)
class SourceEdge:
    """An immutable complete OSM way or explicitly created manual source."""

    source_id: str
    geometry: BaseGeometry
    source_type: str
    osm_way_id: Any = None
    osm_node_ids: tuple[Hashable, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "osm_node_ids", tuple(self.osm_node_ids))
        object.__setattr__(self, "attributes", _immutable_mapping(self.attributes))


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
    """Read new source chains and transparently normalize legacy single-source edges."""
    raw_segments = data.get("source_segments")
    if raw_segments is not None:
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
    if all(name in data for name in ("source_id", "source_start_m", "source_end_m")):
        return (
            SourceSegment(
                str(data["source_id"]),
                data["source_start_m"],
                data["source_end_m"],
            ),
        )
    return ()


@dataclass(frozen=True, slots=True)
class GraphMetadata:
    airport: str = "ZBAA"
    build_issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NodeMergeGroup:
    """One explicit decision that several graph nodes are one topology node."""

    canonical_node_id: Hashable
    member_node_ids: tuple[Hashable, ...]
    original_positions: Mapping[Hashable, tuple[float, float]]
    merge_type: str = "manual"

    def __post_init__(self) -> None:
        object.__setattr__(self, "member_node_ids", tuple(self.member_node_ids))
        object.__setattr__(
            self,
            "original_positions",
            MappingProxyType(
                {node: tuple(position[:2]) for node, position in self.original_positions.items()}
            ),
        )


@dataclass(frozen=True, slots=True)
class NodeSnapRecord:
    """One explicit manual decision to move a graph node onto a source edge."""

    node_id: Hashable
    original_position: tuple[float, float]
    snapped_position: tuple[float, float]
    target_source_id: str
    target_station_m: float
    distance_m: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "original_position", tuple(self.original_position[:2]))
        object.__setattr__(self, "snapped_position", tuple(self.snapped_position[:2]))
        object.__setattr__(self, "target_station_m", float(self.target_station_m))
        object.__setattr__(self, "distance_m", float(self.distance_m))


class AirportGraph:
    """Airport topology, projection helpers, and authoritative source registries."""

    wgs84 = Proj("EPSG:4326")

    def __init__(
        self,
        graph: nx.MultiGraph,
        projection: Any,
        *,
        source_nodes: Mapping[Hashable, SourceNode] | None = None,
        source_edges: Mapping[str, SourceEdge] | None = None,
        node_aliases: Mapping[Hashable, Hashable] | None = None,
        node_merge_groups: Mapping[Hashable, NodeMergeGroup] | None = None,
        node_snap_records: list[NodeSnapRecord] | tuple[NodeSnapRecord, ...] | None = None,
        parking_position_nodes: set[Hashable] | None = None,
        runway_access_nodes: set[Hashable] | None = None,
        metadata: GraphMetadata | None = None,
    ) -> None:
        self.graph = graph
        self.projection = projection
        self.project = Transformer.from_proj(self.wgs84, projection, always_xy=True)
        self.to_wgs84 = Transformer.from_proj(projection, self.wgs84, always_xy=True)
        self.source_nodes = dict(source_nodes or {})
        self.source_edges = dict(source_edges or {})
        self.node_aliases = dict(node_aliases or {})
        self.node_merge_groups = dict(node_merge_groups or {})
        self.node_snap_records = list(node_snap_records or ())
        self.parking_position_nodes = set(parking_position_nodes or ())
        self.runway_access_nodes = set(runway_access_nodes or ())
        self.metadata = metadata or GraphMetadata()
        missing_business_nodes = (
            self.parking_position_nodes | self.runway_access_nodes
        ).difference(self.graph.nodes)
        if missing_business_nodes:
            raise ValueError(
                "Business node annotations reference unknown graph nodes: "
                f"{sorted(missing_business_nodes, key=repr)!r}"
            )
        for _, _, data in self.graph.edges(data=True):
            segments = edge_source_segments(data)
            if segments:
                data["source_segments"] = segments

    @property
    def components(self) -> list[int]:
        return [len(component) for component in nx.connected_components(self.graph)]

    def project_shape(self, geometry: BaseGeometry) -> BaseGeometry:
        return transform(self.project.transform, geometry)

    def to_wgs84_shape(self, geometry: BaseGeometry) -> BaseGeometry:
        return transform(self.to_wgs84.transform, geometry)

    def length(self, geometry: BaseGeometry) -> float:
        return self.project_shape(geometry).length

    def canonical_node_id(self, node_id: Hashable) -> Hashable:
        return self.node_aliases.get(node_id, node_id)

    def get_source_node(self, node_id: Hashable) -> SourceNode:
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
            node_merge_groups=self.node_merge_groups,
            node_snap_records=self.node_snap_records,
            parking_position_nodes=self.parking_position_nodes,
            runway_access_nodes=self.runway_access_nodes,
            metadata=self.metadata,
        )
