"""Shared DuckDB connection and schema helpers."""

from .connection import (
    CORE_SCHEMA_SQL,
    STATE_DIR,
    TOKEN_FILE,
    DuckDBConnection,
    DuckDBSession,
    apply_core_schema,
    attach_sql,
    get_token,
    sql_literal,
    sql_value,
)

__all__ = [
    "CORE_SCHEMA_SQL",
    "DuckDBConnection",
    "DuckDBSession",
    "STATE_DIR",
    "TOKEN_FILE",
    "apply_core_schema",
    "attach_sql",
    "get_token",
    "sql_literal",
    "sql_value",
]
