"""DuckDB persistence for archived matching issues (main.match_issues)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from db import DuckDBConnection, sql_value

MATCH_ISSUES_TABLE = "main.match_issues"
BATCH_MUTATION_SIZE = 200


def make_issue_id(movement: str, flight_id: str) -> str:
    seed = f"{movement}\0{flight_id}".encode("utf-8")
    return f"iss-{hashlib.sha256(seed).hexdigest()[:16]}"


@dataclass(frozen=True, slots=True)
class MatchIssueEntry:
    issue_id: str
    movement: str
    flight_id: str
    reason: str | None = None
    graph_id: str | None = None
    created_at: datetime | None = None


class MatchIssueRepository:
    """Manage archived problematic flights in main.match_issues."""

    def __init__(self, database: DuckDBConnection) -> None:
        self._database = database

    def list_all(self) -> list[MatchIssueEntry]:
        with self._database.connection() as connection:
            rows = connection.execute(
                f"SELECT issue_id, movement, flight_id, reason, graph_id, created_at "
                f"FROM {MATCH_ISSUES_TABLE} "
                "ORDER BY created_at DESC, issue_id"
            ).fetchall()
            return [
                MatchIssueEntry(
                    issue_id=str(issue_id),
                    movement=str(movement),
                    flight_id=str(flight_id),
                    reason=str(reason) if reason is not None else None,
                    graph_id=str(graph_id) if graph_id is not None else None,
                    created_at=created_at,
                )
                for issue_id, movement, flight_id, reason, graph_id, created_at in rows
            ]

    def add(
        self,
        items: Sequence[tuple[str, str, str | None, str | None]],
    ) -> tuple[int, int]:
        """Idempotently archive (movement, flight_id, reason, graph_id) entries.

        Returns ``(inserted_count, existing_count)``.
        """
        if not items:
            return 0, 0
        deduped = list(
            {
                (movement, flight_id): (movement, flight_id, reason, graph_id)
                for movement, flight_id, reason, graph_id in items
            }.values()
        )
        now = datetime.now(timezone.utc)
        inserted = 0
        existing = 0
        with self._database.connection(write=True) as connection:
            for offset in range(0, len(deduped), BATCH_MUTATION_SIZE):
                chunk = deduped[offset : offset + BATCH_MUTATION_SIZE]
                values_sql = ", ".join(
                    "("
                    + ", ".join(
                        sql_value(value)
                        for value in (
                            make_issue_id(movement, flight_id),
                            movement,
                            flight_id,
                            (reason.strip() or None) if reason is not None else None,
                            graph_id,
                            now,
                        )
                    )
                    + ")"
                    for movement, flight_id, reason, graph_id in chunk
                )
                rows = connection.execute(
                    f"INSERT INTO {MATCH_ISSUES_TABLE} "
                    "(issue_id, movement, flight_id, reason, graph_id, created_at) "
                    f"VALUES {values_sql} "
                    "ON CONFLICT (movement, flight_id) DO NOTHING "
                    "RETURNING issue_id"
                ).fetchall()
                chunk_inserted = len(rows)
                inserted += chunk_inserted
                existing += len(chunk) - chunk_inserted
        return inserted, existing

    def remove(self, pairs: Sequence[tuple[str, str]]) -> int:
        """Remove archived flights by (movement, flight_id). Returns deleted count."""
        if not pairs:
            return 0
        deduped = list(dict.fromkeys(pairs))
        deleted = 0
        with self._database.connection(write=True) as connection:
            for offset in range(0, len(deduped), BATCH_MUTATION_SIZE):
                chunk = deduped[offset : offset + BATCH_MUTATION_SIZE]
                tuples_sql = ", ".join(
                    f"({sql_value(movement)}, {sql_value(flight_id)})"
                    for movement, flight_id in chunk
                )
                rows = connection.execute(
                    f"DELETE FROM {MATCH_ISSUES_TABLE} "
                    f"WHERE (movement, flight_id) IN ({tuples_sql}) "
                    "RETURNING issue_id"
                ).fetchall()
                deleted += len(rows)
        return deleted
