"""PostgreSQL persistence for archived matching issues (public.match_issues)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from db import PostgresConnection

MATCH_ISSUES_TABLE = "public.match_issues"
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
    """Manage archived problematic flights in public.match_issues."""

    def __init__(self, database: PostgresConnection) -> None:
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
                rows = connection.execute(
                    f"""
                    INSERT INTO {MATCH_ISSUES_TABLE} (
                        issue_id, movement, flight_id, reason, graph_id, created_at
                    )
                    SELECT * FROM UNNEST(
                        CAST(:issue_ids AS TEXT[]),
                        CAST(:movements AS TEXT[]),
                        CAST(:flight_ids AS TEXT[]),
                        CAST(:reasons AS TEXT[]),
                        CAST(:graph_ids AS TEXT[]),
                        CAST(:created_ats AS TIMESTAMPTZ[])
                    )
                    ON CONFLICT (movement, flight_id) DO NOTHING
                    RETURNING issue_id
                    """,
                    {
                        "issue_ids": [make_issue_id(m, fid) for m, fid, _, _ in chunk],
                        "movements": [m for m, _, _, _ in chunk],
                        "flight_ids": [fid for _, fid, _, _ in chunk],
                        "reasons": [
                            (reason.strip() or None) if reason is not None else None
                            for _, _, reason, _ in chunk
                        ],
                        "graph_ids": [gid for _, _, _, gid in chunk],
                        "created_ats": [now for _ in chunk],
                    },
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
                rows = connection.execute(
                    f"""
                    DELETE FROM {MATCH_ISSUES_TABLE} AS target
                    USING UNNEST(
                        CAST(:movements AS TEXT[]),
                        CAST(:flight_ids AS TEXT[])
                    ) AS keys(movement, flight_id)
                    WHERE target.movement = keys.movement
                      AND target.flight_id = keys.flight_id
                    RETURNING target.issue_id
                    """,
                    {
                        "movements": [m for m, _ in chunk],
                        "flight_ids": [fid for _, fid in chunk],
                    },
                ).fetchall()
                deleted += len(rows)
        return deleted
