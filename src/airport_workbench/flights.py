"""Session-scoped flight catalogue and asynchronous map-matching state."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import ceil
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd

from adsb import Flight
from airport_surface import AirportGraph, graph_id
from path_map import MapMatchingError, MatchConfig, Matcher, Path

from .serializers import flight_geojson, path_geojson

MATCH_STATUSES = {"unmatched", "queued", "matching", "success", "failed", "stale"}
MAX_SELECTED_FLIGHTS = 5
BUSINESS_FIELD_NAMES = {
    "flight_id",
    "flight_number",
    "number",
    "callsign",
    "flight",
    "ident",
    "registration",
    "aircraft",
    "aircraft_type",
    "origin",
    "destination",
    "movement_type",
}


class CataloguePageOutOfRange(ValueError):
    """Raised when a filtered catalogue page no longer exists."""

    def __init__(self, requested_page: int, total_pages: int) -> None:
        self.requested_page = requested_page
        self.total_pages = total_pages
        super().__init__(
            f"page must be between 1 and {total_pages}; got {requested_page}"
        )


def flight_key(index: int, source: str, original_flight_id: str) -> str:
    """Build the stable session key used by catalogue and explicit path associations."""
    seed = f"{index}\0{source}\0{original_flight_id}".encode()
    return f"f-{hashlib.sha256(seed).hexdigest()[:16]}"


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


def _scalar(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def _consistent_value(frame: pd.DataFrame, names: Iterable[str]) -> tuple[Any, bool]:
    for name in names:
        if name not in frame:
            continue
        values = [_scalar(value) for value in frame[name].tolist()]
        distinct = []
        for value in values:
            if value is not None and value not in distinct:
                distinct.append(value)
        if len(distinct) == 1:
            return distinct[0], True
        if len(distinct) > 1:
            return None, False
    return None, True


@dataclass(frozen=True, slots=True)
class FlightCatalogItem:
    flight_key: str
    source: str
    flight_id: str
    flight_number: Any
    movement_type: str
    start_time: str
    end_time: str
    point_count: int
    inconsistent_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class MatchResultItem:
    flight_key: str
    graph_id: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    status: str = "unmatched"
    path: Path | None = None
    error: str | None = None
    error_kind: str | None = None
    task_id: str | None = None
    updated_at: str | None = None

    def public(self) -> dict[str, Any]:
        # Never dataclasses.asdict() this object: Path owns an AirportGraph containing
        # immutable mapping proxies that are intentionally not deepcopy-able.
        return {
            "flight_key": self.flight_key,
            "graph_id": self.graph_id,
            "config": dict(self.config),
            "status": self.status,
            "error": self.error,
            "error_kind": self.error_kind,
            "task_id": self.task_id,
            "updated_at": self.updated_at,
            "has_path": self.path is not None and self.status == "success",
        }


class FlightWorkbench:
    """Own catalogue, result cache and one serial worker for a workbench session."""

    def __init__(
        self,
        airport_graph: AirportGraph,
        flights: Sequence[Flight] = (),
        *,
        sources: Sequence[str] | None = None,
        movement_types: Sequence[str] | None = None,
        paths_by_flight_key: Mapping[str, Path] | None = None,
        match_config: MatchConfig | None = None,
        input_time_semantics: str = "UTC",
        display_timezone: str = "UTC",
        graph_lock: Any | None = None,
        graph_provider: Callable[[], AirportGraph] | None = None,
        revision_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.airport_graph = airport_graph
        self.graph_provider = graph_provider or (lambda: self.airport_graph)
        self.revision_provider = revision_provider or (
            lambda: _graph_identity(self.graph_provider())
        )
        self.match_config = match_config or MatchConfig()
        self.input_time_semantics = input_time_semantics
        self.display_timezone = display_timezone
        self.lock = threading.RLock()
        self.graph_lock = graph_lock or self.lock
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flight-match")
        self._revision = self.revision_provider()
        self._graph_id = _graph_identity(self.graph_provider())
        self.flights: dict[str, Flight] = {}
        self.items: dict[str, FlightCatalogItem] = {}
        self.results: dict[str, MatchResultItem] = {}
        source_values = list(sources or ())
        movement_values = list(movement_types or ())
        for index, flight in enumerate(flights):
            source = source_values[index] if index < len(source_values) else "provided"
            movement = movement_values[index] if index < len(movement_values) else "unknown"
            key = flight_key(index, source, flight.flight_id)
            number, number_consistent = _consistent_value(
                flight.data,
                ("flight_number", "NUMBER", "number", "callsign", "flight", "ident"),
            )
            inconsistent = () if number_consistent else ("flight_number",)
            self.flights[key] = flight
            self.items[key] = FlightCatalogItem(
                key,
                source,
                flight.flight_id,
                number,
                movement,
                flight.data.timestamp.min().isoformat(),
                flight.data.timestamp.max().isoformat(),
                len(flight.data),
                inconsistent,
            )
            result = MatchResultItem(key)
            associated_path = (paths_by_flight_key or {}).get(key)
            if associated_path is not None:
                result.graph_id = self._graph_id
                result.config = asdict(self.match_config)
                result.status = "success"
                result.path = associated_path
                result.updated_at = self._now()
            self.results[key] = result
        self.dataset_max_points = max(
            (item.point_count for item in self.items.values()), default=0
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def sync_graph(self) -> str:
        """Invalidate results whenever the mutable graph content changes."""
        with self.graph_lock:
            revision = self.revision_provider()
            if revision == self._revision:
                return self._graph_id
            current = _graph_identity(self.graph_provider())
        with self.lock:
            if current == self._graph_id:
                self._revision = revision
                return current
            self._revision = revision
            self._graph_id = current
            for result in self.results.values():
                if result.status != "unmatched":
                    result.status = "stale"
                    result.path = None
                    result.error = "机场图已变更；结果基于旧图快照，需重新匹配"
                    result.error_kind = "stale_graph"
                    result.updated_at = self._now()
            return current

    def catalogue(
        self,
        *,
        query: str = "",
        movement_type: str | None = None,
        status: str | None = None,
        min_points: int = 0,
        max_points: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        self.sync_graph()
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("page must be >= 1 and page_size must be between 1 and 100")
        if status and status not in MATCH_STATUSES:
            raise ValueError("unknown match status")
        if min_points < 0:
            raise ValueError("min_points must be a non-negative integer")
        effective_max = self.dataset_max_points if max_points is None else max_points
        if effective_max < 0:
            raise ValueError("max_points must be a non-negative integer")
        if min_points > effective_max:
            raise ValueError("min_points must not be greater than max_points")
        if effective_max > self.dataset_max_points:
            raise ValueError(
                f"max_points must not exceed dataset maximum {self.dataset_max_points}"
            )
        needle = query.strip().casefold()
        rows = []
        with self.lock:
            for key, item in self.items.items():
                result = self.results[key]
                matches_id = needle in str(item.flight_id).casefold()
                matches_number = needle in str(item.flight_number or "").casefold()
                if needle and not matches_id and not matches_number:
                    continue
                if movement_type and movement_type != item.movement_type:
                    continue
                if status and status != result.status:
                    continue
                if not min_points <= item.point_count <= effective_max:
                    continue
                row = asdict(item)
                row["start_time"] = self._display_time(item.start_time)
                row["end_time"] = self._display_time(item.end_time)
                rows.append({**row, "match": result.public()})
        total = len(rows)
        total_pages = ceil(total / page_size) if total else 0
        if total_pages and page > total_pages:
            raise CataloguePageOutOfRange(page, total_pages)
        if not total_pages and page != 1:
            raise CataloguePageOutOfRange(page, 0)
        actual_page = page if total_pages else 0
        start = (page - 1) * page_size
        return {
            "items": rows[start : start + page_size],
            "total": total,
            "total_pages": total_pages,
            "page": actual_page,
            "page_size": page_size,
            "dataset_max_points": self.dataset_max_points,
            "min_points": min_points,
            "max_points": effective_max,
            "max_selected": MAX_SELECTED_FLIGHTS,
            "graph_id": self._graph_id,
            "time": {
                "input_semantics": self.input_time_semantics,
                "display_timezone": self.display_timezone,
            },
        }

    def detail(self, flight_key: str) -> dict[str, Any]:
        flight = self._flight(flight_key)
        fields: dict[str, Any] = {}
        inconsistent: dict[str, list[Any]] = {}
        for column in flight.data.columns:
            values = []
            for raw in flight.data[column].tolist():
                value = _scalar(raw)
                if value is not None and value not in values:
                    values.append(value)
            if len(values) <= 1:
                fields[column] = values[0] if values else None
            elif column.casefold() in BUSINESS_FIELD_NAMES:
                fields[column] = None
                inconsistent[column] = values
            else:
                fields[column] = None
        return {
            "summary": {
                **asdict(self.items[flight_key]),
                "start_time": self._display_time(self.items[flight_key].start_time),
                "end_time": self._display_time(self.items[flight_key].end_time),
            },
            "fields": fields,
            "inconsistent_fields": inconsistent,
            "observations": [
                {name: _scalar(value) for name, value in row.items()}
                for row in flight.data.to_dict(orient="records")
            ],
            "match": self.results[flight_key].public(),
        }

    def geometry(self, flight_key: str) -> dict[str, Any]:
        flight = self._flight(flight_key)
        current_graph_id = self.sync_graph()
        with self.lock:
            result = self.results[flight_key]
            valid = result.status == "success" and result.graph_id == current_graph_id
            path = result.path if valid else None
            return {
                "flight_key": flight_key,
                "flight": flight_geojson(flight, flight_key=flight_key),
                "path": path_geojson(path, flight_key=flight_key) if path else None,
                "match": result.public(),
            }

    def submit(self, flight_keys: Sequence[str], *, force: bool = False) -> dict[str, Any]:
        keys = list(dict.fromkeys(flight_keys))
        if not 1 <= len(keys) <= MAX_SELECTED_FLIGHTS:
            raise ValueError("每次必须选择 1～5 条航班")
        for key in keys:
            self._flight(key)
        snapshot_id = self.sync_graph()
        task_id = hashlib.sha256(f"{snapshot_id}:{keys}:{self._now()}".encode()).hexdigest()[:20]
        config = asdict(self.match_config)
        pending = []
        with self.lock:
            for key in keys:
                result = self.results[key]
                cache_hit = (
                    not force
                    and result.status == "success"
                    and result.graph_id == snapshot_id
                    and result.config == config
                )
                if cache_hit:
                    continue
                result.graph_id = snapshot_id
                result.config = config
                result.status = "queued"
                result.path = None
                result.error = None
                result.error_kind = None
                result.task_id = task_id
                result.updated_at = self._now()
                pending.append(key)
        if pending:
            self.executor.submit(self._run, task_id, snapshot_id, tuple(pending))
        return {"task_id": task_id, "flight_keys": keys, "queued": pending}

    def _run(self, task_id: str, snapshot_id: str, keys: tuple[str, ...]) -> None:
        # The matcher is built for this graph version once per submitted batch.
        try:
            with self.graph_lock, self.lock:
                if self.sync_graph() != snapshot_id:
                    self.sync_graph()
                    return
                matcher = Matcher(self.graph_provider().copy(), self.match_config)
        except Exception as error:  # infrastructure/initialisation failure, not a normal mismatch
            self._fail_pending(keys, task_id, f"匹配器异常：{type(error).__name__}: {error}")
            return
        for key in keys:
            with self.graph_lock, self.lock:
                result = self.results[key]
                if result.task_id != task_id or self.sync_graph() != snapshot_id:
                    self.sync_graph()
                    continue
                result.status = "matching"
                result.updated_at = self._now()
            try:
                path = matcher.map_flight(self.flights[key])
            except MapMatchingError as error:
                self._complete(
                    key, task_id, snapshot_id, "failed", None, str(error), "matching"
                )
            except Exception as error:
                self._complete(
                    key,
                    task_id,
                    snapshot_id,
                    "failed",
                    None,
                    f"系统异常（非正常匹配失败）：{type(error).__name__}: {error}",
                    "system",
                )
            else:
                self._complete(key, task_id, snapshot_id, "success", path, None, None)

    def _complete(
        self,
        key: str,
        task_id: str,
        snapshot_id: str,
        status: str,
        path: Path | None,
        error: str | None,
        error_kind: str | None,
    ) -> None:
        with self.graph_lock, self.lock:
            result = self.results[key]
            if result.task_id != task_id:
                return
            if self.sync_graph() != snapshot_id:
                self.sync_graph()
                return
            result.status = status
            result.path = path
            result.error = error
            result.error_kind = error_kind
            result.updated_at = self._now()

    def _fail_pending(self, keys: Sequence[str], task_id: str, error: str) -> None:
        with self.lock:
            for key in keys:
                result = self.results[key]
                if result.task_id == task_id and result.status in {"queued", "matching"}:
                    result.status = "failed"
                    result.error = error
                    result.error_kind = "system"
                    result.updated_at = self._now()

    def _flight(self, flight_key: str) -> Flight:
        try:
            return self.flights[flight_key]
        except KeyError as error:
            raise KeyError("未知 flight_key") from error

    def _display_time(self, value: str) -> str:
        return pd.Timestamp(value).tz_convert(self.display_timezone).isoformat()


def config_fingerprint(config: MatchConfig) -> str:
    return hashlib.sha256(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()
