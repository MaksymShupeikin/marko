"""Liveness and dependency readiness endpoints."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import get_session
from marko.services.schema_state import schema_revision_status
from marko.services.source_access import source_access_status

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class SchemaRevisionResponse(BaseModel):
    code_head: str | None
    database_revision: str | None
    in_sync: bool


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
    revisions = await schema_revision_status(session)
    if not revisions.in_sync:
        # A stale image against an older volume used to report healthy while the
        # code described a schema the database did not have (F2-0015).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SCHEMA_REVISION_MISMATCH",
                "message": (
                    "Database schema revision does not match the migration head "
                    "shipped with this build"
                ),
                **revisions.as_dict(),
            },
        )
    return HealthResponse()


@router.get("/schema-revision", response_model=SchemaRevisionResponse)
async def schema_revision(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SchemaRevisionResponse:
    """Report the revision drift explicitly, so an operator can see the pair."""

    return SchemaRevisionResponse.model_validate(
        (await schema_revision_status(session)).as_dict()
    )
