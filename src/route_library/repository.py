"""DuckDB persistence and OD-indexed queries for main.route_library."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from flight.duckdb_connection import DuckDBConnection

from .models import (
    RouteEntry,
    RouteSource,
    RouteStatus,
    deserialize_edges,
    normalize_movement,
    normalize_runway_ref,
    normalize_stand_ref,
)

ROUTE_LIBRARY_TABLE = "main.route_library"
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
    "status",
    "source",
    "note",
    "created_at",
    "updated_at",
)

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {ROUTE_LIBRARY_TABLE} (
    route_id              VARCHAR PRIMARY KEY,
    graph_id              VARCHAR NOT NULL,
    movement              VARCHAR NOT NULL,
    stand_ref             VARCHAR NOT NULL,
    runway_ref            VARCHAR,
    runway_interface_node VARCHAR NOT NULL,
    edges_json            VARCHAR NOT NULL,
    edge_count            INTEGER NOT NULL,
    total_length_m        DOUBLE  NOT NULL,
    status                VARCHAR NOT NULL DEFAULT 'candidate',
    source                VARCHAR NOT NULL DEFAULT 'matched',
    note                  VARCHAR,
    created_at            TIMESTAMPTZ NOT NULL,
    updated_at            TIMESTAMPTZ NOT NULL
)
"""

CREATE_OD_INDEX_SQL = f"""
CREATE INDEX IF NOT EXISTS idx_route_library_od
ON {ROUTE_LIBRARY_TABLE} (graph_id, movement, stand_ref, runway_ref)
"""


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
        status=RouteStatus(str(row["status"])),
        source=RouteSource(str(row["source"])),
        note=str(row["note"]) if row["note"] is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class RouteLibraryRepository:
    """Own schema management, idempotent inserts, and OD-indexed lookups."""

    def __init__(self, database: DuckDBConnection) -> None:
        self._database = database

    def ensure_schema(self) -> None:
        """Create the route_library table and OD index if they do not exist."""
        with self._database.connection(write=True) as connection:
            connection.execute(CREATE_TABLE_SQL)
            connection.execute(CREATE_OD_INDEX_SQL)

    def _insert_entries(
        self,
        connection: Any,
        entries: Sequence[RouteEntry],
    ) -> tuple[int, int]:
        if not entries:
            return 0, 0
        deduped = list(dict.fromkeys(entries))
        now = datetime.now(timezone.utc)
        inserted = 0
        existing = 0
        columns = ", ".join(ROUTE_LIBRARY_COLUMNS)
        for entry in deduped:
            created_at = entry.created_at or now
            updated_at = entry.updated_at or now
            placeholders, parameters = self._database.bind(
                connection,
                entry.route_id,
                entry.graph_id,
                entry.movement,
                entry.stand_ref,
                entry.runway_ref,
                entry.runway_interface_node,
                entry.edges_json,
                entry.edge_count,
                entry.total_length_m,
                entry.status.value,
                entry.source.value,
                entry.note,
                created_at,
                updated_at,
            )
            row = connection.execute(
                f"INSERT INTO {ROUTE_LIBRARY_TABLE} ({columns}) "
                f"VALUES ({', '.join(placeholders)}) "
                "ON CONFLICT (route_id) DO NOTHING "
                "RETURNING route_id",
                parameters,
            ).fetchone()
            if row is not None:
                inserted += 1
            else:
                existing += 1
        return inserted, existing

    def upsert_routes(self, entries: Sequence[RouteEntry]) -> tuple[int, int]:
        """Insert new routes without overwriting existing review status or notes.

        Returns ``(inserted_count, existing_count)``.
        """
        if not entries:
            return 0, 0
        with self._database.connection(write=True) as connection:
            connection.execute(CREATE_TABLE_SQL)
            connection.execute(CREATE_OD_INDEX_SQL)
            return self._insert_entries(connection, entries)

    def replace_candidates(
        self,
        graph_id: str,
        entries: Sequence[RouteEntry],
    ) -> tuple[int, int, int]:
        """Replace candidate routes for ``graph_id`` while preserving reviewed/manual ones.

        Runs in a single write transaction and returns
        ``(deleted_candidates, inserted_count, existing_count)``.
        """
        with self._database.connection(write=True) as connection:
            connection.execute(CREATE_TABLE_SQL)
            connection.execute(CREATE_OD_INDEX_SQL)
            (graph_val, status_val), parameters = self._database.bind(
                connection, graph_id, RouteStatus.CANDIDATE.value
            )
            deleted_rows = connection.execute(
                f"DELETE FROM {ROUTE_LIBRARY_TABLE} "
                f"WHERE graph_id = {graph_val} AND status = {status_val} "
                "RETURNING route_id",
                parameters,
            ).fetchall()
            inserted, existing = self._insert_entries(connection, entries)
            return len(deleted_rows), inserted, existing

    def get(self, route_id: str) -> RouteEntry | None:
        columns = ", ".join(ROUTE_LIBRARY_COLUMNS)
        with self._database.connection() as connection:
            (identifier,), parameters = self._database.bind(connection, route_id)
            row = connection.execute(
                f"SELECT {columns} FROM {ROUTE_LIBRARY_TABLE} WHERE route_id = {identifier}",
                parameters,
            ).mappings().fetchone()
            return _row_to_entry(row) if row is not None else None

    def find_by_od(
        self,
        *,
        graph_id: str | None = None,
        movement: str | None = None,
        stand_ref: str | None = None,
        runway_ref: str | None = None,
        runway_is_null: bool = False,
        status: RouteStatus | str | None = None,
    ) -> list[RouteEntry]:
        """Query routes using the (graph_id, movement, stand_ref, runway_ref) index."""
        clauses: list[str] = []
        values: list[Any] = []
        if graph_id is not None:
            clauses.append("graph_id = {}")
            values.append(graph_id)
        if movement is not None:
            clauses.append("movement = {}")
            values.append(normalize_movement(movement))
        if stand_ref is not None:
            clauses.append("stand_ref = {}")
            values.append(normalize_stand_ref(stand_ref))
        if runway_is_null:
            clauses.append("runway_ref IS NULL")
        elif runway_ref is not None:
            clauses.append("runway_ref = {}")
            values.append(normalize_runway_ref(runway_ref))
        if status is not None:
            clauses.append("status = {}")
            values.append(RouteStatus(status).value)

        columns = ", ".join(ROUTE_LIBRARY_COLUMNS)
        with self._database.connection() as connection:
            placeholders, parameters = self._database.bind(connection, *values)
            placeholder_iter = iter(placeholders)
            rendered = [
                clause.format(next(placeholder_iter)) if "{}" in clause else clause
                for clause in clauses
            ]
            where = f" WHERE {' AND '.join(rendered)}" if rendered else ""
            rows = connection.execute(
                f"SELECT {columns} FROM {ROUTE_LIBRARY_TABLE}{where} "
                "ORDER BY movement, stand_ref, runway_ref NULLS LAST, total_length_m, route_id",
                parameters,
            ).mappings()
            return [_row_to_entry(row) for row in rows]

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
            (status_val, note_val, updated_val, identifier), parameters = self._database.bind(
                connection, normalized_status, note, now, route_id
            )
            row = connection.execute(
                f"UPDATE {ROUTE_LIBRARY_TABLE} "
                f"SET status = {status_val}, note = {note_val}, updated_at = {updated_val} "
                f"WHERE route_id = {identifier} "
                f"RETURNING {columns}",
                parameters,
            ).mappings().fetchone()
            if row is None:
                raise KeyError(f"Unknown route_id: {route_id!r}")
            return _row_to_entry(row)

    def delete(self, route_id: str) -> bool:
        with self._database.connection(write=True) as connection:
            (identifier,), parameters = self._database.bind(connection, route_id)
            row = connection.execute(
                f"DELETE FROM {ROUTE_LIBRARY_TABLE} WHERE route_id = {identifier} "
                "RETURNING route_id",
                parameters,
            ).fetchone()
            return row is not None
