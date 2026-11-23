"""Domain models and deterministic identifiers for the airport route library."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from airport_surface import AirportGraph, graph_id
from path_map import DirectedEdge, Path, PathRecord


class RouteStatus(StrEnum):
    """Lifecycle and review status of a stored taxi route."""

    CANDIDATE = "candidate"
    VERIFIED = "verified"
    REJECTED = "rejected"
    MANUAL = "manual"


class RouteSource(StrEnum):
    """How a route entry entered the library."""

    MATCHED = "matched"
    MANUAL = "manual"


def normalize_stand_ref(stand_ref: str) -> str:
    value = stand_ref.strip()
    if not value:
        raise ValueError("stand_ref must be a non-empty string")
    return value


def normalize_runway_ref(runway_ref: str | None) -> str | None:
    if runway_ref is None:
        return None
    value = runway_ref.strip().upper()
    return value or None


def normalize_movement(movement: str) -> str:
    value = movement.strip().lower()
    if value not in ("departure", "arrival"):
        raise ValueError(f"Unsupported movement: {movement!r}")
    return value


def serialize_edges(edges: Sequence[DirectedEdge]) -> str:
    """Serialize directed edges in the same compact JSON shape as PathRecord."""
    payload = [[edge.from_, edge.to_, edge.key_] for edge in edges]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def deserialize_edges(edges_json: str) -> tuple[DirectedEdge, ...]:
    raw = json.loads(edges_json)
    return tuple(DirectedEdge(str(edge[0]), str(edge[1]), int(edge[2])) for edge in raw)


def make_route_id(
    graph_identity: str,
    movement: str,
    stand_ref: str,
    runway_ref: str | None,
    edges_json: str,
) -> str:
    """Build a deterministic, idempotent route identifier scoped to graph and OD."""
    seed = "\0".join(
        (
            graph_identity,
            normalize_movement(movement),
            normalize_stand_ref(stand_ref),
            normalize_runway_ref(runway_ref) or "",
            edges_json,
        )
    ).encode("utf-8")
    return f"r-{hashlib.sha256(seed).hexdigest()[:20]}"


@dataclass(frozen=True, slots=True)
class RouteEntry:
    """One deduplicated taxi route template stored in DuckDB."""

    route_id: str
    graph_id: str
    movement: str
    stand_ref: str
    runway_ref: str | None
    runway_interface_node: str
    edges: tuple[DirectedEdge, ...]
    edge_count: int
    total_length_m: float
    status: RouteStatus = RouteStatus.CANDIDATE
    source: RouteSource = RouteSource.MATCHED
    note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def edges_json(self) -> str:
        return serialize_edges(self.edges)

    def to_path_record(self) -> PathRecord:
        return PathRecord(self.graph_id, self.edges)

    def resolve(self, airport_graph: AirportGraph) -> Path:
        return self.to_path_record().resolve(airport_graph)

    @classmethod
    def from_path(
        cls,
        airport_graph: AirportGraph,
        path: Path,
        *,
        movement: str,
        stand_ref: str,
        runway_ref: str | None = None,
        graph_identity: str | None = None,
        status: RouteStatus = RouteStatus.CANDIDATE,
        source: RouteSource = RouteSource.MATCHED,
        note: str | None = None,
    ) -> RouteEntry:
        if not path.edges:
            raise ValueError("Cannot create a RouteEntry from an empty Path")
        normalized_movement = normalize_movement(movement)
        normalized_stand = normalize_stand_ref(stand_ref)
        normalized_runway = normalize_runway_ref(runway_ref)
        identity = graph_identity or graph_id(airport_graph)
        edges_json = serialize_edges(path.edges)
        interface_node = (
            str(path.edges[-1].to_)
            if normalized_movement == "departure"
            else str(path.edges[0].from_)
        )
        return cls(
            route_id=make_route_id(
                identity,
                normalized_movement,
                normalized_stand,
                normalized_runway,
                edges_json,
            ),
            graph_id=identity,
            movement=normalized_movement,
            stand_ref=normalized_stand,
            runway_ref=normalized_runway,
            runway_interface_node=interface_node,
            edges=path.edges,
            edge_count=len(path.edges),
            total_length_m=float(path.total_length),
            status=status,
            source=source,
            note=note,
        )
