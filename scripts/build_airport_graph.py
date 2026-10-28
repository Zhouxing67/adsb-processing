"""Build and persist an airport surface graph as an explicit offline task.

Install the optional builder dependency before running this script::

    uv sync --group graph-build
    uv run python scripts/build_airport_graph.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from airport_surface import graph_id, load_graph, save_graph

DEFAULT_OUTPUT_DIRECTORY = Path("data/graphs")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an AirportGraph from traffic's airport/OSM data."
    )
    parser.add_argument(
        "--airport",
        required=True,
        type=str.upper,
        help="ICAO airport code, such as ZBAA or KJFK",
    )
    parser.add_argument(
        "--projection",
        required=True,
        help="metric projected CRS, for example EPSG:32650",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="output graph file (default: data/graphs/<icao>_raw.json)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace the output file if it already exists",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = (
        args.output
        if args.output is not None
        else DEFAULT_OUTPUT_DIRECTORY / f"{args.airport.lower()}_raw.json"
    ).resolve()
    if output.exists() and not args.force:
        raise SystemExit(
            f"Output already exists: {output}\n"
            "Pass --force to replace it, or choose another --output path."
        )

    try:
        from airport_surface.traffic_builder import build_graph
    except ModuleNotFoundError as error:
        if error.name == "traffic" or (error.name or "").startswith("traffic."):
            raise SystemExit(
                "The optional graph-build dependencies are not installed.\n"
                "Run: uv sync --group graph-build"
            ) from error
        raise

    print(
        f"Building {args.airport} surface graph from airport/OSM data "
        f"with projection={args.projection!r}..."
    )
    try:
        airport_graph = build_graph(args.airport, args.projection)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    save_graph(airport_graph, output)

    # Read the artifact through the production loader before reporting success.
    restored = load_graph(output)
    expected_id = graph_id(airport_graph)
    restored_id = graph_id(restored)
    if restored_id != expected_id:
        raise RuntimeError(
            f"Saved graph verification failed: expected {expected_id}, got {restored_id}"
        )

    print(f"Saved and verified: {output}")
    print(
        f"airport={restored.metadata.airport} "
        f"projection={restored.projection.srs} "
        f"nodes={restored.graph.number_of_nodes()} "
        f"edges={restored.graph.number_of_edges()} "
        f"sources={len(restored.source_edges)}"
    )
    print(f"graph_id={restored_id}")
    if restored.metadata.build_issues:
        print(f"build_issues={len(restored.metadata.build_issues)}")
        for issue in restored.metadata.build_issues:
            print(f"- {issue}")
    else:
        print("build_issues=0")


if __name__ == "__main__":
    main()
