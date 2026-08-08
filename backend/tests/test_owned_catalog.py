from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import json
from uuid import UUID, uuid4

import pytest

from marko.infrastructure.db.models import StoreKind
from marko.services import owned_catalog
from marko.services.owned_catalog import (
    OwnedCatalogListing,
    _owned_catalog_statement,
    _identity_title_label_pattern,
    _identity_title_pattern,
    _is_identity_query,
    build_owned_catalog_page,
    canonical_catalog_sku,
    enrich_listing_identifiers,
    enrich_listing_oe,
    extract_labeled_oe,
    get_owned_catalog_product,
    list_owned_catalog,
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
    mpn: str | None = None,
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
        mpn=mpn,
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


def test_owned_catalog_exposes_and_searches_native_mpn_without_calling_it_oe() -> None:
    rows = [
        _listing(
            store_id=STORE_A,
            external_id="3912822",
            sku="SELLER-LOCAL-1",
            mpn="TH 652 688 J",
        ),
        _listing(
            store_id=STORE_B,
            external_id="3325174",
            sku="OTHER-LOCAL-1",
            mpn="OTHER-MPN",
            name="Другой термостат Ford",
        ),
    ]

    page = build_owned_catalog_page(
        rows,
        query="TH652688J",
        limit=50,
        offset=0,
    )

    assert page.total == 1
    assert page.items[0].mpn == "TH 652 688 J"
    assert page.items[0].oe is None


def test_owned_catalog_identity_search_does_not_accept_numeric_suffixes() -> None:
    rows = [
        _listing(
            store_id=STORE_A,
            external_id="3912822",
            sku="1234567",
            name="Деталь з артикулом 1234567",
        ),
        _listing(
            store_id=STORE_B,
            external_id="3325174",
            sku="123456",
            name="Деталь з артикулом 123456",
        ),
    ]

    page = build_owned_catalog_page(rows, query="123456", limit=50, offset=0)

    assert page.total == 1
    assert page.items[0].sku == "123456"


def test_owned_catalog_identity_search_accepts_grouped_number_in_title() -> None:
    rows = [
        _listing(
            store_id=STORE_A,
            external_id="3912822",
            sku="INTERNAL-ROW",
            name="Кришка OEM 6 1131 36 9611",
        ),
    ]

    page = build_owned_catalog_page(
        rows,
        query="6-1131-36-9611",
        limit=50,
        offset=0,
    )

    assert page.total == 1


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("7E5 827 505 A", True),
        ("VW 7E5 827 505 A", True),
        ("123456", True),
        ("Mercedes 124", False),
        ("радиатор 2006", False),
    ],
)
def test_owned_catalog_identity_query_lane_recognizes_grouped_oe_without_catching_words(
    query: str,
    expected: bool,
) -> None:
    assert _is_identity_query(query.casefold(), owned_catalog.normalize_catalog_code(query)) is expected


def test_owned_catalog_sql_identity_lane_uses_boundaries_and_short_number_labels() -> None:
    long_pattern = _identity_title_pattern("7E5827505A")
    short_pattern = _identity_title_label_pattern("123456")

    assert "[:alnum:]" in long_pattern
    assert "[:alnum:]" in short_pattern
    assert "1[^[:alnum:]]*2" in short_pattern
    assert "5[^[:alnum:]]*6" in short_pattern
    assert "1234567" not in short_pattern


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
            oe_raw="6 1131 36 9611",
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


def test_owned_catalog_does_not_promote_title_oem_text_to_oe() -> None:
    page = build_owned_catalog_page(
        [
            _listing(
                store_id=STORE_A,
                external_id="3912822",
                sku="61131369611",
                name="Кришка запобіжників BMW 3 E21 OEM 6 1131 36 9611",
            )
        ],
        query="6-1131-36-9611",
        limit=50,
        offset=0,
    )

    assert page.total == 1
    assert page.items[0].oe is None


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


class _FakeMappings:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def one(self) -> dict:
        assert len(self.rows) == 1
        return self.rows[0]

    def first(self) -> dict | None:
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class _FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self.rows)


class _BoundedCatalogSession:
    def __init__(self, page_size: int) -> None:
        self.page_size = page_size
        self.calls: list[str] = []
        self.selected_rows_returned = 0

    async def execute(self, statement, parameters=None) -> _FakeResult:
        sql = str(statement)
        self.calls.append(sql)
        if "page_identities" in sql:
            identities = [
                {
                    "identity_kind": "brand_sku",
                    "identity_value": f"KEMP:SKU{index:04d}",
                }
                for index in range(self.page_size)
            ]
            return _FakeResult(
                [
                    {
                        "listing_total": 100_000,
                        "catalog_total": 75_000,
                        "filtered_total": 75_000,
                        "page_identities": identities,
                    }
                ]
            )
        if "first_listing.seller_name" in sql:
            return _FakeResult(
                [
                    {
                        "store_id": STORE_A,
                        "external_id": "3912822",
                        "store_name": "Parts Avto",
                    }
                ]
            )

        selected = json.loads(parameters["selected_identities"])
        rows = []
        for index, identity in enumerate(selected):
            listing = _listing(
                store_id=STORE_A,
                external_id="3912822",
                sku=f"SKU{index:04d}",
            )
            rows.append(
                {
                    "identity_kind": identity["identity_kind"],
                    "identity_value": identity["identity_value"],
                    **listing.__dict__,
                }
            )
        self.selected_rows_returned = len(rows)
        return _FakeResult(rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 50])
async def test_sql_catalog_paging_keeps_query_count_constant_and_rows_bounded(
    limit: int,
) -> None:
    session = _BoundedCatalogSession(page_size=limit)

    page = await list_owned_catalog(
        session,
        workspace_id=uuid4(),
        query=None,
        store_ids=None,
        limit=limit,
        offset=0,
    )

    assert len(session.calls) == 3
    assert session.selected_rows_returned == limit
    assert len(page.items) == limit
    assert page.listing_total == 100_000


class _DirectCatalogSession:
    def __init__(self, *, found: bool = True) -> None:
        self.found = found
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, parameters=None) -> _FakeResult:
        sql = str(statement)
        values = dict(parameters or {})
        self.calls.append((sql, values))
        if "selected_identities" not in values:
            if not self.found:
                return _FakeResult([])
            return _FakeResult(
                [
                    {
                        "identity_kind": "brand_sku",
                        "identity_value": "KEMP:SKU0001",
                    }
                ]
            )
        listing = _listing(
            store_id=STORE_A,
            external_id="3912822",
            sku="SKU0001",
        )
        return _FakeResult(
            [
                {
                    "identity_kind": "brand_sku",
                    "identity_value": "KEMP:SKU0001",
                    **listing.__dict__,
                }
            ]
        )


@pytest.mark.asyncio
async def test_direct_catalog_product_is_workspace_scoped_and_bounded() -> None:
    identity = ("brand_sku", "KEMP:SKU0001")
    product_id = (
        __import__("hashlib").sha256(f"{identity[0]}:{identity[1]}".encode()).hexdigest()[
            :32
        ]
    )
    workspace_id = uuid4()
    session = _DirectCatalogSession()

    product = await get_owned_catalog_product(
        session,
        workspace_id=workspace_id,
        product_id=product_id,
    )

    assert product is not None
    assert product.id == product_id
    assert len(session.calls) == 2
    identity_sql, parameters = session.calls[0]
    assert "ws.workspace_id = :workspace_id" in identity_sql
    assert "LIMIT 2" in identity_sql
    assert parameters == {
        "workspace_id": workspace_id,
        "product_id": product_id,
    }


@pytest.mark.asyncio
async def test_direct_catalog_product_rejects_invalid_or_foreign_ids() -> None:
    invalid_session = _DirectCatalogSession()
    assert (
        await get_owned_catalog_product(
            invalid_session,
            workspace_id=uuid4(),
            product_id="../not-an-id",
        )
        is None
    )
    assert invalid_session.calls == []

    foreign_session = _DirectCatalogSession(found=False)
    assert (
        await get_owned_catalog_product(
            foreign_session,
            workspace_id=uuid4(),
            product_id="a" * 32,
        )
        is None
    )
    assert len(foreign_session.calls) == 1


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
async def test_identifier_enrichment_caches_mpn_and_typed_detail_fields(
    monkeypatch,
) -> None:
    listing = _FakeListing(
        url="https://prom.ua/ua/p1-product.html",
        raw_data={},
    )
    session = _FakeSession()

    async def fake_owned_listing(*_args, **_kwargs):
        return listing

    class _Product:
        oe_raw = None
        mpn = "TH 652 688 J"
        name = "Термостат Ford"
        condition = "Новий"
        package_quantity = 1
        measure_unit = "шт."
        characteristics = [{"name": "Температура", "value": "88"}]
        description = "Деталь для Ford"

    def fake_fetch(url: str, _settings):
        assert url == listing.url
        return _Product()

    monkeypatch.setattr(owned_catalog, "_owned_listing", fake_owned_listing)
    monkeypatch.setattr(owned_catalog, "_fetch_listing_product", fake_fetch)
    monkeypatch.setattr(
        owned_catalog,
        "require_live_prom_marketplace_collection",
        lambda *_a, **_k: None,
    )

    result = await enrich_listing_identifiers(
        session,
        workspace_id=uuid4(),
        store_id=uuid4(),
        external_id="1",
    )

    assert result is not None
    assert result.mpn == "TH 652 688 J"
    assert result.oe is None
    assert result.status == "IDENTIFIERS_FOUND"
    assert listing.raw_data["mpn"] == "TH 652 688 J"
    assert listing.raw_data["condition"] == "Новий"
    assert listing.raw_data["identifier_enrichment_source"] == (
        "PROM_PRODUCT_DETAIL"
    )
    assert session.committed


@pytest.mark.asyncio
async def test_identifier_enrichment_does_not_refetch_cached_absence(monkeypatch) -> None:
    listing = _FakeListing(
        url="https://prom.ua/ua/p1-product.html",
        raw_data={
            "oe_raw": None,
            "mpn": None,
            "identifier_enrichment_checked_at": "2026-08-06T00:00:00Z",
            "identifier_enrichment_status": "NO_IDENTIFIER",
        },
    )

    async def fake_owned_listing(*_args, **_kwargs):
        return listing

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("cached absence must not trigger another fetch")

    monkeypatch.setattr(owned_catalog, "_owned_listing", fake_owned_listing)
    monkeypatch.setattr(owned_catalog, "_fetch_listing_product", fail_if_called)

    result = await enrich_listing_identifiers(
        _FakeSession(),
        workspace_id=uuid4(),
        store_id=uuid4(),
        external_id="1",
    )

    assert result is not None
    assert result.oe is None
    assert result.mpn is None
    assert result.status == "NO_IDENTIFIER"


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
