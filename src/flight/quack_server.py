"""Serve the configured DuckDB file and write the DataGrip session script."""

import time
import tomllib
from pathlib import Path

import duckdb

from db import STATE_DIR, attach_sql, get_token, sql_literal

INIT_SQL = STATE_DIR / "quack-datagrip.sql"
CONFIG_FILE = Path("config.local.toml")


def _load_database_config() -> tuple[Path, str]:
    if not CONFIG_FILE.is_file():
        raise ValueError(
            "Missing config.local.toml. Copy config.example.toml and set [database].path."
        )
    data = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    db_section = data.get("database") or {}
    raw_path = db_section.get("path")
    if not raw_path:
        raise ValueError("Missing [database].path in config.local.toml")
    uri = db_section.get("quack_uri") or "quack:127.0.0.1:9494"
    return Path(raw_path), str(uri)


def main() -> None:
    db_path, uri = _load_database_config()

    if uri != "quack:127.0.0.1:9494":
        raise ValueError("Only local Quack connections are allowed")

    token = get_token()

    with duckdb.connect(str(db_path)) as con:
        con.execute("INSTALL quack")
        con.execute("LOAD quack")
        con.execute("INSTALL spatial")
        con.execute("LOAD spatial")

        con.execute(f"CALL quack_serve({sql_literal(uri)}, token := {sql_literal(token)})")

        INIT_SQL.write_text(
            "/* DUCKDB_CONNECTION_INIT_BELOW_MARKER */\n"
            "LOAD quack;\n"
            f"{attach_sql(uri, token)}\n"
            "USE adsb.main;\n"
            "LOAD spatial;\n",
            encoding="utf-8",
        )

        print(f"Quack listening at {uri}", flush=True)
        print("Press Ctrl+C to stop.")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping Quack Server...")

if __name__ == "__main__":
    main()
