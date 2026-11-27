"""Tests for the stateless algorithm demonstration service and HTTP routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from airport_workbench.algorithm_demo import (
    _toy_airport_graph,
    list_demo_scenarios,
    trace_demo_scenario,
)
from airport_workbench.api_models import DemoMatchConfig, DemoPointInput, DemoTraceRequest
from airport_workbench.app import create_app
from airport_workbench.editor import EditorSession
from airport_workbench.routes_demo import build_demo_router


def test_all_builtin_scenarios_match_real_matcher() -> None:
    scenarios = list_demo_scenarios()
    assert [item.id for item in scenarios] == [
        "arrival_basic",
        "departure_pushback",
        "phase2_fallback",
    ]

    for scenario in scenarios:
        trace = trace_demo_scenario(scenario.id)
        assert trace.final_result.status == "success"
        assert trace.final_result.edges
        active_phase = trace.phase2 if trace.final_result.used_phase == "phase2" else trace.phase1
        assert active_phase is not None
        assert active_phase.status == "accepted"
        # Traced trimmed path must match real Matcher.map_flight() edge-for-edge.
        assert active_phase.trimmed_edges == trace.final_result.edges


def test_departure_pushback_uses_reversal_state() -> None:
    trace = trace_demo_scenario("departure_pushback")
    assert trace.final_result.status == "success"
    active_phase = trace.phase2 if trace.final_result.used_phase == "phase2" else trace.phase1
    assert active_phase is not None
    reversal_steps = [
        state
        for layer in active_phase.layers
        for state in layer.states
        if state.is_optimal and state.used_reversal_step
    ]
    assert len(reversal_steps) == 1


def test_phase2_fallback_triggers_after_phase1_rejection() -> None:
    trace = trace_demo_scenario("phase2_fallback")
    assert trace.phase1.status in {"rejected", "no_path"}
    assert trace.phase1.rejection_reason is not None
    assert trace.phase2 is not None
    assert trace.phase2.status == "accepted"
    assert trace.final_result.used_phase == "phase2"
    assert trace.final_result.edges == trace.phase2.trimmed_edges


def test_custom_observations_and_config_override_via_router(tmp_path: Path) -> None:
    session = EditorSession(_toy_airport_graph())
    app = create_app(session, tmp_path / "unused.json")
    openapi_paths = app.openapi()["paths"]
    assert "/api/algorithm-demo/scenarios" in openapi_paths
    assert "/api/algorithm-demo/trace" in openapi_paths

    demo_router = build_demo_router()
    endpoints = {
        getattr(route, "path"): getattr(route, "endpoint")
        for route in demo_router.routes
        if hasattr(route, "path") and hasattr(route, "endpoint")
    }

    scenarios_resp = endpoints["/api/algorithm-demo/scenarios"]()
    assert len(scenarios_resp.scenarios) == 3

    # Dragging the 3rd observation point closer to taxiway A keeps matching valid
    custom_points = [
        DemoPointInput(x=475.0, y=48.0),
        DemoPointInput(x=408.0, y=98.0),
        DemoPointInput(x=310.0, y=148.0),
        DemoPointInput(x=180.0, y=150.0),
        DemoPointInput(x=124.0, y=232.0),
    ]
    trace_resp = endpoints["/api/algorithm-demo/trace"](
        DemoTraceRequest(
            scenario_id="arrival_basic",
            observations=custom_points,
            config=DemoMatchConfig(gps_sigma=8.0, max_candidates=4),
        )
    )
    assert trace_resp.final_result.status == "success"
    assert trace_resp.config.gps_sigma == 8.0
    assert trace_resp.observations[2].y == 148.0

    # Unknown scenario raises 404
    with pytest.raises(HTTPException) as exc_info:
        endpoints["/api/algorithm-demo/trace"](DemoTraceRequest(scenario_id="nonexistent"))
    assert exc_info.value.status_code == 404

    # Out-of-radius single point produces clean failed result
    far_trace = trace_demo_scenario(
        "arrival_basic",
        observations=[DemoPointInput(x=5000.0, y=5000.0)],
    )
    assert far_trace.final_result.status == "failed"
    assert far_trace.final_result.error_code == "no_candidates"
