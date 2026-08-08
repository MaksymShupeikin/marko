from __future__ import annotations

from datetime import datetime
import hashlib
import uuid
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    CatalogProduct,
    Listing,
    MarketplaceStore,
    StoreKind,
    SyncRun,
    SyncStatus,
    StoreSyncTaskExecution,
    WorkspaceStore,
)

async def get_store_by_id(
    session: AsyncSession, store_id: uuid.UUID, workspace_id: uuid.UUID
) -> tuple[MarketplaceStore, StoreKind, int, str | None] | None:
    statement = (
        select(
            MarketplaceStore,
            WorkspaceStore.kind,
            func.count(Listing.id).label("product_count"),
            func.max(Listing.raw_data["seller_name"].as_string()).label(
                "prom_store_name"
            ),
        )
        .join(WorkspaceStore, WorkspaceStore.store_id == MarketplaceStore.id)
        .outerjoin(Listing, Listing.store_id == MarketplaceStore.id)
        .where(
            WorkspaceStore.workspace_id == workspace_id,
            MarketplaceStore.id == store_id,
        )
        .group_by(MarketplaceStore.id, WorkspaceStore.kind)
    )
    row = (await session.execute(statement)).one_or_none()
    return row  # Returns a tuple (store, kind, product_count) or None


async def list_stores(
    session: AsyncSession, workspace_id: uuid.UUID
) -> list[tuple[MarketplaceStore, StoreKind, int, str | None]]:
    statement = (
        select(
            MarketplaceStore,
            WorkspaceStore.kind,
            func.count(Listing.id).label("product_count"),
            func.max(Listing.raw_data["seller_name"].as_string()).label(
                "prom_store_name"
            ),
        )
        .join(WorkspaceStore, WorkspaceStore.store_id == MarketplaceStore.id)
        .outerjoin(Listing, Listing.store_id == MarketplaceStore.id)
        .where(WorkspaceStore.workspace_id == workspace_id)
        .group_by(MarketplaceStore.id, WorkspaceStore.kind)
        .order_by(MarketplaceStore.created_at.desc())
    )
    rows = (await session.execute(statement)).all()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


async def upsert_marketplace_store(
    session: AsyncSession,
    *,
    marketplace: str,
    external_id: str,
    name: str | None,
    canonical_url: str,
) -> uuid.UUID:
    statement = (
        insert(MarketplaceStore)
        .values(
            id=uuid.uuid4(),
            marketplace=marketplace,
            external_id=external_id,
            name=name,
            canonical_url=canonical_url,
        )
        .on_conflict_do_update(
            constraint="uq_store_marketplace_external",
            set_={
                "canonical_url": canonical_url,
                "updated_at": func.now(),
            },
        )
        .returning(MarketplaceStore.id)
    )
    return (await session.execute(statement)).scalar_one()


async def upsert_workspace_store(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    store_id: uuid.UUID,
    kind: StoreKind,
) -> None:
    statement = (
        insert(WorkspaceStore)
        .values(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            store_id=store_id,
            kind=kind,
        )
        .on_conflict_do_update(
            constraint="uq_workspace_store",
            set_={
                "kind": kind,
                "updated_at": func.now(),
            },
        )
    )
    await session.execute(statement)


async def get_workspace_store(
    session: AsyncSession, store_id: uuid.UUID, workspace_id: uuid.UUID
) -> WorkspaceStore | None:
    return await session.scalar(
        select(WorkspaceStore).where(
            WorkspaceStore.store_id == store_id,
            WorkspaceStore.workspace_id == workspace_id,
        )
    )


async def delete_owned_workspace_store(
    session: AsyncSession,
    *,
    store_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> bool:
    result = await session.execute(
        delete(WorkspaceStore).where(
            WorkspaceStore.store_id == store_id,
            WorkspaceStore.workspace_id == workspace_id,
            WorkspaceStore.kind == StoreKind.owned,
        )
    )
    return result.rowcount > 0


async def cancel_active_store_sync_runs(
    session: AsyncSession,
    *,
    store_id: uuid.UUID,
    workspace_id: uuid.UUID,
    cancelled_at: datetime,
) -> int:
    """Fence active imports so a worker cannot recreate removed products."""

    active_conditions = (
        SyncRun.store_id == store_id,
        SyncRun.workspace_id == workspace_id,
        SyncRun.kind == "catalog_import",
        SyncRun.scrape_state.in_(("queued", "running", "retry_wait")),
    )
    result = await session.execute(
        update(SyncRun)
        .where(*active_conditions)
        .values(
            status=SyncStatus.failed,
            scrape_state="cancelled",
            scrape_owner_task_id=None,
            scrape_lease_expires_at=None,
            scrape_fencing_token=SyncRun.scrape_fencing_token + 1,
            error="Store removed from workspace",
            finished_at=cancelled_at,
            scrape_checkpoint={
                "stage": "cancelled",
                "reason": "store_removed",
                "at": cancelled_at.isoformat(),
            },
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount <= 0:
        return 0

    cancelled_run_ids = select(SyncRun.id).where(
        SyncRun.store_id == store_id,
        SyncRun.workspace_id == workspace_id,
        SyncRun.kind == "catalog_import",
        SyncRun.scrape_state == "cancelled",
    )
    await session.execute(
        update(StoreSyncTaskExecution)
        .where(
            StoreSyncTaskExecution.sync_run_id.in_(cancelled_run_ids),
            StoreSyncTaskExecution.outcome == "running",
        )
        .values(
            outcome="terminal_failure",
            error_category="store_removed",
            error_detail="Store removed from workspace",
            finished_at=cancelled_at,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


async def delete_workspace_store_catalog_products(
    session: AsyncSession,
    *,
    store_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> int:
    """Delete the workspace-visible store catalog and its cascaded attention."""

    result = await session.execute(
        delete(CatalogProduct).where(
            CatalogProduct.workspace_id == workspace_id,
            CatalogProduct.source_kind == "PROM_STORE",
            CatalogProduct.source_id == store_id,
        )
    )
    return result.rowcount


async def get_active_sync_run(
    session: AsyncSession, store_id: uuid.UUID, workspace_id: uuid.UUID
) -> SyncRun | None:
    return await session.scalar(
        select(SyncRun)
        .where(
            SyncRun.store_id == store_id,
            SyncRun.workspace_id == workspace_id,
            SyncRun.kind == "catalog_import",
            SyncRun.scrape_state.in_(("queued", "running", "retry_wait")),
        )
        .order_by(SyncRun.created_at.desc())
        .limit(1)
    )


async def lock_store_sync_scope(
    session: AsyncSession,
    *,
    store_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    """Serialize active-run creation for one workspace/store pair.

    The partial unique index remains the final DB invariant. The transaction
    advisory lock makes the normal get-or-create path deterministic and avoids
    using an exception as concurrency control.
    """

    digest = hashlib.blake2b(
        workspace_id.bytes + store_id.bytes,
        digest_size=8,
        person=b"markosyn",
    ).digest()
    lock_key = int.from_bytes(digest, byteorder="big", signed=True)
    await session.execute(select(func.pg_advisory_xact_lock(lock_key)))


async def create_sync_run(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    store_id: uuid.UUID,
    kind: str,
    status: SyncStatus = SyncStatus.queued,
) -> SyncRun:
    sync_run = SyncRun(
        workspace_id=workspace_id,
        store_id=store_id,
        kind=kind,
        status=status,
    )
    session.add(sync_run)
    # ``SyncRun.id`` uses a Python-side SQLAlchemy default, so it is not
    # populated until the pending row is flushed.  Callers construct the
    # transactional outbox identity from this UUID before committing; return
    # only after that identity is stable while keeping both rows in the same
    # transaction.
    await session.flush()
    return sync_run


async def get_sync_run_by_id(
    session: AsyncSession, sync_run_id: uuid.UUID, workspace_id: uuid.UUID
) -> SyncRun | None:
    return await session.scalar(
        select(SyncRun).where(
            SyncRun.id == sync_run_id,
            SyncRun.workspace_id == workspace_id,
        )
    )
