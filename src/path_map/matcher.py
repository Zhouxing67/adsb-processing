"""Public HMM map matching entry point."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import networkx as nx
from shapely.geometry import Point

from airport_surface import AirportGraph
from flight import Flight

from .candidates import Candidate, CandidateIndex
from .hmm import NetworkRouter, Transition, viterbi
from .path import DirectedEdge, Path
from .transition_constraints import LocalTurnConstraint

logger = logging.getLogger(__name__)


class MapMatchingError(ValueError):
    """Raised when observations cannot be matched without guessing."""


@dataclass(frozen=True, slots=True)
class MatchConfig:
    candidate_radius: float = 120.0
    max_candidates: int = 16
    gps_sigma: float = 10.0
    transition_beta: float = 20.0
    max_transition_turn_angle_deg: float = 150.0
    turn_tangent_sample_m: float = 10.0

    def __post_init__(self) -> None:
        distances = (
            self.candidate_radius,
            self.gps_sigma,
            self.transition_beta,
            self.turn_tangent_sample_m,
        )
        if any(not math.isfinite(value) or value <= 0 for value in distances):
            raise ValueError("Distance parameters must be finite and positive")
        if (
            not math.isfinite(self.max_transition_turn_angle_deg)
            or not 0 < self.max_transition_turn_angle_deg <= 180
        ):
            raise ValueError("max_transition_turn_angle_deg must be finite and in (0, 180]")
        if isinstance(self.max_candidates, bool) or not isinstance(self.max_candidates, int):
            raise ValueError("max_candidates must be a positive integer")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be a positive integer")


class Matcher:
    """Reusable matcher state for many flights on the same airport graph."""

    def __init__(
        self,
        airport_graph: AirportGraph,
        config: MatchConfig  = MatchConfig(),
    ) -> None:
        self.airport_graph = airport_graph
        self.config = config
        self.index = CandidateIndex(airport_graph)
        turn_constraint = LocalTurnConstraint(
            self.index,
            max_angle_deg=self.config.max_transition_turn_angle_deg,
            tangent_sample_m=self.config.turn_tangent_sample_m,
        )
        self.router = NetworkRouter(
            airport_graph,
            self.index,
            constraints=(turn_constraint,),
        )

    def map_flight(
        self,
        flight: Flight,
    ) -> Path:
        """Match one flight while reusing the graph index and router."""
        observations = _observations(self.airport_graph, flight)
        matched_observations: list[Point] = []
        layers: list[list[Candidate]] = []

        for index, point in enumerate(observations):
            candidates = self._candidates(index, point)
            if not candidates:
                continue
            matched_observations.append(point)
            layers.append(candidates)

        skipped_count = len(observations) - len(layers)
        logger.debug(
            "Map matching retained %d observations and skipped %d without candidates",
            len(layers),
            skipped_count,
        )
        if len(layers) < 2:
            raise MapMatchingError(
                f"At least two observations with edge candidates are required; got {len(layers)}"
            )
        try:
            states, transitions = viterbi(
                layers,
                matched_observations,
                self.router,
                self.config.gps_sigma,
                self.config.transition_beta,
            )
        except nx.NetworkXNoPath as exc:
            raise MapMatchingError("No connected network path matches all observations") from exc
        edges = _recover(transitions, states[0])
        if not edges:
            raise MapMatchingError(
                "Retained candidates have no along-network movement; "
                "a directed path cannot be determined"
            )
        return Path(self.airport_graph, edges)

    def _candidates(self, observation_index: int, point: Point) -> list[Candidate]:
        """Find the nearest candidates in one complete-radius spatial query."""
        candidates = self.index.candidates(
            observation_index,
            point,
            self.config.candidate_radius,
            self.config.max_candidates,
        )
        if any(candidate.edge_id[0] == candidate.edge_id[1] for candidate in candidates):
            raise MapMatchingError("Map matching candidates on self-loop edges are not supported")
        return candidates


def _observations(ag: AirportGraph, flight: Flight) -> list[Point]:
    if flight.point_count < 2:
        raise MapMatchingError("At least two valid observations are required")
    coordinates = [(point.longitude, point.latitude) for point in flight.observations]
    longitude, latitude = zip(*coordinates)
    x, y = ag.project.transform(longitude, latitude)
    return [Point(float(px), float(py)) for px, py in zip(x, y)]


def _recover(transitions: list[Transition], first: Candidate) -> list[DirectedEdge]:
    if not transitions:
        u, v, key = first.edge_id
        return [DirectedEdge(u, v, key)]
    output: list[DirectedEdge] = []
    for transition in transitions:
        _append_transition_edges(output, transition.edges)
    return output

def _append_transition_edges(
    output: list[DirectedEdge], edges: tuple[DirectedEdge, ...]
) -> None:
    """Join transitions, collapsing only continued travel on their shared boundary edge."""
    start = 1 if output and edges and output[-1] == edges[0] else 0
    output.extend(edges[start:])
