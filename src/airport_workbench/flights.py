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
from .issues_service import MatchIssueService
from .routes_service import RouteLibraryService
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
    whitelist_only: bool = False
    issues_only: bool = False

    def validate(
        self,
        dataset_max_points: int,
        *,
        supports_validation: bool,
        supports_whitelist: bool = False,
    ) -> FlightFilter:
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
        if self.whitelist_only and not supports_whitelist:
            raise ValueError("白名单航班筛选需要数据库包含 flight_whitelist 表")
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
        self._display_tz = ZoneInfo(display_timezone)
        self.lock = threading.RLock()
        self.items: dict[str, FlightCatalogItem] = {}
        self._display_times: dict[str, tuple[str, str, date]] = {}
        self._validation_keys: set[str] | None = None
        self.flight_database = flight_database
        for summary in flight_database.catalogue.summaries():
            movement = summary.movement
            key = database_flight_key(movement, summary.flight_id)
            inconsistent = () if summary.number_count <= 1 else ("flight_number",)
            if summary.stand_count > 1:
                inconsistent += (STAND_COLUMNS[movement][1],)
            item = FlightCatalogItem(
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
            self.items[key] = item
            start_local = summary.start_time.astimezone(self._display_tz)
            end_local = summary.end_time.astimezone(self._display_tz)
            self._display_times[key] = (
                start_local.isoformat(),
                end_local.isoformat(),
                start_local.date(),
            )
        self.match_tasks = FlightMatchTasks(
            self.items,
            self._flight,
            airport_graph=self.airport_graph,
            lock=self.lock,
            config=self.match_config,
            load_flights_batch=self._flights_batch,
        )
        self.routes_service = RouteLibraryService(
            self.airport_graph,
            self.flight_database,
            graph_id=self.match_tasks.graph_id,
            lock=self.lock,
            items=self.items,
            results=self.match_tasks.results,
            page_out_of_range_cls=CataloguePageOutOfRange,
        )
        self.issues_service = MatchIssueService(
            self.flight_database,
            graph_id=self.match_tasks.graph_id,
            lock=self.lock,
            items=self.items,
            results=self.match_tasks.results,
        )
        self.dataset_max_points = max((item.point_count for item in self.items.values()), default=0)
        display_dates = [times[2].isoformat() for times in self._display_times.values()]
        self.dataset_min_date = min(display_dates, default=None)
        self.dataset_max_date = max(display_dates, default=None)
        self._stand_options = self._compute_stand_options()

    @property
    def results(self) -> dict[str, MatchResultItem]:
        return self.match_tasks.results

    def close(self) -> None:
        self.match_tasks.close()
        self.flight_database.close()

    def submit(self, flight_keys: Sequence[str], *, force: bool = False) -> dict[str, Any]:
        return self.match_tasks.submit(flight_keys, force=force)

    def task_status(
        self,
        task_ids: Sequence[str] | None = None,
        *,
        include_items: bool = True,
        flight_keys: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        return self.match_tasks.task_status(
            task_ids,
            include_items=include_items,
            flight_keys=flight_keys,
        )

    @cached_property
    def _stand_geometry(self) -> StandGeometryIndex:
        return StandGeometryIndex(self.airport_graph)

    def recommend_stands(self, key: str) -> StandRecommendations:
        flight = self._flight(key)
        movement = flight.movement
        if movement is None or movement not in STAND_COLUMNS:
            return StandRecommendations(high=[], medium=[])
        _, column = STAND_COLUMNS[movement]
        event = flight.actual_dep if movement == "departure" else flight.actual_arr
        if flight.stand_ref or (flight.od_error and column in flight.od_error) or event is None:
            return StandRecommendations(high=[], medium=[])
        high = self._stand_geometry.candidates(flight, event)
        history = self.flight_database.stands.historical_candidates(
            movement, flight.flight_id, flight.number, event, flight.a_num
        ) if flight.number else []
        spatial_stands = {candidate.stand for candidate in high}
        return StandRecommendations(high=high, medium=[
            HistoricalStandCandidate(stand=stand, uses=uses, total=total)
            for stand, uses, total in history if stand not in spatial_stands
        ])

    def _compute_stand_options(self) -> list[str]:
        return sorted(
            {
                item.stand_position
                for item in self.items.values()
                if item.stand_position is not None
            }
        )

    def update_stand(self, key: str, stand: str | None) -> None:
        stand = (stand.strip() or None) if stand is not None else None
        with self.lock:
            item = self.items[key]
            if not item.can_edit_stand:
                raise ValueError("该航班没有可编辑的数据库机位记录")
            movement_type = item.movement_type
            flight_id = item.flight_id
            _, column = STAND_COLUMNS[movement_type]
        self.flight_database.stands.update(movement_type, flight_id, stand)
        with self.lock:
            latest = self.items[key]
            self.items[key] = replace(
                latest,
                stand_position=stand,
                inconsistent_fields=tuple(
                    name for name in latest.inconsistent_fields if name != column
                ),
            )
            self._validation_keys = None
            self._stand_options = self._compute_stand_options()

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
            supports_whitelist=True,
        )
        issue_map = self._issue_map()
        eligible = self._eligible_keys(filters, issue_keys=set(issue_map))
        rows = []
        with self.lock:
            keys = self._filtered_keys(filters, eligible=eligible)
            start = (page - 1) * page_size
            for key in keys[start : start + page_size]:
                item = self.items[key]
                result = self.results[key]
                row = asdict(item)
                display_start, display_end, _ = self._display_times[key]
                row["start_time"] = display_start
                row["end_time"] = display_end
                row["is_issue"] = key in issue_map
                row["issue_reason"] = issue_map.get(key)
                rows.append({**row, "match": result.public()})
            stand_options = list(self._stand_options)
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
            "supports_whitelist_filter": True,
            "issue_count": len(issue_map),
            "can_edit_issues": not self.flight_database.read_only,
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
            supports_whitelist=True,
        )
        issue_keys = set(self._issue_map()) if filters.issues_only else None
        eligible = self._eligible_keys(filters, issue_keys=issue_keys)
        with self.lock:
            keys = self._filtered_keys(filters, eligible=eligible)
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
        with self.lock:
            item = self.items[flight_key]
            match_public = self.results[flight_key].public()
            display_start, display_end, _ = self._display_times[flight_key]
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
                "start_time": display_start,
                "end_time": display_end,
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
            "match": match_public,
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

    def routes_list(self, **kwargs: Any) -> dict[str, Any]:
        return self.routes_service.list_routes(**kwargs)

    def route_geometry(self, route_id: str) -> dict[str, Any]:
        return self.routes_service.geometry(route_id)

    def update_route_review(
        self,
        route_id: str,
        status: str,
        *,
        note: str | None = None,
    ) -> dict[str, Any]:
        return self.routes_service.update_review(route_id, status, note=note)

    def import_matched_routes(
        self,
        flight_keys: Sequence[str] | None = None,
        *,
        replace_candidates: bool = False,
    ) -> dict[str, Any]:
        return self.routes_service.import_matched_routes(
            flight_keys,
            replace_candidates=replace_candidates,
        )

    def _issue_map(self) -> dict[str, str | None]:
        return self.issues_service.issue_map()

    def list_issue_keys(self) -> dict[str, Any]:
        return self.issues_service.list_issue_keys()

    def add_match_issues(
        self,
        flight_keys: Sequence[str],
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self.issues_service.add_issues(flight_keys, reason=reason)

    def remove_match_issues(self, flight_keys: Sequence[str]) -> dict[str, Any]:
        return self.issues_service.remove_issues(flight_keys)

    def _eligible_keys(
        self,
        filters: FlightFilter,
        *,
        issue_keys: set[str] | None = None,
    ) -> set[str] | None:
        """Resolve database-backed cohort filters outside self.lock."""
        eligible: set[str] | None = None
        if filters.validation_only:
            cached = self._validation_keys
            if cached is None:
                directions = {"dep": "departure", "arr": "arrival"}
                cached = {
                    database_flight_key(directions[row["movement"]], row["flight_id"])
                    for row in self.flight_database.catalogue.validation_flights()
                    if row["flight_id"] is not None
                }
                self._validation_keys = cached
            eligible = set(cached)
        if filters.whitelist_only:
            whitelisted = {
                database_flight_key(movement, flight_id)
                for movement, flight_id in self.flight_database.catalogue.whitelist_flights()
            }
            eligible = whitelisted if eligible is None else eligible & whitelisted
        if filters.issues_only:
            archived = issue_keys if issue_keys is not None else set(self._issue_map())
            eligible = archived if eligible is None else eligible & archived
        return eligible

    def _filtered_keys(
        self,
        filters: FlightFilter,
        *,
        eligible: set[str] | None = None,
    ) -> list[str]:
        maximum = filters.max_points
        assert maximum is not None
        search = filters.query.lower()
        stand_set = set(filters.stands) if filters.stands else None
        start_date = filters.start_date
        end_date = filters.end_date
        movement_type = filters.movement_type
        min_points = filters.min_points
        status = filters.status
        matched: list[str] = []
        for key, item in self.items.items():
            if movement_type and item.movement_type != movement_type:
                continue
            if item.point_count < min_points or item.point_count > maximum:
                continue
            if eligible is not None and key not in eligible:
                continue
            if status and self.results[key].status != status:
                continue
            if search:
                in_id = search in item.flight_id.lower()
                in_num = (
                    item.flight_number is not None
                    and search in str(item.flight_number).lower()
                )
                if not (in_id or in_num):
                    continue
            if stand_set is not None:
                stand_col = STAND_COLUMNS[item.movement_type][1]
                if stand_col in item.inconsistent_fields:
                    continue
                if (item.stand_position or "") not in stand_set:
                    continue
            if start_date is not None or end_date is not None:
                item_date = self._display_times[key][2]
                if start_date is not None and item_date < start_date:
                    continue
                if end_date is not None and item_date > end_date:
                    continue
            matched.append(key)
        return matched

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

    def _flights_batch(self, flight_keys: Sequence[str]) -> dict[str, Flight]:
        by_movement: dict[str, list[tuple[str, str]]] = {}
        for key in flight_keys:
            item = self.items.get(key)
            if item is not None:
                by_movement.setdefault(item.movement_type, []).append((key, item.flight_id))
        loaded: dict[str, Flight] = {}
        for movement, pairs in by_movement.items():
            flights_by_id = self.flight_database.observations.flights_batch(
                movement, [flight_id for _, flight_id in pairs]
            )
            for key, flight_id in pairs:
                flight = flights_by_id.get(flight_id)
                if flight is not None:
                    loaded[key] = flight
        return loaded

    def _display_time(self, value: str) -> str:
        return datetime.fromisoformat(value).astimezone(self._display_tz).isoformat()
