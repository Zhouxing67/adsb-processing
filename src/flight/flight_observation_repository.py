"""Flight observation loading and detail queries."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from itertools import groupby
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from db import DuckDBConnection

from .flight_catalogue_repository import BEIJING, STAND_COLUMNS
from .models import Flight, utc_timestamp


def _utc(value: datetime) -> datetime:
    return utc_timestamp(value, ZoneInfo(BEIJING))


class FlightObservationRepository:
    def __init__(self, database: DuckDBConnection) -> None:
        self._database = database

    def flight(self, movement: str, identifier: str) -> Flight:
        table, _ = STAND_COLUMNS[movement]
        with self._database.connection() as connection:
            (flight_id,), parameters = self._database.bind(connection, identifier)
            cursor = connection.execute(
                f"SELECT * FROM main.{table} WHERE flight_id = {flight_id} "
                "ORDER BY timestamp, rowid",
                parameters,
            )
            return Flight(cursor.mappings(), movement=movement, input_zone=ZoneInfo(BEIJING))

    def flights_batch(self, movement: str, identifiers: Sequence[str]) -> dict[str, Flight]:
        """Load multiple flights for one movement in a single query/connection."""
        unique_ids = list(dict.fromkeys(identifiers))
        if not unique_ids:
            return {}
        table, _ = STAND_COLUMNS[movement]
        with self._database.connection() as connection:
            (id_list,), parameters = self._database.bind(connection, unique_ids)
            cursor = connection.execute(
                f"SELECT * FROM main.{table} "
                f"WHERE flight_id = ANY({id_list}::VARCHAR[]) "
                "ORDER BY flight_id, timestamp, rowid",
                parameters,
            )
            input_zone = ZoneInfo(BEIJING)
            result: dict[str, Flight] = {}
            for fid, rows in groupby(cursor.mappings(), key=lambda row: row["flight_id"]):
                result[str(fid)] = Flight(rows, movement=movement, input_zone=input_zone)
            return result

    def detail(
        self,
        movement: str,
        identifier: str,
        offset: int,
        limit: int,
        business_fields: set[str],
    ) -> tuple[list[str], dict[str, Any], dict[str, list[Any]], list[dict[str, Any]], int]:
        table, _ = STAND_COLUMNS[movement]
        with self._database.connection() as connection:
            (flight_id, page_limit, page_offset), parameters = self._database.bind(
                connection, identifier, limit, offset
            )
            source = f"FROM main.{table} WHERE flight_id = {flight_id}"
            description = connection.execute(f"SELECT * {source} LIMIT 0", parameters[:1])
            columns = list(description.keys())
            aggregates = ["COUNT(*)"]
            for column in columns:
                quoted = '"' + column.replace('"', '""') + '"'
                if column.casefold() in business_fields:
                    aggregates.append(
                        f"list(DISTINCT {quoted} ORDER BY {quoted}) "
                        f"FILTER (WHERE {quoted} IS NOT NULL)"
                    )
                else:
                    aggregates.append(
                        f"CASE WHEN MIN({quoted}) = MAX({quoted}) THEN MIN({quoted}) END"
                    )
            result = connection.execute(f"SELECT {', '.join(aggregates)} {source}", parameters[:1])
            total, *values = result.fetchone()
            fields = dict(zip(columns, values))
            inconsistent = {}
            for column in columns:
                if column.casefold() in business_fields:
                    distinct = fields[column] or []
                    if len(distinct) > 1:
                        inconsistent[column] = distinct
                    fields[column] = distinct[0] if len(distinct) == 1 else None
            if fields["timestamp"] is not None:
                fields["timestamp"] = _utc(fields["timestamp"])
            records = connection.execute(
                f"SELECT * {source} ORDER BY timestamp, rowid "
                f"LIMIT {page_limit} OFFSET {page_offset}",
                parameters,
            )
            observations = [
                {
                    **row,
                    "timestamp": _utc(row["timestamp"]) if row["timestamp"] is not None else None,
                }
                for row in records.mappings()
            ]
            return columns, fields, inconsistent, observations, total

    def iterate(self, movement: str, limit: int | None) -> Iterator[Flight]:
        table, _ = STAND_COLUMNS[movement]
        with self._database.connection() as connection:
            (flight_limit,), parameters = self._database.bind(connection, limit)
            cursor = connection.execute(
                f"""
                SELECT source.* FROM main.{table} AS source
                WHERE flight_id IN (
                    SELECT DISTINCT flight_id FROM main.{table}
                    WHERE flight_id IS NOT NULL AND trim(flight_id) <> ''
                    ORDER BY flight_id LIMIT coalesce({flight_limit}, 9223372036854775807)
                )
                ORDER BY flight_id, timestamp, source.rowid
                """,
                parameters,
            )
            records = groupby(cursor.mappings(), key=lambda row: row["flight_id"])
            input_zone = ZoneInfo(BEIJING)
            for _, rows in records:
                yield Flight(rows, movement=movement, input_zone=input_zone)
