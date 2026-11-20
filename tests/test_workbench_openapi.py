from scripts.export_workbench_openapi import export_openapi, workbench_openapi_documents


def test_committed_workbench_openapi_contracts_are_current() -> None:
    assert export_openapi(check=True) == []


def test_workbench_modes_export_only_their_available_routes() -> None:
    documents = workbench_openapi_documents()
    graph_paths = documents["graph.json"]["paths"]
    flight_paths = documents["flight.json"]["paths"]

    assert "/api/state" in graph_paths
    assert "/api/state" in flight_paths
    assert "/api/draw-connection" in graph_paths
    assert "/api/draw-connection" not in flight_paths
    assert "/api/flights" in flight_paths
    assert "/api/flights" not in graph_paths
