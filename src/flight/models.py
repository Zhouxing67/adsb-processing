"""Validated ADS-B trajectories built from observation records."""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from itertools import islice
from typing import Any

from utils.json_value import to_json_value

REQUIRED_FLIGHT_COLUMNS = frozenset({"flight_id", "timestamp", "longitude", "latitude"})


def _records(source: Iterable[Mapping[str, Any]], owner: str) -> list[dict[str, Any]]:
    # Accept existing DataFrame callers at the input boundary.
    if hasattr(source, "to_dict") and hasattr(source, "columns"):
        missing = REQUIRED_FLIGHT_COLUMNS.difference(source.columns)
        if missing:
            raise ValueError(f"{owner} is missing required columns: {sorted(missing)}")
        source = source.to_dict(orient="records")
    rows = []
    for record in source:
        missing = REQUIRED_FLIGHT_COLUMNS.difference(record)
        if missing:
            raise ValueError(f"{owner} is missing required columns: {sorted(missing)}")
        identifier = to_json_value(record["flight_id"])
        if identifier is None or not str(identifier).strip():
            raise ValueError(f"{owner} contains an empty flight_id")
        rows.append({**record, "flight_id": str(identifier).strip()})
    return rows


def utc_timestamp(value: Any, input_zone: tzinfo = timezone.utc) -> datetime:
    if to_json_value(value) is None:
        raise ValueError("Empty timestamp")
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip())
    if stamp.tzinfo is None:
        localized = stamp.replace(tzinfo=input_zone)
        if localized.utcoffset() != localized.replace(fold=1).utcoffset():
            raise ValueError(f"Ambiguous or nonexistent local timestamp: {stamp}")
        stamp = localized
    return stamp.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True, init=False)
class Flight:
    """One validated trajectory with UTC observations in stable time order."""

    rows: tuple[dict[str, Any], ...]
    flight_id: str

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        records = _records(rows, "Flight")
        if not records:
            raise ValueError("Flight must contain at least one observation")
        identifiers = {record["flight_id"] for record in records}
        if len(identifiers) != 1:
            raise ValueError("Flight must contain exactly one flight_id")
        for record in records:
            try:
                record["timestamp"] = utc_timestamp(record["timestamp"])
                longitude = float(record["longitude"])
                latitude = float(record["latitude"])
            except (TypeError, ValueError) as error:
                raise ValueError("Flight contains invalid timestamp or coordinates") from error
            if not math.isfinite(longitude) or not math.isfinite(latitude):
                raise ValueError("Flight coordinates must be finite")
            if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                raise ValueError("Flight coordinates outside longitude or latitude bounds")
            record["longitude"] = longitude
            record["latitude"] = latitude
        records.sort(key=lambda row: row["timestamp"])
        object.__setattr__(self, "rows", tuple(records))
        object.__setattr__(self, "flight_id", identifiers.pop())

    @property
    def point_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True, init=False)
class Flights:
    """Observation records that can be grouped into validated trajectories."""

    rows: tuple[dict[str, Any], ...]

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        object.__setattr__(self, "rows", tuple(_records(rows, "Flights")))

    def iterate(self, limit: int | None = None) -> Iterator[Flight]:
        grouped = {}
        for row in self.rows:
            grouped.setdefault(row["flight_id"], []).append(row)
        for identifier in islice(sorted(grouped), limit):
            yield Flight(grouped[identifier])

    def __iter__(self) -> Iterator[Flight]:
        return self.iterate()
