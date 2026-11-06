from __future__ import annotations

from pathlib import Path

import pytest

from airport_surface import load_graph
from path_map import MatchConfig, Matcher, MovementType, load_data
from path_map.candidates import CandidateIndex
from path_map.hmm import NetworkRouter
from path_map.path import DirectedEdge

ROOT = Path(__file__).resolve().parents[1]
GRAPH_FILE = ROOT / "data" / "graphs" / "zbaa_final.json"
DEPARTURES_FILE = ROOT / "data" / "ADS-B" / "more_15_dep.csv"
TARGET_FLIGHT_ID = "3U3109_20240628082400"


@pytest.fixture(scope="module")
def target_case():
    if not GRAPH_FILE.exists() or not DEPARTURES_FILE.exists():
        pytest.skip("ZBAA graph or departure regression data is not available")
    airport_graph = load_graph(GRAPH_FILE)
    flights = load_data(DEPARTURES_FILE, MovementType.DEPARTURE)
    flight = next(item for item in flights if item.flight_id == TARGET_FLIGHT_ID)
    return airport_graph, flight


def test_target_turn_is_measured_from_local_directed_tangents(target_case):
    airport_graph, _flight = target_case
    router = NetworkRouter(airport_graph, CandidateIndex(airport_graph))
    incoming = DirectedEdge(244881041, 244881044, 0)
    outgoing = DirectedEdge(244881044, 1055651195, 0)

    angle = router._turn_angle(incoming, outgoing)

    assert angle == pytest.approx(169.952391, abs=1e-6)
    assert router._contains_illegal_turn((incoming, outgoing))


def test_target_flight_never_returns_the_prohibited_turn(target_case):
    airport_graph, flight = target_case

    path = Matcher(airport_graph, MatchConfig()).map_flight(flight)

    prohibited = (244881044, 1055651195, 244881044)
    assert all(
        tuple(path.nodes[index : index + 3]) != prohibited
        for index in range(len(path.nodes) - 2)
    )
    assert (244881041, 244881044, 244881048) in tuple(
        tuple(path.nodes[index : index + 3]) for index in range(len(path.nodes) - 2)
    )
