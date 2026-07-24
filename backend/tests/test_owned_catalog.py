from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from marko.infrastructure.db.models import StoreKind
from marko.services.owned_catalog import (
    OwnedCatalogListing,
    _owned_catalog_statement,
    build_owned_catalog_page,
    canonical_catalog_sku,
)


STORE_A = UUID("10000000-0000-0000-0000-000000000001")
STORE_B = UUID("20000000-0000-0000-0000-000000000002")


def _listing(
    *,
    store_id: UUID,
    external_id: str,
    sku: str,
    name: str = "Втягивающее реле стартера Mercedes",
    brand: str | None = "KEMP",
) -> OwnedCatalogListing:
    return OwnedCatalogListing(
        listing_id=uuid4(),
        store_id=store_id,
        store_external_id=external_id,
        store_name="parts-avto" if store_id == STORE_A else "profparts",
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
        oe_raw=None,
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
