from __future__ import annotations

import networkx as nx
import pandas as pd
from pyproj import Proj, Transformer
from shapely.geometry import LineString
from traffic.core import Flight

from airport_surface import AirportGraph
from path_map import MatchConfig, Matcher


def straight_airport_graph() -> tuple[AirportGraph, Transformer]:
    projection = Proj("EPSG:32650")
    to_wgs84 = Transformer.from_proj(projection, "EPSG:4326", always_xy=True)
    projected_positions = {
        "A": (450_000.0, 4_428_000.0),
        "B": (450_010.0, 4_428_000.0),
        "C": (450_020.0, 4_428_000.0),
    }
    positions = {
        node: to_wgs84.transform(*position)
        for node, position in projected_positions.items()
    }
    graph = nx.MultiGraph()
    for node, position in positions.items():
        graph.add_node(node, pos=position)
    graph.add_edge("A", "B", key="AB", geometry=LineString([positions["A"], positions["B"]]))
    graph.add_edge("B", "C", key="BC", geometry=LineString([positions["B"], positions["C"]]))
    return AirportGraph(graph, projection), to_wgs84


def test_reusing_matcher_does_not_mutate_graph_or_change_result():
    airport_graph, to_wgs84 = straight_airport_graph()
    points = [to_wgs84.transform(x, 4_428_000.0) for x in (450_001.0, 450_009.0, 450_019.0)]
    flight = Flight(
        pd.DataFrame(
            {
                "longitude": [point[0] for point in points],
                "latitude": [point[1] for point in points],
            }
        )
    )
    matcher = Matcher(
        airport_graph,
        MatchConfig(search_radius=3, max_candidates=3, gps_sigma=2, transition_beta=5),
    )
    original_nodes = tuple(airport_graph.graph.nodes)
    original_edges = tuple(airport_graph.graph.edges(keys=True))

    results = [matcher.map_flight(flight).edge_ids for _ in range(20)]

    assert all(result == results[0] for result in results)
    assert tuple(airport_graph.graph.nodes) == original_nodes
    assert tuple(airport_graph.graph.edges(keys=True)) == original_edges
    assert nx.is_frozen(matcher.router.routing_graph)
