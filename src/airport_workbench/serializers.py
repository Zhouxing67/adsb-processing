"""GeoJSON serializers used by the browser workbench."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Sequence

import pandas as pd
from shapely.geometry import LineString, Point, mapping

from adsb import Flight
from path_map import Path


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return _json_value(value.item())
    return str(value)


def flight_geojson(flight: Flight, index: int = 0) -> dict[str, Any]:
    """Serialize valid Flight observations and their connecting line."""
    data = flight.data
    if "longitude" not in data or "latitude" not in data:
        raise ValueError("Flight data must contain longitude and latitude columns")

    features: list[dict[str, Any]] = []
    coordinates: list[list[float]] = []
    for sequence, (_, row) in enumerate(data.iterrows()):
        longitude = row["longitude"]
        latitude = row["latitude"]
        if pd.isna(longitude) or pd.isna(latitude):
            continue
        coordinate = [float(longitude), float(latitude)]
        coordinates.append(coordinate)
        properties = {name: _json_value(value) for name, value in row.items()}
        properties.update(kind="observation", sequence=sequence, flight_index=index)
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
                    "observation_count": len(coordinates),
                },
            },
        )
    return {"type": "FeatureCollection", "features": features}


def path_geojson(path: Path, index: int = 0) -> dict[str, Any]:
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
                    "sequence": sequence,
                    "u": repr(edge.from_),
                    "v": repr(edge.to_),
                    "key": repr(edge.key_),
                    "edge_id": repr(edge.id),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def serialize_flights(flights: Sequence[Flight]) -> list[dict[str, Any]]:
    return [flight_geojson(flight, index) for index, flight in enumerate(flights)]


def serialize_paths(paths: Sequence[Path]) -> list[dict[str, Any]]:
    return [path_geojson(path, index) for index, path in enumerate(paths)]
