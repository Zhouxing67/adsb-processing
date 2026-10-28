from __future__ import annotations

import json

import networkx as nx
import pandas as pd
import pytest
from pyproj import Proj, Transformer
from shapely.geometry import LineString

from adsb import Flight
from airport_surface import AirportGraph, graph_id, load_graph, save_graph
from path_map import MapMatchingError, MatchConfig, Matcher, Path, PathGraphMismatch, PathRecord


def straight_airport_graph() -> tuple[AirportGraph, Transformer]:
    projection = Proj("EPSG:32650")
    to_wgs84 = Transformer.from_proj(projection, "EPSG:4326", always_xy=True)
    projected_positions = {
        "A": (450_000.0, 4_428_000.0),
        "B": (450_010.0, 4_428_000.0),
        "C": (450_020.0, 4_428_000.0),
    }
    positions = {
        node: to_wgs84.transform(*position) for node, position in projected_positions.items()
    }
    graph = nx.MultiGraph()
    for node, position in positions.items():
        graph.add_node(node, pos=position)
    graph.add_edge("A", "B", key="AB", geometry=LineString([positions["A"], positions["B"]]))
    graph.add_edge("B", "C", key="BC", geometry=LineString([positions["B"], positions["C"]]))
    return AirportGraph(graph, projection), to_wgs84


def test_reusing_matcher_does_not_mutate_graph_or_change_result():
    airport_graph, to_wgs84 = straight_airport_graph()
    points = [to_wgs84.transform(x, 4_428_000.0) for x in (450_001.0, 450_009.0, 450_019.0)]
    flight = Flight(
        pd.DataFrame(
            {
                "flight_id": ["test"] * len(points),
                "timestamp": pd.date_range(
                    "2026-01-01", periods=len(points), freq="5s", tz="UTC"
                ),
                "longitude": [point[0] for point in points],
                "latitude": [point[1] for point in points],
            }
        )
    )
    matcher = Matcher(
        airport_graph,
        MatchConfig(search_radius=3, max_candidates=3, gps_sigma=2, transition_beta=5),
    )
    original_nodes = tuple(airport_graph.graph.nodes)
    original_edges = tuple(airport_graph.graph.edges(keys=True))

    results = [matcher.map_flight(flight).edge_ids for _ in range(20)]

    assert all(result == results[0] for result in results)
    assert tuple(airport_graph.graph.nodes) == original_nodes
    assert tuple(airport_graph.graph.edges(keys=True)) == original_edges
    assert nx.is_frozen(matcher.router.routing_graph)


def make_flight(to_wgs84: Transformer, points: list[tuple[float, float]]) -> Flight:
    lon_lat = [to_wgs84.transform(x, y) for x, y in points]
    return Flight(
        pd.DataFrame(
            {
                "flight_id": ["test"] * len(points),
                "timestamp": pd.date_range("2026-01-01", periods=len(points), freq="5s", tz="UTC"),
                "longitude": [point[0] for point in lon_lat],
                "latitude": [point[1] for point in lon_lat],
            }
        )
    )


def robust_matcher(airport_graph: AirportGraph) -> Matcher:
    return Matcher(
        airport_graph,
        MatchConfig(
            search_radius=3,
            max_search_radius=30,
            max_candidates=10,
            gps_sigma=5,
            transition_beta=10,
        ),
    )


def test_isolated_observation_without_candidates_is_skipped():
    airport_graph, to_wgs84 = straight_airport_graph()
    flight = make_flight(
        to_wgs84,
        [
            (450_001, 4_428_000),
            (450_010, 4_428_500),
            (450_019, 4_428_000),
        ],
    )

    path = robust_matcher(airport_graph).map_flight(flight)

    assert path.edge_ids == (("A", "B", "AB"), ("B", "C", "BC"))


def test_consecutive_observations_without_candidates_are_skipped():
    airport_graph, to_wgs84 = straight_airport_graph()
    flight = make_flight(
        to_wgs84,
        [
            (450_001, 4_428_000),
            (450_005, 4_428_500),
            (450_015, 4_428_500),
            (450_019, 4_428_000),
        ],
    )

    path = robust_matcher(airport_graph).map_flight(flight)

    assert path.edge_ids == (("A", "B", "AB"), ("B", "C", "BC"))


def test_candidate_radius_expands_when_initial_radius_finds_nothing():
    airport_graph, to_wgs84 = straight_airport_graph()
    flight = make_flight(
        to_wgs84,
        [(450_001, 4_428_010), (450_019, 4_428_010)],
    )

    path = robust_matcher(airport_graph).map_flight(flight)

    assert path.edge_ids == (("A", "B", "AB"), ("B", "C", "BC"))


def test_all_observations_without_candidates_still_fail():
    airport_graph, to_wgs84 = straight_airport_graph()
    flight = make_flight(
        to_wgs84,
        [(450_001, 4_428_500), (450_019, 4_428_500)],
    )

    with pytest.raises(MapMatchingError, match="any observation"):
        robust_matcher(airport_graph).map_flight(flight)


def test_long_time_gap_does_not_reject_otherwise_valid_observations():
    airport_graph, to_wgs84 = straight_airport_graph()
    flight = make_flight(
        to_wgs84,
        [(450_001, 4_428_000), (450_019, 4_428_000)],
    )
    flight.data.loc[1, "timestamp"] += pd.Timedelta(hours=1)

    path = robust_matcher(airport_graph).map_flight(flight)

    assert path.edge_ids == (("A", "B", "AB"), ("B", "C", "BC"))


def test_path_record_round_trip_resolves_against_same_graph(tmp_path):
    airport_graph, _ = straight_airport_graph()
    path = Path(airport_graph, [("A", "B", "AB"), ("B", "C", "BC")])
    record = PathRecord.from_path(path)
    encoded = json.loads(json.dumps(record.to_dict()))

    graph_file = tmp_path / "graph.json"
    save_graph(airport_graph, graph_file)
    loaded_graph = load_graph(graph_file)
    restored = PathRecord.from_dict(encoded).resolve(loaded_graph)

    assert restored.edge_ids == path.edge_ids
    assert record.graph_id == graph_id(loaded_graph)


def test_path_record_rejects_modified_graph():
    airport_graph, _ = straight_airport_graph()
    record = PathRecord.from_path(Path(airport_graph, [("A", "B", "AB")]))
    airport_graph.graph.edges["A", "B", "AB"]["ref"] = "A"

    with pytest.raises(PathGraphMismatch, match="Path requires graph"):
        record.resolve(airport_graph)


def test_saved_graph_rejects_content_tampering(tmp_path):
    airport_graph, _ = straight_airport_graph()
    graph_file = tmp_path / "graph.json"
    save_graph(airport_graph, graph_file)
    document = json.loads(graph_file.read_text(encoding="utf-8"))
    document["edges"][0]["geometry"] = LineString([(0, 0), (1, 1)]).__geo_interface__
    graph_file.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match graph_id"):
        load_graph(graph_file)
