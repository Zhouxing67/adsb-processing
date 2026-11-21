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
    graph.add_node("1", pos=(116.0, 40.0))
    graph.add_node("2", pos=(116.001, 40.001))
    graph.add_edge("1", "2", geometry=LineString([(116.0, 40.0), (116.001, 40.001)]))
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
            blocked = client.post("/api/undo", json={"expected_revision": 0})
            assert blocked.status_code == 405
            assert blocked.json() == {
                "detail": {
                    "code": "method_not_allowed",
                    "message": "航班工作台不允许修改机场图",
                    "context": {},
                }
            }


def test_http_and_validation_errors_share_one_response_shape():
    graph = nx.MultiGraph()
    graph.add_node("1", pos=(116.0, 40.0))
    session = EditorSession(AirportGraph(graph, Proj("EPSG:32650")))

    with TestClient(create_app(session)) as client:
        missing = client.get("/api/not-found")
        invalid = client.post("/api/undo", json={"expected_revision": "invalid"})

    assert missing.json() == {
        "detail": {"code": "not_found", "message": "Not Found", "context": {}}
    }
    invalid_detail = invalid.json()["detail"]
    assert invalid_detail["code"] == "validation_error"
    assert invalid_detail["message"] == "请求参数验证失败"
    assert invalid_detail["context"]["errors"][0]["loc"] == ["body", "expected_revision"]
