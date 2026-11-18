from pathlib import Path

import networkx as nx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pyproj import Proj
from shapely.geometry import LineString

from airport_surface import AirportGraph
from airport_workbench.app import create_app
from airport_workbench.editor import EditorSession
from flight import Flight


@pytest.mark.parametrize(
    "with_flights,editable",
    [(False, True), (True, False)],
)
def test_capabilities_keep_server_permissions(with_flights, editable):
    graph = nx.MultiGraph()
    graph.add_node("a", pos=(116.0, 40.0))
    graph.add_node("b", pos=(116.001, 40.001))
    graph.add_edge("a", "b", geometry=LineString([(116.0, 40.0), (116.001, 40.001)]))
    session = EditorSession(AirportGraph(graph, Proj("EPSG:32650")))
    flights = (
        [
            Flight(
                pd.DataFrame(
                    {
                        "flight_id": ["one", "one"],
                        "timestamp": ["2024-01-01 00:00:00", "2024-01-01 00:01:00"],
                        "longitude": [116.0, 116.001],
                        "latitude": [40.0, 40.001],
                    }
                )
            )
        ]
        if with_flights
        else []
    )
    with TestClient(create_app(session, Path("unused.json"), flights=flights)) as client:
        capabilities = client.get("/api/state").json()["capabilities"]
        assert capabilities == {
            "can_edit_graph": editable,
            "has_flights": with_flights,
            "can_match": with_flights,
        }
        routes = client.get("/openapi.json").json()["paths"]
        assert ("/api/flights" in routes) == with_flights
        assert ("/api/update-edge" in routes) == editable
        if editable:
            assert client.get("/api/flights").status_code == 404
            assert client.post("/api/matches", json={"flight_keys": []}).status_code in {404, 405}
        else:
            assert client.post("/api/undo", json={"expected_revision": 0}).status_code == 405
