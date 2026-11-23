"""Distance-based HMM scoring and Viterbi decoding."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from math import acos, degrees, hypot, inf, log, pi
from typing import Protocol

import networkx as nx
from shapely.geometry import LineString, Point

from airport_surface import NodeId

from .candidates import Candidate, CandidateIndex
from .path import DirectedEdge, EdgeId

ZERO_DISTANCE_TOLERANCE_M = 1e-9
ANGLE_COMPARISON_TOLERANCE_DEG = 1e-9
REVERSAL_PENALTY_M = 40.0
logger = logging.getLogger(__name__)

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


class CandidateRouter(Protocol):
    def transition(self, source: Candidate, target: Candidate) -> Transition | None: ...
    def reversed_transition(self, source: Candidate, target: Candidate) -> Transition | None: ...


class DirectedNetworkRouter:
    """生产级有向对偶线图路由：封装全部有向状态展开、局部转角过滤与最短路计算。

    将无向多重图转换为以有向边为顶点的有向图，并在构图时按局部切线转角过滤非法连接
    （默认 >150°），杜绝掉头走法。所有与边方向相关的细节均收敛在本类内部。
    """

    def __init__(
        self,
        index: CandidateIndex,
        *,
        max_turn_angle_deg: float = 150.0,
        tangent_sample_m: float = 10.0,
    ) -> None:
        self.max_turn_angle_deg = max_turn_angle_deg
        self.tangent_sample_m = tangent_sample_m
        self.lengths: dict[EdgeId, float] = {}
        # Node作为终点的所有有向边，即指向该节点的边；
        self.incoming: dict[NodeId, list[EdgeId]] = {}
        # Node作为起点的所有有向边，即从该节点发出的边；
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

    @lru_cache(maxsize=100_000)
    def _route(self, source: EdgeId, target: EdgeId) -> tuple[EdgeId, ...]:
        try:
            return tuple(nx.shortest_path(self.graph, source, target, weight="length"))
        except nx.NetworkXNoPath:
            return ()

    def transition(self, source: Candidate, target: Candidate) -> Transition | None:
        start, end = source.edge_id, target.edge_id
        if start == end:
            if target.offset < source.offset:
                return None
            distance = target.offset - source.offset
            return Transition(distance, (DirectedEdge(*start),) if distance else ())

        route = self._route(start, end)
        if not route:
            return None
        remaining = self.lengths[start] - source.offset
        distance = remaining + sum(self.lengths[edge] for edge in route[1:-1]) + target.offset
        traversed = route if remaining > 0 else route[1:]
        return Transition(distance, tuple(DirectedEdge(*edge) for edge in traversed))

    def reversed_transition(self, source: Candidate, target: Candidate) -> Transition | None:
        """Transition after reversing travel direction in place at ``source`` (pushback)."""
        if source.offset <= ZERO_DISTANCE_TOLERANCE_M:
            return None
        u, v, key = source.edge_id
        length = self.lengths[source.edge_id]
        flipped = replace(
            source,
            edge_id=(v, u, key),
            offset=length - source.offset,
            fraction=1.0 - source.fraction,
        )
        return self.transition(flipped, target)


def observation_log_score(distance: float, sigma: float) -> float:
    r"""
    Observation log probability density.
    $$
    \log P(d \mid \sigma) = -\frac{d^2}{2\sigma^2} - \log(\sigma\sqrt{2\pi})
    $$
    """
    return -(distance**2) / (2 * sigma**2) - log(sigma * (2 * pi) ** 0.5)


def transition_log_score(
    network_distance: float,
    observed_distance: float,
    beta: float,
) -> float:
    r"""
    Distance-based transition log score.
    $$
    \log S_t = -\frac{|d_{\mathrm{network}}-d_{\mathrm{observed}}|}{\beta}
    $$
    """
    return -abs(network_distance - observed_distance) / beta


type Backref = tuple[int, int, Transition]


def _best_predecessor(
    previous_layer: Sequence[Candidate],
    previous_scores: Sequence[float],
    target: Candidate,
    observed_distance: float,
    beta: float,
    transition_fn: Callable[[Candidate, Candidate], Transition | None],
    source_phase: int,
    penalty: float = 0.0,
) -> tuple[float, Backref] | None:
    best: tuple[float, Backref] | None = None
    for index, (source, score) in enumerate(zip(previous_layer, previous_scores)):
        if score == -inf:
            continue
        transition = transition_fn(source, target)
        if transition is None:
            continue
        value = score + transition_log_score(transition.distance, observed_distance, beta) + penalty
        if best is None or value > best[0]:
            best = value, (source_phase, index, transition)
    return best


def viterbi(
    layers: Sequence[Sequence[Candidate]],
    observations: Sequence[Point],
    router: CandidateRouter,
    sigma: float,
    beta: float,
    *,
    allow_single_reversal: bool = False,
) -> tuple[list[Candidate], list[Transition]]:
    """Decode candidates in log space using Gaussian emissions and distance transitions.

    When ``allow_single_reversal`` is enabled (departure pushback), the decoder tracks two
    phases: phase 0 (no reversal used yet) and phase 1 (one in-place reversal already used).
    """
    reversal_penalty = -REVERSAL_PENALTY_M / beta
    scores: list[list[float]] = [
        [observation_log_score(candidate.distance, sigma) for candidate in layers[0]]
    ]
    if allow_single_reversal:
        scores.append([-inf] * len(layers[0]))
    backrefs: list[list[list[Backref | None]]] = []

    for step in range(1, len(layers)):
        observed_distance = observations[step - 1].distance(observations[step])
        previous_layer = layers[step - 1]
        next_scores: list[list[float]] = [[] for _ in scores]
        step_refs: list[list[Backref | None]] = [[] for _ in scores]

        for target in layers[step]:
            emission = observation_log_score(target.distance, sigma)
            # Phase 0: normal forward transitions without any reversal.
            choices: list[tuple[float, Backref] | None] = [
                _best_predecessor(
                    previous_layer, scores[0], target, observed_distance, beta, router.transition, 0
                )
            ]
            # Phase 1: either continue after an earlier reversal, or reverse now from phase 0.
            if allow_single_reversal:
                stay = _best_predecessor(
                    previous_layer, scores[1], target, observed_distance, beta, router.transition, 1
                )
                reverse_now = _best_predecessor(
                    previous_layer,
                    scores[0],
                    target,
                    observed_distance,
                    beta,
                    router.reversed_transition,
                    0,
                    reversal_penalty,
                )
                choices.append(
                    max(
                        (item for item in (stay, reverse_now) if item is not None),
                        key=lambda item: item[0],
                        default=None,
                    )
                )

            for phase, best in enumerate(choices):
                if best is None:
                    next_scores[phase].append(-inf)
                    step_refs[phase].append(None)
                else:
                    next_scores[phase].append(best[0] + emission)
                    step_refs[phase].append(best[1])
        scores = next_scores
        backrefs.append(step_refs)

    max_score, phase, current = max(
        (
            (score, phase, index)
            for phase, phase_scores in enumerate(scores)
            for index, score in enumerate(phase_scores)
        ),
        key=lambda item: item[0],
        default=(-inf, 0, -1),
    )
    if max_score == -inf:
        raise nx.NetworkXNoPath("No reachable candidate sequence")
    # back_trace
    states = [layers[-1][current]]
    transitions: list[Transition] = []
    for step_refs, previous_layer in zip(reversed(backrefs), reversed(layers[:-1])):
        ref = step_refs[phase][current]
        assert ref is not None
        phase, current, transition = ref
        transitions.append(transition)
        states.append(previous_layer[current])
    return list(reversed(states)), list(reversed(transitions))
