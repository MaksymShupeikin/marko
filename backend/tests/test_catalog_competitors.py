from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from marko.services.catalog_competitors import (
    _catalog_item_match_score,
    build_catalog_competitor_comparison,
    build_catalog_recommendation_summaries,
    empty_catalog_competitor_comparison,
)
from marko.services.catalog_discovery import (
    CatalogDiscoveredOffer,
    CatalogDiscoverySnapshot,
)


def _observation(
    *,
    seller_name: str,
    price: str,
):
    return SimpleNamespace(
        id=uuid4(),
        seller_id=seller_name.casefold().replace(" ", "-"),
        seller_name=seller_name,
        title=f"Предложение {seller_name}",
        url=f"https://prom.ua/p-{seller_name.casefold()}.html",
        price=Decimal(price),
        currency="UAH",
        is_available=True,
        match_confidence=Decimal("0.95"),
        observed_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
    )


def _classification(*, is_owned: bool, cohort_role: str):
    return SimpleNamespace(
        is_owned=is_owned,
        cohort_role=cohort_role,
        tier="aftermarket_a",
    )


def test_catalog_competitors_only_include_actual_target_market_evidence() -> None:
    competitor = _observation(seller_name="Auto Partner", price="690")
    owned = _observation(seller_name="KEMP", price="720")
    reference = _observation(seller_name="Reference seller", price="680")
    excluded = _observation(seller_name="Rejected seller", price="300")
    recommendation = SimpleNamespace(
        id=uuid4(),
        computed_at=datetime(2026, 7, 25, 13, 0, tzinfo=UTC),
        current_price=Decimal("720"),
        fair_price=Decimal("700"),
        recommended_price=Decimal("710"),
        currency="UAH",
        reason_codes=[],
        evidence_observation_ids=[
            str(competitor.id),
            str(owned.id),
            str(reference.id),
        ],
        calculation_trace={
            "normalized_offers": [
                {
                    "observation_id": str(competitor.id),
                    "normalized_price": "705.50",
                }
            ]
        },
    )

    result = build_catalog_competitor_comparison(
        recommendation,
        [
            (
                competitor,
                _classification(is_owned=False, cohort_role="TARGET_MARKET"),
            ),
            (owned, _classification(is_owned=True, cohort_role="OWNED_STORE")),
            (
                reference,
                _classification(is_owned=False, cohort_role="KEMP_REFERENCE"),
            ),
            (
                excluded,
                _classification(is_owned=False, cohort_role="TARGET_MARKET"),
            ),
        ],
    )

    assert [item.observation_id for item in result.items] == [competitor.id]
    assert result.items[0].seller_name == "Auto Partner"
    assert result.items[0].normalized_price == Decimal("705.50")
    assert result.current_price == Decimal("720")


def test_catalog_item_match_prefers_exact_oe_then_canonical_sku() -> None:
    item = SimpleNamespace(
        sku="KEMP 03-31 402 053",
        brand="KEMP",
        oe_norm="61131369611",
        mpn_norm="0331402053",
    )

    exact_oe = _catalog_item_match_score(
        item,
        sku="0331402053",
        oe="6 1131 36 9611",
        brand="KEMP",
    )
    sku_only = _catalog_item_match_score(
        item,
        sku="0331402053",
        oe=None,
        brand="KEMP",
    )

    assert exact_oe > sku_only
    assert sku_only > 0


def test_catalog_recommendation_summary_prefers_exact_product_match() -> None:
    product = SimpleNamespace(
        id="catalog-product",
        sku="0331402053",
        oe="6 1131 36 9611",
        brand="KEMP",
    )
    exact_oe_item = SimpleNamespace(
        sku="other",
        brand="KEMP",
        oe_norm="61131369611",
        mpn_norm="",
    )
    weaker_sku_item = SimpleNamespace(
        sku="0331402053",
        brand="KEMP",
        oe_norm="",
        mpn_norm="",
    )
    exact_recommendation = SimpleNamespace(
        id=uuid4(),
        computed_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
        recommended_price=Decimal("780"),
        currency="UAH",
        action="RAISE",
    )
    newer_weaker_recommendation = SimpleNamespace(
        id=uuid4(),
        computed_at=datetime(2026, 7, 25, 13, 0, tzinfo=UTC),
        recommended_price=Decimal("730"),
        currency="UAH",
        action="HOLD",
    )

    summaries = build_catalog_recommendation_summaries(
        (product,),
        [
            (exact_recommendation, exact_oe_item),
            (newer_weaker_recommendation, weaker_sku_item),
        ],
    )

    summary = summaries["catalog-product"]
    assert summary.recommended_price == Decimal("780")
    assert summary.action == "RAISE"


def test_catalog_empty_pricing_result_keeps_discovery_candidates_separate() -> None:
    discovery_offer = CatalogDiscoveredOffer(
        discovery_offer_id=uuid4(),
        source_listing_id="1402874053",
        seller_id="668922",
        seller_name="Autoparts IF",
        title="Замок багажника 7E5827505A",
        url="https://prom.ua/ua/p1402874053-item.html",
        sku="DF-11260",
        brand="Detali IF",
        sale_price=Decimal("629"),
        reference_price=None,
        currency="UAH",
        measure_unit="шт.",
        is_available=True,
        title_contains_query=True,
        identity_status="QUERY_TOKEN_PRESENT",
        source_confidence=Decimal("1"),
        reason_codes=("DISCOVERY_ONLY_NOT_PRICING_EVIDENCE",),
        selection_status="REVIEW",
        selection_reason="TIER_UNKNOWN",
        passed_gates=(
            "own_seller",
            "dismantler_seller",
            "condition",
            "remanufactured",
            "oem_identity",
            "oem_stuffing",
            "variant",
            "package",
            "applicability",
        ),
        selection_flags=(),
        selection_details={"stopped_gate": "tier"},
        predicted_tier="unknown",
        tier_confidence=Decimal("0"),
    )
    snapshot = CatalogDiscoverySnapshot(
        run_id=uuid4(),
        collected_at=datetime(2026, 7, 25, 14, 0, tzinfo=UTC),
        query="7E5827505A",
        status="completed",
        prom_reported_total=91,
        retrieved_count=29,
        persisted_count=29,
        owned_excluded_count=0,
        rejected_count=0,
        comparable_count=0,
        review_count=1,
        skipped_count=0,
        selection_histogram={"TIER_UNKNOWN (REVIEW)": 1},
        search_pages_fetched=1,
        search_page_limit=1,
        unfetched_count=62,
        coverage_ratio=Decimal("0.318681"),
        coverage_reason="SEARCH_PAGE_LIMIT",
        selection_method_version="deterministic-candidate-gates-v1",
        selection_config_sha256="a" * 64,
        brand_rules_dataset_id="NO_BRAND_DICTIONARY_CONFIGURED",
        items=(discovery_offer,),
    )

    result = empty_catalog_competitor_comparison(discovery=snapshot)

    assert result.items == ()
    assert result.recommendation_id is None
    assert result.discovery_run_id == snapshot.run_id
    assert result.discovery_items == (discovery_offer,)
    assert result.discovered_total == 1
    assert result.review_count == 1
    assert result.selection_histogram == {"TIER_UNKNOWN (REVIEW)": 1}
    assert result.unfetched_count == 62
