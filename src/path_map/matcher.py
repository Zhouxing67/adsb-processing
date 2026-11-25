"""Public HMM map matching entry point."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property, lru_cache
from typing import Any, Literal, Mapping

import networkx as nx
from shapely.geometry import Point

from airport_surface import AirportGraph
from flight import Flight, MovementType

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


@dataclass(frozen=True, slots=True)
class FlightOD:
    """Surface OD labels. An inferred runway label may identify both reciprocal ends."""

    movement: MovementType
    stand_ref: str
    runway_ref: str | None
    runway_source: Literal["reported", "inferred"]
    runway_hit_edge: EdgeId | None = None

    @property
    def origin(self) -> str | None:
        return self.stand_ref if self.movement == MovementType.DEPARTURE else self.runway_ref

    @property
    def destination(self) -> str | None:
        return self.runway_ref if self.movement == MovementType.DEPARTURE else self.stand_ref


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
        self._runway_layer = lru_cache(maxsize=64)(self._build_runway_layer)

    @cached_property
    def _directed_router(self) -> DirectedNetworkRouter:
        return DirectedNetworkRouter(
            self.index,
            max_turn_angle_deg=self.config.max_transition_turn_angle_deg,
            tangent_sample_m=self.config.turn_tangent_sample_m,
        )

    def get_od(self, flight: Flight, movetype: MovementType | str | None = None) -> FlightOD:
        """Resolve business endpoints without computing a taxi path."""
        if movetype is not None:
            if movetype not in ("arrival", "departure") or (
                flight.movement is not None and flight.movement != movetype
            ):
                raise MapMatchingError(
                    MapMatchingFailure.INVALID_OD,
                    f"Invalid movement {movetype!r} for flight with movement {flight.movement!r}",
                )
            if flight.movement is None:
                # Apply the same per-direction conflict checks as a database-loaded flight.
                flight = Flight(flight.rows, movement=movetype)
        is_departure, _ = self._flight_stand_layer(flight)
        candidates = []
        if not flight.runway_ref:
            observations = _observations(self.airport_graph, flight)
            indices = range(len(observations))
            if is_departure:
                indices = indices[::-1]
            for index in indices:
                candidates = self._candidates(index, observations[index])
                if candidates:
                    break
            if not candidates:
                raise MapMatchingError(
                    MapMatchingFailure.NO_CANDIDATES, "No observation has edge candidates"
                )
        od, _, _ = self._flight_runway_layer(flight, candidates, is_departure)
        return od

    def map_flight(self, flight: Flight) -> Path:
        """Match a flight: pure turn-constrained trajectory first, OD prior fallback second."""
        is_departure = self._validate_flight_direction(flight)
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

        # Phase 1: Pure trajectory matching under the turn constraint (no virtual OD layers).
        phase1_path = self._match_pure_trajectory(
            flight, directed_layers, directed_observations, is_departure
        )
        if phase1_path is not None:
            return phase1_path

        # Phase 2: Fallback with OD prior boundary layers when trajectory alone is insufficient.
        _, stand_layer = self._flight_stand_layer(flight)
        _, runway_layer, runway_edges = self._flight_runway_layer(
            flight, layers[-1] if is_departure else layers[0], is_departure
        )
        start, end = (stand_layer, runway_layer) if is_departure else (runway_layer, stand_layer)
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
                allow_single_reversal=is_departure,
            )
        except nx.NetworkXNoPath as exc:
            raise MapMatchingError(
                MapMatchingFailure.NO_LEGAL_PATH,
                "No turn-constrained path matches the observations and flight OD",
            ) from exc
        edges = _trim_runway_edges(
            _recover(transitions, states[0]), runway_edges, is_departure=is_departure
        )
        if not edges:
            raise MapMatchingError(
                MapMatchingFailure.NO_MOVEMENT,
                "Retained candidates have no along-network movement; "
                "a directed path cannot be determined",
            )
        return Path(self.airport_graph, edges)

    def _validate_flight_direction(self, flight: Flight) -> bool:
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
        return flight.movement == "departure"

    def _match_pure_trajectory(
        self,
        flight: Flight,
        directed_layers: list[list[Candidate]],
        directed_observations: list[Point],
        is_departure: bool,
    ) -> Path | None:
        """Phase 1: Decode without virtual OD layers and accept complete, label-consistent paths."""
        try:
            states, transitions = viterbi(
                directed_layers,
                directed_observations,
                self._directed_router,
                self.config.gps_sigma,
                self.config.transition_beta,
                allow_single_reversal=is_departure,
            )
        except nx.NetworkXNoPath:
            return None
        _, all_runway_edges = self._runway_layer(None, is_departure)
        edges = _trim_runway_edges(
            _recover(transitions, states[0]), all_runway_edges, is_departure=is_departure
        )
        if not edges:
            return None
        if not self._is_valid_pure_path(flight, edges, is_departure):
            return None
        return Path(self.airport_graph, edges)

    def _is_valid_pure_path(
        self, flight: Flight, edges: list[DirectedEdge], is_departure: bool
    ) -> bool:
        """Accept a Phase 1 path iff endpoints hit stand/runway boundary edges and match labels."""
        stand_edge = edges[0] if is_departure else edges[-1]
        runway_edge = edges[-1] if is_departure else edges[0]

        matched_stand = self.airport_graph.stand_for_edge(stand_edge.id)
        if matched_stand is None:
            return False
        if flight.stand_ref and matched_stand != flight.stand_ref:
            return False

        matched_runways = self.airport_graph.runways_for_edge(runway_edge.id)
        if matched_runways is None:
            return False
        interface_node = runway_edge.to_ if is_departure else runway_edge.from_
        interface = self.airport_graph.runway_interfaces.get(interface_node)
        if interface is None:
            return False
        if flight.runway_ref:
            expected_runway = flight.runway_ref.upper()
            node_runways = {
                part.strip()
                for edge_id in interface["runway"]
                for part in str(self.airport_graph.graph.edges[edge_id].get("ref") or "")
                .upper()
                .split("/")
                if part.strip()
            }
            if expected_runway not in node_runways:
                return False
        return True

    def _flight_stand_layer(self, flight: Flight) -> tuple[bool, list[Candidate]]:
        is_departure = self._validate_flight_direction(flight)
        if not flight.stand_ref:
            raise MapMatchingError(
                MapMatchingFailure.MISSING_OD,
                "Missing flight OD: stand is required",
                context={"fields": ["stand"]},
            )
        stand_layer = self._directed_router.stand_candidates(
            self.airport_graph.stand_to_edges.get(flight.stand_ref, ()),
            departure=is_departure,
        )
        if not stand_layer:
            raise MapMatchingError(
                MapMatchingFailure.UNKNOWN_OD,
                f"Unknown or unusable stand in flight OD: {flight.stand_ref!r}",
                context={"field": "stand", "value": flight.stand_ref},
            )
        return is_departure, stand_layer

    def _flight_runway_layer(
        self,
        flight: Flight,
        end_candidates: list[Candidate],
        is_departure: bool,
    ) -> tuple[FlightOD, tuple[Candidate, ...], frozenset[EdgeId]]:
        movement = MovementType(flight.movement)
        stand = flight.stand_ref
        assert stand is not None  # validated by _flight_stand_layer
        if flight.runway_ref:
            runway_layer, runway_edges = self._runway_layer(
                flight.runway_ref.upper(), is_departure
            )
            if not runway_layer:
                raise MapMatchingError(
                    MapMatchingFailure.UNKNOWN_OD,
                    f"Unknown or unusable runway in flight OD: {flight.runway_ref!r}",
                    context={"field": "runway", "value": flight.runway_ref},
                )
            od = FlightOD(movement, stand, flight.runway_ref.upper(), "reported")
            return od, runway_layer, runway_edges

        _, all_runway_edges = self._runway_layer(None, is_departure)
        hit = next((c.edge_id for c in end_candidates if c.edge_id in all_runway_edges), None)
        if hit is None:
            raise MapMatchingError(
                MapMatchingFailure.MISSING_OD,
                "Missing flight OD: runway is required when track does not reach a runway",
                context={"fields": ["runway"]},
            )
        raw_ref = str(self.airport_graph.graph.edges[hit].get("ref") or "").upper()
        refs = [ref.strip() for ref in raw_ref.split("/") if ref.strip()]
        od = FlightOD(movement, stand, "/".join(refs) or None, "inferred", hit)
        runway_layer, runway_edges = self._runway_layer(refs[0] if refs else None, is_departure)
        return od, runway_layer, runway_edges

    def _build_runway_layer(
        self, runway_ref: str | None, is_departure: bool
    ) -> tuple[tuple[Candidate, ...], frozenset[EdgeId]]:
        graph = self.airport_graph
        runway_edges: set[EdgeId] = set()
        for u, v, key, data in graph.graph.edges(keys=True, data=True):
            if data.get("aeroway") != "runway":
                continue
            if runway_ref is None or runway_ref in {
                ref.strip() for ref in str(data.get("ref") or "").upper().split("/")
            }:
                runway_edges.update(((u, v, key), (v, u, key)))
        target_interface_edges = (
            set(graph.edge_to_runways)
            if runway_ref is None
            else set(graph.runway_to_edges.get(runway_ref, ()))
        )
        runway_layer = self._directed_router.runway_edge_candidates(
            runway_edges, departure=is_departure
        )
        for node, interface in graph.runway_interfaces.items():
            if not runway_edges.intersection(interface["runway"]):
                continue
            matched_taxiways = [
                edge for edge in interface["taxiway"] if edge in target_interface_edges
            ]
            if matched_taxiways:
                runway_layer.extend(
                    self._directed_router.runway_candidates(
                        node, matched_taxiways, departure=is_departure
                    )
                )
        return tuple(runway_layer), frozenset(runway_edges)

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


def get_od(
    airport_graph: AirportGraph,
    flight: Flight,
    movetype: MovementType | str | None = None,
    *,
    config: MatchConfig = MatchConfig(),
) -> FlightOD:
    """Resolve a flight's surface OD. Reuse Matcher.get_od for many flights on one graph."""
    return Matcher(airport_graph, config).get_od(flight, movetype)


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


def _trim_runway_edges(
    edges: list[DirectedEdge], runway_edges: frozenset[EdgeId], *, is_departure: bool
) -> list[DirectedEdge]:
    """Trim runway-roll edges on the runway side so the path ends at the interface taxiway."""
    if is_departure:
        trimmed = list(edges)
        while trimmed and trimmed[-1].id in runway_edges:
            trimmed.pop()
        return trimmed
    first_taxi = next(
        (i for i, edge in enumerate(edges) if edge.id not in runway_edges),
        len(edges),
    )
    return edges[first_taxi:]
