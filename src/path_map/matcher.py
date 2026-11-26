"""Public HMM map matching entry point."""

from __future__ import annotations

import logging
from functools import cached_property, lru_cache

import networkx as nx
from shapely.geometry import Point

from airport_surface import AirportGraph
from flight import Flight, MovementType

from .candidates import Candidate, CandidateIndex
from .hmm import decode_route
from .models import FlightOD, MapMatchingError, MapMatchingFailure, MatchConfig
from .path import DirectedEdge, EdgeId, Path
from .recovery import project_observations, recover_edges, trim_runway_edges
from .router import DirectedNetworkRouter

logger = logging.getLogger(__name__)


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
            same_edge_jitter_m=self.config.same_edge_jitter_m,
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
        od, _, _ = self._flight_runway_layer(flight, candidates, is_departure)
        return od

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
        reversal_origin = (
            Point(
                sum(c.point.x for c in stand_layer) / len(stand_layer),
                sum(c.point.y for c in stand_layer) / len(stand_layer),
            )
            if is_departure
            else None
        )
        try:
            states, transitions = decode_route(
                [start, *directed_layers, end],
                boundary_observations,
                self._directed_router,
                self.config.gps_sigma,
                self.config.transition_beta,
                allow_single_reversal=is_departure,
                max_pushback_radius_m=self.config.max_pushback_radius_m,
                reversal_origin=reversal_origin,
                max_transition_detour_m=self.config.max_transition_detour_m,
                has_boundary_layers=True,
            )
        except nx.NetworkXNoPath as exc:
            raise MapMatchingError(
                MapMatchingFailure.NO_LEGAL_PATH,
                "No turn-constrained path matches the observations and flight OD",
            ) from exc
        edges = trim_runway_edges(
            recover_edges([t.edges for t in transitions], states[0].edge_id),
            runway_edges,
            is_departure=is_departure,
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
            states, transitions = decode_route(
                directed_layers,
                directed_observations,
                self._directed_router,
                self.config.gps_sigma,
                self.config.transition_beta,
                allow_single_reversal=is_departure,
                max_pushback_radius_m=self.config.max_pushback_radius_m,
                max_transition_detour_m=self.config.max_transition_detour_m,
                has_boundary_layers=False,
            )
        except nx.NetworkXNoPath:
            return None
        _, all_runway_edges = self._runway_layer(None, is_departure)
        edges = trim_runway_edges(
            recover_edges([t.edges for t in transitions], states[0].edge_id),
            all_runway_edges,
            is_departure=is_departure,
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
