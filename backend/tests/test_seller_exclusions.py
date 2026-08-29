from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import marko.services.catalog_import as catalog_import
import marko.services.competitor_prices as competitor_prices_module
import marko.services.stores as stores_service
from factories import product
from marko.services.competitor_prices import (
    PartSearchQuery,
    PromPriceSource,
    _cache_key,
    _is_own_prom_product,
)
from marko.services.parser_models import Seller
from marko.services.seller_exclusions import (
    GLOBAL_PROM_SELLER_EXCLUSIONS,
    SellerExclusion,
    load_prom_seller_exclusions,
    merge_prom_seller_exclusions,
    remember_prom_seller,
)


def _dynamic(external_id: str, slug: str) -> SellerExclusion:
    return SellerExclusion(
        marketplace="prom",
        external_id=external_id,
        slug=slug,
        canonical_url=f"https://prom.ua/ua/c{external_id}-{slug}.html",
    )


def test_global_exclusions_are_the_four_exact_parsed_sellers():
    parsed = [
        Seller.from_url(url)
        for url in (
            "https://prom.ua/ua/c2847093-kemp.html",
            "https://prom.ua/c4015921-avtobust.html",
            "https://prom.ua/ua/c3325174-profparts.html",
            "https://prom.ua/ua/c3912822-parts-avto.html",
        )
    ]

    assert [(seller.company_id, seller.slug) for seller in parsed] == [
        ("2847093", "kemp"),
        ("4015921", "avtobust"),
        ("3325174", "profparts"),
        ("3912822", "parts-avto"),
    ]


def test_prom_source_excludes_all_presets_and_keeps_external_seller():
    query = competitor_prices_module.manual_search_query(
        "0451103316",
        "Bosch",
        "Фільтр масляний Bosch",
        seller_exclusions=GLOBAL_PROM_SELLER_EXCLUSIONS,
    )
    companies = [
        {"id": 2847093, "name": "KEMP", "slug": "kemp"},
        {"id": 4015921, "name": "Avtobust", "slug": "avtobust"},
        {"id": 3325174, "name": "Profparts", "slug": "profparts"},
        {"id": 3912822, "name": "Parts Avto", "slug": "parts-avto"},
        {"id": 7777777, "name": "External", "slug": "external"},
    ]
    products = [
        product(
            id=index,
            name="Фільтр масляний Bosch 0451103316",
            sku="0451103316",
            price=str(100 + index),
            manufacturerInfo={"name": "Bosch"},
            company=company,
            urlText=f"filter-{index}",
        )
        for index, company in enumerate(companies, start=1)
    ]

    offers = list(PromPriceSource()._offers_from(query, products, "0451103316"))

    assert [(offer.seller, offer.price) for offer in offers] == [
        ("External", Decimal("105.00"))
    ]


def test_seller_identity_uses_id_then_slug_then_url_fallback():
    query = PartSearchQuery(
        listing_id="manual:part",
        oem_numbers=("0451103316",),
        brand="Bosch",
        name="Фільтр масляний Bosch",
        source_url="",
        owner_seller_ids=("2847093",),
        owner_seller_slugs=("kemp",),
    )

    assert not _is_own_prom_product(
        query,
        SimpleNamespace(
            seller_id=9999999,
            seller_slug="kemp",
            url="https://prom.ua/ua/p999-filter.html",
        ),
    )
    assert _is_own_prom_product(
        query,
        SimpleNamespace(
            seller_id=None,
            seller_slug="KEMP",
            url="https://prom.ua/ua/p999-filter.html",
        ),
    )
    assert _is_own_prom_product(
        query,
        SimpleNamespace(
            seller_id=None,
            seller_slug=None,
            url="https://kemp-cs2847093.prom.ua/p999-filter.html",
        ),
    )


def test_cache_key_is_v8_stable_and_changes_when_exclusion_is_added():
    fields = dict(
        listing_id="p1",
        oem_numbers=("0451103316",),
        brand="Bosch",
        name="Фільтр масляний Bosch",
        source_url="https://prom.ua/ua/p1-filter.html",
    )
    first = PartSearchQuery(
        **fields,
        owner_seller_ids=("4015921", "2847093"),
        owner_seller_slugs=("kemp", "avtobust"),
    )
    reordered = PartSearchQuery(
        **fields,
        owner_seller_ids=("2847093", "4015921"),
        owner_seller_slugs=("avtobust", "kemp"),
    )
    expanded = PartSearchQuery(
        **fields,
        owner_seller_ids=(*first.owner_seller_ids, "999"),
        owner_seller_slugs=(*first.owner_seller_slugs, "dynamic"),
    )

    assert _cache_key(first) == _cache_key(reordered)
    assert _cache_key(first) != _cache_key(expanded)
    assert _cache_key(first).startswith("competitor-prices:v8:")
    assert ":p1:" in _cache_key(first)


async def test_listing_query_loads_presets_and_workspace_exclusions(monkeypatch):
    workspace_id = uuid4()
    listing = SimpleNamespace(
        id=uuid4(),
        sku="0451103316",
        brand="Bosch",
        name="Фільтр масляний Bosch",
        url="https://prom.ua/ua/p1-filter.html",
        raw_data={},
    )
    dynamic = _dynamic("888", "dynamic-store")
    monkeypatch.setattr(
        competitor_prices_module,
        "get_workspace_listing",
        AsyncMock(return_value=listing),
    )
    load = AsyncMock(return_value=(*GLOBAL_PROM_SELLER_EXCLUSIONS, dynamic))
    monkeypatch.setattr(
        competitor_prices_module,
        "load_prom_seller_exclusions",
        load,
    )

    query = await competitor_prices_module.listing_search_query(
        object(), workspace_id, listing.id
    )

    load.assert_awaited_once()
    assert set(query.owner_seller_ids) == {
        "2847093",
        "4015921",
        "3325174",
        "3912822",
        "888",
    }


def test_workspace_exclusions_are_merged_without_cross_workspace_leakage():
    first = merge_prom_seller_exclusions([_dynamic("101", "first-store")])
    second = merge_prom_seller_exclusions([_dynamic("202", "second-store")])

    assert "101" in {item.external_id for item in first}
    assert "202" not in {item.external_id for item in first}
    assert "202" in {item.external_id for item in second}
    assert "101" not in {item.external_id for item in second}
    assert {item.external_id for item in GLOBAL_PROM_SELLER_EXCLUSIONS}.issubset(
        {item.external_id for item in first}
    )
    assert {item.external_id for item in GLOBAL_PROM_SELLER_EXCLUSIONS}.issubset(
        {item.external_id for item in second}
    )


def test_workspace_row_cannot_replace_a_fixed_preset_slug():
    changed_kemp = SellerExclusion(
        marketplace="prom",
        external_id="2847093",
        slug="kemp-renamed",
        canonical_url="https://prom.ua/ua/c2847093-kemp-renamed.html",
    )

    merged = merge_prom_seller_exclusions([changed_kemp])

    assert {item.slug for item in merged if item.external_id == "2847093"} == {
        "kemp",
        "kemp-renamed",
    }


async def test_load_exclusions_queries_only_the_requested_workspace(monkeypatch):
    workspace_id = uuid4()
    session = object()
    stored = _dynamic("101", "first-store")
    list_rows = AsyncMock(return_value=[stored])
    monkeypatch.setattr(
        "marko.services.seller_exclusions.stores_repo.list_competitor_seller_exclusions",
        list_rows,
    )

    loaded = await load_prom_seller_exclusions(session, workspace_id)

    list_rows.assert_awaited_once_with(session, workspace_id, marketplace="prom")
    assert "101" in {item.external_id for item in loaded}


async def test_remember_prom_seller_upserts_normalized_stable_identity(monkeypatch):
    workspace_id = uuid4()
    session = object()
    exclusion_id = uuid4()
    upsert = AsyncMock(return_value=exclusion_id)
    monkeypatch.setattr(
        "marko.services.seller_exclusions.stores_repo.upsert_competitor_seller_exclusion",
        upsert,
    )
    seller = Seller.from_url("https://prom.ua/c4015921-Avtobust.html")

    result = await remember_prom_seller(
        session,
        workspace_id=workspace_id,
        seller=seller,
    )

    assert result == exclusion_id
    upsert.assert_awaited_once_with(
        session,
        workspace_id=workspace_id,
        marketplace="prom",
        external_id="4015921",
        slug="Avtobust",
        canonical_url="https://prom.ua/ua/c4015921-Avtobust.html",
    )


async def test_post_store_registration_remembers_seller_before_transaction_commit(
    monkeypatch,
):
    events: list[str] = []
    workspace_id = uuid4()
    store_id = uuid4()
    active_run = SimpleNamespace(id=uuid4())
    session = AsyncMock()
    session.commit.side_effect = lambda: events.append("commit")

    async def upsert_store(*_args, **_kwargs):
        events.append("store")
        return store_id

    async def upsert_link(*_args, **_kwargs):
        events.append("link")

    async def remember(*_args, **_kwargs):
        events.append("exclusion")

    monkeypatch.setattr(
        stores_service.stores_repo, "upsert_marketplace_store", upsert_store
    )
    monkeypatch.setattr(
        stores_service.stores_repo, "upsert_workspace_store", upsert_link
    )
    monkeypatch.setattr(
        stores_service.stores_repo,
        "get_active_sync_run",
        AsyncMock(return_value=active_run),
    )
    monkeypatch.setattr(stores_service, "remember_prom_seller", remember)

    result_store_id, result_run = await stores_service.register_store(
        session,
        url="https://prom.ua/ua/c888-dynamic-store.html",
        workspace_id=workspace_id,
        celery_app=SimpleNamespace(),
    )

    assert (result_store_id, result_run) == (store_id, active_run)
    assert events == ["store", "link", "exclusion", "commit"]


async def test_xlsx_import_remembers_seller_in_the_import_transaction(monkeypatch):
    events: list[str] = []
    workspace_id = uuid4()
    store_id = uuid4()
    seller = Seller(company_id="888", slug="dynamic-store", lang="ua")
    imported_product = product()
    store = SimpleNamespace(last_synced_at=None)
    session = AsyncMock()
    session.get.return_value = store
    session.commit.side_effect = lambda: events.append("commit")

    monkeypatch.setattr(
        catalog_import, "parse_export", lambda _content: iter([imported_product])
    )
    monkeypatch.setattr(catalog_import, "seller_of", lambda _products: seller)
    monkeypatch.setattr(
        catalog_import.stores_repo,
        "upsert_marketplace_store",
        AsyncMock(return_value=store_id),
    )
    monkeypatch.setattr(
        catalog_import.stores_repo,
        "upsert_workspace_store",
        AsyncMock(),
    )

    async def remember(*_args, **_kwargs):
        events.append("exclusion")

    monkeypatch.setattr(catalog_import, "remember_prom_seller", remember)
    monkeypatch.setattr(catalog_import, "persist_products", AsyncMock(return_value=1))
    monkeypatch.setattr(
        catalog_import.listings_repo,
        "undelete_listings_for_store",
        AsyncMock(),
    )

    result = await catalog_import.import_export_file(
        session,
        workspace_id=workspace_id,
        content=b"xlsx",
    )

    assert result.store_id == store_id
    assert events == ["exclusion", "commit"]
