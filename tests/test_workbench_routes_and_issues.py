"""Focused tests for workbench route library, match issues, and slim polling."""

from __future__ import annotations

import networkx as nx
import pandas as pd
from fastapi.testclient import TestClient
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import AirportGraph
from airport_workbench.app import create_app
from airport_workbench.editor import EditorSession
from airport_workbench.flights import FlightFilter, FlightWorkbench
from flight import Flight
from path_map import Path
from route_library import RouteEntry, RouteLibraryRepository, RouteStatus
from tests.flight_database_fixture import create_flight_database


def _mini_graph() -> AirportGraph:
    graph = nx.MultiGraph()
    graph.add_node("1", pos=(116.59, 40.07))
    graph.add_node("2", pos=(116.595, 40.07))
    graph.add_node("3", pos=(116.60, 40.07))
    graph.add_edge(
        "1",
        "2",
        key=0,
        geometry=LineString([(116.59, 40.07), (116.595, 40.07)]),
        aeroway="parking_position",
        ref="009",
    )
    graph.add_edge(
        "2",
        "3",
        key=0,
        geometry=LineString([(116.595, 40.07), (116.60, 40.07)]),
        aeroway="taxiway",
    )
    return AirportGraph(graph, Proj("EPSG:32650"))


def _single_flight_db():
    sample = Flight(
        pd.DataFrame(
            {
                "flight_id": ["F1"],
                "number": ["CA1"],
                "timestamp": ["2024-06-15 00:05:00+08:00"],
                "longitude": [116.59],
                "latitude": [40.07],
                "dep_stand_position": ["009"],
                "org_runway": ["01"],
            }
        ),
        movement="departure",
    )
    return create_flight_database([sample], movement_types=["departure"])


def test_route_library_endpoints_list_geometry_review_and_import():
    airport_graph = _mini_graph()
    store = _single_flight_db()
    routes = RouteLibraryRepository(store.postgres)
    app = create_app(EditorSession(airport_graph), flight_database=store)

    with TestClient(app) as client:
        empty = client.get("/api/routes").json()
        assert empty["has_route_library"] is True
        assert empty["items"] == []

        entry = RouteEntry.from_path(
            airport_graph,
            Path(airport_graph, [("1", "2", 0), ("2", "3", 0)]),
            movement="departure",
            stand_ref="009",
            runway_ref="01",
        )
        routes.upsert_routes([entry])

        listed = client.get(
            "/api/routes",
            params={"movement": "departure", "stand_ref": "009"},
        ).json()
        assert listed["total"] == 1
        assert listed["status_counts"]["candidate"] == 1
        assert listed["items"][0]["route_id"] == entry.route_id
        assert listed["items"][0]["matches_current_graph"] is True

        geom = client.get(f"/api/routes/{entry.route_id}/geometry").json()
        assert geom["route"]["route_id"] == entry.route_id
        assert len(geom["path"]["features"]) == 2

        updated = client.patch(
            f"/api/routes/{entry.route_id}",
            json={"status": RouteStatus.VERIFIED.value, "note": "标准滑行路线"},
        ).json()
        assert updated["status"] == "verified"
        assert updated["note"] == "标准滑行路线"

        verified = client.get("/api/routes", params={"status": "verified"}).json()
        assert verified["total"] == 1
        assert verified["status_counts"]["verified"] == 1

        flight_key = client.get("/api/flights").json()["items"][0]["flight_key"]
        assert client.post("/api/matches", json={"flight_keys": [flight_key]}).status_code == 200
        for _ in range(100):
            res = client.get("/api/matches", params={"include_items": False}).json()
            progress = res["progress"]
            if progress["waiting"] == 0 and progress["running"] == 0:
                break
        imported = client.post(
            "/api/routes/import-matches",
            json={"flight_keys": [flight_key], "replace_candidates": False},
        )
        assert imported.status_code == 200
        assert imported.json()["graph_id"] == listed["current_graph_id"]


def test_route_coverage_endpoint_computes_fine_and_cluster_coverage():
    from airport_surface import StandCluster

    graph = nx.MultiGraph()
    graph.add_node("1", pos=(116.59, 40.07))
    graph.add_node("2", pos=(116.595, 40.07))
    graph.add_node("3", pos=(116.60, 40.07))
    graph.add_node("4", pos=(116.59, 40.075))
    graph.add_node("5", pos=(116.605, 40.07))
    graph.add_edge(
        "1", "2", key=0, geometry=LineString([(116.59, 40.07), (116.595, 40.07)]),
        aeroway="parking_position", ref="009",
    )
    graph.add_edge(
        "4", "2", key=0, geometry=LineString([(116.59, 40.075), (116.595, 40.07)]),
        aeroway="parking_position", ref="010",
    )
    graph.add_edge(
        "2", "3", key=0, geometry=LineString([(116.595, 40.07), (116.60, 40.07)]),
        aeroway="taxiway",
    )
    graph.add_edge(
        "3", "5", key=0, geometry=LineString([(116.60, 40.07), (116.605, 40.07)]),
        aeroway="runway", ref="01/19",
    )
    airport_graph = AirportGraph(
        graph,
        Proj("EPSG:32650"),
        stand_clusters=[StandCluster(c_id=1, stands=(("1", "2", 0), ("4", "2", 0)), name="A区")],
    )
    store = _single_flight_db()
    routes = RouteLibraryRepository(store.postgres)
    routes.upsert_routes(
        [
            RouteEntry.from_path(
                airport_graph,
                Path(airport_graph, [("1", "2", 0), ("2", "3", 0)]),
                movement="departure",
                stand_ref="009",
                runway_ref="01",
            ),
            RouteEntry.from_path(
                airport_graph,
                Path(airport_graph, [("3", "2", 0), ("2", "1", 0)]),
                movement="arrival",
                stand_ref="009",
                runway_ref="19",
                status=RouteStatus.REJECTED,
            ),
        ]
    )
    app = create_app(EditorSession(airport_graph), flight_database=store)
    with TestClient(app) as client:
        cov = client.get("/api/routes/coverage").json()
        # 2 stands ("009", "010") x 2 runways ("01", "19") x 2 movements = 8 total ODs
        assert cov["total_stands"] == 2
        assert cov["clustered_stands"] == 2
        assert cov["cluster_count"] == 1
        assert cov["total_runways"] == 2
        assert cov["covered_runways"] == 1
        assert cov["uncovered_runways"] == ["19"]
        assert cov["total_ods"] == 8
        assert cov["fine_covered_ods"] == 1
        assert cov["effective_covered_ods"] == 2
        assert cov["fine_covered_stands"] == 1
        assert cov["effective_covered_stands"] == 2
        assert cov["uncovered_stands"] == []


def test_route_anomaly_detection_flags_obvious_anomalies_without_false_positives():
    graph = nx.MultiGraph()
    graph.add_node("1", pos=(116.590, 40.070))
    graph.add_node("2", pos=(116.595, 40.070))
    graph.add_node("3", pos=(116.600, 40.070))
    graph.add_node("4", pos=(116.600, 40.075))
    graph.add_node("5", pos=(116.595, 40.075))
    graph.add_edge(
        "1", "2", key=0, geometry=LineString([(116.590, 40.070), (116.595, 40.070)]),
        aeroway="parking_position", ref="009",
    )
    graph.add_edge(
        "2", "3", key=0, geometry=LineString([(116.595, 40.070), (116.600, 40.070)]),
        aeroway="taxiway",
    )
    graph.add_edge(
        "3", "4", key=0, geometry=LineString([(116.600, 40.070), (116.600, 40.075)]),
        aeroway="taxiway",
    )
    graph.add_edge(
        "4", "5", key=0, geometry=LineString([(116.600, 40.075), (116.595, 40.075)]),
        aeroway="taxiway",
    )
    graph.add_edge(
        "5", "2", key=0, geometry=LineString([(116.595, 40.075), (116.595, 40.070)]),
        aeroway="taxiway",
    )
    airport_graph = AirportGraph(graph, Proj("EPSG:32650"))
    store = _single_flight_db()
    routes = RouteLibraryRepository(store.postgres)

    # Normal departure with a single pushback reversal on parking edge: MUST NOT be flagged
    normal_pushback = RouteEntry.from_path(
        airport_graph,
        Path(airport_graph, [("2", "1", 0), ("1", "2", 0), ("2", "3", 0)]),
        movement="departure",
        stand_ref="009",
        runway_ref="01",
        flight_count=10,
    )
    # Normal clean departure: MUST NOT be flagged
    normal_clean = RouteEntry.from_path(
        airport_graph,
        Path(airport_graph, [("1", "2", 0), ("2", "3", 0)]),
        movement="departure",
        stand_ref="009",
        runway_ref="01",
        flight_count=20,
    )
    # Obvious closed loop (2 -> 3 -> 4 -> 5 -> 2 -> 3): MUST be flagged
    loop_anomaly = RouteEntry.from_path(
        airport_graph,
        Path(
            airport_graph,
            [
                ("1", "2", 0),
                ("2", "3", 0),
                ("3", "4", 0),
                ("4", "5", 0),
                ("5", "2", 0),
                ("2", "3", 0),
            ],
        ),
        movement="departure",
        stand_ref="009",
        runway_ref="01",
        flight_count=1,
    )
    routes.upsert_routes([normal_clean, normal_pushback, loop_anomaly])

    app = create_app(EditorSession(airport_graph), flight_database=store)
    with TestClient(app) as client:
        res = client.post(
            "/api/routes/detect-anomalies",
            json={
                "route_ids": [
                    normal_clean.route_id,
                    normal_pushback.route_id,
                    loop_anomaly.route_id,
                ],
            },
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["checked_count"] == 3
        assert payload["anomalous_count"] == 1
        assert payload["items"][0]["route_id"] == loop_anomaly.route_id
        codes = {reason["code"] for reason in payload["items"][0]["reasons"]}
        assert "closed_loop" in codes
        assert "repeated_edge" in codes

        # Batch reject the detected anomaly
        rejected = client.post(
            "/api/routes/batch-review",
            json={
                "route_ids": [loop_anomaly.route_id],
                "status": "rejected",
                "note": "异常检测自动驳回",
            },
        )
        assert rejected.status_code == 200
        assert rejected.json()["updated_count"] == 1
        assert routes.get(loop_anomaly.route_id).status == RouteStatus.REJECTED


def test_match_issues_archive_filter_remove_and_slim_polling():
    airport_graph = _mini_graph()
    store = _single_flight_db()
    app = create_app(EditorSession(airport_graph), flight_database=store)

    with TestClient(app) as client:
        flight_key = client.get("/api/flights").json()["items"][0]["flight_key"]
        assert client.get("/api/match-issues").json() == {"flight_keys": [], "count": 0}

        added = client.post(
            "/api/match-issues",
            json={"flight_keys": [flight_key], "reason": "人工核查走偏"},
        ).json()
        assert added["inserted"] == 1
        assert added["issue_flight_keys"] == [flight_key]

        filtered = client.get("/api/flights", params={"issues_only": True}).json()
        assert filtered["total"] == 1
        assert filtered["issue_count"] == 1
        assert filtered["items"][0]["is_issue"] is True
        assert filtered["items"][0]["issue_reason"] == "人工核查走偏"

        removed = client.post(
            "/api/match-issues/remove",
            json={"flight_keys": [flight_key]},
        ).json()
        assert removed["deleted"] == 1
        assert removed["issue_flight_keys"] == []
        assert client.get("/api/flights", params={"issues_only": True}).json()["total"] == 0
        assert client.get("/api/flights").json()["total"] == 1

        client.post("/api/matches", json={"flight_keys": [flight_key]})
        slim_empty = client.get("/api/matches", params={"include_items": False}).json()
        assert slim_empty["progress"]["total"] == 1
        assert slim_empty["tasks"][0]["items"] == []
        slim_tracked = client.get(
            "/api/matches",
            params={"include_items": False, "flight_key": [flight_key]},
        ).json()
        assert [item["flight_key"] for item in slim_tracked["tasks"][0]["items"]] == [flight_key]


def test_import_matched_routes_reuses_graph_id_and_catalogue_avoids_rescan(monkeypatch):
    airport_graph = _mini_graph()
    store = _single_flight_db()
    workbench = FlightWorkbench(airport_graph, flight_database=store)
    flight_key = next(iter(workbench.items))

    # Catalogue refresh must filter in-memory items without re-scanning flights table.
    def fail_summaries(*_args, **_kwargs):
        raise AssertionError("catalogue() must not rescan flights table")

    monkeypatch.setattr(store.catalogue, "summaries", fail_summaries)
    refreshed = workbench.catalogue(FlightFilter(query="F1"))
    assert refreshed["total"] == 1
    assert refreshed["items"][0]["flight_key"] == flight_key

    # Route import must pass graph_identity=self.graph_id instead of re-hashing per flight.
    result = workbench.results[flight_key]
    result.status = "success"
    result.graph_id = workbench.match_tasks.graph_id
    result.path = Path(airport_graph, [("1", "2", 0), ("2", "3", 0)])
    result.stand_ref = "009"
    result.runway_ref = "01"

    def fail_graph_id(_graph):
        raise AssertionError("import_matched_routes() must reuse cached graph_id")

    monkeypatch.setattr("route_library.models.graph_id", fail_graph_id)
    summary = workbench.import_matched_routes([flight_key])
    assert summary["evaluated_flights"] == 1
    assert summary["unique_routes"] == 1
    assert summary["inserted_routes"] == 1
    assert summary["existing_routes"] == 0
    workbench.close()


def test_postgres_connection_uses_queue_pool():
    from sqlalchemy.pool import QueuePool

    store = _single_flight_db()
    try:
        assert isinstance(store.postgres._engine.pool, QueuePool)
    finally:
        store.close()
