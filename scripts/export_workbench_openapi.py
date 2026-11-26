"""Export deterministic OpenAPI contracts for both workbench modes."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import networkx as nx
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import AirportGraph
from airport_workbench.app import create_app
from airport_workbench.editor import EditorSession
from flight.flight_repository import FlightDatabase
from flight.models import FlightSummary

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_DIRECTORY = ROOT / "frontend" / "workbench" / "openapi"


def _session() -> EditorSession:
    graph = nx.MultiGraph()
    graph.add_node("1", pos=(116.59, 40.07))
    graph.add_node("2", pos=(116.595, 40.07))
    graph.add_edge(
        "1",
        "2",
        geometry=LineString([(116.59, 40.07), (116.595, 40.07)]),
        aeroway="parking_position",
        ref="A01",
    )
    return EditorSession(AirportGraph(graph, Proj("EPSG:32650")))


class _StubCatalogue:
    def dataset_stats(self, *, display_timezone: str = "UTC") -> dict[str, Any]:
        del display_timezone
        return {
            "total_flights": 1,
            "dataset_max_points": 2,
            "dataset_min_date": "2024-01-01",
            "dataset_max_date": "2024-01-01",
            "stand_options": ["A01"],
        }

    def summaries(self) -> list[FlightSummary]:
        return [
            FlightSummary(
                movement="departure",
                flight_id="OPENAPI",
                flight_number="OPENAPI",
                number_count=1,
                start_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
                end_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
                point_count=2,
                stand_position="A01",
                stand_count=1,
            )
        ]


class _StubFlightDatabase:
    """Minimal in-memory stand-in so OpenAPI export requires no live database."""

    read_only = False
    postgres = None
    catalogue = _StubCatalogue()

    def close(self) -> None:
        return None


def workbench_openapi_documents() -> dict[str, dict[str, Any]]:
    """Build contracts from the same application factory used in production."""
    graph_app = create_app(_session(), ROOT / "outputs" / "openapi-unused.json")
    flight_app = create_app(
        _session(),
        ROOT / "outputs" / "openapi-unused.json",
        flight_database=cast(FlightDatabase, _StubFlightDatabase()),
    )
    return {
        "graph.json": graph_app.openapi(),
        "flight.json": flight_app.openapi(),
    }


def _serialized(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def export_openapi(*, check: bool = False) -> list[Path]:
    """Write contracts, or return mismatched paths without modifying them."""
    mismatches: list[Path] = []
    if not check:
        OPENAPI_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for filename, document in workbench_openapi_documents().items():
        path = OPENAPI_DIRECTORY / filename
        expected = _serialized(document)
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                mismatches.append(path)
        else:
            path.write_text(expected, encoding="utf-8", newline="\n")
    return mismatches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when committed OpenAPI files differ from the application schema",
    )
    args = parser.parse_args()
    mismatches = export_openapi(check=args.check)
    if mismatches:
        paths = "\n".join(str(path.relative_to(ROOT)) for path in mismatches)
        raise SystemExit(f"OpenAPI contracts are out of date:\n{paths}")


if __name__ == "__main__":
    main()
