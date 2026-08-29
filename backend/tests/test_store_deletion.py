from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from marko.services import stores


async def test_delete_store_removes_marketplace_store(monkeypatch):
    store_id = uuid4()
    marketplace_store = SimpleNamespace(id=store_id)
    session = AsyncMock()
    session.get.return_value = marketplace_store
    monkeypatch.setattr(
        stores,
        "_get_workspace_store",
        AsyncMock(return_value=SimpleNamespace(store_id=store_id)),
    )

    await stores.delete_store(
        session,
        store_id=store_id,
        workspace_id=uuid4(),
    )

    session.delete.assert_awaited_once_with(marketplace_store)
    session.commit.assert_awaited_once()


async def test_delete_store_rejects_store_from_another_workspace(monkeypatch):
    session = AsyncMock()
    monkeypatch.setattr(
        stores.stores_repo,
        "get_workspace_store",
        AsyncMock(return_value=None),
    )

    with pytest.raises(stores.StoreNotFoundError):
        await stores.delete_store(
            session,
            store_id=uuid4(),
            workspace_id=uuid4(),
        )

    session.commit.assert_not_awaited()


async def test_register_store_persists_permanent_seller_exclusion(monkeypatch):
    workspace_id = uuid4()
    store_id = uuid4()
    sync_run = SimpleNamespace(id=uuid4())
    session = AsyncMock()

    monkeypatch.setattr(
        stores.stores_repo,
        "upsert_marketplace_store",
        AsyncMock(return_value=store_id),
    )
    monkeypatch.setattr(
        stores.stores_repo,
        "upsert_workspace_store",
        AsyncMock(),
    )
    exclusion = AsyncMock()
    monkeypatch.setattr(
        stores.stores_repo,
        "upsert_competitor_seller_exclusion",
        exclusion,
    )
    monkeypatch.setattr(
        stores,
        "_get_or_create_sync_run",
        AsyncMock(return_value=(sync_run, False)),
    )

    result = await stores.register_store(
        session,
        url="https://prom.ua/ua/c9876543-my-shop.html",
        workspace_id=workspace_id,
        celery_app=SimpleNamespace(),
    )

    assert result == (store_id, sync_run)
    exclusion.assert_awaited_once_with(
        session,
        workspace_id=workspace_id,
        marketplace="prom",
        external_id="9876543",
        slug="my-shop",
        canonical_url="https://prom.ua/ua/c9876543-my-shop.html",
    )


async def test_delete_file_products_removes_only_export_listings(monkeypatch):
    """Файл перестає бути референсом: його рядки йдуть, Prom-товари лишаються."""
    store_id = uuid4()
    session = AsyncMock()
    delete_export = AsyncMock(return_value=4901)
    monkeypatch.setattr(
        stores,
        "_get_workspace_store",
        AsyncMock(return_value=SimpleNamespace(store_id=store_id)),
    )
    monkeypatch.setattr(
        stores.listings_repo, "delete_export_listings_for_store", delete_export
    )

    deleted = await stores.delete_store_file_products(
        session,
        store_id=store_id,
        workspace_id=uuid4(),
    )

    assert deleted == 4901
    delete_export.assert_awaited_once_with(session, store_id)
    session.commit.assert_awaited_once()


async def test_delete_file_products_rejects_foreign_workspace(monkeypatch):
    session = AsyncMock()
    monkeypatch.setattr(
        stores.stores_repo,
        "get_workspace_store",
        AsyncMock(return_value=None),
    )
    delete_export = AsyncMock()
    monkeypatch.setattr(
        stores.listings_repo, "delete_export_listings_for_store", delete_export
    )

    with pytest.raises(stores.StoreNotFoundError):
        await stores.delete_store_file_products(
            session,
            store_id=uuid4(),
            workspace_id=uuid4(),
        )

    delete_export.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_store_view_carries_the_file_product_count():
    """Лічильник «з файлу» доїжджає до відповіді API — фронт малює картку."""
    store = SimpleNamespace(
        id=uuid4(),
        marketplace="prom",
        external_id="2847093",
        name="kemp",
        canonical_url="https://prom.ua/ua/c2847093-kemp.html",
        logo_url=None,
        last_synced_at=None,
    )
    from marko.infrastructure.db.models import StoreKind

    view = stores._store_view(store, StoreKind.owned, 14120, 4901)

    assert view.product_count == 14120
    assert view.file_product_count == 4901
    # Роут будує відповідь через StoreResponse(**view.__dict__).
    from marko.api.schemas.stores import StoreResponse

    assert StoreResponse(**view.__dict__).file_product_count == 4901
