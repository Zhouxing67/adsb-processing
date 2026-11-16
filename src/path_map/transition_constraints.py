"""Pluggable constraints for candidate-to-candidate transition choices."""

from __future__ import annotations

import logging
from itertools import pairwise
from math import acos, degrees, hypot, isfinite
from typing import Protocol, Sequence

from shapely.geometry import Point

from .candidates import CandidateIndex
from .path import DirectedEdge, EdgeId

ZERO_DISTANCE_TOLERANCE_M = 1e-9
ANGLE_COMPARISON_TOLERANCE_DEG = 1e-9
logger = logging.getLogger(__name__)

type Tangent = tuple[float, float]


class TransitionConstraint(Protocol):
    """Decide whether one complete directed transition choice is allowed."""

    def accepts(self, edges: Sequence[DirectedEdge]) -> bool: ...


class LocalTurnConstraint:
    """Reject sharp local turns inside a single transition choice."""

    def __init__(
        self,
        index: CandidateIndex,
        *,
        max_angle_deg: float,
        tangent_sample_m: float,
    ) -> None:
        self.max_angle_deg = max_angle_deg
        self.tangent_sample_m = tangent_sample_m
        self.incoming_tangents: dict[EdgeId, Tangent | None] = {}
        self.outgoing_tangents: dict[EdgeId, Tangent | None] = {}

        for edge_id, line in index.directed_lines.items():
            distance = min(self.tangent_sample_m, line.length)
            if distance <= ZERO_DISTANCE_TOLERANCE_M:
                self.incoming_tangents[edge_id] = None
                self.outgoing_tangents[edge_id] = None
                continue
            start = Point(line.coords[0])
            end = Point(line.coords[-1])
            outgoing_sample = line.interpolate(distance)
            incoming_sample = line.interpolate(line.length - distance)
            self.outgoing_tangents[edge_id] = (
                outgoing_sample.x - start.x,
                outgoing_sample.y - start.y,
            )
            self.incoming_tangents[edge_id] = (
                end.x - incoming_sample.x,
                end.y - incoming_sample.y,
            )

    def turn_angle(
        self, incoming_edge: DirectedEdge, outgoing_edge: DirectedEdge
    ) -> float | None:
        """Return the local turn angle, or None for disconnected/degenerate edges."""
        if incoming_edge.to_ != outgoing_edge.from_:
            return None
        incoming = self.incoming_tangents[incoming_edge.id]
        outgoing = self.outgoing_tangents[outgoing_edge.id]
        if incoming is None or outgoing is None:
            return None
        incoming_norm = hypot(*incoming)
        outgoing_norm = hypot(*outgoing)
        if (
            incoming_norm <= ZERO_DISTANCE_TOLERANCE_M
            or outgoing_norm <= ZERO_DISTANCE_TOLERANCE_M
        ):
            return None
        cosine = (incoming[0] * outgoing[0] + incoming[1] * outgoing[1]) / (
            incoming_norm * outgoing_norm
        )
        return degrees(acos(max(-1.0, min(1.0, cosine))))

    def accepts(self, edges: Sequence[DirectedEdge]) -> bool:
        for incoming_edge, outgoing_edge in pairwise(edges):
            if incoming_edge.to_ != outgoing_edge.from_:
                continue
            angle = self.turn_angle(incoming_edge, outgoing_edge)
            if angle is None or not isfinite(angle):
                logger.debug(
                    "Skipping turn constraint for degenerate geometry: shared_node=%r "
                    "incoming_edge=%r outgoing_edge=%r",
                    incoming_edge.to_,
                    incoming_edge,
                    outgoing_edge,
                )
                continue
            if angle > self.max_angle_deg + ANGLE_COMPARISON_TOLERANCE_DEG:
                logger.debug(
                    "Rejected transition choice: shared_node=%r incoming_edge=%r "
                    "outgoing_edge=%r angle_deg=%.6f threshold_deg=%.6f",
                    incoming_edge.to_,
                    incoming_edge,
                    outgoing_edge,
                    angle,
                    self.max_angle_deg,
                )
                return False
        return True
