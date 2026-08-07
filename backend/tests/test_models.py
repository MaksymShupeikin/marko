from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint

from marko.api.schemas.stores import ProductResponse
from marko.infrastructure.db.models import (
    CandidateComparabilityFeedback,
    CandidateComparabilityReview,
    CatalogDiscoveryCapture,
    CatalogDiscoveryOffer,
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


def test_from_raw_uses_current_product_page_description_keys():
    plain = Product.from_raw(
        {"id": 5, "descriptionPlain": "OE 1K0121251", "descriptionFull": "HTML"},
        "ua",
    )
    full = Product.from_raw({"id": 6, "descriptionFull": "OE 6Q0121253"}, "ua")

    assert plain.description == "OE 1K0121251"
    assert full.description == "OE 6Q0121253"


def test_from_raw_normalizes_product_card_attributes_without_inventing_oe():
    parsed = Product.from_raw(
        {
            "id": 5,
            "sku": "93818439",
            "identifiers": {"mpn": "93818439"},
            "category": {"caption": "Радіатори автомобільні"},
            "attributes": [
                {
                    "id": 18009,
                    "name": "Код запчастини",
                    "group": "Основні",
                    "values": [{"value": "93818439, 77643"}],
                },
                {
                    "id": 10006,
                    "name": "Стан",
                    "group": "Основні",
                    "values": [{"value": "Новий"}],
                },
                {
                    "id": 18631,
                    "name": "Сумісність з моделлю",
                    "values": [{"value": "Daily"}, {"value": "Daily II"}],
                },
                {
                    "id": 99999,
                    "name": "Кількість в упаковці",
                    "values": [{"value": "6 шт."}],
                },
            ],
        }
    )

    assert parsed.mpn == "93818439"
    assert parsed.part_numbers == ("93818439", "77643")
    assert parsed.category == "Радіатори автомобільні"
    assert parsed.condition == "Новий"
    assert parsed.package_quantity == 6
    assert parsed.oe_raw is None
    assert [
        item["value"]
        for item in parsed.characteristics
        if item["name"] == "Сумісність з моделлю"
    ] == ["Daily", "Daily II"]
    assert parsed.characteristics[0]["source_path"] == (
        "$.attributes[0].values[0].value"
    )


def test_labelled_part_numbers_ignore_unrelated_attributes_and_unlabelled_text():
    parsed = Product.from_raw(
        {
            "id": 6,
            "name": "Радіатор 77646966",
            "descriptionPlain": "інший код 999999",
            "attributes": [
                {
                    "name": "Код запчастини",
                    "values": [{"value": "77646966, 230 588, 230589"}],
                },
                {"name": "Рік", "values": [{"value": "2006-2011"}]},
                {"name": "Розташування", "values": [{"value": "Задній міст"}]},
            ],
        }
    )

    assert parsed.part_numbers == ("77646966", "230 588", "230589")


def test_explicit_comparison_evidence_wins_over_product_attributes():
    parsed = Product.from_raw(
        {
            "comparisonEvidence": {"condition": "USED", "packageQuantity": 2},
            "characteristics": [{"name": "S", "value": "kept"}],
            "attributes": [
                {"name": "Стан", "values": [{"value": "Новий"}]},
                {
                    "name": "Кількість в упаковці",
                    "values": [{"value": "6"}],
                },
            ],
        }
    )

    assert parsed.condition == "USED"
    assert parsed.package_quantity == 2
    assert parsed.characteristics == [{"name": "S", "value": "kept"}]


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


def test_price_boundary_constraints_keep_sale_below_reference() -> None:
    observation_constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in MarketObservation.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }
    offer_constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in CatalogDiscoveryOffer.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }

    assert (
        "ck_market_observation_price_boundaries" in observation_constraints
    )
    assert (
        "ck_market_observation_sale_not_above_reference"
        in observation_constraints
    )
    assert "sale_price <= reference_price" in observation_constraints[
        "ck_market_observation_sale_not_above_reference"
    ]
    assert (
        "ck_catalog_discovery_offer_sale_not_above_reference" in offer_constraints
    )
    assert "sale_price <= reference_price" in offer_constraints[
        "ck_catalog_discovery_offer_sale_not_above_reference"
    ]


def test_llm_comparability_models_are_auditable_and_append_only_ready() -> None:
    observation_columns = MarketObservation.__table__.c
    review = CandidateComparabilityReview.__table__
    feedback = CandidateComparabilityFeedback.__table__

    assert not observation_columns.candidate_snapshot.nullable
    assert observation_columns.candidate_snapshot.server_default is not None
    assert _ondelete(review, "market_observation_id") == "RESTRICT"
    assert _ondelete(review, "cache_hit_review_id") == "RESTRICT"
    assert _ondelete(feedback, "review_id") == "RESTRICT"
    assert {
        "input_snapshot",
        "image_urls",
        "dimension_findings",
        "hard_stop_conflicts",
        "provider_response_id",
        "usage",
    } <= set(review.c.keys())
    assert {
        "corrected_verdict",
        "corrected_match_level",
        "evidence_corrections",
    } <= set(feedback.c.keys())


# Seller.from_url


def test_seller_from_url_parses_and_lowercases_lang():
    seller = Seller.from_url("https://prom.ua/UA/c2847093-kemp.html")
    assert (seller.company_id, seller.slug, seller.lang) == ("2847093", "kemp", "ua")


def test_seller_from_url_invalid_raises():
    with pytest.raises(ValueError):
        Seller.from_url("https://example.com/not-a-seller")


# raw evidence retention (F2-0014)


def _ondelete(table, column: str) -> str | None:
    for fk in table.columns[column].foreign_keys:
        return fk.ondelete
    raise AssertionError(f"{table.name}.{column} has no foreign key")


def test_discovery_captures_survive_deletion_of_their_run():
    """F2-0014: capture — сырое доказательство, а не производная строка.

    Проба аудита удаляла один ``catalog_discovery_runs`` и уносила 10 captures
    и 290 offers. Блоб был защищён RESTRICT, но без capture его нельзя привязать
    к запросу, который его породил.
    """
    captures = CatalogDiscoveryCapture.__table__
    assert _ondelete(captures, "discovery_run_id") == "RESTRICT"
    assert _ondelete(captures, "evidence_blob_id") == "RESTRICT"


def test_discovery_offers_remain_derived_rows():
    """Разобранные кандидаты восстановимы из captures, поэтому CASCADE уместен."""
    assert _ondelete(CatalogDiscoveryOffer.__table__, "discovery_run_id") == "CASCADE"
