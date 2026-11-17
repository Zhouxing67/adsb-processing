import json

import networkx as nx
import pytest
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import AirportGraph, graph_id, load_graph, save_graph
from airport_surface.graph import (
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
    graph.graph.add_node("stand", pos=(0.0005, 0), aeroway="parking_position")
    assert graph.graph.number_of_edges() == 2
    assert graph.graph.degree("stand") == 0
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


def test_workbench_portal_lock_save_unlock(tmp_path):
    from fastapi.testclient import TestClient

    from airport_workbench.app import create_app

    graph = topology()
    session = EditorSession(graph)
    path = tmp_path / "saved.json"
    with TestClient(create_app(session, path)) as client:
        state = client.get("/api/state").json()
        node = state["nodes"]["features"][0]["properties"]
        attributes = dict(
            node["editable_attributes"], node_type="group_portal", is_manual_lock=True
        )
        response = client.post(
            "/api/update-node",
            json={"node": node["id"], "attributes": attributes, "expected_revision": 0},
        )
        assert response.status_code == 200
        revision = response.json()["revision"]
        response = client.post("/api/save", json={"expected_revision": revision})
        assert response.status_code == 200
        saved = load_graph(path)
        assert any(
            d["node_type"] == "group_portal" and d["is_manual_lock"]
            for _, d in saved.graph.nodes(data=True)
        )
        attributes.update(is_manual_lock=False, node_type="unclassified")
        response = client.post(
            "/api/update-node",
            json={
                "node": node["id"],
                "attributes": attributes,
                "expected_revision": response.json()["revision"],
            },
        )
        assert response.status_code == 200
        assert (
            client.post(
                "/api/save", json={"expected_revision": response.json()["revision"]}
            ).status_code
            == 200
        )
        assert all(
            d["node_type"] != "group_portal" for _, d in load_graph(path).graph.nodes(data=True)
        )


def test_legacy_missing_semantic_fields(tmp_path):
    import json

    path = save_graph(topology(), tmp_path / "legacy.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    document.pop("graph_id")
    for item in document["nodes"] + document["edges"]:
        for field in ("node_type", "edge_zone", "stand_group_id", "is_manual_lock"):
            item["attributes"].pop(field, None)
    path.write_text(json.dumps(document), encoding="utf-8")
    graph = load_graph(path)
    assert all(not d["is_manual_lock"] for _, d in graph.graph.nodes(data=True))
    assert all(d["edge_zone"] == "backbone" for *_, d in graph.graph.edges(data=True))


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


def test_coordinate_transforms_preserve_linestring():
    graph = topology()
    line = LineString([(0, 0), (0.001, 0.001), (0.002, 0)])
    projected = graph.project_shape(line)
    restored = graph.to_wgs84_shape(projected)
    assert isinstance(projected, LineString)
    assert isinstance(restored, LineString)
    assert restored.equals_exact(line, tolerance=1e-12)


def test_old_collections_are_verified_then_ignored(tmp_path):
    from airport_surface.graph import _document_graph_id

    graph = nx.MultiGraph()
    graph.add_node(1, pos=(0, 0))
    path = save_graph(AirportGraph(graph, Proj("EPSG:3857")), tmp_path / "old.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    document["parking_position_nodes"] = [1, "obsolete-node"]
    document["runway_access_nodes"] = [1]
    document["graph_id"] = _document_graph_id(document)
    path.write_text(json.dumps(document), encoding="utf-8")
    loaded = load_graph(path)
    assert loaded.graph.nodes[1]["node_type"] == "unclassified"
    assert not hasattr(loaded, "parking_position_nodes")
    save_graph(loaded, tmp_path / "new.json")
    new = json.loads((tmp_path / "new.json").read_text(encoding="utf-8"))
    assert "parking_position_nodes" not in new
    assert "runway_access_nodes" not in new
    document["parking_position_nodes"] = []
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="graph_id"):
        load_graph(path)


def test_stored_groups_survive_without_algorithm(tmp_path):
    groups = ({"stand_group_id": "old", "entities": [], "diagnostics": ["historical"]},)
    graph = AirportGraph(nx.MultiGraph(), Proj("EPSG:3857"), stand_groups=groups)
    copied = graph.copy()
    copied.stand_groups[0]["entities"].append({"id": "new"})
    assert graph.stand_groups == groups
    assert load_graph(save_graph(graph, tmp_path / "graph.json")).stand_groups == groups


def test_node_attribute_edit_is_undoable_and_read_only_is_protected():
    from fastapi.testclient import TestClient

    from airport_workbench.app import create_app

    graph = nx.MultiGraph()
    graph.add_node(1, pos=(0, 0))
    session = EditorSession(AirportGraph(graph, Proj("EPSG:3857")))
    session.update_node_attributes(1, {"name": "reviewed"}, expected_revision=0)
    session.undo(expected_revision=1)
    assert "name" not in session.graph.nodes[1]
    with TestClient(create_app(session, read_only=True)) as client:
        response = client.post(
            "/api/update-node",
            json={
                "node": {"type": "int", "value": "1"},
                "attributes": {"name": "reviewed"},
                "expected_revision": 2,
            },
        )
    assert response.status_code == 405
