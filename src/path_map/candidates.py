"""Spatially indexed candidate generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, Point

from airport_surface import AirportGraph


@dataclass(frozen=True, slots=True)
class Candidate:
    """HMM中观测点的可能隐藏状态候选"""

    # 观测点（索引）（ADS_B点）
    observation_index: int
    # 对应的AirportGraph的一条边
    edge_id: tuple[Hashable, Hashable, Hashable]
    # 观测点到边的距离
    distance: float
    # 该位置距离边起点多远；
    point: Point
    offset: float
    fraction: float


class CandidateIndex:
    """
    Projected edge geometries and their STRtree;
    built once per match.
    负责快速寻找一个Candidate
    """

    def __init__(self, airport_graph: AirportGraph) -> None:
        self.airport_graph = airport_graph
        self.edge_ids: list[tuple[Hashable, Hashable, Hashable]] = []
        self.lines: list[LineString] = []
        for u, v, key, data in airport_graph.graph.edges(keys=True, data=True):
            line = airport_graph.project_shape(data["geometry"])
            if not isinstance(line, LineString):
                raise ValueError(f"Edge {(u, v, key)} geometry must be a LineString")
            if line.is_empty or line.length == 0:
                continue
            line = self._orient_from_node(line, u)
            self.edge_ids.append((u, v, key))
            self.lines.append(line)
        if not self.lines:
            raise ValueError("Airport graph has no non-empty edge geometries")
        self.tree = STRtree(self.lines)

    def _orient_from_node(self, line: LineString, node: Hashable) -> LineString:
        pos = self.airport_graph.graph.nodes[node].get("pos")
        if pos is None:
            return line
        start = Point(line.coords[0])
        end = Point(line.coords[-1])
        node_point = Point(*self.airport_graph.project.transform(*pos))
        if start.distance(node_point) <= end.distance(node_point):
            return line
        return LineString(reversed(line.coords))

    def candidates(
        self, observation_index: int, point: Point, radius: float, maximum: int
    ) -> list[Candidate]:
        indices = self.tree.query(point.buffer(radius), predicate="intersects")
        result: list[Candidate] = []
        for raw_index in np.asarray(indices).tolist():
            index = int(raw_index)

            line = self.lines[index]
            edge = self.edge_ids[index]
            distance = point.distance(line)
            if distance <= radius:
                offset = line.project(point)
                result.append(
                    Candidate(
                        observation_index,
                        edge,
                        distance,
                        line.interpolate(offset),
                        offset,
                        offset / line.length,
                    )
                )
        result.sort(key=lambda candidate: candidate.distance)
        return result[:maximum]
