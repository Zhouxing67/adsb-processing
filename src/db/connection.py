"""PostgreSQL connections and schema helpers via SQLAlchemy + psycopg."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_SCHEMA_SQL = REPO_ROOT / "sql" / "schema" / "01_core_tables.sql"


def normalize_postgres_dsn(dsn: str) -> str:
    """Normalize a PostgreSQL DSN to use the psycopg (v3) SQLAlchemy driver."""
    cleaned = dsn.strip()
    if not cleaned:
        raise ValueError("Database DSN must be a non-empty string")
    if cleaned.startswith("postgresql+psycopg://"):
        return cleaned
    if cleaned.startswith("postgresql://"):
        return "postgresql+psycopg://" + cleaned.removeprefix("postgresql://")
    if cleaned.startswith("postgres://"):
        return "postgresql+psycopg://" + cleaned.removeprefix("postgres://")
    raise ValueError(f"Unsupported database DSN scheme (expected postgresql://): {dsn!r}")


def apply_core_schema(target: Any, schema_path: Path = CORE_SCHEMA_SQL) -> None:
    """Apply the canonical PostgreSQL DDL file to an open connection or PostgresConnection."""
    sql = schema_path.read_text(encoding="utf-8")
    if isinstance(target, PostgresConnection):
        raw_conn = target.raw_connection()
        try:
            with raw_conn.cursor() as cur:
                cur.execute(sql)
            raw_conn.commit()
        finally:
            raw_conn.close()
        return

    if hasattr(target, "cursor"):
        with target.cursor() as cur:
            cur.execute(sql)
        if hasattr(target, "commit"):
            target.commit()
        return

    target.execute(sql)


class DatabaseSession:
    """Thin wrapper around a SQLAlchemy Connection using named :param bindings."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def execute(self, sql: str, parameters: Mapping[str, Any] | None = None) -> Any:
        return self._connection.execute(text(sql), parameters or {})


class PostgresConnection:
    """Manage a pooled SQLAlchemy Engine for PostgreSQL."""

    def __init__(self, dsn: str, *, read_only: bool = False) -> None:
        self.dsn = normalize_postgres_dsn(dsn)
        self.read_only = read_only
        self.database_error: type[Exception] = SQLAlchemyError
        connect_args: dict[str, Any] = {}
        if read_only:
            connect_args["options"] = "-c default_transaction_read_only=on"
        self._engine = create_engine(
            self.dsn,
            poolclass=QueuePool,
            pool_size=4,
            max_overflow=4,
            pool_pre_ping=True,
            connect_args=connect_args,
        )

    def raw_connection(self) -> Any:
        return self._engine.raw_connection()

    def close(self) -> None:
        self._engine.dispose()

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[DatabaseSession]:
        if write and self.read_only:
            raise PermissionError("Database connection is read-only")
        scope = self._engine.begin() if write else self._engine.connect()
        with scope as connection:
            yield DatabaseSession(connection)
