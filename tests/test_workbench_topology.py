from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import networkx as nx
from shapely.geometry import LineString

from airport_workbench.app import BrowserState, _edge_colors, create_app


class _AirportGraph:
    parking_position_nodes: set = set()
    runway_access_nodes: set = set()

    @staticmethod
    def length(geometry: LineString) -> float:
        return geometry.length


def _browser_state(graph: nx.MultiGraph) -> dict:
    session = SimpleNamespace(
        graph=graph,
        lock=SimpleNamespace(
            __enter__=lambda self: self,
            __exit__=lambda self, *args: None,
        ),
        airport_graph=_AirportGraph(),
        can_undo=False,
    )
    return BrowserState(session)._state(False, Path("graph.pkl"))


def test_topology_details_locate_components_parallel_edges_and_isolated_nodes() -> None:
    graph = nx.MultiGraph()
    graph.add_node("a", pos=(0.0, 0.0))
    graph.add_node("b", pos=(1.0, 0.0))
    graph.add_node("isolated", pos=(5.0, 5.0))
    graph.add_edge("a", "b", key="left", geometry=LineString([(0, 0), (1, 0)]))
    graph.add_edge("a", "b", key="right", geometry=LineString([(0, 0.1), (1, 0.1)]))

    state = _browser_state(graph)
    topology = state["topology"]

    assert [component["size"] for component in topology["components"]] == [2, 1]
    assert topology["parallel_pair_count"] == 1
    assert len(topology["parallel_groups"][0]["edge_tokens"]) == 2
    isolated = next(
        feature for feature in state["nodes"]["features"] if feature["properties"]["degree"] == 0
    )
    assert isolated["properties"]["color"] == "#a34f6a"
    assert isolated["properties"]["radius"] == 5
    assert isolated["properties"]["parking_position_node"] is False
    assert isolated["properties"]["runway_access_node"] is False
    assert isolated["properties"]["node_sort_key"] == ["str", "'isolated'"]
    edge = state["edges"]["features"][0]["properties"]
    assert edge["u_node_sort_key"][0] == "str"
    assert edge["v_node_sort_key"][0] == "str"
    assert {edge["u_node_sort_key"][1], edge["v_node_sort_key"][1]} == {"'a'", "'b'"}


def test_validation_colors_differ_for_incident_edges() -> None:
    graph = nx.MultiGraph()
    graph.add_edges_from([("hub", "a"), ("hub", "b"), ("hub", "c")])

    colors = _edge_colors(graph)

    assert len(set(colors.values())) == 3


def test_read_only_viewer_hides_editing_state_and_rejects_writes() -> None:
    graph = nx.MultiGraph()
    graph.add_node("a", pos=(0.0, 0.0))
    session = SimpleNamespace(
        graph=graph,
        lock=RLock(),
        airport_graph=_AirportGraph(),
        can_undo=False,
    )
    app = create_app(session, read_only=True)
    state_route = next(
        route for route in app.routes if getattr(route, "path", None) == "/api/state"
    )

    assert state_route.endpoint()["read_only"] is True
    assert app.user_middleware
