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
    return f"ATTACH {sql_literal(uri)} AS adsb (TOKEN {sql_literal(token)}{access});"


@contextmanager
def client_connection(connect, uri: str, read_only: bool = False):
    """Connect to the running Quack server."""
    with connect() as con:
        con.execute("LOAD quack")
        con.execute(attach_sql(uri, get_token(), read_only))
        con.execute("USE adsb.main")
        yield con


class DuckDBConnection:
    def __init__(self, database: str | Path, *, read_only: bool, quack_uri: str | None):
        try:
            import duckdb
        except ImportError as error:
            raise ValueError("Install DuckDB with: uv sync --extra stand-editing") from error

        self._path = Path(database).resolve(strict=True)
        self.read_only = read_only
        self._quack_uri = quack_uri
        self._connect = duckdb.connect
        self.database_error = duckdb.Error

    @contextmanager
    def connection(self):
        if self._quack_uri:
            with client_connection(self._connect, self._quack_uri, self.read_only) as connection:
                yield connection
            return
        with self._connect(str(self._path), read_only=self.read_only) as connection:
            yield connection

    def bind(self, connection, *values):
        """Return SQL placeholders and parameters for this connection."""
        if not self._quack_uri:
            return ("?",) * len(values), values

        # Quack pushdown can lose prepared parameters. DuckDB binds these values
        # locally and resolves getvariable() to a constant before pushdown.
        placeholders = []
        for index, value in enumerate(values):
            name = f"flight_query_parameter_{index}"
            connection.execute(f"SET VARIABLE {name} = ?", [value])
            placeholders.append(f"getvariable('{name}')")
        return tuple(placeholders), ()
