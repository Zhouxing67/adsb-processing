from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb
import networkx as nx
import pandas as pd
import pytest
from pyproj import Proj, Transformer
from shapely.geometry import LineString, Point

from airport_surface import AirportGraph, graph_id, load_graph, save_graph
from flight import Flight, MovementType
from flight.flight_repository import FlightDatabase
from path_map import (
    MapMatchingError,
    MapMatchingFailure,
    MatchConfig,
    Matcher,
    Path,
    PathGraphMismatch,
    PathRecord,
    get_od,
)
from path_map.candidates import Candidate


def straight_airport_graph() -> tuple[AirportGraph, Transformer]:
    projection = Proj("EPSG:32650")
    to_wgs84 = Transformer.from_proj(projection, "EPSG:4326", always_xy=True)
    projected_positions = {
        "1": (450_000.0, 4_428_000.0),
        "2": (450_010.0, 4_428_000.0),
        "3": (450_020.0, 4_428_000.0),
    }
    positions = {
        node: to_wgs84.transform(*position) for node, position in projected_positions.items()
    }
    graph = nx.MultiGraph()
    for node, position in positions.items():
        graph.add_node(node, pos=position)
    graph.add_edge("1", "2", key=0, geometry=LineString([positions["1"], positions["2"]]))
    graph.add_edge("2", "3", key=1, geometry=LineString([positions["2"], positions["3"]]))
    return AirportGraph(graph, projection), to_wgs84


def straight_od_graph() -> tuple[AirportGraph, Transformer]:
    airport_graph, transform = straight_airport_graph()
    graph = airport_graph.graph
    graph.edges["1", "2", 0].update(aeroway="parking_position", ref="009")
    graph.edges["2", "3", 1]["aeroway"] = "taxiway"
    graph.add_node("5", pos=transform.transform(450_030, 4_428_000))
    graph.add_edge(
        "3",
        "5",
        aeroway="runway",
        ref="01/19",
        geometry=LineString([graph.nodes["3"]["pos"], graph.nodes["5"]["pos"]]),
    )
    airport_graph.rebuild_stand_index()
    airport_graph.rebuild_runway_interfaces()
    return airport_graph, transform


@pytest.mark.parametrize("direction", [MovementType.ARRIVAL, MovementType.DEPARTURE])
def test_get_od_uses_direction_and_preserves_physical_runway(direction):
    graph, transform = straight_od_graph()
    points = [(450_001, 4_428_000), (450_026, 4_428_000)]
    departure = direction == MovementType.DEPARTURE
    flight = make_flight(transform, points if departure else points[::-1], movement=direction)
    rows = flight.rows
    column = "org_runway" if departure else "dst_runway"
    config = MatchConfig(candidate_radius=1)
    reported = get_od(graph, Flight(rows), direction, config=config)
    expected = ("009", "01") if departure else ("01", "009")
    assert (reported.origin, reported.destination) == expected
    assert reported.runway_source == "reported"
    inferred = Matcher(graph, config).get_od(
        Flight([{**row, column: None} for row in rows], movement=direction)
    )
    assert inferred.runway_source == "inferred"
    assert inferred.runway_ref == "01/19"
    assert graph.graph.edges[inferred.runway_hit_edge]["aeroway"] == "runway"

    with pytest.raises(MapMatchingError) as conflict:
        get_od(graph, Flight([rows[0], {**rows[1], column: "19"}]), direction)
    assert conflict.value.code == MapMatchingFailure.INVALID_OD
    with pytest.raises(MapMatchingError) as mismatch:
        get_od(graph, flight, "arrival" if departure else "departure")
    assert mismatch.value.code == MapMatchingFailure.INVALID_OD


def test_reusing_matcher_does_not_mutate_graph_or_change_result():
    airport_graph, to_wgs84 = straight_od_graph()
    points = [to_wgs84.transform(x, 4_428_000.0) for x in (450_001.0, 450_009.0, 450_019.0)]
    flight = Flight(
        pd.DataFrame(
            {
                "flight_id": ["test"] * len(points),
                "dep_stand_position": "009",
                "org_runway": "01",
                "arr_stand_position": "009",
                "dst_runway": "01",
                "timestamp": pd.date_range("2026-01-01", periods=len(points), freq="5s", tz="UTC"),
                "longitude": [point[0] for point in points],
                "latitude": [point[1] for point in points],
            }
        ),
        movement="departure",
    )
    matcher = Matcher(
        airport_graph,
        MatchConfig(candidate_radius=3, max_candidates=3, gps_sigma=2, transition_beta=5),
    )
    original_nodes = tuple(airport_graph.graph.nodes)
    original_edges = tuple(airport_graph.graph.edges(keys=True))

    results = [matcher.map_flight(flight).edge_ids for _ in range(20)]

    assert all(result == results[0] for result in results)
    assert tuple(airport_graph.graph.nodes) == original_nodes
    assert tuple(airport_graph.graph.edges(keys=True)) == original_edges
    assert nx.is_frozen(matcher._directed_router.graph)


def make_flight(
    to_wgs84: Transformer, points: list[tuple[float, float]], *, movement="departure"
) -> Flight:
    lon_lat = [to_wgs84.transform(x, y) for x, y in points]
    return Flight(
        pd.DataFrame(
            {
                "flight_id": ["test"] * len(points),
                "dep_stand_position": "009",
                "org_runway": "01",
                "arr_stand_position": "009",
                "dst_runway": "01",
                "timestamp": pd.date_range("2026-01-01", periods=len(points), freq="5s", tz="UTC"),
                "longitude": [point[0] for point in lon_lat],
                "latitude": [point[1] for point in lon_lat],
            }
        ),
        movement=movement,
    )


def robust_matcher(airport_graph: AirportGraph) -> Matcher:
    return Matcher(
        airport_graph,
        MatchConfig(
            candidate_radius=30,
            max_candidates=10,
            gps_sigma=5,
            transition_beta=10,
        ),
    )


@pytest.mark.parametrize("departure", [True, False])
@pytest.mark.parametrize("detour", [True, False])
def test_fixed_od_finds_legal_alternative_or_reports_failure(departure, detour):
    airport_graph, to_wgs84 = straight_airport_graph()
    graph = airport_graph.graph
    x, y = 450_000, 4_428_000
    positions = {"3": (x + 2, y + 1), "4": (x + 10, y + 10), "5": (x - 8, y + 1)}
    for node, position in positions.items():
        graph.add_node(node, pos=to_wgs84.transform(*position))
    graph.edges["1", "2", 0].update(aeroway="parking_position", ref="009")
    links = [("2", "3", 1, "taxiway"), ("3", "5", 2, "runway")]
    if detour:
        links.extend([("2", "4", 3, "taxiway"), ("4", "3", 4, "taxiway")])
    for u, v, key, kind in links:
        graph.add_edge(
            u,
            v,
            key=key,
            aeroway=kind,
            geometry=LineString([graph.nodes[u]["pos"], graph.nodes[v]["pos"]]),
        )
    for _, _, data in graph.edges(data=True):
        if data.get("aeroway") == "runway":
            data["ref"] = "01/19"
    airport_graph.rebuild_stand_index()
    airport_graph.rebuild_runway_interfaces()
    expected = [("1", "2", 0), ("2", "4", 3), ("4", "3", 4)]
    # The only observation lies inside the stand edge. Neither endpoint is observed.
    if not departure:
        expected = [(v, u, key) for u, v, key in reversed(expected)]
    flight = make_flight(to_wgs84, [(x + 6, y)], movement="departure" if departure else "arrival")
    matcher = Matcher(airport_graph, MatchConfig(candidate_radius=0.5))

    if detour:
        path = matcher.map_flight(flight)
        assert path.edge_ids == tuple(expected)
    else:
        with pytest.raises(MapMatchingError, match="No turn-constrained path"):
            matcher.map_flight(flight)


def test_fixed_od_cannot_reverse_direction_between_observations():
    airport_graph, to_wgs84 = straight_airport_graph()
    graph = airport_graph.graph
    graph.edges["1", "2", 0].update(aeroway="parking_position", ref="009")
    graph.edges["2", "3", 1]["aeroway"] = "taxiway"
    x, y = 450_000, 4_428_000
    graph.add_node("5", pos=to_wgs84.transform(x + 30, y))
    graph.add_edge(
        "3",
        "5",
        aeroway="runway",
        geometry=LineString([graph.nodes["3"]["pos"], graph.nodes["5"]["pos"]]),
    )
    for _, _, data in graph.edges(data=True):
        if data.get("aeroway") == "runway":
            data["ref"] = "01/19"
    airport_graph.rebuild_stand_index()
    airport_graph.rebuild_runway_interfaces()
    matcher = Matcher(airport_graph, MatchConfig(candidate_radius=0.5))
    forward = make_flight(to_wgs84, [(x + 12, y), (x + 18, y)])
    reverse = make_flight(to_wgs84, [(x + 18, y), (x + 12, y)])

    assert matcher.map_flight(forward).edge_ids == (("1", "2", 0), ("2", "3", 1))
    with pytest.raises(MapMatchingError, match="No turn-constrained path"):
        matcher.map_flight(reverse)


@pytest.mark.parametrize(
    "movement,suffix,stand_column,runway_column",
    [
        ("departure", "dep", "dep_stand_position", "org_runway"),
        ("arrival", "arr", "arr_stand_position", "dst_runway"),
    ],
)
def test_database_flight_matches_using_its_od(
    tmp_path, movement, suffix, stand_column, runway_column
):
    airport_graph, to_wgs84 = straight_airport_graph()
    graph = airport_graph.graph
    graph.edges["1", "2", 0].update(aeroway="parking_position", ref="009")
    graph.edges["2", "3", 1]["aeroway"] = "taxiway"
    x, y = 450_000, 4_428_000
    graph.add_node("5", pos=to_wgs84.transform(x + 30, y))
    graph.add_edge(
        "3",
        "5",
        aeroway="runway",
        ref="01/19",
        geometry=LineString([graph.nodes["3"]["pos"], graph.nodes["5"]["pos"]]),
    )
    graph.add_edge(
        "2",
        "5",
        aeroway="taxiway",
        geometry=LineString(
            [graph.nodes["2"]["pos"], to_wgs84.transform(x + 20, y + 10), graph.nodes["5"]["pos"]]
        ),
    )
    airport_graph.rebuild_stand_index()
    airport_graph.rebuild_runway_interfaces()

    database_path = tmp_path / "flights.duckdb"
    points = [x + 12, x + 18, x + 26]
    expected = (("1", "2", 0), ("2", "3", 1))
    if movement == "arrival":
        points.reverse()
        expected = tuple((v, u, key) for u, v, key in reversed(expected))
    table = f"adsb_{suffix}"
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            f"CREATE TABLE {table} (flight_id VARCHAR, timestamp TIMESTAMP, "
            f"longitude DOUBLE, latitude DOUBLE, {stand_column} VARCHAR, {runway_column} VARCHAR, "
            "number VARCHAR, sche_dep TIMESTAMP)"
        )
        connection.executemany(
            f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "flight",
                    f"2026-01-01 00:00:0{i}",
                    *to_wgs84.transform(px, y),
                    " 009 " if i == 1 else None,
                    " 01 ",
                    "CA123",
                    "2026-01-01 08:00:00",
                )
                for i, px in enumerate(points)
            ],
        )

    database = FlightDatabase(database_path)
    matcher = Matcher(airport_graph, MatchConfig(candidate_radius=0.5))
    for flight in (
        database.observations.flight(movement, "flight"),
        *database.observations.iterate(movement, None),
    ):
        assert (flight.stand_ref, flight.runway_ref) == ("009", "01")
        assert flight.number == "CA123"
        assert flight.sche_dep == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert flight.observations[0].timestamp == datetime(2025, 12, 31, 16, tzinfo=timezone.utc)
        assert flight.actual_dep is None
        assert matcher.map_flight(flight).edge_ids == expected
    missing_runway = Flight(
        [{**row, runway_column: None} for row in flight.rows],
        movement=movement,
    )
    assert matcher.map_flight(missing_runway).edge_ids == expected
    missing_stand = Flight(
        [{**row, stand_column: None} for row in flight.rows],
        movement=movement,
    )
    with pytest.raises(MapMatchingError, match="Missing flight OD"):
        matcher.map_flight(missing_stand)


def test_isolated_observation_without_candidates_is_skipped():
    airport_graph, to_wgs84 = straight_od_graph()
    flight = make_flight(
        to_wgs84,
        [
            (450_001, 4_428_000),
            (450_010, 4_428_500),
            (450_019, 4_428_000),
        ],
    )

    path = robust_matcher(airport_graph).map_flight(flight)

    assert path.edge_ids == (("1", "2", 0), ("2", "3", 1))


def test_consecutive_observations_without_candidates_are_skipped():
    airport_graph, to_wgs84 = straight_od_graph()
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

    assert path.edge_ids == (("1", "2", 0), ("2", "3", 1))


def test_candidate_radius_finds_candidates_across_the_complete_range():
    airport_graph, to_wgs84 = straight_od_graph()
    flight = make_flight(
        to_wgs84,
        [(450_001, 4_428_010), (450_019, 4_428_010)],
    )

    path = robust_matcher(airport_graph).map_flight(flight)

    assert path.edge_ids == (("1", "2", 0), ("2", "3", 1))


def test_candidate_search_queries_once_with_complete_radius():
    airport_graph, _ = straight_airport_graph()
    matcher = robust_matcher(airport_graph)
    calls = []

    class RecordingIndex:
        def candidates(self, observation_index, point, radius, maximum):
            calls.append((observation_index, point, radius, maximum))
            return []

    matcher.index = RecordingIndex()
    point = Point(450_001, 4_428_000)

    assert matcher._candidates(7, point) == []
    assert calls == [(7, point, 30, 10)]


def test_complete_radius_keeps_farther_candidate_when_near_candidate_exists():
    airport_graph, _ = straight_airport_graph()
    matcher = robust_matcher(airport_graph)

    candidates = matcher._candidates(0, Point(450_001, 4_428_000))

    assert [candidate.edge_id for candidate in candidates] == [
        ("1", "2", 0),
        ("2", "3", 1),
    ]
    assert [candidate.distance for candidate in candidates] == pytest.approx([0, 9])


def test_candidate_search_respects_max_candidates_after_distance_sorting():
    airport_graph, _ = straight_airport_graph()
    matcher = Matcher(airport_graph, MatchConfig(candidate_radius=30, max_candidates=1))

    candidates = matcher._candidates(0, Point(450_001, 4_428_000))

    assert len(candidates) == 1
    assert candidates[0].edge_id == ("1", "2", 0)


def test_self_loop_candidates_are_ignored():
    airport_graph, _ = straight_airport_graph()
    matcher = robust_matcher(airport_graph)
    matcher.index = type(
        "SelfLoopIndex",
        (),
        {"candidates": lambda self, *_args: [Candidate(0, ("1", "1", 2), 0, Point(0, 0), 0, 0)]},
    )()

    assert matcher._candidates(0, Point(0, 0)) == []


def test_all_observations_without_candidates_still_fail():
    airport_graph, to_wgs84 = straight_od_graph()
    flight = make_flight(
        to_wgs84,
        [(450_001, 4_428_500), (450_019, 4_428_500)],
    )

    with pytest.raises(MapMatchingError, match="got 0"):
        robust_matcher(airport_graph).map_flight(flight)


def test_one_observation_can_match_with_od():
    airport_graph, to_wgs84 = straight_od_graph()
    flight = make_flight(
        to_wgs84,
        [(450_001, 4_428_000), (450_019, 4_428_500)],
    )

    assert robust_matcher(airport_graph).map_flight(flight).nodes == ("1", "2", "3")


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_distance_configuration_must_be_finite_and_positive(value):
    with pytest.raises(ValueError, match="finite and positive"):
        MatchConfig(candidate_radius=value)


@pytest.mark.parametrize("value", [0, -1, 181, float("inf"), float("nan")])
def test_turn_angle_configuration_must_be_finite_and_bounded(value):
    with pytest.raises(ValueError, match="max_transition_turn_angle_deg"):
        MatchConfig(max_transition_turn_angle_deg=value)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_turn_sample_configuration_must_be_finite_and_positive(value):
    with pytest.raises(ValueError, match="finite and positive"):
        MatchConfig(turn_tangent_sample_m=value)


@pytest.mark.parametrize("value", [True, 0, -1, 1.5])
def test_max_candidates_must_be_a_positive_integer(value):
    with pytest.raises(ValueError, match="positive integer"):
        MatchConfig(max_candidates=value)


def test_path_geometry_preserves_forward_reverse_and_repeated_order():
    airport_graph, _ = straight_airport_graph()
    path = Path(
        airport_graph,
        [("1", "2", 0), ("2", "1", 0), ("1", "2", 0)],
    )

    assert list(path.geometry.coords) == [
        airport_graph.graph.nodes[node]["pos"] for node in ("1", "2", "1", "2")
    ]


def test_path_geometry_preserves_closed_loop_and_repeated_edge_order():
    airport_graph, _ = straight_airport_graph()
    positions = nx.get_node_attributes(airport_graph.graph, "pos")
    airport_graph.graph.add_edge(
        "3", "1", key=2, geometry=LineString([positions["3"], positions["1"]])
    )
    path = Path(
        airport_graph,
        [("1", "2", 0), ("2", "3", 1), ("3", "1", 2), ("1", "2", 0)],
    )

    assert list(path.geometry.coords) == [positions[node] for node in ("1", "2", "3", "1", "2")]


def test_path_rejects_ambiguous_self_loop_direction():
    airport_graph, _ = straight_airport_graph()
    position = airport_graph.graph.nodes["1"]["pos"]
    airport_graph.graph.add_edge(
        "1",
        "1",
        key=2,
        geometry=LineString([position, (position[0] + 0.00001, position[1]), position]),
    )

    with pytest.raises(ValueError, match="Self-loop path direction is not supported"):
        Path(airport_graph, [("1", "1", 2)])


@pytest.mark.parametrize(
    "offsets",
    [
        [8, 7, 7, 6],
        [8, 8, 7, 6],
        [8, 7, 6, 6],
    ],
)
def test_repeated_positions_do_not_add_false_traversals(offsets):
    airport_graph, to_wgs84 = straight_od_graph()
    flight = make_flight(
        to_wgs84,
        [(450_000 + offset, 4_428_000) for offset in offsets],
        movement="arrival",
    )

    path = robust_matcher(airport_graph).map_flight(flight)

    assert path.edge_ids == (("3", "2", 1), ("2", "1", 0))


def test_stationary_observations_can_match_with_od():
    airport_graph, to_wgs84 = straight_od_graph()
    flight = make_flight(to_wgs84, [(450_007, 4_428_000)] * 3)

    assert robust_matcher(airport_graph).map_flight(flight).nodes == ("1", "2", "3")


def test_long_time_gap_does_not_reject_otherwise_valid_observations():
    airport_graph, to_wgs84 = straight_od_graph()
    flight = make_flight(
        to_wgs84,
        [(450_001, 4_428_000), (450_019, 4_428_000)],
    )
    rows = flight.rows
    rows[1]["timestamp"] += pd.Timedelta(hours=1)
    flight = Flight(rows, movement=flight.movement)

    path = robust_matcher(airport_graph).map_flight(flight)

    assert path.edge_ids == (("1", "2", 0), ("2", "3", 1))


def test_path_record_round_trip_resolves_against_same_graph(tmp_path):
    airport_graph, _ = straight_airport_graph()
    path = Path(airport_graph, [("1", "2", 0), ("2", "3", 1)])
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
    record = PathRecord.from_path(Path(airport_graph, [("1", "2", 0)]))
    airport_graph.graph.edges["1", "2", 0]["ref"] = "1"

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


def pushback_airport_graph(*, with_detour_loop: bool) -> tuple[AirportGraph, Transformer]:
    projection = Proj(proj="utm", zone=50, ellps="WGS84")
    to_wgs84 = Transformer.from_proj(projection, AirportGraph.wgs84, always_xy=True)
    x0, y0 = 450_000.0, 4_428_000.0
    coords = {
        "1": (x0, y0 - 60),  # stand end
        "2": (x0, y0),  # junction A
        "3": (x0, y0 + 100),  # pushback point P
        "4": (x0 - 120, y0),  # runway interface R
        "5": (x0 - 220, y0),  # runway
    }
    graph = nx.MultiGraph()
    for node, (x, y) in coords.items():
        graph.add_node(node, pos=to_wgs84.transform(x, y))

    def add_line(u: str, v: str, key: int, pts: list[tuple[float, float]], **attrs) -> None:
        graph.add_edge(
            u,
            v,
            key=key,
            geometry=LineString([to_wgs84.transform(x, y) for x, y in pts]),
            **attrs,
        )

    add_line("1", "2", 0, [coords["1"], coords["2"]], aeroway="parking_position", ref="009")
    add_line("2", "3", 0, [coords["2"], coords["3"]], aeroway="taxiway")
    add_line("2", "4", 0, [coords["2"], coords["4"]], aeroway="taxiway")
    add_line("4", "5", 0, [coords["4"], coords["5"]], aeroway="runway", ref="01/19")
    if with_detour_loop:
        # A 300m detour bulb east of P that returns to P heading south.
        d1 = (x0 + 60, y0 + 160)
        d2 = (x0 + 120, y0 + 80)
        graph.add_node("6", pos=to_wgs84.transform(*d1))
        graph.add_node("7", pos=to_wgs84.transform(*d2))
        add_line("3", "6", 0, [coords["3"], d1], aeroway="taxiway")
        add_line("6", "7", 0, [d1, d2], aeroway="taxiway")
        add_line("7", "3", 0, [d2, coords["3"]], aeroway="taxiway")
    return AirportGraph(graph, projection), to_wgs84


def test_departure_allows_single_pushback_reversal_without_detour_loop():
    airport_graph, to_wgs84 = pushback_airport_graph(with_detour_loop=True)
    x0, y0 = 450_000.0, 4_428_000.0
    # Push back north to y0+80, reverse in place, then taxi south to A and west to R.
    flight = make_flight(
        to_wgs84,
        [(x0, y0 + 20), (x0, y0 + 80), (x0, y0 + 40), (x0 - 60, y0)],
        movement="departure",
    )
    matcher = Matcher(airport_graph, MatchConfig(candidate_radius=20, transition_beta=20))

    path = matcher.map_flight(flight)

    assert path.edge_ids == (("1", "2", 0), ("2", "3", 0), ("3", "2", 0), ("2", "4", 0))


def test_arrival_does_not_allow_in_place_reversal():
    airport_graph, to_wgs84 = pushback_airport_graph(with_detour_loop=False)
    x0, y0 = 450_000.0, 4_428_000.0
    flight = make_flight(
        to_wgs84,
        [(x0 - 60, y0), (x0, y0 + 40), (x0, y0 + 80), (x0, y0 + 20)],
        movement="arrival",
    )
    matcher = Matcher(airport_graph, MatchConfig(candidate_radius=20, transition_beta=20))

    with pytest.raises(MapMatchingError, match="No turn-constrained path"):
        matcher.map_flight(flight)


def test_runway_roll_observations_disambiguate_symmetric_runway_entries():
    projection = Proj(proj="utm", zone=50, ellps="WGS84")
    to_wgs84 = Transformer.from_proj(projection, AirportGraph.wgs84, always_xy=True)
    x0, y0 = 450_000.0, 4_428_000.0
    coords = {
        "1": (x0 - 150, y0),  # stand
        "2": (x0 - 80, y0),  # taxiway junction
        "3": (x0, y0 + 50),  # north runway entry (slightly longer curved branch)
        "4": (x0, y0 - 40),  # south runway entry (slightly shorter branch)
        "5": (x0, y0 + 250),  # runway north end
        "6": (x0, y0 - 250),  # runway south end
    }
    graph = nx.MultiGraph()
    for node, (x, y) in coords.items():
        graph.add_node(node, pos=to_wgs84.transform(x, y))

    def add_line(u: str, v: str, key: int, pts: list[tuple[float, float]], **attrs) -> None:
        graph.add_edge(
            u,
            v,
            key=key,
            geometry=LineString([to_wgs84.transform(x, y) for x, y in pts]),
            **attrs,
        )

    add_line("1", "2", 0, [coords["1"], coords["2"]], aeroway="parking_position", ref="009")
    add_line("2", "3", 0, [coords["2"], (x0 - 20, y0 + 10), coords["3"]], aeroway="taxiway")
    add_line("2", "4", 0, [coords["2"], (x0 - 20, y0 - 10), coords["4"]], aeroway="taxiway")
    add_line("6", "4", 0, [coords["6"], coords["4"]], aeroway="runway", ref="01/19")
    add_line("4", "3", 0, [coords["4"], coords["3"]], aeroway="runway", ref="01/19")
    add_line("3", "5", 0, [coords["3"], coords["5"]], aeroway="runway", ref="01/19")
    airport_graph = AirportGraph(graph, projection)

    # Departure rolls north on the runway; missing runway_ref should still match north entry
    # and trim runway edges from the returned path.
    flight = make_flight(
        to_wgs84,
        [(x0 - 110, y0), (x0 - 85, y0), (x0, y0 + 80), (x0, y0 + 160)],
        movement="departure",
    )
    flight = Flight([{**row, "org_runway": None} for row in flight.rows], movement="departure")
    matcher = Matcher(airport_graph, MatchConfig(candidate_radius=30, transition_beta=20))

    path = matcher.map_flight(flight)

    assert path.edge_ids == (("1", "2", 0), ("2", "3", 0))


def test_missing_runway_ref_requires_runway_end_observation():
    airport_graph, to_wgs84 = pushback_airport_graph(with_detour_loop=False)
    x0, y0 = 450_000.0, 4_428_000.0
    # Track stops mid-taxiway without reaching the runway, and runway_ref is missing.
    flight = make_flight(
        to_wgs84,
        [(x0, y0 - 20), (x0 - 40, y0)],
        movement="departure",
    )
    flight = Flight([{**row, "org_runway": None} for row in flight.rows], movement="departure")
    matcher = Matcher(airport_graph, MatchConfig(candidate_radius=20, transition_beta=20))

    with pytest.raises(MapMatchingError, match="Missing flight OD") as exc_info:
        matcher.map_flight(flight)

    assert exc_info.value.code is MapMatchingFailure.MISSING_OD
