"""Directed dual line-graph routing with local turn-angle constraints."""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from math import acos, degrees, hypot

import networkx as nx
from shapely.geometry import LineString, Point

from airport_surface import NodeId

from .candidates import CandidateIndex
from .path import DirectedEdge, EdgeId

ZERO_DISTANCE_TOLERANCE_M = 1e-9
ANGLE_COMPARISON_TOLERANCE_DEG = 1e-9

type Tangent = tuple[float, float]


def _edge_tangents(line: LineString, sample_m: float) -> tuple[Tangent, Tangent]:
    """Return ``(start_tangent, end_tangent)`` along the coordinate order of ``line``."""
    distance = min(sample_m, line.length)
    start = Point(line.coords[0])
    end = Point(line.coords[-1])
    start_sample = line.interpolate(distance)
    end_sample = line.interpolate(line.length - distance)
    start_tangent = (start_sample.x - start.x, start_sample.y - start.y)
    end_tangent = (end.x - end_sample.x, end.y - end_sample.y)
    return start_tangent, end_tangent


class DirectedNetworkRouter:
    """有向对偶线图路由：封装有向边顶点化、局部切线转角剪枝与带缓存的最短路计算。"""

    def __init__(
        self,
        index: CandidateIndex,
        *,
        max_turn_angle_deg: float = 130.0,
        tangent_sample_m: float = 2.0,
    ) -> None:
        self.max_turn_angle_deg = max_turn_angle_deg
        self.tangent_sample_m = tangent_sample_m
        self.lengths: dict[EdgeId, float] = {}
        self._directed_edges: dict[EdgeId, DirectedEdge] = {}
        self.outgoing: dict[NodeId, list[EdgeId]] = {}
        self._endpoints: dict[EdgeId, tuple[Point, Point]] = {}
        self._start_tangents: dict[EdgeId, Tangent] = {}
        self._end_tangents: dict[EdgeId, Tangent] = {}

        for edge, line in zip(index.edge_ids, index.lines):
            u, v, key = edge
            length = line.length
            if u == v or length <= ZERO_DISTANCE_TOLERANCE_M:
                continue
            reverse: EdgeId = (v, u, key)
            start_point = Point(line.coords[0])
            end_point = Point(line.coords[-1])
            self.lengths[edge] = length
            self.lengths[reverse] = length
            self._endpoints[edge] = (start_point, end_point)
            self._endpoints[reverse] = (end_point, start_point)

            start_vec, end_vec = _edge_tangents(line, tangent_sample_m)
            self._start_tangents[edge] = start_vec
            self._end_tangents[edge] = end_vec
            self._start_tangents[reverse] = (-end_vec[0], -end_vec[1])
            self._end_tangents[reverse] = (-start_vec[0], -start_vec[1])

        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(self.lengths)
        for edge in self.lengths:
            self._directed_edges[edge] = DirectedEdge(*edge)
            self.outgoing.setdefault(edge[0], []).append(edge)
        for edge in self.lengths:
            end = edge[1]
            for following in self.outgoing.get(end, ()):
                angle = self.turn_angle(edge, following)
                if angle <= self.max_turn_angle_deg + ANGLE_COMPARISON_TOLERANCE_DEG:
                    self.graph.add_edge(
                        edge, following, length=self.lengths[following], angle=angle
                    )
        nx.freeze(self.graph)

    def turn_angle(self, incoming_edge: EdgeId, outgoing_edge: EdgeId) -> float:
        """Return the local turn angle in degrees between two connected directed edges."""
        incoming = self._end_tangents[incoming_edge]
        outgoing = self._start_tangents[outgoing_edge]
        cosine = (incoming[0] * outgoing[0] + incoming[1] * outgoing[1]) / (
            hypot(*incoming) * hypot(*outgoing)
        )
        return degrees(acos(max(-1.0, min(1.0, cosine))))

    def directed_stand_edges(self, edges: Iterable[EdgeId]) -> frozenset[EdgeId]:
        """Expand undirected stand edges into both valid travel directions."""
        return frozenset(
            directed
            for u, v, key in edges
            for directed in ((u, v, key), (v, u, key))
            if directed in self.lengths
        )

    def edge_centroid(self, edges: Iterable[EdgeId]) -> Point:
        """Return the mean endpoint coordinate of the given directed edges."""
        points = [self._endpoints[edge][0] for edge in edges if edge in self._endpoints]
        return Point(
            sum(point.x for point in points) / len(points),
            sum(point.y for point in points) / len(points),
        )

    def directed_runway_interface_edges(
        self, node: NodeId, taxiway_edges: Iterable[EdgeId], *, departure: bool
    ) -> list[EdgeId]:
        """Orient runway-interface taxiway edges into/out of ``node``."""
        result: list[EdgeId] = []
        for u, v, key in taxiway_edges:
            other = v if u == node else u
            edge: EdgeId = (other, node, key) if departure else (node, other, key)
            if edge in self.lengths:
                result.append(edge)
        return result

    @lru_cache(maxsize=4_096)
    def distances_from(self, source: EdgeId) -> dict[EdgeId, float]:
        """Return single-source dual-graph shortest distances from ``source``."""
        return dict(nx.single_source_dijkstra_path_length(self.graph, source, weight="length"))

    @lru_cache(maxsize=50_000)
    def route_tail(self, source: EdgeId, target: EdgeId) -> tuple[DirectedEdge, ...] | None:
        """Return shortest dual-graph path edges from ``source`` to ``target``, excluding source."""
        try:
            route = nx.shortest_path(self.graph, source, target, weight="length")
        except nx.NetworkXNoPath:
            return None
        return tuple(self._directed_edges[edge] for edge in route[1:])
