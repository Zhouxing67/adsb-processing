import networkx as nx
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import AirportGraph, SourceEdge, SourceSegment


def make_graph():
    graph = nx.MultiGraph()
    graph.add_edge(1, 2, aeroway="parking_position", ref="101")
    return AirportGraph(graph, Proj("EPSG:3857"))


def test_stand_dictionaries_use_osm_ref():
    airport = make_graph()
    assert airport.stand_to_edge["101"] == (1, 2, 0)
    assert airport.edge_to_stand[(1, 2, 0)] == "101"
    airport.graph.remove_edge(1, 2, 0)
    airport.rebuild_stand_index()
    assert not airport.edge_to_stand
    assert not airport.stand_to_edge


def test_shared_runway_taxiway_node_is_indexed():

    graph = nx.MultiGraph()
    sources = {}
    for name, nodes, coords in [
        ("runway", (1, 2), [(-0.001, 0), (0.001, 0)]),
        ("taxiway", (2, 4), [(0.001, 0), (0.001, 0.001)]),
        ("parking_position", (5, 6), [(0.0005, -0.001), (0.0005, 0.001)]),
    ]:
        geometry = LineString(coords)
        sources[name] = SourceEdge(
            name, geometry, "osm", attributes={"aeroway": name, "ref": "102"}
        )
        length = 222.6389816
        for node, pos in zip(nodes, coords):
            graph.add_node(node, pos=pos)
        graph.add_edge(*nodes, geometry=geometry, first=nodes[0], last=nodes[1],
                       aeroway=name, ref="102",
                       source_segments=(SourceSegment(name, 0, length),))
    airport = AirportGraph(graph, Proj("EPSG:3857"), source_edges=sources)
    assert len(airport.stand_to_edge) == 1
    assert len(airport.runway_interfaces) == 1
    interface = next(iter(airport.runway_interfaces.values()))
    assert len(interface["runway"]) == 1
    assert len(interface["taxiway"]) == 1
    assert airport.copy().runway_interfaces == airport.runway_interfaces


def test_missing_ref_is_omitted_and_shared_ref_indexes_all_edges():
    graph = nx.MultiGraph()
    graph.add_edge(1, 2, aeroway="parking_position")
    airport = AirportGraph(graph, Proj("EPSG:3857"))
    assert airport.stand_to_edge == airport.edge_to_stand == {}
    graph.edges[1, 2, 0]["ref"] = "101"
    graph.add_edge(2, 3, aeroway="parking_position", ref="101")
    airport.rebuild_stand_index()
    assert airport.stand_to_edge["101"] == (1, 2, 0)
    assert airport.edge_to_stand[(1, 2, 0)] == "101"
    assert airport.edge_to_stand[(2, 3, 0)] == "101"
