"""Запит на повний доступ: користувач тисне «зв'яжіться зі мною», ми
фіксуємо це на воркспейсі й відкриваємо доступ вручну (has_free_access)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, get_session
from marko.services.billing import access_requested, request_full_access

router = APIRouter()


class AccessRequestStatus(BaseModel):
    requested: bool


@router.get("/access-request", response_model=AccessRequestStatus)
async def get_access_request(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AccessRequestStatus:
    return AccessRequestStatus(
        requested=await access_requested(session, current.workspace_id)
    )


@router.post("/access-request", response_model=AccessRequestStatus)
async def create_access_request(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AccessRequestStatus:
    await request_full_access(session, current.workspace_id)
    return AccessRequestStatus(requested=True)
