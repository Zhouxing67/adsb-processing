import networkx as nx
import pytest
from bidict import bidict
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import AirportGraph, SourceEdge, SourceSegment


def make_graph(*, split=False, mixed=False):
    geometry = LineString([(0, 0), (0.001, 0)])
    sources = {
        name: SourceEdge(name, geometry, "osm", attributes={"aeroway": kind})
        for name, kind in [("stand", "parking_position"), ("taxi", "taxiway")]
    }
    graph = nx.MultiGraph()
    segments = [SourceSegment("stand", 0, 10)]
    if mixed:
        segments.append(SourceSegment("taxi", 0, 10))
    graph.add_edge(1, 2, source_segments=tuple(segments))
    if split:
        graph.add_edge(2, 3, source_segments=(SourceSegment("stand", 10, 20),))
    return AirportGraph(graph, Proj("EPSG:3857"), source_edges=sources)


def test_stand_bidirectional_index_and_deleted_stand():
    airport = make_graph()
    assert isinstance(airport.stand_edges, bidict)
    assert airport.stand_edges["stand"] == (1, 2, 0)
    assert airport.stand_edges.inverse[(1, 2, 0)] == "stand"
    airport.graph.remove_edge(1, 2, 0)
    airport.rebuild_stand_index()
    assert "stand" in airport.stands
    assert not airport.stand_edges


@pytest.mark.parametrize("kwargs", [{"split": True}, {"mixed": True}])
def test_stand_requires_one_exclusive_edge(kwargs):
    with pytest.raises(ValueError, match="Stand"):
        make_graph(**kwargs)


def test_geometric_runway_taxiway_crossing_is_indexed():
    from airport_surface.traffic_builder import complete_geometric_topology

    graph = nx.MultiGraph()
    sources = {}
    for name, nodes, coords in [
        ("runway", (1, 2), [(-0.001, 0), (0.001, 0)]),
        ("taxiway", (3, 4), [(0, -0.001), (0, 0.001)]),
        ("parking_position", (5, 6), [(0.0005, -0.001), (0.0005, 0.001)]),
    ]:
        geometry = LineString(coords)
        sources[name] = SourceEdge(name, geometry, "osm", attributes={"aeroway": name})
        length = 222.6389816
        for node, pos in zip(nodes, coords):
            graph.add_node(node, pos=pos)
        graph.add_edge(*nodes, geometry=geometry, first=nodes[0], last=nodes[1],
                       source_segments=(SourceSegment(name, 0, length),))
    airport = AirportGraph(graph, Proj("EPSG:3857"), source_edges=sources)
    complete_geometric_topology(airport)
    assert len(airport.stand_edges) == 1
    assert len(airport.runway_interfaces) == 1
    interface = next(iter(airport.runway_interfaces.values()))
    assert len(interface["runway"]) == 2
    assert len(interface["taxiway"]) == 2
    assert airport.copy().runway_interfaces == airport.runway_interfaces
