"""ADS-B input loading and movement context."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

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
) -> Flights:
    """Load ADS-B observations and attach their movement context."""
    path = Path(file)
    if not path.exists():
        raise FileNotFoundError(f"ADS-B input does not exist: {path}")

    movement_type = MovementType(movement_type)
    frame = pd.read_csv(path)
    frame["movement_type"] = movement_type.value
    return Flights(frame)
