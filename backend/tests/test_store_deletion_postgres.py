"""PostgreSQL proof that store removal clears only its workspace read models."""

from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from marko.infrastructure.db.models import (
    AttentionItem,
    CatalogProduct,
    Listing,
    MarketplaceStore,
    StoreKind,
    SyncRun,
    SyncStatus,
    Workspace,
    WorkspaceStore,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.stores import delete_owned_store


pytestmark = pytest.mark.postgres


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_store_delete_cascades_catalog_and_attention_without_cross_tenant_loss() -> None:
    workspace_id = uuid4()
    other_workspace_id = uuid4()
    store_id = uuid4()
    listing_id = uuid4()
    removed_product_id = uuid4()
    retained_product_id = uuid4()
    removed_attention_id = uuid4()
    retained_attention_id = uuid4()
    sync_run_id = uuid4()

    async with async_session_factory() as session:
        session.add_all(
            [
                Workspace(
                    id=workspace_id,
                    name="Store deletion test",
                    slug=f"store-delete-{workspace_id.hex}",
                ),
                Workspace(
                    id=other_workspace_id,
                    name="Store deletion neighbour",
                    slug=f"store-delete-{other_workspace_id.hex}",
                ),
                MarketplaceStore(
                    id=store_id,
                    marketplace="prom",
                    external_id=f"delete-{store_id.hex}",
                    name="Shared Prom store",
                    canonical_url=f"https://{store_id.hex}.prom.ua",
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                WorkspaceStore(
                    workspace_id=workspace_id,
                    store_id=store_id,
                    kind=StoreKind.owned,
                ),
                WorkspaceStore(
                    workspace_id=other_workspace_id,
                    store_id=store_id,
                    kind=StoreKind.owned,
                ),
                Listing(
                    id=listing_id,
                    store_id=store_id,
                    external_id=f"listing-{listing_id.hex}",
                    name="Store product",
                    url=f"https://prom.ua/p{listing_id.hex}.html",
                    sku="DELETE-STORE-SKU",
                    currency="UAH",
                    current_price=Decimal("100"),
                    is_available=True,
                    raw_data={},
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                CatalogProduct(
                    id=removed_product_id,
                    workspace_id=workspace_id,
                    source_kind="PROM_STORE",
                    source_id=store_id,
                    source_product_id="owned-product",
                    listing_id=listing_id,
                    name="Removed product",
                    currency="UAH",
                    current_price=Decimal("100"),
                    identity_status="UNRESOLVED",
                    raw_data={},
                ),
                CatalogProduct(
                    id=retained_product_id,
                    workspace_id=other_workspace_id,
                    source_kind="PROM_STORE",
                    source_id=store_id,
                    source_product_id="other-product",
                    listing_id=listing_id,
                    name="Retained product",
                    currency="UAH",
                    current_price=Decimal("100"),
                    identity_status="UNRESOLVED",
                    raw_data={},
                ),
                SyncRun(
                    id=sync_run_id,
                    workspace_id=workspace_id,
                    store_id=store_id,
                    kind="catalog_import",
                    status=SyncStatus.running,
                    scrape_state="running",
                    scrape_owner_task_id="store-delete-worker",
                    scrape_fencing_token=7,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                AttentionItem(
                    id=removed_attention_id,
                    workspace_id=workspace_id,
                    product_id=removed_product_id,
                    status="OVERPRICED",
                    severity=75,
                    review_state="OPEN",
                ),
                AttentionItem(
                    id=retained_attention_id,
                    workspace_id=other_workspace_id,
                    product_id=retained_product_id,
                    status="UNDERPRICED",
                    severity=25,
                    review_state="OPEN",
                ),
            ]
        )
        await session.commit()

    try:
        async with async_session_factory() as session:
            await delete_owned_store(
                session,
                store_id=store_id,
                workspace_id=workspace_id,
            )

        async with async_session_factory() as session:
            assert await session.get(CatalogProduct, removed_product_id) is None
            assert await session.get(AttentionItem, removed_attention_id) is None
            assert await session.get(CatalogProduct, retained_product_id) is not None
            assert await session.get(AttentionItem, retained_attention_id) is not None
            assert await session.get(Listing, listing_id) is not None

            removed_link = await session.scalar(
                select(WorkspaceStore).where(
                    WorkspaceStore.workspace_id == workspace_id,
                    WorkspaceStore.store_id == store_id,
                )
            )
            retained_link = await session.scalar(
                select(WorkspaceStore).where(
                    WorkspaceStore.workspace_id == other_workspace_id,
                    WorkspaceStore.store_id == store_id,
                )
            )
            sync_run = await session.get(SyncRun, sync_run_id)
            assert removed_link is None
            assert retained_link is not None
            assert sync_run is not None
            assert sync_run.scrape_state == "cancelled"
            assert sync_run.scrape_fencing_token == 8
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(Workspace).where(
                    Workspace.id.in_([workspace_id, other_workspace_id])
                )
            )
            await session.execute(delete(Listing).where(Listing.id == listing_id))
            await session.execute(
                delete(MarketplaceStore).where(MarketplaceStore.id == store_id)
            )
            await session.commit()
