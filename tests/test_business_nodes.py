from __future__ import annotations

import json

import networkx as nx
import pytest
from fastapi.testclient import TestClient
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import (
    AirportGraph,
    SourceEdge,
    SourceSegment,
    enrich_airport_semantics,
    load_graph,
    save_graph,
)
from airport_workbench import EditorSession
from airport_workbench.app import create_app

PROJECTION = Proj("EPSG:3857")


def business_graph() -> AirportGraph:
    graph = nx.MultiGraph()
    positions = {
        "park": (0.0, 0.0),
        "apron": (0.001, 0.0),
        "taxi-end": (0.002, 0.0),
        "access": (0.003, 0.0),
        "runway-end": (0.004, 0.0),
        "runway-mid": (0.005, 0.0),
        "runway-other": (0.006, 0.0),
        "composite-start": (0.007, 0.0),
        "composite-access": (0.008, 0.0),
        "composite-apron": (0.009, 0.0),
    }
    for node, position in positions.items():
        graph.add_node(node, pos=position)
    source_types = {
        "parking": "parking_position",
        "taxi": "taxiway",
        "runway-a": "runway",
        "runway-b": "runway",
        "composite-taxi": "taxiway",
        "composite-runway": "runway",
        "composite-parking": "parking_position",
    }
    sources = {
        name: SourceEdge(
            name,
            LineString([(0.0, 0.0), (0.001, 0.0)]),
            "osm",
            attributes={"aeroway": aeroway},
        )
        for name, aeroway in source_types.items()
    }

    def edge(u: str, v: str, *segments: str) -> None:
        graph.add_edge(
            u,
            v,
            geometry=LineString([positions[u], positions[v]]),
            first=u,
            last=v,
            source_segments=tuple(
                SourceSegment(source_id, index, index + 1)
                for index, source_id in enumerate(segments)
            ),
        )

    edge("park", "apron", "parking")
    edge("apron", "taxi-end", "taxi")
    edge("taxi-end", "access", "taxi")
    edge("access", "runway-end", "runway-a")
    edge("runway-end", "runway-mid", "runway-a")
    edge("runway-mid", "runway-other", "runway-b")
    edge("composite-start", "composite-access", "composite-taxi", "composite-runway")
    edge("composite-access", "composite-apron", "composite-parking")
    return AirportGraph(graph, PROJECTION, source_edges=sources)


def test_new_interface_excludes_parking_only_runway_connection():
    graph = enrich_airport_semantics(business_graph())
    interfaces = {n for n, d in graph.graph.nodes(data=True)
                  if d["node_type"] == "runway_interface"}
    assert interfaces == {"access"}


def test_old_collections_are_verified_then_ignored(tmp_path):
    from airport_surface.graph import _document_graph_id

    graph = nx.MultiGraph()
    graph.add_node(1, pos=(0, 0))
    path = save_graph(AirportGraph(graph, PROJECTION), tmp_path / "old.json")
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


def test_semantic_edit_is_undoable_and_read_only_is_protected():
    graph = nx.MultiGraph()
    graph.add_node(1, pos=(0, 0))
    session = EditorSession(AirportGraph(graph, PROJECTION))
    session.update_node_attributes(1, {"node_type": "group_portal", "is_manual_lock": True},
                                   expected_revision=0)
    session.undo(expected_revision=1)
    assert session.graph.nodes[1]["node_type"] == "unclassified"
    with TestClient(create_app(session, read_only=True)) as client:
        response = client.post("/api/update-node", json={
            "node": {"type": "int", "value": "1"},
            "attributes": {"node_type": "group_portal"}, "expected_revision": 2})
    assert response.status_code == 405
