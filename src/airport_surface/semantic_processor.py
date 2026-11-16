from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Hashable

from shapely.geometry import LineString, Point

from .models import AirportGraph, edge_source_segments

# MultiGraph 边必须由 (u, v, key) 标识，避免丢失平行边身份。
EdgeId = tuple[Hashable, Hashable, Hashable]


@dataclass(frozen=True)
class StandEntity:
    entity_id: str
    geometry: Point | LineString
    node_ids: tuple[Hashable, ...] = ()
    edge_ids: tuple[EdgeId, ...] = ()


@dataclass(frozen=True)
class StandGroup:
    stand_group_id: str
    entities: tuple[StandEntity, ...] = ()
    internal_edges: tuple[EdgeId, ...] = ()
    portal_nodes: tuple[Hashable, ...] = ()


def identify_runway_interfaces(airport_graph: AirportGraph) -> set[Hashable]:
    result = set()
    for node in airport_graph.graph:
        types = set()
        for u, v, data in airport_graph.graph.edges(node, data=True):
            segments = edge_source_segments(data)
            value = data.get("aeroway")
            if segments:
                segment = segments[0] if node == data.get("first", u) else segments[-1]
                source = airport_graph.source_edges.get(segment.source_id)
                if source is not None:
                    value = source.attributes.get("aeroway", value)
            types.add(value)
        if {"runway", "taxiway"} <= types:
            result.add(node)
    return result


def extract_stand_entities(airport_graph: AirportGraph) -> tuple[StandEntity, ...]:
    # TODO: Phase 2 — extract complete entities with their current topology anchors.
    return ()


def cluster_stand_entities(
    airport_graph: AirportGraph, entities: tuple[StandEntity, ...], *, cluster_eps_m: float
) -> tuple[StandGroup, ...]:
    # TODO: Phase 2 — spatial clustering with deterministic group identifiers.
    return ()


def extract_group_subgraphs(
    airport_graph: AirportGraph, stand_groups: tuple[StandGroup, ...]
) -> tuple[StandGroup, ...]:
    # TODO: Phase 2 — shortest-path/Steiner approximation and boundary extraction.
    return stand_groups


def enrich_airport_semantics(
    airport_graph: AirportGraph, *, cluster_eps_m: float = 70.0
) -> AirportGraph:
    if not isfinite(cluster_eps_m) or cluster_eps_m <= 0:
        raise ValueError("cluster_eps_m must be finite and positive")
    result = airport_graph.copy()
    interfaces = identify_runway_interfaces(result)
    for node, data in result.graph.nodes(data=True):
        if not data.get("is_manual_lock"):
            data.update(
                node_type="runway_interface" if node in interfaces else "unclassified",
                stand_group_id=None,
            )
    for *_, data in result.graph.edges(data=True):
        if not data.get("is_manual_lock"):
            data.update(edge_zone="backbone", stand_group_id=None)
    groups = cluster_stand_entities(
        result, extract_stand_entities(result), cluster_eps_m=cluster_eps_m
    )
    extract_group_subgraphs(result, groups)
    return result


class SemanticPostProcessor:
    """保存配置的对象式适配器，便于流水线重复调用；不持有待处理图。"""

    def __init__(self, *, cluster_eps_m: float = 70.0) -> None:
        """保存米制聚类阈值；合法性在 process 调用统一入口时校验。"""
        self.cluster_eps_m = cluster_eps_m

    def process(self, airport_graph: AirportGraph) -> AirportGraph:
        """使用实例配置返回增强副本，契约与 enrich_airport_semantics 相同。"""
        return enrich_airport_semantics(airport_graph, cluster_eps_m=self.cluster_eps_m)
