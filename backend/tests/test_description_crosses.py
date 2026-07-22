"""Synthetic logic tests for Path 2; they are not the missing real AB fixtures."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from marko.infrastructure.db.models import CrossLink, MarketObservation
from metis.pricing import (
    CrossListing,
    CrossRejectionReason,
    CrossStageCBlocked,
    CrossValidationStatus,
    ProductTier,
    evaluate_real_fixture_checks,
    extract_cross_candidates,
    load_approved_brand_rules,
    load_cross_config,
    require_stage_c_brand_dictionary,
    run_cross_stages_ab,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cross_config():
    return load_cross_config(BACKEND_ROOT / "config" / "crosses.yaml")


def listing(
    description: str | None,
    *,
    listing_id: str = "listing-1",
    our_oem: str = "OUR1234",
    price: str = "1000",
    our_category: str | None = "radiator",
    source_category: str | None = "radiator",
    url: str | None = None,
    seller_id: str | None = None,
    seller_name: str | None = None,
) -> CrossListing:
    return CrossListing(
        listing_id=listing_id,
        our_oem_norm=our_oem,
        description=description,
        source_listing_url=url or f"https://prom.ua/ua/p-{listing_id}.html",
        source_seller=seller_name or f"seller-{listing_id}",
        source_seller_id=seller_id,
        price=Decimal(price),
        our_category=our_category,
        source_category=source_category,
    )


def test_stage_a_filters_dimensions_and_extracts_three_analog_numbers(
    cross_config,
) -> None:
    result = extract_cross_candidates(
        listing(
            "Радіатор 505*382, аналог ABC12345/DEF67890/GHI54321",
        ),
        cross_config,
    )

    assert {item.extracted_oem_norm for item in result.candidates} == {
        "ABC12345",
        "DEF67890",
        "GHI54321",
    }
    assert CrossRejectionReason.DIMENSION in {item.reason for item in result.rejections}
    assert result.candidates[0].extraction_method == "ANALOG_MARKER"


def test_stage_a_filters_phone_year_vin_gtin_engine_own_oe_and_price(
    cross_config,
) -> None:
    description = (
        "0671234567; 1997-2004; WVWZZZ1JZXW000001; 12345678; "
        "2.0 TDI; OUR1234; 1234567 грн; OE ABC12345"
    )
    result = extract_cross_candidates(listing(description), cross_config)

    assert [item.extracted_oem_norm for item in result.candidates] == ["ABC12345"]
    assert {item.reason for item in result.rejections} >= {
        CrossRejectionReason.PHONE,
        CrossRejectionReason.YEAR_OR_RANGE,
        CrossRejectionReason.VIN,
        CrossRejectionReason.GTIN,
        CrossRejectionReason.ENGINE_DISPLACEMENT,
        CrossRejectionReason.OWN_OEM,
        CrossRejectionReason.PRICE,
    }


@pytest.mark.parametrize("description", (None, "", "  ", "123"))
def test_stage_a_empty_or_short_description_is_safe(
    cross_config, description: str | None
) -> None:
    result = extract_cross_candidates(listing(description), cross_config)

    assert result.description_state == "EMPTY_OR_SHORT"
    assert result.candidates == ()
    assert result.rejections == ()


def test_raw_context_uses_the_configured_eighty_chars_per_side(cross_config) -> None:
    description = f"{'A' * 100} ABC12345 {'B' * 100}"
    result = extract_cross_candidates(listing(description), cross_config)

    assert len(result.candidates) == 1
    context = result.candidates[0].raw_context
    assert len(context) == 168
    assert context.index("ABC12345") == 80
    assert len(context) - context.index("ABC12345") - len("ABC12345") == 80


def test_stage_b_category_mismatch_rejects_before_price(cross_config) -> None:
    result = run_cross_stages_ab(
        [
            listing(
                "OE ABC12345",
                source_category="brake_pad",
            )
        ],
        cross_config,
    )

    decision = result.pair_decisions[0]
    assert decision.validation_status is CrossValidationStatus.REJECTED
    assert decision.rejection_reason is CrossRejectionReason.CATEGORY_MISMATCH


def test_stage_b_outer_price_band_rejects_and_inner_band_reviews(
    cross_config,
) -> None:
    rows = [
        listing("OE ABC12345", listing_id="extreme", price="10000"),
        listing(None, listing_id="market-1", price="1000"),
        listing(None, listing_id="market-2", price="1000"),
        listing(None, listing_id="market-3", price="1000"),
        listing(None, listing_id="market-4", price="1000"),
    ]
    rejected = run_cross_stages_ab(rows, cross_config).pair_decisions[0]
    review_rows = [
        listing("OE DEF67890", listing_id="review", price="3500"),
        listing(None, listing_id="market-a", price="1000"),
        listing(None, listing_id="market-b", price="1000"),
        listing(None, listing_id="market-c", price="1000"),
        listing(None, listing_id="market-d", price="1000"),
    ]
    reviewed = run_cross_stages_ab(review_rows, cross_config).pair_decisions[0]

    assert rejected.validation_status is CrossValidationStatus.REJECTED
    assert rejected.rejection_reason is CrossRejectionReason.PRICE_OUT_OF_BAND
    assert reviewed.validation_status is CrossValidationStatus.REVIEW
    assert reviewed.rejection_reason is None


def test_stage_b_reciprocity_confirms_unmarked_candidate(cross_config) -> None:
    result = run_cross_stages_ab(
        [
            listing("Деталь X123456", listing_id="source"),
            listing(
                "OUR1234 сумісний з X123456",
                listing_id="reciprocal",
                url="https://prom.ua/ua/p-reciprocal.html",
            ),
        ],
        cross_config,
    )

    decision = next(
        item for item in result.pair_decisions if item.extracted_oem_norm == "X123456"
    )
    assert decision.validation_status is CrossValidationStatus.CONFIRMED
    assert decision.reciprocal_evidence_url


def test_stage_b_deduplicates_pair_and_aggregates_sources(cross_config) -> None:
    result = run_cross_stages_ab(
        [
            listing("OE ABC12345", listing_id="explicit"),
            listing("Деталь ABC12345", listing_id="unmarked"),
        ],
        cross_config,
    )

    assert len(result.pair_decisions) == 1
    decision = result.pair_decisions[0]
    assert decision.validation_status is CrossValidationStatus.CONFIRMED
    assert len(decision.source_evidence) == 2
    assert decision.validation_details["source_count"] == 2
    assert decision.validation_details["independent_seller_count"] == 2
    assert decision.automatic_eligible is True


def test_confirmed_single_seller_cross_is_not_automatic(cross_config) -> None:
    result = run_cross_stages_ab(
        [listing("OE ABC12345", listing_id="only-source")],
        cross_config,
    )

    decision = result.pair_decisions[0]
    assert decision.validation_status is CrossValidationStatus.CONFIRMED
    assert decision.validation_details["independent_seller_count"] == 1
    assert decision.automatic_eligible is False


def test_independent_seller_count_prefers_stable_ids_over_display_names(
    cross_config,
) -> None:
    result = run_cross_stages_ab(
        [
            listing(
                "OE ABC12345",
                listing_id="source-a",
                seller_id="42",
                seller_name="Store name",
            ),
            listing(
                "OE ABC12345",
                listing_id="source-b",
                seller_id="42",
                seller_name="Store name with suffix",
            ),
        ],
        cross_config,
    )

    decision = result.pair_decisions[0]
    assert decision.validation_details["source_seller_ids"] == ["42"]
    assert decision.validation_details["independent_seller_count"] == 1
    assert decision.automatic_eligible is False


def test_stage_c_is_runtime_blocked_by_current_unapproved_brand_dictionary(
    cross_config,
) -> None:
    rules = load_approved_brand_rules(BACKEND_ROOT / "config" / "brands.yaml")

    with pytest.raises(CrossStageCBlocked) as error:
        require_stage_c_brand_dictionary(rules.tiers, cross_config)

    assert str(error.value) == (
        "brand dictionary is empty; Stage C is pointless: "
        "new offers would all classify as UNKNOWN"
    )


def test_real_fixture_gate_does_not_require_an_empty_row(cross_config) -> None:
    rows = [
        {
            "listing_id": "real-1",
            "description": "Аналог ABC12345, розмір 10x20, 2010-2020, тел 380501234567",
        }
    ]
    result = run_cross_stages_ab(
        [listing(rows[0]["description"], listing_id="real-1")], cross_config
    )

    checks = evaluate_real_fixture_checks(result, rows)

    assert checks["real_empty_or_short_description_safe"] is True
    assert (
        require_stage_c_brand_dictionary(
            {"KEMP": ProductTier.KEMP, "BOSCH": ProductTier.OES}, cross_config
        )
        == 1
    )


def test_orm_schema_has_append_only_cross_link_and_via_cross_provenance() -> None:
    cross_columns = CrossLink.__table__.c
    observation_columns = MarketObservation.__table__.c
    cross_constraints = {
        constraint.name for constraint in CrossLink.__table__.constraints
    }

    assert not cross_columns.sequence_no.nullable
    assert "uq_cross_link_run_pair" in cross_constraints
    assert "ck_cross_link_validation_status" in cross_constraints
    assert not observation_columns.via_cross.nullable
    assert observation_columns.via_cross.server_default is not None
    assert observation_columns.cross_link_id.nullable
