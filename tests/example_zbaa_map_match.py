"""Minimal real-data example for the ZBAA HMM map matcher.

Run from the repository root with::

    uv run python tests/example_zbaa_map_match.py
"""

from pathlib import Path as FilePath

import pandas as pd
from traffic.core import Flight

from airport_surface import load_graph
from airport_workbench import open_workbench
from path_map import MatchConfig, MovementType, map_flight

ROOT = FilePath(__file__).resolve().parents[1]
GRAPH_FILE = ROOT / "data" / "graphs" / "zbaa_final.json"
FLIGHT_FILE = ROOT / "data" / "ADS-B" / "one_flight.csv"


def main() -> None:
    airport_graph = load_graph(GRAPH_FILE)
    flight = Flight(pd.read_csv(FLIGHT_FILE))

    matched_path = map_flight(
        airport_graph,
        flight,
        MatchConfig(
            search_radius=60.0,
            max_candidates=5,
            gps_sigma=15.0,
            transition_beta=25.0,
        ),
        movement_type=MovementType.ARRIVAL,
    )

    print(f"Matched {len(flight.data)} observations to {len(matched_path)} edges")
    print(f"Movement type: {matched_path.movement_type.value}")
    print(f"Network-path length: {matched_path.total_length:.1f} m")
    for edge in matched_path.edge_ids:
        print(edge)

    open_workbench(airport_graph, flights=[flight], paths=[matched_path])


if __name__ == "__main__":
    main()
