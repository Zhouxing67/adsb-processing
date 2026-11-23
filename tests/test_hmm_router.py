from math import cos, radians, sin
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString

from path_map.hmm import DirectedNetworkRouter


def turn_router(
    angle_deg: float,
    *,
    threshold: float = 150.0,
    sample_m: float = 10.0,
    incoming_coords=None,
    outgoing_coords=None,
) -> DirectedNetworkRouter:
    incoming_coords = incoming_coords or [(-10, 0), (0, 0)]
    outgoing_coords = outgoing_coords or [
        (0, 0),
        (10 * cos(radians(angle_deg)), 10 * sin(radians(angle_deg))),
    ]
    index = SimpleNamespace(
        edge_ids=[("A", "O", "in"), ("O", "B", "out")],
        lines=[LineString(incoming_coords), LineString(outgoing_coords)],
    )
    return DirectedNetworkRouter(
        index,
        max_turn_angle_deg=threshold,
        tangent_sample_m=sample_m,
    )


@pytest.mark.parametrize(
    ("angle", "illegal"),
    [(0, False), (90, False), (149, False), (150, False), (151, True), (179.9, True)],
)
def test_local_turn_angle_threshold(angle, illegal):
    router = turn_router(angle)

    assert router.graph.has_edge(("A", "O", "in"), ("O", "B", "out")) is not illegal


def test_reverse_directed_edge_uses_reverse_local_tangent():
    router = turn_router(90)

    angle = router.turn_angle(("B", "O", "out"), ("O", "A", "in"))

    assert angle == pytest.approx(90)


def test_curved_edge_uses_local_tangent_instead_of_endpoint_chord():
    router = turn_router(
        0,
        threshold=30,
        sample_m=0.5,
        outgoing_coords=[(0, 0), (2, 0), (20, 20)],
    )

    assert router.graph.has_edge(("A", "O", "in"), ("O", "B", "out"))


def test_short_edges_use_their_available_length_for_tangent():
    router = turn_router(
        90,
        sample_m=10,
        incoming_coords=[(-1, 0), (0, 0)],
        outgoing_coords=[(0, 0), (0, 2)],
    )

    assert router.turn_angle(("A", "O", "in"), ("O", "B", "out")) == pytest.approx(90)


def test_degenerate_edge_is_not_connected():
    router = turn_router(
        0,
        incoming_coords=[(0, 0), (1e-12, 0), (0, 0)],
    )

    assert not router.graph.has_edge(("A", "O", "in"), ("O", "B", "out"))
