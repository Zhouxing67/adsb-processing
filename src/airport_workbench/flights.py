"""Session-scoped flight catalogue, editing and map geometry."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from functools import cached_property
from math import ceil
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

from airport_surface import AirportGraph
from flight import Flight
from flight.flight_catalogue_repository import STAND_COLUMNS
from flight.flight_repository import FlightDatabase, database_flight_key, flight_source_name
from path_map import MatchConfig
from utils.json_value import to_json_value

from .api_models import HistoricalStandCandidate, StandRecommendations
from .flight_match_tasks import FlightMatchTasks, MatchResultItem
from .serializers import flight_geojson, path_geojson
from .stand_recommendations import StandGeometryIndex

MATCH_STATUSES = {"unmatched", "queued", "matching", "success", "failed"}
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
        super().__init__(f"page must be between 1 and {total_pages}; got {requested_page}")


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


@dataclass(frozen=True, slots=True)
class FlightFilter:
    query: str = ""
    movement_type: str | None = None
    status: str | None = None
    min_points: int = 0
    max_points: int | None = None
    stands: tuple[str, ...] = ()
    start_date: date | None = None
    end_date: date | None = None
    validation_only: bool = False

    def validate(self, dataset_max_points: int, *, supports_validation: bool) -> FlightFilter:
        if self.status and self.status not in MATCH_STATUSES:
            raise ValueError("unknown match status")
        if self.min_points < 0:
            raise ValueError("min_points must be a non-negative integer")
        maximum = dataset_max_points if self.max_points is None else self.max_points
        if maximum < 0:
            raise ValueError("max_points must be a non-negative integer")
        if self.min_points > maximum:
            raise ValueError("min_points must not be greater than max_points")
        if maximum > dataset_max_points:
            raise ValueError(f"max_points must not exceed dataset maximum {dataset_max_points}")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("起始日期不得晚于终止日期")
        if self.validation_only and not supports_validation:
            raise ValueError("验证航班筛选需要数据库")
        return replace(
            self,
            query=self.query.strip(),
            max_points=maximum,
            stands=tuple(self.stands),
        )


class FlightWorkbench:
    """Expose flight catalogue and matching actions to the workbench API."""

    def __init__(
        self,
        airport_graph: AirportGraph,
        flight_database: FlightDatabase,
        *,
        match_config: MatchConfig | None = None,
        input_time_semantics: str = "UTC",
        display_timezone: str = "UTC",
    ) -> None:
        self.airport_graph = airport_graph
        self.match_config = match_config or MatchConfig()
        self.input_time_semantics = input_time_semantics
        self.display_timezone = display_timezone
        self.lock = threading.RLock()
        self.items: dict[str, FlightCatalogItem] = {}
        self.flight_database = flight_database
        for summary in flight_database.catalogue.summaries():
            movement = summary.movement
            key = database_flight_key(movement, summary.flight_id)
            inconsistent = () if summary.number_count <= 1 else ("flight_number",)
            if summary.stand_count > 1:
                inconsistent += (STAND_COLUMNS[movement][1],)
            self.items[key] = FlightCatalogItem(
                flight_key=key,
                source=flight_source_name(movement),
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
            airport_graph=self.airport_graph,
            lock=self.lock,
            config=self.match_config,
        )
        self.dataset_max_points = max((item.point_count for item in self.items.values()), default=0)
        display_dates = [self._display_time(item.start_time)[:10] for item in self.items.values()]
        self.dataset_min_date = min(display_dates, default=None)
        self.dataset_max_date = max(display_dates, default=None)

    @property
    def results(self) -> dict[str, MatchResultItem]:
        return self.match_tasks.results

    def close(self) -> None:
        self.match_tasks.close()

    def submit(self, flight_keys: Sequence[str], *, force: bool = False) -> dict[str, Any]:
        return self.match_tasks.submit(flight_keys, force=force)

    def task_status(self, task_ids: Sequence[str] | None = None) -> dict[str, Any]:
        return self.match_tasks.task_status(task_ids)

    @cached_property
    def _stand_geometry(self) -> StandGeometryIndex:
        return StandGeometryIndex(self.airport_graph)

    def recommend_stands(self, key: str) -> StandRecommendations:
        flight = self._flight(key)
        _, column = STAND_COLUMNS[flight.movement]
        event = flight.actual_dep if flight.movement == "departure" else flight.actual_arr
        if flight.stand_ref or (flight.od_error and column in flight.od_error) or event is None:
            return StandRecommendations(high=[], medium=[])
        high = self._stand_geometry.candidates(flight, event)
        history = self.flight_database.stands.historical_candidates(
            flight.movement, flight.flight_id, flight.number, event, flight.a_num
        ) if flight.number else []
        spatial_stands = {candidate.stand for candidate in high}
        return StandRecommendations(high=high, medium=[
            HistoricalStandCandidate(stand=stand, uses=uses, total=total)
            for stand, uses, total in history if stand not in spatial_stands
        ])

    def update_stand(self, key: str, stand: str | None) -> None:
        stand = (stand.strip() or None) if stand is not None else None
        with self.lock:
            item = self.items[key]
            if not item.can_edit_stand:
                raise ValueError("该航班没有可编辑的数据库机位记录")
            _, column = STAND_COLUMNS[item.movement_type]
            self.flight_database.stands.update(item.movement_type, item.flight_id, stand)
            self.items[key] = replace(
                item,
                stand_position=stand,
                inconsistent_fields=tuple(
                    name for name in item.inconsistent_fields if name != column
                ),
            )

    def catalogue(
        self,
        filters: FlightFilter = FlightFilter(),
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("page must be >= 1 and page_size must be between 1 and 100")
        filters = filters.validate(
            self.dataset_max_points,
            supports_validation=True,
        )
        rows = []
        with self.lock:
            keys = self._filtered_keys(filters)
            start = (page - 1) * page_size
            for key in keys[start : start + page_size]:
                item = self.items[key]
                result = self.results[key]
                row = asdict(item)
                row["start_time"] = self._display_time(item.start_time)
                row["end_time"] = self._display_time(item.end_time)
                rows.append({**row, "match": result.public()})
            stand_options = sorted(
                {
                    item.stand_position
                    for item in self.items.values()
                    if item.stand_position is not None
                }
            )
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
            "supports_validation_filter": True,
            "total": total,
            "total_pages": total_pages,
            "page": actual_page,
            "page_size": page_size,
            "dataset_max_points": self.dataset_max_points,
            "dataset_min_date": self.dataset_min_date,
            "dataset_max_date": self.dataset_max_date,
            "min_points": filters.min_points,
            "max_points": filters.max_points,
            "graph_id": self.match_tasks.graph_id,
            "time": {
                "input_semantics": self.input_time_semantics,
                "display_timezone": self.display_timezone,
            },
        }

    def filtered_keys(
        self,
        filters: FlightFilter = FlightFilter(),
    ) -> dict[str, Any]:
        """Return the fixed key set matching the currently committed filters."""
        filters = filters.validate(
            self.dataset_max_points,
            supports_validation=True,
        )
        with self.lock:
            keys = self._filtered_keys(filters)
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
            columns, fields, inconsistent, page_records, observation_total = (
                self.flight_database.observations.detail(
                    item.movement_type,
                    item.flight_id,
                    start,
                    observation_page_size,
                    BUSINESS_FIELD_NAMES,
                )
            )
            fields = {name: to_json_value(value) for name, value in fields.items()}
            inconsistent = to_json_value(inconsistent)
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

    def geometry(self, flight_key: str) -> dict[str, Any]:
        flight = self._flight(flight_key)
        with self.lock:
            result = self.results[flight_key]
            valid = result.status == "success" and result.graph_id == self.match_tasks.graph_id
            path = result.path if valid else None
            return {
                "flight_key": flight_key,
                "flight_id": self.items[flight_key].flight_id,
                "flight": flight_geojson(flight, flight_key=flight_key),
                "path": path_geojson(path, flight_key=flight_key) if path else None,
                "match": result.public(),
            }

    def _filtered_keys(self, filters: FlightFilter) -> list[str]:
        maximum = filters.max_points
        assert maximum is not None
        eligible = None
        if filters.validation_only:
            directions = {"dep": "departure", "arr": "arrival"}
            eligible = {
                database_flight_key(directions[row["movement"]], row["flight_id"])
                for row in self.flight_database.catalogue.validation_flights()
                if row["flight_id"] is not None
            }
        return [
            key
            for summary in self.flight_database.catalogue.summaries(
                movement=filters.movement_type,
                query=filters.query,
                min_points=filters.min_points,
                max_points=maximum,
                stands=filters.stands,
                start_date=filters.start_date,
                end_date=filters.end_date,
                display_timezone=self.display_timezone,
            )
            if (key := database_flight_key(summary.movement, summary.flight_id)) in self.results
            and (eligible is None or key in eligible)
            and (not filters.status or self.results[key].status == filters.status)
        ]

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
            item = self.items[flight_key]
            return self.flight_database.observations.flight(item.movement_type, item.flight_id)
        except KeyError as error:
            raise KeyError("未知 flight_key") from error

    def _display_time(self, value: str) -> str:
        return datetime.fromisoformat(value).astimezone(ZoneInfo(self.display_timezone)).isoformat()
