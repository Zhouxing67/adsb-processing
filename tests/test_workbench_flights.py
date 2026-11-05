from __future__ import annotations

import json
from dataclasses import asdict

import networkx as nx
import numpy as np
import pandas as pd
import pytest
from pyproj import Proj, Transformer
from shapely.geometry import LineString

from adsb import Flight
from airport_surface import AirportGraph
from airport_workbench.app import create_app
from airport_workbench.editor import EditorSession
from airport_workbench.flights import (
    CataloguePageOutOfRange,
    FlightWorkbench,
    flight_key,
)
from path_map import MapMatchingError, Path


class SmallGraph:
    def __init__(self) -> None:
        self.graph = nx.MultiGraph()
        self.graph.add_node("a", pos=(116.0, 40.0))

    def copy(self) -> SmallGraph:
        clone = SmallGraph()
        clone.graph = self.graph.copy()
        return clone


def flight(identifier: str, callsigns: tuple[str, str] | None = None) -> Flight:
    frame = pd.DataFrame(
        {
            "flight_id": [identifier, identifier],
            "timestamp": ["2024-01-01 00:00:00", "2024-01-01 00:01:00"],
            "longitude": [116.0, 116.001],
            "latitude": [40.0, 40.001],
        }
    )
    if callsigns:
        frame["callsign"] = callsigns
    return Flight(frame)


def flight_with_points(identifier: str, point_count: int) -> Flight:
    return Flight(
        pd.DataFrame(
            {
                "flight_id": [identifier] * point_count,
                "timestamp": pd.date_range(
                    "2024-01-01", periods=point_count, freq="1min", tz="UTC"
                ),
                "longitude": np.linspace(116.0, 116.01, point_count),
                "latitude": np.linspace(40.0, 40.01, point_count),
            }
        )
    )


def test_catalogue_point_filter_is_closed_and_precedes_pagination() -> None:
    workbench = FlightWorkbench(
        SmallGraph(),
        [
            flight_with_points("two", 2),
            flight_with_points("three", 3),
            flight_with_points("four", 4),
        ],
        movement_types=["arrival", "arrival", "departure"],
    )

    first = workbench.catalogue(min_points=2, max_points=3, page=1, page_size=1)
    second = workbench.catalogue(min_points=2, max_points=3, page=2, page_size=1)
    exact = workbench.catalogue(min_points=3, max_points=3)

    assert first["dataset_max_points"] == 4
    assert first["total"] == 2
    assert first["total_pages"] == 2
    assert first["items"][0]["point_count"] == 2
    assert second["items"][0]["point_count"] == 3
    assert [item["flight_id"] for item in exact["items"]] == ["three"]


def test_catalogue_empty_result_and_dataset_maximum_are_stable() -> None:
    workbench = FlightWorkbench(
        SmallGraph(), [flight_with_points("short", 2), flight_with_points("long", 5)]
    )

    empty = workbench.catalogue(query="missing")
    filtered = workbench.catalogue(max_points=2)

    assert empty["items"] == []
    assert empty["page"] == 0
    assert empty["total_pages"] == 0
    assert empty["dataset_max_points"] == 5
    assert filtered["dataset_max_points"] == 5


def test_catalogue_combines_search_movement_status_and_point_range() -> None:
    workbench = FlightWorkbench(
        SmallGraph(),
        [flight_with_points("target-arrival", 3), flight_with_points("target-departure", 3)],
        movement_types=["arrival", "departure"],
    )
    arrival_key = next(
        key for key, item in workbench.items.items() if item.flight_id == "target-arrival"
    )
    workbench.results[arrival_key].status = "success"

    result = workbench.catalogue(
        query="target",
        movement_type="arrival",
        status="success",
        min_points=3,
        max_points=3,
    )

    assert [item["flight_id"] for item in result["items"]] == ["target-arrival"]


def test_filtered_key_selection_covers_all_pages_and_is_fixed() -> None:
    workbench = FlightWorkbench(
        SmallGraph(),
        [flight_with_points(f"arrival-{index}", 3) for index in range(25)],
        movement_types=["arrival"] * 25,
    )

    selected = workbench.filtered_keys(
        query="arrival", movement_type="arrival", min_points=3, max_points=3
    )

    assert selected["count"] == 25
    assert len(selected["flight_keys"]) == 25
    workbench.results[selected["flight_keys"][0]].status = "success"
    assert len(selected["flight_keys"]) == 25


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"min_points": -1}, "min_points"),
        ({"max_points": -1}, "max_points"),
        ({"min_points": 4, "max_points": 3}, "greater"),
        ({"max_points": 6}, "dataset maximum"),
    ],
)
def test_catalogue_rejects_invalid_point_ranges(kwargs: dict, message: str) -> None:
    workbench = FlightWorkbench(SmallGraph(), [flight_with_points("five", 5)])

    with pytest.raises(ValueError, match=message):
        workbench.catalogue(**kwargs)


def test_catalogue_rejects_page_beyond_filtered_last_page() -> None:
    workbench = FlightWorkbench(SmallGraph(), [flight_with_points("two", 2)])

    with pytest.raises(CataloguePageOutOfRange) as error:
        workbench.catalogue(page=2)

    assert error.value.total_pages == 1


def test_batch_submission_is_not_limited_by_map_capacity_and_conflicts_are_explicit() -> None:
    flights = [flight(str(index)) for index in range(5)]
    flights.append(flight("5", ("CCA1", "CCA2")))
    workbench = FlightWorkbench(SmallGraph(), flights)
    keys = list(workbench.flights)

    submitted = workbench.submit(keys)
    assert submitted["queued_count"] == 6

    detail = workbench.detail(keys[-1])
    assert detail["fields"]["callsign"] is None
    assert detail["inconsistent_fields"]["callsign"] == ["CCA1", "CCA2"]


def test_partial_match_failure_keeps_other_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMatcher:
        def __init__(self, _graph: SmallGraph, _config: object) -> None:
            pass

        def map_flight(self, item: Flight) -> object:
            if item.flight_id == "bad":
                raise MapMatchingError("no candidate")
            return object()

    monkeypatch.setattr("airport_workbench.flights.Matcher", FakeMatcher)
    workbench = FlightWorkbench(SmallGraph(), [flight("good"), flight("bad")])
    keys = list(workbench.flights)
    submitted = workbench.submit(keys)
    workbench.executor.shutdown(wait=True)

    assert workbench.results[keys[0]].status == "success"
    assert workbench.results[keys[1]].status == "failed"
    assert workbench.results[keys[1]].error == "no candidate"
    progress = workbench.task_status([submitted["task_id"]])["tasks"][0]
    assert (progress["total"], progress["success"], progress["failed"]) == (2, 1, 1)
    assert progress["complete"] is True


def test_retry_does_not_rewrite_completed_task_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    class FakeMatcher:
        def __init__(self, _graph: SmallGraph, _config: object) -> None:
            pass

        def map_flight(self, _item: Flight) -> object:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise MapMatchingError("first attempt failed")
            return object()

    class InlineExecutor:
        def submit(self, function: object, *args: object) -> None:
            function(*args)  # type: ignore[operator]

    monkeypatch.setattr("airport_workbench.flights.Matcher", FakeMatcher)
    workbench = FlightWorkbench(SmallGraph(), [flight("retry")])
    workbench.executor.shutdown(wait=True)
    workbench.executor = InlineExecutor()  # type: ignore[assignment]
    key = next(iter(workbench.flights))

    first = workbench.submit([key])
    first_before_retry = workbench.task_status([first["task_id"]])["tasks"][0]
    second = workbench.submit([key])
    first_after_retry = workbench.task_status([first["task_id"]])["tasks"][0]
    second_status = workbench.task_status([second["task_id"]])["tasks"][0]

    assert first_before_retry["complete"] is True
    assert first_before_retry["failed"] == 1
    assert first_after_retry == first_before_retry
    assert second_status["complete"] is True
    assert second_status["success"] == 1

    workbench.graph_provider().graph.add_node("changed", pos=(116.2, 40.2))
    workbench.sync_graph()

    assert workbench.results[key].status == "stale"
    assert workbench.task_status([first["task_id"]])["tasks"][0] == first_before_retry
    preserved_second = workbench.task_status([second["task_id"]])["tasks"][0]
    assert preserved_second["success"] == 1
    assert preserved_second["complete"] is True


def test_batch_rejects_unknown_atomically_and_reports_skip_reasons() -> None:
    workbench = FlightWorkbench(SmallGraph(), [flight("one"), flight("two")])
    first, second = workbench.flights

    with pytest.raises(KeyError, match="flight_key"):
        workbench.submit([first, "missing", second])
    assert all(result.status == "unmatched" for result in workbench.results.values())

    workbench.results[first].status = "matching"
    workbench.results[second].status = "success"
    workbench.results[second].graph_id = workbench._graph_id
    workbench.results[second].config = asdict(workbench.match_config)
    result = workbench.submit([first, second])

    assert result["queued_count"] == 0
    assert result["skipped"] == [
        {"flight_key": first, "reason": "already_running"},
        {"flight_key": second, "reason": "current_success"},
    ]


def test_observation_detail_is_paginated_and_can_expand_fields() -> None:
    item = flight_with_points("many", 205)
    item.data["aircraft_type"] = "A320"
    workbench = FlightWorkbench(SmallGraph(), [item])
    key = next(iter(workbench.flights))

    second = workbench.detail(key, observation_page=2)
    expanded = workbench.detail(key, observation_page=3, all_fields=True)

    assert len(second["observations"]) == 100
    assert second["observations"][0]["record_index"] == 101
    assert "aircraft_type" not in second["observation_columns"]
    assert len(expanded["observations"]) == 5
    assert "aircraft_type" in expanded["observation_columns"]


def test_graph_change_invalidates_old_result() -> None:
    item = flight("one")
    workbench = FlightWorkbench(
        SmallGraph(),
        [item],
        paths_by_flight_key={flight_key(0, "provided", "one"): object()},
    )
    key = next(iter(workbench.flights))
    workbench.graph_provider().graph.add_node("b", pos=(116.1, 40.1))

    workbench.sync_graph()

    assert workbench.results[key].status == "stale"
    assert workbench.results[key].path is None


def test_real_path_and_nan_fields_serialize_through_all_endpoints() -> None:
    projection = Proj("EPSG:32650")
    to_wgs84 = Transformer.from_proj(projection, "EPSG:4326", always_xy=True)
    a, b = to_wgs84.transform(450_000.0, 4_428_000.0), to_wgs84.transform(
        450_010.0, 4_428_000.0
    )
    graph = nx.MultiGraph()
    graph.add_node("a", pos=a)
    graph.add_node("b", pos=b)
    graph.add_edge("a", "b", key="ab", geometry=LineString([a, b]))
    airport_graph = AirportGraph(graph, projection)
    item = Flight(
        pd.DataFrame(
            {
                "flight_id": ["real", "real"],
                "NUMBER": ["CCA123", "CCA123"],
                "optional": [np.nan, np.nan],
                "timestamp": pd.date_range("2026-01-01", periods=2, freq="1min", tz="UTC"),
                "longitude": [a[0], b[0]],
                "latitude": [a[1], b[1]],
            }
        )
    )
    key = flight_key(0, "provided", item.flight_id)
    app = create_app(
        EditorSession(airport_graph),
        flights=[item],
        paths_by_flight_key={key: Path(airport_graph, [("a", "b", "ab")])},
    )

    endpoints = {
        route.path: route.endpoint
        for route in app.routes
        if hasattr(route, "endpoint")
    }
    catalogue = endpoints["/api/flights"]()
    detail = endpoints["/api/flights/{flight_key}"](key)
    geometry = endpoints["/api/flights/{flight_key}/geometry"](key)
    statuses = endpoints["/api/matches"]()

    assert catalogue["items"][0]["flight_number"] == "CCA123"
    assert catalogue["items"][0]["match"]["status"] == "success"
    assert detail["fields"]["optional"] is None
    assert geometry["path"]["features"]
    assert geometry["flight"]["features"][1]["properties"]["optional"] is None
    assert statuses["tasks"] == []
    assert geometry["match"]["has_path"] is True
    json.dumps([catalogue, detail, geometry, statuses], allow_nan=False)
