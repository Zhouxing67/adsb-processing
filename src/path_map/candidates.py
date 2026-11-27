"""Spatially indexed candidate generation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, Point

from airport_surface import AirportGraph

from .path import EdgeId


@dataclass(frozen=True, slots=True)
class Candidate:
    """空间索引召回的无向候选边及其到观测点的 2D 距离。"""

    # 观测点在轨迹中的索引
    observation_index: int
    # 对应的 AirportGraph 无向边标识
    edge_id: EdgeId
    # 观测点到该边线段的 2D 欧氏距离（米）
    distance: float


class CandidateIndex:
    """Projected edge geometries and their STRtree; built once per matcher."""

    def __init__(self, airport_graph: AirportGraph) -> None:
        self.airport_graph = airport_graph
        self.edge_ids: list[EdgeId] = []
        self.lines: list[LineString] = []
        for u, v, key in airport_graph.graph.edges(keys=True):
            line = airport_graph.project_shape(airport_graph.oriented_edge_geometry(u, v, key))
            if line.is_empty or line.length == 0:
                continue
            self.edge_ids.append((u, v, key))
            self.lines.append(line)
        if not self.lines:
            raise ValueError("Airport graph has no non-empty edge geometries")
        self.tree = STRtree(self.lines)

    def candidates(
        self, observation_index: int, point: Point, radius: float, maximum: int
    ) -> list[Candidate]:
        indices = self.tree.query(point, predicate="dwithin", distance=radius)
        if len(indices) == 0:
            return []
        lines = self.lines
        scored: list[tuple[float, int]] = []
        for raw_index in np.asarray(indices).tolist():
            index = int(raw_index)
            distance = point.distance(lines[index])
            if distance <= radius:
                scored.append((distance, index))
        scored.sort()
        edge_ids = self.edge_ids
        return [
            Candidate(observation_index, edge_ids[index], distance)
            for distance, index in scored[:maximum]
        ]
