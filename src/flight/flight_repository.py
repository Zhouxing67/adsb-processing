"""Lazy ADS-B observation and catalogue queries against DuckDB."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator
from zoneinfo import ZoneInfo

from .duckdb_connection import DuckDBConnection
from .models import Flight, FlightSummary, utc_timestamp

if TYPE_CHECKING:
    from config import DatabaseSettings

STAND_COLUMNS = {
    "departure": ("adsb_202406_dep", "dep_stand_position"),
    "arrival": ("adsb_202406_arr", "arr_stand_position"),
}
BEIJING = "Asia/Shanghai"


def database_flight_key(movement: str, flight_id: str) -> str:
    seed = f"duckdb\0{movement}\0{flight_id}".encode()
    return f"f-{hashlib.sha256(seed).hexdigest()[:16]}"


def _utc(value: datetime) -> datetime:
    return utc_timestamp(value, ZoneInfo(BEIJING))


class FlightDatabase:
    """Fetch flight data on demand and persist stand edits transactionally."""

    def __init__(
        self, database: str | Path, *, read_only: bool = False, quack_uri: str | None = None,
    ) -> None:
        self._database = DuckDBConnection(database, read_only=read_only, quack_uri=quack_uri)

    @property
    def read_only(self) -> bool:
        return self._database.read_only

    @property
    def database_error(self) -> type[Exception]:
        return self._database.database_error

    def connection(self):
        return self._database.connection()

    @staticmethod
    def source_name(movement: str) -> str:
        return f"main.{STAND_COLUMNS[movement][0]}"

    def update_stand(self, movement: str, flight_id: str, stand: str | None) -> None:
        table, column = STAND_COLUMNS[movement]
        try:
            with self._database.connection(write=True) as connection:
                (stand_value, identifier), parameters = self._database.bind(
                    connection, stand, flight_id
                )
                count = connection.execute(
                    f"UPDATE main.{table} SET {column} = {stand_value} "
                    f"WHERE flight_id = {identifier}",
                    parameters,
                ).fetchone()
                if not count or not count[0]:
                    raise ValueError("数据库中没有该航班的观测记录")
        except self.database_error as error:
            raise RuntimeError("机位更新事务失败") from error

    update = update_stand

    def summaries(
        self,
        *,
        movement: str | None = None,
        query: str = "",
        min_points: int = 0,
        max_points: int | None = None,
        stands: tuple[str, ...] = (),
        start_date: date | None = None,
        end_date: date | None = None,
        display_timezone: str = BEIJING,
    ) -> Iterator[FlightSummary]:
        with self.connection() as connection:
            for direction, (table, column) in STAND_COLUMNS.items():
                if movement and movement != direction:
                    continue
                rows = connection.execute(
                    f"""
                    WITH flights AS (
                        SELECT flight_id, MIN("NUMBER") AS number,
                               COUNT(DISTINCT "NUMBER") AS number_count,
                               MIN(timestamp) AS started, MAX(timestamp) AS ended,
                               COUNT(*) AS points,
                               MIN(NULLIF(TRIM({column}), '')) AS stand,
                               COUNT(DISTINCT NULLIF(TRIM({column}), '')) AS stand_count
                        FROM main.{table}
                        WHERE flight_id IS NOT NULL AND trim(flight_id) <> ''
                        GROUP BY flight_id
                    )
                    SELECT * FROM flights
                    WHERE points >= $minimum AND ($maximum IS NULL OR points <= $maximum)
                      AND ($query = '' OR contains(lower(flight_id), $query)
                           OR (number_count = 1 AND contains(lower(number), $query)))
                      AND ($all_stands OR (stand_count <= 1
                           AND coalesce(stand, '') = ANY($stands::VARCHAR[])))
                      AND ($start_date IS NULL OR
                           CAST(timezone($zone, timezone($input_zone, started)) AS DATE)
                           >= $start_date)
                      AND ($end_date IS NULL OR
                           CAST(timezone($zone, timezone($input_zone, started)) AS DATE)
                           <= $end_date)
                    ORDER BY flight_id
                    """,
                    {
                        "minimum": min_points, "maximum": max_points, "query": query.lower(),
                        "all_stands": not stands, "stands": list(stands),
                        "start_date": start_date, "end_date": end_date,
                        "zone": display_timezone, "input_zone": BEIJING,
                    },
                ).fetchall()
                for identifier, number, numbers, start, end, points, stand, count in rows:
                    if start is None or end is None:
                        continue
                    yield FlightSummary(
                        movement=direction,
                        flight_id=identifier,
                        flight_number=str(number) if numbers == 1 else None,
                        number_count=numbers,
                        start_time=_utc(start),
                        end_time=_utc(end),
                        point_count=points,
                        stand_position=stand if count <= 1 else None,
                        stand_count=count,
                    )

    @staticmethod
    def _records(cursor) -> Iterator[dict[str, Any]]:
        columns = list(cursor.keys())
        while batch := cursor.fetchmany(2048):
            for values in batch:
                row = dict(zip(columns, values))
                if row["timestamp"] is not None:
                    row["timestamp"] = _utc(row["timestamp"])
                yield row

    def flight(self, movement: str, identifier: str) -> Flight:
        table, _ = STAND_COLUMNS[movement]
        with self.connection() as connection:
            (flight_id,), parameters = self._database.bind(connection, identifier)
            cursor = connection.execute(
                f"SELECT * FROM main.{table} WHERE flight_id = {flight_id} "
                "ORDER BY timestamp, rowid",
                parameters,
            )
            return Flight(self._records(cursor))

    def detail(
        self, movement: str, identifier: str, offset: int, limit: int,
        business_fields: set[str],
    ) -> tuple[list[str], dict[str, Any], dict[str, list[Any]], list[dict[str, Any]], int]:
        table, _ = STAND_COLUMNS[movement]
        with self.connection() as connection:
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
            return columns, fields, inconsistent, list(self._records(records)), total

    def iterate(self, movement: str, limit: int | None) -> Iterator[Flight]:
        table, _ = STAND_COLUMNS[movement]
        with self.connection() as connection:
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
            records = groupby(self._records(cursor), key=lambda row: row["flight_id"])
            for _, rows in records:
                yield Flight(rows)


def open_flight_database(settings: DatabaseSettings, *, read_only: bool = False) -> FlightDatabase:
    return FlightDatabase(settings.path, read_only=read_only, quack_uri=settings.quack_uri)
