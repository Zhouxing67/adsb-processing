from __future__ import annotations

import pandas as pd
import pytest

import path_map.matcher as matcher_module
from adsb import Flights
from path_map import MapMatchingError, map_flights


def flights_with_two_flights() -> Flights:
    return Flights(
        pd.DataFrame(
            {
                "flight_id": ["good", "good", "bad", "bad"],
                "timestamp": pd.date_range("2026-01-01", periods=4, freq="1min", tz="UTC"),
                "longitude": [116.0, 116.1, 116.2, 116.3],
                "latitude": [40.0, 40.1, 40.2, 40.3],
            }
        )
    )


def test_batch_continues_after_expected_match_failure(monkeypatch):
    expected_path = object()

    class FakeMatcher:
        def __init__(self, graph, config):
            pass

        def map_flight(self, flight):
            if flight.flight_id == "bad":
                raise MapMatchingError("no candidates")
            return expected_path

    monkeypatch.setattr(matcher_module, "Matcher", FakeMatcher)
    result = map_flights(object(), flights_with_two_flights())

    assert result.matches == [("good", expected_path)]
    assert len(result.failures) == 1
    assert result.failures[0].flight_id == "bad"
    assert result.failures[0].reason == "no candidates"


def test_batch_does_not_hide_programming_errors(monkeypatch):
    class BrokenMatcher:
        def __init__(self, graph, config):
            pass

        def map_flight(self, flight):
            raise RuntimeError("bug")

    monkeypatch.setattr(matcher_module, "Matcher", BrokenMatcher)
    with pytest.raises(RuntimeError, match="bug"):
        map_flights(object(), flights_with_two_flights())
