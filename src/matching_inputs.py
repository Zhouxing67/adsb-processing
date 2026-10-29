"""Shared input preparation for batch and interactive matching modes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from adsb import Flight
from path_map import MovementType, load_data

DEFAULT_ARRIVALS = Path("data/ADS-B/more_15_arr.csv")
DEFAULT_DEPARTURES = Path("data/ADS-B/more_15_dep.csv")


@dataclass(frozen=True, slots=True)
class InputFile:
    name: str
    path: Path
    movement_type: MovementType


@dataclass(frozen=True, slots=True)
class LoadedDataset:
    name: str
    path: Path
    movement_type: MovementType
    flights: tuple[Flight, ...]

    def iterate(self, limit: int | None = None) -> Iterator[Flight]:
        invalid_limit = limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
        )
        if invalid_limit:
            raise ValueError("limit must be a non-negative integer or None")
        yield from self.flights if limit is None else self.flights[:limit]


def select_input_files(
    arrivals: Path | None,
    departures: Path | None,
    *,
    arrivals_provided: bool,
    departures_provided: bool,
) -> tuple[InputFile, ...]:
    """Apply the CLI's explicit-input selection rules without touching the filesystem."""
    if not arrivals_provided and not departures_provided:
        arrivals = DEFAULT_ARRIVALS
        departures = DEFAULT_DEPARTURES
    selected = []
    if arrivals is not None:
        selected.append(InputFile("arrival", arrivals, MovementType.ARRIVAL))
    if departures is not None:
        selected.append(InputFile("departure", departures, MovementType.DEPARTURE))
    return tuple(selected)


def load_datasets(
    inputs: Iterable[InputFile], input_timezone: str
) -> tuple[LoadedDataset, ...]:
    """Load and normalize every selected file, rejecting an empty combined dataset."""
    datasets = []
    for item in inputs:
        collection = load_data(item.path, item.movement_type, input_timezone)
        # Construct every Flight now so timestamp, coordinate and per-flight
        # consistency errors surface before either mode starts its lifecycle.
        flights = tuple(collection)
        datasets.append(LoadedDataset(item.name, item.path, item.movement_type, flights))
    result = tuple(datasets)
    if not result or not any(dataset.flights for dataset in result):
        raise ValueError("Selected ADS-B inputs contain no flights")
    return result
