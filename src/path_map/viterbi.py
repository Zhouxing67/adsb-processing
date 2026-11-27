"""Generic layered Viterbi dynamic programming decoder."""

from __future__ import annotations

from collections.abc import Sequence
from math import inf
from typing import Protocol

import networkx as nx


class StepScorer[S](Protocol):
    """Per-step transition scorer supplying optimal predecessor scores and indices."""

    def best_predecessors(
        self,
        previous_layer: Sequence[S],
        previous_scores: Sequence[float],
        current_layer: Sequence[S],
    ) -> tuple[list[float], list[int]]: ...


def viterbi[S](
    layers: Sequence[Sequence[S]],
    emissions: Sequence[Sequence[float]],
    step_scorers: Sequence[StepScorer[S]],
) -> list[S]:
    """Decode the highest-scoring state sequence across layered HMM states."""
    if not layers or not layers[0]:
        raise nx.NetworkXNoPath("No reachable candidate sequence")
    if len(emissions) != len(layers):
        raise ValueError(
            f"Expected {len(layers)} emission layers for {len(layers)} state layers, "
            f"got {len(emissions)}"
        )
    if len(step_scorers) != len(layers) - 1:
        raise ValueError(
            f"Expected {len(layers) - 1} step scorers for {len(layers)} layers, "
            f"got {len(step_scorers)}"
        )

    scores = list(emissions[0])
    backrefs: list[list[int]] = []

    for previous_layer, current_layer, layer_emissions, scorer in zip(
        layers, layers[1:], emissions[1:], step_scorers
    ):
        best_prev_scores, step_refs = scorer.best_predecessors(
            previous_layer, scores, current_layer
        )
        scores = [
            prev + emission if prev > -inf else -inf
            for prev, emission in zip(best_prev_scores, layer_emissions)
        ]
        backrefs.append(step_refs)

    if not scores:
        raise nx.NetworkXNoPath("No reachable candidate sequence")
    best_index = max(range(len(scores)), key=scores.__getitem__)
    if scores[best_index] == -inf:
        raise nx.NetworkXNoPath("No reachable candidate sequence")

    path_indices = [best_index]
    for step_refs in reversed(backrefs):
        best_index = step_refs[best_index]
        path_indices.append(best_index)
    path_indices.reverse()
    return [layer[index] for layer, index in zip(layers, path_indices)]
