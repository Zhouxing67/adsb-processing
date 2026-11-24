"""Composed flight persistence repositories."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from route_library.repository import RouteLibraryRepository

from .duckdb_connection import DuckDBConnection
from .flight_catalogue_repository import STAND_COLUMNS, FlightCatalogueRepository
from .flight_observation_repository import FlightObservationRepository

if TYPE_CHECKING:
    from config import DatabaseSettings


def database_flight_key(movement: str, flight_id: str) -> str:
    seed = f"duckdb\0{movement}\0{flight_id}".encode()
    return f"f-{hashlib.sha256(seed).hexdigest()[:16]}"


def flight_source_name(movement: str) -> str:
    return f"main.{STAND_COLUMNS[movement][0]}"


class StandRepository:
    def __init__(self, database: DuckDBConnection) -> None:
        self._database = database

    def historical_candidates(
        self, movement: str, flight_id: str, number: str, event: datetime, aircraft: str | None
    ) -> list[tuple[str, int, int]]:
        """Count prior flights and exclude stands with a known overlapping turnaround."""
        with self._database.connection() as connection:
            # Quack supports one remote streaming scan per statement. Reduce each
            # movement table separately, then join the two small per-aircraft results.
            sources = {}
            for direction, (table, stand) in STAND_COLUMNS.items():
                time = "actual_dep" if direction == "departure" else "actual_arr"
                columns = {
                    row[0].lower(): row[1]
                    for row in connection.execute(f"DESCRIBE main.{table}").fetchall()
                }
                if time not in columns:
                    continue
                instant = time if "WITH TIME ZONE" in columns[time] else (
                    f"timezone('Asia/Shanghai', {time}::TIMESTAMP)"
                )
                reg = "nullif(upper(trim(a_num)), '')" if "a_num" in columns else "NULL::VARCHAR"
                sources[direction] = f"""
                    SELECT flight_id, min({instant}) AS instant,
                        CASE WHEN count(DISTINCT nullif(trim(number), '')) = 1
                             THEN min(nullif(trim(number), '')) END AS number,
                        CASE WHEN count(DISTINCT nullif(trim({stand}), '')) = 1
                             THEN min(nullif(trim({stand}), '')) END AS stand,
                        CASE WHEN count(DISTINCT {reg}) = 1 THEN min({reg}) END AS aircraft
                    FROM main.{table} WHERE flight_id IS NOT NULL
                    GROUP BY flight_id HAVING count(DISTINCT {time}) = 1
                """
            if movement not in sources:
                return []
            (moment, key, num), params = self._database.bind(connection, event, flight_id, number)
            history = connection.execute(f"""
                WITH events AS ({sources[movement]}), target AS (SELECT {moment}::TIMESTAMPTZ AS t)
                SELECT stand, count(*) AS uses, max(instant) AS latest
                FROM events, target
                WHERE flight_id <> {key} AND number = {num} AND stand IS NOT NULL
                  AND instant >= t - INTERVAL '90 days' AND instant < t
                GROUP BY stand ORDER BY uses DESC, latest DESC, stand
            """, params).fetchall()
            if not history:
                return []

            before = {}
            after = {}
            (moment,), params = self._database.bind(connection, event)
            for direction, source in sources.items():
                rows = connection.execute(f"""
                    WITH events AS ({source}), target AS (SELECT {moment}::TIMESTAMPTZ AS t)
                    SELECT aircraft,
                        arg_max(struct_pack(ts := instant, stand := stand), instant)
                            FILTER (WHERE instant <= t),
                        arg_min(struct_pack(ts := instant, stand := stand), instant)
                            FILTER (WHERE instant > t)
                    FROM events, target WHERE aircraft IS NOT NULL GROUP BY aircraft
                """, params)
                for tail, previous, following in rows:
                    if aircraft and tail == aircraft.upper():
                        continue
                    if previous and (tail not in before or previous["ts"] > before[tail][0]):
                        before[tail] = (previous["ts"], direction, previous["stand"])
                    if following and (tail not in after or following["ts"] < after[tail][0]):
                        after[tail] = (following["ts"], direction, following["stand"])

            occupied = {
                stand for tail, (_, direction, stand) in before.items()
                if direction == "arrival" and tail in after
                and after[tail][1:] == ("departure", stand)
            }
            total = sum(uses for _, uses, _ in history)
            return [(stand, uses, total) for stand, uses, _ in history if stand not in occupied]

    def update(self, movement: str, flight_id: str, stand: str | None) -> None:
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
        except self._database.database_error as error:
            raise RuntimeError("机位更新事务失败") from error


class FlightDatabase:
    """Own one DuckDB connection factory and its focused repositories."""

    def __init__(
        self,
        database: str | Path,
        *,
        read_only: bool = False,
        quack_uri: str | None = None,
    ) -> None:
        self._database = DuckDBConnection(database, read_only=read_only, quack_uri=quack_uri)
        self.catalogue = FlightCatalogueRepository(self._database)
        self.observations = FlightObservationRepository(self._database)
        self.stands = StandRepository(self._database)
        self.routes = RouteLibraryRepository(self._database)

    @property
    def read_only(self) -> bool:
        return self._database.read_only

    @property
    def database_error(self) -> type[Exception]:
        return self._database.database_error


def open_flight_database(settings: DatabaseSettings, *, read_only: bool = False) -> FlightDatabase:
    return FlightDatabase(settings.path, read_only=read_only, quack_uri=settings.quack_uri)
