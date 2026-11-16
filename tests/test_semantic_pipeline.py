from copy import deepcopy

import networkx as nx
import pytest
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import enrich_airport_semantics, graph_id, load_graph, save_graph
from airport_surface.graph import (
    validate_edge_sources,
    validate_source_intervals,
)
from airport_surface.traffic_builder import (
    _build_derived_graph,
    _canonicalize_source_nodes,
    _extract_sources,
    complete_geometric_topology,
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


def test_crossing_and_point_split_preserve_sources():
    graph = topology()
    original = {k: s.geometry.wkb for k, s in graph.source_edges.items()}
    graph.graph.add_node("stand", pos=(0.0005, 0), aeroway="parking_position")
    complete_geometric_topology(graph)
    assert graph.graph.number_of_edges() == 5
    assert graph.graph.degree("stand") == 2
    validate_edge_sources(graph)
    validate_source_intervals(graph)
    assert original == {k: s.geometry.wkb for k, s in graph.source_edges.items()}
    before = graph_id(graph)
    complete_geometric_topology(graph)
    assert graph_id(graph) == before


def test_enrichment_is_independent_idempotent_and_locked(tmp_path):
    graph = topology()
    complete_geometric_topology(graph)
    graph.graph.nodes[1].update(
        node_type="group_portal", stand_group_id="manual", is_manual_lock=True, custom="retained"
    )
    edge = next(iter(graph.graph.edges(keys=True)))
    graph.graph.edges[edge].update(
        edge_zone="stand_group_internal", stand_group_id="manual", is_manual_lock=True
    )
    before = graph_id(graph)
    locked = deepcopy(graph.graph.nodes[1])
    result = enrich_airport_semantics(graph)
    assert graph_id(graph) == before
    assert result.graph.nodes[1] == locked
    assert set(result.graph.edges(keys=True)) == set(graph.graph.edges(keys=True))
    assert all(
        result.graph.edges[e]["geometry"].wkb == graph.graph.edges[e]["geometry"].wkb
        for e in graph.graph.edges(keys=True)
    )
    interfaces = {
        n for n, d in result.graph.nodes(data=True) if d["node_type"] == "runway_interface"
    }
    assert len(interfaces) == 1
    assert graph_id(enrich_airport_semantics(result)) == graph_id(result)
    backbone, od = result.get_backbone_subgraph()
    assert 1 in od and interfaces <= set(od)
    assert not backbone.has_edge(*edge)
    path = save_graph(result, tmp_path / "graph.json")
    assert graph_id(load_graph(path)) == graph_id(result)


def test_save_failure_and_semantic_revision(tmp_path, monkeypatch):
    graph = topology()
    complete_geometric_topology(graph)
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
    assert session.revision == 1 and session.topology_revision == 0
    session.save(tmp_path / "graph.json", expected_revision=1)
    assert session.revision == 1


@pytest.mark.parametrize("eps", [0, -1, float("nan"), float("inf")])
def test_invalid_eps(eps):
    with pytest.raises(ValueError):
        enrich_airport_semantics(topology(), cluster_eps_m=eps)


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


def test_json_value_distinguishes_dataclass_instances_from_classes():
    from airport_surface import GraphMetadata
    from utils.json_value import to_json_value

    assert to_json_value(GraphMetadata("TEST")) == {"airport": "TEST", "build_issues": []}
    assert to_json_value(GraphMetadata) == str(GraphMetadata)


def test_coordinate_transforms_preserve_linestring():
    graph = topology()
    line = LineString([(0, 0), (.001, .001), (.002, 0)])
    projected = graph.project_shape(line)
    restored = graph.to_wgs84_shape(projected)
    assert isinstance(projected, LineString)
    assert isinstance(restored, LineString)
    assert restored.equals_exact(line, tolerance=1e-12)
