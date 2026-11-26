"""Fine-grained (stand) to coarse-grained (cluster) historical route lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from airport_surface import AirportGraph, graph_id
from path_map import MatchConfig, Path, get_od

from .models import RouteEntry, normalize_movement, normalize_runway_ref, normalize_stand_ref
from .repository import RouteLibraryRepository

LookupGranularity = Literal["stand", "cluster", "none"]


@dataclass(frozen=True, slots=True)
class HistoricalRouteLookup:
    """Result of resolving historical routes for an OD with cluster fallback."""

    granularity: LookupGranularity
    entries: tuple[RouteEntry, ...]
    cluster_id: int | None = None

    def resolve_paths(
        self,
        airport_graph: AirportGraph,
        *,
        actual_graph_id: str | None = None,
    ) -> list[Path]:
        identity = actual_graph_id or graph_id(airport_graph)
        return [entry.resolve(airport_graph, actual_graph_id=identity) for entry in self.entries]


def _runway_candidates(runway_ref: str | None) -> tuple[str, ...] | None:
    normalized = normalize_runway_ref(runway_ref)
    if normalized is None:
        return None
    parts = [part.strip() for part in normalized.split("/") if part.strip()]
    return tuple(dict.fromkeys([normalized, *parts]))


def find_historical_routes(
    repository: RouteLibraryRepository,
    airport_graph: AirportGraph,
    *,
    movement: str,
    stand_ref: str,
    runway_ref: str | None = None,
    graph_identity: str | None = None,
    include_rejected: bool = False,
) -> HistoricalRouteLookup:
    """Query fine-grained stand routes first; fall back to same-cluster stand routes."""
    identity = graph_identity or graph_id(airport_graph)
    normalized_movement = normalize_movement(movement)
    normalized_stand = normalize_stand_ref(stand_ref)
    runway_refs = _runway_candidates(runway_ref)
    cluster = airport_graph.cluster_for_stand(normalized_stand)
    cluster_id = cluster.c_id if cluster is not None else None

    fine = repository.find_by_od(
        graph_id=identity,
        movement=normalized_movement,
        stand_ref=normalized_stand,
        runway_refs=runway_refs,
        exclude_rejected=not include_rejected,
    )
    if fine:
        return HistoricalRouteLookup(
            granularity="stand",
            entries=tuple(fine),
            cluster_id=cluster_id,
        )

    if cluster is not None:
        stand_refs = airport_graph.stand_refs_in_cluster(cluster.c_id)
        if stand_refs:
            coarse = repository.find_by_od(
                graph_id=identity,
                movement=normalized_movement,
                stand_refs=stand_refs,
                runway_refs=runway_refs,
                exclude_rejected=not include_rejected,
            )
            if coarse:
                return HistoricalRouteLookup(
                    granularity="cluster",
                    entries=tuple(coarse),
                    cluster_id=cluster.c_id,
                )

    return HistoricalRouteLookup(
        granularity="none",
        entries=(),
        cluster_id=cluster_id,
    )


def get_his_path(
    flight: Any,
    airport_graph: AirportGraph,
    repository: RouteLibraryRepository,
    *,
    movetype: str | None = None,
    config: MatchConfig = MatchConfig(),
    graph_identity: str | None = None,
    include_rejected: bool = False,
) -> list[Path]:
    """Resolve OD for ``flight`` and return fine-grained or cluster-level historical paths."""
    od = get_od(airport_graph, flight, movetype=movetype, config=config)
    identity = graph_identity or graph_id(airport_graph)
    lookup = find_historical_routes(
        repository,
        airport_graph,
        movement=od.movement.value,
        stand_ref=od.stand_ref,
        runway_ref=od.runway_ref,
        graph_identity=identity,
        include_rejected=include_rejected,
    )
    return lookup.resolve_paths(airport_graph, actual_graph_id=identity)
