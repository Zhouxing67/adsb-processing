"""Isolated browser-regression backend; never reads or writes user graph data."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import networkx as nx
import pandas as pd
import uvicorn
from flight_database_fixture import create_flight_database
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import AirportGraph
from airport_workbench.app import create_app
from airport_workbench.editor import EditorSession
from flight import Flight

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--flights", type=int, default=0)
args = parser.parse_args()
graph = nx.MultiGraph()
graph.add_node("1", pos=(116.59, 40.07))
graph.add_node("2", pos=(116.595, 40.07))
graph.add_edge(
    "1",
    "2",
    geometry=LineString([(116.59, 40.07), (116.595, 40.07)]),
    aeroway="parking_position",
    ref="A01",
    name="Stand A",
)
flights = [
    Flight(
        pd.DataFrame(
            {
                "flight_id": [f"F{i:02}"] * 3,
                "timestamp": pd.date_range("2024-01-01", periods=3, freq="1min", tz="UTC"),
                "actual_arr": [pd.Timestamp("2024-01-01 00:02", tz="UTC")] * 3,
                "longitude": [116.59, 116.592, 116.595],
                "latitude": [40.07] * 3,
                "arr_stand_position": ["A01" if i == 0 else None] * 3,
                "dep_stand_position": ["D02" if i == 1 else None] * 3,
            }
        )
    )
    for i in range(args.flights)
]
database_directory = TemporaryDirectory()
database = create_flight_database(
    Path(database_directory.name) / "browser.duckdb",
    flights,
    ["arrival" if i % 2 == 0 else "departure" for i in range(args.flights)],
)
app = create_app(
    EditorSession(AirportGraph(graph, Proj("EPSG:32650"))),
    Path("outputs/browser-regression/unused.json"),
    flight_database=database if args.flights else None,
)
uvicorn.run(app, host="127.0.0.1", port=args.port)
