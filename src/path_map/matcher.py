"""Public map matching entry point using edge-anchored Dual-Graph DTW."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cached_property, lru_cache

import networkx as nx
from shapely.geometry import Point

from airport_surface import AirportGraph
from flight import Flight, MovementType

from .candidates import Candidate, CandidateIndex
from .edge_dtw import decode_arrival_route, decode_departure_route
from .models import FlightOD, MapMatchingError, MapMatchingFailure, MatchConfig
from .path import DirectedEdge, DirectedEdgeId, EdgeId, Path
from .recovery import project_observations, trim_runway_edges
from .router import DirectedNetworkRouter

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _RunwayBoundary:
    """Directed runway-side boundary edges (interface + roll) and runway-roll edges to trim."""

    boundary_edges: frozenset[DirectedEdgeId]
    roll_edges: frozenset[DirectedEdgeId]


@dataclass(frozen=True, slots=True)
class _RunwaySpec:
    """Resolved runway OD label together with its boundary and trim edge sets."""

    od: FlightOD
    boundary_edges: frozenset[DirectedEdgeId]
    roll_edges: frozenset[DirectedEdgeId]


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
        self._runway_boundary = lru_cache(maxsize=64)(self._build_runway_boundary)

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
        is_departure, _ = self._flight_stand_edges(flight)
        candidates = []
        if not flight.runway_ref:
            observations = project_observations(self.airport_graph, flight)
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
        return self._flight_runway_spec(flight, candidates, is_departure).od

    def map_flight(self, flight: Flight) -> Path:
        """Match a flight: pure turn-constrained trajectory first, OD prior fallback second."""
        is_departure = self._validate_flight_direction(flight)
        observations = project_observations(self.airport_graph, flight)
        matched_observations: list[Point] = []
        layers: list[list[Candidate]] = []

        for index, point in enumerate(observations):
            candidates = self._candidates(index, point)
            if not candidates:
                continue
            matched_observations.append(point)
            layers.append(candidates)

        if not layers:
            raise MapMatchingError(
                MapMatchingFailure.NO_CANDIDATES,
                "At least one observation with edge candidates is required; got 0",
                context={"observation_count": len(observations)},
            )
        logger.debug(
            "Edge-DTW map matching retained %d of %d observations",
            len(layers),
            len(observations),
        )

        router = self._directed_router
        all_runway_roll_edges = self._runway_boundary(None, is_departure).roll_edges

        # Phase 1: Pure trajectory decoding without OD boundary layers.
        try:
            phase1_edges = self._decode(layers, matched_observations, is_departure=is_departure)
        except nx.NetworkXNoPath:
            phase1_edges = []
        if phase1_edges:
            trimmed = trim_runway_edges(
                phase1_edges, all_runway_roll_edges, is_departure=is_departure
            )
            if trimmed and self._is_valid_pure_path(flight, trimmed, is_departure):
                return Path(self.airport_graph, trimmed)

        # Phase 2: OD-bounded decoding with zero-emission start/end edge layers.
        _, stand_edges = self._flight_stand_edges(flight)
        runway = self._flight_runway_spec(
            flight, layers[-1] if is_departure else layers[0], is_departure
        )
        start_edges, end_edges = (
            (stand_edges, runway.boundary_edges)
            if is_departure
            else (runway.boundary_edges, stand_edges)
        )
        # Anchor pushback radius to the known stand centroid rather than observations[0],
        # so missing early ADS-B frames near the stand do not shift the pushback zone.
        reversal_origin = router.edge_centroid(stand_edges) if is_departure else None
        try:
            edges = self._decode(
                layers,
                matched_observations,
                is_departure=is_departure,
                start_edges=start_edges,
                end_edges=end_edges,
                reversal_origin=reversal_origin,
            )
        except nx.NetworkXNoPath as exc:
            raise MapMatchingError(
                MapMatchingFailure.NO_LEGAL_PATH,
                "No turn-constrained path matches the observations and flight OD",
            ) from exc
        trimmed = trim_runway_edges(edges, runway.roll_edges, is_departure=is_departure)
        if not trimmed:
            raise MapMatchingError(
                MapMatchingFailure.NO_MOVEMENT,
                "Retained candidates have no along-network movement; "
                "a directed path cannot be determined",
            )
        return Path(self.airport_graph, trimmed)

    def _decode(
        self,
        layers: list[list[Candidate]],
        observations: list[Point],
        *,
        is_departure: bool,
        start_edges: frozenset[DirectedEdgeId] | None = None,
        end_edges: frozenset[DirectedEdgeId] | None = None,
        reversal_origin: Point | None = None,
    ) -> list[DirectedEdge]:
        if is_departure:
            return decode_departure_route(
                layers,
                observations,
                self._directed_router,
                self.config.gps_sigma,
                length_scale_m=self.config.length_scale_m,
                max_pushback_radius_m=self.config.max_pushback_radius_m,
                reversal_origin=reversal_origin,
                start_edges=start_edges,
                end_edges=end_edges,
            )
        return decode_arrival_route(
            layers,
            observations,
            self._directed_router,
            self.config.gps_sigma,
            length_scale_m=self.config.length_scale_m,
            start_edges=start_edges,
            end_edges=end_edges,
        )

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

    def _flight_stand_edges(self, flight: Flight) -> tuple[bool, frozenset[DirectedEdgeId]]:
        is_departure = self._validate_flight_direction(flight)
        if not flight.stand_ref:
            raise MapMatchingError(
                MapMatchingFailure.MISSING_OD,
                "Missing flight OD: stand is required",
                context={"fields": ["stand"]},
            )
        stand_edges = self._directed_router.directed_stand_edges(
            self.airport_graph.stand_to_edges.get(flight.stand_ref, ())
        )
        if not stand_edges:
            raise MapMatchingError(
                MapMatchingFailure.UNKNOWN_OD,
                f"Unknown or unusable stand in flight OD: {flight.stand_ref!r}",
                context={"field": "stand", "value": flight.stand_ref},
            )
        return is_departure, stand_edges

    def _flight_runway_spec(
        self,
        flight: Flight,
        end_candidates: list[Candidate],
        is_departure: bool,
    ) -> _RunwaySpec:
        movement = MovementType(flight.movement)
        stand = flight.stand_ref
        assert stand is not None  # validated by _flight_stand_edges
        if flight.runway_ref:
            runway_ref = flight.runway_ref.upper()
            boundary = self._runway_boundary(runway_ref, is_departure)
            if not boundary.boundary_edges:
                raise MapMatchingError(
                    MapMatchingFailure.UNKNOWN_OD,
                    f"Unknown or unusable runway in flight OD: {flight.runway_ref!r}",
                    context={"field": "runway", "value": flight.runway_ref},
                )
            od = FlightOD(movement, stand, runway_ref, "reported")
            return _RunwaySpec(od, boundary.boundary_edges, boundary.roll_edges)

        all_roll_edges = self._runway_boundary(None, is_departure).roll_edges
        hit = next((c.edge_id for c in end_candidates if c.edge_id in all_roll_edges), None)
        if hit is None:
            raise MapMatchingError(
                MapMatchingFailure.MISSING_OD,
                "Missing flight OD: runway is required when track does not reach a runway",
                context={"fields": ["runway"]},
            )
        raw_ref = str(self.airport_graph.graph.edges[hit].get("ref") or "").upper()
        refs = [ref.strip() for ref in raw_ref.split("/") if ref.strip()]
        od = FlightOD(movement, stand, "/".join(refs) or None, "inferred", hit)
        boundary = self._runway_boundary(refs[0] if refs else None, is_departure)
        return _RunwaySpec(od, boundary.boundary_edges, boundary.roll_edges)

    def _build_runway_boundary(
        self, runway_ref: str | None, is_departure: bool
    ) -> _RunwayBoundary:
        graph = self.airport_graph
        roll_edges: set[DirectedEdgeId] = set()
        for u, v, key, data in graph.graph.edges(keys=True, data=True):
            if data.get("aeroway") != "runway":
                continue
            if runway_ref is None or runway_ref in {
                ref.strip() for ref in str(data.get("ref") or "").upper().split("/")
            }:
                roll_edges.update(((u, v, key), (v, u, key)))
        target_interface_edges: set[EdgeId] = (
            set(graph.edge_to_runways)
            if runway_ref is None
            else set(graph.runway_to_edges.get(runway_ref, ()))
        )
        boundary_edges: set[DirectedEdgeId] = {
            edge for edge in roll_edges if edge in self._directed_router.lengths
        }
        for node, interface in graph.runway_interfaces.items():
            if not roll_edges.intersection(interface["runway"]):
                continue
            matched_taxiways = [
                edge for edge in interface["taxiway"] if edge in target_interface_edges
            ]
            if matched_taxiways:
                boundary_edges.update(
                    self._directed_router.directed_runway_interface_edges(
                        node, matched_taxiways, departure=is_departure
                    )
                )
        return _RunwayBoundary(frozenset(boundary_edges), frozenset(roll_edges))

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
