from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from marko.infrastructure.db.models import StoreKind
from marko.services import owned_catalog
from marko.services.owned_catalog import (
    OwnedCatalogListing,
    _owned_catalog_statement,
    build_owned_catalog_page,
    canonical_catalog_sku,
    enrich_listing_oe,
    extract_labeled_oe,
)
from marko.services.source_access import SourceAccessBlocked


STORE_A = UUID("10000000-0000-0000-0000-000000000001")
STORE_B = UUID("20000000-0000-0000-0000-000000000002")


def _listing(
    *,
    store_id: UUID,
    external_id: str,
    sku: str,
    name: str = "Втягивающее реле стартера Mercedes",
    brand: str | None = "KEMP",
    oe_raw: str | None = None,
    description: str | None = None,
    store_name: str | None = None,
) -> OwnedCatalogListing:
    return OwnedCatalogListing(
        listing_id=uuid4(),
        store_id=store_id,
        store_external_id=external_id,
        store_name=store_name or ("parts-avto" if store_id == STORE_A else "profparts"),
        store_url=f"https://prom.ua/ua/c{external_id}-store.html",
        name=name,
        listing_url=f"https://prom.ua/ua/p{uuid4().int}-product.html",
        sku=sku,
        model_id=None,
        brand=brand,
        currency="UAH",
        current_price=Decimal("420.00"),
        is_available=True,
        image_url="https://images.prom.ua/product.jpg",
        oe_raw=oe_raw,
        description=description,
    )


def test_catalog_sku_removes_formatting_and_redundant_brand() -> None:
    assert canonical_catalog_sku("03-31 402 053 KEMP", "KEMP") == "0331402053"
    assert canonical_catalog_sku("KEMP 03-31 402 053", "KEMP") == "0331402053"


def test_owned_catalog_merges_clones_and_keeps_store_presence() -> None:
    rows = [
        _listing(store_id=STORE_A, external_id="3912822", sku="0331402053"),
        _listing(
            store_id=STORE_A,
            external_id="3912822",
            sku="0331-402-053 KEMP",
        ),
        _listing(
            store_id=STORE_B,
            external_id="3325174",
            sku="KEMP 0331402053",
        ),
        _listing(
            store_id=STORE_A,
            external_id="3912822",
            sku="9017601047",
            name="Кронштейн дверей Mercedes Sprinter верхний",
        ),
        _listing(
            store_id=STORE_B,
            external_id="3325174",
            sku="9067600147",
            name="Кронштейн дверей Mercedes Sprinter верхний",
        ),
    ]

    page = build_owned_catalog_page(rows, query=None, limit=50, offset=0)

    assert page.catalog_total == 3
    assert page.listing_total == 5
    assert page.duplicates_removed == 2
    assert page.store_total == 2
    merged = next(item for item in page.items if item.listing_count == 3)
    assert merged.sku == "0331402053"
    assert len(merged.stores) == 2
    assert sorted(store.listing_count for store in merged.stores) == [1, 2]


def test_owned_catalog_search_normalizes_oe_formatting() -> None:
    rows = [
        _listing(store_id=STORE_A, external_id="3912822", sku="0331402053"),
        _listing(store_id=STORE_B, external_id="3325174", sku="9067600147"),
    ]

    page = build_owned_catalog_page(
        rows,
        query="03-31 402 053",
        limit=50,
        offset=0,
    )

    assert page.total == 1
    assert page.items[0].sku == "0331402053"
    assert page.catalog_total == 2


@pytest.mark.parametrize(
    ("query", "expected_sku"),
    [
        ("0331-402-053", "0331402053"),
        ("втягивающее реле", "0331402053"),
        ("стартер Mercedes", "0331402053"),
        ("гальмівний супорт", "0331402053"),
    ],
)
def test_owned_catalog_searches_article_title_and_part_description(
    query: str,
    expected_sku: str,
) -> None:
    rows = [
        _listing(
            store_id=STORE_A,
            external_id="3912822",
            sku="0331402053",
            description="Гальмівний супорт для ремонту передньої осі",
        ),
        _listing(
            store_id=STORE_B,
            external_id="3325174",
            sku="9067600147",
            name="Кронштейн дверей Mercedes Sprinter",
        ),
    ]

    page = build_owned_catalog_page(rows, query=query, limit=50, offset=0)

    assert page.total == 1
    assert page.items[0].sku == expected_sku


def test_owned_catalog_exposes_and_searches_labeled_oe_number() -> None:
    rows = [
        _listing(
            store_id=STORE_A,
            external_id="3912822",
            sku="61131369611",
            name="Кришка запобіжників BMW 3 E21 OEM 6 1131 36 9611",
        ),
    ]

    page = build_owned_catalog_page(
        rows,
        query="6-1131-36-9611",
        limit=50,
        offset=0,
    )

    assert page.total == 1
    assert page.items[0].oe == "6 1131 36 9611"


def test_owned_catalog_uses_original_prom_store_name() -> None:
    page = build_owned_catalog_page(
        [
            _listing(
                store_id=STORE_B,
                external_id="3325174",
                sku="9067600147",
                store_name="ПРОФПАРТС",
            )
        ],
        query=None,
        limit=50,
        offset=0,
    )

    assert page.items[0].stores[0].name == "ПРОФПАРТС"


def test_owned_catalog_filters_by_store_and_keeps_all_store_options() -> None:
    page = build_owned_catalog_page(
        [
            _listing(
                store_id=STORE_A,
                external_id="3912822",
                sku="0331402053",
                store_name="Parts Avto",
            ),
            _listing(
                store_id=STORE_B,
                external_id="3325174",
                sku="9067600147",
                store_name="ПРОФПАРТС",
            ),
        ],
        query=None,
        store_ids=frozenset({STORE_B}),
        limit=50,
        offset=0,
    )

    assert page.catalog_total == 1
    assert page.listing_total == 1
    assert page.total == 1
    assert page.items[0].sku == "9067600147"
    assert page.store_total == 2
    assert [(store.store_id, store.name) for store in page.stores] == [
        (STORE_A, "Parts Avto"),
        (STORE_B, "ПРОФПАРТС"),
    ]


def test_owned_catalog_filters_by_multiple_stores() -> None:
    page = build_owned_catalog_page(
        [
            _listing(
                store_id=STORE_A,
                external_id="3912822",
                sku="0331402053",
                store_name="Parts Avto",
            ),
            _listing(
                store_id=STORE_B,
                external_id="3325174",
                sku="9067600147",
                store_name="ПРОФПАРТС",
            ),
        ],
        query=None,
        store_ids=frozenset({STORE_A, STORE_B}),
        limit=50,
        offset=0,
    )

    assert page.listing_total == 2
    assert page.total == 2
    assert {item.sku for item in page.items} == {"0331402053", "9067600147"}


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Кришка BMW OEM 6 1131 36 9611", "6 1131 36 9611"),
        ("Деталь OE: 4A1422893AA", "4A1422893AA"),
        ("Ремінь OEM BELT", None),
    ],
)
def test_extract_labeled_oe_requires_a_number(
    title: str,
    expected: str | None,
) -> None:
    assert extract_labeled_oe(title) == expected


def test_owned_catalog_statement_is_tenant_and_owned_store_scoped() -> None:
    workspace_id = uuid4()
    compiled = _owned_catalog_statement(workspace_id).compile()

    assert workspace_id in compiled.params.values()
    assert StoreKind.owned in compiled.params.values()


@pytest.mark.parametrize("limit,offset,expected", [(1, 0, 1), (1, 1, 1)])
def test_owned_catalog_paginates_after_deduplication(
    limit: int,
    offset: int,
    expected: int,
) -> None:
    rows = [
        _listing(store_id=STORE_A, external_id="3912822", sku="A-100"),
        _listing(store_id=STORE_B, external_id="3325174", sku="B-200"),
    ]

    page = build_owned_catalog_page(
        rows,
        query=None,
        limit=limit,
        offset=offset,
    )

    assert len(page.items) == expected
    assert page.total == 2


@dataclass
class _FakeListing:
    url: str
    raw_data: dict | None = field(default=None)


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_enrich_listing_oe_returns_cached_result_without_a_network_call(
    monkeypatch,
) -> None:
    listing = _FakeListing(
        url="https://prom.ua/ua/p1-product.html",
        raw_data={"oe_raw": "4A1422893AA", "oe_checked_at": "2026-07-01T00:00:00"},
    )

    async def fake_owned_listing(*_args, **_kwargs):
        return listing

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("should not re-fetch an already-checked listing")

    monkeypatch.setattr(owned_catalog, "_owned_listing", fake_owned_listing)
    monkeypatch.setattr(owned_catalog, "_fetch_listing_oe", fail_if_called)

    oe = await enrich_listing_oe(
        _FakeSession(),
        workspace_id=uuid4(),
        store_id=uuid4(),
        external_id="1",
    )

    assert oe == "4A1422893AA"


@pytest.mark.asyncio
async def test_enrich_listing_oe_fetches_and_caches_when_unchecked(monkeypatch) -> None:
    listing = _FakeListing(url="https://prom.ua/ua/p1-product.html", raw_data={})
    session = _FakeSession()

    async def fake_owned_listing(*_args, **_kwargs):
        return listing

    def fake_fetch(url: str, _settings) -> str | None:
        assert url == listing.url
        return "6 1131 36 9611"

    monkeypatch.setattr(owned_catalog, "_owned_listing", fake_owned_listing)
    monkeypatch.setattr(owned_catalog, "_fetch_listing_oe", fake_fetch)
    monkeypatch.setattr(
        owned_catalog,
        "require_live_prom_marketplace_collection",
        lambda *_a, **_k: None,
    )

    oe = await enrich_listing_oe(
        session,
        workspace_id=uuid4(),
        store_id=uuid4(),
        external_id="1",
    )

    assert oe == "6 1131 36 9611"
    assert listing.raw_data["oe_raw"] == "6 1131 36 9611"
    assert listing.raw_data["oe_checked_at"] is not None
    assert session.committed


@pytest.mark.asyncio
async def test_enrich_listing_oe_returns_none_for_a_foreign_listing(
    monkeypatch,
) -> None:
    async def fake_owned_listing(*_args, **_kwargs):
        return None

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("should not fetch a listing outside the workspace")

    monkeypatch.setattr(owned_catalog, "_owned_listing", fake_owned_listing)
    monkeypatch.setattr(owned_catalog, "_fetch_listing_oe", fail_if_called)

    oe = await enrich_listing_oe(
        _FakeSession(),
        workspace_id=uuid4(),
        store_id=uuid4(),
        external_id="does-not-exist",
    )

    assert oe is None


@pytest.mark.asyncio
async def test_enrich_listing_oe_respects_the_live_collection_gate(
    monkeypatch,
) -> None:
    listing = _FakeListing(url="https://prom.ua/ua/p1-product.html", raw_data={})

    async def fake_owned_listing(*_args, **_kwargs):
        return listing

    def blocked(*_args, **_kwargs):
        raise SourceAccessBlocked(_blocked_status())

    monkeypatch.setattr(owned_catalog, "_owned_listing", fake_owned_listing)
    monkeypatch.setattr(
        owned_catalog, "require_live_prom_marketplace_collection", blocked
    )

    with pytest.raises(SourceAccessBlocked):
        await enrich_listing_oe(
            _FakeSession(),
            workspace_id=uuid4(),
            store_id=uuid4(),
            external_id="1",
        )


def _blocked_status():
    from marko.services.source_access import SourceAccessStatus

    return SourceAccessStatus(
        source="prom_public_marketplace",
        verdict="BLOCKED",
        reference=None,
        live_collection_allowed=False,
    )
