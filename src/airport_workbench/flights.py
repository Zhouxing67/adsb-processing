"""SQL-backed flight catalogue, stand editing, and map geometry service."""

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
from flight.models import FlightSummary
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
    issues_only: bool = False

    def validate(
        self,
        dataset_max_points: int,
        *,
        supports_validation: bool,
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
        return replace(
            self,
            query=self.query.strip(),
            max_points=maximum,
            stands=tuple(self.stands),
        )


class _OnDemandItemsProxy:
    """Mapping-like view over public.flights for callers that resolve flights by key."""

    def __init__(self, owner: FlightWorkbench) -> None:
        self._owner = owner

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return self._owner._resolve_item(key) is not None

    def __getitem__(self, key: str) -> FlightCatalogItem:
        item = self._owner._resolve_item(key)
        if item is None:
            raise KeyError(f"未知 flight_key: {key}")
        return item

    def get(self, key: str, default: Any = None) -> Any:
        item = self._owner._resolve_item(key)
        return item if item is not None else default

    def __len__(self) -> int:
        return self._owner.dataset_total_flights

    def __bool__(self) -> bool:
        return self._owner.dataset_total_flights > 0

    def __iter__(self):
        return iter(self._owner._all_items_snapshot())

    def keys(self):
        return self._owner._all_items_snapshot().keys()

    def values(self):
        return self._owner._all_items_snapshot().values()

    def items(self):
        return self._owner._all_items_snapshot().items()


class FlightWorkbench:
    """Expose SQL-backed flight catalogue and matching actions to the workbench API."""

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
        self.flight_database = flight_database
        self._item_cache: dict[str, FlightCatalogItem] = {}

        stats = flight_database.catalogue.dataset_stats(display_timezone=display_timezone)
        self.dataset_total_flights: int = stats["total_flights"]
        self.dataset_max_points: int = stats["dataset_max_points"]
        self.dataset_min_date: str | None = stats["dataset_min_date"]
        self.dataset_max_date: str | None = stats["dataset_max_date"]
        self._stand_options: list[str] = list(stats["stand_options"])

        self.items: Any = _OnDemandItemsProxy(self)
        self.match_tasks = FlightMatchTasks(
            self._flight,
            airport_graph=self.airport_graph,
            lock=self.lock,
            config=self.match_config,
            validate_keys=self._validate_keys,
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

    def _summary_to_item(self, key: str, summary: FlightSummary) -> FlightCatalogItem:
        movement = summary.movement
        inconsistent = () if summary.number_count <= 1 else ("flight_number",)
        if summary.stand_count > 1:
            inconsistent += (STAND_COLUMNS[movement][1],)
        return FlightCatalogItem(
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
            can_edit_stand=not self.flight_database.read_only,
        )

    def _resolve_item(self, flight_key: str) -> FlightCatalogItem | None:
        with self.lock:
            cached = self._item_cache.get(flight_key)
        if cached is not None:
            return cached
        found = self.flight_database.catalogue.get_by_keys([flight_key])
        summary = found.get(flight_key)
        if summary is None:
            return None
        item = self._summary_to_item(flight_key, summary)
        with self.lock:
            self._item_cache[flight_key] = item
        return item

    def _resolve_items_batch(self, flight_keys: Sequence[str]) -> dict[str, FlightCatalogItem]:
        resolved: dict[str, FlightCatalogItem] = {}
        missing: list[str] = []
        with self.lock:
            for key in dict.fromkeys(flight_keys):
                cached = self._item_cache.get(key)
                if cached is not None:
                    resolved[key] = cached
                else:
                    missing.append(key)
        if missing:
            fetched = self.flight_database.catalogue.get_by_keys(missing)
            with self.lock:
                for key, summary in fetched.items():
                    item = self._summary_to_item(key, summary)
                    self._item_cache[key] = item
                    resolved[key] = item
        return resolved

    def _validate_keys(self, flight_keys: Sequence[str]) -> set[str]:
        return set(self._resolve_items_batch(flight_keys))

    def _all_items_snapshot(self) -> dict[str, FlightCatalogItem]:
        snapshot: dict[str, FlightCatalogItem] = {}
        for summary in self.flight_database.catalogue.summaries():
            key = database_flight_key(summary.movement, summary.flight_id)
            item = self._summary_to_item(key, summary)
            snapshot[key] = item
        with self.lock:
            self._item_cache.update(snapshot)
        return snapshot

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
        history = (
            self.flight_database.stands.historical_candidates(
                movement, flight.flight_id, flight.number, event, flight.a_num
            )
            if flight.number
            else []
        )
        spatial_stands = {candidate.stand for candidate in high}
        return StandRecommendations(
            high=high,
            medium=[
                HistoricalStandCandidate(stand=stand, uses=uses, total=total)
                for stand, uses, total in history
                if stand not in spatial_stands
            ],
        )

    def update_stand(self, key: str, stand: str | None) -> None:
        stand = (stand.strip() or None) if stand is not None else None
        item = self._resolve_item(key)
        if item is None:
            raise KeyError(f"未知 flight_key: {key}")
        if not item.can_edit_stand:
            raise ValueError("该航班没有可编辑的数据库机位记录")
        movement_type = item.movement_type
        flight_id = item.flight_id
        _, column = STAND_COLUMNS[movement_type]
        self.flight_database.stands.update(movement_type, flight_id, stand)
        stats = self.flight_database.catalogue.dataset_stats(display_timezone=self.display_timezone)
        with self.lock:
            self._item_cache[key] = replace(
                item,
                stand_position=stand,
                inconsistent_fields=tuple(
                    name for name in item.inconsistent_fields if name != column
                ),
            )
            self._stand_options = list(stats["stand_options"])

    def _status_key_constraints(
        self, status: str | None
    ) -> tuple[list[str] | None, list[str] | None]:
        if not status:
            return None, None
        with self.lock:
            if status == "unmatched":
                return None, self.match_tasks.non_unmatched_keys()
            return self.match_tasks.keys_with_status(status), None

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
        include_keys, exclude_keys = self._status_key_constraints(filters.status)
        start = (page - 1) * page_size
        page_pairs, total = self.flight_database.catalogue.query_page(
            movement=filters.movement_type,
            query=filters.query,
            min_points=filters.min_points,
            max_points=filters.max_points,
            stands=filters.stands,
            start_date=filters.start_date,
            end_date=filters.end_date,
            validation_only=filters.validation_only,
            issues_only=filters.issues_only,
            include_keys=include_keys,
            exclude_keys=exclude_keys,
            display_timezone=self.display_timezone,
            offset=start,
            limit=page_size,
        )
        total_pages = ceil(total / page_size) if total else 0
        if total_pages and page > total_pages:
            raise CataloguePageOutOfRange(page, total_pages)
        if not total_pages and page != 1:
            raise CataloguePageOutOfRange(page, 0)

        issue_map = self._issue_map()
        rows = []
        with self.lock:
            for key, summary in page_pairs:
                item = self._summary_to_item(key, summary)
                self._item_cache[key] = item
                row = asdict(item)
                row["start_time"] = summary.start_time.astimezone(self._display_tz).isoformat()
                row["end_time"] = summary.end_time.astimezone(self._display_tz).isoformat()
                row["is_issue"] = key in issue_map
                row["issue_reason"] = issue_map.get(key)
                rows.append({**row, "match": self.match_tasks.result_public(key)})
            stand_options = list(self._stand_options)

        actual_page = page if total_pages else 0
        return {
            "items": rows,
            "stand_options": stand_options,
            "supports_validation_filter": True,
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
        )
        include_keys, exclude_keys = self._status_key_constraints(filters.status)
        keys = self.flight_database.catalogue.query_flight_keys(
            movement=filters.movement_type,
            query=filters.query,
            min_points=filters.min_points,
            max_points=filters.max_points,
            stands=filters.stands,
            start_date=filters.start_date,
            end_date=filters.end_date,
            validation_only=filters.validation_only,
            issues_only=filters.issues_only,
            include_keys=include_keys,
            exclude_keys=exclude_keys,
            display_timezone=self.display_timezone,
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
        item = self._resolve_item(flight_key)
        if item is None:
            raise KeyError(f"未知 flight_key: {flight_key}")
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
            match_public = self.match_tasks.result_public(flight_key)
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
            "match": match_public,
        }

    def geometry(self, flight_key: str) -> dict[str, Any]:
        item = self._resolve_item(flight_key)
        if item is None:
            raise KeyError("未知 flight_key")
        flight = self.flight_database.observations.flight(item.movement_type, item.flight_id)
        with self.lock:
            result = dict.get(self.match_tasks.results, flight_key)
            valid = (
                result is not None
                and result.status == "success"
                and result.graph_id == self.match_tasks.graph_id
            )
            path = result.path if valid and result is not None else None
            match_public = (
                result.public() if result is not None else MatchResultItem(flight_key).public()
            )
        return {
            "flight_key": flight_key,
            "flight_id": item.flight_id,
            "flight": flight_geojson(flight, flight_key=flight_key),
            "path": path_geojson(path, flight_key=flight_key) if path else None,
            "match": match_public,
        }

    def routes_list(self, **kwargs: Any) -> dict[str, Any]:
        return self.routes_service.list_routes(**kwargs)

    def route_coverage(self) -> dict[str, Any]:
        return self.routes_service.coverage()

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

    def batch_update_route_review(
        self,
        route_ids: Sequence[str],
        status: str,
        *,
        note: str | None = None,
    ) -> dict[str, Any]:
        return self.routes_service.batch_update_review(route_ids, status, note=note)

    def detect_route_anomalies(self, route_ids: Sequence[str]) -> dict[str, Any]:
        return self.routes_service.detect_anomalies(route_ids)

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
        item = self._resolve_item(flight_key)
        if item is None:
            raise KeyError("未知 flight_key")
        return self.flight_database.observations.flight(item.movement_type, item.flight_id)

    def _flights_batch(self, flight_keys: Sequence[str]) -> dict[str, Flight]:
        items_by_key = self._resolve_items_batch(flight_keys)
        by_movement: dict[str, list[tuple[str, str]]] = {}
        for key in flight_keys:
            item = items_by_key.get(key)
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
