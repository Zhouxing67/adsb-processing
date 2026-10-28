"""Public HMM map matching entry point."""

from __future__ import annotations

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
        if (
            min(
                self.search_radius,
                self.max_search_radius,
                self.gps_sigma,
                self.transition_beta,
            )
            <= 0
        ):
            raise ValueError("Distance parameters must be positive")
        if self.max_search_radius < self.search_radius:
            raise ValueError("max_search_radius must not be smaller than search_radius")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be at least one")


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
        try:
            self.index = CandidateIndex(airport_graph)
        except ValueError as exc:
            raise MapMatchingError(str(exc)) from exc
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

        if not layers:
            raise MapMatchingError("No edge candidates for any observation")
        self.router.clear_route_cache()
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
        return Path(self.airport_graph, _recover(transitions, states[0]))

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


def _recover(transitions: list, first: Candidate) -> list[DirectedEdge]:
    if not transitions:
        u, v, key = first.edge_id
        return [DirectedEdge(u, v, key)]
    output: list[DirectedEdge] = []
    for transition in transitions:
        for edge in transition.edges:
            if output and output[-1] == edge:
                continue
            output.append(edge)
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
