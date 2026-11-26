"""High-precision anomaly detection for obviously broken or extreme-detour taxi routes."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from airport_surface import AirportGraph, EdgeId, canonical_edge_id

from .models import RouteEntry, RouteStatus

AnomalyCode = Literal["repeated_edge", "closed_loop", "extreme_detour"]

EXTREME_DETOUR_RATIO = 1.8
EXTREME_DETOUR_EXCESS_M = 800.0
EXTREME_DETOUR_MAX_FLIGHTS = 2
EXTREME_DETOUR_MAX_TRAFFIC_SHARE = 0.1
EXTREME_DETOUR_MIN_GROUP_FLIGHTS = 3
EXTREME_DETOUR_MIN_GROUP_ROUTES = 2


@dataclass(frozen=True, slots=True)
class RouteAnomalyReason:
    """One explainable high-confidence anomaly reason on a taxi route."""

    code: AnomalyCode
    message: str


@dataclass(frozen=True, slots=True)
class RouteAnomalyReport:
    """Anomaly detection verdict for one RouteEntry."""

    route_id: str
    reasons: tuple[RouteAnomalyReason, ...]

    @property
    def is_anomalous(self) -> bool:
        return bool(self.reasons)


def _is_parking_edge(airport_graph: AirportGraph, edge: EdgeId) -> bool:
    u, v, key = edge
    if airport_graph.graph.has_edge(u, v, key):
        return airport_graph.graph.edges[u, v, key].get("aeroway") == "parking_position"
    if airport_graph.graph.has_edge(v, u, key):
        return airport_graph.graph.edges[v, u, key].get("aeroway") == "parking_position"
    return False


def _detect_repeated_edge(
    entry: RouteEntry,
    airport_graph: AirportGraph,
) -> RouteAnomalyReason | None:
    occurrences: dict[EdgeId, list[int]] = defaultdict(list)
    for index, edge in enumerate(entry.edges):
        canon = canonical_edge_id((edge.from_, edge.to_, edge.key_))
        occurrences[canon].append(index)

    repeated = {edge: indices for edge, indices in occurrences.items() if len(indices) > 1}
    if not repeated:
        return None

    # Allow a single legitimate pushback reversal near the stand for departures.
    if entry.movement == "departure" and len(repeated) == 1:
        only_edge, indices = next(iter(repeated.items()))
        if len(indices) == 2 and (max(indices) <= 2 or _is_parking_edge(airport_graph, only_edge)):
            return None

    max_hits = max(len(indices) for indices in repeated.values())
    return RouteAnomalyReason(
        code="repeated_edge",
        message=f"重复经过同一物理边（{len(repeated)} 条边重复，最高 {max_hits} 次）",
    )


def _detect_closed_loop(entry: RouteEntry) -> RouteAnomalyReason | None:
    if len(entry.edges) < 3:
        return None
    first_seen: dict[str, int] = {entry.edges[0].from_: 0}
    for step, edge in enumerate(entry.edges, start=1):
        node = edge.to_
        previous = first_seen.get(node)
        if previous is not None:
            cycle_edges = step - previous
            if cycle_edges >= 3:
                return RouteAnomalyReason(
                    code="closed_loop",
                    message=f"存在闭合环路（经 {cycle_edges} 条边后回到节点 {node}）",
                )
        else:
            first_seen[node] = step
    return None


def _weighted_median_length(entries: Sequence[RouteEntry]) -> float:
    weighted = sorted(
        ((entry.total_length_m, max(entry.flight_count, 1)) for entry in entries),
        key=lambda item: item[0],
    )
    total_weight = sum(weight for _, weight in weighted)
    threshold = total_weight / 2.0
    acc = 0.0
    for length_m, weight in weighted:
        acc += weight
        if acc >= threshold:
            return length_m
    return weighted[-1][0]


def _runway_bucket(runway_ref: str) -> str:
    return runway_ref


def _detect_extreme_detour(
    entry: RouteEntry,
    *,
    fine_peers: Sequence[RouteEntry],
    cluster_peers: Sequence[RouteEntry],
) -> RouteAnomalyReason | None:
    if entry.flight_count > EXTREME_DETOUR_MAX_FLIGHTS:
        return None

    peers: Sequence[RouteEntry] | None = None
    peer_label = "同 OD"
    fine_flights = sum(item.flight_count for item in fine_peers)
    if (
        len(fine_peers) >= EXTREME_DETOUR_MIN_GROUP_ROUTES
        and fine_flights >= EXTREME_DETOUR_MIN_GROUP_FLIGHTS
    ):
        peers = fine_peers
    else:
        cluster_flights = sum(item.flight_count for item in cluster_peers)
        if (
            len(cluster_peers) >= EXTREME_DETOUR_MIN_GROUP_ROUTES
            and cluster_flights >= EXTREME_DETOUR_MIN_GROUP_FLIGHTS
        ):
            peers = cluster_peers
            peer_label = "同类别"

    if peers is None:
        return None

    total_flights = sum(item.flight_count for item in peers)
    if total_flights <= 0:
        return None
    if entry.flight_count / total_flights > EXTREME_DETOUR_MAX_TRAFFIC_SHARE:
        return None

    baseline_m = _weighted_median_length(peers)
    if baseline_m <= 0:
        return None
    ratio = entry.total_length_m / baseline_m
    excess_m = entry.total_length_m - baseline_m
    if ratio >= EXTREME_DETOUR_RATIO and excess_m >= EXTREME_DETOUR_EXCESS_M:
        return RouteAnomalyReason(
            code="extreme_detour",
            message=(
                f"极端绕行：长度 {round(entry.total_length_m)} m，"
                f"为{peer_label}基准 {round(baseline_m)} m 的 {ratio:.2f} 倍"
                f"（仅 {entry.flight_count}/{total_flights} 架次）"
            ),
        )
    return None


def detect_route_anomalies(
    entries: Sequence[RouteEntry],
    *,
    airport_graph: AirportGraph,
    reference_entries: Sequence[RouteEntry] | None = None,
) -> list[RouteAnomalyReport]:
    """Run high-precision anomaly checks on ``entries`` without flagging normal alternates."""
    pool = [
        item
        for item in (reference_entries if reference_entries is not None else entries)
        if item.status != RouteStatus.REJECTED
    ]

    by_fine_od: dict[tuple[str, str, str], list[RouteEntry]] = defaultdict(list)
    by_cluster_od: dict[tuple[str, int, str], list[RouteEntry]] = defaultdict(list)
    for item in pool:
        rwy = _runway_bucket(item.runway_ref)
        by_fine_od[(item.movement, item.stand_ref, rwy)].append(item)
        cluster = airport_graph.cluster_for_stand(item.stand_ref)
        if cluster is not None:
            by_cluster_od[(item.movement, cluster.c_id, rwy)].append(item)

    reports: list[RouteAnomalyReport] = []
    seen_ids: Counter[str] = Counter()
    for entry in entries:
        if seen_ids[entry.route_id]:
            continue
        seen_ids[entry.route_id] += 1
        reasons: list[RouteAnomalyReason] = []
        repeated = _detect_repeated_edge(entry, airport_graph)
        if repeated is not None:
            reasons.append(repeated)
        loop = _detect_closed_loop(entry)
        if loop is not None:
            reasons.append(loop)
        rwy = _runway_bucket(entry.runway_ref)
        fine_peers = by_fine_od.get((entry.movement, entry.stand_ref, rwy), ())
        cluster = airport_graph.cluster_for_stand(entry.stand_ref)
        cluster_peers = (
            by_cluster_od.get((entry.movement, cluster.c_id, rwy), ())
            if cluster is not None
            else ()
        )
        detour = _detect_extreme_detour(
            entry,
            fine_peers=fine_peers,
            cluster_peers=cluster_peers,
        )
        if detour is not None:
            reasons.append(detour)
        reports.append(RouteAnomalyReport(route_id=entry.route_id, reasons=tuple(reasons)))
    return reports
