"""Read ADS-B CSV samples for standalone diagnostics and tests."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flight import Flights, MovementType
from flight.models import REQUIRED_FLIGHT_COLUMNS, utc_timestamp

IDENTIFIER_COLUMNS = frozenset({"flight_id", "dep_stand_position", "arr_stand_position"})


def load_csv_flights(
    file: str | Path,
    movement_type: MovementType = MovementType.UNKNOWN,
    input_timezone: str = "UTC",
) -> Flights:
    """Load observations, interpreting naive timestamps in ``input_timezone``."""
    path = Path(file)
    if not path.exists():
        raise FileNotFoundError(f"ADS-B input does not exist: {path}")
    try:
        timezone = ZoneInfo(input_timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"Unknown input timezone: {input_timezone}") from error

    movement_type = MovementType(movement_type)
    rows = []
    for row in _read_csv_records(path):
        try:
            row["timestamp"] = utc_timestamp(row["timestamp"], timezone)
        except (TypeError, ValueError) as error:
            raise ValueError(f"ADS-B input contains invalid timestamps: {path}") from error
        row["movement_type"] = movement_type.value
        rows.append(row)
    return Flights(rows)


def _read_csv_records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        missing = REQUIRED_FLIGHT_COLUMNS.difference(columns)
        if missing:
            raise ValueError(f"ADS-B input is missing required columns: {sorted(missing)}")
        rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError(f"ADS-B input contains a row with too many fields: {path}")
    for name in columns:
        present = [row[name] for row in rows if row[name] not in (None, "")]
        numeric = name.lower() not in IDENTIFIER_COLUMNS | {"timestamp"} and present
        converter = str
        if numeric:
            for candidate in (int, float):
                try:
                    for value in present:
                        candidate(value)
                except ValueError:
                    continue
                converter = candidate
                break
        for row in rows:
            row[name] = None if row[name] in (None, "") else converter(row[name])
    yield from rows
