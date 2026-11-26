from __future__ import annotations

from itertools import product

import pytest
from shapely.geometry import Point

from path_map.candidates import CandidateIndex
from path_map.hmm import (
    DirectedNetworkRouter,
    observation_log_score,
    transition_log_score,
    viterbi,
)
from path_map.matcher import _append_transition_edges
from path_map.path import DirectedEdge
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

    states, _ = viterbi(layers, observations, router, sigma, beta)

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

    _append_transition_edges(output, (ab, ba, ab, ab))

    assert output == [ab, ba, ab, ab]
