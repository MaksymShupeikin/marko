"""Opt-in PostgreSQL integration coverage for store registration and outbox identity."""

from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from marko.api import main as api_main
from marko.api.dependencies import get_current_user
from marko.api.routers.v1 import stores as stores_router
from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    ScrapeDispatchOutbox,
    StoreKind,
    SyncRun,
    User,
    Workspace,
    WorkspaceRole,
    WorkspaceStore,
)
from marko.infrastructure.db.session import async_session_factory
from marko.repositories.listings import search_listings_in_other_stores
from marko.services import stores as stores_service
from marko.services.auth import AuthContext


pytestmark = pytest.mark.postgres


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_post_store_uses_one_non_null_sync_identity(monkeypatch) -> None:
    workspace_id = uuid4()
    workspace_slug = f"store-sync-test-{workspace_id.hex}"
    async with async_session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="Store sync integration test",
                slug=workspace_slug,
            )
        )
        await session.commit()

    auth = AuthContext(
        user=User(
            id=uuid4(),
            email=f"store-sync-{workspace_id.hex}@example.com",
            is_active=True,
        ),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.owner,
    )
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    monkeypatch.setattr(
        stores_service,
        "require_live_prom_marketplace_collection",
        lambda: None,
    )
    monkeypatch.setattr(stores_router, "celery_app", fake_celery)

    application = api_main.create_app()

    async def current_user_override() -> AuthContext:
        return auth

    application.dependency_overrides[get_current_user] = current_user_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            first = await client.post(
                "/api/v1/stores",
                json={"url": "https://prom.ua/ua/c2257594-pilot-avto.html"},
            )
            second = await client.post(
                "/api/v1/stores",
                json={"url": "https://prom.ua/ua/c2257594-pilot-avto.html"},
            )

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        first_body = first.json()
        second_body = second.json()
        assert first_body["sync_run_id"]
        assert second_body["sync_run_id"] == first_body["sync_run_id"]

        sync_run_id = first_body["sync_run_id"]
        sync_run_uuid = UUID(sync_run_id)
        async with async_session_factory() as session:
            sync_run = await session.get(SyncRun, sync_run_uuid)
            outbox = await session.scalar(
                select(ScrapeDispatchOutbox).where(
                    ScrapeDispatchOutbox.aggregate_id == sync_run_uuid
                )
            )
            assert sync_run is not None
            assert outbox is not None
            assert str(outbox.aggregate_id) == sync_run_id
            assert outbox.event_key == f"store-sync:{sync_run_id}:start:v1"
            assert outbox.task_args == [sync_run_id]
            assert sync_run.scrape_deduplicated_submissions == 1
        assert fake_celery.send_task.call_count == 1
    finally:
        application.dependency_overrides.clear()
        async with async_session_factory() as session:
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.commit()


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_cross_store_search_never_returns_a_foreign_workspace_listing() -> None:
    """F2-0103: два арендатора с одинаковым SKU не видят листинги друг друга.

    Дополняет инвариант формы SQL в ``test_catalog_search.py`` поведенческим
    доказательством на населённой базе: одинаковый артикул лежит в обоих
    воркспейсах, и поиск обязан вернуть только свой.
    """
    shared_sku = f"TENANT{uuid4().hex[:10].upper()}"
    own_ws, foreign_ws = uuid4(), uuid4()
    own_home, own_other, foreign_store = uuid4(), uuid4(), uuid4()

    def _store(store_id: UUID, slug: str) -> MarketplaceStore:
        return MarketplaceStore(
            id=store_id,
            marketplace="prom",
            external_id=f"ext-{slug}-{store_id.hex[:8]}",
            name=slug,
            canonical_url=f"https://prom.ua/ua/c{store_id.hex[:7]}-{slug}.html",
        )

    def _listing(store_id: UUID, label: str) -> Listing:
        return Listing(
            id=uuid4(),
            store_id=store_id,
            external_id=f"lst-{store_id.hex[:8]}",
            name=f"Амортизатор {label}",
            url=f"https://prom.ua/ua/p{store_id.hex[:9]}-{label}.html",
            sku=shared_sku,
            brand="KEMP",
            currency="UAH",
            current_price=Decimal("256.50"),
            is_available=True,
            raw_data={},
        )

    async with async_session_factory() as session:
        session.add_all(
            [
                Workspace(id=own_ws, name="own", slug=f"own-{own_ws.hex}"),
                Workspace(
                    id=foreign_ws, name="foreign", slug=f"foreign-{foreign_ws.hex}"
                ),
                _store(own_home, "own-home"),
                _store(own_other, "own-other"),
                _store(foreign_store, "foreign-store"),
            ]
        )
        await session.flush()
        session.add_all(
            [
                WorkspaceStore(
                    workspace_id=own_ws, store_id=own_home, kind=StoreKind.owned
                ),
                WorkspaceStore(
                    workspace_id=own_ws, store_id=own_other, kind=StoreKind.competitor
                ),
                WorkspaceStore(
                    workspace_id=foreign_ws,
                    store_id=foreign_store,
                    kind=StoreKind.owned,
                ),
                _listing(own_other, "own-neighbour"),
                _listing(foreign_store, "foreign-secret"),
            ]
        )
        await session.commit()

    try:
        async with async_session_factory() as session:
            found = await search_listings_in_other_stores(
                session,
                workspace_id=own_ws,
                excluded_store_id=own_home,
                identities=(shared_sku,),
                limit=24,
            )
            names = {listing.name for listing, _store_row in found}
            store_ids = {listing.store_id for listing, _store_row in found}

        assert names == {"Амортизатор own-neighbour"}
        assert foreign_store not in store_ids
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(Listing).where(Listing.sku == shared_sku))
            await session.execute(
                delete(WorkspaceStore).where(
                    WorkspaceStore.workspace_id.in_([own_ws, foreign_ws])
                )
            )
            await session.execute(
                delete(MarketplaceStore).where(
                    MarketplaceStore.id.in_([own_home, own_other, foreign_store])
                )
            )
            await session.execute(
                delete(Workspace).where(Workspace.id.in_([own_ws, foreign_ws]))
            )
            await session.commit()
