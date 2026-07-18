"""Liveness and dependency readiness endpoints."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import get_session
from marko.services.source_access import source_access_status

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class SourceAccessResponse(BaseModel):
    source: str
    verdict: str
    reference: str | None
    live_collection_allowed: bool


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse()


@router.get("/source-access", response_model=SourceAccessResponse)
async def source_access() -> SourceAccessResponse:
    return SourceAccessResponse.model_validate(source_access_status().as_dict())


@router.get("/ready", response_model=HealthResponse)
async def ready(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc
    return HealthResponse()
