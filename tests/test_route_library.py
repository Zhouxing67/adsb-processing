from __future__ import annotations

import json

import networkx as nx
import pandas as pd
import pytest
from pyproj import Proj, Transformer
from shapely.geometry import LineString

from airport_surface import (
    AirportGraph,
    SourceEdge,
    SourceNode,
    SourceSegment,
    graph_id,
    save_graph,
)
from batch_matching import BatchMatchingRunner, DatabaseDataset
from flight import Flight, MovementType
from path_map import DirectedEdge, Path, PathGraphMismatch
from route_library import (
    RouteEntry,
    RouteLibraryRepository,
    RouteSource,
    RouteStatus,
    import_batch_run,
)
from tests.flight_database_fixture import create_flight_database


def _persisted_od_graph() -> tuple[AirportGraph, Transformer]:
    projection = Proj("EPSG:32650")
    to_wgs84 = Transformer.from_proj(projection, "EPSG:4326", always_xy=True)
    projected_positions = {
        "1": (450_000.0, 4_428_000.0),
        "2": (450_010.0, 4_428_000.0),
        "3": (450_020.0, 4_428_000.0),
        "5": (450_030.0, 4_428_000.0),
    }
    positions = {
        node: to_wgs84.transform(*position) for node, position in projected_positions.items()
    }
    graph = nx.MultiGraph()
    source_nodes: dict[str, SourceNode] = {}
    for node, position in positions.items():
        graph.add_node(node, pos=position)
        source_nodes[node] = SourceNode(node, position, (node,))

    source_edges: dict[str, SourceEdge] = {}
    edge_specs = (
        ("src_stand", "1", "2", 0, {"aeroway": "parking_position", "ref": "009"}),
        ("src_taxi", "2", "3", 1, {"aeroway": "taxiway"}),
        ("src_rwy", "3", "5", 0, {"aeroway": "runway", "ref": "01/19"}),
    )
    for source_id, u, v, key, attrs in edge_specs:
        line = LineString([positions[u], positions[v]])
        source_edges[source_id] = SourceEdge(
            source_id=source_id,
            geometry=line,
            source_type="manual",
            osm_node_ids=(u, v),
            attributes=attrs,
        )
        graph.add_edge(
            u,
            v,
            key=key,
            first=u,
            last=v,
            geometry=line,
            source_segments=(SourceSegment(source_id, 0.0, 10.0),),
            **attrs,
        )

    airport_graph = AirportGraph(
        graph,
        projection,
        source_nodes=source_nodes,
        source_edges=source_edges,
    )
    return airport_graph, to_wgs84


def _make_flight(
    flight_id: str,
    movement: str,
    xs: tuple[float, ...],
    to_wgs84: Transformer,
    *,
    stand_ref: str = "009",
    runway_ref: str | None = "01",
) -> Flight:
    points = [to_wgs84.transform(x, 4_428_000.0) for x in xs]
    data = {
        "flight_id": [flight_id] * len(points),
        "timestamp": pd.date_range("2026-01-01", periods=len(points), freq="5s", tz="UTC"),
        "longitude": [point[0] for point in points],
        "latitude": [point[1] for point in points],
    }
    if movement == "departure":
        data["dep_stand_position"] = stand_ref
        data["org_runway"] = runway_ref
    else:
        data["arr_stand_position"] = stand_ref
        data["dst_runway"] = runway_ref
    return Flight(pd.DataFrame(data), movement=movement)


def test_batch_matching_persists_od_and_imports_into_route_library(tmp_path):
    airport_graph, to_wgs84 = _persisted_od_graph()
    graph_path = tmp_path / "graph.json"
    save_graph(airport_graph, graph_path)
    expected_graph_id = graph_id(airport_graph)

    flights = [
        _make_flight(
            "DEP1", "departure", (450_001.0, 450_009.0, 450_019.0), to_wgs84, runway_ref="01"
        ),
        _make_flight(
            "DEP2", "departure", (450_002.0, 450_011.0, 450_018.0), to_wgs84, runway_ref="01"
        ),
        _make_flight(
            "DEP_NO_RWY",
            "departure",
            (450_001.0, 450_012.0, 450_019.0),
            to_wgs84,
            runway_ref=None,
        ),
        _make_flight(
            "ARR1", "arrival", (450_019.0, 450_011.0, 450_001.0), to_wgs84, runway_ref="01"
        ),
    ]
    database = create_flight_database(
        flights,
        movement_types=("departure", "departure", "departure", "arrival"),
    )

    output_dir = tmp_path / "outputs"
    datasets = (
        DatabaseDataset("arrival", MovementType.ARRIVAL, database),
        DatabaseDataset("departure", MovementType.DEPARTURE, database),
    )
    BatchMatchingRunner(graph_path, datasets, output_dir).run()

    run_dirs = [path for path in output_dir.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    # Verify matches.jsonl contains stand_ref and runway_ref.
    match_rows = [
        json.loads(line)
        for line in (run_dir / "matches.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    by_id = {row["flight_id"]: row for row in match_rows}
    assert by_id["DEP1"]["stand_ref"] == "009"
    assert by_id["DEP1"]["runway_ref"] == "01"
    assert by_id["DEP_NO_RWY"]["stand_ref"] == "009"
    assert by_id["DEP_NO_RWY"]["runway_ref"] == "01/19"
    assert by_id["ARR1"]["stand_ref"] == "009"
    assert by_id["ARR1"]["runway_ref"] == "01"

    # First import: 4 matched rows collapse to 3 unique OD routes (DEP1 & DEP2 share one).
    routes = RouteLibraryRepository(database.postgres)
    summary = import_batch_run(run_dir, routes)
    assert summary.graph_id == expected_graph_id
    assert summary.total_match_rows == 4
    assert summary.matched_rows == 4
    assert summary.skipped_missing_od == 0
    assert summary.unique_routes == 3
    assert summary.inserted_routes == 3
    assert summary.existing_routes == 0

    # Query by OD grouping key index.
    dep_01 = routes.find_by_od(
        graph_id=expected_graph_id,
        movement="departure",
        stand_ref="009",
        runway_ref="01",
    )
    assert len(dep_01) == 1
    assert dep_01[0].runway_interface_node == "3"
    assert dep_01[0].edge_count == 2
    assert dep_01[0].total_length_m == pytest.approx(20.0, abs=0.1)
    assert dep_01[0].resolve(airport_graph).edge_ids == (("1", "2", 0), ("2", "3", 1))

    dep_inferred_rwy = routes.find_by_od(
        graph_id=expected_graph_id,
        movement="departure",
        stand_ref="009",
        runway_ref="01/19",
    )
    assert len(dep_inferred_rwy) == 1
    assert dep_inferred_rwy[0].runway_ref == "01/19"

    arr_01 = routes.find_by_od(
        graph_id=expected_graph_id,
        movement="arrival",
        stand_ref="009",
        runway_ref="01",
    )
    assert len(arr_01) == 1
    assert arr_01[0].runway_interface_node == "3"
    assert arr_01[0].resolve(airport_graph).edge_ids == (("3", "2", 1), ("2", "1", 0))

    # Update review status and verify default re-import replaces candidates
    # while preserving verified routes and their notes.
    updated = routes.update_status(
        dep_01[0].route_id, RouteStatus.VERIFIED, note="Confirmed standard taxi route"
    )
    assert updated.status == RouteStatus.VERIFIED
    assert updated.note == "Confirmed standard taxi route"

    # Default mode: 2 candidates replaced, 1 verified preserved.
    second_summary = import_batch_run(run_dir, routes)
    assert second_summary.deleted_candidates == 2
    assert second_summary.inserted_routes == 2
    assert second_summary.existing_routes == 1

    # Append mode: nothing deleted, all 3 existing skipped.
    append_summary = import_batch_run(run_dir, routes, replace_candidates=False)
    assert append_summary.deleted_candidates == 0
    assert append_summary.inserted_routes == 0
    assert append_summary.existing_routes == 3

    fetched = routes.get(dep_01[0].route_id)
    assert fetched is not None
    assert fetched.status == RouteStatus.VERIFIED
    assert fetched.note == "Confirmed standard taxi route"

    verified_only = routes.find_by_od(
        graph_id=expected_graph_id,
        status=RouteStatus.VERIFIED,
    )
    assert [entry.route_id for entry in verified_only] == [dep_01[0].route_id]

    assert routes.delete(dep_inferred_rwy[0].route_id) is True
    assert routes.get(dep_inferred_rwy[0].route_id) is None
    assert routes.delete(dep_inferred_rwy[0].route_id) is False


def test_runway_ref_required_and_enforced_by_database(tmp_path):
    airport_graph, to_wgs84 = _persisted_od_graph()
    path = Path(airport_graph, (DirectedEdge("1", "2", 0), DirectedEdge("2", "3", 1)))

    with pytest.raises(ValueError, match="runway_ref"):
        RouteEntry.from_path(
            airport_graph,
            path,
            movement="departure",
            stand_ref="009",
            runway_ref="   ",
        )

    # PostgreSQL schema itself enforces NOT NULL and non-blank CHECK on runway_ref.
    flight = _make_flight(
        "DEP1", "departure", (450_001.0, 450_009.0, 450_019.0), to_wgs84, runway_ref="01"
    )
    database = create_flight_database([flight], movement_types=("departure",))
    with pytest.raises(database.database_error):
        with database.postgres.connection(write=True) as conn:
            conn.execute(
                """
                INSERT INTO public.route_library (
                    route_id, graph_id, movement, stand_ref, runway_ref,
                    runway_interface_node, edges_json, edge_count, total_length_m
                ) VALUES (
                    'r-null-test', 'g1', 'departure', '009', NULL,
                    '3', '[["1","2",0]]', 1, 10.0
                )
                """
            )
    with pytest.raises(database.database_error):
        with database.postgres.connection(write=True) as conn:
            conn.execute(
                """
                INSERT INTO public.route_library (
                    route_id, graph_id, movement, stand_ref, runway_ref,
                    runway_interface_node, edges_json, edge_count, total_length_m
                ) VALUES (
                    'r-blank-test', 'g1', 'departure', '009', '   ',
                    '3', '[["1","2",0]]', 1, 10.0
                )
                """
            )


def test_import_skips_legacy_match_rows_without_stand_ref(tmp_path):
    airport_graph, to_wgs84 = _persisted_od_graph()
    graph_path = tmp_path / "graph.json"
    save_graph(airport_graph, graph_path)

    flights = [
        _make_flight(
            "DEP1", "departure", (450_001.0, 450_009.0, 450_019.0), to_wgs84, runway_ref="01"
        ),
    ]
    database = create_flight_database(
        flights,
        movement_types=("departure",),
    )

    output_dir = tmp_path / "outputs"
    BatchMatchingRunner(
        graph_path,
        (DatabaseDataset("departure", MovementType.DEPARTURE, database),),
        output_dir,
    ).run()
    run_dir = next(path for path in output_dir.iterdir() if path.is_dir())

    # Strip stand_ref to simulate a legacy matches.jsonl file.
    matches_file = run_dir / "matches.jsonl"
    legacy_rows = []
    for line in matches_file.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        row.pop("stand_ref", None)
        legacy_rows.append(json.dumps(row))
    matches_file.write_text("\n".join(legacy_rows) + "\n", encoding="utf-8")

    routes = RouteLibraryRepository(database.postgres)
    summary = import_batch_run(run_dir, routes)
    assert summary.matched_rows == 1
    assert summary.skipped_missing_od == 1
    assert summary.unique_routes == 0
    assert summary.deleted_candidates == 0
    assert summary.inserted_routes == 0


def test_replace_candidates_only_clears_same_graph_candidates(tmp_path):
    airport_graph, to_wgs84 = _persisted_od_graph()
    graph_path = tmp_path / "graph.json"
    save_graph(airport_graph, graph_path)
    expected_graph_id = graph_id(airport_graph)

    flights = [
        _make_flight(
            "DEP1", "departure", (450_001.0, 450_009.0, 450_019.0), to_wgs84, runway_ref="01"
        ),
    ]
    database = create_flight_database(
        flights,
        movement_types=("departure",),
    )
    output_dir = tmp_path / "outputs"
    BatchMatchingRunner(
        graph_path,
        (DatabaseDataset("departure", MovementType.DEPARTURE, database),),
        output_dir,
    ).run()
    run_dir = next(path for path in output_dir.iterdir() if path.is_dir())

    # Seed stale candidate (same graph), manual route (same graph), and other-graph candidate.
    routes = RouteLibraryRepository(database.postgres)
    first_summary = import_batch_run(run_dir, routes)
    assert first_summary.inserted_routes == 1
    base_entry = routes.find_by_od(graph_id=expected_graph_id)[0]
    base_path = base_entry.resolve(airport_graph)

    stale_candidate = RouteEntry.from_path(
        airport_graph,
        base_path,
        movement="departure",
        stand_ref="009",
        runway_ref="19",
        graph_identity=expected_graph_id,
        status=RouteStatus.CANDIDATE,
    )
    manual_entry = RouteEntry.from_path(
        airport_graph,
        base_path,
        movement="departure",
        stand_ref="010",
        runway_ref="01",
        graph_identity=expected_graph_id,
        status=RouteStatus.MANUAL,
        source=RouteSource.MANUAL,
        note="Hand-drawn",
    )
    other_graph_candidate = RouteEntry.from_path(
        airport_graph,
        base_path,
        movement="departure",
        stand_ref="009",
        runway_ref="01",
        graph_identity="other-graph-id",
        status=RouteStatus.CANDIDATE,
    )
    routes.upsert_routes([stale_candidate, manual_entry, other_graph_candidate])

    routes = RouteLibraryRepository(database.postgres)
    summary = import_batch_run(run_dir, routes)
    # Both same-graph candidates (base_entry + stale_candidate) were deleted; only base_entry
    # is re-inserted from run_dir.
    assert summary.deleted_candidates == 2
    assert summary.inserted_routes == 1
    assert routes.get(stale_candidate.route_id) is None
    assert routes.get(manual_entry.route_id) is not None
    assert routes.get(other_graph_candidate.route_id) is not None


def test_route_entry_resolve_accepts_precomputed_graph_id_without_rehashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    airport_graph, _ = _persisted_od_graph()
    path = Path(airport_graph, (DirectedEdge("1", "2", 0), DirectedEdge("2", "3", 1)))
    expected_graph_id = graph_id(airport_graph)
    entry = RouteEntry.from_path(
        airport_graph,
        path,
        movement="departure",
        stand_ref="009",
        runway_ref="01",
        graph_identity=expected_graph_id,
    )

    def _boom(_graph: AirportGraph) -> str:
        raise AssertionError("graph_id() must not be recomputed when actual_graph_id is supplied")

    monkeypatch.setattr("path_map.path.graph_id", _boom)

    resolved = entry.resolve(airport_graph, actual_graph_id=expected_graph_id)
    assert resolved.edges == path.edges

    with pytest.raises(PathGraphMismatch):
        entry.resolve(airport_graph, actual_graph_id="sha256:different")


def test_flight_count_is_idempotent_and_historical_lookup_falls_back_to_cluster(tmp_path):
    from airport_surface import StandCluster
    from route_library import find_historical_routes, get_his_path

    airport_graph, to_wgs84 = _persisted_od_graph()
    # Add a second stand "010" grouped in the same cluster as "009"
    pos_4 = to_wgs84.transform(450_000.0, 4_428_010.0)
    airport_graph.graph.add_node("4", pos=pos_4)
    airport_graph.source_nodes["4"] = SourceNode("4", pos_4, ("4",))
    stand_010_line = LineString([pos_4, airport_graph.graph.nodes["2"]["pos"]])
    airport_graph.source_edges["src_stand_010"] = SourceEdge(
        source_id="src_stand_010",
        geometry=stand_010_line,
        source_type="manual",
        osm_node_ids=("4", "2"),
        attributes={"aeroway": "parking_position", "ref": "010"},
    )
    airport_graph.graph.add_edge(
        "4",
        "2",
        key=0,
        first="4",
        last="2",
        geometry=stand_010_line,
        source_segments=(SourceSegment("src_stand_010", 0.0, 10.0),),
        aeroway="parking_position",
        ref="010",
    )
    airport_graph.stand_clusters = {
        1: StandCluster(c_id=1, stands=(("1", "2", 0), ("4", "2", 0)), name="Gate A")
    }
    airport_graph.rebuild_stand_index()
    airport_graph.rebuild_cluster_index()

    graph_path = tmp_path / "graph.json"
    save_graph(airport_graph, graph_path)
    expected_graph_id = graph_id(airport_graph)

    flights = [
        _make_flight(
            "DEP1",
            "departure",
            (450_001.0, 450_009.0, 450_019.0),
            to_wgs84,
            stand_ref="009",
            runway_ref="01",
        ),
        _make_flight(
            "DEP2",
            "departure",
            (450_002.0, 450_011.0, 450_018.0),
            to_wgs84,
            stand_ref="009",
            runway_ref="01",
        ),
    ]
    database = create_flight_database(flights, movement_types=("departure", "departure"))
    output_dir = tmp_path / "outputs"
    BatchMatchingRunner(
        graph_path,
        (DatabaseDataset("departure", MovementType.DEPARTURE, database),),
        output_dir,
    ).run()
    run_dir = next(path for path in output_dir.iterdir() if path.is_dir())

    routes = RouteLibraryRepository(database.postgres)
    import_batch_run(run_dir, routes)
    # Re-importing with append must keep flight_count strictly idempotent at 2.
    import_batch_run(run_dir, routes, replace_candidates=False)

    fine = find_historical_routes(
        routes,
        airport_graph,
        movement="departure",
        stand_ref="009",
        runway_ref="01",
        graph_identity=expected_graph_id,
    )
    assert fine.granularity == "stand"
    assert fine.cluster_id == 1
    assert len(fine.entries) == 1
    assert fine.entries[0].flight_count == 2
    assert routes.list_flight_ids(fine.entries[0].route_id) == ["DEP1", "DEP2"]

    # Stand "010" has no historical routes of its own -> falls back to cluster 1 ("009").
    coarse = find_historical_routes(
        routes,
        airport_graph,
        movement="departure",
        stand_ref="010",
        runway_ref="01/19",
        graph_identity=expected_graph_id,
    )
    assert coarse.granularity == "cluster"
    assert coarse.cluster_id == 1
    assert len(coarse.entries) == 1
    assert coarse.entries[0].stand_ref == "009"

    # get_his_path works directly from a Flight object.
    probe_flight = _make_flight(
        "DEP_PROBE", "departure", (450_000.0, 450_010.0), to_wgs84, stand_ref="010", runway_ref="01"
    )
    paths = get_his_path(probe_flight, airport_graph, routes, graph_identity=expected_graph_id)
    assert len(paths) == 1
    assert paths[0].edge_ids == (("1", "2", 0), ("2", "3", 1))
