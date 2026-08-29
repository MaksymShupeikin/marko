"""Store registration, catalog job dispatch, and read models."""
from __future__ import annotations

import logging

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

import marko.repositories.stores as stores_repo
import marko.repositories.listings as listings_repo


log = logging.getLogger(__name__)


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
    file_product_count: int
    last_synced_at: datetime | None


@dataclass(frozen=True)
class SyncRunView:
    """Запуск імпорту разом із магазином: рядок черги підписується його іменем."""

    sync_run: SyncRun
    store_name: str | None
    store_logo_url: str | None


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
    await stores_repo.upsert_competitor_seller_exclusion(
        session,
        workspace_id=workspace_id,
        marketplace="prom",
        external_id=seller.company_id,
        slug=seller.slug,
        canonical_url=seller.listing_url,
    )

    sync_run, created = await _get_or_create_sync_run(
        session, store_id=store_id, workspace_id=workspace_id
    )
    if created:
        await _dispatch_if_idle(session, sync_run, celery_app)
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
        await _dispatch_if_idle(session, sync_run, celery_app)
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


async def _dispatch_if_idle(
    session: AsyncSession, sync_run: SyncRun, celery_app: Celery
) -> None:
    """Віддати воркеру лише якщо в майстерні порожньо.

    Магазини імпортуються по одному: паралельні запуски ділять один канал до
    prom.ua і сповільнюють обидва. Решта чекає зі статусом queued і без
    task_id — саме за цією ознакою черга й рухається далі.
    """
    if await stores_repo.count_dispatched_sync_runs(session, sync_run.workspace_id):
        return
    await _dispatch_sync_run(session, sync_run, celery_app)


async def dispatch_next_queued(
    session: AsyncSession, workspace_id: UUID, celery_app: Celery
) -> SyncRun | None:
    """Пустити наступний імпорт у роботу: після завершення, скасування чи збою.

    Запуск, який не вдалося поставити в чергу, позначається помилкою — і ми
    беремо наступний, інакше одна мертва задача заморозила б усю чергу.
    """
    if await stores_repo.count_dispatched_sync_runs(session, workspace_id):
        return None
    while True:
        sync_run = await stores_repo.lock_next_queued_sync_run(session, workspace_id)
        if sync_run is None:
            await session.commit()
            return None
        try:
            await _dispatch_sync_run(session, sync_run, celery_app)
        except TaskDispatchError:
            continue
        return sync_run


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
    return [_store_view(*row) for row in rows]


async def get_store(
    session: AsyncSession, *, store_id: UUID, workspace_id: UUID
) -> StoreView:
    row = await stores_repo.get_store_by_id(session, store_id, workspace_id)
    if row is None:
        raise StoreNotFoundError(str(store_id))
    return _store_view(*row)


async def delete_store_file_products(
    session: AsyncSession,
    *,
    store_id: UUID,
    workspace_id: UUID,
) -> int:
    """Прибирає з каталогу товари, що приїхали з XLSX-файлу цього магазину.

    Після цього файл перестає бути референсом для пошуку: його рядків немає
    ні в каталозі, ні в запитах конкурентів. Prom-товари магазину і запис
    у реєстрі виключень продавців лишаються.
    """
    await _get_workspace_store(session, store_id=store_id, workspace_id=workspace_id)
    deleted = await listings_repo.delete_export_listings_for_store(session, store_id)
    await session.commit()
    log.info("Прибрано %d товарів із файлу магазину %s", deleted, store_id)
    return deleted


async def delete_store(
    session: AsyncSession,
    *,
    store_id: UUID,
    workspace_id: UUID,
) -> None:
    """Delete the catalog but retain its permanent competitor exclusion."""
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
    session: AsyncSession, workspace_id: UUID, celery_app: Celery | None = None
) -> list[SyncRunView]:
    """Черга імпортів; заразом лікує її, якщо голова чомусь не поїхала.

    Планувальника (celery beat) у проєкті немає, а фронт і так опитує цей
    список кожні дві секунди — тож саме тут найдешевше помітити, що ніхто
    не виконується, хоч у черзі хтось є (наприклад, воркер помер разом із
    задачею), і зрушити її.
    """
    if celery_app is not None:
        await dispatch_next_queued(session, workspace_id, celery_app)
    rows = await stores_repo.list_active_sync_runs(session, workspace_id)
    return [_sync_run_view(sync_run, store) for sync_run, store in rows]


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
    # Місце звільнилось — наступний магазин має рушити без чекання фронта.
    await dispatch_next_queued(session, workspace_id, celery_app)
    return sync_run


def _sync_run_view(sync_run: SyncRun, store: MarketplaceStore | None) -> SyncRunView:
    return SyncRunView(
        sync_run=sync_run,
        store_name=store.name if store else None,
        store_logo_url=store.logo_url if store else None,
    )


async def _get_workspace_store(
    session: AsyncSession, *, store_id: UUID, workspace_id: UUID
) -> WorkspaceStore:
    link = await stores_repo.get_workspace_store(session, store_id, workspace_id)
    if link is None:
        raise StoreNotFoundError(str(store_id))
    return link


def _store_view(
    store: MarketplaceStore,
    kind: StoreKind,
    product_count: int,
    file_product_count: int = 0,
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
        file_product_count=file_product_count,
        last_synced_at=store.last_synced_at,
    )
