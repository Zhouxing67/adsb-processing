"""Distance-based HMM scoring and Viterbi decoding."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import isinf, log, pi
from typing import Hashable, Sequence

import networkx as nx
from shapely.geometry import Point

from airport_surface import AirportGraph

from .candidates import Candidate, CandidateIndex
from .path import DirectedEdge

ZERO_DISTANCE_TOLERANCE_M = 1e-9


@dataclass(frozen=True, slots=True)
class Transition:
    """从 前一个候选位置 移动到 后一个候选位置 的一次网络状态转移"""

    # distance 表示两个候选位置之间的实际沿网距离，单位是米。
    distance: float

    # edges 表示从 前一个候选位置 到 后一个候选位置所需要经过的有序边序列
    edges: tuple[DirectedEdge, ...]


class NetworkRouter:
    """负责计算两个 Candidate 之间如何沿机场网络移动。"""

    def __init__(self, airport_graph: AirportGraph, index: CandidateIndex) -> None:
        self.ag = airport_graph
        self.index = index
        self.graph = airport_graph.graph
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

    def _middle(self, start: Hashable, end: Hashable) -> tuple[float, tuple[DirectedEdge, ...]]:
        nodes = nx.shortest_path(
            self.routing_graph,
            start,
            end,
            weight="length",
        )
        edges = tuple(self._best_parallel_edge(u, v) for u, v in pairwise(nodes))
        return sum(self.lengths[edge.from_, edge.to_, edge.key_] for edge in edges), edges

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
                choices.append(Transition(distance, tuple(edges)))
        return min(choices, key=lambda item: item.distance) if choices else None


def observation_log_score(distance: float, sigma: float) -> float:
    """Log probability density for one candidate's observation distance."""
    return -(distance**2) / (2 * sigma**2) - log(sigma * (2 * pi) ** 0.5)


def transition_log_score(network_distance: float, observed_distance: float, beta: float) -> float:
    """Distance-only transition score; reachability is represented separately."""
    return -abs(network_distance - observed_distance) / beta


def viterbi(
    layers: Sequence[Sequence[Candidate]],
    observations: Sequence[Point],
    router: NetworkRouter,
    sigma: float,
    beta: float,
) -> tuple[list[Candidate], list[Transition]]:
    """Decode candidates in log space using Gaussian emissions and distance transitions.

    - sigma:观测误差高斯模型的标准差，单位为米。
    - beta:网络转移距离误差的尺度参数，单位为米。
    """

    scores = [observation_log_score(candidate.distance, sigma) for candidate in layers[0]]
    backrefs: list[list[tuple[int, Transition] | None]] = []

    for step in range(1, len(layers)):
        observed_distance = observations[step - 1].distance(observations[step])
        next_scores: list[float] = []
        refs: list[tuple[int, Transition] | None] = []
        for target in layers[step]:
            emission = observation_log_score(target.distance, sigma)
            best: tuple[float, int, Transition] | None = None
            for source_index, source in enumerate(layers[step - 1]):
                if isinf(scores[source_index]) and scores[source_index] < 0:
                    continue
                transition = router.transition(source, target)
                if transition is None:
                    continue
                value = (
                    scores[source_index]
                    + transition_log_score(transition.distance, observed_distance, beta)
                    + emission
                )

                if best is None or value > best[0]:
                    best = value, source_index, transition
            if best is None:
                next_scores.append(float("-inf"))
                refs.append(None)
            else:
                next_scores.append(best[0])
                refs.append((best[1], best[2]))

        assert len(next_scores) == len(layers[step])
        assert len(refs) == len(layers[step])

        scores = next_scores
        backrefs.append(refs)
    if not scores or max(scores) == float("-inf"):
        raise nx.NetworkXNoPath("No reachable candidate sequence")
    current = max(range(len(scores)), key=scores.__getitem__)
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
