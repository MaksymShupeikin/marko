"""Database queries for repricing runs and their rows."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Sequence

from sqlalchemy import Select, and_, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    RepriceItemStatus,
    RepriceOutcome,
    RepriceRun,
    RepriceRunItem,
    SyncRun,
    WorkspaceListingOverride,
)


async def covered_listing_ids(
    session: AsyncSession, workspace_id: uuid.UUID, signature: str
) -> set[uuid.UUID]:
    """Товари, які вже пораховано під цим складом каталогу.

    Покриття живе не окремою таблицею, а цим запитом: рядок прогону з тією
    самою підписою і є доказом, що товар уже проходили. Тому «продовжити»
    працює й через кілька прогонів, і після перезапуску воркера.
    """
    statement = (
        select(RepriceRunItem.listing_id)
        .join(RepriceRun, RepriceRun.id == RepriceRunItem.run_id)
        .where(
            RepriceRun.workspace_id == workspace_id,
            RepriceRun.catalog_scope_signature == signature,
            RepriceRunItem.status == RepriceItemStatus.done,
        )
        .distinct()
    )
    return set((await session.execute(statement)).scalars().all())


async def create_run(session: AsyncSession, run: RepriceRun) -> RepriceRun:
    session.add(run)
    return run


async def get_run(
    session: AsyncSession, run_id: uuid.UUID, workspace_id: uuid.UUID
) -> RepriceRun | None:
    return await session.scalar(
        select(RepriceRun).where(
            RepriceRun.id == run_id, RepriceRun.workspace_id == workspace_id
        )
    )


async def get_run_by_sync_run(
    session: AsyncSession, sync_run_id: uuid.UUID
) -> RepriceRun | None:
    return await session.scalar(
        select(RepriceRun).where(RepriceRun.sync_run_id == sync_run_id)
    )


async def list_runs(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[tuple[RepriceRun, SyncRun | None]]:
    """Історія прогонів: свіжі зверху, разом зі станом їхньої фонової задачі."""
    statement = (
        select(RepriceRun, SyncRun)
        .outerjoin(SyncRun, SyncRun.id == RepriceRun.sync_run_id)
        .where(RepriceRun.workspace_id == workspace_id)
        .order_by(RepriceRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(statement)).tuples().all())


async def count_runs(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(RepriceRun)
            .where(RepriceRun.workspace_id == workspace_id)
        )
    ) or 0


async def insert_items(
    session: AsyncSession, rows: Sequence[dict[str, Any]]
) -> None:
    """Bulk insert of the plan: ORM-обʼєкти тут були б на порядок повільніші."""
    if not rows:
        return
    await session.execute(insert(RepriceRunItem), list(rows))


async def next_pending_items(
    session: AsyncSession, run_id: uuid.UUID, *, limit: int
) -> list[RepriceRunItem]:
    """Наступна порція плану — строго в порядку, який зафіксував запуск."""
    return list(
        (
            await session.execute(
                select(RepriceRunItem)
                .where(
                    RepriceRunItem.run_id == run_id,
                    RepriceRunItem.status == RepriceItemStatus.pending,
                )
                .order_by(RepriceRunItem.position.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


def _items_query(run_id: uuid.UUID, workspace_id: uuid.UUID) -> Select:
    return (
        select(RepriceRunItem, Listing, MarketplaceStore, WorkspaceListingOverride)
        .join(Listing, Listing.id == RepriceRunItem.listing_id)
        .outerjoin(MarketplaceStore, MarketplaceStore.id == Listing.store_id)
        # Правки каталогу лежать парою (workspace_id, listing_id) — без
        # першої половини сюди приїхала б назва з чужого воркспейсу.
        .outerjoin(
            WorkspaceListingOverride,
            and_(
                WorkspaceListingOverride.listing_id == Listing.id,
                WorkspaceListingOverride.workspace_id == workspace_id,
            ),
        )
        .where(RepriceRunItem.run_id == run_id)
    )


def _apply_item_filters(
    statement: Select,
    *,
    outcome: RepriceOutcome | None,
    include_dismissed: bool,
) -> Select:
    if outcome is not None:
        statement = statement.where(RepriceRunItem.outcome == outcome)
    if not include_dismissed:
        statement = statement.where(RepriceRunItem.dismissed_at.is_(None))
    return statement


async def list_items(
    session: AsyncSession,
    run_id: uuid.UUID,
    workspace_id: uuid.UUID,
    *,
    outcome: RepriceOutcome | None = None,
    include_dismissed: bool = False,
    limit: int = 60,
    offset: int = 0,
) -> list[tuple[RepriceRunItem, Listing, MarketplaceStore | None, Any]]:
    statement = _apply_item_filters(
        _items_query(run_id, workspace_id),
        outcome=outcome,
        include_dismissed=include_dismissed,
    )
    # Найбільші рухи ціни — зверху: саме їх людина має побачити першими.
    statement = statement.order_by(
        func.abs(func.coalesce(RepriceRunItem.delta_pct, 0)).desc(),
        RepriceRunItem.position.asc(),
    )
    rows = (await session.execute(statement.limit(limit).offset(offset))).tuples().all()
    return list(rows)


async def count_items(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    outcome: RepriceOutcome | None = None,
    include_dismissed: bool = False,
) -> int:
    statement = _apply_item_filters(
        select(func.count())
        .select_from(RepriceRunItem)
        .where(RepriceRunItem.run_id == run_id),
        outcome=outcome,
        include_dismissed=include_dismissed,
    )
    return (await session.scalar(statement)) or 0


async def set_item_dismissed(
    session: AsyncSession,
    run_id: uuid.UUID,
    listing_id: uuid.UUID,
    *,
    dismissed: bool,
) -> bool:
    """Ховає рядок зі звіту або повертає його. Товар у каталозі не чіпаємо."""
    result = await session.execute(
        update(RepriceRunItem)
        .where(
            RepriceRunItem.run_id == run_id,
            RepriceRunItem.listing_id == listing_id,
        )
        .values(dismissed_at=datetime.now(UTC) if dismissed else None)
    )
    return bool(result.rowcount)


async def items_for_export(
    session: AsyncSession, run_id: uuid.UUID, workspace_id: uuid.UUID
) -> Sequence[tuple[RepriceRunItem, Listing, MarketplaceStore | None, Any]]:
    """Everything the Excel sheet needs, dismissed rows already left out."""
    statement = _apply_item_filters(
        _items_query(run_id, workspace_id), outcome=None, include_dismissed=False
    ).order_by(RepriceRunItem.position.asc())
    return (await session.execute(statement)).tuples().all()
