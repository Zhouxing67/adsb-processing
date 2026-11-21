"""Background flight matching, result caching and task history."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import partial
from typing import Any, Callable, Iterable, Mapping, Sequence

from airport_surface import AirportGraph, graph_id
from flight import Flight
from path_map import BatchStats, MatchConfig, Matcher, MatchOutcome, Path, match_batch


def _graph_identity(airport_graph: AirportGraph) -> str:
    """Return a content identity, including for small graph doubles used by embedders."""
    try:
        return graph_id(airport_graph)
    except AttributeError:
        graph = getattr(airport_graph, "graph", None)
        if graph is None:
            return hashlib.sha256(type(airport_graph).__qualname__.encode()).hexdigest()
        content = (list(graph.nodes(data=True)), list(graph.edges(keys=True, data=True)))
        return hashlib.sha256(repr(content).encode()).hexdigest()


@dataclass(slots=True)
class MatchResultItem:
    flight_key: str
    graph_id: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    status: str = "unmatched"
    path: Path | None = None
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


class FlightMatchTasks:
    """Own match results, graph revisions and the serial matching worker."""

    def __init__(
        self,
        flight_keys: Iterable[str],
        load_flight: Callable[[str], Flight],
        *,
        graph_provider: Callable[[], AirportGraph],
        revision_provider: Callable[[], Any] | None,
        graph_lock: Any,
        lock: Any,
        config: MatchConfig,
        paths: Mapping[str, Path],
    ) -> None:
        self.load_flight = load_flight
        self.graph_provider = graph_provider
        self.revision_provider = revision_provider or (
            lambda: _graph_identity(self.graph_provider())
        )
        self.graph_lock = graph_lock
        self.lock = lock
        self.match_config = config
        self._revision = self.revision_provider()
        self.graph_id = _graph_identity(self.graph_provider())
        self._closing = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flight-match")
        self.tasks: dict[str, MatchTask] = {}
        self.results: dict[str, MatchResultItem] = {}
        for key in flight_keys:
            result = MatchResultItem(key)
            path = paths.get(key)
            if path is not None:
                result.graph_id = self.graph_id
                result.config = asdict(self.match_config)
                result.status = "success"
                result.path = path
                result.updated_at = self._now()
            self.results[key] = result

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

    def sync_graph(self) -> str:
        """Invalidate results whenever the mutable graph content changes."""
        with self.graph_lock:
            revision = self.revision_provider()
            if revision == self._revision:
                return self.graph_id
            current = _graph_identity(self.graph_provider())
        with self.lock:
            if current == self.graph_id:
                self._revision = revision
                return current
            self._revision = revision
            self.graph_id = current
            for result in self.results.values():
                if result.status != "unmatched":
                    result.status = "stale"
                    result.path = None
                    result.error = "机场图已变更；结果基于旧图快照，需重新匹配"
                    result.error_kind = "stale_graph"
                    result.failure_type = "stale_graph"
                    result.updated_at = self._now()
                    self._snapshot_task_result(
                        result.flight_key, result.task_id, only_if_active=True
                    )
            return current

    def submit(self, flight_keys: Sequence[str], *, force: bool = False) -> dict[str, Any]:
        keys = list(dict.fromkeys(flight_keys))
        if not keys:
            raise ValueError("至少选择一条航班")
        if any(key not in self.results for key in keys):
            raise KeyError("未知 flight_key")
        snapshot_id = self.sync_graph()
        task_id = hashlib.sha256(f"{snapshot_id}:{keys}:{self._now()}".encode()).hexdigest()[:20]
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
                    and result.graph_id == snapshot_id
                    and result.config == config
                )
                if cache_hit:
                    skipped.append({"flight_key": key, "reason": "current_success"})
                    continue
                result.graph_id = snapshot_id
                result.config = config
                result.status = "queued"
                result.path = None
                result.error = None
                result.error_kind = None
                result.failure_type = None
                result.elapsed_seconds = 0.0
                result.task_id = task_id
                result.updated_at = self._now()
                pending.append(key)
            self.tasks[task_id] = MatchTask(
                task_id,
                tuple(pending),
                self._now(),
                {key: self.results[key].public() for key in pending},
            )
            if pending:
                self.executor.submit(self._run, task_id, snapshot_id, tuple(pending))
        return {
            "task_id": task_id,
            "requested_count": len(keys),
            "queued": pending,
            "queued_count": len(pending),
            "skipped": skipped,
            "skipped_count": len(skipped),
        }

    def task_status(self, task_ids: Sequence[str] | None = None) -> dict[str, Any]:
        """Return compact progress without catalogue rows or geometry."""
        self.sync_graph()
        wanted = set(task_ids or ())
        with self.lock:
            tasks = [
                task for task_id, task in self.tasks.items() if not wanted or task_id in wanted
            ]
            payload = []
            total_stats = BatchStats()
            for task in tasks:
                stats = BatchStats()
                items = [dict(task.results[key]) for key in task.flight_keys]
                for item in items:
                    stats.add(item["status"], item["failure_type"], item["elapsed_seconds"])
                total_stats.merge(stats)
                payload.append(
                    {
                        "task_id": task.task_id,
                        "flight_keys": list(task.flight_keys),
                        **stats.progress(),
                        "items": items,
                    }
                )
        return {"graph_id": self.graph_id, "tasks": payload, "progress": total_stats.progress()}

    def _run(self, task_id: str, snapshot_id: str, keys: tuple[str, ...]) -> None:
        # The matcher is built for this graph version once per submitted batch.
        try:
            with self.graph_lock, self.lock:
                if self._closing:
                    return
                if self.sync_graph() != snapshot_id:
                    self.sync_graph()
                    return
                matcher = Matcher(self.graph_provider().copy(), self.match_config)
        except Exception as error:  # infrastructure/initialisation failure, not a normal mismatch
            self._fail_pending(keys, task_id, f"匹配器异常：{type(error).__name__}: {error}")
            return
        inputs = self._batch_inputs(task_id, snapshot_id, keys)
        for outcome in match_batch(matcher, inputs, capture_system_errors=True):
            self._complete(task_id, snapshot_id, outcome)

    def _batch_inputs(
        self,
        task_id: str,
        snapshot_id: str,
        keys: tuple[str, ...],
    ) -> Iterable[tuple[str, Callable[[], Flight]]]:
        for key in keys:
            with self.graph_lock, self.lock:
                if self._closing:
                    return
                result = self.results[key]
                if result.task_id != task_id or self.sync_graph() != snapshot_id:
                    continue
                result.status = "matching"
                result.updated_at = self._now()
                self._snapshot_task_result(key, task_id)
            yield key, partial(self.load_flight, key)

    def _complete(self, task_id: str, snapshot_id: str, outcome: MatchOutcome) -> None:
        key = outcome.key
        with self.graph_lock, self.lock:
            result = self.results[key]
            if result.task_id != task_id:
                return
            if self.sync_graph() != snapshot_id:
                self.sync_graph()
                return
            result.status = outcome.status
            result.path = outcome.path
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

    def _snapshot_task_result(
        self, key: str, task_id: str | None, *, only_if_active: bool = False
    ) -> None:
        """Copy the latest flight result into its owning task's immutable history."""
        if task_id is None:
            return
        task = self.tasks.get(task_id)
        if task is not None and key in task.results:
            if only_if_active and task.results[key]["status"] not in {"queued", "matching"}:
                return
            task.results[key] = self.results[key].public()
