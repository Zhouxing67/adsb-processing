"""Session-scoped flight catalogue, editing and map geometry."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from math import ceil
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from airport_surface import AirportGraph
from flight import Flight
from flight.flight_repository import STAND_COLUMNS, FlightDatabase, database_flight_key
from path_map import MatchConfig, Path
from utils.json_value import to_json_value

from .flight_match_tasks import FlightMatchTasks, MatchResultItem
from .serializers import flight_geojson, path_geojson

MATCH_STATUSES = {"unmatched", "queued", "matching", "success", "failed", "stale"}
MAX_MAP_FLIGHTS = 10
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
    "dep_stand_position",
    "arr_stand_position",
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


def _distinct_values(rows: Iterable[Mapping[str, Any]], name: str) -> list[Any]:
    distinct = []
    for row in rows:
        value = to_json_value(row.get(name))
        if value is not None and value not in distinct:
            distinct.append(value)
    return distinct


def _consistent_value(
    rows: tuple[dict[str, Any], ...], names: Iterable[str],
) -> tuple[Any, bool]:
    for name in names:
        distinct = _distinct_values(rows, name)
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
    stand_position: str | None = None
    can_edit_stand: bool = False


class FlightWorkbench:
    """Expose flight catalogue and matching actions to the workbench API."""

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
        flight_database: FlightDatabase | None = None,
        graph_lock: Any | None = None,
        graph_provider: Callable[[], AirportGraph] | None = None,
        revision_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.airport_graph = airport_graph
        self.match_config = match_config or MatchConfig()
        self.input_time_semantics = input_time_semantics
        self.display_timezone = display_timezone
        self.lock = threading.RLock()
        self.flights: dict[str, Flight] = {}
        self.items: dict[str, FlightCatalogItem] = {}
        source_values = list(sources or ())
        movement_values = list(movement_types or ())
        self.flight_database = flight_database
        for index, flight in enumerate(flights):
            source = source_values[index] if index < len(source_values) else "provided"
            movement = movement_values[index] if index < len(movement_values) else "unknown"
            key = flight_key(index, source, flight.flight_id)
            rows = flight.rows
            number, number_consistent = _consistent_value(
                rows,
                ("flight_number", "NUMBER", "number", "callsign", "flight", "ident"),
            )
            inconsistent = () if number_consistent else ("flight_number",)
            stand_column = STAND_COLUMNS.get(movement, ("", ""))[1]
            distinct = {
                str(value).strip() for value in _distinct_values(rows, stand_column)
            }
            distinct.discard("")
            stand = next(iter(distinct)) if len(distinct) == 1 else None
            consistent = len(distinct) <= 1
            if not consistent:
                inconsistent += (stand_column,)
            self.flights[key] = flight
            self.items[key] = FlightCatalogItem(
                key,
                source,
                flight.flight_id,
                number,
                movement,
                flight.observations[0].timestamp.isoformat(),
                flight.observations[-1].timestamp.isoformat(),
                flight.point_count,
                inconsistent,
                stand,
                False,
            )
        if flight_database:
            for summary in flight_database.summaries():
                movement = summary.movement
                key = database_flight_key(movement, summary.flight_id)
                inconsistent = () if summary.number_count <= 1 else ("flight_number",)
                if summary.stand_count > 1:
                    inconsistent += (STAND_COLUMNS[movement][1],)
                self.items[key] = FlightCatalogItem(
                    flight_key=key,
                    source=flight_database.source_name(movement),
                    flight_id=summary.flight_id,
                    flight_number=summary.flight_number,
                    movement_type=movement,
                    start_time=summary.start_time.isoformat(),
                    end_time=summary.end_time.isoformat(),
                    point_count=summary.point_count,
                    inconsistent_fields=inconsistent,
                    stand_position=summary.stand_position,
                    can_edit_stand=not flight_database.read_only,
                )
        self.match_tasks = FlightMatchTasks(
            self.items,
            self._flight,
            graph_provider=graph_provider or (lambda: self.airport_graph),
            revision_provider=revision_provider,
            graph_lock=graph_lock or self.lock,
            lock=self.lock,
            config=self.match_config,
            paths=paths_by_flight_key or {},
        )
        self.dataset_max_points = max(
            (item.point_count for item in self.items.values()), default=0
        )

    @property
    def results(self) -> dict[str, MatchResultItem]:
        return self.match_tasks.results

    def close(self) -> None:
        self.match_tasks.close()

    def sync_graph(self) -> str:
        return self.match_tasks.sync_graph()

    def submit(self, flight_keys: Sequence[str], *, force: bool = False) -> dict[str, Any]:
        return self.match_tasks.submit(flight_keys, force=force)

    def task_status(self, task_ids: Sequence[str] | None = None) -> dict[str, Any]:
        return self.match_tasks.task_status(task_ids)

    def update_stand(self, key: str, stand: str | None) -> None:
        stand = (stand.strip() or None) if stand is not None else None
        with self.lock:
            item = self.items[key]
            if not item.can_edit_stand or self.flight_database is None:
                raise ValueError("该航班没有可编辑的数据库机位记录")
            _, column = STAND_COLUMNS[item.movement_type]
            self.flight_database.update_stand(item.movement_type, item.flight_id, stand)
            self.items[key] = replace(
                item, stand_position=stand,
                inconsistent_fields=tuple(
                    name for name in item.inconsistent_fields if name != column
                ),
            )

    def catalogue(
        self,
        *,
        query: str = "",
        movement_type: str | None = None,
        status: str | None = None,
        min_points: int = 0,
        max_points: int | None = None,
        stands: Sequence[str] = (),
        start_date: date | None = None,
        end_date: date | None = None,
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
        rows = []
        with self.lock:
            keys = self._filtered_keys(
                query, movement_type, status, min_points, effective_max,
                stands, start_date, end_date,
            )
            start = (page - 1) * page_size
            for key in keys[start : start + page_size]:
                item = self.items[key]
                result = self.results[key]
                row = asdict(item)
                row["start_time"] = self._display_time(item.start_time)
                row["end_time"] = self._display_time(item.end_time)
                rows.append({**row, "match": result.public()})
            stand_options = sorted({
                item.stand_position for item in self.items.values()
                if item.stand_position is not None
            })
        total = len(keys)
        total_pages = ceil(total / page_size) if total else 0
        if total_pages and page > total_pages:
            raise CataloguePageOutOfRange(page, total_pages)
        if not total_pages and page != 1:
            raise CataloguePageOutOfRange(page, 0)
        actual_page = page if total_pages else 0
        return {
            "items": rows,
            "stand_options": stand_options,
            "total": total,
            "total_pages": total_pages,
            "page": actual_page,
            "page_size": page_size,
            "dataset_max_points": self.dataset_max_points,
            "min_points": min_points,
            "max_points": effective_max,
            "max_map_flights": MAX_MAP_FLIGHTS,
            "graph_id": self.match_tasks.graph_id,
            "time": {
                "input_semantics": self.input_time_semantics,
                "display_timezone": self.display_timezone,
            },
        }

    def filtered_keys(
        self,
        *,
        query: str = "",
        movement_type: str | None = None,
        status: str | None = None,
        min_points: int = 0,
        max_points: int | None = None,
        stands: Sequence[str] = (),
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        """Return the fixed key set matching the currently committed filters."""
        self.sync_graph()
        effective_max = self.dataset_max_points if max_points is None else max_points
        self._validate_filters(status, min_points, effective_max)
        with self.lock:
            keys = self._filtered_keys(
                query, movement_type, status, min_points, effective_max,
                stands, start_date, end_date,
            )
        return {"flight_keys": keys, "count": len(keys)}

    def detail(
        self,
        flight_key: str,
        *,
        observation_page: int = 1,
        observation_page_size: int = 100,
        all_fields: bool = False,
    ) -> dict[str, Any]:
        if observation_page < 1 or not 1 <= observation_page_size <= 500:
            raise ValueError("observation page must be >= 1 and page size between 1 and 500")
        start = (observation_page - 1) * observation_page_size
        with self.lock:
            item = self.items[flight_key]
            if self.flight_database:
                columns, fields, inconsistent, page_records, observation_total = (
                    self.flight_database.detail(
                        item.movement_type, item.flight_id, start, observation_page_size,
                        BUSINESS_FIELD_NAMES,
                    )
                )
                fields = {name: to_json_value(value) for name, value in fields.items()}
                inconsistent = to_json_value(inconsistent)
            else:
                flight = self.flights[flight_key]
                rows = flight.rows
                columns = list(dict.fromkeys(name for row in rows for name in row))
                fields, inconsistent = self._detail_fields(rows, columns)
                observation_total = flight.point_count
                page_records = rows[start : start + observation_page_size]
        observation_pages = ceil(observation_total / observation_page_size)
        if observation_pages and observation_page > observation_pages:
            raise CataloguePageOutOfRange(observation_page, observation_pages)
        default_names = self._observation_columns(columns)
        column_names = columns if all_fields else default_names
        observations = []
        for offset, row in enumerate(page_records, start=start):
            observations.append(
                {
                    "record_index": offset + 1,
                    **{name: to_json_value(row.get(name)) for name in column_names},
                }
            )
        return {
            "summary": {
                **asdict(item),
                "start_time": self._display_time(item.start_time),
                "end_time": self._display_time(item.end_time),
            },
            "fields": fields,
            "inconsistent_fields": inconsistent,
            "observations": observations,
            "observation_columns": ["record_index", *column_names],
            "observation_page": observation_page if observation_pages else 0,
            "observation_pages": observation_pages,
            "observation_total": observation_total,
            "observation_page_size": observation_page_size,
            "all_fields": all_fields,
            "match": self.results[flight_key].public(),
        }

    @staticmethod
    def _detail_fields(
        rows: tuple[dict[str, Any], ...], columns: Iterable[str],
    ) -> tuple[dict[str, Any], dict[str, list[Any]]]:
        fields = {}
        inconsistent = {}
        for column in columns:
            values = _distinct_values(rows, column)
            fields[column] = values[0] if len(values) == 1 else None
            if len(values) > 1 and column.casefold() in BUSINESS_FIELD_NAMES:
                inconsistent[column] = values
        return fields, inconsistent

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

    def _validate_filters(self, status: str | None, min_points: int, max_points: int) -> None:
        if status and status not in MATCH_STATUSES:
            raise ValueError("unknown match status")
        if min_points < 0 or max_points < 0:
            raise ValueError("point limits must be non-negative integers")
        if min_points > max_points:
            raise ValueError("min_points must not be greater than max_points")
        if max_points > self.dataset_max_points:
            raise ValueError(
                f"max_points must not exceed dataset maximum {self.dataset_max_points}"
            )

    def _filtered_keys(
        self,
        query: str,
        movement_type: str | None,
        status: str | None,
        min_points: int,
        max_points: int,
        stands: Sequence[str] = (),
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[str]:
        if start_date and end_date and start_date > end_date:
            raise ValueError("起始日期不得晚于终止日期")
        if self.flight_database:
            return [
                key
                for summary in self.flight_database.summaries(
                    movement=movement_type, query=query.strip(),
                    min_points=min_points, max_points=max_points, stands=tuple(stands),
                    start_date=start_date, end_date=end_date,
                    display_timezone=self.display_timezone,
                )
                if (key := database_flight_key(summary.movement, summary.flight_id)) in self.results
                and (not status or self.results[key].status == status)
            ]
        selected_stands = set(stands)
        needle = query.strip().casefold()
        keys = []
        for key, item in self.items.items():
            result = self.results[key]
            if needle and needle not in str(item.flight_id).casefold() and needle not in str(
                item.flight_number or ""
            ).casefold():
                continue
            if movement_type and movement_type != item.movement_type:
                continue
            if status and status != result.status:
                continue
            if selected_stands and (
                item.movement_type not in STAND_COLUMNS
                or STAND_COLUMNS[item.movement_type][1] in item.inconsistent_fields
                or (item.stand_position or "") not in selected_stands
            ):
                continue
            if start_date or end_date:
                day = date.fromisoformat(self._display_time(item.start_time)[:10])
                if (start_date and day < start_date) or (end_date and day > end_date):
                    continue
            if min_points <= item.point_count <= max_points:
                keys.append(key)
        return keys

    @staticmethod
    def _observation_columns(columns: Iterable[Any]) -> list[Any]:
        available = list(columns)
        aliases = (
            ("timestamp", "time"),
            ("longitude", "lon"),
            ("latitude", "lat"),
            ("altitude", "altitude_ft", "height"),
            ("ground_speed", "groundspeed", "speed"),
            ("heading", "track", "course"),
            ("vertical_speed", "vertical_rate", "verticalspeed"),
        )
        selected = []
        lower = {str(name).casefold(): name for name in available}
        for group in aliases:
            match = next((lower[name] for name in group if name in lower), None)
            if match is not None and match not in selected:
                selected.append(match)
        return selected

    def _flight(self, flight_key: str) -> Flight:
        try:
            if self.flight_database:
                item = self.items[flight_key]
                return self.flight_database.flight(item.movement_type, item.flight_id)
            return self.flights[flight_key]
        except KeyError as error:
            raise KeyError("未知 flight_key") from error

    def _display_time(self, value: str) -> str:
        return datetime.fromisoformat(value).astimezone(ZoneInfo(self.display_timezone)).isoformat()

