"""Store registration, catalog job dispatch, and read models."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    StoreKind,
    SyncRun,
    SyncStatus,
    WorkspaceStore,
)
from marko.services.parser_models import Seller
from marko.services.seller_exclusions import remember_prom_seller

import marko.repositories.stores as stores_repo
import marko.repositories.listings as listings_repo


class StoreNotFoundError(LookupError):
    pass


class SyncRunNotFoundError(LookupError):
    pass


class TaskDispatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoreView:
    id: UUID
    marketplace: str
    external_id: str
    name: str | None
    url: str
    logo_url: str | None
    kind: str
    product_count: int
    last_synced_at: datetime | None


@dataclass(frozen=True)
class ProductPage:
    items: list[Listing]
    total: int
    limit: int
    offset: int


async def register_store(
    session: AsyncSession,
    *,
    url: str,
    workspace_id: UUID,
    celery_app: Celery,
) -> tuple[UUID, SyncRun]:
    seller = Seller.from_url(url)
    store_id = await stores_repo.upsert_marketplace_store(
        session,
        workspace_id=workspace_id,
        marketplace="prom",
        external_id=seller.company_id,
        name=seller.slug,
        canonical_url=seller.listing_url,
    )

    await stores_repo.upsert_workspace_store(
        session,
        workspace_id=workspace_id,
        store_id=store_id,
        kind=StoreKind.owned,
    )
    await remember_prom_seller(
        session,
        workspace_id=workspace_id,
        seller=seller,
    )

    sync_run, created = await _get_or_create_sync_run(
        session, store_id=store_id, workspace_id=workspace_id
    )
    if created:
        await _dispatch_sync_run(session, sync_run, celery_app)
    return store_id, sync_run


async def queue_store_sync(
    session: AsyncSession,
    *,
    store_id: UUID,
    workspace_id: UUID,
    celery_app: Celery,
) -> SyncRun:
    await _get_workspace_store(session, store_id=store_id, workspace_id=workspace_id)
    sync_run, created = await _get_or_create_sync_run(
        session, store_id=store_id, workspace_id=workspace_id
    )
    if created:
        await _dispatch_sync_run(session, sync_run, celery_app)
    return sync_run


async def _get_or_create_sync_run(
    session: AsyncSession, *, store_id: UUID, workspace_id: UUID
) -> tuple[SyncRun, bool]:
    active = await stores_repo.get_active_sync_run(session, store_id, workspace_id)
    if active is not None:
        await session.commit()
        return active, False

    sync_run = await stores_repo.create_sync_run(
        session,
        workspace_id=workspace_id,
        store_id=store_id,
        kind="catalog_import",
        status=SyncStatus.queued,
    )
    await session.commit()
    await session.refresh(sync_run)
    return sync_run, True


async def _dispatch_sync_run(
    session: AsyncSession, sync_run: SyncRun, celery_app: Celery
) -> None:
    try:
        result = await asyncio.to_thread(
            celery_app.send_task,
            "marko.worker.import_store_catalog",
            args=[str(sync_run.id)],
        )
    except Exception as exc:
        sync_run.status = SyncStatus.failed
        sync_run.error = f"Could not enqueue catalog import: {exc}"[:4000]
        sync_run.finished_at = datetime.now(UTC)
        await session.commit()
        raise TaskDispatchError(sync_run.error) from exc

    sync_run.task_id = result.id
    await session.commit()


async def list_stores(session: AsyncSession, workspace_id: UUID) -> list[StoreView]:
    rows = await stores_repo.list_stores(session, workspace_id)
    return [_store_view(store, kind, product_count) for store, kind, product_count in rows]


async def get_store(
    session: AsyncSession, *, store_id: UUID, workspace_id: UUID
) -> StoreView:
    row = await stores_repo.get_store_by_id(session, store_id, workspace_id)
    if row is None:
        raise StoreNotFoundError(str(store_id))
    return _store_view(*row)


async def delete_store(
    session: AsyncSession,
    *,
    store_id: UUID,
    workspace_id: UUID,
) -> None:
    """Магазини тепер належать одному воркспейсу: видаляємо разом з лінком і лістингами."""
    await _get_workspace_store(session, store_id=store_id, workspace_id=workspace_id)
    store = await session.get(MarketplaceStore, store_id)
    if store is not None:
        await session.delete(store)
    await session.commit()


async def list_store_products(
    session: AsyncSession,
    *,
    store_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
) -> ProductPage:
    await _get_workspace_store(session, store_id=store_id, workspace_id=workspace_id)
    total = await listings_repo.count_listings_for_store(session, store_id)
    items = await listings_repo.list_listings_for_store(session, store_id, limit, offset)
    return ProductPage(items=items, total=total, limit=limit, offset=offset)


async def get_sync_run(
    session: AsyncSession, *, sync_run_id: UUID, workspace_id: UUID
) -> SyncRun:
    sync_run = await stores_repo.get_sync_run_by_id(session, sync_run_id, workspace_id)
    if sync_run is None:
        raise SyncRunNotFoundError(str(sync_run_id))
    return sync_run


async def list_active_sync_runs(
    session: AsyncSession, workspace_id: UUID
) -> list[SyncRun]:
    return await stores_repo.list_active_sync_runs(session, workspace_id)


async def cancel_sync_run(
    session: AsyncSession,
    *,
    sync_run_id: UUID,
    workspace_id: UUID,
    celery_app: Celery,
) -> SyncRun:
    """Stop a queued or running import and mark the run cancelled."""
    sync_run = await get_sync_run(
        session, sync_run_id=sync_run_id, workspace_id=workspace_id
    )
    if sync_run.status not in (SyncStatus.queued, SyncStatus.running):
        return sync_run

    if sync_run.task_id:
        # terminate вбиває вже запущену задачу; для черги достатньо revoke.
        await asyncio.to_thread(
            celery_app.control.revoke, sync_run.task_id, terminate=True
        )
    sync_run.status = SyncStatus.cancelled
    sync_run.finished_at = datetime.now(UTC)
    await session.commit()
    return sync_run


async def _get_workspace_store(
    session: AsyncSession, *, store_id: UUID, workspace_id: UUID
) -> WorkspaceStore:
    link = await stores_repo.get_workspace_store(session, store_id, workspace_id)
    if link is None:
        raise StoreNotFoundError(str(store_id))
    return link


def _store_view(
    store: MarketplaceStore, kind: StoreKind, product_count: int
) -> StoreView:
    return StoreView(
        id=store.id,
        marketplace=store.marketplace,
        external_id=store.external_id,
        name=store.name,
        url=store.canonical_url,
        logo_url=store.logo_url,
        kind=kind.value,
        product_count=product_count,
        last_synced_at=store.last_synced_at,
    )
