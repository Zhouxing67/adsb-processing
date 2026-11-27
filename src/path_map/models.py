"""Public configuration, OD, and error models for map matching."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Mapping

from flight import MovementType

from .path import EdgeId


class MapMatchingFailure(StrEnum):
    """Stable machine-readable reasons for expected matching failures."""

    INVALID_OD = "invalid_od"
    MISSING_OD = "missing_od"
    UNKNOWN_OD = "unknown_od"
    NO_CANDIDATES = "no_candidates"
    NO_LEGAL_PATH = "no_legal_path"
    NO_MOVEMENT = "no_movement"


class MapMatchingError(ValueError):
    """An expected matching failure with a stable code and diagnostic context."""

    def __init__(
        self,
        code: MapMatchingFailure,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})


@dataclass(frozen=True, slots=True)
class MatchConfig:
    candidate_radius: float = 120.0
    max_candidates: int = 16
    gps_sigma: float = 10.0
    length_scale_m: float = 50.0
    max_transition_turn_angle_deg: float = 130.0
    turn_tangent_sample_m: float = 2.0
    max_pushback_radius_m: float = 250.0

    def __post_init__(self) -> None:
        distances = (
            self.candidate_radius,
            self.gps_sigma,
            self.length_scale_m,
            self.turn_tangent_sample_m,
            self.max_pushback_radius_m,
        )
        if any(not math.isfinite(value) or value <= 0 for value in distances):
            raise ValueError("Distance parameters must be finite and positive")
        if (
            not math.isfinite(self.max_transition_turn_angle_deg)
            or not 0 < self.max_transition_turn_angle_deg <= 180
        ):
            raise ValueError("max_transition_turn_angle_deg must be finite and in (0, 180]")
        if isinstance(self.max_candidates, bool) or not isinstance(self.max_candidates, int):
            raise ValueError("max_candidates must be a positive integer")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be a positive integer")


@dataclass(frozen=True, slots=True)
class FlightOD:
    """Surface OD labels. An inferred runway label may identify both reciprocal ends."""

    movement: MovementType
    stand_ref: str
    runway_ref: str | None
    runway_source: Literal["reported", "inferred"]
    runway_hit_edge: EdgeId | None = None

    @property
    def origin(self) -> str | None:
        return self.stand_ref if self.movement == MovementType.DEPARTURE else self.runway_ref

    @property
    def destination(self) -> str | None:
        return self.runway_ref if self.movement == MovementType.DEPARTURE else self.stand_ref
