"""HTTP routes for flight catalogue, stand editing, geometry, and matching."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .api_models import (
    FlightCatalogueRequest,
    FlightCatalogueResponse,
    FlightDetailResponse,
    FlightFilterRequest,
    FlightGeometryResponse,
    FlightSelectionResponse,
    MatchStatusResponse,
    MatchSubmissionResponse,
    StandRecommendations,
)
from .flights import CataloguePageOutOfRange, FlightFilter, FlightWorkbench


class UpdateStandRequest(BaseModel):
    stand_position: str | None


class MatchFlightsRequest(BaseModel):
    flight_keys: list[str] = Field(default_factory=list)
    force: bool = False


def _flight_filter(item: FlightFilterRequest) -> FlightFilter:
    return FlightFilter(
        query=item.q,
        movement_type=item.movement_type,
        status=item.match_status,
        min_points=item.min_points,
        max_points=item.max_points,
        stands=tuple(item.stands),
        start_date=item.start_date,
        end_date=item.end_date,
        validation_only=item.validation_only,
        whitelist_only=item.whitelist_only,
        issues_only=item.issues_only,
    )


def build_flights_router(flight_workbench: FlightWorkbench) -> APIRouter:
    router = APIRouter()

    @router.get("/api/flights")
    def flights_catalogue(
        filters: Annotated[FlightCatalogueRequest, Query()],
    ) -> FlightCatalogueResponse:
        try:
            value = flight_workbench.catalogue(
                _flight_filter(filters),
                page=filters.page,
                page_size=filters.page_size,
            )
            return FlightCatalogueResponse.model_validate(value)
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

    @router.get("/api/flights/{flight_key}/stand-recommendations")
    def stand_recommendations(flight_key: str) -> StandRecommendations:
        try:
            return flight_workbench.recommend_stands(flight_key)
        except KeyError as error:
            raise HTTPException(404, "未知 flight_key") from error

    @router.patch(
        "/api/flights/{flight_key}/stand", status_code=204, response_class=Response
    )
    def update_stand(flight_key: str, item: UpdateStandRequest) -> None:
        try:
            flight_workbench.update_stand(flight_key, item.stand_position)
        except KeyError as error:
            raise HTTPException(404, "未知 flight_key") from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @router.get("/api/flights/{flight_key}")
    def flight_detail(
        flight_key: str,
        observation_page: int = 1,
        observation_page_size: int = 100,
        all_fields: bool = False,
    ) -> FlightDetailResponse:
        try:
            value = flight_workbench.detail(
                flight_key,
                observation_page=observation_page,
                observation_page_size=observation_page_size,
                all_fields=all_fields,
            )
            return FlightDetailResponse.model_validate(value)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except (ValueError, CataloguePageOutOfRange) as error:
            raise HTTPException(400, str(error)) from error

    @router.get("/api/flight-selection")
    def flight_selection(
        filters: Annotated[FlightFilterRequest, Query()],
    ) -> FlightSelectionResponse:
        try:
            value = flight_workbench.filtered_keys(_flight_filter(filters))
            return FlightSelectionResponse.model_validate(value)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.get("/api/flights/{flight_key}/geometry")
    def flight_geometry(flight_key: str) -> FlightGeometryResponse:
        try:
            return FlightGeometryResponse.model_validate(flight_workbench.geometry(flight_key))
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @router.post("/api/matches")
    def match_flights(item: MatchFlightsRequest) -> MatchSubmissionResponse:
        try:
            return MatchSubmissionResponse.model_validate(
                flight_workbench.submit(item.flight_keys, force=item.force)
            )
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.get("/api/matches")
    def match_status(
        task_id: Annotated[list[str] | None, Query()] = None,
        include_items: bool = True,
        flight_key: Annotated[list[str] | None, Query()] = None,
    ) -> MatchStatusResponse:
        return MatchStatusResponse.model_validate(
            flight_workbench.task_status(
                task_id,
                include_items=include_items,
                flight_keys=flight_key,
            )
        )

    return router
