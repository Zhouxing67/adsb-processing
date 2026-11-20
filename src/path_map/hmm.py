"""Distance-based HMM scoring and Viterbi decoding."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from math import isfinite, isinf, log, pi
from typing import Hashable, Protocol, Sequence

import networkx as nx
from shapely.geometry import Point

from airport_surface import AirportGraph

from .candidates import Candidate, CandidateIndex
from .path import DirectedEdge, EdgeId
from .transition_constraints import (
    ANGLE_COMPARISON_TOLERANCE_DEG,
    LocalTurnConstraint,
    TransitionConstraint,
)

ZERO_DISTANCE_TOLERANCE_M = 1e-9
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Transition:
    """从 前一个候选位置 移动到 后一个候选位置 的一次网络状态转移"""

    # distance 表示两个候选位置之间的实际沿网距离，单位是米。
    distance: float

    # edges 表示从 前一个候选位置 到 后一个候选位置所需要经过的有序边序列
    edges: tuple[DirectedEdge, ...]


class NetworkRouter:
    """负责计算两个 Candidate 之间如何沿机场网络移动。"""

    def __init__(
        self,
        airport_graph: AirportGraph,
        index: CandidateIndex,
        *,
        constraints: Sequence[TransitionConstraint] = (),
    ) -> None:
        self.graph = airport_graph.graph
        self.constraints = tuple(constraints)
        self.lengths = {edge: line.length for edge, line in zip(index.edge_ids, index.lines)}
        self.routing_graph = nx.Graph()
        self.routing_graph.add_nodes_from(self.graph.nodes)
        for u, v, key in self.graph.edges(keys=True):
            edge = (u, v, key)
            reverse = (v, u, key)
            length = self.lengths.get(edge, self.lengths.get(reverse))
            if length is None:
                length = airport_graph.length(self.graph.edges[u, v, key]["geometry"])
            self.lengths[edge] = self.lengths[reverse] = length

            selected = self.routing_graph.get_edge_data(u, v)
            if selected is None or length < selected["length"]:
                self.routing_graph.add_edge(u, v, length=length, key=key)

        # Routing never changes the airport topology. Freezing the private
        # view makes accidental mutations fail immediately during development.
        nx.freeze(self.routing_graph)

    def _best_parallel_edge(self, u: Hashable, v: Hashable) -> DirectedEdge:
        data = self.routing_graph.edges[u, v]
        return DirectedEdge(u, v, data["key"])

    @lru_cache(maxsize=100_000)
    def _middle(self, start: Hashable, end: Hashable) -> tuple[float, tuple[DirectedEdge, ...]]:
        """Return a fixed-graph shortest path, cached by endpoint pair."""
        nodes = nx.shortest_path(
            self.routing_graph,
            start,
            end,
            weight="length",
        )
        edges = tuple(self._best_parallel_edge(u, v) for u, v in pairwise(nodes))
        distance = sum(self.lengths[edge.from_, edge.to_, edge.key_] for edge in edges)
        return distance, edges

    def transition(self, source: Candidate, target: Candidate) -> Transition | None:
        su, sv, sk = source.edge_id
        tu, tv, tk = target.edge_id
        slen = self.lengths[su, sv, sk]
        tlen = self.lengths[tu, tv, tk]
        choices: list[Transition] = []
        if (su, sv, sk) == (tu, tv, tk):
            offset_delta = target.offset - source.offset
            if abs(offset_delta) <= ZERO_DISTANCE_TOLERANCE_M:
                choices.append(Transition(0.0, ()))
            elif offset_delta > 0:
                direct_edge = DirectedEdge(su, sv, sk)
                choices.append(Transition(offset_delta, (direct_edge,)))
            else:
                direct_edge = DirectedEdge(sv, su, sk)
                choices.append(Transition(-offset_delta, (direct_edge,)))

        source_exits = (
            (su, source.offset, DirectedEdge(sv, su, sk)),
            (sv, slen - source.offset, DirectedEdge(su, sv, sk)),
        )
        target_entries = (
            (tu, target.offset, DirectedEdge(tu, tv, tk)),
            (tv, tlen - target.offset, DirectedEdge(tv, tu, tk)),
        )
        for exit_node, source_cost, source_edge in source_exits:
            for entry_node, target_cost, target_edge in target_entries:
                try:
                    middle_cost, middle_edges = self._middle(exit_node, entry_node)
                except nx.NetworkXNoPath:
                    continue
                edges: list[DirectedEdge] = []
                if source_cost > ZERO_DISTANCE_TOLERANCE_M:
                    edges.append(source_edge)
                edges.extend(middle_edges)
                if target_cost > ZERO_DISTANCE_TOLERANCE_M:
                    edges.append(target_edge)
                distance = source_cost + middle_cost + target_cost
                if distance <= ZERO_DISTANCE_TOLERANCE_M:
                    distance = 0.0
                if not all(constraint.accepts(edges) for constraint in self.constraints):
                    logger.debug(
                        "Rejected transition choice: source_candidate=%r "
                        "target_candidate=%r edges=%r",
                        source,
                        target,
                        tuple(edges),
                    )
                    continue
                choices.append(Transition(distance, tuple(edges)))
        return min(choices, key=lambda item: item.distance) if choices else None


class CandidateRouter(Protocol):
    def transition(self, source: Candidate, target: Candidate) -> Transition | None: ...


class DirectedNetworkRouter:
    """Route between directed positions using only allowed edge-to-edge turns."""

    def __init__(self, index: CandidateIndex, turns: LocalTurnConstraint) -> None:
        self.lengths = {
            edge: line.length
            for edge, line in index.directed_lines.items()
            if edge[0] != edge[1] and line.length > ZERO_DISTANCE_TOLERANCE_M
        }
        self.incoming: dict[Hashable, list[EdgeId]] = {}
        self.outgoing: dict[Hashable, list[EdgeId]] = {}
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(self.lengths)
        for edge in self.lengths:
            self.outgoing.setdefault(edge[0], []).append(edge)
            self.incoming.setdefault(edge[1], []).append(edge)
        for edge in self.lengths:
            for following in self.outgoing.get(edge[1], ()):
                angle = turns.turn_angle(DirectedEdge(*edge), DirectedEdge(*following))
                if (
                    angle is not None
                    and isfinite(angle)
                    and angle <= turns.max_angle_deg + ANGLE_COMPARISON_TOLERANCE_DEG
                ):
                    self.graph.add_edge(edge, following, length=self.lengths[following])
        nx.freeze(self.graph)

    @lru_cache(maxsize=100_000)
    def _route(self, source: EdgeId, target: EdgeId) -> tuple[EdgeId, ...]:
        try:
            if source != target:
                return tuple(nx.shortest_path(self.graph, source, target, weight="length"))
            # Returning to an earlier position on the same directed edge requires a cycle.
            return min(
                ((source, *route) for edge in self.graph.successors(source)
                 if (route := self._route(edge, target))),
                key=lambda route: sum(self.lengths[edge] for edge in route[1:]),
                default=(),
            )
        except nx.NetworkXNoPath:
            return ()

    def transition(self, source: Candidate, target: Candidate) -> Transition | None:
        start, end = source.edge_id, target.edge_id
        if start == end and target.offset >= source.offset:
            distance = target.offset - source.offset
            return Transition(distance, (DirectedEdge(*start),) if distance else ())

        route = self._route(start, end)
        if not route:
            return None
        remaining = self.lengths[start] - source.offset
        distance = remaining + sum(self.lengths[edge] for edge in route[1:-1]) + target.offset
        traversed = route if remaining > 0 else route[1:]
        return Transition(distance, tuple(DirectedEdge(*edge) for edge in traversed))


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


def viterbi(
    layers: Sequence[Sequence[Candidate]],
    observations: Sequence[Point],
    router: CandidateRouter,
    sigma: float,
    beta: float,
) -> tuple[list[Candidate], list[Transition]]:
    """Decode candidates in log space using Gaussian emissions and distance transitions.

    - sigma:观测误差高斯模型的标准差，单位为米。
    - beta:网络转移距离误差的尺度参数，单位为米。
    """

    candidate_scores = [observation_log_score(candidate.distance, sigma) for candidate in layers[0]]
    backrefs: list[list[tuple[int, Transition] | None]] = []

    for step in range(1, len(layers)):
        observed_distance = observations[step - 1].distance(observations[step])
        next_scores: list[float] = []
        refs: list[tuple[int, Transition] | None] = []
        for target in layers[step]:
            emission = observation_log_score(target.distance, sigma)
            best_transition_plan: tuple[float, int, Transition] | None = None
            for source_index, source in enumerate(layers[step - 1]):
                if isinf(candidate_scores[source_index]) and candidate_scores[source_index] < 0:
                    continue
                transition = router.transition(source, target)
                if transition is None:
                    continue
                value = (
                    candidate_scores[source_index]
                    + transition_log_score(transition.distance, observed_distance, beta)
                    + emission
                )

                if best_transition_plan is None or value > best_transition_plan[0]:
                    best_transition_plan = value, source_index, transition
            if best_transition_plan is None:
                next_scores.append(float("-inf"))
                refs.append(None)
            else:
                next_scores.append(best_transition_plan[0])
                refs.append((best_transition_plan[1], best_transition_plan[2]))
        candidate_scores = next_scores
        backrefs.append(refs)
    if not candidate_scores or max(candidate_scores) == float("-inf"):
        raise nx.NetworkXNoPath("No reachable candidate sequence")
    # back_trace
    current, _ = max(enumerate(candidate_scores), key=lambda item: item[1])
    states = [layers[-1][current]]
    transitions: list[Transition] = []
    for refs, previous_layer in zip(reversed(backrefs), reversed(layers[:-1])):
        ref = refs[current]
        if ref is None:
            raise nx.NetworkXNoPath("Broken Viterbi backtrace")
        current, transition = ref
        transitions.append(transition)
        states.append(previous_layer[current])
    return list(reversed(states)), list(reversed(transitions))
