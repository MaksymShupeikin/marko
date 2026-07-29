"""Operational dead-letter visibility and controlled replay."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, WorkspaceAdmin, get_session
from marko.api.schemas.operations import (
    DeadLetterPageResponse,
    DeadLetterReplayResponse,
    DeadLetterResponse,
)
from marko.services.dead_letters import (
    DeadLetterNotFoundError,
    DeadLetterReplayError,
    list_dead_letters,
    replay_dead_letter,
)
from marko.services.scraper_metrics import render_latest_operational_prometheus
from marko.worker.celery_app import celery_app

router = APIRouter()


@router.get(
    "/metrics/prometheus",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
async def get_internal_operational_metrics(
    _current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlainTextResponse:
    """Authenticated scrape target; the production edge may restrict it further."""

    return PlainTextResponse(
        await render_latest_operational_prometheus(session),
        media_type="text/plain; version=0.0.4",
    )


@router.get("/dead-letters", response_model=DeadLetterPageResponse)
async def get_dead_letters(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DeadLetterPageResponse:
    page = await list_dead_letters(
        session,
        workspace_id=current.workspace_id,
        limit=limit,
        offset=offset,
    )
    return DeadLetterPageResponse(
        items=[DeadLetterResponse(**entry.__dict__) for entry in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/dead-letters/{kind}/{dead_letter_id}/replay",
    response_model=DeadLetterReplayResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replay_failed_workflow(
    kind: Literal["store_sync", "pricing_target"],
    dead_letter_id: UUID,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeadLetterReplayResponse:
    try:
        replay = await replay_dead_letter(
            session,
            workspace_id=current.workspace_id,
            kind=kind,
            dead_letter_id=dead_letter_id,
            celery_app=celery_app,
        )
    except DeadLetterNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dead letter not found",
        ) from exc
    except DeadLetterReplayError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DEAD_LETTER_NOT_REPLAYABLE",
                "message": str(exc),
            },
        ) from exc
    return DeadLetterReplayResponse(**replay.__dict__)
