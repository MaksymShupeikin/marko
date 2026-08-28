from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from marko.api.routers.v1 import avtopro, products
from marko.services.competitor_prices import (
    CompetitorPriceReport,
    MarketOffer,
    SourceResult,
    manual_search_query,
)


def _report(query):
    offer = MarketOffer(
        source="prom",
        title="Фільтр Bosch 0451103316",
        price=Decimal("100"),
        currency="UAH",
        url="https://prom.ua/ua/p1-filter.html",
        seller="Market Seller",
    )
    return CompetitorPriceReport(
        query=query,
        sources=(SourceResult("prom", "Prom.ua", "ok", (offer,)),),
        observed_at=datetime.now(UTC),
    ).as_json()


async def test_manual_rest_and_sse_use_workspace_seller_exclusions(monkeypatch):
    workspace_id = uuid4()
    current = SimpleNamespace(workspace_id=workspace_id)
    session = object()
    exclusions = [
        SimpleNamespace(
            marketplace="prom",
            external_id="9876543",
            slug="my-shop",
        )
    ]
    list_exclusions = AsyncMock(return_value=exclusions)
    monkeypatch.setattr(
        avtopro.stores_repo,
        "list_competitor_seller_exclusions",
        list_exclusions,
    )
    monkeypatch.setattr(avtopro, "consume_check", AsyncMock())

    captured_rest = []

    async def fake_report(query, *, refresh=False):
        captured_rest.append((query, refresh))
        return _report(query)

    monkeypatch.setattr(avtopro, "competitor_prices_for_query", fake_report)

    await avtopro.search_competitors(
        current=current,
        session=session,
        oem="0451103316",
        brand="Bosch",
        refresh=True,
    )

    captured_sse = []
    sentinel = object()

    def fake_stream(query, *, refresh=False):
        captured_sse.append((query, refresh))
        return sentinel

    monkeypatch.setattr(avtopro, "competitor_price_stream", fake_stream)
    response = await avtopro.search_competitors_stream(
        current=current,
        session=session,
        oem="0451103316",
        brand="Bosch",
        refresh=True,
    )

    assert response is sentinel
    assert list_exclusions.await_count == 2
    for query, refresh in [*captured_rest, *captured_sse]:
        assert refresh is True
        assert "9876543" in query.owner_seller_ids
        assert "my-shop" in query.owner_seller_slugs
        assert "2847093" in query.owner_seller_ids


async def test_product_rest_and_sse_keep_the_filtered_query(monkeypatch):
    workspace_id = uuid4()
    listing_id = uuid4()
    current = SimpleNamespace(workspace_id=workspace_id)
    session = object()
    query = manual_search_query(
        "0451103316",
        "Bosch",
        seller_exclusions=[
            SimpleNamespace(
                marketplace="prom",
                external_id="9876543",
                slug="my-shop",
            )
        ],
    )
    report_call = AsyncMock(return_value=_report(query))
    monkeypatch.setattr(products, "competitor_prices_for_listing", report_call)
    monkeypatch.setattr(products, "consume_check", AsyncMock())

    await products.competitor_prices(
        listing_id=listing_id,
        session=session,
        current=current,
        refresh=True,
    )

    report_call.assert_awaited_once_with(
        session,
        workspace_id,
        listing_id,
        refresh=True,
    )

    monkeypatch.setattr(products, "listing_search_query", AsyncMock(return_value=query))
    captured = []
    sentinel = object()

    def fake_stream(filtered_query, *, refresh=False):
        captured.append((filtered_query, refresh))
        return sentinel

    monkeypatch.setattr(products, "competitor_price_stream", fake_stream)
    response = await products.competitor_prices_stream(
        listing_id=listing_id,
        session=session,
        current=current,
        refresh=True,
    )

    assert response is sentinel
    assert captured == [(query, True)]
    assert "9876543" in query.owner_seller_ids
