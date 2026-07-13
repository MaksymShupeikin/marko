"""Background job status endpoints."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, get_session
from marko.api.schemas.stores import SyncRunResponse
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from exc
    return SyncRunResponse.model_validate(sync_run)
