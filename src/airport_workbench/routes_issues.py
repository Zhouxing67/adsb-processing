"""HTTP routes for archived matching issues (public.match_issues)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .api_models import (
    MatchIssueKeysRequest,
    MatchIssueListResponse,
    MatchIssueMutationResponse,
)
from .flights import FlightWorkbench


def build_match_issues_router(flight_workbench: FlightWorkbench) -> APIRouter:
    router = APIRouter()

    @router.get("/api/match-issues")
    def match_issues_list() -> MatchIssueListResponse:
        return MatchIssueListResponse.model_validate(flight_workbench.list_issue_keys())

    @router.post("/api/match-issues")
    def add_match_issues(item: MatchIssueKeysRequest) -> MatchIssueMutationResponse:
        try:
            return MatchIssueMutationResponse.model_validate(
                flight_workbench.add_match_issues(item.flight_keys, reason=item.reason)
            )
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @router.post("/api/match-issues/remove")
    def remove_match_issues(item: MatchIssueKeysRequest) -> MatchIssueMutationResponse:
        try:
            return MatchIssueMutationResponse.model_validate(
                flight_workbench.remove_match_issues(item.flight_keys)
            )
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    return router
