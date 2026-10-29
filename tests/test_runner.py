from pathlib import Path

import pandas as pd

from airport_workbench import flight_key
from path_map import MovementType, load_data
from runner import Runner, _sample_path_associations


def make_runner(input_path: Path, *, limit: int | None = None) -> Runner:
    return Runner(
        Path("graph.json"),
        input_path,
        input_path,
        Path("output"),
        limit=limit,
    )


def test_iter_flights_groups_non_contiguous_input(tmp_path):
    source = tmp_path / "flights.csv"
    pd.DataFrame(
        {
            "flight_id": ["B", "A", "B", "A"],
            "timestamp": [
                "2026-01-01 00:00:02",
                "2026-01-01 00:00:02",
                "2026-01-01 00:00:01",
                "2026-01-01 00:00:01",
            ],
            "longitude": [2.0, 1.0, 2.1, 1.1],
            "latitude": [40.0, 40.0, 40.1, 40.1],
        }
    ).to_csv(source, index=False)

    flights = list(make_runner(source)._iter_flights(source))

    assert [flight.flight_id for flight in flights] == ["A", "B"]
    assert all(flight.data.timestamp.is_monotonic_increasing for flight in flights)


def test_iter_flights_honors_limit(tmp_path):
    source = tmp_path / "flights.csv"
    pd.DataFrame(
        {
            "flight_id": ["C", "B", "A"],
            "timestamp": ["2026-01-01"] * 3,
            "longitude": [1.0, 2.0, 3.0],
            "latitude": [40.0, 40.0, 40.0],
        }
    ).to_csv(source, index=False)

    flights = list(make_runner(source, limit=2)._iter_flights(source))

    assert [flight.flight_id for flight in flights] == ["A", "B"]


def test_load_data_attaches_movement_type(tmp_path):
    source = tmp_path / "flights.csv"
    pd.DataFrame(
        {
            "flight_id": ["A", "A"],
            "timestamp": ["2026-01-01 00:00:00", "2026-01-01 00:00:01"],
            "longitude": [116.0, 116.1],
            "latitude": [40.0, 40.1],
        }
    ).to_csv(source, index=False)

    traffic = load_data(source, MovementType.ARRIVAL)

    assert traffic.data["movement_type"].tolist() == ["arrival", "arrival"]


def test_sample_paths_remain_associated_across_failed_and_later_batches():
    class SampleFlight:
        def __init__(self, identifier: str) -> None:
            self.flight_id = identifier

    arrival_success = SampleFlight("A")
    arrival_failure = SampleFlight("B")
    departure_success = SampleFlight("C")
    path_a, path_c = object(), object()

    associations = _sample_path_associations(
        [arrival_success, arrival_failure, departure_success],
        [(arrival_success, path_a), (departure_success, path_c)],
    )

    assert associations == {
        flight_key(0, "provided", "A"): path_a,
        flight_key(2, "provided", "C"): path_c,
    }
