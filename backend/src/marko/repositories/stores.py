from __future__ import annotations

import hashlib
import uuid
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    StoreKind,
    SyncRun,
    SyncStatus,
    WorkspaceStore,
)


async def get_store_by_id(
    session: AsyncSession, store_id: uuid.UUID, workspace_id: uuid.UUID
) -> tuple[MarketplaceStore, StoreKind, int] | None:
    statement = (
        select(
            MarketplaceStore,
            WorkspaceStore.kind,
            func.count(Listing.id).label("product_count"),
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
) -> list[tuple[MarketplaceStore, StoreKind, int]]:
    statement = (
        select(
            MarketplaceStore,
            WorkspaceStore.kind,
            func.count(Listing.id).label("product_count"),
        )
        .join(WorkspaceStore, WorkspaceStore.store_id == MarketplaceStore.id)
        .outerjoin(Listing, Listing.store_id == MarketplaceStore.id)
        .where(WorkspaceStore.workspace_id == workspace_id)
        .group_by(MarketplaceStore.id, WorkspaceStore.kind)
        .order_by(MarketplaceStore.created_at.desc())
    )
    rows = (await session.execute(statement)).all()
    return [(row[0], row[1], row[2]) for row in rows]


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
