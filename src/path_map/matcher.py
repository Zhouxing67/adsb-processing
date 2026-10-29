"""Public HMM map matching entry point."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import networkx as nx
import pandas as pd
from shapely.geometry import Point

from adsb import Flight, Flights
from airport_surface import AirportGraph

from .candidates import Candidate, CandidateIndex
from .hmm import NetworkRouter, viterbi
from .path import DirectedEdge, Path

logger = logging.getLogger(__name__)


class MapMatchingError(ValueError):
    """Raised when observations cannot be matched without guessing."""


@dataclass(frozen=True, slots=True)
class MatchConfig:
    search_radius: float = 40.0
    max_search_radius: float = 120.0
    max_candidates: int = 40
    gps_sigma: float = 10.0
    transition_beta: float = 20.0

    def __post_init__(self) -> None:
        distances = (
            self.search_radius,
            self.max_search_radius,
            self.gps_sigma,
            self.transition_beta,
        )
        if any(not math.isfinite(value) or value <= 0 for value in distances):
            raise ValueError("Distance parameters must be finite and positive")
        if self.max_search_radius < self.search_radius:
            raise ValueError("max_search_radius must not be smaller than search_radius")
        if isinstance(self.max_candidates, bool) or not isinstance(self.max_candidates, int):
            raise ValueError("max_candidates must be a positive integer")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be a positive integer")


@dataclass(frozen=True, slots=True)
class MatchFailure:
    """One flight that could not be matched, together with the reason."""

    flight_id: Any
    reason: str


@dataclass(frozen=True, slots=True)
class BatchMatchResult:
    """Successful matches and expected data-quality failures for one batch."""

    matches: list[tuple[Any, Path]]
    failures: list[MatchFailure]


class Matcher:
    """Reusable matcher state for many flights on the same airport graph."""

    def __init__(
        self,
        airport_graph: AirportGraph,
        config: MatchConfig | None = None,
    ) -> None:
        self.airport_graph = airport_graph
        self.config = config or MatchConfig()
        self.index = CandidateIndex(airport_graph)
        self.router = NetworkRouter(airport_graph, self.index)

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
        """Find candidates, expanding the radius only when none are found."""
        radius = self.config.search_radius
        while True:
            candidates = self.index.candidates(
                observation_index,
                point,
                radius,
                self.config.max_candidates,
            )
            if candidates or radius >= self.config.max_search_radius:
                if any(candidate.edge_id[0] == candidate.edge_id[1] for candidate in candidates):
                    raise MapMatchingError(
                        "Map matching candidates on self-loop edges are not supported"
                    )
                return candidates
            radius = min(radius * 2, self.config.max_search_radius)


def _observations(ag: AirportGraph, flight: Flight) -> list[Point]:
    required = {"longitude", "latitude"}
    if not required <= set(flight.data.columns):
        raise MapMatchingError("Flight must contain longitude and latitude columns")
    columns = ["longitude", "latitude"]
    if "timestamp" in flight.data.columns:
        columns.append("timestamp")
    frame = flight.data.loc[:, columns].dropna(subset=["longitude", "latitude"])
    if "timestamp" in frame:
        try:
            frame = frame.assign(timestamp=pd.to_datetime(frame.timestamp, utc=True))
        except (TypeError, ValueError) as exc:
            raise MapMatchingError("Flight contains invalid timestamps") from exc
        frame = frame.sort_values("timestamp", kind="stable")
    if len(frame) < 2:
        raise MapMatchingError("At least two valid observations are required")
    x, y = ag.project.transform(frame.longitude.to_numpy(), frame.latitude.to_numpy())
    return [Point(float(px), float(py)) for px, py in zip(x, y)]


def _append_transition_edges(
    output: list[DirectedEdge], edges: tuple[DirectedEdge, ...]
) -> None:
    """Join transitions, collapsing only continued travel on their shared boundary edge."""
    start = 1 if output and edges and output[-1] == edges[0] else 0
    output.extend(edges[start:])


def _recover(transitions: list, first: Candidate) -> list[DirectedEdge]:
    if not transitions:
        u, v, key = first.edge_id
        return [DirectedEdge(u, v, key)]
    output: list[DirectedEdge] = []
    for transition in transitions:
        _append_transition_edges(output, transition.edges)
    return output


def map_flight(
    AG: AirportGraph,
    f: Flight,
    config: MatchConfig | None = None,
) -> Path:
    """Match ADS-B observations to a continuous airport-network path with an HMM."""
    return Matcher(AG, config).map_flight(f)


def map_flights(
    airport_graph: AirportGraph,
    flights: Flights,
    config: MatchConfig | None = None,
) -> BatchMatchResult:
    """Match every flight independently without stopping on matching failures."""
    matches: list[tuple[Any, Path]] = []
    failures: list[MatchFailure] = []
    matcher = Matcher(airport_graph, config)

    for flight in flights:
        flight_id = flight.flight_id
        try:
            path = matcher.map_flight(flight)
        except MapMatchingError as error:
            failures.append(MatchFailure(flight_id, str(error)))
            continue
        matches.append((flight_id, path))

    return BatchMatchResult(matches, failures)
