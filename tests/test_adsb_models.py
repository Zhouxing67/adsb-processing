from __future__ import annotations

import pandas as pd
import pytest

from adsb import Flight, Flights


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
    assert flight.data.timestamp.is_monotonic_increasing
    assert str(flight.data.timestamp.dtype) == "datetime64[ns, UTC]"
    assert flight.data.longitude.tolist() == [116.0, 116.1]
    source.loc[0, "longitude"] = 0
    assert flight.data.longitude.tolist() == [116.0, 116.1]


@pytest.mark.parametrize("column", ["flight_id", "timestamp", "longitude", "latitude"])
def test_flight_requires_core_columns(column):
    with pytest.raises(ValueError, match="required columns"):
        Flight(observations().drop(columns=column))


def test_flight_rejects_multiple_ids():
    with pytest.raises(ValueError, match="exactly one"):
        Flight(observations(flight_id=["A", "B"]))


def test_flights_requires_core_columns():
    with pytest.raises(ValueError, match="required columns"):
        Flights(observations().drop(columns="timestamp"))


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


def test_flights_groups_non_contiguous_observations_and_honors_limit():
    collection = Flights(
        pd.DataFrame(
            {
                "flight_id": ["B", "A", "B", "A"],
                "timestamp": pd.date_range("2026-01-01", periods=4, freq="1s"),
                "longitude": [116.0] * 4,
                "latitude": [40.0] * 4,
            }
        )
    )

    assert [flight.flight_id for flight in collection] == ["A", "B"]
    assert [flight.flight_id for flight in collection.iterate(limit=1)] == ["A"]
    assert list(collection.iterate(limit=0)) == []
