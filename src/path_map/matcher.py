"""Public HMM map matching entry point."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import networkx as nx
import pandas as pd
from shapely.geometry import Point
from traffic.core import Flight, Traffic

from airport_surface import AirportGraph

from .candidates import Candidate, CandidateIndex
from .hmm import NetworkRouter, viterbi
from .path import DirectedEdge, MovementType, Path


class MapMatchingError(ValueError):
    """Raised when observations cannot be matched without guessing."""


@dataclass(frozen=True, slots=True)
class MatchConfig:
    search_radius: float = 40.0
    max_candidates: int = 6
    gps_sigma: float = 10.0
    transition_beta: float = 20.0
    max_time_gap: timedelta | None = timedelta(minutes=2)

    def __post_init__(self) -> None:
        if min(self.search_radius, self.gps_sigma, self.transition_beta) <= 0:
            raise ValueError("Distance parameters must be positive")
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
        *,
        movement_type: MovementType = MovementType.UNKNOWN,
    ) -> Path:
        """Match one flight while reusing the graph index and router."""
        observations = _observations(self.airport_graph, flight, self.config)
        layers = [
            self.index.candidates(
                index,
                point,
                self.config.search_radius,
                self.config.max_candidates,
            )
            for index, point in enumerate(observations)
        ]
        empty = [index for index, layer in enumerate(layers) if not layer]
        if empty:
            raise MapMatchingError(f"No edge candidates for observation(s): {empty}")
        try:
            states, transitions = viterbi(
                layers,
                observations,
                self.router,
                self.config.gps_sigma,
                self.config.transition_beta,
            )
        except nx.NetworkXNoPath as exc:
            raise MapMatchingError("No connected network path matches all observations") from exc
        return Path(
            self.airport_graph,
            _recover(transitions, states[0]),
            movement_type=movement_type,
        )


def _observations(ag: AirportGraph, flight: Flight, config: MatchConfig) -> list[Point]:
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
        if config.max_time_gap is not None and (frame.timestamp.diff() > config.max_time_gap).any():
            raise MapMatchingError("Flight contains a time gap larger than max_time_gap")
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
    *,
    movement_type: MovementType = MovementType.UNKNOWN,
) -> Path:
    """Match ADS-B observations to a continuous airport-network path with an HMM."""
    return Matcher(AG, config).map_flight(f, movement_type=movement_type)


def map_traffic(
    airport_graph: AirportGraph,
    traffic: Traffic,
    config: MatchConfig | None = None,
    *,
    movement_type: MovementType = MovementType.UNKNOWN,
) -> BatchMatchResult:
    """Match every flight independently without stopping on matching failures."""
    matches: list[tuple[Any, Path]] = []
    failures: list[MatchFailure] = []
    matcher = Matcher(airport_graph, config)

    for flight in traffic:
        flight_id = flight.flight_id
        try:
            path = matcher.map_flight(
                flight,
                movement_type=movement_type,
            )
        except MapMatchingError as error:
            failures.append(MatchFailure(flight_id, str(error)))
            continue
        matches.append((flight_id, path))

    return BatchMatchResult(matches, failures)
