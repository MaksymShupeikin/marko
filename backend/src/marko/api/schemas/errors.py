"""Shared runtime error contract exposed to API clients through OpenAPI."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ValidationIssue(BaseModel):
    type: str
    loc: list[str | int] = Field(default_factory=list)
    msg: str

    model_config = ConfigDict(extra="allow")


class StructuredErrorDetail(BaseModel):
    code: str | None = None
    message: str | None = None
    required_roles: list[str] | None = None
    actual_role: str | None = None
    verdict: str | None = None
    reference: str | None = None

    model_config = ConfigDict(extra="allow")


class ErrorEnvelope(BaseModel):
    detail: str | StructuredErrorDetail | list[ValidationIssue]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "detail": {
                        "code": "INSUFFICIENT_WORKSPACE_ROLE",
                        "required_roles": ["owner", "admin"],
                        "actual_role": "member",
                    }
                }
            ]
        }
    )


_DESCRIPTIONS: dict[int, str] = {
    401: "Authentication is missing or invalid.",
    403: "The authenticated workspace role cannot perform this operation.",
    404: "The workspace-scoped resource does not exist.",
    409: "The request conflicts with workflow or source-access state.",
    415: "The uploaded media type is not supported.",
    422: "The request or domain input failed validation.",
    500: "The server could not complete the request.",
    503: "A required service or configuration is unavailable.",
}


def error_responses(*status_codes: int) -> dict[int, dict[str, Any]]:
    return {
        status_code: {
            "model": ErrorEnvelope,
            "description": _DESCRIPTIONS[status_code],
            # Error handlers always return JSON, including for endpoints whose
            # successful response is text/plain (Prometheus exposition).
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                }
            },
        }
        for status_code in status_codes
    }


__all__ = [
    "ErrorEnvelope",
    "StructuredErrorDetail",
    "ValidationIssue",
    "error_responses",
]
