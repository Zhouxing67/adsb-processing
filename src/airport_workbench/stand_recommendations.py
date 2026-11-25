"""Rank parking positions using observations at pushback or arrival at stand."""

from datetime import datetime, timedelta
from math import inf

from shapely import STRtree
from shapely.geometry import Point

from airport_surface import AirportGraph
from flight import Flight

from .api_models import SpatialStandCandidate


class StandGeometryIndex:
    def __init__(self, graph: AirportGraph):
        self.project = graph.project
        self.refs = []
        lines = []
        for stand, edges in graph.stand_to_edges.items():
            for edge in edges:
                self.refs.append(stand)
                lines.append(graph.project_shape(graph.graph.edges[edge]["geometry"]))
        self.tree = STRtree(lines)

    def candidates(self, flight: Flight, event: datetime) -> list[SpatialStandCandidate]:
        departure = flight.movement == "departure"
        points = flight.observations if departure else reversed(flight.observations)
        previous = None
        streak = 0
        nearest = inf
        first = True
        best: dict[str, SpatialStandCandidate] = {}
        for obs in points:
            elapsed = obs.timestamp - event if departure else event - obs.timestamp
            if elapsed < timedelta(0):
                continue
            if elapsed > timedelta(minutes=3):
                break
            point = Point(*self.project.transform(obs.longitude, obs.latitude))
            distances: dict[str, float] = {}
            # 25 m includes every competitor that could invalidate either margin.
            for i in self.tree.query(point, predicate="dwithin", distance=25):
                stand = self.refs[i]
                distance = point.distance(self.tree.geometries[i])
                distances[stand] = min(distance, distances.get(stand, inf))
            ranked = sorted(distances, key=distances.__getitem__)
            if ranked:
                stand = ranked[0]
                distance = distances[stand]
                margin = distances[ranked[1]] - distance if len(ranked) > 1 else inf
                if distance <= 15 and margin >= 8:
                    streak = streak + 1 if stand == previous else 1
                    nearest = min(nearest, distance) if stand == previous else distance
                    previous = stand
                    if streak >= 2 or (first and distance <= 5 and margin >= 10):
                        prior = best.get(stand)
                        if not prior or (streak, -nearest) > (
                            prior.consecutive_points, -prior.nearest_m
                        ):
                            best[stand] = SpatialStandCandidate(
                                stand=stand, consecutive_points=streak, nearest_m=nearest
                            )
                    first = False
                    continue
            previous = None
            first = False
        return sorted(best.values(), key=lambda c: (-c.consecutive_points, c.nearest_m, c.stand))
