"""Thin FastAPI application wiring for the airport graph and flight workbench."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path as FilePath
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from airport_surface import DEFAULT_GRAPH_PATH
from flight.flight_repository import FlightDatabase

from .api_models import (
    ERROR_RESPONSES,
    ApiErrorCode,
    ErrorResponse,
    WorkbenchStateResponse,
    error_detail,
    normalize_error_detail,
)
from .editor import EditorSession, GraphObjectNotFound, RevisionConflict
from .flights import FlightWorkbench
from .graph_state import VALIDATION_EDGE_COLORS, BrowserState, _edge_colors
from .routes_flights import build_flights_router
from .routes_graph import build_graph_router
from .routes_issues import build_match_issues_router
from .routes_library import build_route_library_router

__all__ = [
    "BrowserState",
    "VALIDATION_EDGE_COLORS",
    "_edge_colors",
    "create_app",
]


def create_app(
    session: EditorSession,
    save_path: FilePath = DEFAULT_GRAPH_PATH,
    on_finish: Callable[[], None] | None = None,
    *,
    match_config: Any | None = None,
    input_time_semantics: str = "UTC",
    display_timezone: str = "UTC",
    flight_database: FlightDatabase | None = None,
) -> FastAPI:
    browser = BrowserState(session)
    flight_mode = flight_database is not None
    flight_workbench = None
    if flight_database is not None:
        flight_workbench = FlightWorkbench(
            session.airport_graph,
            flight_database,
            match_config=match_config,
            input_time_semantics=input_time_semantics,
            display_timezone=display_timezone,
        )
        if flight_workbench.dataset_total_flights == 0:
            flight_workbench.close()
            raise ValueError("数据库中没有可用的航班")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            if flight_workbench is not None:
                await run_in_threadpool(flight_workbench.close)

    app = FastAPI(
        title="Airport Workbench",
        lifespan=lifespan,
        responses=ERROR_RESPONSES,
    )
    graph_routes = build_graph_router(session, save_path, on_finish)
    graph_paths = {getattr(route, "path", None) for route in graph_routes.routes}

    @app.exception_handler(RevisionConflict)
    async def revision_conflict_handler(_request: Request, error: RevisionConflict) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                detail=error_detail(
                    ApiErrorCode.REVISION_CONFLICT,
                    str(error),
                    {"current_revision": error.current_revision},
                )
            ).model_dump(mode="json"),
        )

    @app.exception_handler(GraphObjectNotFound)
    async def object_not_found_handler(
        _request: Request, error: GraphObjectNotFound
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                detail=error_detail(ApiErrorCode.OBJECT_NOT_FOUND, str(error))
            ).model_dump(mode="json"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
        detail = error.detail
        if flight_mode and error.status_code == 405 and request.url.path in graph_paths:
            detail = "航班工作台不允许修改机场图"
        return JSONResponse(
            status_code=error.status_code,
            content=ErrorResponse(
                detail=normalize_error_detail(error.status_code, detail)
            ).model_dump(mode="json"),
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                detail=error_detail(
                    ApiErrorCode.VALIDATION_ERROR,
                    "请求参数验证失败",
                    {
                        "errors": [
                            {
                                str(key): list(value) if key == "loc" else value
                                for key, value in item.items()
                                if key not in {"ctx", "input", "url"}
                            }
                            for item in error.errors()
                        ]
                    },
                )
            ).model_dump(mode="json"),
        )

    @app.get("/api/state")
    def state() -> WorkbenchStateResponse:
        value = browser.state(not flight_mode and on_finish is not None, save_path)
        value["flight_mode"] = flight_mode
        value["capabilities"] = {
            "can_edit_graph": not flight_mode,
            "has_flights": flight_mode,
            "can_match": flight_mode,
        }
        if flight_workbench is not None:
            value["flight_count"] = flight_workbench.dataset_total_flights
        return WorkbenchStateResponse.model_validate(value)

    if flight_mode:
        assert flight_workbench is not None
        app.include_router(build_flights_router(flight_workbench))
        app.include_router(build_route_library_router(flight_workbench))
        app.include_router(build_match_issues_router(flight_workbench))
    else:
        app.include_router(graph_routes)

    from .frontend import mount_frontend

    mount_frontend(app)
    return app
