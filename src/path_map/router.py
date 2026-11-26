"""Directed dual line-graph routing with local turn-angle constraints."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from math import acos, degrees, hypot

import networkx as nx
from shapely.geometry import LineString, Point

from airport_surface import NodeId

from .candidates import Candidate, CandidateIndex
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


@dataclass(frozen=True, slots=True)
class Transition:
    """从 前一个候选位置 移动到 后一个候选位置 的一次网络状态转移"""

    # distance 表示两个候选位置之间的实际沿网距离，单位是米。
    distance: float

    # edges 表示从 前一个候选位置 到 后一个候选位置所需要经过的有序边序列
    edges: tuple[DirectedEdge, ...]


@dataclass(frozen=True, slots=True)
class AnchoredSource:
    """Precomputed source geometry and single-source dual-graph distance table."""

    edge: EdgeId
    offset: float
    remaining: float
    distances: dict[EdgeId, float]


class DirectedNetworkRouter:
    """生产级有向对偶线图路由：封装全部有向状态展开、局部转角过滤与最短路计算。

    将无向多重图转换为以有向边为顶点的有向图，并在构图时按局部切线转角过滤非法连接
    """

    def __init__(
        self,
        index: CandidateIndex,
        *,
        max_turn_angle_deg: float = 130.0,
        tangent_sample_m: float = 2.0,
        same_edge_jitter_m: float = 5.0,
    ) -> None:
        self.max_turn_angle_deg = max_turn_angle_deg
        self.tangent_sample_m = tangent_sample_m
        self.same_edge_jitter_m = same_edge_jitter_m
        self.lengths: dict[EdgeId, float] = {}
        self._directed_edges: dict[EdgeId, DirectedEdge] = {}
        self._single_edge_tuples: dict[EdgeId, tuple[DirectedEdge, ...]] = {}
        # Node作为终点的所有有向边，即指向该节点的边；
        self.incoming: dict[NodeId, list[EdgeId]] = {}
        # Node作为起点的所有有向边，即从该节点发出的边；
        self.outgoing: dict[NodeId, list[EdgeId]] = {}
        self._endpoints: dict[EdgeId, tuple[Point, Point]] = {}
        self._start_tangents: dict[EdgeId, Tangent] = {}
        self._end_tangents: dict[EdgeId, Tangent] = {}
        stand_edges: set[EdgeId] = set()
        raw_edges = index.airport_graph.graph.edges

        for edge, line in zip(index.edge_ids, index.lines):
            u, v, key = edge
            length = line.length
            if u == v or length <= ZERO_DISTANCE_TOLERANCE_M:
                continue
            reverse: EdgeId = (v, u, key)
            if raw_edges[edge].get("aeroway") == "parking_position":
                stand_edges.add(edge)
                stand_edges.add(reverse)
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
        self._stand_edges = frozenset(stand_edges)

        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(self.lengths)
        for edge in self.lengths:
            directed = DirectedEdge(*edge)
            self._directed_edges[edge] = directed
            self._single_edge_tuples[edge] = (directed,)
            self.outgoing.setdefault(edge[0], []).append(edge)
            self.incoming.setdefault(edge[1], []).append(edge)
        for edge in self.lengths:
            # 枚举每条边 edge 终点 edge[1] 处的所有后续边 following，把转角合法的衔接连成对偶图的边
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

    def _boundary_candidate(self, edge: EdgeId, *, at_end: bool) -> Candidate:
        start_point, end_point = self._endpoints[edge]
        point = end_point if at_end else start_point
        offset = self.lengths[edge] if at_end else 0.0
        return Candidate(-1, edge, 0.0, point, offset, float(at_end))

    def stand_candidates(self, edges: Iterable[EdgeId], *, departure: bool) -> list[Candidate]:
        """Build directed stand boundary candidates for both travel directions of each edge."""
        return [
            self._boundary_candidate(edge, at_end=not departure)
            for u, v, key in edges
            for edge in ((u, v, key), (v, u, key))
        ]

    def runway_candidates(
        self, node: NodeId, taxiway_edges: Iterable[EdgeId], *, departure: bool
    ) -> list[Candidate]:
        """Build directed runway-interface candidates oriented into/out of ``node``."""
        result: list[Candidate] = []
        for u, v, key in taxiway_edges:
            other = v if u == node else u
            edge = (other, node, key) if departure else (node, other, key)
            result.append(self._boundary_candidate(edge, at_end=departure))
        return result

    def runway_edge_candidates(
        self, runway_edges: Iterable[EdgeId], *, departure: bool
    ) -> list[Candidate]:
        """Build directed boundary candidates on runway segments for runway-roll tracks."""
        return [
            self._boundary_candidate(edge, at_end=departure)
            for edge in runway_edges
            if edge in self.lengths
        ]

    def expand_candidates(self, candidates: Sequence[Candidate]) -> list[Candidate]:
        """Expand undirected observation candidates into directed HMM states."""
        directed: dict[tuple[EdgeId, float], Candidate] = {}
        for candidate in candidates:
            edge = candidate.edge_id
            length = self.lengths.get(edge)
            if length is None:
                continue
            u, v, key = edge
            offset = candidate.offset
            if min(offset, length - offset) <= ZERO_DISTANCE_TOLERANCE_M:
                node = u if offset <= ZERO_DISTANCE_TOLERANCE_M else v
                # At a junction the arrival edge, rather than the snapped
                # edge, determines which turns remain available.
                for incoming in self.incoming.get(node, ()):
                    end = self.lengths[incoming]
                    state = replace(candidate, edge_id=incoming, offset=end, fraction=1.0)
                    previous = directed.get((incoming, end))
                    if previous is None or state.distance < previous.distance:
                        directed[incoming, end] = state
            else:
                directed[edge, offset] = candidate
                reverse = (v, u, key)
                directed[reverse, length - offset] = replace(
                    candidate,
                    edge_id=reverse,
                    offset=length - offset,
                    fraction=1.0 - candidate.fraction,
                )
        return list(directed.values())

    @lru_cache(maxsize=4_096)
    def distances_from(self, source: EdgeId) -> dict[EdgeId, float]:
        """Return single-source dual-graph shortest distances from ``source``."""
        return dict(nx.single_source_dijkstra_path_length(self.graph, source, weight="length"))

    @lru_cache(maxsize=50_000)
    def _route(
        self, source: EdgeId, target: EdgeId
    ) -> tuple[float, tuple[DirectedEdge, ...], tuple[DirectedEdge, ...]] | None:
        try:
            route = nx.shortest_path(self.graph, source, target, weight="length")
        except nx.NetworkXNoPath:
            return None
        middle_distance = 0.0
        for index in range(1, len(route) - 1):
            middle_distance += self.lengths[route[index]]
        full_edges = tuple(self._directed_edges[edge] for edge in route)
        return middle_distance, full_edges, full_edges[1:]

    def _same_edge_distance(
        self, edge: EdgeId, start_offset: float, target_offset: float
    ) -> float | None:
        if target_offset < start_offset:
            if (
                edge not in self._stand_edges
                and start_offset - target_offset > self.same_edge_jitter_m
            ):
                return None
            return 0.0
        return target_offset - start_offset

    def anchor(
        self, source: Candidate, *, reversed_direction: bool = False
    ) -> AnchoredSource | None:
        """Prepare a source candidate for repeated distance queries against a target layer."""
        edge = source.edge_id
        length = self.lengths[edge]
        if reversed_direction:
            if source.offset <= ZERO_DISTANCE_TOLERANCE_M:
                return None
            u, v, key = edge
            edge = (v, u, key)
            offset = length - source.offset
        else:
            offset = source.offset
        return AnchoredSource(edge, offset, length - offset, self.distances_from(edge))

    def distance_from_anchor(
        self, anchor: AnchoredSource, target: Candidate
    ) -> float | None:
        """Return along-network distance from a prepared source anchor to ``target``."""
        target_edge = target.edge_id
        if anchor.edge == target_edge:
            return self._same_edge_distance(anchor.edge, anchor.offset, target.offset)
        raw = anchor.distances.get(target_edge)
        if raw is None:
            return None
        return anchor.remaining + raw - (self.lengths[target_edge] - target.offset)

    def _transition_from_edge(
        self, start: EdgeId, start_offset: float, target: Candidate
    ) -> Transition | None:
        end = target.edge_id
        if start == end:
            distance = self._same_edge_distance(start, start_offset, target.offset)
            if distance is None:
                return None
            return Transition(distance, self._single_edge_tuples[start] if distance else ())

        cached = self._route(start, end)
        if cached is None:
            return None
        middle_distance, full_edges, tail_edges = cached
        remaining = self.lengths[start] - start_offset
        distance = remaining + middle_distance + target.offset
        return Transition(distance, full_edges if remaining > 0 else tail_edges)

    def transition(self, source: Candidate, target: Candidate) -> Transition | None:
        return self._transition_from_edge(source.edge_id, source.offset, target)

    def reversed_transition(self, source: Candidate, target: Candidate) -> Transition | None:
        """Transition after reversing travel direction in place at ``source`` (pushback)."""
        if source.offset <= ZERO_DISTANCE_TOLERANCE_M:
            return None
        u, v, key = source.edge_id
        length = self.lengths[source.edge_id]
        return self._transition_from_edge((v, u, key), length - source.offset, target)
