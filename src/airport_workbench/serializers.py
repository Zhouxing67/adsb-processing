"""GeoJSON serializers used by the browser workbench."""

from __future__ import annotations

from typing import Any, Sequence

from shapely.geometry import LineString, Point, mapping

from flight import Flight
from path_map import Path
from utils.json_value import to_json_value


def flight_geojson(
    flight: Flight, index: int = 0, *, flight_key: str | None = None
) -> dict[str, Any]:
    """Serialize valid Flight observations and their connecting line."""
    features: list[dict[str, Any]] = []
    coordinates: list[list[float]] = []
    for sequence, point in enumerate(flight.observations):
        coordinate = [point.longitude, point.latitude]
        coordinates.append(coordinate)
        properties = {name: to_json_value(value) for name, value in point.to_record().items()}
        properties.update(
            kind="observation", sequence=sequence, flight_index=index, flight_key=flight_key
        )
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(Point(coordinate)),
                "properties": properties,
            }
        )
    if len(coordinates) >= 2:
        features.insert(
            0,
            {
                "type": "Feature",
                "geometry": mapping(LineString(coordinates)),
                "properties": {
                    "kind": "trajectory",
                    "flight_index": index,
                    "flight_key": flight_key,
                    "observation_count": len(coordinates),
                },
            },
        )
    return {"type": "FeatureCollection", "features": features}


def path_geojson(path: Path, index: int = 0, *, flight_key: str | None = None) -> dict[str, Any]:
    """Serialize every directed path edge separately, preserving traversal order."""
    features = []
    for sequence, edge in enumerate(path):
        geometry = path.oriented_geometry(edge)
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geometry),
                "properties": {
                    "kind": "path_edge",
                    "path_index": index,
                    "flight_key": flight_key,
                    "sequence": sequence,
                    "u": edge.from_,
                    "v": edge.to_,
                    "key": edge.key_,
                    "edge_id": {"u": edge.from_, "v": edge.to_, "key": edge.key_},
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def serialize_flights(flights: Sequence[Flight]) -> list[dict[str, Any]]:
    return [flight_geojson(flight, index) for index, flight in enumerate(flights)]


def serialize_paths(paths: Sequence[Path]) -> list[dict[str, Any]]:
    return [path_geojson(path, index) for index, path in enumerate(paths)]
