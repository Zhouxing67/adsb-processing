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

    def _transition_from_edge(
        self, start: EdgeId, start_offset: float, target: Candidate
    ) -> Transition | None:
        end = target.edge_id
        if start == end:
            if target.offset < start_offset:
                if (
                    start not in self._stand_edges
                    and start_offset - target.offset > self.same_edge_jitter_m
                ):
                    return None
                return Transition(0.0, ())
            distance = target.offset - start_offset
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


type Backref = tuple[int, int, bool]
type ActiveSource = tuple[int, EdgeId, float, float, float, dict[EdgeId, float]]


def _best_distance_predecessor(
    active_sources: Sequence[ActiveSource],
    target_edge: EdgeId,
    target_offset: float,
    target_adj: float,
    observed_distance: float,
    inv_beta: float,
    source_phase: int,
    is_reversed: bool,
    same_edge_jitter_m: float,
    stand_edges: frozenset[EdgeId],
    max_detour_m: float | None,
    penalty: float = 0.0,
) -> tuple[float, Backref] | None:
    best_score = -inf
    best_index = -1
    for index, src_edge, src_offset, remaining, score, dists in active_sources:
        if src_edge == target_edge:
            if target_offset < src_offset:
                if src_edge not in stand_edges and src_offset - target_offset > same_edge_jitter_m:
                    continue
                distance = 0.0
            else:
                distance = target_offset - src_offset
        else:
            raw = dists.get(target_edge)
            if raw is None:
                continue
            distance = remaining + raw - target_adj
        if max_detour_m is not None and distance - observed_distance > max_detour_m:
            continue
        value = score - abs(distance - observed_distance) * inv_beta + penalty
        if value > best_score:
            best_score = value
            best_index = index
    if best_index < 0:
        return None
    return best_score, (source_phase, best_index, is_reversed)


def _prepare_active_sources(
    previous_layer: Sequence[Candidate],
    previous_scores: Sequence[float],
    lengths: dict[EdgeId, float],
    distances_from: Callable[[EdgeId], dict[EdgeId, float]],
    *,
    reversed_mode: bool = False,
) -> list[ActiveSource]:
    active: list[ActiveSource] = []
    for index, (source, score) in enumerate(zip(previous_layer, previous_scores)):
        if score == -inf:
            continue
        edge = source.edge_id
        length = lengths[edge]
        if reversed_mode:
            if source.offset <= ZERO_DISTANCE_TOLERANCE_M:
                continue
            u, v, key = edge
            edge = (v, u, key)
            offset = length - source.offset
        else:
            offset = source.offset
        active.append((index, edge, offset, length - offset, score, distances_from(edge)))
    return active


def viterbi(
    layers: Sequence[Sequence[Candidate]],
    observations: Sequence[Point],
    router: CandidateRouter,
    sigma: float,
    beta: float,
    *,
    allow_single_reversal: bool = False,
    max_transition_detour_m: float | None = None,
    has_boundary_layers: bool = False,
) -> tuple[list[Candidate], list[Transition]]:
    """Decode candidates in log space using Gaussian emissions and distance transitions.

    When ``allow_single_reversal`` is enabled (departure pushback), the decoder tracks two
    phases: phase 0 (no reversal used yet) and phase 1 (one in-place reversal already used).
    """
    if not isinstance(router, DirectedNetworkRouter):
        return _viterbi_generic(
            layers,
            observations,
            router,
            sigma,
            beta,
            allow_single_reversal=allow_single_reversal,
            max_transition_detour_m=max_transition_detour_m,
            has_boundary_layers=has_boundary_layers,
        )

    inv_beta = 1.0 / beta
    inv_two_sigma_sq = 1.0 / (2.0 * sigma * sigma)
    log_norm = log(sigma * (2 * pi) ** 0.5)
    reversal_penalty = -REVERSAL_PENALTY_M * inv_beta
    lengths = router.lengths
    distances_from = router.distances_from
    jitter_m = router.same_edge_jitter_m
    stand_edges = router._stand_edges
    last_step = len(layers) - 1

    scores: list[list[float]] = [
        [-(c.distance * c.distance) * inv_two_sigma_sq - log_norm for c in layers[0]]
    ]
    if allow_single_reversal:
        scores.append([-inf] * len(layers[0]))
    backrefs: list[list[list[Backref | None]]] = []

    for step in range(1, len(layers)):
        observed_distance = observations[step - 1].distance(observations[step])
        step_detour = (
            None
            if has_boundary_layers and (step == 1 or step == last_step)
            else max_transition_detour_m
        )
        previous_layer = layers[step - 1]
        active_p0 = _prepare_active_sources(previous_layer, scores[0], lengths, distances_from)
        if allow_single_reversal:
            active_p1 = _prepare_active_sources(previous_layer, scores[1], lengths, distances_from)
            active_rev = _prepare_active_sources(
                previous_layer, scores[0], lengths, distances_from, reversed_mode=True
            )
        else:
            active_p1 = ()
            active_rev = ()

        next_scores: list[list[float]] = [[] for _ in scores]
        step_refs: list[list[Backref | None]] = [[] for _ in scores]

        for target in layers[step]:
            emission = -(target.distance * target.distance) * inv_two_sigma_sq - log_norm
            target_edge = target.edge_id
            target_offset = target.offset
            target_adj = lengths[target_edge] - target_offset

            best_p0 = _best_distance_predecessor(
                active_p0,
                target_edge,
                target_offset,
                target_adj,
                observed_distance,
                inv_beta,
                0,
                False,
                jitter_m,
                stand_edges,
                step_detour,
            )
            if best_p0 is None:
                next_scores[0].append(-inf)
                step_refs[0].append(None)
            else:
                next_scores[0].append(best_p0[0] + emission)
                step_refs[0].append(best_p0[1])

            if allow_single_reversal:
                stay = _best_distance_predecessor(
                    active_p1,
                    target_edge,
                    target_offset,
                    target_adj,
                    observed_distance,
                    inv_beta,
                    1,
                    False,
                    jitter_m,
                    stand_edges,
                    step_detour,
                )
                reverse_now = _best_distance_predecessor(
                    active_rev,
                    target_edge,
                    target_offset,
                    target_adj,
                    observed_distance,
                    inv_beta,
                    0,
                    True,
                    jitter_m,
                    stand_edges,
                    step_detour,
                    reversal_penalty,
                )
                if stay is None:
                    best_p1 = reverse_now
                elif reverse_now is None or stay[0] >= reverse_now[0]:
                    best_p1 = stay
                else:
                    best_p1 = reverse_now

                if best_p1 is None:
                    next_scores[1].append(-inf)
                    step_refs[1].append(None)
                else:
                    next_scores[1].append(best_p1[0] + emission)
                    step_refs[1].append(best_p1[1])

        scores = next_scores
        backrefs.append(step_refs)

    max_score = -inf
    phase = 0
    current = -1
    for phase_index, phase_scores in enumerate(scores):
        for index, score in enumerate(phase_scores):
            if score > max_score:
                max_score = score
                phase = phase_index
                current = index
    if max_score == -inf:
        raise nx.NetworkXNoPath("No reachable candidate sequence")

    # Backtrace states and lazily reconstruct Transitions only for the winning path.
    states = [layers[-1][current]]
    transitions: list[Transition] = []
    for step_refs, previous_layer in zip(reversed(backrefs), reversed(layers[:-1])):
        ref = step_refs[phase][current]
        assert ref is not None
        phase, current, is_reversed = ref
        prev_state = previous_layer[current]
        curr_state = states[-1]
        transition = (
            router.reversed_transition(prev_state, curr_state)
            if is_reversed
            else router.transition(prev_state, curr_state)
        )
        assert transition is not None
        transitions.append(transition)
        states.append(prev_state)
    return list(reversed(states)), list(reversed(transitions))


type GenericBackref = tuple[int, int, Transition]


def _best_predecessor(
    previous_layer: Sequence[Candidate],
    previous_scores: Sequence[float],
    target: Candidate,
    observed_distance: float,
    beta: float,
    transition_fn: Callable[[Candidate, Candidate], Transition | None],
    source_phase: int,
    penalty: float = 0.0,
    max_detour_m: float | None = None,
) -> tuple[float, GenericBackref] | None:
    best: tuple[float, GenericBackref] | None = None
    for index, (source, score) in enumerate(zip(previous_layer, previous_scores)):
        if score == -inf:
            continue
        transition = transition_fn(source, target)
        if transition is None:
            continue
        if max_detour_m is not None and transition.distance - observed_distance > max_detour_m:
            continue
        value = score + transition_log_score(transition.distance, observed_distance, beta) + penalty
        if best is None or value > best[0]:
            best = value, (source_phase, index, transition)
    return best


def _viterbi_generic(
    layers: Sequence[Sequence[Candidate]],
    observations: Sequence[Point],
    router: CandidateRouter,
    sigma: float,
    beta: float,
    *,
    allow_single_reversal: bool = False,
    max_transition_detour_m: float | None = None,
    has_boundary_layers: bool = False,
) -> tuple[list[Candidate], list[Transition]]:
    reversal_penalty = -REVERSAL_PENALTY_M / beta
    last_step = len(layers) - 1
    scores: list[list[float]] = [
        [observation_log_score(candidate.distance, sigma) for candidate in layers[0]]
    ]
    if allow_single_reversal:
        scores.append([-inf] * len(layers[0]))
    backrefs: list[list[list[GenericBackref | None]]] = []

    for step in range(1, len(layers)):
        observed_distance = observations[step - 1].distance(observations[step])
        step_detour = (
            None
            if has_boundary_layers and (step == 1 or step == last_step)
            else max_transition_detour_m
        )
        previous_layer = layers[step - 1]
        next_scores: list[list[float]] = [[] for _ in scores]
        step_refs: list[list[GenericBackref | None]] = [[] for _ in scores]

        for target in layers[step]:
            emission = observation_log_score(target.distance, sigma)
            choices: list[tuple[float, GenericBackref] | None] = [
                _best_predecessor(
                    previous_layer,
                    scores[0],
                    target,
                    observed_distance,
                    beta,
                    router.transition,
                    0,
                    max_detour_m=step_detour,
                )
            ]
            if allow_single_reversal:
                stay = _best_predecessor(
                    previous_layer,
                    scores[1],
                    target,
                    observed_distance,
                    beta,
                    router.transition,
                    1,
                    max_detour_m=step_detour,
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
                    max_detour_m=step_detour,
                )
                if stay is None:
                    choices.append(reverse_now)
                elif reverse_now is None or stay[0] >= reverse_now[0]:
                    choices.append(stay)
                else:
                    choices.append(reverse_now)

            for phase, best in enumerate(choices):
                if best is None:
                    next_scores[phase].append(-inf)
                    step_refs[phase].append(None)
                else:
                    next_scores[phase].append(best[0] + emission)
                    step_refs[phase].append(best[1])
        scores = next_scores
        backrefs.append(step_refs)

    max_score = -inf
    phase = 0
    current = -1
    for phase_index, phase_scores in enumerate(scores):
        for index, score in enumerate(phase_scores):
            if score > max_score:
                max_score = score
                phase = phase_index
                current = index
    if max_score == -inf:
        raise nx.NetworkXNoPath("No reachable candidate sequence")
    states = [layers[-1][current]]
    transitions: list[Transition] = []
    for step_refs, previous_layer in zip(reversed(backrefs), reversed(layers[:-1])):
        ref = step_refs[phase][current]
        assert ref is not None
        phase, current, transition = ref
        transitions.append(transition)
        states.append(previous_layer[current])
    return list(reversed(states)), list(reversed(transitions))
