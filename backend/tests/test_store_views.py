from __future__ import annotations

from uuid import uuid4

import pytest

import marko.repositories.stores as stores_repo
from marko.infrastructure.db.models import MarketplaceStore, StoreKind
from marko.services.stores import list_stores


@pytest.mark.asyncio
async def test_store_view_prefers_original_prom_name_from_listing_data(
    monkeypatch,
) -> None:
    store = MarketplaceStore(
        id=uuid4(),
        marketplace="prom",
        external_id="3325174",
        name="profparts",
        canonical_url="https://prom.ua/ua/c3325174-profparts.html",
    )

    async def fake_list_stores(_session, _workspace_id):
        return [(store, StoreKind.owned, 725, "ПРОФПАРТС")]

    monkeypatch.setattr(stores_repo, "list_stores", fake_list_stores)

    views = await list_stores(object(), uuid4())

    assert views[0].name == "ПРОФПАРТС"
    assert views[0].product_count == 725


@pytest.mark.asyncio
async def test_store_view_falls_back_to_registered_slug_without_listing_name(
    monkeypatch,
) -> None:
    store = MarketplaceStore(
        id=uuid4(),
        marketplace="prom",
        external_id="4015921",
        name="avtobust",
        canonical_url="https://prom.ua/ua/c4015921-avtobust.html",
    )

    async def fake_list_stores(_session, _workspace_id):
        return [(store, StoreKind.owned, 0, None)]

    monkeypatch.setattr(stores_repo, "list_stores", fake_list_stores)

    views = await list_stores(object(), uuid4())

    assert views[0].name == "avtobust"
