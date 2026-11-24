"""Focused tests for workbench whitelist, route library, match issues, and slim polling."""

from __future__ import annotations

import networkx as nx
import pytest
from fastapi.testclient import TestClient
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import AirportGraph
from airport_workbench.app import create_app
from airport_workbench.editor import EditorSession
from airport_workbench.flights import FlightFilter, FlightWorkbench
from db import apply_core_schema
from flight.flight_repository import FlightDatabase, database_flight_key
from path_map import Path
from route_library import RouteEntry, RouteLibraryRepository, RouteStatus


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


def _single_flight_db(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    database = tmp_path / "workbench.duckdb"
    with duckdb.connect(str(database)) as connection:
        apply_core_schema(connection)
        connection.execute("""
            INSERT INTO main.adsb_dep (
                flight_id, number, timestamp, longitude, latitude, dep_stand_position, org_runway
            ) VALUES
                ('F1', 'CA1', '2024-06-15 00:05:00', 116.59, 40.07, '009', '01');
        """)
    return FlightDatabase(database)


def test_whitelist_filter_handles_empty_and_populated_whitelist_table(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    database = tmp_path / "whitelist.duckdb"
    with duckdb.connect(str(database)) as connection:
        apply_core_schema(connection)
        for suffix, stand, runway in (
            ("dep", "dep_stand_position", "org_runway"),
            ("arr", "arr_stand_position", "dst_runway"),
        ):
            connection.execute(f"DROP TABLE main.adsb_{suffix}")
            connection.execute(f"""
                CREATE TABLE adsb_{suffix} AS
                SELECT flight_id, flight_id AS number,
                       TIMESTAMP '2024-06-15 00:05:00' AS timestamp,
                       116.0 AS longitude, 40.0 AS latitude,
                       '009' AS {stand}, '01' AS {runway}
                FROM (VALUES ('keep'), ('drop')) AS cases(flight_id), range(30)
            """)

    store = FlightDatabase(database)
    workbench = FlightWorkbench(_mini_graph(), flight_database=store)

    empty = workbench.catalogue(FlightFilter(whitelist_only=True))
    assert empty["supports_whitelist_filter"] is True
    assert empty["total"] == 0

    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "INSERT INTO main.flight_whitelist VALUES ('departure', 'keep', '009', '01')"
        )

    populated = workbench.catalogue(FlightFilter(whitelist_only=True))
    assert populated["total"] == 1
    assert populated["items"][0]["flight_key"] == database_flight_key("departure", "keep")
    assert workbench.filtered_keys(FlightFilter(whitelist_only=True, validation_only=True)) == {
        "flight_keys": [database_flight_key("departure", "keep")],
        "count": 1,
    }


def test_route_library_endpoints_list_geometry_review_and_import(tmp_path):
    airport_graph = _mini_graph()
    store = _single_flight_db(tmp_path)
    routes = RouteLibraryRepository(store.duckdb)
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


def test_match_issues_archive_filter_remove_and_slim_polling(tmp_path):
    airport_graph = _mini_graph()
    store = _single_flight_db(tmp_path)
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


def test_import_matched_routes_reuses_graph_id_and_catalogue_avoids_rescan(tmp_path, monkeypatch):
    airport_graph = _mini_graph()
    store = _single_flight_db(tmp_path)
    workbench = FlightWorkbench(airport_graph, flight_database=store)
    flight_key = next(iter(workbench.items))

    # Catalogue refresh must filter in-memory items without re-scanning adsb_dep/adsb_arr.
    def fail_summaries(*_args, **_kwargs):
        raise AssertionError("catalogue() must not rescan raw ADS-B tables")

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


def test_quack_connection_uses_queue_pool_while_local_file_uses_null_pool(tmp_path):
    from sqlalchemy.pool import NullPool, QueuePool

    from db import DuckDBConnection

    store = _single_flight_db(tmp_path)
    assert isinstance(store.duckdb._engine.pool, NullPool)
    store.close()

    quack_conn = DuckDBConnection(
        tmp_path / "workbench.duckdb",
        read_only=False,
        quack_uri="quack:127.0.0.1:9494",
    )
    assert isinstance(quack_conn._engine.pool, QueuePool)
    quack_conn.close()
