"""Retired grouping results remain loadable as opaque JSON metadata."""
import networkx as nx
from pyproj import Proj

from airport_surface import AirportGraph, load_graph, save_graph


def test_stored_groups_survive_without_algorithm(tmp_path):
    groups = ({"stand_group_id": "old", "entities": [], "diagnostics": ["historical"]},)
    graph = AirportGraph(nx.MultiGraph(), Proj("EPSG:3857"), stand_groups=groups)
    copied = graph.copy()
    copied.stand_groups[0]["entities"].append({"id": "new"})
    assert graph.stand_groups == groups
    assert load_graph(save_graph(graph, tmp_path / "graph.json")).stand_groups == groups
