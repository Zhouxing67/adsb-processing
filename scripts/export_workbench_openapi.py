"""Export deterministic OpenAPI contracts for both workbench modes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import networkx as nx
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import AirportGraph
from airport_workbench.app import create_app
from airport_workbench.editor import EditorSession
from flight.flight_repository import FlightDatabase

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


def _flight_database(path: Path) -> FlightDatabase:
    import duckdb

    with duckdb.connect(str(path)) as connection:
        connection.execute("""
            CREATE TABLE adsb_dep (
                flight_id VARCHAR, number VARCHAR, timestamp TIMESTAMP,
                longitude DOUBLE, latitude DOUBLE, dep_stand_position VARCHAR,
                org_runway VARCHAR
            );
            INSERT INTO adsb_dep VALUES
                ('OPENAPI', 'OPENAPI', '2024-01-01 00:00:00', 116.59, 40.07, 'A01', NULL),
                ('OPENAPI', 'OPENAPI', '2024-01-01 00:01:00', 116.595, 40.07, 'A01', NULL);
            CREATE TABLE adsb_arr (
                flight_id VARCHAR, number VARCHAR, timestamp TIMESTAMP,
                longitude DOUBLE, latitude DOUBLE, arr_stand_position VARCHAR,
                dst_runway VARCHAR
            );
        """)
    return FlightDatabase(path)


def workbench_openapi_documents() -> dict[str, dict[str, Any]]:
    """Build contracts from the same application factory used in production."""
    graph_app = create_app(_session(), ROOT / "outputs" / "openapi-unused.json")
    with TemporaryDirectory(dir=ROOT) as directory:
        database = _flight_database(Path(directory) / "openapi.duckdb")
        flight_app = create_app(
            _session(),
            ROOT / "outputs" / "openapi-unused.json",
            flight_database=database,
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
