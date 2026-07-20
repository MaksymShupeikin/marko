"""Background job status endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, get_session
from marko.api.schemas.stores import SyncRunResponse
from marko.api.schemas.pricing import ScraperMetricsResponse
from marko.services.scraper_metrics import (
    get_store_sync_scraper_metrics,
    render_prometheus,
)
from marko.services.stores import SyncRunNotFoundError, get_sync_run

router = APIRouter()


@router.get("/{sync_run_id}", response_model=SyncRunResponse)
async def get_job(
    sync_run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> SyncRunResponse:
    try:
        sync_run = await get_sync_run(
            session,
            sync_run_id=sync_run_id,
            workspace_id=current.workspace_id,
        )
    except SyncRunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        ) from exc
    return SyncRunResponse.model_validate(sync_run)


@router.get(
    "/{sync_run_id}/scrape-metrics",
    response_model=ScraperMetricsResponse,
)
async def get_job_scrape_metrics(
    sync_run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
    arrival_rate_items_per_second: Annotated[float, Query(ge=0)] = 0.0,
    parallel_efficiency: Annotated[float, Query(gt=0, le=1)] = 1.0,
    database_write_capacity_per_second: Annotated[
        float | None,
        Query(gt=0),
    ] = None,
    queue_capacity_items_per_second: Annotated[
        float | None,
        Query(gt=0),
    ] = None,
) -> ScraperMetricsResponse:
    try:
        snapshot = await get_store_sync_scraper_metrics(
            session,
            workspace_id=current.workspace_id,
            sync_run_id=sync_run_id,
            arrival_rate_items_per_second=arrival_rate_items_per_second,
            parallel_efficiency=parallel_efficiency,
            database_write_capacity_per_second=(database_write_capacity_per_second),
            queue_capacity_items_per_second=queue_capacity_items_per_second,
        )
    except SyncRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    return ScraperMetricsResponse.model_validate(snapshot)


@router.get(
    "/{sync_run_id}/scrape-metrics/prometheus",
    response_class=PlainTextResponse,
)
async def get_job_scrape_metrics_prometheus(
    sync_run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> PlainTextResponse:
    try:
        snapshot = await get_store_sync_scraper_metrics(
            session,
            workspace_id=current.workspace_id,
            sync_run_id=sync_run_id,
        )
    except SyncRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    return PlainTextResponse(
        render_prometheus(snapshot),
        media_type="text/plain; version=0.0.4",
    )
