"""Public HMM map matching entry point."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from typing import Any, Mapping, NamedTuple

import networkx as nx
from shapely.geometry import Point

from airport_surface import AirportGraph
from flight import Flight

from .candidates import Candidate, CandidateIndex
from .hmm import (
    DirectedNetworkRouter,
    Transition,
    viterbi,
)
from .path import DirectedEdge, EdgeId, Path

logger = logging.getLogger(__name__)


class MapMatchingFailure(StrEnum):
    """Stable machine-readable reasons for expected matching failures."""

    INVALID_OD = "invalid_od"
    MISSING_OD = "missing_od"
    UNKNOWN_OD = "unknown_od"
    NO_CANDIDATES = "no_candidates"
    NO_LEGAL_PATH = "no_legal_path"
    NO_MOVEMENT = "no_movement"


class MapMatchingError(ValueError):
    """An expected matching failure with a stable code and diagnostic context."""

    def __init__(
        self,
        code: MapMatchingFailure,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})


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


class _FlightODLayers(NamedTuple):
    start: list[Candidate]
    end: list[Candidate]
    runway_edges: set[EdgeId]


class Matcher:
    """Reusable matcher state for many flights on the same airport graph."""

    def __init__(
        self,
        airport_graph: AirportGraph,
        config: MatchConfig = MatchConfig(),
    ) -> None:
        self.airport_graph = airport_graph
        self.config = config
        self.index = CandidateIndex(airport_graph)

    @cached_property
    def _directed_router(self) -> DirectedNetworkRouter:
        return DirectedNetworkRouter(
            self.index,
            max_turn_angle_deg=self.config.max_transition_turn_angle_deg,
            tangent_sample_m=self.config.turn_tangent_sample_m,
        )

    def map_flight(self, flight: Flight) -> Path:
        """Match a flight within its reported stand and runway."""
        start, end, runway_edges = self._flight_od_layers(flight)
        observations = _observations(self.airport_graph, flight)
        matched_observations: list[Point] = []
        layers: list[list[Candidate]] = []

        for index, point in enumerate(observations):
            candidates = self._candidates(index, point)
            if not candidates:
                continue
            matched_observations.append(point)
            layers.append(candidates)

        directed_layers = []
        directed_observations = []
        for point, candidates in zip(matched_observations, layers):
            directed = self._directed_router.expand_candidates(candidates)
            if directed:
                directed_layers.append(directed)
                directed_observations.append(point)

        if not directed_layers:
            raise MapMatchingError(
                MapMatchingFailure.NO_CANDIDATES,
                "At least one observation with edge candidates is required; got 0",
                context={"observation_count": len(observations)},
            )
        logger.debug(
            "Map matching retained %d of %d observations",
            len(directed_layers),
            len(observations),
        )
        # Boundary segments have no observed displacement. Their score penalizes
        # added network distance.
        boundary_observations = [
            directed_observations[0],
            *directed_observations,
            directed_observations[-1],
        ]
        try:
            states, transitions = viterbi(
                [start, *directed_layers, end],
                boundary_observations,
                self._directed_router,
                self.config.gps_sigma,
                self.config.transition_beta,
                allow_single_reversal=flight.movement == "departure",
            )
        except nx.NetworkXNoPath as exc:
            raise MapMatchingError(
                MapMatchingFailure.NO_LEGAL_PATH,
                "No turn-constrained path matches the observations and flight OD",
            ) from exc
        edges = _recover(transitions, states[0])
        # Trim the runway roll on the runway side so the path ends at the runway interface.
        if flight.movement == "departure":
            while edges and edges[-1].id in runway_edges:
                edges.pop()
        else:
            first_taxi = next(
                (i for i, edge in enumerate(edges) if edge.id not in runway_edges),
                len(edges),
            )
            edges = edges[first_taxi:]
        if not edges:
            raise MapMatchingError(
                MapMatchingFailure.NO_MOVEMENT,
                "Retained candidates have no along-network movement; "
                "a directed path cannot be determined",
            )
        return Path(self.airport_graph, edges)

    def _flight_od_layers(
        self,
        flight: Flight,
    ) -> _FlightODLayers:
        if flight.od_error:
            raise MapMatchingError(
                MapMatchingFailure.INVALID_OD,
                f"Invalid flight OD: {flight.od_error}",
                context={"od_error": flight.od_error},
            )
        if flight.movement not in ("departure", "arrival"):
            raise MapMatchingError(
                MapMatchingFailure.MISSING_OD,
                "Missing flight OD: departure or arrival direction is required",
                context={"field": "movement"},
            )
        if not flight.stand_ref:
            raise MapMatchingError(
                MapMatchingFailure.MISSING_OD,
                "Missing flight OD: stand is required",
                context={"fields": ["stand"]},
            )

        is_departure = flight.movement == "departure"
        graph = self.airport_graph
        stand_layer = self._directed_router.stand_candidates(
            graph.stand_to_edges.get(flight.stand_ref, ()),
            departure=is_departure,
        )
        if not stand_layer:
            raise MapMatchingError(
                MapMatchingFailure.UNKNOWN_OD,
                f"Unknown or unusable stand in flight OD: {flight.stand_ref!r}",
                context={"field": "stand", "value": flight.stand_ref},
            )

        runway_edges: set[EdgeId] = set()
        runway_ref = flight.runway_ref.upper() if flight.runway_ref else None
        for u, v, key, data in graph.graph.edges(keys=True, data=True):
            if data.get("aeroway") != "runway":
                continue
            if runway_ref is None or runway_ref in {
                ref.strip() for ref in str(data.get("ref") or "").upper().split("/")
            }:
                runway_edges.update(((u, v, key), (v, u, key)))
        runway_layer = self._directed_router.runway_edge_candidates(
            runway_edges, departure=is_departure
        )
        for node, interface in graph.runway_interfaces.items():
            if runway_edges.intersection(interface["runway"]):
                runway_layer.extend(
                    self._directed_router.runway_candidates(
                        node, interface["taxiway"], departure=is_departure
                    )
                )
        if not runway_layer:
            raise MapMatchingError(
                MapMatchingFailure.UNKNOWN_OD,
                f"Unknown or unusable runway in flight OD: {flight.runway_ref!r}",
                context={"field": "runway", "value": flight.runway_ref},
            )
        if is_departure:
            return _FlightODLayers(stand_layer, runway_layer, runway_edges)
        return _FlightODLayers(runway_layer, stand_layer, runway_edges)

    def _candidates(self, observation_index: int, point: Point) -> list[Candidate]:
        """Find the nearest candidates in one complete-radius spatial query."""
        candidates = self.index.candidates(
            observation_index,
            point,
            self.config.candidate_radius,
            self.config.max_candidates,
        )
        return [
            candidate for candidate in candidates if candidate.edge_id[0] != candidate.edge_id[1]
        ]


def _observations(ag: AirportGraph, flight: Flight) -> list[Point]:
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


def _append_transition_edges(output: list[DirectedEdge], edges: tuple[DirectedEdge, ...]) -> None:
    """Join transitions, collapsing only continued travel on their shared boundary edge."""
    start = 1 if output and edges and output[-1] == edges[0] else 0
    output.extend(edges[start:])
