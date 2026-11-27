"""High-precision anomaly detection for obviously looped taxi routes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .models import RouteEntry

AnomalyCode = Literal["closed_loop"]


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


def _detect_closed_loop(entry: RouteEntry) -> RouteAnomalyReason | None:
    """Flag a cycle of >= 3 edges (excludes 2-step pushback reversals A -> B -> A)."""
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


def detect_route_anomalies(
    entries: Sequence[RouteEntry],
) -> list[RouteAnomalyReport]:
    """Flag only unambiguous closed-loop routes (>= 3 edges) to avoid false positives."""
    reports: list[RouteAnomalyReport] = []
    seen_ids: Counter[str] = Counter()
    for entry in entries:
        if seen_ids[entry.route_id]:
            continue
        seen_ids[entry.route_id] += 1
        loop = _detect_closed_loop(entry)
        reasons = (loop,) if loop is not None else ()
        reports.append(RouteAnomalyReport(route_id=entry.route_id, reasons=reasons))
    return reports
