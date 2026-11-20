"""Shared streaming batch execution and summary for matching callers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from time import perf_counter

from flight import Flight

from .matcher import MapMatchingError, Matcher
from .path import Path


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    key: str
    observation_count: int | None
    elapsed_seconds: float
    path: Path | None = None
    reason: str | None = None
    failure_type: str | None = None
    error_kind: str | None = None

    @property
    def status(self) -> str:
        return "success" if self.failure_type is None else "failed"


def match_batch(
    matcher: Matcher,
    flights: Iterable[tuple[str, Flight | Callable[[], Flight]]],
    *,
    capture_system_errors: bool = False,
) -> Iterator[MatchOutcome]:
    """Match ordered inputs one by one; callers can supply a lazy flight loader."""
    for key, source in flights:
        started = perf_counter()
        count = None
        try:
            flight = source() if callable(source) else source
            count = flight.point_count
            started = perf_counter()
            path = matcher.map_flight(flight)
        except MapMatchingError as error:
            reason = str(error)
            yield MatchOutcome(
                key, count, perf_counter() - started,
                reason=reason, failure_type=error.code.value, error_kind="matching",
            )
        except Exception as error:
            if not capture_system_errors:
                raise
            yield MatchOutcome(
                key, count, perf_counter() - started,
                reason=f"系统异常（非正常匹配失败）：{type(error).__name__}: {error}",
                failure_type="system", error_kind="system",
            )
        else:
            yield MatchOutcome(key, count, perf_counter() - started, path=path)


@dataclass(slots=True)
class BatchStats:
    """Accumulate outcomes or snapshots including pending work."""

    counts: Counter[str] = field(default_factory=Counter)
    failures: Counter[str] = field(default_factory=Counter)
    matching_seconds: float = 0.0

    def add(
        self, status: str, failure_type: str | None = None, elapsed_seconds: float = 0.0
    ) -> None:
        self.counts[status] += 1
        self.matching_seconds += elapsed_seconds
        if status in {"failed", "stale"}:
            self.failures[failure_type or status] += 1

    def merge(self, other: BatchStats) -> None:
        self.counts.update(other.counts)
        self.failures.update(other.failures)
        self.matching_seconds += other.matching_seconds

    def summary(self) -> dict:
        matched = self.counts["success"]
        failed = self.counts["failed"] + self.counts["stale"]
        completed = matched + failed
        return {
            "total_flights": self.counts.total(),
            "matched_flights": matched,
            "failed_flights": failed,
            "success_rate": matched / completed if completed else None,
            "failure_counts": dict(self.failures),
            "matching_seconds": self.matching_seconds,
        }

    def progress(self) -> dict:
        summary = self.summary()
        waiting, running = self.counts["queued"], self.counts["matching"]
        return {
            "total": summary["total_flights"],
            "waiting": waiting,
            "running": running,
            "success": summary["matched_flights"],
            "failed": summary["failed_flights"],
            "complete": not (waiting or running),
            "summary": summary,
        }
