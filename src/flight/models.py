"""Validated ADS-B trajectories built from observation records."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
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


@dataclass(slots=True)
class FlightObservation:
    """A trajectory point with its original observation attributes."""

    flight_id: str
    timestamp: datetime
    longitude: float
    latitude: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __init__(self, record: Mapping[str, Any], *, input_zone: tzinfo = timezone.utc) -> None:
        try:
            timestamp = utc_timestamp(record["timestamp"], input_zone)
            longitude = float(record["longitude"])
            latitude = float(record["latitude"])
        except (TypeError, ValueError) as error:
            raise ValueError("Flight contains invalid timestamp or coordinates") from error
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            raise ValueError("Flight coordinates must be finite")
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("Flight coordinates outside longitude or latitude bounds")
        self.flight_id = record["flight_id"]
        self.timestamp = timestamp
        self.longitude = longitude
        self.latitude = latitude
        self.metadata = {
            name: value for name, value in record.items() if name not in REQUIRED_FLIGHT_COLUMNS
        }

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


@dataclass(slots=True)
class Flight:
    """One validated trajectory with UTC observations in stable time order."""

    flight_id: str = field(init=False)
    number: str | None = field(init=False, default=None)
    org_name: str | None = field(init=False, default=None)
    dst_name: str | None = field(init=False, default=None)
    r_type: str | None = field(init=False, default=None)
    a_num: str | None = field(init=False, default=None)

    org_runway: str | None = field(init=False, default=None)
    dst_runway: str | None = field(init=False, default=None)
    dep_stand_position: str | None = field(init=False, default=None)
    arr_stand_position: str | None = field(init=False, default=None)

    sche_dep: datetime | None = field(init=False, default=None)
    sche_arr: datetime | None = field(init=False, default=None)
    actual_dep: datetime | None = field(init=False, default=None)
    actual_arr: datetime | None = field(init=False, default=None)

    observations: tuple[FlightObservation, ...] = field(init=False)

    od_error: str | None = field(init=False, default=None)
    movement: str | None = field(init=False, default=None)

    def __init__(
        self, rows: Iterable[Mapping[str, Any]], *,
        movement: str | None = None, input_zone: tzinfo = timezone.utc,
    ) -> None:
        records = _records(rows, "Flight")
        if not records:
            raise ValueError("Flight must contain at least one observation")
        identifiers = {record["flight_id"] for record in records}
        if len(identifiers) != 1:
            raise ValueError("Flight must contain exactly one flight_id")
        observations = sorted(
            (FlightObservation(record, input_zone=input_zone) for record in records),
            key=lambda point: point.timestamp,
        )
        self.observations = tuple(observations)
        self.flight_id = identifiers.pop()
        self.movement = movement
        text_fields = (
            "number", "org_name", "dst_name", "r_type", "a_num",
            "org_runway", "dst_runway", "dep_stand_position", "arr_stand_position",
        )
        time_fields = ("sche_dep", "sche_arr", "actual_dep", "actual_arr")
        values = {field: set() for field in (*text_fields, *time_fields)}
        for record in records:
            for name, raw in record.items():
                field = name.casefold()
                if field not in values or to_json_value(raw) is None:
                    continue
                if str(raw).strip():
                    value = (
                        utc_timestamp(raw, input_zone)
                        if field in time_fields
                        else str(raw).strip()
                    )
                    values[field].add(value)
        for field, distinct in values.items():
            setattr(self, field, next(iter(distinct)) if len(distinct) == 1 else None)
        od_fields_by_movement: dict[str, tuple[str, ...]] = {
            "departure": ("dep_stand_position", "org_runway"),
            "arrival": ("arr_stand_position", "dst_runway"),
        }
        od_fields = od_fields_by_movement.get(movement, ()) if movement is not None else ()
        conflicts = [field for field in od_fields if len(values[field]) > 1]
        self.od_error = f"Conflicting OD fields: {', '.join(conflicts)}" if conflicts else None

    @property
    def stand_ref(self) -> str | None:
        if self.movement == "departure":
            return self.dep_stand_position
        return self.arr_stand_position if self.movement == "arrival" else None

    @property
    def runway_ref(self) -> str | None:
        if self.movement == "departure":
            return self.org_runway
        return self.dst_runway if self.movement == "arrival" else None

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
