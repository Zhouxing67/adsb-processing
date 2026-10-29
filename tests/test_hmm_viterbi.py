from __future__ import annotations

from itertools import product

import pytest
from shapely.geometry import Point

from path_map.candidates import Candidate
from path_map.hmm import (
    Transition,
    observation_log_score,
    transition_log_score,
    viterbi,
)
from path_map.matcher import _append_transition_edges
from path_map.path import DirectedEdge


def make_candidate(layer: int, state: int, distance: float) -> Candidate:
    return Candidate(layer, (layer, state, 0), distance, Point(layer, state), 0, 0)


class TableRouter:
    def __init__(self, distances):
        self.distances = distances

    def transition(self, source, target):
        distance = self.distances.get((source.edge_id, target.edge_id))
        if distance is None:
            return None
        return Transition(distance, ())


def test_viterbi_score_matches_exhaustive_candidate_sequence_search():
    layers = [
        [make_candidate(0, 0, 0.5), make_candidate(0, 1, 2.0)],
        [make_candidate(1, 0, 1.0), make_candidate(1, 1, 0.2)],
        [make_candidate(2, 0, 0.4), make_candidate(2, 1, 1.5)],
    ]
    observations = [Point(0, 0), Point(4, 0), Point(10, 0)]
    distances = {
        (source.edge_id, target.edge_id): 1 + source.edge_id[1] + 3 * target.edge_id[1]
        for left, right in zip(layers, layers[1:])
        for source in left
        for target in right
    }
    router = TableRouter(distances)
    sigma, beta = 2.0, 3.0

    states, _ = viterbi(layers, observations, router, sigma, beta)

    def score(sequence):
        total = sum(observation_log_score(candidate.distance, sigma) for candidate in sequence)
        for step, (source, target) in enumerate(zip(sequence, sequence[1:])):
            total += transition_log_score(
                distances[source.edge_id, target.edge_id],
                observations[step].distance(observations[step + 1]),
                beta,
            )
        return total

    exhaustive = list(product(*layers))
    assert score(states) == pytest.approx(max(map(score, exhaustive)))


def test_transition_boundary_merge_preserves_reversal_and_internal_repetition():
    ab = DirectedEdge("A", "B", 0)
    ba = DirectedEdge("B", "A", 0)
    output = [ab]

    _append_transition_edges(output, (ab, ba, ab, ab))

    assert output == [ab, ba, ab, ab]
