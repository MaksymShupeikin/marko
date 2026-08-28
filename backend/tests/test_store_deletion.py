from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from marko.services import stores
from marko.services.competitor_prices import _is_own_prom_product, manual_search_query
from marko.services.seller_exclusions import (
    SellerExclusion,
    merge_prom_seller_exclusions,
)


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


async def test_deleted_store_remains_excluded_from_competitor_offers(monkeypatch):
    store_id = uuid4()
    workspace_id = uuid4()
    marketplace_store = SimpleNamespace(id=store_id)
    exclusion = SellerExclusion(
        marketplace="prom",
        external_id="888",
        slug="dynamic-store",
        canonical_url="https://prom.ua/ua/c888-dynamic-store.html",
    )
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
        workspace_id=workspace_id,
    )
    query = manual_search_query(
        "0451103316",
        seller_exclusions=merge_prom_seller_exclusions([exclusion]),
    )

    assert _is_own_prom_product(
        query,
        SimpleNamespace(
            seller_id=888,
            seller_slug="dynamic-store",
            url="https://prom.ua/ua/p999-filter.html",
        ),
    )
    session.delete.assert_awaited_once_with(marketplace_store)


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
