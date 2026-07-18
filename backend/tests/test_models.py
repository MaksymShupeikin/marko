from datetime import UTC, datetime
from uuid import uuid4

import pytest

from marko.api.schemas.stores import ProductResponse
from marko.infrastructure.db.models import (
    Listing,
    MarketObservation,
    StoreSyncProductSnapshot,
    SyncRun,
)
from marko.services.parser_models import Product, Seller, get_nested

from factories import product


# get_nested


def test_get_nested_returns_leaf_value():
    assert get_nested({"a": {"b": {"c": 7}}}, "a.b.c") == 7


def test_get_nested_missing_key_returns_none():
    assert get_nested({"a": {"b": 1}}, "a.x") is None


def test_get_nested_non_dict_midway_returns_none():
    assert get_nested({"a": 5}, "a.b") is None


# Product.from_raw


def test_from_raw_builds_url():
    assert product(id=5, urlText="slug").url == "https://prom.ua/ua/p5-slug.html"


def test_from_raw_url_none_without_id():
    assert Product.from_raw({"urlText": "slug"}, "ua").url is None


def test_from_raw_uses_fallback_keys():
    p = Product.from_raw({"id": 5, "newModelId": "NM", "company_id": 99}, "ua")
    assert (p.model_id, p.seller_id) == ("NM", 99)


def test_field_names_end_with_url():
    assert Product.field_names()[-1] == "url"


def test_listing_exposes_image_url_from_raw_product_data():
    listing = Listing(raw_data={"image": " https://images.prom.ua/product.jpg "})

    assert listing.image_url == "https://images.prom.ua/product.jpg"


def test_listing_rejects_non_http_image_url():
    listing = Listing(raw_data={"image": "javascript:alert(1)"})

    assert listing.image_url is None


def test_product_response_includes_listing_image_url():
    listing = Listing(
        id=uuid4(),
        store_id=uuid4(),
        external_id="product-1",
        name="Product",
        url="https://prom.ua/ua/p1-product.html",
        currency="UAH",
        raw_data={"image": "https://images.prom.ua/product.jpg"},
        last_seen_at=datetime.now(UTC),
    )

    response = ProductResponse.model_validate(listing)

    assert response.image_url == "https://images.prom.ua/product.jpg"


def test_store_sync_has_active_run_guard_and_immutable_snapshot_model():
    index_names = {index.name for index in SyncRun.__table__.indexes}
    constraints = {
        constraint.name for constraint in StoreSyncProductSnapshot.__table__.constraints
    }

    assert "uq_sync_run_active_store_sync" in index_names
    assert "uq_store_sync_product_snapshot_external" in constraints
    assert StoreSyncProductSnapshot.__table__.c.content_sha256 is not None
    snapshot_indexes = {
        index.name for index in StoreSyncProductSnapshot.__table__.indexes
    }
    assert snapshot_indexes == {
        "ix_store_sync_product_snapshot_run",
        "ix_store_sync_product_snapshots_listing_id",
        "ix_store_sync_product_snapshots_content_sha256",
    }


def test_market_observation_orm_matches_currency_evidence_migration() -> None:
    columns = MarketObservation.__table__.c

    assert columns.currency_raw.nullable
    assert not columns.currency_inferred.nullable
    assert columns.currency_inferred.server_default is not None


# Seller.from_url


def test_seller_from_url_parses_and_lowercases_lang():
    seller = Seller.from_url("https://prom.ua/UA/c2847093-kemp.html")
    assert (seller.company_id, seller.slug, seller.lang) == ("2847093", "kemp", "ua")


def test_seller_from_url_invalid_raises():
    with pytest.raises(ValueError):
        Seller.from_url("https://example.com/not-a-seller")
