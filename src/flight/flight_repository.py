"""Composed flight persistence repositories (PostgreSQL)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Protocol

from db import PostgresConnection

from .flight_catalogue_repository import FlightCatalogueRepository
from .flight_observation_repository import FlightObservationRepository
from .match_issue_repository import MatchIssueRepository

TURNAROUND_WINDOW_DAYS = 7


class DatabaseConfig(Protocol):
    dsn: str


def database_flight_key(movement: str, flight_id: str) -> str:
    # Retain historical 'duckdb' seed prefix to preserve deterministic flight_key stability.
    seed = f"duckdb\0{movement}\0{flight_id}".encode()
    return f"f-{hashlib.sha256(seed).hexdigest()[:16]}"


def flight_source_name(movement: str) -> str:
    return f"public.flights:{movement}"


class StandRepository:
    def __init__(self, database: PostgresConnection) -> None:
        self._database = database

    def historical_candidates(
        self, movement: str, flight_id: str, number: str, event: datetime, aircraft: str | None
    ) -> list[tuple[str, int, int]]:
        """Count prior flights and exclude stands with a known overlapping turnaround."""
        event_utc = (
            event.astimezone(timezone.utc)
            if event.tzinfo
            else event.replace(tzinfo=timezone.utc)
        )
        time_col = "actual_dep" if movement == "departure" else "actual_arr"
        with self._database.connection() as connection:
            history = connection.execute(
                f"""
                SELECT stand, COUNT(*) AS uses, MAX(instant) AS latest
                FROM (
                    SELECT
                        CASE WHEN stand_is_overridden
                             THEN stand_override
                             ELSE raw_stand_position
                        END AS stand,
                        {time_col} AS instant
                    FROM public.flights
                    WHERE movement = :movement
                      AND number = :number
                      AND flight_id <> :flight_id
                      AND {time_col} >= :event - INTERVAL '90 days'
                      AND {time_col} < :event
                ) events
                WHERE stand IS NOT NULL
                GROUP BY stand
                ORDER BY uses DESC, latest DESC, stand
                """,
                {
                    "movement": movement,
                    "flight_id": flight_id,
                    "number": number,
                    "event": event_utc,
                },
            ).fetchall()
            if not history:
                return []

            # Restrict turnaround occupancy scan to +-TURNAROUND_WINDOW_DAYS using
            # actual_dep / actual_arr indexes rather than full-table scanning public.flights.
            before_rows = connection.execute(
                f"""
                WITH windowed AS (
                    SELECT
                        upper(trim(a_num)) AS aircraft,
                        'departure' AS movement,
                        CASE WHEN stand_is_overridden
                             THEN stand_override
                             ELSE raw_stand_position
                        END AS stand,
                        actual_dep AS instant
                    FROM public.flights
                    WHERE movement = 'departure'
                      AND a_num IS NOT NULL AND trim(a_num) <> ''
                      AND actual_dep >= :event - INTERVAL '{TURNAROUND_WINDOW_DAYS} days'
                      AND actual_dep <= :event
                    UNION ALL
                    SELECT
                        upper(trim(a_num)) AS aircraft,
                        'arrival' AS movement,
                        CASE WHEN stand_is_overridden
                             THEN stand_override
                             ELSE raw_stand_position
                        END AS stand,
                        actual_arr AS instant
                    FROM public.flights
                    WHERE movement = 'arrival'
                      AND a_num IS NOT NULL AND trim(a_num) <> ''
                      AND actual_arr >= :event - INTERVAL '{TURNAROUND_WINDOW_DAYS} days'
                      AND actual_arr <= :event
                )
                SELECT DISTINCT ON (aircraft) aircraft, movement, stand
                FROM windowed
                ORDER BY aircraft, instant DESC
                """,
                {"event": event_utc},
            ).fetchall()

            after_rows = connection.execute(
                f"""
                WITH windowed AS (
                    SELECT
                        upper(trim(a_num)) AS aircraft,
                        'departure' AS movement,
                        CASE WHEN stand_is_overridden
                             THEN stand_override
                             ELSE raw_stand_position
                        END AS stand,
                        actual_dep AS instant
                    FROM public.flights
                    WHERE movement = 'departure'
                      AND a_num IS NOT NULL AND trim(a_num) <> ''
                      AND actual_dep > :event
                      AND actual_dep <= :event + INTERVAL '{TURNAROUND_WINDOW_DAYS} days'
                    UNION ALL
                    SELECT
                        upper(trim(a_num)) AS aircraft,
                        'arrival' AS movement,
                        CASE WHEN stand_is_overridden
                             THEN stand_override
                             ELSE raw_stand_position
                        END AS stand,
                        actual_arr AS instant
                    FROM public.flights
                    WHERE movement = 'arrival'
                      AND a_num IS NOT NULL AND trim(a_num) <> ''
                      AND actual_arr > :event
                      AND actual_arr <= :event + INTERVAL '{TURNAROUND_WINDOW_DAYS} days'
                )
                SELECT DISTINCT ON (aircraft) aircraft, movement, stand
                FROM windowed
                ORDER BY aircraft, instant ASC
                """,
                {"event": event_utc},
            ).fetchall()

            target_aircraft = aircraft.upper() if aircraft else None
            before = {
                tail: (direction, stand)
                for tail, direction, stand in before_rows
                if not target_aircraft or tail != target_aircraft
            }
            after = {
                tail: (direction, stand)
                for tail, direction, stand in after_rows
                if not target_aircraft or tail != target_aircraft
            }

            occupied = {
                stand
                for tail, (direction, stand) in before.items()
                if direction == "arrival"
                and stand is not None
                and tail in after
                and after[tail] == ("departure", stand)
            }
            total = sum(int(uses) for _, uses, _ in history)
            return [
                (str(stand), int(uses), total)
                for stand, uses, _ in history
                if stand not in occupied
            ]

    def update(self, movement: str, flight_id: str, stand: str | None) -> None:
        try:
            with self._database.connection(write=True) as connection:
                row = connection.execute(
                    """
                    UPDATE public.flights
                    SET stand_override = :stand,
                        stand_is_overridden = TRUE,
                        stand_updated_at = now(),
                        updated_at = now()
                    WHERE movement = :movement AND flight_id = :flight_id
                    RETURNING flight_pk
                    """,
                    {"stand": stand, "movement": movement, "flight_id": flight_id},
                ).fetchone()
                if row is None:
                    raise ValueError("数据库中没有该航班的观测记录")
        except self._database.database_error as error:
            raise RuntimeError("机位更新事务失败") from error


class FlightDatabase:
    """Own one PostgreSQL connection pool and its focused repositories."""

    def __init__(self, dsn: str, *, read_only: bool = False) -> None:
        self._database = PostgresConnection(dsn, read_only=read_only)
        self.catalogue = FlightCatalogueRepository(self._database)
        self.observations = FlightObservationRepository(self._database)
        self.stands = StandRepository(self._database)
        self.issues = MatchIssueRepository(self._database)

    @property
    def postgres(self) -> PostgresConnection:
        return self._database

    def connection(self, *, write: bool = False):
        return self._database.connection(write=write)

    def close(self) -> None:
        self._database.close()

    @property
    def read_only(self) -> bool:
        return self._database.read_only

    @property
    def database_error(self) -> type[Exception]:
        return self._database.database_error


def open_flight_database(settings: DatabaseConfig, *, read_only: bool = False) -> FlightDatabase:
    return FlightDatabase(settings.dsn, read_only=read_only)
