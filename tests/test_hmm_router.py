from types import SimpleNamespace

import networkx as nx
import pytest
from shapely.geometry import LineString

from path_map.hmm import NetworkRouter
from path_map.path import DirectedEdge


def test_router_uses_shortest_parallel_edge_and_preserves_its_key():
    graph = nx.MultiGraph()
    graph.add_edge("A", "B", key="long", geometry=LineString([(0, 0), (20, 0)]))
    graph.add_edge("A", "B", key="short", geometry=LineString([(0, 0), (10, 0)]))
    graph.add_edge("B", "C", key="next", geometry=LineString([(10, 0), (15, 0)]))
    index = SimpleNamespace(
        edge_ids=[("A", "B", "long"), ("A", "B", "short"), ("B", "C", "next")],
        lines=[
            LineString([(0, 0), (20, 0)]),
            LineString([(0, 0), (10, 0)]),
            LineString([(10, 0), (15, 0)]),
        ],
    )
    airport_graph = SimpleNamespace(graph=graph)

    router = NetworkRouter(airport_graph, index)
    distance, edges = router._middle("A", "C")

    assert distance == pytest.approx(15)
    assert edges == (
        DirectedEdge("A", "B", "short"),
        DirectedEdge("B", "C", "next"),
    )
