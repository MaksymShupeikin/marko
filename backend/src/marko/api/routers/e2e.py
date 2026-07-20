"""Routes compiled into the API only for the isolated disposable E2E stack."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import WorkspaceAdmin, get_session
from marko.api.schemas.pricing import PricingRunResponse
from marko.services.pricing_runs import (
    PricingRunError,
    PricingTaskDispatchError,
    create_pricing_run,
)
from marko.worker.celery_app import celery_app


router = APIRouter()


class E2ePricingRunCreateRequest(BaseModel):
    import_batch_id: UUID
    policy: dict[str, Any] | None = None


@router.post(
    "/pricing/runs",
    response_model=PricingRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_fixture_replay_pricing_run(
    payload: E2ePricingRunCreateRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PricingRunResponse:
    """Create a real queued run whose acquisition lane accepts only seeded replay."""

    try:
        run = await create_pricing_run(
            session,
            workspace_id=current.workspace_id,
            import_batch_id=payload.import_batch_id,
            celery_app=celery_app,
            policy_config=payload.policy,
            source_mode="e2e_fixture_replay",
        )
    except PricingTaskDispatchError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PricingRunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PricingRunResponse.model_validate(run)
