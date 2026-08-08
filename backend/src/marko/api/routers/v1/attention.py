"""The small daily-work API built over immutable pricing evidence."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, get_session
from marko.api.schemas.attention import (
    AttentionItemResponse,
    AttentionPageResponse,
    AttentionSummaryResponse,
)
from marko.services.attention import get_attention_summary, list_attention_items


router = APIRouter()

AttentionStatus = Literal[
    "OVERPRICED",
    "UNDERPRICED",
    "IN_MARKET",
    "REVIEW_REQUIRED",
    "NO_DATA",
    "PROCESSING",
]


@router.get("/summary", response_model=AttentionSummaryResponse)
async def attention_summary(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AttentionSummaryResponse:
    summary = await get_attention_summary(
        session,
        workspace_id=current.workspace_id,
    )
    return AttentionSummaryResponse.model_validate(summary)


@router.get("/items", response_model=AttentionPageResponse)
async def attention_items(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: AttentionStatus | None = None,
    q: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AttentionPageResponse:
    try:
        page = await list_attention_items(
            session,
            workspace_id=current.workspace_id,
            status=status,
            query=q,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AttentionPageResponse(
        items=[AttentionItemResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
