"""ADS-B input loading and movement context."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from adsb import Flights


class MovementType(str, Enum):
    """Operational context attached to loaded ADS-B observations."""

    ARRIVAL = "arrival"
    DEPARTURE = "departure"
    UNKNOWN = "unknown"


def load_data(
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
    frame = pd.read_csv(path)
    if "timestamp" not in frame:
        raise ValueError(f"ADS-B input is missing timestamp column: {path}")
    try:
        normalized = []
        for value in frame["timestamp"]:
            timestamp = pd.Timestamp(value)
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize(timezone)
            normalized.append(timestamp.tz_convert("UTC"))
        frame["timestamp"] = pd.to_datetime(normalized, utc=True)
    except (TypeError, ValueError) as error:
        raise ValueError(f"ADS-B input contains invalid timestamps: {path}") from error
    frame["movement_type"] = movement_type.value
    return Flights(frame)
