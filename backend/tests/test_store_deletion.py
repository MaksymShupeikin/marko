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
