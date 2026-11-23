"""DuckDB connections to a local file or a Quack server."""

import secrets
from contextlib import contextmanager
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parents[2] / "outputs"
TOKEN_FILE = STATE_DIR / "quack.token"


def get_token() -> str:
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_hex(32), encoding="ascii")

    return TOKEN_FILE.read_text(encoding="ascii").strip()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def attach_sql(uri: str, token: str, read_only: bool = False) -> str:
    access = ", READ_ONLY" if read_only else ""
    return f"ATTACH {sql_literal(uri)} AS adsb (TOKEN {sql_literal(token)}{access}); "


class DuckDBSession:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, parameters=()):
        return self._connection.exec_driver_sql(sql, parameters)


class DuckDBConnection:
    def __init__(self, database: str | Path, *, read_only: bool, quack_uri: str | None):
        try:
            import duckdb_engine  # noqa: F401
            from sqlalchemy import URL, create_engine, event
            from sqlalchemy.exc import SQLAlchemyError
            from sqlalchemy.pool import NullPool
        except ImportError as error:
            raise ValueError(
                "Install database support with: uv sync --extra stand-editing"
            ) from error

        path = Path(database).resolve(strict=True)
        self.read_only = read_only
        self._quack_uri = quack_uri
        self.database_error = SQLAlchemyError
        self._engine = create_engine(
            URL.create("duckdb", database=":memory:" if quack_uri else str(path)),
            connect_args={"read_only": read_only and not quack_uri},
            poolclass=NullPool,
        )
        if quack_uri:
            event.listen(self._engine, "connect", self._initialize_quack)

    def _initialize_quack(self, connection, _record):
        connection.execute("LOAD quack")
        connection.execute(attach_sql(self._quack_uri, get_token(), self.read_only))
        connection.execute("USE adsb.main")

    @contextmanager
    def connection(self, *, write: bool = False):
        scope = self._engine.begin() if write else self._engine.connect()
        with scope as connection:
            yield DuckDBSession(connection)

    def bind(self, connection, *values):
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
