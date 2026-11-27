"""HTTP routes for the PostgreSQL route library."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from .api_models import (
    BatchUpdateRouteReviewRequest,
    BatchUpdateRouteReviewResponse,
    DetectRouteAnomaliesRequest,
    DetectRouteAnomaliesResponse,
    ImportMatchesToRouteLibraryRequest,
    ImportRoutesSummaryResponse,
    RouteCoverageResponse,
    RouteGeometryResponse,
    RouteItemResponse,
    RouteListRequest,
    RouteListResponse,
    UpdateRouteReviewRequest,
)
from .flights import CataloguePageOutOfRange, FlightWorkbench


def build_route_library_router(flight_workbench: FlightWorkbench) -> APIRouter:
    router = APIRouter()

    @router.get("/api/routes")
    def routes_list(
        filters: Annotated[RouteListRequest, Query()],
    ) -> RouteListResponse:
        try:
            value = flight_workbench.routes_list(
                query=filters.q,
                movement=filters.movement,
                stand_ref=filters.stand_ref,
                runway_ref=filters.runway_ref,
                status=filters.status,
                all_graphs=filters.all_graphs,
                page=filters.page,
                page_size=filters.page_size,
            )
            return RouteListResponse.model_validate(value)
        except CataloguePageOutOfRange as error:
            raise HTTPException(
                400,
                {
                    "code": "page_out_of_range",
                    "message": str(error),
                    "total_pages": error.total_pages,
                },
            ) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.get("/api/routes/coverage")
    def route_coverage() -> RouteCoverageResponse:
        return RouteCoverageResponse.model_validate(flight_workbench.route_coverage())

    @router.get("/api/routes/{route_id}/geometry")
    def route_geometry(route_id: str) -> RouteGeometryResponse:
        try:
            return RouteGeometryResponse.model_validate(flight_workbench.route_geometry(route_id))
        except KeyError as error:
            raise HTTPException(404, "未知 route_id") from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.patch("/api/routes/{route_id}")
    def update_route_review(
        route_id: str,
        item: UpdateRouteReviewRequest,
    ) -> RouteItemResponse:
        try:
            return RouteItemResponse.model_validate(
                flight_workbench.update_route_review(route_id, item.status, note=item.note)
            )
        except KeyError as error:
            raise HTTPException(404, "未知 route_id") from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @router.post("/api/routes/detect-anomalies")
    def detect_route_anomalies(
        item: DetectRouteAnomaliesRequest,
    ) -> DetectRouteAnomaliesResponse:
        try:
            return DetectRouteAnomaliesResponse.model_validate(
                flight_workbench.detect_route_anomalies(
                    item.route_ids,
                    query=item.q,
                    movement=item.movement,
                    stand_ref=item.stand_ref,
                    runway_ref=item.runway_ref,
                    status=item.status,
                    all_graphs=item.all_graphs,
                )
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/api/routes/batch-review")
    def batch_update_route_review(
        item: BatchUpdateRouteReviewRequest,
    ) -> BatchUpdateRouteReviewResponse:
        try:
            return BatchUpdateRouteReviewResponse.model_validate(
                flight_workbench.batch_update_route_review(
                    item.route_ids,
                    item.status,
                    note=item.note,
                )
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @router.post("/api/routes/import-matches")
    def import_matched_routes(
        item: ImportMatchesToRouteLibraryRequest,
    ) -> ImportRoutesSummaryResponse:
        try:
            return ImportRoutesSummaryResponse.model_validate(
                flight_workbench.import_matched_routes(
                    item.flight_keys,
                    replace_candidates=item.replace_candidates,
                )
            )
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    return router
