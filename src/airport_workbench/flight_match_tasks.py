"""Background flight matching, result caching and task history."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import partial
from typing import Any, Callable, Iterable, Sequence

from airport_surface import AirportGraph, graph_id
from flight import Flight
from path_map import BatchStats, MatchConfig, Matcher, MatchOutcome, Path, match_batch


@dataclass(slots=True)
class MatchResultItem:
    flight_key: str
    graph_id: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    status: str = "unmatched"
    path: Path | None = None
    stand_ref: str | None = None
    runway_ref: str | None = None
    error: str | None = None
    error_kind: str | None = None
    failure_type: str | None = None
    elapsed_seconds: float = 0.0
    task_id: str | None = None
    updated_at: str | None = None

    def public(self) -> dict[str, Any]:
        # Return a lightweight dictionary representation of match results for API responses.
        return {
            "flight_key": self.flight_key,
            "graph_id": self.graph_id,
            "config": dict(self.config),
            "status": self.status,
            "error": self.error,
            "error_kind": self.error_kind,
            "failure_type": self.failure_type,
            "elapsed_seconds": self.elapsed_seconds,
            "task_id": self.task_id,
            "updated_at": self.updated_at,
            "has_path": self.path is not None and self.status == "success",
        }


@dataclass(slots=True)
class MatchTask:
    task_id: str
    flight_keys: tuple[str, ...]
    created_at: str
    results: dict[str, dict[str, Any]]
    stats: BatchStats = field(default_factory=BatchStats)


BATCH_LOAD_SIZE = 200


class FlightMatchTasks:
    """Own match results and the serial matching worker for one immutable graph."""

    def __init__(
        self,
        flight_keys: Iterable[str],
        load_flight: Callable[[str], Flight],
        *,
        airport_graph: AirportGraph,
        lock: Any,
        config: MatchConfig,
        load_flights_batch: Callable[[Sequence[str]], dict[str, Flight]] | None = None,
    ) -> None:
        self.load_flight = load_flight
        self.load_flights_batch = load_flights_batch
        self.lock = lock
        self.match_config = config
        self.graph_id = graph_id(airport_graph)
        self.matcher = Matcher(airport_graph, self.match_config)
        self._closing = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flight-match")
        self.tasks: dict[str, MatchTask] = {}
        self.results: dict[str, MatchResultItem] = {}
        for key in flight_keys:
            self.results[key] = MatchResultItem(key)

    def close(self) -> None:
        with self.lock:
            self._closing = True
        self.executor.shutdown(wait=True, cancel_futures=True)
        with self.lock:
            for task in self.tasks.values():
                self._fail_pending(task.flight_keys, task.task_id, "工作台已关闭")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def submit(self, flight_keys: Sequence[str], *, force: bool = False) -> dict[str, Any]:
        keys = list(dict.fromkeys(flight_keys))
        if not keys:
            raise ValueError("至少选择一条航班")
        if any(key not in self.results for key in keys):
            raise KeyError("未知 flight_key")
        task_id = hashlib.sha256(
            f"{self.graph_id}:{keys}:{self._now()}".encode()
        ).hexdigest()[:20]
        config = asdict(self.match_config)
        pending = []
        skipped: list[dict[str, str]] = []
        with self.lock:
            if self._closing:
                raise ValueError("航班工作台正在关闭")
            for key in keys:
                result = self.results[key]
                if result.status in {"queued", "matching"}:
                    skipped.append({"flight_key": key, "reason": "already_running"})
                    continue
                cache_hit = (
                    not force
                    and result.status == "success"
                    and result.graph_id == self.graph_id
                    and result.config == config
                )
                if cache_hit:
                    skipped.append({"flight_key": key, "reason": "current_success"})
                    continue
                result.graph_id = self.graph_id
                result.config = config
                result.status = "queued"
                result.path = None
                result.stand_ref = None
                result.runway_ref = None
                result.error = None
                result.error_kind = None
                result.failure_type = None
                result.elapsed_seconds = 0.0
                result.task_id = task_id
                result.updated_at = self._now()
                pending.append(key)
            task_stats = BatchStats()
            if pending:
                task_stats.counts["queued"] = len(pending)
            self.tasks[task_id] = MatchTask(
                task_id,
                tuple(pending),
                self._now(),
                {key: self.results[key].public() for key in pending},
                task_stats,
            )
            if pending:
                self.executor.submit(self._run, task_id, tuple(pending))
        return {
            "task_id": task_id,
            "requested_count": len(keys),
            "queued": pending,
            "queued_count": len(pending),
            "skipped": skipped,
            "skipped_count": len(skipped),
        }

    def task_status(
        self,
        task_ids: Sequence[str] | None = None,
        *,
        include_items: bool = True,
        flight_keys: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Return progress; when include_items is False, include only requested flight_keys."""
        wanted_tasks = set(task_ids or ())
        wanted_keys = set(flight_keys or ())
        with self.lock:
            tasks = [
                task for task_id, task in self.tasks.items()
                if not wanted_tasks or task_id in wanted_tasks
            ]
            payload = []
            total_stats = BatchStats()
            for task in tasks:
                total_stats.merge(task.stats)
                if include_items:
                    task_flight_keys = list(task.flight_keys)
                    items = [dict(task.results[key]) for key in task.flight_keys]
                elif wanted_keys:
                    matched_keys = [key for key in wanted_keys if key in task.results]
                    task_flight_keys = matched_keys
                    items = [dict(task.results[key]) for key in matched_keys]
                else:
                    task_flight_keys = []
                    items = []
                payload.append(
                    {
                        "task_id": task.task_id,
                        "flight_keys": task_flight_keys,
                        **task.stats.progress(),
                        "items": items,
                    }
                )
        return {"graph_id": self.graph_id, "tasks": payload, "progress": total_stats.progress()}

    def _run(self, task_id: str, keys: tuple[str, ...]) -> None:
        inputs = self._batch_inputs(task_id, keys)
        for outcome in match_batch(self.matcher, inputs, capture_system_errors=True):
            self._complete(task_id, outcome)

    def _batch_inputs(
        self,
        task_id: str,
        keys: tuple[str, ...],
    ) -> Iterable[tuple[str, Flight | Callable[[], Flight]]]:
        if self.load_flights_batch is None:
            for key in keys:
                with self.lock:
                    if self._closing:
                        return
                    result = self.results[key]
                    if result.task_id != task_id:
                        continue
                    result.status = "matching"
                    result.updated_at = self._now()
                    self._snapshot_task_result(key, task_id)
                yield key, partial(self.load_flight, key)
            return

        for offset in range(0, len(keys), BATCH_LOAD_SIZE):
            chunk = keys[offset : offset + BATCH_LOAD_SIZE]
            active_chunk: list[str] = []
            with self.lock:
                if self._closing:
                    return
                for key in chunk:
                    if self.results[key].task_id == task_id:
                        active_chunk.append(key)
            if not active_chunk:
                continue
            try:
                preloaded = self.load_flights_batch(active_chunk)
            except Exception:
                preloaded = {}
            for key in active_chunk:
                with self.lock:
                    if self._closing:
                        return
                    result = self.results[key]
                    if result.task_id != task_id:
                        continue
                    result.status = "matching"
                    result.updated_at = self._now()
                    self._snapshot_task_result(key, task_id)
                flight = preloaded.pop(key, None)
                yield key, flight if flight is not None else partial(self.load_flight, key)

    def _complete(self, task_id: str, outcome: MatchOutcome) -> None:
        key = outcome.key
        with self.lock:
            result = self.results[key]
            if result.task_id != task_id:
                return
            result.status = outcome.status
            result.path = outcome.path
            result.stand_ref = outcome.stand_ref
            result.runway_ref = outcome.runway_ref
            result.error = outcome.reason
            result.error_kind = outcome.error_kind
            result.failure_type = outcome.failure_type
            result.elapsed_seconds = outcome.elapsed_seconds
            result.updated_at = self._now()
            self._snapshot_task_result(key, task_id)

    def _fail_pending(self, keys: Sequence[str], task_id: str, error: str) -> None:
        with self.lock:
            for key in keys:
                result = self.results[key]
                if result.task_id == task_id and result.status in {"queued", "matching"}:
                    result.status = "failed"
                    result.error = error
                    result.error_kind = "system"
                    result.failure_type = "system"
                    result.updated_at = self._now()
                    self._snapshot_task_result(key, task_id)

    def _snapshot_task_result(self, key: str, task_id: str | None) -> None:
        """Copy the latest flight result into its owning task's immutable history."""
        if task_id is None:
            return
        task = self.tasks.get(task_id)
        if task is not None and key in task.results:
            previous = task.results[key]
            updated = self.results[key].public()
            task.results[key] = updated
            prev_status = previous["status"]
            task.stats.counts[prev_status] -= 1
            if task.stats.counts[prev_status] <= 0:
                del task.stats.counts[prev_status]
            task.stats.matching_seconds -= previous["elapsed_seconds"]
            if prev_status == "failed":
                prev_failure = previous["failure_type"] or prev_status
                task.stats.failures[prev_failure] -= 1
                if task.stats.failures[prev_failure] <= 0:
                    del task.stats.failures[prev_failure]
            task.stats.add(updated["status"], updated["failure_type"], updated["elapsed_seconds"])
