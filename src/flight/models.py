"""Validated ADS-B trajectories built from observation records."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from types import MappingProxyType
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
class FlightObservation:
    """A trajectory point with its original observation attributes."""

    flight_id: str
    timestamp: datetime
    longitude: float
    latitude: float
    metadata: Mapping[str, Any]

    def __init__(self, record: Mapping[str, Any]) -> None:
        try:
            timestamp = utc_timestamp(record["timestamp"])
            longitude = float(record["longitude"])
            latitude = float(record["latitude"])
        except (TypeError, ValueError) as error:
            raise ValueError("Flight contains invalid timestamp or coordinates") from error
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            raise ValueError("Flight coordinates must be finite")
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("Flight coordinates outside longitude or latitude bounds")
        object.__setattr__(self, "flight_id", record["flight_id"])
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "longitude", longitude)
        object.__setattr__(self, "latitude", latitude)
        object.__setattr__(self, "metadata", MappingProxyType({
            name: value for name, value in record.items() if name not in REQUIRED_FLIGHT_COLUMNS
        }))

    @property
    def altitude(self) -> float | None:
        value = to_json_value(self.metadata.get("altitude"))
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def groundspeed(self) -> float | None:
        value = to_json_value(self.metadata.get("groundspeed"))
        return float(value) if isinstance(value, (int, float)) else None

    def to_record(self) -> dict[str, Any]:
        return {
            "flight_id": self.flight_id,
            "timestamp": self.timestamp,
            "longitude": self.longitude,
            "latitude": self.latitude,
            **self.metadata,
        }


@dataclass(frozen=True, slots=True, init=False)
class Flight:
    """One validated trajectory with UTC observations in stable time order."""

    observations: tuple[FlightObservation, ...]
    flight_id: str

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        records = _records(rows, "Flight")
        if not records:
            raise ValueError("Flight must contain at least one observation")
        identifiers = {record["flight_id"] for record in records}
        if len(identifiers) != 1:
            raise ValueError("Flight must contain exactly one flight_id")
        observations = sorted(map(FlightObservation, records), key=lambda point: point.timestamp)
        object.__setattr__(self, "observations", tuple(observations))
        object.__setattr__(self, "flight_id", identifiers.pop())

    @property
    def rows(self) -> tuple[dict[str, Any], ...]:
        """Return record snapshots for callers that consume raw fields."""
        return tuple(point.to_record() for point in self.observations)

    @property
    def point_count(self) -> int:
        return len(self.observations)


@dataclass(frozen=True, slots=True)
class FlightSummary:
    movement: str
    flight_id: str
    flight_number: str | None
    number_count: int
    start_time: datetime
    end_time: datetime
    point_count: int
    stand_position: str | None
    stand_count: int
