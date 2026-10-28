"""Small, strict data models for ADS-B flight trajectories."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REQUIRED_FLIGHT_COLUMNS = frozenset(
    {"flight_id", "timestamp", "longitude", "latitude"}
)


@dataclass(frozen=True, slots=True)
class Flight:
    """One validated flight trajectory, ordered by observation time."""

    data: pd.DataFrame
    flight_id: str = field(init=False)

    def __post_init__(self) -> None:
        missing = REQUIRED_FLIGHT_COLUMNS.difference(self.data.columns)
        if missing:
            raise ValueError(f"Flight is missing required columns: {sorted(missing)}")
        if self.data.empty:
            raise ValueError("Flight must contain at least one observation")

        frame = self.data.copy()
        identifiers = _flight_ids(frame["flight_id"], owner="Flight")
        if len(identifiers) != 1:
            raise ValueError("Flight must contain exactly one flight_id")

        try:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
            frame["longitude"] = pd.to_numeric(frame["longitude"], errors="raise")
            frame["latitude"] = pd.to_numeric(frame["latitude"], errors="raise")
        except (TypeError, ValueError) as error:
            raise ValueError("Flight contains invalid timestamp or coordinates") from error

        required_values = ["timestamp", "longitude", "latitude"]
        if frame[required_values].isna().any().any():
            raise ValueError("Flight contains empty required values")
        coordinates = frame[["longitude", "latitude"]].to_numpy(dtype=float)
        if not np.isfinite(coordinates).all():
            raise ValueError("Flight coordinates must be finite")
        if not frame["longitude"].between(-180, 180).all():
            raise ValueError("Flight longitude must be between -180 and 180")
        if not frame["latitude"].between(-90, 90).all():
            raise ValueError("Flight latitude must be between -90 and 90")

        frame["flight_id"] = identifiers[0]
        frame = frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
        object.__setattr__(self, "data", frame)
        object.__setattr__(self, "flight_id", identifiers[0])

    @classmethod
    def from_file(cls, path: str | Path, **read_csv_options: Any) -> Flight:
        """Read one flight from CSV and validate it."""
        return cls(pd.read_csv(path, **read_csv_options))


@dataclass(frozen=True, slots=True)
class Flights:
    """A collection of observations that can be split into validated flights."""

    data: pd.DataFrame

    def __post_init__(self) -> None:
        missing = REQUIRED_FLIGHT_COLUMNS.difference(self.data.columns)
        if missing:
            raise ValueError(f"Flights is missing required columns: {sorted(missing)}")
        frame = self.data.copy()
        _flight_ids(frame["flight_id"], owner="Flights")
        normalized = frame["flight_id"].astype(str).str.strip()
        frame["flight_id"] = normalized
        object.__setattr__(self, "data", frame)

    @classmethod
    def from_file(cls, path: str | Path, **read_csv_options: Any) -> Flights:
        """Read a collection of flight observations from CSV."""
        return cls(pd.read_csv(path, **read_csv_options))

    def iterate(self, limit: int | None = None) -> Iterator[Flight]:
        """Yield flights in deterministic ID order."""
        invalid_limit = limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
        )
        if invalid_limit:
            raise ValueError("limit must be a non-negative integer or None")
        if limit == 0:
            return
        for index, (_flight_id, frame) in enumerate(
            self.data.groupby("flight_id", sort=True, dropna=False)
        ):
            if limit is not None and index >= limit:
                break
            yield Flight(frame)

    def __iter__(self) -> Iterator[Flight]:
        return self.iterate()


def _flight_ids(values: pd.Series, *, owner: str) -> list[str]:
    if values.isna().any():
        raise ValueError(f"{owner} contains an empty flight_id")
    normalized = values.astype(str).str.strip()
    if normalized.eq("").any():
        raise ValueError(f"{owner} contains an empty flight_id")
    return normalized.drop_duplicates().tolist()
