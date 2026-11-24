"""Build minimal DuckDB databases for workbench tests."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

from flight import Flight
from flight.flight_repository import FlightDatabase


def create_flight_database(
    path: str | Path,
    flights: Sequence[Flight],
    movement_types: Sequence[str] | None = None,
) -> FlightDatabase:
    import duckdb

    destination = Path(path)
    if destination.exists():
        raise FileExistsError(destination)
    movements = list(movement_types or ())
    rows_by_movement: dict[str, list[dict]] = {"arrival": [], "departure": []}
    for index, flight in enumerate(flights):
        movement = movements[index] if index < len(movements) else "departure"
        if movement not in rows_by_movement:
            raise ValueError(f"Unsupported fixture movement: {movement}")
        rows_by_movement[movement].extend(dict(row) for row in flight.rows)

    required = {
        "flight_id": pd.Series(dtype="string"),
        "number": pd.Series(dtype="string"),
        "timestamp": pd.Series(dtype="datetime64[ns]"),
        "longitude": pd.Series(dtype="float64"),
        "latitude": pd.Series(dtype="float64"),
    }
    with duckdb.connect(str(destination)) as connection:
        for movement, suffix, stand, runway in (
            ("arrival", "arr", "arr_stand_position", "dst_runway"),
            ("departure", "dep", "dep_stand_position", "org_runway"),
        ):
            frame = pd.DataFrame(rows_by_movement[movement])
            existing_columns = {str(col).casefold() for col in frame.columns}
            for name, empty in required.items():
                if name.casefold() not in existing_columns:
                    frame[name] = empty
            for name in (stand, runway):
                if name.casefold() not in existing_columns:
                    frame[name] = pd.Series(dtype="string")
            connection.register("fixture_rows", frame)
            connection.execute(
                f"CREATE TABLE adsb_{suffix} AS SELECT * FROM fixture_rows"
            )
            connection.unregister("fixture_rows")
    return FlightDatabase(destination)
