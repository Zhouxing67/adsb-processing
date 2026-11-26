"""Route library listing, geometry resolution, review, and match import service."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from math import ceil
from typing import Any

from airport_surface import AirportGraph
from flight.flight_repository import FlightDatabase
from path_map import PathGraphMismatch
from route_library.anomalies import detect_route_anomalies
from route_library.models import (
    RouteEntry,
    RouteFlightMatch,
    RouteStatus,
    normalize_movement,
    normalize_runway_ref,
)
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
        self.repository = RouteLibraryRepository(flight_database.postgres)
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
            "flight_count": entry.flight_count,
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
            "flight_count": entry["flight_count"],
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
        start = (page - 1) * page_size

        result = self.repository.query_metadata_page(
            graph_id=None if all_graphs else self.graph_id,
            movement=normalized_movement,
            stand_ref=normalized_stand,
            runway_ref=normalized_runway,
            runway_is_null=runway_is_null,
            status=normalized_status,
            query=query,
            offset=start,
            limit=page_size,
        )
        total = result["total"]
        total_pages = ceil(total / page_size) if total else 0
        if total_pages and page > total_pages:
            raise self._page_out_of_range(page, total_pages)
        if not total_pages and page != 1:
            raise self._page_out_of_range(page, 0)
        page_items = [self._serialize_metadata(entry) for entry in result["items"]]
        return {
            "items": page_items,
            "has_route_library": True,
            "current_graph_id": self.graph_id,
            "can_edit": not self.flight_database.read_only,
            "stand_options": result["stand_options"],
            "runway_options": result["runway_options"],
            "status_counts": result["status_counts"],
            "total": total,
            "total_pages": total_pages,
            "page": page if total_pages else 0,
            "page_size": page_size,
        }

    def coverage(self) -> dict[str, Any]:
        """Compute fine-grained (stand) and coarse-grained (cluster) OD coverage."""
        all_stands = sorted(self.airport_graph.stand_to_edges.keys())
        stand_set = set(all_stands)
        all_runways = sorted(self.airport_graph.runway_to_edges.keys())
        runway_set = set(all_runways)

        clustered_stands = [
            stand for stand in all_stands if self.airport_graph.cluster_for_stand(stand) is not None
        ]
        unclustered_stands = [
            stand for stand in all_stands if self.airport_graph.cluster_for_stand(stand) is None
        ]

        active_keys = self.repository.list_active_od_keys(self.graph_id)
        fine_ods: set[tuple[str, str, str]] = set()
        effective_ods: set[tuple[str, str, str]] = set()
        fine_stands: set[str] = set()
        effective_stands: set[str] = set()
        covered_runways: set[str] = set()

        for movement, stand_ref, raw_runway in active_keys:
            if stand_ref not in stand_set:
                continue
            fine_stands.add(stand_ref)
            cluster = self.airport_graph.cluster_for_stand(stand_ref)
            peer_stands = (
                [
                    peer
                    for peer in self.airport_graph.stand_refs_in_cluster(cluster.c_id)
                    if peer in stand_set
                ]
                if cluster is not None
                else [stand_ref]
            )
            effective_stands.update(peer_stands)

            if not raw_runway:
                continue
            matched_runways = [
                part.strip().upper()
                for part in raw_runway.split("/")
                if part.strip().upper() in runway_set
            ]
            if raw_runway.upper() in runway_set and raw_runway.upper() not in matched_runways:
                matched_runways.append(raw_runway.upper())
            for runway_ref in matched_runways:
                covered_runways.add(runway_ref)
                fine_ods.add((movement, stand_ref, runway_ref))
                for peer in peer_stands:
                    effective_ods.add((movement, peer, runway_ref))

        per_movement_total = len(all_stands) * len(all_runways)
        total_ods = per_movement_total * 2
        by_movement = []
        for movement in ("departure", "arrival"):
            fine_count = sum(1 for item in fine_ods if item[0] == movement)
            effective_count = sum(1 for item in effective_ods if item[0] == movement)
            by_movement.append(
                {
                    "movement": movement,
                    "total_ods": per_movement_total,
                    "fine_covered_ods": fine_count,
                    "effective_covered_ods": effective_count,
                    "fine_od_rate": (
                        round(fine_count / per_movement_total, 4) if per_movement_total else 0.0
                    ),
                    "effective_od_rate": (
                        round(effective_count / per_movement_total, 4)
                        if per_movement_total
                        else 0.0
                    ),
                }
            )

        return {
            "graph_id": self.graph_id,
            "total_stands": len(all_stands),
            "clustered_stands": len(clustered_stands),
            "cluster_count": len(self.airport_graph.stand_clusters),
            "fine_covered_stands": len(fine_stands),
            "effective_covered_stands": len(effective_stands),
            "total_runways": len(all_runways),
            "covered_runways": len(covered_runways),
            "total_ods": total_ods,
            "fine_covered_ods": len(fine_ods),
            "effective_covered_ods": len(effective_ods),
            "fine_od_rate": round(len(fine_ods) / total_ods, 4) if total_ods else 0.0,
            "effective_od_rate": round(len(effective_ods) / total_ods, 4) if total_ods else 0.0,
            "by_movement": by_movement,
            "uncovered_stands": [stand for stand in all_stands if stand not in effective_stands],
            "unclustered_stands": unclustered_stands,
            "uncovered_runways": [rwy for rwy in all_runways if rwy not in covered_runways],
        }

    def geometry(self, route_id: str) -> dict[str, Any]:
        entry = self.repository.get(route_id)
        if entry is None:
            raise KeyError(f"Unknown route_id: {route_id!r}")
        try:
            path = entry.resolve(self.airport_graph, actual_graph_id=self.graph_id)
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

    def batch_update_review(
        self,
        route_ids: Sequence[str],
        status: str,
        *,
        note: str | None = None,
    ) -> dict[str, Any]:
        if self.flight_database.read_only:
            raise ValueError("当前数据库为只读模式，无法更新路径审校状态")
        normalized_status = RouteStatus(status).value
        cleaned_note = (note.strip() or None) if note is not None else None
        try:
            updated_ids = self.repository.batch_update_status(
                route_ids,
                normalized_status,
                note=cleaned_note,
            )
        except self.flight_database.database_error as error:
            raise RuntimeError("批量路径审校更新失败") from error
        return {
            "updated_count": len(updated_ids),
            "route_ids": updated_ids,
            "status": normalized_status,
        }

    def detect_anomalies(self, route_ids: Sequence[str]) -> dict[str, Any]:
        entries = self.repository.get_many(route_ids)
        if not entries:
            return {"checked_count": 0, "anomalous_count": 0, "items": []}
        reference_entries = self.repository.find_by_od(
            graph_id=self.graph_id,
            exclude_rejected=True,
        )
        reports = detect_route_anomalies(
            entries,
            airport_graph=self.airport_graph,
            reference_entries=reference_entries,
        )
        by_id = {entry.route_id: entry for entry in entries}
        anomalous_items = []
        for report in reports:
            if not report.is_anomalous:
                continue
            entry = by_id[report.route_id]
            anomalous_items.append(
                {
                    "route_id": entry.route_id,
                    "movement": entry.movement,
                    "stand_ref": entry.stand_ref,
                    "runway_ref": entry.runway_ref,
                    "total_length_m": entry.total_length_m,
                    "flight_count": entry.flight_count,
                    "status": entry.status.value,
                    "reasons": [
                        {"code": reason.code, "message": reason.message}
                        for reason in report.reasons
                    ],
                }
            )
        return {
            "checked_count": len(entries),
            "anomalous_count": len(anomalous_items),
            "items": anomalous_items,
        }

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
                candidate_keys = list(self.results)
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
                    (item.flight_id, item.movement_type, stand_ref, result.runway_ref, result.path)
                )

        unique_entries: dict[str, RouteEntry] = {}
        flight_matches: list[RouteFlightMatch] = []
        skipped_missing_stand = 0
        skipped_invalid_path = 0
        for flight_id, movement, stand_ref, runway_ref, path in matched_records:
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
            if flight_id and str(flight_id).strip():
                flight_matches.append(
                    RouteFlightMatch(
                        route_id=entry.route_id,
                        movement=movement,
                        flight_id=str(flight_id),
                    )
                )

        entries = list(unique_entries.values())
        try:
            if replace_candidates:
                deleted, inserted, existing = self.repository.replace_candidates(
                    self.graph_id, entries, flight_matches=flight_matches
                )
            else:
                deleted = 0
                inserted, existing = self.repository.upsert_routes(
                    entries, flight_matches=flight_matches
                )
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
