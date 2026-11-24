"""Route library listing, geometry resolution, review, and match import service."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from math import ceil
from typing import Any

from airport_surface import AirportGraph
from flight.flight_repository import FlightDatabase
from path_map import PathGraphMismatch
from route_library.models import RouteEntry, RouteStatus, normalize_movement, normalize_runway_ref
from route_library.repository import RouteLibraryRepository

from .serializers import path_geojson

logger = logging.getLogger(__name__)


class RoutePageOutOfRange(ValueError):
    """Raised when a filtered route library page no longer exists."""

    def __init__(self, requested_page: int, total_pages: int) -> None:
        self.requested_page = requested_page
        self.total_pages = total_pages
        super().__init__(f"page must be between 1 and {total_pages}; got {requested_page}")


class RouteLibraryService:
    """Coordinate route_library queries, review updates, and matched-flight imports."""

    def __init__(
        self,
        airport_graph: AirportGraph,
        flight_database: FlightDatabase,
        *,
        graph_id: str,
        lock: Any,
        items: Mapping[str, Any],
        results: Mapping[str, Any],
        page_out_of_range_cls: Callable[[int, int], ValueError] = RoutePageOutOfRange,
    ) -> None:
        self.airport_graph = airport_graph
        self.flight_database = flight_database
        self.repository = RouteLibraryRepository(flight_database.duckdb)
        self.graph_id = graph_id
        self.lock = lock
        self.items = items
        self.results = results
        self._page_out_of_range = page_out_of_range_cls

    def _serialize(self, entry: RouteEntry) -> dict[str, Any]:
        return {
            "route_id": entry.route_id,
            "graph_id": entry.graph_id,
            "matches_current_graph": entry.graph_id == self.graph_id,
            "movement": entry.movement,
            "stand_ref": entry.stand_ref,
            "runway_ref": entry.runway_ref,
            "runway_interface_node": entry.runway_interface_node,
            "edge_count": entry.edge_count,
            "total_length_m": entry.total_length_m,
            "status": entry.status.value,
            "source": entry.source.value,
            "note": entry.note,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
        }

    def _serialize_metadata(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        created_at = entry["created_at"]
        updated_at = entry["updated_at"]
        return {
            "route_id": entry["route_id"],
            "graph_id": entry["graph_id"],
            "matches_current_graph": entry["graph_id"] == self.graph_id,
            "movement": entry["movement"],
            "stand_ref": entry["stand_ref"],
            "runway_ref": entry["runway_ref"],
            "runway_interface_node": entry["runway_interface_node"],
            "edge_count": entry["edge_count"],
            "total_length_m": entry["total_length_m"],
            "status": entry["status"],
            "source": entry["source"],
            "note": entry["note"],
            "created_at": created_at.isoformat() if created_at else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
        }

    def list_routes(
        self,
        *,
        query: str = "",
        movement: str | None = None,
        stand_ref: str | None = None,
        runway_ref: str | None = None,
        runway_is_null: bool = False,
        status: str | None = None,
        all_graphs: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        if page < 1 or not 1 <= page_size <= 200:
            raise ValueError("page must be >= 1 and page_size must be between 1 and 200")
        normalized_movement = normalize_movement(movement) if movement else None
        normalized_stand = stand_ref.strip() if stand_ref and stand_ref.strip() else None
        normalized_runway = normalize_runway_ref(runway_ref) if runway_ref else None
        normalized_status = RouteStatus(status).value if status else None
        search = query.strip().casefold()

        scoped = self.repository.list_metadata(
            graph_id=None if all_graphs else self.graph_id,
        )
        stand_options = sorted({entry["stand_ref"] for entry in scoped})
        runway_options = sorted({entry["runway_ref"] for entry in scoped if entry["runway_ref"]})
        status_counts = {member.value: 0 for member in RouteStatus}
        for entry in scoped:
            status_counts[entry["status"]] = status_counts.get(entry["status"], 0) + 1

        filtered = []
        for entry in scoped:
            if normalized_movement and entry["movement"] != normalized_movement:
                continue
            if normalized_stand and entry["stand_ref"] != normalized_stand:
                continue
            if runway_is_null:
                if entry["runway_ref"] is not None:
                    continue
            elif normalized_runway and entry["runway_ref"] != normalized_runway:
                continue
            if normalized_status and entry["status"] != normalized_status:
                continue
            if search:
                haystack = " ".join(
                    part
                    for part in (
                        entry["route_id"],
                        entry["stand_ref"],
                        entry["runway_ref"] or "",
                        entry["runway_interface_node"],
                        entry["note"] or "",
                    )
                    if part
                ).casefold()
                if search not in haystack:
                    continue
            filtered.append(entry)

        total = len(filtered)
        total_pages = ceil(total / page_size) if total else 0
        if total_pages and page > total_pages:
            raise self._page_out_of_range(page, total_pages)
        if not total_pages and page != 1:
            raise self._page_out_of_range(page, 0)
        start = (page - 1) * page_size
        page_items = [
            self._serialize_metadata(entry) for entry in filtered[start : start + page_size]
        ]
        return {
            "items": page_items,
            "has_route_library": True,
            "current_graph_id": self.graph_id,
            "can_edit": not self.flight_database.read_only,
            "stand_options": stand_options,
            "runway_options": runway_options,
            "status_counts": status_counts,
            "total": total,
            "total_pages": total_pages,
            "page": page if total_pages else 0,
            "page_size": page_size,
        }

    def geometry(self, route_id: str) -> dict[str, Any]:
        entry = self.repository.get(route_id)
        if entry is None:
            raise KeyError(f"Unknown route_id: {route_id!r}")
        try:
            path = entry.resolve(self.airport_graph)
        except (PathGraphMismatch, ValueError, KeyError) as error:
            raise ValueError(f"路径无法在当前机场图上解析：{error}") from error
        return {
            "route": self._serialize(entry),
            "path": path_geojson(path),
        }

    def update_review(
        self,
        route_id: str,
        status: str,
        *,
        note: str | None = None,
    ) -> dict[str, Any]:
        if self.flight_database.read_only:
            raise ValueError("当前数据库为只读模式，无法更新路径审校状态")
        cleaned_note = (note.strip() or None) if note is not None else None
        try:
            updated = self.repository.update_status(
                route_id,
                RouteStatus(status),
                note=cleaned_note,
            )
        except KeyError:
            raise
        except self.flight_database.database_error as error:
            raise RuntimeError("路径审校更新失败") from error
        return self._serialize(updated)

    def import_matched_routes(
        self,
        flight_keys: Sequence[str] | None = None,
        *,
        replace_candidates: bool = False,
    ) -> dict[str, Any]:
        if self.flight_database.read_only:
            raise ValueError("当前数据库为只读模式，无法写入路径库")
        with self.lock:
            if flight_keys is None:
                candidate_keys = list(self.items)
            else:
                candidate_keys = list(dict.fromkeys(flight_keys))
                unknown = [key for key in candidate_keys if key not in self.items]
                if unknown:
                    raise KeyError(f"未知 flight_key: {unknown[0]}")
            matched_records = []
            for key in candidate_keys:
                result = self.results[key]
                if (
                    result.status != "success"
                    or result.graph_id != self.graph_id
                    or result.path is None
                ):
                    continue
                item = self.items[key]
                stand_ref = result.stand_ref or item.stand_position
                matched_records.append(
                    (item.movement_type, stand_ref, result.runway_ref, result.path)
                )

        unique_entries: dict[str, RouteEntry] = {}
        skipped_missing_stand = 0
        skipped_invalid_path = 0
        for movement, stand_ref, runway_ref, path in matched_records:
            if not stand_ref or not stand_ref.strip():
                skipped_missing_stand += 1
                continue
            try:
                entry = RouteEntry.from_path(
                    self.airport_graph,
                    path,
                    movement=movement,
                    stand_ref=stand_ref,
                    runway_ref=runway_ref,
                    graph_identity=self.graph_id,
                )
            except ValueError:
                skipped_invalid_path += 1
                continue
            unique_entries.setdefault(entry.route_id, entry)

        entries = list(unique_entries.values())
        try:
            if replace_candidates:
                deleted, inserted, existing = self.repository.replace_candidates(
                    self.graph_id, entries
                )
            else:
                deleted = 0
                inserted, existing = self.repository.upsert_routes(entries)
        except self.flight_database.database_error as error:
            logger.exception("Failed to write %d routes to route_library", len(entries))
            raise RuntimeError(f"路径库写入失败：{error}") from error

        return {
            "graph_id": self.graph_id,
            "evaluated_flights": len(matched_records),
            "unique_routes": len(entries),
            "deleted_candidates": deleted,
            "inserted_routes": inserted,
            "existing_routes": existing,
            "skipped_missing_stand": skipped_missing_stand,
            "skipped_invalid_path": skipped_invalid_path,
        }
