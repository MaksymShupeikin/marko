"""Operational dead-letter visibility and controlled replay."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import (
    CurrentUser,
    MetricsScraper,
    WorkspaceAdmin,
    get_session,
)
from marko.api.schemas.operations import (
    ClientErrorEventRequest,
    ClientErrorEventResponse,
    DeadLetterPageResponse,
    DeadLetterReplayResponse,
    DeadLetterResponse,
    DiscoveryFunnelResponse,
)
from metis.pricing.observability import pricing_event
from marko.services.dead_letters import (
    DeadLetterNotFoundError,
    DeadLetterReplayError,
    list_dead_letters,
    replay_dead_letter,
)
from marko.services.discovery_funnel import load_discovery_funnel
from marko.services.scraper_metrics import render_latest_operational_prometheus
from marko.worker.celery_app import celery_app

router = APIRouter()


@router.post(
    "/client-errors",
    response_model=ClientErrorEventResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def record_client_error(
    event: ClientErrorEventRequest,
    current: CurrentUser,
) -> ClientErrorEventResponse:
    """Accept an authenticated, privacy-safe client crash fingerprint."""

    pricing_event(
        "client_unhandled_error",
        workspace_id=str(current.workspace_id),
        user_id=str(current.user.id),
        event_id=event.event_id,
        error_kind=event.kind,
        exception_type=event.exception_type,
        message_fingerprint=event.message_fingerprint,
        stack_frames=event.stack_frames,
        route=event.route,
        client_correlation_id=event.correlation_id,
        release=event.release,
        occurred_at=event.occurred_at.isoformat(),
    )
    return ClientErrorEventResponse(status="accepted")


@router.get("/discovery-funnel", response_model=DiscoveryFunnelResponse)
async def get_discovery_funnel(
    request: Request,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    run_limit: Annotated[int, Query(ge=1, le=1000)] = 400,
    category_limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DiscoveryFunnelResponse:
    """Explain persisted candidate attrition without rerunning collection."""

    snapshot = await load_discovery_funnel(
        session,
        workspace_id=current.workspace_id,
        run_limit=run_limit,
        category_limit=category_limit,
    )
    return DiscoveryFunnelResponse(
        **snapshot.as_dict(
            correlation_id=getattr(request.state, "correlation_id", None)
        )
    )


@router.get(
    "/metrics/prometheus",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
async def get_internal_operational_metrics(
    _authorized: MetricsScraper,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlainTextResponse:
    """Authenticated scrape target; the production edge may restrict it further.

    Accepts either the internal ``OPERATIONAL_METRICS_TOKEN`` service credential
    used by Prometheus or a normal user JWT. Anonymous access stays refused.
    """

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
