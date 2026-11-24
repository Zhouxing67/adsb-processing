"""DuckDB connections to a local file or a Quack server."""

from __future__ import annotations

import math
import secrets
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / "outputs"
TOKEN_FILE = STATE_DIR / "quack.token"
CORE_SCHEMA_SQL = REPO_ROOT / "sql" / "schema" / "01_core_tables.sql"


def get_token() -> str:
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_hex(32), encoding="ascii")

    return TOKEN_FILE.read_text(encoding="ascii").strip()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_value(value: Any) -> str:
    """Render a scalar Python value as a safe DuckDB SQL literal for bulk DML."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Non-finite float cannot be serialized to SQL: {value!r}")
        return repr(value)
    if isinstance(value, datetime):
        prefix = "TIMESTAMPTZ" if value.tzinfo is not None else "TIMESTAMP"
        return f"{prefix} {sql_literal(value.isoformat())}"
    if isinstance(value, date):
        return f"DATE {sql_literal(value.isoformat())}"
    if isinstance(value, str):
        return sql_literal(value)
    raise TypeError(f"Unsupported SQL literal value type: {type(value).__qualname__}")


def attach_sql(uri: str, token: str, read_only: bool = False) -> str:
    access = ", READ_ONLY" if read_only else ""
    return f"ATTACH {sql_literal(uri)} AS adsb (TOKEN {sql_literal(token)}{access}); "


def apply_core_schema(connection: Any, schema_path: Path = CORE_SCHEMA_SQL) -> None:
    """Apply the canonical SQL DDL file to an open DuckDB connection."""
    sql = schema_path.read_text(encoding="utf-8")
    connection.execute(sql)


class DuckDBSession:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        return self._connection.exec_driver_sql(sql, parameters)


class DuckDBConnection:
    def __init__(self, database: str | Path, *, read_only: bool, quack_uri: str | None) -> None:
        try:
            import duckdb_engine  # noqa: F401
            from sqlalchemy import URL, create_engine, event
            from sqlalchemy.exc import SQLAlchemyError
            from sqlalchemy.pool import NullPool, QueuePool
        except ImportError as error:
            raise ValueError(
                "Install database support with: uv sync --extra stand-editing"
            ) from error

        path = Path(database).resolve(strict=True)
        self.read_only = read_only
        self._quack_uri = quack_uri
        self._quack_token = get_token() if quack_uri else None
        self.database_error = SQLAlchemyError
        engine_kwargs: dict[str, Any] = {
            "connect_args": {"read_only": read_only and not quack_uri},
        }
        if quack_uri:
            engine_kwargs.update(
                poolclass=QueuePool,
                pool_size=4,
                max_overflow=4,
                pool_pre_ping=True,
            )
        else:
            engine_kwargs["poolclass"] = NullPool
        self._engine = create_engine(
            URL.create("duckdb", database=":memory:" if quack_uri else str(path)),
            **engine_kwargs,
        )
        if quack_uri:
            event.listen(self._engine, "connect", self._initialize_quack)

    def _initialize_quack(self, connection: Any, _record: Any) -> None:
        token = self._quack_token or get_token()
        connection.execute("LOAD quack")
        connection.execute(attach_sql(self._quack_uri, token, self.read_only))
        connection.execute("USE adsb.main")

    def close(self) -> None:
        self._engine.dispose()

    @contextmanager
    def connection(self, *, write: bool = False):
        scope = self._engine.begin() if write else self._engine.connect()
        with scope as connection:
            yield DuckDBSession(connection)

    def bind(self, connection: Any, *values: Any) -> tuple[tuple[str, ...], tuple[Any, ...]]:
        """Return SQL placeholders and parameters for this connection."""
        if not self._quack_uri:
            return ("?",) * len(values), values

        # Quack pushdown can lose prepared parameters. DuckDB binds these values
        # locally and resolves getvariable() to a constant before pushdown.
        placeholders = []
        for index, value in enumerate(values):
            name = f"flight_query_parameter_{index}"
            connection.execute(f"SET VARIABLE {name} = ?", (value,))
            placeholders.append(f"getvariable('{name}')")
        return tuple(placeholders), ()
