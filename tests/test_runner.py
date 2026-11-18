import pandas as pd

from flight import MovementType
from scripts.csv_flights import load_csv_flights


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

    flights = list(load_csv_flights(source).iterate())

    assert [flight.flight_id for flight in flights] == ["A", "B"]
    for flight in flights:
        times = [row["timestamp"] for row in flight.rows]
        assert times == sorted(times)


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

    flights = list(load_csv_flights(source).iterate(limit=2))

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

    traffic = load_csv_flights(source, MovementType.ARRIVAL)

    assert [row["movement_type"] for row in traffic.rows] == ["arrival", "arrival"]
