from math import cos, radians, sin
from types import SimpleNamespace

import networkx as nx
import pytest
from shapely.geometry import LineString

from path_map.path import DirectedEdge
from path_map.transition_constraints import LocalTurnConstraint


def turn_constraint(
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
        directed_lines={
            ("A", "O", "in"): LineString(incoming_coords),
            ("O", "A", "in"): LineString(reversed(incoming_coords)),
            ("O", "B", "out"): LineString(outgoing_coords),
            ("B", "O", "out"): LineString(reversed(outgoing_coords)),
        },
    )
    return LocalTurnConstraint(
        index,
        max_angle_deg=threshold,
        tangent_sample_m=sample_m,
    )


@pytest.mark.parametrize(
    ("angle", "illegal"),
    [(0, False), (90, False), (149, False), (150, False), (151, True), (179.9, True)],
)
def test_local_turn_angle_threshold(angle, illegal):
    constraint = turn_constraint(angle)

    assert (
        constraint.accepts([DirectedEdge("A", "O", "in"), DirectedEdge("O", "B", "out")])
        is not illegal
    )


def test_reverse_directed_edge_uses_reverse_local_tangent():
    constraint = turn_constraint(90)

    angle = constraint.turn_angle(DirectedEdge("B", "O", "out"), DirectedEdge("O", "A", "in"))

    assert angle == pytest.approx(90)


def test_curved_edge_uses_local_tangent_instead_of_endpoint_chord():
    constraint = turn_constraint(
        0,
        threshold=30,
        sample_m=0.5,
        outgoing_coords=[(0, 0), (2, 0), (20, 20)],
    )

    assert constraint.accepts([DirectedEdge("A", "O", "in"), DirectedEdge("O", "B", "out")])


def test_short_edges_use_their_available_length_for_tangent():
    constraint = turn_constraint(
        90,
        sample_m=10,
        incoming_coords=[(-1, 0), (0, 0)],
        outgoing_coords=[(0, 0), (0, 2)],
    )

    assert constraint.turn_angle(
        DirectedEdge("A", "O", "in"), DirectedEdge("O", "B", "out")
    ) == pytest.approx(90)


def test_degenerate_tangent_is_skipped_without_error(caplog):
    constraint = turn_constraint(0)
    constraint.incoming_tangents[("A", "O", "in")] = None

    assert constraint.accepts([DirectedEdge("A", "O", "in"), DirectedEdge("O", "B", "out")])
