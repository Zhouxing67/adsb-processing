from __future__ import annotations

import pandas as pd
import pytest

from flight import Flight


def observations(**overrides) -> pd.DataFrame:
    values = {
        "flight_id": ["A", "A"],
        "timestamp": ["2026-01-01 00:00:02", "2026-01-01 00:00:01"],
        "longitude": [116.1, 116.0],
        "latitude": [40.1, 40.0],
    }
    values.update(overrides)
    return pd.DataFrame(values)


def test_flight_validates_normalizes_and_sorts_trajectory():
    source = observations()

    flight = Flight(source)

    assert flight.flight_id == "A"
    assert [point.timestamp.isoformat() for point in flight.observations] == [
        "2026-01-01T00:00:01+00:00", "2026-01-01T00:00:02+00:00",
    ]
    assert [point.longitude for point in flight.observations] == [116.0, 116.1]
    source.loc[0, "longitude"] = 0
    assert [row["longitude"] for row in flight.rows] == [116.0, 116.1]


@pytest.mark.parametrize("column", ["flight_id", "timestamp", "longitude", "latitude"])
def test_flight_requires_core_columns(column):
    with pytest.raises(ValueError, match="required columns"):
        Flight(observations().drop(columns=column))


def test_flight_rejects_multiple_ids():
    with pytest.raises(ValueError, match="exactly one"):
        Flight(observations(flight_id=["A", "B"]))


@pytest.mark.parametrize(
    ("column", "values"),
    [
        ("timestamp", ["invalid", "2026-01-01"]),
        ("longitude", [181, 116]),
        ("latitude", [91, 40]),
    ],
)
def test_flight_rejects_invalid_required_values(column, values):
    with pytest.raises(ValueError):
        Flight(observations(**{column: values}))


def test_csv_record_loader_preserves_stand_codes_and_normalizes_time(tmp_path):
    from scripts.csv_flights import load_csv_flights

    source = tmp_path / "stands.csv"
    source.write_text(
        "flight_id,timestamp,longitude,latitude,dep_stand_position,altitude\n"
        "0001,2024-06-15 00:05:00,116.0,40.0,007,20\n"
        "0001,2024-06-14T16:06:00Z,116.1,40.0,,21\n",
        encoding="utf-8",
    )
    flight = next(iter(load_csv_flights(source, input_timezone="Asia/Shanghai")))
    assert flight.flight_id == "0001"
    assert [row["dep_stand_position"] for row in flight.rows] == ["007", None]
    assert [point.altitude for point in flight.observations] == [20.0, 21.0]
    assert [row["timestamp"].isoformat() for row in flight.rows] == [
        "2024-06-14T16:05:00+00:00", "2024-06-14T16:06:00+00:00",
    ]
