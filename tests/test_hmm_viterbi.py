from __future__ import annotations

from itertools import product

import pytest
from shapely.geometry import Point

from path_map.candidates import CandidateIndex
from path_map.hmm import (
    decode_route,
    observation_log_score,
    transition_log_score,
)
from path_map.path import DirectedEdge
from path_map.recovery import append_transition_edges
from path_map.router import DirectedNetworkRouter
from path_map.viterbi import viterbi
from tests.test_path_map import straight_airport_graph


def test_viterbi_score_matches_exhaustive_candidate_sequence_search():
    graph, _ = straight_airport_graph()
    index = CandidateIndex(graph)
    router = DirectedNetworkRouter(index)
    observations = [Point(450_000 + x, 4_428_001) for x in (2, 9, 17)]
    layers = [
        router.expand_candidates(index.candidates(i, point, radius=12, maximum=2))
        for i, point in enumerate(observations)
    ]
    sigma, beta = 2.0, 3.0

    states, _ = decode_route(layers, observations, router, sigma, beta)

    def score(sequence):
        total = sum(observation_log_score(candidate.distance, sigma) for candidate in sequence)
        for step, (source, target) in enumerate(zip(sequence, sequence[1:])):
            transition = router.transition(source, target)
            if transition is None:
                return float("-inf")
            total += transition_log_score(
                transition.distance,
                observations[step].distance(observations[step + 1]),
                beta,
            )
        return total

    exhaustive = list(product(*layers))
    assert score(states) > float("-inf")
    assert score(states) == pytest.approx(max(map(score, exhaustive)))


def test_transition_boundary_merge_preserves_reversal_and_internal_repetition():
    ab = DirectedEdge("A", "B", 0)
    ba = DirectedEdge("B", "A", 0)
    output = [ab]

    append_transition_edges(output, (ab, ba, ab, ab))

    assert output == [ab, ba, ab, ab]


def test_generic_viterbi_decodes_arbitrary_state_sequence():
    class TableScorer:
        def __init__(self, weights: dict[tuple[str, str], float]) -> None:
            self._weights = weights

        def best_predecessors(
            self,
            previous_layer: tuple[str, ...],
            previous_scores: list[float],
            current_layer: tuple[str, ...],
        ) -> tuple[list[float], list[int]]:
            best_scores: list[float] = []
            best_indices: list[int] = []
            for target in current_layer:
                best_score = float("-inf")
                best_index = -1
                for idx, (source, prev_score) in enumerate(zip(previous_layer, previous_scores)):
                    weight = self._weights.get((source, target))
                    if weight is None:
                        continue
                    candidate_score = prev_score + weight
                    if candidate_score > best_score:
                        best_score = candidate_score
                        best_index = idx
                best_scores.append(best_score)
                best_indices.append(best_index)
            return best_scores, best_indices

    layers = [("A", "B"), ("C", "D"), ("E",)]
    emissions = {"A": -1.0, "B": -0.5, "C": -0.2, "D": -2.0, "E": 0.0}
    scorers = [
        TableScorer({("A", "C"): -0.1, ("B", "C"): -3.0, ("B", "D"): -0.1}),
        TableScorer({("C", "E"): -0.2, ("D", "E"): -0.1}),
    ]

    assert viterbi(layers, emissions.__getitem__, scorers) == ["A", "C", "E"]
