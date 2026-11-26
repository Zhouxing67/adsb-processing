"""Distance-based HMM scoring and airport-surface route decoding."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import inf, log, pi

import networkx as nx
from shapely.geometry import Point

from .candidates import Candidate
from .router import AnchoredSource, DirectedNetworkRouter, Transition
from .viterbi import viterbi

REVERSAL_PENALTY_M = 40.0


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


@dataclass(frozen=True, slots=True)
class RouteState:
    """Product HMM state pairing a directed edge candidate with pushback-reversal phase."""

    candidate: Candidate
    reversed_used: bool = False


type _ScoredAnchor = tuple[int, float, AnchoredSource]


@dataclass(frozen=True, slots=True)
class RouteTransitionStep:
    """Airport-surface transition policy between two consecutive ``RouteState`` layers."""

    router: DirectedNetworkRouter
    observed_distance: float
    beta: float
    max_detour_m: float | None = None
    allow_reversal: bool = False
    reversal_penalty_m: float = REVERSAL_PENALTY_M

    def _prepare(
        self,
        previous_layer: Sequence[RouteState],
        previous_scores: Sequence[float],
    ) -> tuple[list[_ScoredAnchor], list[_ScoredAnchor], list[_ScoredAnchor]]:
        normal_p0: list[_ScoredAnchor] = []
        normal_p1: list[_ScoredAnchor] = []
        reversed_p0: list[_ScoredAnchor] = []
        for index, (state, score) in enumerate(zip(previous_layer, previous_scores)):
            if score == -inf:
                continue
            anchor = self.router.anchor(state.candidate)
            if anchor is not None:
                if state.reversed_used:
                    normal_p1.append((index, score, anchor))
                else:
                    normal_p0.append((index, score, anchor))
            if self.allow_reversal and not state.reversed_used:
                rev_anchor = self.router.anchor(state.candidate, reversed_direction=True)
                if rev_anchor is not None:
                    reversed_p0.append((index, score, rev_anchor))
        return normal_p0, normal_p1, reversed_p0

    def _best_from(
        self,
        sources: Sequence[_ScoredAnchor],
        target: Candidate,
        *,
        penalty: float = 0.0,
        best_score: float = -inf,
        best_index: int = -1,
    ) -> tuple[float, int]:
        distance_from = self.router.distance_from_anchor
        observed = self.observed_distance
        beta = self.beta
        max_detour = self.max_detour_m
        for index, score, anchor in sources:
            distance = distance_from(anchor, target)
            if distance is None:
                continue
            if max_detour is not None and distance - observed > max_detour:
                continue
            value = score + transition_log_score(distance, observed, beta) + penalty
            if value > best_score:
                best_score = value
                best_index = index
        return best_score, best_index

    def best_predecessors(
        self,
        previous_layer: Sequence[RouteState],
        previous_scores: Sequence[float],
        current_layer: Sequence[RouteState],
    ) -> tuple[list[float], list[int]]:
        normal_p0, normal_p1, reversed_p0 = self._prepare(previous_layer, previous_scores)
        reversal_penalty = -self.reversal_penalty_m / self.beta
        best_scores: list[float] = []
        best_indices: list[int] = []
        for target in current_layer:
            if not target.reversed_used:
                score, index = self._best_from(normal_p0, target.candidate)
            else:
                score, index = self._best_from(normal_p1, target.candidate)
                if reversed_p0:
                    score, index = self._best_from(
                        reversed_p0,
                        target.candidate,
                        penalty=reversal_penalty,
                        best_score=score,
                        best_index=index,
                    )
            best_scores.append(score)
            best_indices.append(index)
        return best_scores, best_indices


def decode_route(
    layers: Sequence[Sequence[Candidate]],
    observations: Sequence[Point],
    router: DirectedNetworkRouter,
    sigma: float,
    beta: float,
    *,
    allow_single_reversal: bool = False,
    max_pushback_radius_m: float | None = None,
    reversal_origin: Point | None = None,
    max_transition_detour_m: float | None = None,
    has_boundary_layers: bool = False,
) -> tuple[list[Candidate], list[Transition]]:
    """Decode airport-surface candidates using product-state Viterbi and reconstruct transitions."""
    if not layers or not layers[0]:
        raise nx.NetworkXNoPath("No reachable candidate sequence")

    origin = reversal_origin if reversal_origin is not None else observations[0]
    last_step = len(layers) - 1

    state_layers: list[list[RouteState]] = [
        [RouteState(candidate, reversed_used=False) for candidate in layers[0]]
    ]
    for layer in layers[1:]:
        if allow_single_reversal:
            state_layers.append(
                [RouteState(candidate, reversed_used=False) for candidate in layer]
                + [RouteState(candidate, reversed_used=True) for candidate in layer]
            )
        else:
            state_layers.append(
                [RouteState(candidate, reversed_used=False) for candidate in layer]
            )

    step_scorers = [
        RouteTransitionStep(
            router=router,
            observed_distance=observations[step - 1].distance(observations[step]),
            beta=beta,
            max_detour_m=(
                None
                if has_boundary_layers and (step == 1 or step == last_step)
                else max_transition_detour_m
            ),
            allow_reversal=(
                allow_single_reversal
                and (
                    max_pushback_radius_m is None
                    or observations[step - 1].distance(origin) <= max_pushback_radius_m
                )
            ),
        )
        for step in range(1, len(layers))
    ]

    decoded_states = viterbi(
        state_layers,
        lambda state: observation_log_score(state.candidate.distance, sigma),
        step_scorers,
    )

    candidates = [state.candidate for state in decoded_states]
    transitions: list[Transition] = []
    for previous, current in zip(decoded_states, decoded_states[1:]):
        is_reversed = (not previous.reversed_used) and current.reversed_used
        transition = (
            router.reversed_transition(previous.candidate, current.candidate)
            if is_reversed
            else router.transition(previous.candidate, current.candidate)
        )
        assert transition is not None
        transitions.append(transition)
    return candidates, transitions
