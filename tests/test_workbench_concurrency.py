from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import networkx as nx
import pytest
from fastapi.testclient import TestClient
from pyproj import CRS
from shapely.geometry import LineString

from airport_surface import AirportGraph, GraphMetadata
from airport_workbench.app import create_app
from airport_workbench.editor import (
    CommandResult,
    EditorSession,
    GraphObjectNotFound,
    RevisionConflict,
)
from airport_workbench.identifiers import EdgeIdentity

PROJECTION = CRS.from_epsg(3857)


def graph_session() -> EditorSession:
    graph = nx.MultiGraph()
    graph.add_node("1", pos=(0.0, 0.0))
    graph.add_node("2", pos=(1.0, 0.0))
    graph.add_edge(
        "1",
        "2",
        key=0,
        geometry=LineString([(0.0, 0.0), (1.0, 0.0)]),
        first="1",
        last="2",
    )
    return EditorSession(AirportGraph(graph, PROJECTION, metadata=GraphMetadata("TEST")))


def test_identifier_contract_accepts_canonical_strings_and_integer_edge_keys() -> None:
    large = 2**63 + 123
    edge = EdgeIdentity(u=str(large), v="-1", key=7)
    assert edge.as_tuple() == (str(large), "-1", 7)
    with pytest.raises(ValueError):
        EdgeIdentity(u="01", v="1", key=0)
    with pytest.raises(ValueError):
        EdgeIdentity(u="1", v="2", key=-1)


def test_state_contains_stable_identities_without_temporary_tokens() -> None:
    with TestClient(create_app(graph_session())) as client:
        state = client.get("/api/state").json()

    nodes = [item["properties"] for item in state["nodes"]["features"]]
    assert {item["id"] for item in nodes} == {"1", "2"}
    assert all("token" not in item for item in nodes)
    edge = state["edges"]["features"][0]["properties"]
    assert edge["id"] == {"u": "1", "v": "2", "key": 0}
    assert "token" not in edge


def test_two_clients_stale_edit_conflicts_without_extra_history() -> None:
    session = graph_session()
    with TestClient(create_app(session)) as client:
        first = client.post(
            "/api/update-node",
            json={
                "node": "1",
                "attributes": {"name": "reviewed"},
                "expected_revision": 0,
            },
        )
        stale = client.post(
            "/api/update-node",
            json={
                "node": "2",
                "attributes": {"name": "reviewed"},
                "expected_revision": 0,
            },
        )

    assert first.json()["revision"] == 1
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "revision_conflict",
        "message": "图已变更，请重新检查操作",
        "context": {"current_revision": 1},
    }
    assert session.revision == 1
    assert len(session._history) == 1
    assert "name" not in session.graph.nodes["2"]


def test_simultaneous_same_revision_allows_only_one_edit() -> None:
    session = graph_session()
    barrier = threading.Barrier(2)

    def edit(node: str) -> str:
        barrier.wait()
        try:
            session.update_node_attributes(
                node,
                {"name": "reviewed"},
                expected_revision=0,
            )
            return "success"
        except RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(edit, ("1", "2")))

    assert sorted(outcomes) == ["conflict", "success"]
    assert session.revision == 1
    assert len(session._history) == 1


def test_preview_revision_becomes_invalid_after_other_edit() -> None:
    session = graph_session()
    with TestClient(create_app(session)) as client:
        state = client.get("/api/state").json()
        edge = state["edges"]["features"][0]["properties"]["id"]
        preview = client.post(
            "/api/delete-edge-preview",
            json={"edge": edge, "expected_revision": 0},
        ).json()
        client.post(
            "/api/update-node",
            json={
                "node": "1",
                "attributes": {"name": "reviewed"},
                "expected_revision": 0,
            },
        )
        confirm = client.post(
            "/api/delete-edge-confirm",
            json={"edge": edge, "expected_revision": preview["revision"]},
        )

    assert confirm.status_code == 409
    assert session.graph.has_edge("1", "2", 0)


def test_current_revision_missing_object_and_reversed_undirected_edge() -> None:
    session = graph_session()
    with pytest.raises(GraphObjectNotFound):
        session.update_node_attributes(
            "missing",
            {"name": "reviewed"},
            expected_revision=0,
        )

    session = graph_session()
    result = session.update_edge_attributes(
        "2", "1", 0, {"name": "reverse request"}, expected_revision=0
    )
    assert result.revision == 1
    assert session.graph.edges["1", "2", 0]["name"] == "reverse request"


def test_merged_old_node_id_is_not_resolved_through_aliases() -> None:
    graph = nx.MultiGraph()
    graph.add_node("1", pos=(0.0, 0.0))
    graph.add_node("2", pos=(0.000001, 0.0))
    session = EditorSession(AirportGraph(graph, PROJECTION, metadata=GraphMetadata("TEST")))
    session.merge_nodes(["1", "2"], canonical_node="1", expected_revision=0)

    with pytest.raises(GraphObjectNotFound):
        session.update_node_attributes(
            "2",
            {"name": "reviewed"},
            expected_revision=1,
        )


def test_undo_revision_is_monotonic_and_missing_revision_is_rejected() -> None:
    session = graph_session()
    with pytest.raises(TypeError, match="expected_revision"):
        session.update_node_attributes("1", {"name": "reviewed"})
    session.update_node_attributes("1", {"name": "reviewed"}, expected_revision=0)
    result = session.undo(expected_revision=1)
    assert result.revision == 2
    with pytest.raises(RevisionConflict):
        session.update_node_attributes("1", {"name": "stale"}, expected_revision=1)

    with TestClient(create_app(graph_session())) as client:
        missing = client.post(
            "/api/update-node",
            json={
                "node": "1",
                "attributes": {"name": "reviewed"},
            },
        )
        invalid = client.post("/api/undo", json={"expected_revision": "0"})
    assert missing.status_code == 422
    assert invalid.status_code == 422


def test_failed_edit_rolls_back_graph_history_and_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    session = graph_session()

    def fail_refresh() -> None:
        raise RuntimeError("refresh failed")

    monkeypatch.setattr(session, "_refresh", fail_refresh)
    with pytest.raises(RuntimeError, match="refresh failed"):
        session.update_node_attributes("1", {"name": "partial"}, expected_revision=0)

    assert "name" not in session.graph.nodes["1"]
    assert session.revision == 0
    assert session._history == []


def test_self_loop_parallel_keys_and_missing_edge_are_resolved_exactly() -> None:
    session = graph_session()
    session.graph.add_edge("1", "1", key=1, geometry=LineString([(0, 0), (0, 0)]))
    session.graph.add_edge("1", "2", key=1, geometry=LineString([(0, 0), (1, 0)]))

    assert session.require_edge("1", "1", 1) == ("1", "1", 1)
    assert session.require_edge("2", "1", 1) in {("2", "1", 1), ("1", "2", 1)}
    assert session.require_edge("1", "2", 0) == ("1", "2", 0)
    with pytest.raises(GraphObjectNotFound):
        session.require_edge("1", "2", 99)


def test_save_checks_revision_and_does_not_increment_it(tmp_path, monkeypatch) -> None:
    session = graph_session()
    calls: list[object] = []

    def fake_save(graph: AirportGraph, path):
        calls.append(graph)
        return path

    monkeypatch.setattr("airport_workbench.editor.save_graph", fake_save)
    monkeypatch.setattr("airport_workbench.editor.validate_edge_endpoints", lambda _graph: None)
    monkeypatch.setattr("airport_workbench.editor.validate_edge_sources", lambda _graph: None)
    with pytest.raises(RevisionConflict):
        session.save(tmp_path / "graph.json", expected_revision=1)
    assert calls == []

    result = session.save(tmp_path / "graph.json", expected_revision=0)
    assert result.revision == 0
    assert len(calls) == 1


def test_one_complex_delete_creates_one_revision_and_one_undo_record() -> None:
    session = graph_session()
    plan = session.node_deletion_plan("1", expected_revision=0).value
    session.remove_node_with_pairs(
        "1",
        [],
        discard_unpaired=True,
        expected_revision=0,
    )

    assert plan["half_edges"]
    assert session.revision == 1
    assert len(session._history) == 1


def test_finish_does_not_stop_on_conflict_or_save_failure(monkeypatch) -> None:
    session = graph_session()
    finished: list[bool] = []
    app = create_app(session, on_finish=lambda: finished.append(True))

    with TestClient(app, raise_server_exceptions=False) as client:
        conflict = client.post("/api/finish", json={"expected_revision": 1})
        assert conflict.status_code == 409
        assert finished == []

        def fail_save(*_args, **_kwargs):
            raise RuntimeError("save failed")

        monkeypatch.setattr(session, "finish", fail_save)
        failed = client.post("/api/finish", json={"expected_revision": 0})
        assert failed.status_code == 500
        assert finished == []

        def successful_finish(_path, callback, **_kwargs):
            callback()
            return CommandResult(Path("graph.json"), 0)

        monkeypatch.setattr(session, "finish", successful_finish)
        succeeded = client.post("/api/finish", json={"expected_revision": 0})

    assert succeeded.status_code == 200
    assert succeeded.json()["revision"] == 0
    assert finished == [True]
