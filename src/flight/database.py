"""Compatibility imports for the flight repository."""

from .flight_repository import (
    BEIJING,
    STAND_COLUMNS,
    FlightDatabase,
    database_flight_key,
    open_flight_database,
)

__all__ = [
    "BEIJING",
    "STAND_COLUMNS",
    "FlightDatabase",
    "database_flight_key",
    "open_flight_database",
]
