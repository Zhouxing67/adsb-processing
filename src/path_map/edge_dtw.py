"""Edge-anchored Dual-Graph DTW decoders built on top of generic Viterbi.

Organized into two independent decoders for clarity:
1. Arrival (``decode_arrival_route``): plain directed edges, no reversal.
2. Departure (``decode_departure_route``): product states allowing at most one
   in-place pushback reversal near the stand.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import inf, log, pi

import networkx as nx
from shapely.geometry import Point

from .candidates import Candidate
from .path import DirectedEdge, EdgeId
from .router import DirectedNetworkRouter
from .viterbi import viterbi

DEFAULT_LENGTH_SCALE_M = 50.0
REVERSAL_PENALTY_M = 40.0

type _ScoredSource = tuple[int, float, EdgeId, dict[EdgeId, float]]


# ---------------------------------------------------------------------------
# Shared scoring & layer construction helpers
# ---------------------------------------------------------------------------


def observation_log_score(distance: float, sigma: float) -> float:
    r"""Observation log probability density for 2D point-to-edge distance.

    $$
    \log P(d \mid \sigma) = -\frac{d^2}{2\sigma^2} - \log(\sigma\sqrt{2\pi})
    $$
    """
    return -(distance**2) / (2 * sigma**2) - log(sigma * (2 * pi) ** 0.5)


def directed_edge_distances(
    candidates: Sequence[Candidate],
    router: DirectedNetworkRouter,
) -> dict[EdgeId, float]:
    """Expand undirected edge candidates to both travel directions keeping min 2D distance."""
    distances: dict[EdgeId, float] = {}
    lengths = router.lengths
    for candidate in candidates:
        u, v, key = candidate.edge_id
        for edge in ((u, v, key), (v, u, key)):
            if edge not in lengths:
                continue
            previous = distances.get(edge)
            if previous is None or candidate.distance < previous:
                distances[edge] = candidate.distance
    return distances


def _build_emission_layers(
    observation_candidates: Sequence[Sequence[Candidate]],
    observations: Sequence[Point],
    router: DirectedNetworkRouter,
    sigma: float,
    *,
    start_edges: Iterable[EdgeId] | None = None,
    end_edges: Iterable[EdgeId] | None = None,
) -> tuple[list[dict[EdgeId, float]], list[Point]]:
    """Build per-layer ``{directed_edge: emission_log_score}`` maps and reference points."""
    if not observation_candidates:
        raise nx.NetworkXNoPath("No reachable candidate sequence")

    emission_layers: list[dict[EdgeId, float]] = []
    layer_points: list[Point] = []

    if start_edges is not None:
        valid_start = {edge: 0.0 for edge in start_edges if edge in router.lengths}
        if not valid_start:
            raise nx.NetworkXNoPath("No usable start boundary edges")
        emission_layers.append(valid_start)
        layer_points.append(observations[0])

    for point, candidates in zip(observations, observation_candidates):
        edge_dists = directed_edge_distances(candidates, router)
        if not edge_dists:
            raise nx.NetworkXNoPath("Observation layer has no usable directed edges")
        emission_layers.append(
            {edge: observation_log_score(dist, sigma) for edge, dist in edge_dists.items()}
        )
        layer_points.append(point)

    if end_edges is not None:
        valid_end = {edge: 0.0 for edge in end_edges if edge in router.lengths}
        if not valid_end:
            raise nx.NetworkXNoPath("No usable end boundary edges")
        emission_layers.append(valid_end)
        layer_points.append(observations[-1])

    return emission_layers, layer_points


def _best_predecessor(
    sources: Sequence[_ScoredSource],
    target_edge: EdgeId,
    inv_scale: float,
    *,
    penalty: float = 0.0,
    best_score: float = -inf,
    best_index: int = -1,
) -> tuple[float, int]:
    for index, score, source_edge, dists in sources:
        if source_edge == target_edge:
            distance = 0.0
        else:
            raw = dists.get(target_edge)
            if raw is None:
                continue
            distance = raw
        value = score - distance * inv_scale + penalty
        if value > best_score:
            best_score = value
            best_index = index
    return best_score, best_index


# ---------------------------------------------------------------------------
# 1. Arrival decoder (simple: directed edges only, zero reversals)
# ---------------------------------------------------------------------------

type _ArrivalLayerItem = tuple[EdgeId, float]


@dataclass(frozen=True, slots=True)
class ArrivalTransitionStep:
    """Length-regularized transition scorer for arrival trajectories (no reversal)."""

    router: DirectedNetworkRouter
    length_scale_m: float = DEFAULT_LENGTH_SCALE_M

    def best_predecessors(
        self,
        previous_layer: Sequence[_ArrivalLayerItem],
        previous_scores: Sequence[float],
        current_layer: Sequence[_ArrivalLayerItem],
    ) -> tuple[list[float], list[int]]:
        distances_from = self.router.distances_from
        sources: list[_ScoredSource] = [
            (index, score, edge, distances_from(edge))
            for index, ((edge, _), score) in enumerate(zip(previous_layer, previous_scores))
            if score > -inf
        ]
        inv_scale = 1.0 / self.length_scale_m
        best_scores: list[float] = []
        best_indices: list[int] = []
        for target_edge, _ in current_layer:
            score, index = _best_predecessor(sources, target_edge, inv_scale)
            best_scores.append(score)
            best_indices.append(index)
        return best_scores, best_indices


def decode_arrival_route(
    observation_candidates: Sequence[Sequence[Candidate]],
    observations: Sequence[Point],
    router: DirectedNetworkRouter,
    sigma: float,
    *,
    length_scale_m: float = DEFAULT_LENGTH_SCALE_M,
    start_edges: Iterable[EdgeId] | None = None,
    end_edges: Iterable[EdgeId] | None = None,
) -> list[DirectedEdge]:
    """Decode an arrival route using plain directed-edge Dual-Graph DTW (no reversal)."""
    emission_layers, _ = _build_emission_layers(
        observation_candidates,
        observations,
        router,
        sigma,
        start_edges=start_edges,
        end_edges=end_edges,
    )
    scored_layers: list[list[_ArrivalLayerItem]] = [
        list(emissions.items()) for emissions in emission_layers
    ]
    step = ArrivalTransitionStep(router=router, length_scale_m=length_scale_m)
    decoded = viterbi(scored_layers, lambda item: item[1], [step] * (len(scored_layers) - 1))

    edges = [edge for edge, _ in decoded]
    output: list[DirectedEdge] = [DirectedEdge(*edges[0])]
    for previous, current in zip(edges, edges[1:]):
        if previous == current:
            continue
        tail = router.route_tail(previous, current)
        assert tail is not None
        output.extend(tail)
    return output


# ---------------------------------------------------------------------------
# 2. Departure decoder (product state: at most one pushback reversal near stand)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DepartureState:
    """Product state pairing a directed edge with whether pushback reversal was used."""

    edge: EdgeId
    reversed_used: bool = False


type _DepartureLayerItem = tuple[DepartureState, float]


@dataclass(frozen=True, slots=True)
class DepartureTransitionStep:
    """Transition scorer allowing at most one in-place reversal (False -> True)."""

    router: DirectedNetworkRouter
    length_scale_m: float = DEFAULT_LENGTH_SCALE_M
    allow_reversal: bool = False
    reversal_penalty_m: float = REVERSAL_PENALTY_M

    def best_predecessors(
        self,
        previous_layer: Sequence[_DepartureLayerItem],
        previous_scores: Sequence[float],
        current_layer: Sequence[_DepartureLayerItem],
    ) -> tuple[list[float], list[int]]:
        distances_from = self.router.distances_from
        normal_p0: list[_ScoredSource] = []
        normal_p1: list[_ScoredSource] = []
        reversed_p0: list[_ScoredSource] = []
        for index, ((state, _), score) in enumerate(zip(previous_layer, previous_scores)):
            if score == -inf:
                continue
            edge = state.edge
            if state.reversed_used:
                normal_p1.append((index, score, edge, distances_from(edge)))
            else:
                normal_p0.append((index, score, edge, distances_from(edge)))
                if self.allow_reversal:
                    u, v, key = edge
                    rev_edge: EdgeId = (v, u, key)
                    if rev_edge in self.router.lengths:
                        reversed_p0.append((index, score, rev_edge, distances_from(rev_edge)))

        inv_scale = 1.0 / self.length_scale_m
        reversal_penalty = -self.reversal_penalty_m * inv_scale
        best_scores: list[float] = []
        best_indices: list[int] = []
        for target_state, _ in current_layer:
            if not target_state.reversed_used:
                score, index = _best_predecessor(normal_p0, target_state.edge, inv_scale)
            else:
                score, index = _best_predecessor(normal_p1, target_state.edge, inv_scale)
                if reversed_p0:
                    score, index = _best_predecessor(
                        reversed_p0,
                        target_state.edge,
                        inv_scale,
                        penalty=reversal_penalty,
                        best_score=score,
                        best_index=index,
                    )
            best_scores.append(score)
            best_indices.append(index)
        return best_scores, best_indices


def decode_departure_route(
    observation_candidates: Sequence[Sequence[Candidate]],
    observations: Sequence[Point],
    router: DirectedNetworkRouter,
    sigma: float,
    *,
    length_scale_m: float = DEFAULT_LENGTH_SCALE_M,
    max_pushback_radius_m: float | None = None,
    reversal_origin: Point | None = None,
    start_edges: Iterable[EdgeId] | None = None,
    end_edges: Iterable[EdgeId] | None = None,
) -> list[DirectedEdge]:
    """Decode a departure route allowing at most one in-place pushback reversal near stand."""
    emission_layers, layer_points = _build_emission_layers(
        observation_candidates,
        observations,
        router,
        sigma,
        start_edges=start_edges,
        end_edges=end_edges,
    )
    origin = reversal_origin if reversal_origin is not None else observations[0]

    scored_layers: list[list[_DepartureLayerItem]] = [
        [
            (DepartureState(edge, reversed_used=False), emit)
            for edge, emit in emission_layers[0].items()
        ]
    ]
    for emissions in emission_layers[1:]:
        scored_layers.append(
            [(DepartureState(edge, reversed_used=False), emit) for edge, emit in emissions.items()]
            + [(DepartureState(edge, reversed_used=True), emit) for edge, emit in emissions.items()]
        )

    step_scorers = [
        DepartureTransitionStep(
            router=router,
            length_scale_m=length_scale_m,
            allow_reversal=(
                max_pushback_radius_m is None
                or layer_points[step - 1].distance(origin) <= max_pushback_radius_m
            ),
        )
        for step in range(1, len(scored_layers))
    ]

    decoded = viterbi(scored_layers, lambda item: item[1], step_scorers)
    states = [state for state, _ in decoded]

    output: list[DirectedEdge] = [DirectedEdge(*states[0].edge)]
    for previous, current in zip(states, states[1:]):
        if (not previous.reversed_used) and current.reversed_used:
            u, v, key = previous.edge
            start_edge: EdgeId = (v, u, key)
            output.append(DirectedEdge(*start_edge))
        else:
            start_edge = previous.edge
        if start_edge == current.edge:
            continue
        tail = router.route_tail(start_edge, current.edge)
        assert tail is not None
        output.extend(tail)
    return output
