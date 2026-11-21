from __future__ import annotations

from types import MappingProxyType

import networkx as nx
import pytest
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import AirportGraph, SourceEdge, SourceNode, mutable_source_attributes
from airport_workbench.editor import EditorSession


def source_graph() -> AirportGraph:
    graph = nx.MultiGraph()
    graph.add_node("1", pos=(116.0, 40.0))
    graph.add_node("2", pos=(116.1, 40.1))
    graph.add_edge("1", "2", geometry=LineString([(116.0, 40.0), (116.1, 40.1)]))
    attributes = {"tags": {"names": ["A", "B"]}}
    return AirportGraph(
        graph,
        Proj("EPSG:32650"),
        source_nodes={"1": SourceNode("1", (116.0, 40.0), ("1",), attributes)},
        source_edges={
            "way-1": SourceEdge(
                "way-1",
                LineString([(116.0, 40.0), (116.1, 40.1)]),
                "osm",
                attributes=attributes,
            )
        },
    )


def test_source_attributes_are_recursively_immutable_and_defensively_copied() -> None:
    original = {"tags": {"names": ["A", "B"]}}
    source = SourceNode("1", (116.0, 40.0), ("1",), original)
    original["tags"]["names"].append("C")

    assert isinstance(source.attributes, MappingProxyType)
    assert isinstance(source.attributes["tags"], MappingProxyType)
    assert source.attributes["tags"]["names"] == ("A", "B")
    with pytest.raises(TypeError):
        source.attributes["new"] = "value"  # type: ignore[index]

    mutable = mutable_source_attributes(source.attributes)
    mutable["tags"]["names"].append("C")
    assert source.attributes["tags"]["names"] == ("A", "B")


def test_graph_copies_share_immutable_records_but_not_registries() -> None:
    graph = source_graph()
    copied = graph.copy()
    session = EditorSession(graph)

    assert copied.source_nodes["1"] is graph.source_nodes["1"]
    assert copied.source_edges["way-1"] is graph.source_edges["way-1"]
    assert session.airport_graph.source_nodes["1"] is graph.source_nodes["1"]
    assert session.airport_graph.source_edges["way-1"] is graph.source_edges["way-1"]

    copied.source_nodes["1"] = SourceNode("1", (0.0, 0.0), ("1",))
    assert graph.source_nodes["1"].position == (116.0, 40.0)
