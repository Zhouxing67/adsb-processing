"""Serve the configured DuckDB file and write the DataGrip session script."""

from threading import Event

import duckdb

from config import load_settings

from .duckdb_connection import STATE_DIR, attach_sql, get_token, sql_literal

INIT_SQL = STATE_DIR / "quack-datagrip.sql"


def main() -> None:
    settings = load_settings().database
    uri = settings.quack_uri or "quack:127.0.0.1:9494"

    if uri != "quack:127.0.0.1:9494":
        raise ValueError("Only local Quack connections are allowed")

    token = get_token()

    with duckdb.connect(str(settings.path)) as con:
        con.execute("INSTALL quack")
        con.execute("LOAD quack")
        con.execute(f"CALL quack_serve({sql_literal(uri)}, token := {sql_literal(token)})")

        INIT_SQL.write_text(
            "/* DUCKDB_CONNECTION_INIT_BELOW_MARKER */\n"
            "LOAD quack;\n"
            f"{attach_sql(uri, token)}\n"
            "USE adsb.main;\n",
            encoding="utf-8",
        )

        print(f"Quack listening at {uri}", flush=True)
        Event().wait()


if __name__ == "__main__":
    main()
