"""Edge-anchored Dual-Graph DTW decoder built on top of generic Viterbi."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import inf

import networkx as nx
from shapely.geometry import Point

from .candidates import Candidate
from .hmm import REVERSAL_PENALTY_M, observation_log_score
from .path import DirectedEdge, EdgeId
from .router import DirectedNetworkRouter
from .viterbi import viterbi

DEFAULT_LENGTH_SCALE_M = 50.0


@dataclass(frozen=True, slots=True)
class EdgeState:
    """HMM / DTW state anchored to a directed dual-graph vertex and pushback phase."""

    edge: EdgeId
    reversed_used: bool = False


type _ScoredEdge = tuple[int, float, EdgeId, dict[EdgeId, float]]


@dataclass(frozen=True, slots=True)
class EdgeTransitionStep:
    """Length-regularized dual-graph transition policy between two ``EdgeState`` layers.

    - Staying on the same directed edge (``e -> e``) has zero transition cost,
      absorbing stationary and longitudinal jitter natively without heuristics.
    - Advancing to another edge pays ``-dual_distance(e, e') / length_scale_m``.
    - A single in-place reversal (``(e, False) -> (e', True)``) pays
      ``-(reversal_penalty_m + dual_distance(rev(e), e')) / length_scale_m``.
    """

    router: DirectedNetworkRouter
    length_scale_m: float = DEFAULT_LENGTH_SCALE_M
    allow_reversal: bool = False
    reversal_penalty_m: float = REVERSAL_PENALTY_M

    def _prepare(
        self,
        previous_layer: Sequence[EdgeState],
        previous_scores: Sequence[float],
    ) -> tuple[list[_ScoredEdge], list[_ScoredEdge], list[_ScoredEdge]]:
        distances_from = self.router.distances_from
        normal_p0: list[_ScoredEdge] = []
        normal_p1: list[_ScoredEdge] = []
        reversed_p0: list[_ScoredEdge] = []
        for index, (state, score) in enumerate(zip(previous_layer, previous_scores)):
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
        return normal_p0, normal_p1, reversed_p0

    def _best_from(
        self,
        sources: Sequence[_ScoredEdge],
        target_edge: EdgeId,
        *,
        penalty: float = 0.0,
        best_score: float = -inf,
        best_index: int = -1,
    ) -> tuple[float, int]:
        inv_scale = 1.0 / self.length_scale_m
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

    def best_predecessors(
        self,
        previous_layer: Sequence[EdgeState],
        previous_scores: Sequence[float],
        current_layer: Sequence[EdgeState],
    ) -> tuple[list[float], list[int]]:
        normal_p0, normal_p1, reversed_p0 = self._prepare(previous_layer, previous_scores)
        reversal_penalty = -self.reversal_penalty_m / self.length_scale_m
        best_scores: list[float] = []
        best_indices: list[int] = []
        for target in current_layer:
            if not target.reversed_used:
                score, index = self._best_from(normal_p0, target.edge)
            else:
                score, index = self._best_from(normal_p1, target.edge)
                if reversed_p0:
                    score, index = self._best_from(
                        reversed_p0,
                        target.edge,
                        penalty=reversal_penalty,
                        best_score=score,
                        best_index=index,
                    )
            best_scores.append(score)
            best_indices.append(index)
        return best_scores, best_indices


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


def reconstruct_edge_path(
    states: Sequence[EdgeState],
    router: DirectedNetworkRouter,
) -> list[DirectedEdge]:
    """Reconstruct a continuous directed edge walk from decoded ``EdgeState`` sequence."""
    if not states:
        return []
    output: list[DirectedEdge] = [DirectedEdge(*states[0].edge)]
    for previous, current in zip(states, states[1:]):
        is_reversed = (not previous.reversed_used) and current.reversed_used
        if is_reversed:
            u, v, key = previous.edge
            start_edge: EdgeId = (v, u, key)
            output.append(DirectedEdge(*start_edge))
        else:
            start_edge = previous.edge
        if start_edge == current.edge:
            continue
        cached = router._route(start_edge, current.edge)
        assert cached is not None
        _, _, tail_edges = cached
        output.extend(tail_edges)
    return output


def decode_edge_route(
    observation_candidates: Sequence[Sequence[Candidate]],
    observations: Sequence[Point],
    router: DirectedNetworkRouter,
    sigma: float,
    *,
    length_scale_m: float = DEFAULT_LENGTH_SCALE_M,
    allow_single_reversal: bool = False,
    max_pushback_radius_m: float | None = None,
    reversal_origin: Point | None = None,
    start_edges: Iterable[EdgeId] | None = None,
    end_edges: Iterable[EdgeId] | None = None,
) -> list[DirectedEdge]:
    """Decode a turn-constrained directed edge path using edge-anchored Dual-Graph DTW.

    Each observation layer maps to directed graph edges (no sub-edge projection offsets).
    Optional ``start_edges`` / ``end_edges`` constrain the path endpoints with zero emission
    cost, paying only the dual-graph length regularization needed to connect to the track.
    """
    if not observation_candidates:
        raise nx.NetworkXNoPath("No reachable candidate sequence")

    origin = reversal_origin if reversal_origin is not None else observations[0]
    layer_distances: list[dict[EdgeId, float]] = []
    layer_points: list[Point] = []

    if start_edges is not None:
        valid_start = {edge: 0.0 for edge in start_edges if edge in router.lengths}
        if not valid_start:
            raise nx.NetworkXNoPath("No usable start boundary edges")
        layer_distances.append(valid_start)
        layer_points.append(observations[0])

    for point, candidates in zip(observations, observation_candidates):
        edge_dists = directed_edge_distances(candidates, router)
        if not edge_dists:
            raise nx.NetworkXNoPath("Observation layer has no usable directed edges")
        layer_distances.append(edge_dists)
        layer_points.append(point)

    if end_edges is not None:
        valid_end = {edge: 0.0 for edge in end_edges if edge in router.lengths}
        if not valid_end:
            raise nx.NetworkXNoPath("No usable end boundary edges")
        layer_distances.append(valid_end)
        layer_points.append(observations[-1])

    has_start = start_edges is not None
    has_end = end_edges is not None
    last_idx = len(layer_distances) - 1

    # Build per-layer state lists and emission score tables.
    state_layers: list[list[EdgeState]] = []
    layer_emissions: list[dict[EdgeId, float]] = []
    for layer_idx, edge_dists in enumerate(layer_distances):
        is_boundary = (has_start and layer_idx == 0) or (has_end and layer_idx == last_idx)
        emissions = (
            {edge: 0.0 for edge in edge_dists}
            if is_boundary
            else {edge: observation_log_score(dist, sigma) for edge, dist in edge_dists.items()}
        )
        layer_emissions.append(emissions)
        if layer_idx == 0 or not allow_single_reversal:
            state_layers.append([EdgeState(edge, reversed_used=False) for edge in edge_dists])
        else:
            state_layers.append(
                [EdgeState(edge, reversed_used=False) for edge in edge_dists]
                + [EdgeState(edge, reversed_used=True) for edge in edge_dists]
            )

    # Emit per-step scorers; use layer-indexed emission lookup via wrapper states or closure.
    # Because EdgeState is shared across layers, wrap emission lookup per layer by binding
    # a lightweight (layer_idx, EdgeState) pair? Even simpler: store emission right on a
    # local _ScoredLayerState so generic viterbi() stays 100% unchanged!
    scored_layers: list[list[tuple[EdgeState, float]]] = [
        [(state, emissions[state.edge]) for state in layer]
        for layer, emissions in zip(state_layers, layer_emissions)
    ]

    step_scorers = [
        _EdgeLayerStepAdapter(
            EdgeTransitionStep(
                router=router,
                length_scale_m=length_scale_m,
                allow_reversal=(
                    allow_single_reversal
                    and (
                        max_pushback_radius_m is None
                        or layer_points[step - 1].distance(origin) <= max_pushback_radius_m
                    )
                ),
            )
        )
        for step in range(1, len(scored_layers))
    ]

    decoded = viterbi(scored_layers, lambda item: item[1], step_scorers)
    return reconstruct_edge_path([state for state, _ in decoded], router)


@dataclass(frozen=True, slots=True)
class _EdgeLayerStepAdapter:
    """Adapt ``EdgeTransitionStep`` to ``(EdgeState, emission)`` tuples for generic ``viterbi``."""

    inner: EdgeTransitionStep

    def best_predecessors(
        self,
        previous_layer: Sequence[tuple[EdgeState, float]],
        previous_scores: Sequence[float],
        current_layer: Sequence[tuple[EdgeState, float]],
    ) -> tuple[list[float], list[int]]:
        return self.inner.best_predecessors(
            [state for state, _ in previous_layer],
            previous_scores,
            [state for state, _ in current_layer],
        )
