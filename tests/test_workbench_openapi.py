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


def test_state_endpoint_has_a_named_response_contract() -> None:
    documents = workbench_openapi_documents()
    for document in documents.values():
        response = document["paths"]["/api/state"]["get"]["responses"]["200"]
        schema = response["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/WorkbenchStateResponse"}


def test_graph_command_endpoints_share_a_named_response_contract() -> None:
    document = workbench_openapi_documents()["graph.json"]
    command_paths = {
        "/api/draw-connection",
        "/api/restore-confirm",
        "/api/merge-nodes-confirm",
        "/api/delete-edge-confirm",
        "/api/delete-node-confirm",
        "/api/split-source-confirm",
        "/api/manual-snap-confirm",
        "/api/update-node",
        "/api/update-edge",
        "/api/stand-clusters/create",
        "/api/stand-clusters/assign",
        "/api/stand-clusters/rename",
        "/api/stand-clusters/delete",
        "/api/save",
        "/api/undo",
        "/api/finish",
    }
    for path in command_paths:
        response = document["paths"][path]["post"]["responses"]["200"]
        schema = response["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/GraphCommandResponse"}


def test_graph_preview_endpoints_have_named_response_contracts() -> None:
    document = workbench_openapi_documents()["graph.json"]
    endpoints = {
        ("/api/restore-options", "post"): "RestoreOptionsResponse",
        ("/api/merge-candidates", "get"): "MergeCandidatesResponse",
        ("/api/merge-nodes-preview", "post"): "MergeNodesPreviewResponse",
        ("/api/delete-edge-preview", "post"): "DeleteEdgePreviewResponse",
        ("/api/delete-node-preview", "post"): "DeleteNodePreviewResponse",
        ("/api/split-source-preview", "post"): "SplitSourcePreviewResponse",
        ("/api/manual-snap-preview", "post"): "ManualSnapPreviewResponse",
    }
    for (path, method), model in endpoints.items():
        response = document["paths"][path][method]["responses"]["200"]
        schema = response["content"]["application/json"]["schema"]
        assert schema == {"$ref": f"#/components/schemas/{model}"}


def test_flight_endpoints_have_named_response_contracts() -> None:
    document = workbench_openapi_documents()["flight.json"]
    endpoints = {
        ("/api/flights", "get"): "FlightCatalogueResponse",
        ("/api/flights/{flight_key}", "get"): "FlightDetailResponse",
        ("/api/flight-selection", "get"): "FlightSelectionResponse",
        ("/api/flights/{flight_key}/geometry", "get"): "FlightGeometryResponse",
        ("/api/matches", "post"): "MatchSubmissionResponse",
        ("/api/matches", "get"): "MatchStatusResponse",
        ("/api/routes/coverage", "get"): "RouteCoverageResponse",
        ("/api/routes/detect-anomalies", "post"): "DetectRouteAnomaliesResponse",
        ("/api/routes/batch-review", "post"): "BatchUpdateRouteReviewResponse",
    }
    for (path, method), model in endpoints.items():
        response = document["paths"][path][method]["responses"]["200"]
        schema = response["content"]["application/json"]["schema"]
        assert schema == {"$ref": f"#/components/schemas/{model}"}
