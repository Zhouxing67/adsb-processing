from __future__ import annotations

import pandas as pd
import pytest

from flight import Flight
from path_map import BatchStats, MapMatchingError, MapMatchingFailure, match_batch


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
