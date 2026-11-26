"""PostgreSQL persistence and OD-indexed queries for public.route_library."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from db import PostgresConnection

from .models import (
    RouteEntry,
    RouteFlightMatch,
    RouteSource,
    RouteStatus,
    deserialize_edges,
    normalize_movement,
    normalize_runway_ref,
    normalize_stand_ref,
)

ROUTE_LIBRARY_TABLE = "public.route_library"
ROUTE_FLIGHT_MATCHES_TABLE = "public.route_flight_matches"
ROUTE_LIBRARY_COLUMNS = (
    "route_id",
    "graph_id",
    "movement",
    "stand_ref",
    "runway_ref",
    "runway_interface_node",
    "edges_json",
    "edge_count",
    "total_length_m",
    "flight_count",
    "status",
    "source",
    "note",
    "created_at",
    "updated_at",
)
ROUTE_LIBRARY_SUMMARY_COLUMNS = (
    "route_id",
    "graph_id",
    "movement",
    "stand_ref",
    "runway_ref",
    "runway_interface_node",
    "edge_count",
    "total_length_m",
    "flight_count",
    "status",
    "source",
    "note",
    "created_at",
    "updated_at",
)
BATCH_INSERT_SIZE = 200


def _row_to_entry(row: Mapping[str, Any]) -> RouteEntry:
    return RouteEntry(
        route_id=str(row["route_id"]),
        graph_id=str(row["graph_id"]),
        movement=str(row["movement"]),
        stand_ref=str(row["stand_ref"]),
        runway_ref=str(row["runway_ref"]) if row["runway_ref"] is not None else None,
        runway_interface_node=str(row["runway_interface_node"]),
        edges=deserialize_edges(str(row["edges_json"])),
        edge_count=int(row["edge_count"]),
        total_length_m=float(row["total_length_m"]),
        flight_count=int(row["flight_count"]),
        status=RouteStatus(str(row["status"])),
        source=RouteSource(str(row["source"])),
        note=str(row["note"]) if row["note"] is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class RouteLibraryRepository:
    """Own idempotent inserts, review updates, and OD-indexed lookups."""

    def __init__(self, database: PostgresConnection) -> None:
        self._database = database

    def _insert_entries(
        self,
        connection: Any,
        entries: Sequence[RouteEntry],
    ) -> tuple[int, int]:
        if not entries:
            return 0, 0
        deduped = list({entry.route_id: entry for entry in entries}.values())
        now = datetime.now(timezone.utc)
        inserted = 0
        existing = 0
        columns = ", ".join(ROUTE_LIBRARY_COLUMNS)
        for offset in range(0, len(deduped), BATCH_INSERT_SIZE):
            chunk = deduped[offset : offset + BATCH_INSERT_SIZE]
            rows = connection.execute(
                f"""
                INSERT INTO {ROUTE_LIBRARY_TABLE} ({columns})
                SELECT * FROM UNNEST(
                    CAST(:route_ids AS TEXT[]),
                    CAST(:graph_ids AS TEXT[]),
                    CAST(:movements AS TEXT[]),
                    CAST(:stand_refs AS TEXT[]),
                    CAST(:runway_refs AS TEXT[]),
                    CAST(:interface_nodes AS TEXT[]),
                    CAST(:edges_jsons AS TEXT[]),
                    CAST(:edge_counts AS INTEGER[]),
                    CAST(:total_lengths AS DOUBLE PRECISION[]),
                    CAST(:flight_counts AS INTEGER[]),
                    CAST(:statuses AS TEXT[]),
                    CAST(:sources AS TEXT[]),
                    CAST(:notes AS TEXT[]),
                    CAST(:created_ats AS TIMESTAMPTZ[]),
                    CAST(:updated_ats AS TIMESTAMPTZ[])
                )
                ON CONFLICT (route_id) DO NOTHING
                RETURNING route_id
                """,
                {
                    "route_ids": [e.route_id for e in chunk],
                    "graph_ids": [e.graph_id for e in chunk],
                    "movements": [e.movement for e in chunk],
                    "stand_refs": [e.stand_ref for e in chunk],
                    "runway_refs": [e.runway_ref for e in chunk],
                    "interface_nodes": [e.runway_interface_node for e in chunk],
                    "edges_jsons": [e.edges_json for e in chunk],
                    "edge_counts": [e.edge_count for e in chunk],
                    "total_lengths": [e.total_length_m for e in chunk],
                    "flight_counts": [e.flight_count for e in chunk],
                    "statuses": [e.status.value for e in chunk],
                    "sources": [e.source.value for e in chunk],
                    "notes": [e.note for e in chunk],
                    "created_ats": [e.created_at or now for e in chunk],
                    "updated_ats": [e.updated_at or now for e in chunk],
                },
            ).fetchall()
            chunk_inserted = len(rows)
            inserted += chunk_inserted
            existing += len(chunk) - chunk_inserted
        return inserted, existing

    def _insert_flight_matches(
        self,
        connection: Any,
        flight_matches: Sequence[RouteFlightMatch],
    ) -> None:
        if not flight_matches:
            return
        deduped = list(
            {(item.route_id, item.flight_id): item for item in flight_matches}.values()
        )
        for offset in range(0, len(deduped), BATCH_INSERT_SIZE):
            chunk = deduped[offset : offset + BATCH_INSERT_SIZE]
            connection.execute(
                f"""
                INSERT INTO {ROUTE_FLIGHT_MATCHES_TABLE} (route_id, movement, flight_id)
                SELECT * FROM UNNEST(
                    CAST(:route_ids AS TEXT[]),
                    CAST(:movements AS TEXT[]),
                    CAST(:flight_ids AS TEXT[])
                )
                ON CONFLICT (route_id, flight_id) DO NOTHING
                """,
                {
                    "route_ids": [item.route_id for item in chunk],
                    "movements": [item.movement for item in chunk],
                    "flight_ids": [item.flight_id for item in chunk],
                },
            )
        affected_route_ids = list(dict.fromkeys(item.route_id for item in deduped))
        self._sync_flight_counts(connection, affected_route_ids)

    def _sync_flight_counts(
        self,
        connection: Any,
        route_ids: Sequence[str],
    ) -> None:
        for offset in range(0, len(route_ids), BATCH_INSERT_SIZE):
            chunk = list(route_ids[offset : offset + BATCH_INSERT_SIZE])
            connection.execute(
                f"""
                UPDATE {ROUTE_LIBRARY_TABLE} r
                SET flight_count = (
                    SELECT COUNT(*)
                    FROM {ROUTE_FLIGHT_MATCHES_TABLE} m
                    WHERE m.route_id = r.route_id
                )
                WHERE r.route_id = ANY(CAST(:route_ids AS TEXT[]))
                """,
                {"route_ids": chunk},
            )

    def upsert_routes(
        self,
        entries: Sequence[RouteEntry],
        *,
        flight_matches: Sequence[RouteFlightMatch] = (),
    ) -> tuple[int, int]:
        """Insert new routes without overwriting existing review status or notes.

        Returns ``(inserted_count, existing_count)``.
        """
        if not entries and not flight_matches:
            return 0, 0
        with self._database.connection(write=True) as connection:
            inserted, existing = self._insert_entries(connection, entries)
            self._insert_flight_matches(connection, flight_matches)
            return inserted, existing

    def replace_candidates(
        self,
        graph_id: str,
        entries: Sequence[RouteEntry],
        *,
        flight_matches: Sequence[RouteFlightMatch] = (),
    ) -> tuple[int, int, int]:
        """Replace candidate routes for ``graph_id`` while preserving reviewed/manual ones.

        Runs in a single write transaction and returns
        ``(deleted_candidates, inserted_count, existing_count)``.
        """
        with self._database.connection(write=True) as connection:
            deleted_rows = connection.execute(
                f"DELETE FROM {ROUTE_LIBRARY_TABLE} "
                "WHERE graph_id = :graph_id AND status = :status "
                "RETURNING route_id",
                {"graph_id": graph_id, "status": RouteStatus.CANDIDATE.value},
            ).fetchall()
            inserted, existing = self._insert_entries(connection, entries)
            self._insert_flight_matches(connection, flight_matches)
            return len(deleted_rows), inserted, existing

    def get(self, route_id: str) -> RouteEntry | None:
        columns = ", ".join(ROUTE_LIBRARY_COLUMNS)
        with self._database.connection() as connection:
            row = connection.execute(
                f"SELECT {columns} FROM {ROUTE_LIBRARY_TABLE} WHERE route_id = :route_id",
                {"route_id": route_id},
            ).mappings().fetchone()
            return _row_to_entry(row) if row is not None else None

    def list_flight_ids(self, route_id: str) -> list[str]:
        """Return all deduplicated flight_ids recorded as matching ``route_id``."""
        with self._database.connection() as connection:
            rows = connection.execute(
                f"SELECT flight_id FROM {ROUTE_FLIGHT_MATCHES_TABLE} "
                "WHERE route_id = :route_id ORDER BY flight_id",
                {"route_id": route_id},
            ).fetchall()
            return [str(row[0]) for row in rows]

    def find_by_od(
        self,
        *,
        graph_id: str | None = None,
        movement: str | None = None,
        stand_ref: str | None = None,
        stand_refs: Sequence[str] | None = None,
        runway_ref: str | None = None,
        runway_refs: Sequence[str] | None = None,
        runway_is_null: bool = False,
        status: RouteStatus | str | None = None,
        exclude_rejected: bool = False,
    ) -> list[RouteEntry]:
        """Query routes using the (graph_id, movement, stand_ref, runway_ref) index."""
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if graph_id is not None:
            clauses.append("graph_id = :graph_id")
            params["graph_id"] = graph_id
        if movement is not None:
            clauses.append("movement = :movement")
            params["movement"] = normalize_movement(movement)
        if stand_refs is not None:
            normalized_stands = list(dict.fromkeys(normalize_stand_ref(ref) for ref in stand_refs))
            if not normalized_stands:
                return []
            clauses.append("stand_ref = ANY(CAST(:stand_refs AS TEXT[]))")
            params["stand_refs"] = normalized_stands
        elif stand_ref is not None:
            clauses.append("stand_ref = :stand_ref")
            params["stand_ref"] = normalize_stand_ref(stand_ref)
        if runway_is_null:
            clauses.append("runway_ref IS NULL")
        elif runway_refs is not None:
            normalized_runways = list(
                dict.fromkeys(
                    ref for raw in runway_refs if (ref := normalize_runway_ref(raw)) is not None
                )
            )
            if not normalized_runways:
                return []
            clauses.append("runway_ref = ANY(CAST(:runway_refs AS TEXT[]))")
            params["runway_refs"] = normalized_runways
        elif runway_ref is not None:
            clauses.append("runway_ref = :runway_ref")
            params["runway_ref"] = normalize_runway_ref(runway_ref)
        if status is not None:
            clauses.append("status = :status")
            params["status"] = RouteStatus(status).value
        elif exclude_rejected:
            clauses.append("status <> :rejected_status")
            params["rejected_status"] = RouteStatus.REJECTED.value

        columns = ", ".join(ROUTE_LIBRARY_COLUMNS)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._database.connection() as connection:
            rows = connection.execute(
                f"SELECT {columns} FROM {ROUTE_LIBRARY_TABLE}{where} "
                "ORDER BY movement, runway_ref NULLS LAST, "
                "flight_count DESC, total_length_m, route_id",
                params,
            ).mappings()
            return [_row_to_entry(row) for row in rows]

    def list_metadata(self, *, graph_id: str | None = None) -> list[dict[str, Any]]:
        """Query route metadata without fetching or deserializing edges_json."""
        columns = ", ".join(ROUTE_LIBRARY_SUMMARY_COLUMNS)
        params: dict[str, Any] = {}
        where = ""
        if graph_id is not None:
            where = " WHERE graph_id = :graph_id"
            params["graph_id"] = graph_id
        with self._database.connection() as connection:
            rows = connection.execute(
                f"SELECT {columns} FROM {ROUTE_LIBRARY_TABLE}{where} "
                "ORDER BY movement, stand_ref, runway_ref NULLS LAST, "
                "flight_count DESC, total_length_m, route_id",
                params,
            ).mappings()
            return [self._summary_row_to_dict(row) for row in rows]

    @staticmethod
    def _summary_row_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "route_id": str(row["route_id"]),
            "graph_id": str(row["graph_id"]),
            "movement": str(row["movement"]),
            "stand_ref": str(row["stand_ref"]),
            "runway_ref": str(row["runway_ref"]) if row["runway_ref"] is not None else None,
            "runway_interface_node": str(row["runway_interface_node"]),
            "edge_count": int(row["edge_count"]),
            "total_length_m": float(row["total_length_m"]),
            "flight_count": int(row["flight_count"]),
            "status": RouteStatus(str(row["status"])).value,
            "source": RouteSource(str(row["source"])).value,
            "note": str(row["note"]) if row["note"] is not None else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def query_metadata_page(
        self,
        *,
        graph_id: str | None = None,
        movement: str | None = None,
        stand_ref: str | None = None,
        runway_ref: str | None = None,
        runway_is_null: bool = False,
        status: RouteStatus | str | None = None,
        query: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Filter, paginate, and summarize route metadata directly in PostgreSQL."""
        scope_clauses: list[str] = []
        scope_params: dict[str, Any] = {}
        if graph_id is not None:
            scope_clauses.append("graph_id = :graph_id")
            scope_params["graph_id"] = graph_id
        scope_where = f" WHERE {' AND '.join(scope_clauses)}" if scope_clauses else ""

        filter_clauses = list(scope_clauses)
        filter_params = dict(scope_params)
        if movement is not None:
            filter_clauses.append("movement = :movement")
            filter_params["movement"] = normalize_movement(movement)
        if stand_ref is not None:
            filter_clauses.append("stand_ref = :stand_ref")
            filter_params["stand_ref"] = normalize_stand_ref(stand_ref)
        if runway_is_null:
            filter_clauses.append("runway_ref IS NULL")
        elif runway_ref is not None:
            filter_clauses.append("runway_ref = :runway_ref")
            filter_params["runway_ref"] = normalize_runway_ref(runway_ref)
        if status is not None:
            filter_clauses.append("status = :status")
            filter_params["status"] = RouteStatus(status).value
        search = query.strip().casefold()
        if search:
            filter_clauses.append(
                "("
                "strpos(lower(route_id), :search) > 0 "
                "OR strpos(lower(stand_ref), :search) > 0 "
                "OR strpos(lower(COALESCE(runway_ref, '')), :search) > 0 "
                "OR strpos(lower(runway_interface_node), :search) > 0 "
                "OR strpos(lower(COALESCE(note, '')), :search) > 0"
                ")"
            )
            filter_params["search"] = search

        filter_where = f" WHERE {' AND '.join(filter_clauses)}" if filter_clauses else ""
        columns = ", ".join(ROUTE_LIBRARY_SUMMARY_COLUMNS)
        with self._database.connection() as connection:
            stand_options = [
                str(r[0])
                for r in connection.execute(
                    f"SELECT DISTINCT stand_ref FROM {ROUTE_LIBRARY_TABLE}{scope_where} "
                    "ORDER BY stand_ref",
                    scope_params,
                ).fetchall()
            ]
            runway_options = [
                str(r[0])
                for r in connection.execute(
                    f"SELECT DISTINCT runway_ref FROM {ROUTE_LIBRARY_TABLE}"
                    f"{scope_where + ' AND ' if scope_where else ' WHERE '}"
                    "runway_ref IS NOT NULL AND runway_ref <> '' "
                    "ORDER BY runway_ref",
                    scope_params,
                ).fetchall()
            ]
            status_counts = {member.value: 0 for member in RouteStatus}
            for st_val, cnt in connection.execute(
                f"SELECT status, COUNT(*) FROM {ROUTE_LIBRARY_TABLE}{scope_where} GROUP BY status",
                scope_params,
            ).fetchall():
                status_counts[str(st_val)] = int(cnt)

            total_row = connection.execute(
                f"SELECT COUNT(*) FROM {ROUTE_LIBRARY_TABLE}{filter_where}",
                filter_params,
            ).fetchone()
            total = int(total_row[0]) if total_row is not None else 0

            page_rows = connection.execute(
                f"SELECT {columns} FROM {ROUTE_LIBRARY_TABLE}{filter_where} "
                "ORDER BY movement, stand_ref, runway_ref NULLS LAST, total_length_m, route_id "
                "LIMIT :limit OFFSET :offset",
                {**filter_params, "limit": limit, "offset": offset},
            ).mappings()
            items = [self._summary_row_to_dict(row) for row in page_rows]

        return {
            "items": items,
            "total": total,
            "stand_options": stand_options,
            "runway_options": runway_options,
            "status_counts": status_counts,
        }

    def update_status(
        self,
        route_id: str,
        status: RouteStatus | str,
        *,
        note: str | None = None,
    ) -> RouteEntry:
        """Update review status and note for an existing route."""
        normalized_status = RouteStatus(status).value
        now = datetime.now(timezone.utc)
        columns = ", ".join(ROUTE_LIBRARY_COLUMNS)
        with self._database.connection(write=True) as connection:
            row = connection.execute(
                f"UPDATE {ROUTE_LIBRARY_TABLE} "
                "SET status = :status, note = :note, updated_at = :updated_at "
                "WHERE route_id = :route_id "
                f"RETURNING {columns}",
                {
                    "status": normalized_status,
                    "note": note,
                    "updated_at": now,
                    "route_id": route_id,
                },
            ).mappings().fetchone()
            if row is None:
                raise KeyError(f"Unknown route_id: {route_id!r}")
            return _row_to_entry(row)

    def delete(self, route_id: str) -> bool:
        with self._database.connection(write=True) as connection:
            row = connection.execute(
                f"DELETE FROM {ROUTE_LIBRARY_TABLE} "
                "WHERE route_id = :route_id "
                "RETURNING route_id",
                {"route_id": route_id},
            ).fetchone()
            return row is not None
