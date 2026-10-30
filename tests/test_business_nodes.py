from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pytest
from fastapi.testclient import TestClient
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import (
    AirportGraph,
    SourceEdge,
    SourceSegment,
    classify_business_nodes,
    graph_id,
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


def test_business_node_classification_uses_degree_and_endpoint_segments() -> None:
    airport_graph = business_graph()

    classify_business_nodes(airport_graph)

    assert airport_graph.parking_position_nodes == {"park", "composite-apron"}
    assert airport_graph.runway_access_nodes == {"access", "composite-access"}
    assert "taxi-end" not in airport_graph.parking_position_nodes
    assert "runway-other" not in airport_graph.parking_position_nodes
    assert "runway-mid" not in airport_graph.runway_access_nodes


def test_business_annotations_copy_save_load_and_graph_identity(tmp_path: Path) -> None:
    graph = nx.MultiGraph()
    graph.add_node(1, pos=(0.0, 0.0))
    graph.add_node("mixed", pos=(1.0, 0.0))
    airport_graph = AirportGraph(
        graph,
        PROJECTION,
        parking_position_nodes={1, "mixed"},
        runway_access_nodes={"mixed"},
    )
    before = graph_id(airport_graph)
    copied = airport_graph.copy()
    copied.parking_position_nodes.remove(1)

    assert 1 in airport_graph.parking_position_nodes
    assert graph_id(copied) != before

    path = tmp_path / "business.json"
    save_graph(airport_graph, path)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["parking_position_nodes"] == [1, "mixed"]
    loaded = load_graph(path)
    assert loaded.parking_position_nodes == {1, "mixed"}
    assert loaded.runway_access_nodes == {"mixed"}


def test_legacy_graph_defaults_to_empty_annotations_and_invalid_reference_fails(
    tmp_path: Path,
) -> None:
    graph = nx.MultiGraph()
    graph.add_node("only", pos=(0.0, 0.0))
    path = tmp_path / "legacy.json"
    save_graph(AirportGraph(graph, PROJECTION), path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document.pop("graph_id")
    document.pop("parking_position_nodes")
    document.pop("runway_access_nodes")
    path.write_text(json.dumps(document), encoding="utf-8")

    loaded = load_graph(path)
    assert loaded.parking_position_nodes == set()
    assert loaded.runway_access_nodes == set()

    document["parking_position_nodes"] = ["missing"]
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown graph nodes"):
        load_graph(path)


def test_manual_annotations_are_atomic_undoable_and_deleted_with_node() -> None:
    graph = nx.MultiGraph()
    graph.add_node("node", pos=(0.0, 0.0))
    session = EditorSession(AirportGraph(graph, PROJECTION))

    session.set_business_node_annotations(
        "node", parking_position=True, runway_access=True
    )
    assert session.airport_graph.parking_position_nodes == {"node"}
    assert session.airport_graph.runway_access_nodes == {"node"}
    assert session.topology_revision == 0

    session.undo()
    assert session.airport_graph.parking_position_nodes == set()
    assert session.airport_graph.runway_access_nodes == set()
    assert session.topology_revision == 0

    session.set_business_node_annotations(
        "node", parking_position=True, runway_access=False
    )
    session.delete_node("node")
    assert session.airport_graph.parking_position_nodes == set()
    assert session.topology_revision == 1
    session.undo()
    assert "node" in session.airport_graph.parking_position_nodes
    assert session.topology_revision == 2


def test_read_only_workbench_rejects_business_annotation_updates() -> None:
    graph = nx.MultiGraph()
    graph.add_node("node", pos=(0.0, 0.0))
    app = create_app(EditorSession(AirportGraph(graph, PROJECTION)), read_only=True)

    with TestClient(app) as client:
        response = client.post(
            "/api/nodes/n0/business-annotations",
            json={"parking_position": True, "runway_access": False},
        )

    assert response.status_code == 405


def test_workbench_annotation_endpoint_updates_state_and_undoes() -> None:
    graph = nx.MultiGraph()
    graph.add_node("node", pos=(0.0, 0.0))
    app = create_app(EditorSession(AirportGraph(graph, PROJECTION)))

    with TestClient(app) as client:
        state = client.get("/api/state").json()
        token = state["nodes"]["features"][0]["properties"]["token"]
        response = client.post(
            f"/api/nodes/{token}/business-annotations",
            json={"parking_position": True, "runway_access": True},
        )
        updated = client.get("/api/state").json()
        client.post("/api/undo")
        undone = client.get("/api/state").json()

    assert response.status_code == 200
    properties = updated["nodes"]["features"][0]["properties"]
    assert properties["parking_position_node"] is True
    assert properties["runway_access_node"] is True
    assert updated["topology_revision"] == state["topology_revision"]
    undone_properties = undone["nodes"]["features"][0]["properties"]
    assert undone_properties["parking_position_node"] is False
    assert undone_properties["runway_access_node"] is False
    assert undone["topology_revision"] == state["topology_revision"]
