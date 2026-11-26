import json

import networkx as nx
import pytest
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import (
    AirportGraph,
    graph_id,
    load_graph,
    save_graph,
    validate_edge_sources,
    validate_source_intervals,
)
from airport_surface.traffic_builder import (
    _build_derived_graph,
    _canonicalize_source_nodes,
    _extract_sources,
)
from airport_workbench import EditorSession


def topology():
    raw = nx.MultiGraph()
    raw.add_edge(1, 2, geometry=LineString([(0, 0), (0.002, 0)]), nodes=(1, 2), aeroway="runway")
    raw.add_edge(
        3,
        4,
        geometry=LineString([(0.001, -0.001), (0.001, 0.001)]),
        nodes=(3, 4),
        aeroway="taxiway",
    )
    sources, positions, issues = _extract_sources(raw)
    nodes, aliases = _canonicalize_source_nodes(positions)
    return _build_derived_graph(sources, nodes, aliases, Proj("EPSG:3857"), "TEST", issues)


def test_geometric_crossing_and_point_do_not_change_topology():
    graph = topology()
    original = {k: s.geometry.wkb for k, s in graph.source_edges.items()}
    graph.graph.add_node("-1", pos=(0.0005, 0), aeroway="parking_position")
    assert graph.graph.number_of_edges() == 2
    assert graph.graph.degree("-1") == 0
    validate_edge_sources(graph)
    validate_source_intervals(graph)
    assert original == {k: s.geometry.wkb for k, s in graph.source_edges.items()}
    before = graph_id(graph)
    assert graph_id(graph) == before


def test_save_failure_preserves_graph_and_revision(tmp_path, monkeypatch):
    graph = topology()
    session = EditorSession(graph)
    original = graph_id(session.airport_graph)
    with monkeypatch.context() as patch:

        def fail(*args):
            raise OSError("disk failure")

        patch.setattr("airport_workbench.editor.save_graph", fail)
        with pytest.raises(OSError):
            session.save(tmp_path / "graph.json", expected_revision=0)
    assert session.revision == 0 and graph_id(session.airport_graph) == original
    session.save(tmp_path / "graph.json", expected_revision=0)
    assert session.revision == 0 and session.topology_revision == 0
    session.save(tmp_path / "graph.json", expected_revision=0)
    assert session.revision == 0


def test_loader_rejects_non_line_source_geometry(tmp_path):
    import json

    path = save_graph(topology(), tmp_path / "invalid-source.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    document.pop("graph_id")
    source = next(iter(document["source_edges"].values()))
    source["geometry"] = {"type": "Point", "coordinates": [0, 0]}
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="requires LineString geometry, got Point"):
        load_graph(path)


def test_loader_rejects_schema_v1_without_implicit_migration(tmp_path):
    path = save_graph(topology(), tmp_path / "schema-v1.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schema_version"] = 1
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Unsupported airport graph schema version: 1; expected 2",
    ):
        load_graph(path)


def test_coordinate_transforms_preserve_linestring():
    graph = topology()
    line = LineString([(0, 0), (0.001, 0.001), (0.002, 0)])
    projected = graph.project_shape(line)
    restored = graph.to_wgs84_shape(projected)
    assert isinstance(projected, LineString)
    assert isinstance(restored, LineString)
    assert restored.equals_exact(line, tolerance=1e-12)


def test_old_collections_are_verified_then_ignored(tmp_path):
    from airport_surface.persistence import _document_graph_id

    graph = nx.MultiGraph()
    graph.add_node("1", pos=(0, 0))
    path = save_graph(AirportGraph(graph, Proj("EPSG:3857")), tmp_path / "old.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    document["parking_position_nodes"] = ["1", "obsolete-node"]
    document["runway_access_nodes"] = ["1"]
    document["graph_id"] = _document_graph_id(document)
    path.write_text(json.dumps(document), encoding="utf-8")
    loaded = load_graph(path)
    assert loaded.graph.nodes["1"]["pos"] == (0, 0)
    assert not hasattr(loaded, "parking_position_nodes")
    save_graph(loaded, tmp_path / "new.json")
    new = json.loads((tmp_path / "new.json").read_text(encoding="utf-8"))
    assert "parking_position_nodes" not in new
    assert "runway_access_nodes" not in new
    document["parking_position_nodes"] = []
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="graph_id"):
        load_graph(path)


def test_node_attribute_edit_is_undoable_and_read_only_is_protected(
    flight_samples, flight_database_factory
):
    from fastapi.testclient import TestClient

    from airport_workbench.app import create_app

    graph = nx.MultiGraph()
    graph.add_node("1", pos=(0, 0))
    graph.add_node("2", pos=(0.001, 0))
    graph.add_edge("1", "2", geometry=LineString([(0, 0), (0.001, 0)]))
    session = EditorSession(AirportGraph(graph, Proj("EPSG:3857")))
    session.update_node_attributes("1", {"name": "reviewed"}, expected_revision=0)
    session.undo(expected_revision=1)
    assert "name" not in session.graph.nodes["1"]
    with TestClient(
        create_app(session, flight_database=flight_database_factory(flight_samples))
    ) as client:
        response = client.post(
            "/api/update-node",
            json={
                "node": "1",
                "attributes": {"name": "reviewed"},
                "expected_revision": 2,
            },
        )
    assert response.status_code == 405


def test_stand_clusters_persist_without_changing_graph_id(tmp_path):
    from airport_surface import StandCluster

    graph = nx.MultiGraph()
    graph.add_node("1", pos=(0.0, 0.0))
    graph.add_node("2", pos=(0.001, 0.0))
    graph.add_node("3", pos=(0.002, 0.0))
    graph.add_edge(
        "1",
        "2",
        key=0,
        geometry=LineString([(0.0, 0.0), (0.001, 0.0)]),
        aeroway="parking_position",
        ref="201",
    )
    graph.add_edge(
        "2",
        "3",
        key=0,
        geometry=LineString([(0.001, 0.0), (0.002, 0.0)]),
        aeroway="parking_position",
        ref="202",
    )
    base_graph = AirportGraph(graph, Proj("EPSG:3857"))
    base_id = graph_id(base_graph)

    clustered_graph = AirportGraph(
        graph.copy(),
        Proj("EPSG:3857"),
        stand_clusters=[StandCluster(c_id=1, stands=(("1", "2", 0), ("2", "3", 0)), name="T3西侧")],
    )
    assert graph_id(clustered_graph) == base_id

    path = save_graph(clustered_graph, tmp_path / "clustered.json")
    loaded = load_graph(path)
    assert graph_id(loaded) == base_id
    assert loaded.cluster_for_edge(("2", "1", 0)) == StandCluster(
        c_id=1, stands=(("1", "2", 0), ("2", "3", 0)), name="T3西侧"
    )
    assert loaded.cluster_for_stand("201") is not None
    assert loaded.cluster_for_stand("201").c_id == 1
    assert loaded.stand_refs_in_cluster(1) == ("201", "202")
    assert loaded.next_cluster_id() == 2


def test_workbench_stand_cluster_endpoints_and_undo():
    from fastapi.testclient import TestClient

    from airport_workbench.app import create_app

    graph = nx.MultiGraph()
    graph.add_node("1", pos=(0.0, 0.0))
    graph.add_node("2", pos=(0.001, 0.0))
    graph.add_node("3", pos=(0.002, 0.0))
    graph.add_node("4", pos=(0.003, 0.0))
    graph.add_edge(
        "1", "2", key=0, geometry=LineString([(0.0, 0.0), (0.001, 0.0)]),
        aeroway="parking_position", ref="201",
    )
    graph.add_edge(
        "2", "3", key=0, geometry=LineString([(0.001, 0.0), (0.002, 0.0)]),
        aeroway="parking_position", ref="202",
    )
    graph.add_edge(
        "3", "4", key=0, geometry=LineString([(0.002, 0.0), (0.003, 0.0)]),
        aeroway="taxiway",
    )
    session = EditorSession(AirportGraph(graph, Proj("EPSG:3857")))
    with TestClient(create_app(session)) as client:
        # Non-parking edge must be rejected
        bad = client.post(
            "/api/stand-clusters/create",
            json={"edges": [{"u": "3", "v": "4", "key": 0}], "expected_revision": 0},
        )
        assert bad.status_code == 400

        # Create cluster #1 with edge 201
        created = client.post(
            "/api/stand-clusters/create",
            json={
                "edges": [{"u": "1", "v": "2", "key": 0}],
                "name": "北区",
                "expected_revision": 0,
            },
        )
        assert created.status_code == 200
        assert created.json()["revision"] == 1

        # Assign edge 202 to cluster #1
        assigned = client.post(
            "/api/stand-clusters/assign",
            json={
                "edges": [{"u": "2", "v": "3", "key": 0}],
                "c_id": 1,
                "expected_revision": 1,
            },
        )
        assert assigned.status_code == 200

        # Rename cluster #1
        renamed = client.post(
            "/api/stand-clusters/rename",
            json={"c_id": 1, "name": "北指廊", "expected_revision": 2},
        )
        assert renamed.status_code == 200

        state = client.get("/api/state").json()
        assert len(state["stand_clusters"]) == 1
        assert state["stand_clusters"][0]["name"] == "北指廊"
        assert state["stand_clusters"][0]["stand_refs"] == ["201", "202"]

        # Delete cluster #1 and undo
        deleted = client.post(
            "/api/stand-clusters/delete",
            json={"c_id": 1, "expected_revision": 3},
        )
        assert deleted.status_code == 200
        assert client.get("/api/state").json()["stand_clusters"] == []

        undone = client.post("/api/undo", json={"expected_revision": 4})
        assert undone.status_code == 200
        assert len(client.get("/api/state").json()["stand_clusters"]) == 1

        # Remove all stands from cluster #1, leaving it empty, then save -> empty cluster pruned.
        unassigned = client.post(
            "/api/stand-clusters/assign",
            json={
                "edges": [{"u": "1", "v": "2", "key": 0}, {"u": "2", "v": "3", "key": 0}],
                "c_id": None,
                "expected_revision": 5,
            },
        )
        assert unassigned.status_code == 200
        assert len(client.get("/api/state").json()["stand_clusters"]) == 1
        assert client.get("/api/state").json()["stand_clusters"][0]["stands"] == []

        session.airport_graph.prune_empty_clusters()
        assert session.airport_graph.stand_clusters == {}
