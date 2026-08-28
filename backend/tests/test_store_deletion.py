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
