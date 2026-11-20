"""Distance-based HMM scoring and Viterbi decoding."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite, isinf, log, pi
from typing import Hashable, Protocol, Sequence

import networkx as nx
from shapely.geometry import Point

from .candidates import Candidate, CandidateIndex
from .path import DirectedEdge, EdgeId
from .transition_constraints import (
    ANGLE_COMPARISON_TOLERANCE_DEG,
    LocalTurnConstraint,
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


class CandidateRouter(Protocol):
    def transition(self, source: Candidate, target: Candidate) -> Transition | None: ...


class DirectedNetworkRouter:
    """生产级有向对偶线图路由：在有向边节点构成的图上沿允许转角寻找最短路。

    被 `Matcher` 生产流水线直接使用。将无向多重图转换为以有向边为顶点的有向图，
    并在构图时直接应用 `LocalTurnConstraint` 过滤非法转角（>150°），杜绝掉头走法。
    """

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
                (
                    (source, *route)
                    for edge in self.graph.successors(source)
                    if (route := self._route(edge, target))
                ),
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
