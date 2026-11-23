import networkx as nx
import pytest
from fastapi.testclient import TestClient
from pyproj import Proj

from airport_surface import AirportGraph, load_graph, validate_edge_sources
from airport_workbench import EditorSession
from airport_workbench.app import create_app
from airport_workbench.editor import RevisionConflict


def session():
    graph = nx.MultiGraph()
    graph.add_node("1", pos=(0, 0))
    graph.add_node("2", pos=(0.002, 0))
    return EditorSession(AirportGraph(graph, Proj("EPSG:3857")))


def test_manual_curve_roundtrip_and_complete_undo(tmp_path):
    editor = session()
    editor.draw_connection("1", "2", [(0.001, 0.001)], ref="A", expected_revision=0)
    assert editor.revision == editor.topology_revision == 1
    assert len(editor._history) == 1
    assert editor.graph.number_of_nodes() == 2
    data = next(iter(editor.graph.edges(data=True)))[2]
    assert list(data["geometry"].coords) == [(0, 0), (0.001, 0.001), (0.002, 0)]
    assert data["source_type"] == "manual"
    assert data["aeroway"] == "taxiway"
    validate_edge_sources(editor.airport_graph)
    path = tmp_path / "drawn.json"
    editor.save(path, expected_revision=1)
    restored = load_graph(path)
    validate_edge_sources(restored)
    assert nx.has_path(restored.graph, "1", "2")
    assert next(iter(restored.graph.edges(data=True)))[2]["geometry"].equals(data["geometry"])
    editor.undo(expected_revision=editor.revision)
    assert editor.graph.number_of_edges() == 0
    assert editor.airport_graph.source_edges == {}


@pytest.mark.parametrize("end,points", [("1", []), ("2", [(float("nan"), 0)]), ("2", [(181, 0)])])
def test_invalid_drawing_is_atomic(end, points):
    editor = session()
    with pytest.raises(ValueError):
        editor.draw_connection("1", end, points, expected_revision=0)
    assert editor.revision == 0
    assert not editor.airport_graph.source_edges


def test_revision_conflict():
    editor = session()
    editor.update_node_attributes("1", {"name": "changed"}, expected_revision=0)
    with pytest.raises(RevisionConflict):
        editor.draw_connection("1", "2", [], expected_revision=0)
    assert not editor.airport_graph.source_edges


def test_api_and_read_only(flight_samples, flight_database_factory):
    payload = {
        "start": "1",
        "end": "2",
        "intermediate_points": [[0.001, 0.001]],
        "expected_revision": 0,
    }
    editor = session()
    with TestClient(create_app(editor)) as client:
        assert client.post("/api/draw-connection", json=payload).status_code == 200
        assert client.post("/api/draw-connection", json=payload).status_code == 409
    read_only = session()
    read_only.draw_connection("1", "2", [], expected_revision=0)
    with TestClient(
        create_app(read_only, flight_database=flight_database_factory(flight_samples))
    ) as client:
        assert client.post("/api/draw-connection", json=payload).status_code == 405
