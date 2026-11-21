"""Composed flight persistence repositories."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

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

    @property
    def read_only(self) -> bool:
        return self._database.read_only

    @property
    def database_error(self) -> type[Exception]:
        return self._database.database_error


def open_flight_database(settings: DatabaseSettings, *, read_only: bool = False) -> FlightDatabase:
    return FlightDatabase(settings.path, read_only=read_only, quack_uri=settings.quack_uri)
