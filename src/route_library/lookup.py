"""Fine-grained (stand) to coarse-grained (cluster) historical route lookup."""

from __future__ import annotations

from collections import defaultdict
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
    if runway_ref is None or not runway_ref.strip():
        return None
    normalized = normalize_runway_ref(runway_ref)
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


def _matches_runway(entry_runway: str | None, runway_candidates: set[str] | None) -> bool:
    if runway_candidates is None:
        return True
    if entry_runway is None:
        return False
    return entry_runway in runway_candidates


class HistoricalRouteQuery:
    """In-memory cached fine-to-coarse historical route query for downstream callers."""

    def __init__(
        self,
        airport_graph: AirportGraph,
        repository: RouteLibraryRepository,
        *,
        graph_identity: str | None = None,
        include_rejected: bool = False,
    ) -> None:
        self.airport_graph = airport_graph
        self.repository = repository
        self.graph_id = graph_identity or graph_id(airport_graph)
        self.include_rejected = include_rejected
        self._by_stand: dict[tuple[str, str], list[RouteEntry]] = defaultdict(list)
        self._path_cache: dict[str, Path] = {}
        self.reload()

    def reload(self) -> None:
        """Reload routes for ``self.graph_id`` into memory and clear resolved path cache."""
        entries = self.repository.find_by_od(
            graph_id=self.graph_id,
            exclude_rejected=not self.include_rejected,
        )
        by_stand: dict[tuple[str, str], list[RouteEntry]] = defaultdict(list)
        for entry in entries:
            by_stand[(entry.movement, entry.stand_ref)].append(entry)
        for bucket in by_stand.values():
            bucket.sort(key=lambda item: (-item.flight_count, item.total_length_m, item.route_id))
        self._by_stand = by_stand
        self._path_cache.clear()

    def _resolve_entries(self, entries: tuple[RouteEntry, ...]) -> list[Path]:
        paths: list[Path] = []
        for entry in entries:
            cached = self._path_cache.get(entry.route_id)
            if cached is None:
                cached = entry.resolve(self.airport_graph, actual_graph_id=self.graph_id)
                self._path_cache[entry.route_id] = cached
            paths.append(cached)
        return paths

    def lookup_by_od(
        self,
        movement: str,
        stand_ref: str,
        runway_ref: str | None = None,
    ) -> HistoricalRouteLookup:
        """Look up fine-grained stand routes first, falling back to same-cluster routes."""
        normalized_movement = normalize_movement(movement)
        normalized_stand = normalize_stand_ref(stand_ref)
        candidates = _runway_candidates(runway_ref)
        runway_set = set(candidates) if candidates is not None else None
        cluster = self.airport_graph.cluster_for_stand(normalized_stand)
        cluster_id = cluster.c_id if cluster is not None else None

        fine = [
            entry
            for entry in self._by_stand.get((normalized_movement, normalized_stand), ())
            if _matches_runway(entry.runway_ref, runway_set)
        ]
        if fine:
            return HistoricalRouteLookup(
                granularity="stand",
                entries=tuple(fine),
                cluster_id=cluster_id,
            )

        if cluster is not None:
            seen: set[str] = set()
            coarse: list[RouteEntry] = []
            for peer_stand in self.airport_graph.stand_refs_in_cluster(cluster.c_id):
                for entry in self._by_stand.get((normalized_movement, peer_stand), ()):
                    if entry.route_id in seen:
                        continue
                    if _matches_runway(entry.runway_ref, runway_set):
                        seen.add(entry.route_id)
                        coarse.append(entry)
            if coarse:
                coarse.sort(
                    key=lambda item: (-item.flight_count, item.total_length_m, item.route_id)
                )
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

    def get_paths_by_od(
        self,
        movement: str,
        stand_ref: str,
        runway_ref: str | None = None,
    ) -> list[Path]:
        """Return ordered historical Path list for pure planned OD fields."""
        lookup = self.lookup_by_od(movement, stand_ref, runway_ref)
        return self._resolve_entries(lookup.entries)

    def get_paths_for_flight(
        self,
        flight: Any,
        *,
        movetype: str | None = None,
        config: MatchConfig = MatchConfig(),
    ) -> list[Path]:
        """Resolve OD from ``flight`` and return ordered historical Path list."""
        od = get_od(self.airport_graph, flight, movetype=movetype, config=config)
        return self.get_paths_by_od(od.movement.value, od.stand_ref, od.runway_ref)
