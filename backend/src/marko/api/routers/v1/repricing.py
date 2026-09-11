"""Catalog repricing: plan a run, follow it, and read its rows."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

import marko.repositories.repricing as repricing_repo
from marko.api.dependencies import CurrentUser, get_session
from marko.api.schemas.repricing import (
    CatalogSignatureResponse,
    ReconciliationResponse,
    RepriceItemDismissResponse,
    RepriceItemPageResponse,
    RepriceItemResponse,
    RepricePreviewRequest,
    RepricePreviewResponse,
    RepriceRunPageResponse,
    RepriceRunRequest,
    RepriceRunResponse,
)
from marko.infrastructure.db.models import (
    RepriceMode,
    RepriceOutcome,
    RepricePolicy,
    RepriceRun,
    RepriceScope,
    SyncRun,
)
from marko.services.repricing import (
    RepriceDispatchError,
    carry_over_coverage,
    catalog_signature,
    preview,
    queue_reprice,
    reconciliation,
)
from marko.services.repricing_export import export_filename, export_run
from marko.worker.celery_app import celery_app

router = APIRouter()


@router.post("/preview", response_model=RepricePreviewResponse)
async def reprice_preview(
    payload: RepricePreviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> RepricePreviewResponse:
    """Скільки товарів під фільтром, скільки вже пораховано, скільки лишилось."""
    result = await preview(
        session,
        current.workspace_id,
        payload.to_filter(),
        mode=RepriceMode(payload.mode),
    )
    return RepricePreviewResponse(
        catalog=CatalogSignatureResponse(
            signature=result.catalog.value,
            item_count=result.catalog.item_count,
            store_ids=list(result.catalog.store_ids),
        ),
        matching=result.matching,
        covered=result.covered,
        remaining=result.remaining,
        checks_left=result.checks_left,
        last_run_signature=result.last_run_signature,
        signature_changed=result.signature_changed,
    )


@router.get("/reconciliation", response_model=ReconciliationResponse)
async def reprice_reconciliation(
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> ReconciliationResponse:
    """Що з пораховного вціліло після зміни складу каталогу."""
    result = await reconciliation(session, current.workspace_id)
    return ReconciliationResponse(
        signature_changed=result.signature_changed,
        previous_signature=result.previous_signature,
        kept=result.kept,
        gone=result.gone,
        fresh=result.fresh,
    )


@router.post("/carry-over", response_model=RepriceRunResponse | None)
async def carry_over(
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> RepriceRunResponse | None:
    """Зараховує вцілілі товари під новий каталог, щоб не рахувати їх знову."""
    run = await carry_over_coverage(session, current.workspace_id)
    if run is None:
        return None
    return _run_response(run, None, current_signature=run.catalog_scope_signature)


@router.post("/runs", response_model=RepriceRunResponse, status_code=status.HTTP_201_CREATED)
async def start_reprice_run(
    payload: RepriceRunRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> RepriceRunResponse:
    try:
        run = await queue_reprice(
            session,
            current.workspace_id,
            payload.to_filter(),
            scope=RepriceScope(payload.scope),
            mode=RepriceMode(payload.mode),
            policy=RepricePolicy(payload.policy),
            requested_count=payload.count,
            celery_app=celery_app,
        )
    except RepriceDispatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    sync_run = await session.get(SyncRun, run.sync_run_id)
    return _run_response(run, sync_run, current_signature=run.catalog_scope_signature)


@router.get("/runs", response_model=RepriceRunPageResponse)
async def list_reprice_runs(
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RepriceRunPageResponse:
    """Історія прогонів: коли, по якому каталогу і що вийшло."""
    rows = await repricing_repo.list_runs(
        session, current.workspace_id, limit=limit, offset=offset
    )
    signature = await catalog_signature(session, current.workspace_id)
    return RepriceRunPageResponse(
        items=[
            _run_response(run, sync_run, current_signature=signature.value)
            for run, sync_run in rows
        ],
        total=await repricing_repo.count_runs(session, current.workspace_id),
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=RepriceRunResponse)
async def get_reprice_run(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> RepriceRunResponse:
    run = await _run_or_404(session, run_id, current.workspace_id)
    sync_run = await session.get(SyncRun, run.sync_run_id) if run.sync_run_id else None
    signature = await catalog_signature(session, current.workspace_id)
    return _run_response(run, sync_run, current_signature=signature.value)


@router.get("/runs/{run_id}/items", response_model=RepriceItemPageResponse)
async def list_reprice_items(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
    outcome: Literal["changed", "unchanged", "no_recommendation"] | None = None,
    include_dismissed: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 60,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RepriceItemPageResponse:
    await _run_or_404(session, run_id, current.workspace_id)
    selected = RepriceOutcome(outcome) if outcome else None
    rows = await repricing_repo.list_items(
        session,
        run_id,
        current.workspace_id,
        outcome=selected,
        include_dismissed=include_dismissed,
        limit=limit,
        offset=offset,
    )
    return RepriceItemPageResponse(
        items=[_item_response(*row) for row in rows],
        total=await repricing_repo.count_items(
            session,
            run_id,
            outcome=selected,
            include_dismissed=include_dismissed,
        ),
        limit=limit,
        offset=offset,
    )


XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


@router.get("/runs/{run_id}/export.xlsx")
async def export_reprice_run(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> StreamingResponse:
    """Прогін одним аркушем: у шапці — коли і по якому каталогу рахували."""
    run = await _run_or_404(session, run_id, current.workspace_id)
    buffer = await export_run(session, run, current.workspace_id)
    return StreamingResponse(
        buffer,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename(run)}"'
        },
    )


@router.post(
    "/runs/{run_id}/items/{listing_id}/dismiss",
    response_model=RepriceItemDismissResponse,
)
async def dismiss_reprice_item(
    run_id: UUID,
    listing_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
    dismissed: bool = True,
) -> RepriceItemDismissResponse:
    """Ховає рядок зі звіту або повертає його. Товар у каталозі лишається."""
    await _run_or_404(session, run_id, current.workspace_id)
    changed = await repricing_repo.set_item_dismissed(
        session, run_id, listing_id, dismissed=dismissed
    )
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Рядок не знайдено в цьому прогоні.",
        )
    await session.commit()
    return RepriceItemDismissResponse(listing_id=listing_id, dismissed=dismissed)


async def _run_or_404(
    session: AsyncSession, run_id: UUID, workspace_id: UUID
) -> RepriceRun:
    run = await repricing_repo.get_run(session, run_id, workspace_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Прогін не знайдено."
        )
    return run


def _run_response(
    run: RepriceRun, sync_run: SyncRun | None, *, current_signature: str
) -> RepriceRunResponse:
    return RepriceRunResponse(
        id=run.id,
        sync_run_id=run.sync_run_id,
        scope=run.scope.value,
        mode=run.mode.value,
        policy=run.policy.value,
        engine=run.engine,
        requested_count=run.requested_count,
        catalog=CatalogSignatureResponse(
            signature=run.catalog_scope_signature,
            item_count=run.catalog_item_count,
            store_ids=list(run.store_ids or []),
        ),
        catalog_is_current=run.catalog_scope_signature == current_signature,
        # Перенесення покриття не має фонової задачі — воно завершене
        # у той самий момент, коли створене.
        status=sync_run.status.value if sync_run is not None else "completed",
        progress_current=sync_run.progress_current if sync_run is not None else 0,
        progress_total=sync_run.progress_total if sync_run is not None else None,
        error=sync_run.error if sync_run is not None else None,
        changed_count=run.changed_count,
        unchanged_count=run.unchanged_count,
        skipped_count=run.skipped_count,
        failed_count=run.failed_count,
        created_at=run.created_at,
        started_at=sync_run.started_at if sync_run is not None else None,
        finished_at=sync_run.finished_at if sync_run is not None else None,
    )


def _item_response(item, listing, store, override) -> RepriceItemResponse:
    def effective(field: str):
        value = getattr(override, field, None) if override is not None else None
        return value if value is not None else getattr(listing, field, None)

    current_price = effective("current_price")
    return RepriceItemResponse(
        listing_id=item.listing_id,
        position=item.position,
        name=effective("name") or listing.name,
        sku=effective("sku"),
        brand=effective("brand"),
        store_name=store.name if store is not None else None,
        image_url=(
            override.image_url
            if override is not None and override.image_url
            else listing.image_url
        ),
        url=listing.url,
        currency=listing.currency,
        status=item.status.value,
        outcome=item.outcome.value if item.outcome else None,
        reason=item.reason,
        old_price=item.old_price,
        new_price=item.new_price,
        delta_abs=item.delta_abs,
        delta_pct=item.delta_pct,
        # Застарівання — по товару, а не по каталогу: підпис каталогу навмисно
        # не реагує на ціни, інакше «продовжити» ламалось би після кожного
        # оновлення.
        price_changed_since=(
            item.price_at_compute is not None
            and current_price is not None
            and current_price != item.price_at_compute
        ),
        zone=item.zone,
        tier=item.tier,
        method=item.method,
        confidence=item.confidence,
        offers_total=item.offers_total,
        evidence=item.evidence,
        computed_at=item.computed_at,
        dismissed=item.dismissed_at is not None,
    )
