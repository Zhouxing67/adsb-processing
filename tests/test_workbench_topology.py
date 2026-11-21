from pathlib import Path
from types import SimpleNamespace

import networkx as nx
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import AirportGraph
from airport_workbench.app import BrowserState, _edge_colors, create_app
from airport_workbench.editor import EditorSession


class _AirportGraph:
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
    graph.add_node("1", pos=(0.0, 0.0))
    graph.add_node("2", pos=(1.0, 0.0))
    graph.add_node("3", pos=(5.0, 5.0))
    graph.add_edge("1", "2", key=0, geometry=LineString([(0, 0), (1, 0)]))
    graph.add_edge("1", "2", key=1, geometry=LineString([(0, 0.1), (1, 0.1)]))

    state = _browser_state(graph)
    topology = state["topology"]

    assert [component["size"] for component in topology["components"]] == [2, 1]
    assert topology["parallel_pair_count"] == 1
    assert len(topology["parallel_groups"][0]["edge_ids"]) == 2
    isolated = next(
        feature for feature in state["nodes"]["features"] if feature["properties"]["degree"] == 0
    )
    assert isolated["properties"]["color"] == "#a34f6a"
    assert isolated["properties"]["radius"] == 5
    assert isolated["properties"]["node_type"] == "unclassified"
    assert isolated["properties"]["id"] == "3"
    edge = state["edges"]["features"][0]["properties"]
    assert {edge["u"], edge["v"]} == {"1", "2"}


def test_validation_colors_differ_for_incident_edges() -> None:
    graph = nx.MultiGraph()
    graph.add_edges_from([("1", "2"), ("1", "3"), ("1", "4")])

    colors = _edge_colors(graph)

    assert len(set(colors.values())) == 3


def test_read_only_viewer_hides_editing_state_and_rejects_writes(
    flight_samples, flight_database_factory
) -> None:
    graph = nx.MultiGraph()
    graph.add_node("1", pos=(0.0, 0.0))
    graph.add_node("2", pos=(0.001, 0.0))
    graph.add_edge("1", "2", geometry=LineString([(0.0, 0.0), (0.001, 0.0)]))
    session = EditorSession(AirportGraph(graph, Proj("EPSG:32650")))
    app = create_app(session, flight_database=flight_database_factory(flight_samples))
    state_route = next(
        route for route in app.routes if getattr(route, "path", None) == "/api/state"
    )

    assert state_route.endpoint().capabilities.can_edit_graph is False
    assert "/api/update-edge" not in {route.path for route in app.routes if hasattr(route, "path")}
    assert not app.user_middleware
