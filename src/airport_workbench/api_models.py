"""Shared request-independent API error contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ApiErrorCode(StrEnum):
    BAD_REQUEST = "bad_request"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    SERVICE_UNAVAILABLE = "service_unavailable"
    VALIDATION_ERROR = "validation_error"
    REVISION_CONFLICT = "revision_conflict"
    OBJECT_NOT_FOUND = "object_not_found"
    PAGE_OUT_OF_RANGE = "page_out_of_range"


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    context: dict[str, JsonValue] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: ErrorDetail


DEFAULT_ERROR_CODE = {
    400: ApiErrorCode.BAD_REQUEST,
    404: ApiErrorCode.NOT_FOUND,
    405: ApiErrorCode.METHOD_NOT_ALLOWED,
    422: ApiErrorCode.VALIDATION_ERROR,
    503: ApiErrorCode.SERVICE_UNAVAILABLE,
}


def error_detail(
    code: str | ApiErrorCode,
    message: str,
    context: Mapping[str, JsonValue] | None = None,
) -> ErrorDetail:
    return ErrorDetail(code=str(code), message=message, context=dict(context or {}))


def normalize_error_detail(status_code: int, detail: Any) -> ErrorDetail:
    """Normalize legacy HTTPException details at the one API error boundary."""
    default_code = DEFAULT_ERROR_CODE.get(status_code, ApiErrorCode.BAD_REQUEST)
    if isinstance(detail, ErrorDetail):
        return detail
    if isinstance(detail, Mapping):
        code = detail.get("code", default_code)
        message = detail.get("message")
        if message is not None:
            nested = detail.get("context")
            context = dict(nested) if isinstance(nested, Mapping) else {}
            context.update(
                {
                    str(key): value
                    for key, value in detail.items()
                    if key not in {"code", "message", "context"}
                }
            )
            return error_detail(str(code), str(message), context)
    return error_detail(default_code, str(detail))


ERROR_RESPONSES = {
    "default": {"model": ErrorResponse, "description": "Error response"},
    422: {"model": ErrorResponse, "description": "Request validation error"},
}
