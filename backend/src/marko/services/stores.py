"""Store registration, catalog job dispatch, and read models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    SyncRun,
    StoreKind,
    SyncStatus,
    WorkspaceStore,
)
from marko.core.config import get_settings
from marko.services.catalog_search import (
    MAX_CROSS_STORE_MATCHES,
    CrossStoreSearch,
    search_other_stores,
)
from marko.services.seller_url_resolver import resolve_prom_seller
from marko.services.source_access import require_live_prom_marketplace_collection
from marko.services.scraper_outbox import enqueue_dispatch, publish_dispatch

import marko.repositories.users as users_repo
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
    kind: str
    product_count: int
    last_synced_at: datetime | None


@dataclass(frozen=True)
class ProductPage:
    items: list[Listing]
    total: int
    limit: int
    offset: int
    query: str | None = None


async def register_store(
    session: AsyncSession,
    *,
    url: str,
    workspace_id: UUID,
    celery_app: Celery,
) -> tuple[UUID, SyncRun]:
    require_live_prom_marketplace_collection()
    seller = await resolve_prom_seller(url)
    await users_repo.ensure_default_workspace(session, workspace_id)

    store_id = await stores_repo.upsert_marketplace_store(
        session,
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

    sync_run, created, dispatch_id = await _get_or_create_sync_run(
        session, store_id=store_id, workspace_id=workspace_id
    )
    if created and dispatch_id is not None:
        await _dispatch_sync_run(session, dispatch_id, celery_app)
    return store_id, sync_run


async def queue_store_sync(
    session: AsyncSession,
    *,
    store_id: UUID,
    workspace_id: UUID,
    celery_app: Celery,
) -> SyncRun:
    await _get_workspace_store(session, store_id=store_id, workspace_id=workspace_id)
    require_live_prom_marketplace_collection()
    sync_run, created, dispatch_id = await _get_or_create_sync_run(
        session, store_id=store_id, workspace_id=workspace_id
    )
    if created and dispatch_id is not None:
        await _dispatch_sync_run(session, dispatch_id, celery_app)
    return sync_run


async def _get_or_create_sync_run(
    session: AsyncSession, *, store_id: UUID, workspace_id: UUID
) -> tuple[SyncRun, bool, UUID | None]:
    await stores_repo.lock_store_sync_scope(
        session,
        store_id=store_id,
        workspace_id=workspace_id,
    )
    # Re-check after taking the same lock used by deletion. A sync request that
    # observed the link just before deletion must not recreate the catalog.
    await _get_workspace_store(
        session,
        store_id=store_id,
        workspace_id=workspace_id,
    )
    active = await stores_repo.get_active_sync_run(session, store_id, workspace_id)
    if active is not None:
        active.scrape_deduplicated_submissions += 1
        await session.commit()
        return active, False, None

    store = await session.get(MarketplaceStore, store_id)
    if store is None:
        raise StoreNotFoundError(str(store_id))
    settings = get_settings()
    sync_run = await stores_repo.create_sync_run(
        session,
        workspace_id=workspace_id,
        store_id=store_id,
        kind="catalog_import",
        status=SyncStatus.queued,
    )
    sync_run.scrape_item_version = "store-sync-v1"
    sync_run.scrape_input_fingerprint = hashlib.sha256(
        f"store-sync-v1|{store.canonical_url}".encode()
    ).hexdigest()
    sync_run.scrape_state = "queued"
    sync_run.scrape_max_task_executions = max(
        1,
        settings.store_sync_max_task_executions,
    )
    sync_run.scrape_deadline_at = datetime.now(UTC) + timedelta(
        seconds=max(1, settings.store_sync_item_deadline_seconds)
    )
    sync_run.scrape_checkpoint = {
        "stage": "queued",
        "item_kind": "store_sync",
        "item_version": sync_run.scrape_item_version,
        "next_page": 1,
        "at": datetime.now(UTC).isoformat(),
    }
    dispatch = await enqueue_dispatch(
        session,
        event_key=f"store-sync:{sync_run.id}:start:v1",
        aggregate_type="sync_run",
        aggregate_id=sync_run.id,
        workspace_id=workspace_id,
        task_name="marko.worker.import_store_catalog",
        task_args=[str(sync_run.id)],
        queue="store-sync",
    )
    sync_run.task_id = dispatch.task_id
    await session.commit()
    await session.refresh(sync_run)
    return sync_run, True, dispatch.id


async def _dispatch_sync_run(
    session: AsyncSession, dispatch_id: UUID, celery_app: Celery
) -> None:
    await publish_dispatch(
        session,
        event_id=dispatch_id,
        celery_app=celery_app,
    )


async def list_stores(session: AsyncSession, workspace_id: UUID) -> list[StoreView]:
    rows = await stores_repo.list_stores(session, workspace_id)
    return [
        _store_view(store, kind, product_count, prom_store_name)
        for store, kind, product_count, prom_store_name in rows
    ]


async def get_store(
    session: AsyncSession, *, store_id: UUID, workspace_id: UUID
) -> StoreView:
    row = await stores_repo.get_store_by_id(session, store_id, workspace_id)
    if row is None:
        raise StoreNotFoundError(str(store_id))
    return _store_view(*row)


async def list_store_products(
    session: AsyncSession,
    *,
    store_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    query: str | None = None,
) -> ProductPage:
    await _get_workspace_store(session, store_id=store_id, workspace_id=workspace_id)
    total = await listings_repo.count_listings_for_store(session, store_id, query)
    items = await listings_repo.list_listings_for_store(
        session, store_id, limit, offset, query
    )
    return ProductPage(
        items=items, total=total, limit=limit, offset=offset, query=query
    )


async def search_store_neighbours(
    session: AsyncSession,
    *,
    store_id: UUID,
    workspace_id: UUID,
    query: str,
    limit: int = MAX_CROSS_STORE_MATCHES,
) -> CrossStoreSearch:
    """Replay a catalog query against every other store of the workspace."""

    await _get_workspace_store(session, store_id=store_id, workspace_id=workspace_id)
    return await search_other_stores(
        session,
        store_id=store_id,
        workspace_id=workspace_id,
        query=query,
        limit=limit,
    )


async def delete_owned_store(
    session: AsyncSession,
    *,
    store_id: UUID,
    workspace_id: UUID,
) -> None:
    await stores_repo.lock_store_sync_scope(
        session,
        store_id=store_id,
        workspace_id=workspace_id,
    )
    deleted = await stores_repo.delete_owned_workspace_store(
        session,
        store_id=store_id,
        workspace_id=workspace_id,
    )
    if not deleted:
        raise StoreNotFoundError(str(store_id))
    cancelled_at = datetime.now(UTC)
    await stores_repo.cancel_active_store_sync_runs(
        session,
        store_id=store_id,
        workspace_id=workspace_id,
        cancelled_at=cancelled_at,
    )
    await stores_repo.delete_workspace_store_catalog_products(
        session,
        store_id=store_id,
        workspace_id=workspace_id,
    )
    await session.commit()


async def get_sync_run(
    session: AsyncSession, *, sync_run_id: UUID, workspace_id: UUID
) -> SyncRun:
    sync_run = await stores_repo.get_sync_run_by_id(session, sync_run_id, workspace_id)
    if sync_run is None:
        raise SyncRunNotFoundError(str(sync_run_id))
    return sync_run


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
    prom_store_name: str | None,
) -> StoreView:
    original_name = (prom_store_name or "").strip() or store.name
    return StoreView(
        id=store.id,
        marketplace=store.marketplace,
        external_id=store.external_id,
        name=original_name,
        url=store.canonical_url,
        kind=kind.value,
        product_count=product_count,
        last_synced_at=store.last_synced_at,
    )
