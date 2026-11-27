from __future__ import annotations

from itertools import product

import networkx as nx
from pyproj import Proj, Transformer
from shapely.geometry import LineString, Point

from airport_surface import AirportGraph
from path_map.candidates import CandidateIndex
from path_map.edge_dtw import (
    DepartureState,
    decode_arrival_route,
    decode_departure_route,
    directed_edge_distances,
    observation_log_score,
)
from path_map.path import Path
from path_map.router import DirectedNetworkRouter
from path_map.viterbi import viterbi
from tests.test_path_map import straight_airport_graph, straight_od_graph


def test_arrival_dtw_matches_exhaustive_search_on_straight_graph():
    graph, _ = straight_airport_graph()
    index = CandidateIndex(graph)
    router = DirectedNetworkRouter(index)
    observations = [Point(450_000 + x, 4_428_001) for x in (2, 9, 17)]
    obs_candidates = [
        index.candidates(i, point, radius=12, maximum=4)
        for i, point in enumerate(observations)
    ]
    sigma, length_scale = 2.0, 50.0

    edges = decode_arrival_route(
        obs_candidates,
        observations,
        router,
        sigma,
        length_scale_m=length_scale,
    )
    path = Path(graph, edges)
    assert path.edge_ids == (("1", "2", 0), ("2", "3", 1))

    # Exhaustively verify the edge-state sequence score matches optimum.
    per_layer_dists = [directed_edge_distances(cands, router) for cands in obs_candidates]

    def score_seq(seq):
        total = sum(observation_log_score(d[e], sigma) for d, e in zip(per_layer_dists, seq))
        for e1, e2 in zip(seq, seq[1:]):
            if e1 == e2:
                continue
            dist = router.distances_from(e1).get(e2)
            if dist is None:
                return float("-inf")
            total -= dist / length_scale
        return total

    best_seq = max(product(*(d.keys() for d in per_layer_dists)), key=score_seq)
    assert best_seq == (("1", "2", 0), ("1", "2", 0), ("2", "3", 1))


def test_arrival_dtw_absorbs_heavy_backward_jitter_without_heuristics():
    """Large backward jitter (15m+) on a normal taxiway stays cleanly on the edge."""
    projection = Proj("EPSG:32650")
    to_wgs84 = Transformer.from_proj(projection, "EPSG:4326", always_xy=True)
    coords = {
        "1": (450_000.0, 4_428_000.0),
        "2": (450_100.0, 4_428_000.0),
        "3": (450_200.0, 4_428_000.0),
    }
    graph = nx.MultiGraph()
    for node, xy in coords.items():
        graph.add_node(node, pos=to_wgs84.transform(*xy))
    for u, v in (("1", "2"), ("2", "3")):
        line = LineString([graph.nodes[u]["pos"], graph.nodes[v]["pos"]])
        graph.add_edge(u, v, key=0, geometry=line)
    airport_graph = AirportGraph(graph, projection)
    index = CandidateIndex(airport_graph)
    router = DirectedNetworkRouter(index)

    # Jitter backwards by 25m on 1->2, then poke 3m past junction 2 and jitter back 15m onto 1->2,
    # before continuing cleanly onto 2->3.
    xs = [10, 40, 15, 50, 103, 88, 120, 160, 190]
    observations = [Point(450_000.0 + x, 4_428_001.0) for x in xs]
    obs_candidates = [
        index.candidates(i, pt, radius=30.0, maximum=4)
        for i, pt in enumerate(observations)
    ]

    edges = decode_arrival_route(
        obs_candidates, observations, router, sigma=10.0, length_scale_m=50.0
    )
    path = Path(airport_graph, edges)
    assert path.edge_ids == (("1", "2", 0), ("2", "3", 0))


def test_departure_dtw_supports_pushback_reversal():
    """Departure pushes back from dead-end stand then reverses once onto the taxiway."""
    projection = Proj("EPSG:32650")
    to_wgs84 = Transformer.from_proj(projection, "EPSG:4326", always_xy=True)
    coords = {
        "1": (450_000.0, 4_428_000.0),
        "2": (450_000.0, 4_428_060.0),
        "3": (449_920.0, 4_428_060.0),
        "4": (450_100.0, 4_428_060.0),
    }
    graph = nx.MultiGraph()
    for node, xy in coords.items():
        graph.add_node(node, pos=to_wgs84.transform(*xy))
    for u, v in (("1", "2"), ("2", "3"), ("2", "4")):
        line = LineString([graph.nodes[u]["pos"], graph.nodes[v]["pos"]])
        graph.add_edge(u, v, key=0, geometry=line)
    airport_graph = AirportGraph(graph, projection)
    index = CandidateIndex(airport_graph)
    router = DirectedNetworkRouter(index, max_turn_angle_deg=130.0)

    # Push back 1 -> 2 -> 3 (west), stop, reverse in place, taxi 3 -> 2 -> 4 (east).
    pts = [
        (450_000.0, 4_428_010.0),
        (450_000.0, 4_428_055.0),
        (449_950.0, 4_428_060.0),
        (449_940.0, 4_428_060.0),
        (449_960.0, 4_428_060.0),
        (450_040.0, 4_428_060.0),
        (450_090.0, 4_428_060.0),
    ]
    observations = [Point(x, y) for x, y in pts]
    obs_candidates = [
        index.candidates(i, pt, radius=30.0, maximum=4)
        for i, pt in enumerate(observations)
    ]

    edges = decode_departure_route(
        obs_candidates,
        observations,
        router,
        sigma=10.0,
        length_scale_m=50.0,
        max_pushback_radius_m=250.0,
        start_edges=[("1", "2", 0)],
        end_edges=[("2", "4", 0)],
    )
    path = Path(airport_graph, edges)
    assert path.edge_ids == (("1", "2", 0), ("2", "3", 0), ("3", "2", 0), ("2", "4", 0))


def test_arrival_dtw_connects_od_boundaries_across_missing_signal_gap():
    graph, _ = straight_od_graph()
    index = CandidateIndex(graph)
    router = DirectedNetworkRouter(index)
    # Only one observation in the middle taxiway; start/end boundaries bridge stand and runway.
    observations = [Point(450_015.0, 4_428_000.0)]
    obs_candidates = [index.candidates(0, observations[0], radius=5.0, maximum=2)]

    edges = decode_arrival_route(
        obs_candidates,
        observations,
        router,
        sigma=5.0,
        start_edges=[("1", "2", 0)],
        end_edges=[("3", "5", 0)],
    )
    path = Path(graph, edges)
    assert path.edge_ids == (("1", "2", 0), ("2", "3", 1), ("3", "5", 0))
    assert DepartureState(("1", "2", 0)).reversed_used is False


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
    emissions = [[-1.0, -0.5], [-0.2, -2.0], [0.0]]
    scorers = [
        TableScorer({("A", "C"): -0.1, ("B", "C"): -3.0, ("B", "D"): -0.1}),
        TableScorer({("C", "E"): -0.2, ("D", "E"): -0.1}),
    ]

    assert viterbi(layers, emissions, scorers) == ["A", "C", "E"]
