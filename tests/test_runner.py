import pandas as pd

from path_map import MovementType, load_data


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

    flights = list(load_data(source).iterate())

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

    flights = list(load_data(source).iterate(limit=2))

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
