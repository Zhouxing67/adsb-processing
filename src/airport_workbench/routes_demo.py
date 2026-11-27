"""HTTP routes for the interactive map-matching algorithm demonstration."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .algorithm_demo import list_demo_scenarios, trace_demo_scenario
from .api_models import (
    DemoScenariosResponse,
    DemoTraceRequest,
    DemoTraceResponse,
)


def build_demo_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/algorithm-demo/scenarios")
    def demo_scenarios() -> DemoScenariosResponse:
        return DemoScenariosResponse(scenarios=list_demo_scenarios())

    @router.post("/api/algorithm-demo/trace")
    def demo_trace(item: DemoTraceRequest) -> DemoTraceResponse:
        try:
            return trace_demo_scenario(
                item.scenario_id,
                observations=item.observations,
                config_override=item.config,
            )
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    return router
