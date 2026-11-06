from math import cos, radians, sin
from types import SimpleNamespace

import networkx as nx
import pytest
from shapely.geometry import LineString, Point

from path_map.candidates import Candidate
from path_map.hmm import NetworkRouter
from path_map.path import DirectedEdge


def turn_router(
    angle_deg: float,
    *,
    threshold: float = 150.0,
    sample_m: float = 10.0,
    incoming_coords=None,
    outgoing_coords=None,
):
    incoming_coords = incoming_coords or [(-10, 0), (0, 0)]
    outgoing_coords = outgoing_coords or [
        (0, 0),
        (10 * cos(radians(angle_deg)), 10 * sin(radians(angle_deg))),
    ]
    graph = nx.MultiGraph()
    graph.add_edge("A", "O", key="in", geometry=LineString(incoming_coords))
    graph.add_edge("O", "B", key="out", geometry=LineString(outgoing_coords))
    index = SimpleNamespace(
        edge_ids=[("A", "O", "in"), ("O", "B", "out")],
        lines=[LineString(incoming_coords), LineString(outgoing_coords)],
    )
    return NetworkRouter(
        SimpleNamespace(graph=graph),
        index,
        max_transition_turn_angle_deg=threshold,
        turn_tangent_sample_m=sample_m,
    )


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


def test_router_uses_networkx_shortest_path(monkeypatch):
    graph = nx.MultiGraph()
    graph.add_edge("A", "B", key=0, geometry=LineString([(0, 0), (10, 0)]))
    graph.add_edge("B", "C", key=0, geometry=LineString([(10, 0), (20, 0)]))
    index = SimpleNamespace(
        edge_ids=[("A", "B", 0), ("B", "C", 0)],
        lines=[LineString([(0, 0), (10, 0)]), LineString([(10, 0), (20, 0)])],
    )
    router = NetworkRouter(SimpleNamespace(graph=graph), index)
    original = nx.shortest_path
    call_count = 0

    def counted_shortest_path(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(nx, "shortest_path", counted_shortest_path)

    assert router._middle("A", "B")[0] == pytest.approx(10)
    assert router._middle("A", "C")[0] == pytest.approx(20)
    assert call_count == 2


def test_router_reuses_middle_path_for_the_same_node_pair(monkeypatch):
    graph = nx.MultiGraph()
    graph.add_edge("A", "B", key=0, geometry=LineString([(0, 0), (10, 0)]))
    index = SimpleNamespace(
        edge_ids=[("A", "B", 0)],
        lines=[LineString([(0, 0), (10, 0)])],
    )
    router = NetworkRouter(SimpleNamespace(graph=graph), index)
    original = nx.shortest_path
    call_count = 0

    def counted_shortest_path(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(nx, "shortest_path", counted_shortest_path)

    assert router._middle("A", "B")[0] == pytest.approx(10)
    assert router._middle("A", "B")[0] == pytest.approx(10)
    assert call_count == 1


def candidate(edge_id, offset, length=100):
    return Candidate(0, edge_id, 0, Point(offset, 0), offset, offset / length)


def inserted_candidate_distance(graph, edge_id, source_offset, target_offset, edge_length):
    """Independent reference: split the candidate edge and route between inserted nodes."""
    reference = graph.copy()
    u, v, key = edge_id
    reference.remove_edge(u, v, key)
    source_node = object()
    target_node = object()
    positions = sorted(((source_offset, source_node), (target_offset, target_node)))
    chain = [(0, u), *positions, (edge_length, v)]
    for (left_offset, left), (right_offset, right) in zip(chain, chain[1:]):
        reference.add_edge(left, right, length=right_offset - left_offset)
    for _left, _right, data in reference.edges(data=True):
        if "length" not in data:
            data["length"] = data["geometry"].length
    return nx.shortest_path_length(reference, source_node, target_node, weight="length")


def test_same_edge_direct_travel_competes_with_shorter_endpoint_detour():
    graph = nx.MultiGraph()
    graph.add_edge("A", "B", key="main", geometry=LineString([(0, 0), (100, 0)]))
    graph.add_edge("A", "C", key="AC", geometry=LineString([(0, 0), (5, 0)]))
    graph.add_edge("C", "B", key="CB", geometry=LineString([(5, 0), (10, 0)]))
    index = SimpleNamespace(
        edge_ids=[("A", "B", "main"), ("A", "C", "AC"), ("C", "B", "CB")],
        lines=[
            LineString([(0, 0), (100, 0)]),
            LineString([(0, 0), (5, 0)]),
            LineString([(5, 0), (10, 0)]),
        ],
    )
    router = NetworkRouter(
        SimpleNamespace(graph=graph), index, max_transition_turn_angle_deg=180
    )

    transition = router.transition(
        candidate(("A", "B", "main"), 10),
        candidate(("A", "B", "main"), 90),
    )

    assert transition is not None
    reference_distance = inserted_candidate_distance(
        graph, ("A", "B", "main"), 10, 90, 100
    )
    assert transition.distance == pytest.approx(reference_distance)
    assert transition.edges == (
        DirectedEdge("B", "A", "main"),
        DirectedEdge("A", "C", "AC"),
        DirectedEdge("C", "B", "CB"),
        DirectedEdge("B", "A", "main"),
    )


def test_transition_returns_none_between_disconnected_components():
    graph = nx.MultiGraph()
    graph.add_edge("A", "B", key="AB", geometry=LineString([(0, 0), (10, 0)]))
    graph.add_edge("C", "D", key="CD", geometry=LineString([(20, 0), (30, 0)]))
    index = SimpleNamespace(
        edge_ids=[("A", "B", "AB"), ("C", "D", "CD")],
        lines=[LineString([(0, 0), (10, 0)]), LineString([(20, 0), (30, 0)])],
    )
    router = NetworkRouter(SimpleNamespace(graph=graph), index)

    assert router.transition(
        candidate(("A", "B", "AB"), 5, 10),
        candidate(("C", "D", "CD"), 5, 10),
    ) is None


def test_same_position_transition_has_no_directed_edge():
    graph = nx.MultiGraph()
    graph.add_edge("A", "B", key="AB", geometry=LineString([(0, 0), (10, 0)]))
    index = SimpleNamespace(
        edge_ids=[("A", "B", "AB")],
        lines=[LineString([(0, 0), (10, 0)])],
    )
    router = NetworkRouter(SimpleNamespace(graph=graph), index)

    transition = router.transition(
        candidate(("A", "B", "AB"), 7, 10),
        candidate(("A", "B", "AB"), 7, 10),
    )

    assert transition is not None
    assert transition.distance == 0
    assert transition.edges == ()


def test_shared_node_zero_distance_transition_adds_no_partial_edges():
    graph = nx.MultiGraph()
    graph.add_edge("A", "B", key="AB", geometry=LineString([(0, 0), (10, 0)]))
    graph.add_edge("B", "C", key="BC", geometry=LineString([(10, 0), (20, 0)]))
    index = SimpleNamespace(
        edge_ids=[("A", "B", "AB"), ("B", "C", "BC")],
        lines=[LineString([(0, 0), (10, 0)]), LineString([(10, 0), (20, 0)])],
    )
    router = NetworkRouter(SimpleNamespace(graph=graph), index)

    transition = router.transition(
        candidate(("A", "B", "AB"), 10, 10),
        candidate(("B", "C", "BC"), 0, 10),
    )

    assert transition is not None
    assert transition.distance == 0
    assert transition.edges == ()


@pytest.mark.parametrize(
    ("angle", "illegal"),
    [(0, False), (90, False), (149, False), (150, False), (151, True), (179.9, True)],
)
def test_local_turn_angle_threshold(angle, illegal):
    router = turn_router(angle)

    assert router._contains_illegal_turn(
        [DirectedEdge("A", "O", "in"), DirectedEdge("O", "B", "out")]
    ) is illegal


def test_reverse_directed_edge_uses_reverse_local_tangent():
    router = turn_router(90)

    angle = router._turn_angle(
        DirectedEdge("B", "O", "out"), DirectedEdge("O", "A", "in")
    )

    assert angle == pytest.approx(90)


def test_curved_edge_uses_local_tangent_instead_of_endpoint_chord():
    router = turn_router(
        0,
        threshold=30,
        sample_m=0.5,
        outgoing_coords=[(0, 0), (2, 0), (20, 20)],
    )

    assert not router._contains_illegal_turn(
        [DirectedEdge("A", "O", "in"), DirectedEdge("O", "B", "out")]
    )


def test_short_edges_use_their_available_length_for_tangent():
    router = turn_router(
        90,
        sample_m=10,
        incoming_coords=[(-1, 0), (0, 0)],
        outgoing_coords=[(0, 0), (0, 2)],
    )

    assert router._turn_angle(
        DirectedEdge("A", "O", "in"), DirectedEdge("O", "B", "out")
    ) == pytest.approx(90)


def test_degenerate_tangent_is_skipped_without_error(caplog):
    router = turn_router(0)
    router.incoming_tangents[("A", "O", "in")] = None

    assert not router._contains_illegal_turn(
        [DirectedEdge("A", "O", "in"), DirectedEdge("O", "B", "out")]
    )


def test_illegal_endpoint_choice_does_not_hide_legal_alternative(monkeypatch):
    graph = nx.MultiGraph()
    graph.add_edge("A", "B", key="source", geometry=LineString([(0, 0), (10, 0)]))
    graph.add_edge("B", "C", key="target", geometry=LineString([(10, 0), (20, 0)]))
    index = SimpleNamespace(
        edge_ids=[("A", "B", "source"), ("B", "C", "target")],
        lines=[LineString([(0, 0), (10, 0)]), LineString([(10, 0), (20, 0)])],
    )
    router = NetworkRouter(SimpleNamespace(graph=graph), index)
    checked = 0

    def reject_first(edges):
        nonlocal checked
        checked += 1
        return checked == 1

    monkeypatch.setattr(router, "_contains_illegal_turn", reject_first)

    transition = router.transition(
        candidate(("A", "B", "source"), 5, 10),
        candidate(("B", "C", "target"), 5, 10),
    )

    assert checked == 4
    assert transition is not None


def test_transition_returns_none_when_every_endpoint_choice_is_illegal(monkeypatch):
    graph = nx.MultiGraph()
    graph.add_edge("A", "B", key="source", geometry=LineString([(0, 0), (10, 0)]))
    graph.add_edge("B", "C", key="target", geometry=LineString([(10, 0), (20, 0)]))
    index = SimpleNamespace(
        edge_ids=[("A", "B", "source"), ("B", "C", "target")],
        lines=[LineString([(0, 0), (10, 0)]), LineString([(10, 0), (20, 0)])],
    )
    router = NetworkRouter(SimpleNamespace(graph=graph), index)
    monkeypatch.setattr(router, "_contains_illegal_turn", lambda _edges: True)

    assert router.transition(
        candidate(("A", "B", "source"), 5, 10),
        candidate(("B", "C", "target"), 5, 10),
    ) is None
