from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from marko.api.routers.v1 import avtopro, products
from marko.services.competitor_prices import (
    CompetitorPriceReport,
    MarketOffer,
    PartSearchQuery,
    SourceResult,
)
from marko.services.seller_exclusions import GLOBAL_PROM_SELLER_EXCLUSIONS


def _query(listing_id: str) -> PartSearchQuery:
    return PartSearchQuery(
        listing_id=listing_id,
        oem_numbers=("0451103316",),
        brand="Bosch",
        name="Фільтр масляний Bosch",
        source_url="",
        owner_seller_ids=tuple(
            item.external_id for item in GLOBAL_PROM_SELLER_EXCLUSIONS
        ),
        owner_seller_slugs=tuple(item.slug for item in GLOBAL_PROM_SELLER_EXCLUSIONS),
    )


def _payload(query: PartSearchQuery) -> dict:
    offer = MarketOffer(
        source="prom",
        title="External filter",
        price=Decimal("100"),
        currency="UAH",
        url="https://prom.ua/ua/p999-filter.html",
        seller="External",
    )
    return CompetitorPriceReport(
        query=query,
        sources=(SourceResult("prom", "Prom.ua", "ok", (offer,)),),
        observed_at=datetime.now(UTC),
    ).as_json()


async def test_manual_rest_and_sse_routes_load_the_same_exclusion_context(monkeypatch):
    workspace_id = uuid4()
    current = SimpleNamespace(workspace_id=workspace_id)
    session = object()
    loaded = AsyncMock(return_value=GLOBAL_PROM_SELLER_EXCLUSIONS)
    captured: list[PartSearchQuery] = []

    async def prices_for_query(query, **_kwargs):
        captured.append(query)
        return _payload(query)

    def stream(query, **_kwargs):
        captured.append(query)
        return "stream"

    monkeypatch.setattr(avtopro, "consume_check", AsyncMock())
    monkeypatch.setattr(avtopro, "load_prom_seller_exclusions", loaded)
    monkeypatch.setattr(avtopro, "competitor_prices_for_query", prices_for_query)
    monkeypatch.setattr(avtopro, "competitor_price_stream", stream)

    response = await avtopro.search_competitors(
        current=current,
        session=session,
        oem="0451103316",
        brand="Bosch",
    )
    stream_response = await avtopro.search_competitors_stream(
        current=current,
        session=session,
        oem="0451103316",
        brand="Bosch",
    )

    assert response.stats.offers_total == 1
    assert stream_response == "stream"
    assert loaded.await_count == 2
    assert all("2847093" in query.owner_seller_ids for query in captured)
    assert captured[0].owner_seller_ids == captured[1].owner_seller_ids


async def test_product_rest_and_sse_routes_use_workspace_scoped_query_loading(
    monkeypatch,
):
    workspace_id = uuid4()
    listing_id = uuid4()
    current = SimpleNamespace(workspace_id=workspace_id)
    session = object()
    query = _query(str(listing_id))
    listing_report = AsyncMock(return_value=_payload(query))
    listing_query = AsyncMock(return_value=query)
    streamed: list[PartSearchQuery] = []

    monkeypatch.setattr(products, "consume_check", AsyncMock())
    monkeypatch.setattr(products, "competitor_prices_for_listing", listing_report)
    monkeypatch.setattr(products, "listing_search_query", listing_query)
    monkeypatch.setattr(
        products,
        "competitor_price_stream",
        lambda received, **_kwargs: streamed.append(received) or "stream",
    )

    response = await products.competitor_prices(
        listing_id=listing_id,
        session=session,
        current=current,
    )
    stream_response = await products.competitor_prices_stream(
        listing_id=listing_id,
        session=session,
        current=current,
    )

    assert response.stats.offers_total == 1
    assert stream_response == "stream"
    listing_report.assert_awaited_once_with(
        session,
        workspace_id,
        listing_id,
        refresh=False,
    )
    listing_query.assert_awaited_once_with(session, workspace_id, listing_id)
    assert streamed == [query]
