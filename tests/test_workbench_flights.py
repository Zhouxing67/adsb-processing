from __future__ import annotations

import json
from dataclasses import asdict

import networkx as nx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pyproj import Proj, Transformer
from shapely.geometry import LineString

from airport_surface import AirportGraph
from airport_workbench.app import create_app
from airport_workbench.editor import EditorSession
from airport_workbench.flights import (
    CataloguePageOutOfRange,
    FlightFilter,
)
from airport_workbench.flights import (
    FlightWorkbench as DatabaseFlightWorkbench,
)
from flight import Flight
from flight.flight_repository import database_flight_key
from path_map import MapMatchingError, MapMatchingFailure, Path


class SmallGraph(AirportGraph):
    def __init__(self) -> None:
        graph = nx.MultiGraph()
        graph.add_node("1", pos=(116.0, 40.0))
        graph.add_node("2", pos=(116.001, 40.001))
        graph.add_edge(
            "1",
            "2",
            geometry=LineString([(116.0, 40.0), (116.001, 40.001)]),
        )
        super().__init__(graph, Proj("EPSG:32650"))


_flight_database_factory = None


@pytest.fixture(autouse=True)
def configure_flight_database_factory(flight_database_factory):
    global _flight_database_factory
    _flight_database_factory = flight_database_factory
    yield
    _flight_database_factory = None


def FlightWorkbench(
    airport_graph,
    flights=(),
    *,
    movement_types=None,
    flight_database=None,
    **kwargs,
):
    database = flight_database or _flight_database_factory(flights, movement_types)
    return DatabaseFlightWorkbench(airport_graph, database, **kwargs)


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

    first = workbench.catalogue(FlightFilter(min_points=2, max_points=3), page=1, page_size=1)
    second = workbench.catalogue(FlightFilter(min_points=2, max_points=3), page=2, page_size=1)
    exact = workbench.catalogue(FlightFilter(min_points=3, max_points=3))

    assert first["dataset_max_points"] == 4
    assert first["total"] == 2
    assert first["total_pages"] == 2
    assert first["items"][0]["point_count"] == 3
    assert second["items"][0]["point_count"] == 2
    assert [item["flight_id"] for item in exact["items"]] == ["three"]


def test_catalogue_empty_result_and_dataset_maximum_are_stable() -> None:
    workbench = FlightWorkbench(
        SmallGraph(), [flight_with_points("short", 2), flight_with_points("long", 5)]
    )

    empty = workbench.catalogue(FlightFilter(query="missing"))
    filtered = workbench.catalogue(FlightFilter(max_points=2))

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
        FlightFilter(
            query="target",
            movement_type="arrival",
            status="success",
            min_points=3,
            max_points=3,
        )
    )

    assert [item["flight_id"] for item in result["items"]] == ["target-arrival"]


def test_filtered_key_selection_covers_all_pages_and_is_fixed() -> None:
    workbench = FlightWorkbench(
        SmallGraph(),
        [flight_with_points(f"arrival-{index}", 3) for index in range(25)],
        movement_types=["arrival"] * 25,
    )

    selected = workbench.filtered_keys(
        FlightFilter(query="arrival", movement_type="arrival", min_points=3, max_points=3)
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
@pytest.mark.parametrize("operation", ["catalogue", "filtered_keys"])
def test_flight_filters_share_point_range_validation(
    kwargs: dict, message: str, operation: str
) -> None:
    workbench = FlightWorkbench(SmallGraph(), [flight_with_points("five", 5)])

    with pytest.raises(ValueError, match=message):
        getattr(workbench, operation)(FlightFilter(**kwargs))


def test_catalogue_rejects_page_beyond_filtered_last_page() -> None:
    workbench = FlightWorkbench(SmallGraph(), [flight_with_points("two", 2)])

    with pytest.raises(CataloguePageOutOfRange) as error:
        workbench.catalogue(page=2)

    assert error.value.total_pages == 1


def test_batch_submission_is_not_limited_by_map_capacity_and_conflicts_are_explicit() -> None:
    flights = [flight(str(index)) for index in range(5)]
    flights.append(flight("5", ("CCA1", "CCA2")))
    workbench = FlightWorkbench(SmallGraph(), flights)
    keys = list(workbench.items)

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
                raise MapMatchingError(MapMatchingFailure.NO_CANDIDATES, "no candidate")
            return object()

    monkeypatch.setattr("airport_workbench.flight_match_tasks.Matcher", FakeMatcher)
    workbench = FlightWorkbench(SmallGraph(), [flight("good"), flight("bad")])
    keys = list(workbench.items)
    key_by_id = {item.flight_id: key for key, item in workbench.items.items()}
    submitted = workbench.submit(keys)
    workbench.match_tasks.executor.shutdown(wait=True)

    assert workbench.results[key_by_id["good"]].status == "success"
    assert workbench.results[key_by_id["bad"]].status == "failed"
    assert workbench.results[key_by_id["bad"]].error == "no candidate"
    status = workbench.task_status([submitted["task_id"]])
    progress = status["tasks"][0]
    assert (progress["total"], progress["success"], progress["failed"]) == (2, 1, 1)
    assert progress["complete"] is True
    assert status["progress"]["summary"] == progress["summary"]
    assert progress["summary"]["success_rate"] == 0.5
    assert progress["summary"]["failure_counts"] == {"no_candidates": 1}


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
                raise MapMatchingError(MapMatchingFailure.NO_LEGAL_PATH, "first attempt failed")
            return object()

    class InlineExecutor:
        def submit(self, function: object, *args: object) -> None:
            function(*args)  # type: ignore[operator]

    monkeypatch.setattr("airport_workbench.flight_match_tasks.Matcher", FakeMatcher)
    workbench = FlightWorkbench(SmallGraph(), [flight("retry")])
    workbench.match_tasks.executor.shutdown(wait=True)
    workbench.match_tasks.executor = InlineExecutor()  # type: ignore[assignment]
    key = next(iter(workbench.items))

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
    assert workbench.task_status([first["task_id"]])["tasks"][0] == first_before_retry
    preserved_second = workbench.task_status([second["task_id"]])["tasks"][0]
    assert preserved_second["success"] == 1
    assert preserved_second["complete"] is True


def test_batch_rejects_unknown_atomically_and_reports_skip_reasons() -> None:
    workbench = FlightWorkbench(SmallGraph(), [flight("one"), flight("two")])
    first, second = workbench.items

    with pytest.raises(KeyError, match="flight_key"):
        workbench.submit([first, "missing", second])
    assert all(result.status == "unmatched" for result in workbench.results.values())

    workbench.results[first].status = "matching"
    workbench.results[second].status = "success"
    workbench.results[second].graph_id = workbench.match_tasks.graph_id
    workbench.results[second].config = asdict(workbench.match_config)
    result = workbench.submit([first, second])

    assert result["queued_count"] == 0
    assert result["skipped"] == [
        {"flight_key": first, "reason": "already_running"},
        {"flight_key": second, "reason": "current_success"},
    ]


def test_observation_detail_is_paginated_and_can_expand_fields() -> None:
    item = flight_with_points("many", 205)
    item = Flight({**row, "aircraft_type": "A320"} for row in item.rows)
    workbench = FlightWorkbench(SmallGraph(), [item])
    key = next(iter(workbench.items))

    second = workbench.detail(key, observation_page=2)
    expanded = workbench.detail(key, observation_page=3, all_fields=True)

    assert len(second["observations"]) == 100
    assert second["observations"][0]["record_index"] == 101
    assert "aircraft_type" not in second["observation_columns"]
    assert len(expanded["observations"]) == 5
    assert "aircraft_type" in expanded["observation_columns"]


def test_real_path_and_nan_fields_serialize_through_all_endpoints(monkeypatch) -> None:
    from threading import Event
    from time import sleep

    projection = Proj("EPSG:32650")
    to_wgs84 = Transformer.from_proj(projection, "EPSG:4326", always_xy=True)
    a, b = to_wgs84.transform(450_000.0, 4_428_000.0), to_wgs84.transform(450_010.0, 4_428_000.0)
    graph = nx.MultiGraph()
    graph.add_node("1", pos=a)
    graph.add_node("2", pos=b)
    graph.add_edge("1", "2", key=0, geometry=LineString([a, b]))
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
    key = database_flight_key("departure", item.flight_id)
    store = _flight_database_factory([item], ["departure"])
    matched = Event()

    class FakeMatcher:
        def __init__(self, graph, _config):
            self.graph = graph

        def map_flight(self, _flight):
            matched.set()
            return Path(self.graph, [("1", "2", 0)])

    monkeypatch.setattr("airport_workbench.flight_match_tasks.Matcher", FakeMatcher)
    app = create_app(EditorSession(airport_graph), flight_database=store)

    with TestClient(app) as client:
        statuses = client.get("/api/matches").json()
        first = client.post("/api/matches", json={"flight_keys": [key]}).json()
        assert matched.wait(5)
        for _ in range(100):
            catalogue = client.get("/api/flights").json()
            if catalogue["items"][0]["match"]["status"] == "success":
                break
            sleep(0.01)
        detail = client.get(f"/api/flights/{key}").json()
        geometry = client.get(f"/api/flights/{key}/geometry").json()
        client.post("/api/matches", json={"flight_keys": [key]}).raise_for_status()
        filtered = client.get("/api/matches", params={"task_id": first["task_id"]}).json()
        assert [task["task_id"] for task in filtered["tasks"]] == [first["task_id"]]

    assert catalogue["items"][0]["flight_number"] == "CCA123"
    assert catalogue["items"][0]["match"]["status"] == "success"
    assert detail["fields"]["optional"] is None
    assert geometry["path"]["features"]
    assert geometry["flight"]["features"][1]["properties"]["optional"] is None
    assert statuses["tasks"] == []
    assert geometry["match"]["has_path"] is True
    json.dumps([catalogue, detail, geometry, statuses], allow_nan=False)


def test_duckdb_workbench_reads_full_catalogue_and_filters_in_beijing(tmp_path):
    from datetime import date

    from flight.flight_catalogue_repository import BEIJING
    from flight.flight_repository import FlightDatabase, database_flight_key

    duckdb = pytest.importorskip("duckdb")
    database = tmp_path / "catalogue.duckdb"
    with duckdb.connect(str(database)) as connection:
        for movement, stand_column in (
            ("arr", "arr_stand_position"),
            ("dep", "dep_stand_position"),
        ):
            connection.execute(f"""
                CREATE TABLE adsb_202406_{movement} (
                    flight_id VARCHAR, "NUMBER" VARCHAR, timestamp TIMESTAMP,
                    longitude DOUBLE, latitude DOUBLE,
                    {stand_column} VARCHAR CHECK ({stand_column} <> 'invalid')
                );
                INSERT INTO adsb_202406_{movement} VALUES
                    ('same', 'CA1', '2024-06-15 00:05:00', 116.0, 40.0, NULL),
                    ('same', 'CA1', '2024-06-15 00:06:00', 116.1, 40.0, NULL);
            """)

    store = FlightDatabase(database)
    workbench = FlightWorkbench(
        SmallGraph(),
        flight_database=store,
        display_timezone=BEIJING,
        input_time_semantics=BEIJING,
    )
    arrival = database_flight_key("arrival", "same")
    departure = database_flight_key("departure", "same")
    criteria = {"start_date": date(2024, 6, 15), "end_date": date(2024, 6, 15), "stands": [""]}
    assert workbench.catalogue(FlightFilter(**criteria))["total"] == 2
    assert workbench.catalogue(FlightFilter(end_date=date(2024, 6, 14)))["total"] == 0
    assert (
        workbench.catalogue(FlightFilter(movement_type="arrival"))["items"][0]["flight_key"]
        == arrival
    )
    detail = workbench.detail(arrival, observation_page=2, observation_page_size=1)
    assert detail["summary"]["start_time"] == "2024-06-15T00:05:00+08:00"
    assert detail["observations"][0]["timestamp"] == "2024-06-14T16:06:00+00:00"
    assert detail["observations"][0]["record_index"] == 2
    assert detail["observation_total"] == 2
    assert len(workbench.geometry(arrival)["flight"]["features"]) == 3

    with pytest.raises(RuntimeError, match="事务失败"):
        workbench.update_stand(arrival, "invalid")
    assert workbench.filtered_keys(FlightFilter(**criteria))["count"] == 2
    workbench.update_stand(arrival, "009")
    assert workbench.filtered_keys(FlightFilter(**criteria))["flight_keys"] == [departure]
    assert workbench.detail(arrival)["fields"]["arr_stand_position"] == "009"
    assert workbench.detail(departure)["fields"]["dep_stand_position"] is None
    assert [flight.point_count for flight in store.observations.iterate("arrival", None)] == [2]
    assert list(store.observations.iterate("arrival", 0)) == []

    with duckdb.connect(str(database), read_only=True) as db:
        assert db.execute(
            "SELECT arr_stand_position FROM adsb_202406_arr ORDER BY timestamp"
        ).fetchall() == [("009",), ("009",)]
    restarted = FlightWorkbench(SmallGraph(), flight_database=store)
    assert restarted.detail(arrival)["fields"]["arr_stand_position"] == "009"

    graph = SmallGraph().graph
    graph.add_node("2", pos=(116.001, 40.001))
    graph.add_edge("1", "2", geometry=LineString([(116.0, 40.0), (116.001, 40.001)]))
    editor = EditorSession(AirportGraph(graph, Proj("EPSG:32650")))
    with TestClient(create_app(editor, flight_database=store)) as client:
        response = client.patch(f"/api/flights/{arrival}/stand", json={"stand_position": None})
        assert response.status_code == 204
        assert client.get("/api/flight-selection", params={"stands": ""}).json()["count"] == 2
        assert client.get(f"/api/flights/{arrival}").json()["fields"]["arr_stand_position"] is None


def test_validation_flights_filter_counts_only_eligible_observations(tmp_path):
    from flight.flight_repository import FlightDatabase, database_flight_key

    duckdb = pytest.importorskip("duckdb")
    database = tmp_path / "validation.duckdb"
    with duckdb.connect(str(database)) as connection:
        for suffix, stand, runway in (
            ("dep", "dep_stand_position", "org_runway"),
            ("arr", "arr_stand_position", "dst_runway"),
        ):
            table = f"adsb_202406_{suffix}"
            connection.execute(f"""
                CREATE TABLE {table} AS
                SELECT flight_id, flight_id AS "NUMBER",
                       TIMESTAMP '2024-06-15 00:05:00' AS timestamp,
                       116.0 AS longitude, 40.0 AS latitude,
                       stand AS {stand}, runway AS {runway}
                FROM (VALUES ('eligible', '009', '01', 30),
                             ('eligible', '009', NULL, 4),
                             ('too-few', '009', '01', 29),
                             ('too-few', '009', NULL, 10),
                             ('excluded', '952L', '01', 40))
                     AS cases(flight_id, stand, runway, points),
                     range(points)
            """)
    store = FlightDatabase(database)
    assert store.catalogue.validation_flights() == [
        dict(
            flight_id="eligible", movement=movement, stand="009", flight_points=30, total_flights=2
        )
        for movement in ("arr", "dep")
    ]
    assert store.catalogue.validation_flights(31) == []
    workbench = FlightWorkbench(SmallGraph(), flight_database=store)
    assert workbench.catalogue(FlightFilter(validation_only=True))["total"] == 2
    assert workbench.filtered_keys(FlightFilter(validation_only=True, movement_type="departure"))[
        "flight_keys"
    ] == [database_flight_key("departure", "eligible")]


def test_close_finishes_current_flight_and_cancels_queued_work(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    started, release, closing = Event(), Event(), Event()
    calls = []

    class BlockingMatcher:
        def __init__(self, _graph, _config):
            pass

        def map_flight(self, item):
            calls.append(item.flight_id)
            started.set()
            if not release.wait(5):
                raise RuntimeError("test did not release matcher")
            return object()

    monkeypatch.setattr("airport_workbench.flight_match_tasks.Matcher", BlockingMatcher)
    workbench = FlightWorkbench(SmallGraph(), [flight("active"), flight("next"), flight("queued")])
    active, following, queued = workbench.items
    workbench.submit([active, following])
    workbench.submit([queued])
    shutdown = workbench.match_tasks.executor.shutdown

    def observe_shutdown(**options):
        closing.set()
        shutdown(**options)

    monkeypatch.setattr(workbench.match_tasks.executor, "shutdown", observe_shutdown)
    with ThreadPoolExecutor() as pool:
        try:
            assert started.wait(5)
            stopped = pool.submit(workbench.close)
            assert closing.wait(5)
            assert not stopped.done()
            with pytest.raises(ValueError, match="正在关闭"):
                workbench.submit([queued])
        finally:
            release.set()
        stopped.result(timeout=5)

    assert calls == ["active"]
    assert [workbench.results[key].status for key in workbench.items] == [
        "success",
        "failed",
        "failed",
    ]
