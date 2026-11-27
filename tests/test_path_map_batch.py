from __future__ import annotations

import networkx as nx
import pandas as pd
import pytest

from flight import Flight
from path_map import BatchStats, MapMatchingError, MapMatchingFailure, Path, match_batch
from path_map.path import DirectedEdge


def flights_with_two_flights() -> tuple[Flight, ...]:
    records = pd.DataFrame(
        {
            "flight_id": ["good", "good", "bad", "bad"],
            "timestamp": pd.date_range("2026-01-01", periods=4, freq="1min", tz="UTC"),
            "longitude": [116.0, 116.1, 116.2, 116.3],
            "latitude": [40.0, 40.1, 40.2, 40.3],
        }
    )
    return tuple(Flight(group) for _, group in records.groupby("flight_id"))


def test_batch_continues_after_expected_match_failure():
    expected_path = object()

    class FakeMatcher:
        def map_flight(self, flight):
            if flight.flight_id == "bad":
                raise MapMatchingError(
                    MapMatchingFailure.NO_CANDIDATES,
                    "This text is deliberately unrelated to the failure code",
                )
            return expected_path

    inputs = ((flight.flight_id, flight) for flight in flights_with_two_flights())
    outcomes = list(match_batch(FakeMatcher(), inputs))

    bad, good = outcomes
    assert (bad.key, bad.failure_type) == ("bad", "no_candidates")
    assert bad.reason == "This text is deliberately unrelated to the failure code"
    assert (good.key, good.path) == ("good", expected_path)
    stats = BatchStats()
    for outcome in outcomes:
        stats.add(outcome.status, outcome.failure_type, outcome.elapsed_seconds)
    assert stats.summary()["success_rate"] == 0.5
    assert stats.summary()["failure_counts"] == {"no_candidates": 1}


def test_batch_does_not_hide_programming_errors():
    class BrokenMatcher:
        def map_flight(self, flight):
            raise RuntimeError("bug")

    inputs = [(flight.flight_id, flight) for flight in flights_with_two_flights()]
    with pytest.raises(RuntimeError, match="bug"):
        list(match_batch(BrokenMatcher(), inputs))

    captured = list(match_batch(BrokenMatcher(), inputs, capture_system_errors=True))
    assert [item.failure_type for item in captured] == ["system", "system"]


def _make_od_test_flight(
    flight_id: str,
    movement: str,
    *,
    stand: str | None = None,
    runway: str | None = None,
) -> Flight:
    record: dict[str, object] = {
        "flight_id": flight_id,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "longitude": 116.6,
        "latitude": 40.07,
    }
    if stand is not None:
        key = "dep_stand_position" if movement == "departure" else "arr_stand_position"
        record[key] = stand
    if runway is not None:
        key = "org_runway" if movement == "departure" else "dst_runway"
        record[key] = runway
    return Flight([record], movement=movement)


def test_batch_infers_missing_stand_and_runway_from_path():
    stand_edge_id = ("S1", "N1", 0)
    runway_edge_id = ("N1", "R1", 0)
    raw_graph = nx.MultiGraph()
    raw_graph.add_edge("S1", "N1", key=0)
    raw_graph.add_edge("N1", "R1", key=0)
    raw_graph.add_edge("R1", "R2", key=0, ref="36R/18L")

    class FakeAirportGraph:
        runway_interfaces = {"R1": {"runway": [("R1", "R2", 0)]}}
        graph = raw_graph

        def stand_for_edge(self, edge):
            return "301" if edge in (stand_edge_id, ("N1", "S1", 0)) else None

        def runways_for_edge(self, edge):
            return frozenset({"36R"}) if edge in (runway_edge_id, ("R1", "N1", 0)) else None

    fake_graph = FakeAirportGraph()
    dep_path = Path(
        fake_graph,  # type: ignore[arg-type]
        [DirectedEdge("S1", "N1", 0), DirectedEdge("N1", "R1", 0)],
    )
    arr_path = Path(
        fake_graph,  # type: ignore[arg-type]
        [DirectedEdge("R1", "N1", 0), DirectedEdge("N1", "S1", 0)],
    )

    class FakeMatcher:
        airport_graph = fake_graph

        def map_flight(self, flight: Flight) -> Path:
            return dep_path if flight.movement == "departure" else arr_path

    dep_missing = _make_od_test_flight("dep_no_od", "departure")
    arr_missing = _make_od_test_flight("arr_no_od", "arrival")
    dep_reported = _make_od_test_flight("dep_reported", "departure", stand="999", runway="01")

    outcomes = list(
        match_batch(
            FakeMatcher(),  # type: ignore[arg-type]
            [
                (dep_missing.flight_id, dep_missing),
                (arr_missing.flight_id, arr_missing),
                (dep_reported.flight_id, dep_reported),
            ],
        )
    )

    assert (outcomes[0].stand_ref, outcomes[0].runway_ref) == ("301", "18L/36R")
    assert (outcomes[1].stand_ref, outcomes[1].runway_ref) == ("301", "18L/36R")
    assert (outcomes[2].stand_ref, outcomes[2].runway_ref) == ("999", "01")
