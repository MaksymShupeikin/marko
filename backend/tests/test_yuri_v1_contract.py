"""Executable Yuri V1 semantic contract and Prompt 15.016 regressions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from factories import product

from marko.api.routers.v1.catalog import _catalog_item_response
from marko.api.schemas.catalog import CatalogItemResponse
from marko.api.schemas.pricing import PricingEvaluateResponse, RecommendationResponse
from marko.core.config import Settings
from marko.infrastructure.db.models import (
    MarketObservation,
    ObservationTierClassification,
)
from marko.services.cost_privacy import (
    CostPrivacyBlocked,
    is_raw_cost_label,
    privacy_safe_mapping,
    privacy_safe_validation_errors,
    require_server_cost_input_allowed,
)
from marko.services.market_collection import (
    _domain_offer,
    _persist_payload_observations,
    _validated_listing_url,
)
from marko.services.matching import match_offer
from metis.pricing import (
    CoefficientModel,
    CohortRole,
    CompetitorOffer,
    ConditionState,
    DimensionEvidence,
    EvidenceState,
    PricingPolicy,
    ProductPricingContext,
    ProductTier,
    RecommendationAction,
    StockStatus,
    TierCoefficient,
    evaluate_comparison_evidence,
    normalize_oe,
    recommend_price,
    verified_comparison_evidence,
)
from metis.pricing.tiering import (
    classify_condition,
    classify_tier,
    extract_description_cross_candidates,
)

CATEGORY = "brakes"


def _coefficient(tier: ProductTier = ProductTier.AFTERMARKET_A) -> TierCoefficient:
    return TierCoefficient(
        category=CATEGORY,
        tier=tier,
        multiplier=Decimal("1"),
        model=CoefficientModel.SHRINKAGE,
        method_version="yuri-v1-test-coefficient-v1",
        coefficient_version="yuri-v1-test-coefficient-v1:dataset",
        sample_size=20,
        effective_sample_size=Decimal("18"),
        confidence=Decimal("0.95"),
        validated=True,
        log_effect=Decimal("0"),
        interval_low=Decimal("0.9"),
        interval_high=Decimal("1.1"),
        dataset_hash="a" * 64,
    )


def _offer(
    index: int,
    price: str,
    *,
    tier: ProductTier = ProductTier.AFTERMARKET_A,
    is_kemp: bool = False,
) -> CompetitorOffer:
    seller_id = f"seller-{index}"
    return CompetitorOffer(
        observation_id=f"obs-{index}",
        seller_id=seller_id,
        seller_name=f"Seller {index}",
        price=Decimal(price),
        currency="UAH",
        currency_raw="UAH",
        is_available=True,
        age_hours=Decimal("0"),
        match_confidence=Decimal("0.99"),
        tier=tier,
        tier_confidence=Decimal("0.99"),
        source_confidence=Decimal("1"),
        semantic_gate_current=True,
        automatic_eligible=True,
        is_kemp=is_kemp,
        listing_url=f"https://prom.ua/ua/p{index}-part.html",
        comparison_evidence=verified_comparison_evidence(
            stable_seller_id=seller_id,
            source_record_id=f"obs-{index}",
        ),
    )


def _market() -> list[CompetitorOffer]:
    return [
        _offer(index, price)
        for index, price in enumerate(("1000", "1050", "1100", "1150", "1200"))
    ]


def _context(price: str, **overrides) -> ProductPricingContext:
    values = {
        "sku": "YURI-V1",
        "category": CATEGORY,
        "current_price": Decimal(price),
        "stock_status": StockStatus.FRESH,
    }
    values.update(overrides)
    return ProductPricingContext(**values)


def _coefficients() -> dict[tuple[str, ProductTier], TierCoefficient]:
    return {(CATEGORY, ProductTier.AFTERMARKET_A): _coefficient()}


def test_oe_first_same_oe_different_brand_reaches_comparability() -> None:
    seed = product(
        id=1,
        manufacturerInfo={"name": "KEMP"},
        comparisonEvidence={"oeRaw": "1K0 698 151 E"},
    )
    candidate = product(
        id=2,
        manufacturerInfo={"name": "Bosch"},
        comparisonEvidence={"oeRaw": "1K0-698-151-E"},
    )

    match = match_offer(seed, candidate, 0.99)

    assert match is not None
    assert match.kind == "oe"


def test_brand_dimension_is_not_an_identity_or_comparability_rejection() -> None:
    evidence = verified_comparison_evidence(
        stable_seller_id="seller-1",
        source_record_id="obs-1",
        dimension_overrides={
            "brand_manufacturer": DimensionEvidence(
                state=EvidenceState.CONFLICT,
                raw_value="Bosch",
                normalized_value="bosch",
            )
        },
    )

    decision = evaluate_comparison_evidence(
        evidence,
        seller_id="seller-1",
        currency_raw="UAH",
        currency_normalized="UAH",
        required_currency="UAH",
        category=CATEGORY,
    )

    assert decision.automatic_eligible
    assert "REJECTED_IDENTITY_CONFLICT" not in decision.reason_codes


def test_same_brand_cannot_override_conflicting_oe() -> None:
    evidence = verified_comparison_evidence(
        stable_seller_id="seller-1",
        source_record_id="obs-1",
        dimension_overrides={
            "oe_reference": DimensionEvidence(state=EvidenceState.CONFLICT),
            "brand_manufacturer": DimensionEvidence(state=EvidenceState.MATCH),
        },
    )

    decision = evaluate_comparison_evidence(
        evidence,
        seller_id="seller-1",
        currency_raw="UAH",
        currency_normalized="UAH",
        required_currency="UAH",
        category=CATEGORY,
    )

    assert not decision.automatic_eligible
    assert decision.reason_codes[0] == "REJECTED_IDENTITY_CONFLICT"


def test_oe_normalization_is_nfkc_and_removes_all_non_alnum_separators() -> None:
    assert normalize_oe("１Ｋ０\u00a0６９８—１５１／Ｅ") == "1K0698151E"


def test_kemp_reference_price_mutation_does_not_change_target_recommendation() -> None:
    first = recommend_price(
        _context("800"),
        [*_market(), _offer(90, "1025", tier=ProductTier.KEMP, is_kemp=True)],
        _coefficients(),
    )
    second = recommend_price(
        _context("800"),
        [*_market(), _offer(90, "1175", tier=ProductTier.KEMP, is_kemp=True)],
        _coefficients(),
    )

    assert first.fair_price == second.fair_price
    assert first.recommended_price == second.recommended_price
    assert first.action == second.action
    assert first.target_market_count == 5
    assert first.kemp_reference_count == 1


def test_persisted_non_target_cohort_role_cannot_reenter_target_market() -> None:
    forged_kemp = replace(
        _offer(91, "1", tier=ProductTier.AFTERMARKET_A),
        cohort_role=CohortRole.KEMP_REFERENCE,
    )
    forged_used = replace(
        _offer(92, "2", tier=ProductTier.AFTERMARKET_A),
        cohort_role=CohortRole.USED_REJECTED,
    )

    result = recommend_price(
        _context("800"),
        [*_market(), forged_kemp, forged_used],
        _coefficients(),
    )

    assert result.target_market_count == 5
    assert result.kemp_reference_count == 1
    assert all(item.observation_id != "obs-91" for item in result.evidence)
    assert any(
        item.observation_id == "obs-92" and item.cohort_role == CohortRole.USED_REJECTED
        for item in result.excluded
    )


def test_legacy_domain_adapter_rederives_used_and_kemp_safety_signals() -> None:
    now = datetime.now(UTC)
    base_observation = {
        "id": uuid4(),
        "seller_id": "legacy-seller",
        "seller_name": "Legacy seller",
        "price": Decimal("1000"),
        "currency": "UAH",
        "currency_raw": "UAH",
        "currency_inferred": False,
        "is_available": True,
        "observed_at": now,
        "match_confidence": Decimal("0.99"),
        "source_confidence": Decimal("1"),
        "source": "persisted_replay",
        "url": "https://prom.ua/legacy",
        "comparison_evidence": None,
        "condition_raw": None,
        "condition_state": "UNKNOWN",
        "title": "Колодки",
        "description": "Вживаний товар",
        "brand_raw": "Bosch",
    }
    classification = SimpleNamespace(
        tier=ProductTier.AFTERMARKET_A.value,
        tier_confidence=Decimal("0.99"),
        is_used=False,
        is_kemp=False,
        is_owned=False,
        is_dumping=False,
        exclusion_reason=None,
        cohort_role=CohortRole.TARGET_MARKET.value,
    )

    used_offer = _domain_offer(SimpleNamespace(**base_observation), classification, now)
    kemp_offer = _domain_offer(
        SimpleNamespace(
            **{
                **base_observation,
                "id": uuid4(),
                "description": None,
                "condition_state": "NEW",
                "brand_raw": "KEMP",
            }
        ),
        classification,
        now,
    )

    assert used_offer.is_used
    assert kemp_offer.is_kemp
    # condition-v4 (2026-08-21): молчание карточки о состоянии больше не
    # конфликт — KEMP исключается своей ролью, а не «неизвестным состоянием».
    assert not kemp_offer.severe_conflict
    assert kemp_offer.conflict_reason is None


def test_product_additive_boundary_preserves_available_description() -> None:
    parsed = product(description="Товар вживаний, з розборки")

    assert parsed.description == "Товар вживаний, з розборки"


@pytest.mark.parametrize(
    ("title", "description", "explicit_condition"),
    (
        ("Колодки б/у", None, None),
        ("Амортизатор Hyundai передний правый Б.У", None, None),
        ("Амортизатор Hyundai передний правый б-у", None, None),
        ("Амортизатор Hyundai передний правый second-hand", None, None),
        ("A 901 501 27 82 BU _ ПАТРУБОК", None, None),
        ("Mercedes B/U патрубок", None, None),
        ("Колодки", "Товар вживаний з розборки", None),
        ("Колодки", None, "used"),
    ),
)
def test_used_signal_from_any_available_lane_is_a_hard_tier_reject(
    title: str,
    description: str | None,
    explicit_condition: str | None,
) -> None:
    assessment = classify_condition(
        title=title,
        description=description,
        explicit_condition=explicit_condition,
    )
    tier = classify_tier(
        brand="Bosch",
        title=title,
        description=description,
        condition=explicit_condition,
    )

    assert assessment.is_used
    assert assessment.state == ConditionState.USED_OR_REFURBISHED
    assert tier.tier == ProductTier.USED
    assert tier.is_used


def test_silent_condition_is_assumed_new_by_owner_decision() -> None:
    # Решение владельца 2026-08-21: про б/у на Prom пишут явно, поэтому
    # молчание карточки читается как «новый», а не UNKNOWN (condition-v4).
    assessment = classify_condition(
        title="Колодки",
        description=None,
        explicit_condition=None,
    )

    assert assessment.state == ConditionState.NEW
    assert not assessment.is_used
    assert assessment.reason_codes == ("CONDITION_NEW_ASSUMED_NO_USED_MARKERS",)


def test_condition_markers_are_boundary_aware_and_conflicts_fail_closed() -> None:
    safe = classify_condition(
        title="Буфер крепления Mercedes BU A9015012782BU",
        description="Бутылка в комплекте, втулка BU-42",
        explicit_condition=None,
    )
    conflict = classify_condition(
        title="Новая деталь",
        description="Вживаний товар",
        explicit_condition=None,
    )

    # BU-токены в артикулах — не маркер б/у; молчание = «новый» (condition-v4).
    assert safe.state == ConditionState.NEW
    assert not safe.is_used
    assert conflict.state == ConditionState.CONFLICT
    assert conflict.is_used


def test_description_cross_numbers_stay_unvalidated_phase_two_candidates() -> None:
    candidates = extract_description_cross_candidates(
        "Кросс номера: 1K0 698 151 E, 8E0-698-151.",
        source_observation_id="obs-cross",
    )

    assert {item.normalized_token for item in candidates} == {
        "1K0698151E",
        "8E0698151",
    }
    assert all(item.validation_state == "UNVALIDATED" for item in candidates)
    assert all(not item.automatic_identity_eligible for item in candidates)


@pytest.mark.asyncio
async def test_description_condition_is_persisted_before_cohort_assignment() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, value: object) -> None:
            self.added.append(value)

        async def flush(self) -> None:
            for value in self.added:
                if isinstance(value, MarketObservation) and value.id is None:
                    value.id = uuid4()

        def begin_nested(self):
            session = self

            class _Nested:
                async def __aenter__(self) -> FakeSession:
                    return session

                async def __aexit__(self, *_exc: object) -> None:
                    return None

            return _Nested()

    session = FakeSession()
    await _persist_payload_observations(
        session,
        run=SimpleNamespace(id=uuid4(), parser_version="fixture-parser-v1"),
        run_item=SimpleNamespace(id=uuid4()),
        catalog_item=SimpleNamespace(
            id=uuid4(),
            category=CATEGORY,
            oe_norm="1K0698151E",
            mpn_norm="",
            identity_status="OE_CONFIRMED",
            part_numbers_norm=(),
        ),
        capture=SimpleNamespace(id=uuid4(), content_sha256="b" * 64),
        offers=[
            {
                "price": "1000",
                "match_score": "0.99",
                "seller_id": "seller-used",
                "seller_name": "Seller Used",
                "name": "Колодки Bosch",
                "brand": "Bosch",
                "description": "Товар вживаний, кросс 1K0 698 151 E",
                "currency": "UAH",
                "is_available": True,
                "url": "https://prom.ua/ua/p1-used.html",
            }
        ],
        owned_sellers=set(),
        brand_tiers={"BOSCH": ProductTier.OES},
        brand_confidence={},
        observed_at=SimpleNamespace(),
        source_type="persisted_replay",
        acquisition_query="1K0698151E",
    )

    observation = next(
        value for value in session.added if isinstance(value, MarketObservation)
    )
    classification = next(
        value
        for value in session.added
        if isinstance(value, ObservationTierClassification)
    )
    assert observation.description_available
    assert observation.condition_state == "USED_OR_REFURBISHED"
    assert observation.cross_candidates
    assert not observation.automatic_eligible
    assert classification.is_used
    assert classification.cohort_role == "USED_REJECTED"


@pytest.mark.parametrize(
    "mode",
    ("UNDECIDED", "LOCAL_DEVICE_ONLY"),
)
def test_raw_cost_input_is_fail_closed_for_every_unimplemented_mode(mode: str) -> None:
    with pytest.raises(CostPrivacyBlocked) as error:
        require_server_cost_input_allowed(
            Decimal("987.65"),
            settings=Settings(cost_privacy_mode=mode),
        )

    assert "987.65" not in str(error.value)


def test_legacy_cost_fields_are_recursively_redacted_from_response_boundaries() -> None:
    safe = privacy_safe_mapping(
        {
            "cost": "sensitive",
            "nested": {
                "cost_snapshot": "sensitive",
                "retail_price": "1000",
            },
            "rows": [{"below_cost_floor": "sensitive", "action": "LOWER"}],
        }
    )

    assert safe == {"nested": {"retail_price": "1000"}, "rows": [{"action": "LOWER"}]}


@pytest.mark.parametrize(
    "label",
    (
        "Себестоимость, грн",
        "Собівартість (грн)",
        "Unit cost (UAH)",
        "costSnapshot",
        "belowCostFloor",
        "Закупівельна ціна, ₴",
    ),
)
def test_cost_label_detection_covers_units_and_camel_case(label: str) -> None:
    assert is_raw_cost_label(label)


def test_cost_label_detection_does_not_remove_retail_or_shipping_fields() -> None:
    assert not is_raw_cost_label("retail_price")
    assert not is_raw_cost_label("Стоимость доставки")
    assert not is_raw_cost_label("cost_configured")
    assert not is_raw_cost_label("allow_below_cost")


def test_validation_errors_never_echo_raw_cost_or_client_input() -> None:
    errors = privacy_safe_validation_errors(
        [
            {
                "type": "greater_than",
                "loc": ("body", "context", "cost"),
                "msg": "Input should be greater than 0",
                "input": "sensitive-cost-canary",
                "ctx": {"gt": 0},
            },
            {
                "type": "missing",
                "loc": ("body", "offers", 0, "price"),
                "msg": "Field required",
                "input": {"client_row_canary": "sensitive-row-canary"},
            },
        ]
    )

    rendered = repr(errors)
    assert "sensitive-cost-canary" not in rendered
    assert "sensitive-row-canary" not in rendered
    assert all("input" not in error and "ctx" not in error for error in errors)
    assert errors[0]["type"] == "value_error.sensitive_input_disabled"


def test_competitor_url_is_preserved_only_for_openable_http_protocols() -> None:
    assert _validated_listing_url("https://prom.ua/ua/p1-part.html") == (
        "https://prom.ua/ua/p1-part.html",
        None,
    )
    assert _validated_listing_url("javascript:alert(1)") == (
        "",
        "INVALID_URL_PROTOCOL",
    )
    assert _validated_listing_url(None) == ("", "SOURCE_URL_NOT_AVAILABLE")


def test_fresh_item_priced_above_the_market_is_left_alone() -> None:
    """Contract revision 2026-07-28: no downward advice for a selling item.

    The customer chose the asymmetry: the tool exists to show where a price can
    go up.  Being wrong about a cut costs margin on every unit sold, so above
    the target the engine holds and says why.
    """

    result = recommend_price(_context("1500"), _market(), _coefficients())

    assert result.action == RecommendationAction.HOLD
    assert result.recommended_price is None
    assert "PRICE_ALREADY_AT_OR_ABOVE_TARGET" in result.reasons


def test_dead_stock_markdown_is_saturated_and_does_not_depend_on_age() -> None:
    """Dead stock is liquidated at full pressure from day one.

    ``dead_stock_markdown_beta`` is 1, so age cannot deepen a markdown that is
    already at the market floor.  The age ramp it replaced belonged to the
    stale path, which contract revision 2026-07-28 removed: a slow mover is no
    longer marked down at all, so that ramp now has no reachable caller.
    """

    younger = recommend_price(
        _context(
            "1500",
            stock_status=StockStatus.DEAD_STOCK,
            stock_age_days=Decimal("365"),
        ),
        _market(),
        _coefficients(),
    )
    older = recommend_price(
        _context(
            "1500",
            stock_status=StockStatus.DEAD_STOCK,
            stock_age_days=Decimal("730"),
        ),
        _market(),
        _coefficients(),
    )

    assert younger.recommended_price is not None
    assert older.recommended_price is not None
    assert older.recommended_price == younger.recommended_price


def test_slow_mover_is_never_marked_down_by_age() -> None:
    """A stale item above the cheapest offer gets silence, not a discount."""

    aged = recommend_price(
        _context(
            "1500",
            stock_status=StockStatus.STALE,
            stock_age_days=Decimal("730"),
        ),
        _market(),
        _coefficients(),
    )

    assert aged.action == RecommendationAction.HOLD
    assert aged.recommended_price is None
    assert "STALE_NOT_BELOW_CHEAPEST_COMPETITOR" in aged.reasons


def test_dead_stock_target_is_not_higher_than_the_current_price() -> None:
    stale = recommend_price(
        _context(
            "1500",
            stock_status=StockStatus.DEAD_STOCK,
            stock_age_days=Decimal("365"),
        ),
        _market(),
        _coefficients(),
    )
    dead = recommend_price(
        _context(
            "1500",
            stock_status=StockStatus.DEAD_STOCK,
            stock_age_days=Decimal("730"),
        ),
        _market(),
        _coefficients(),
    )

    assert stale.recommended_price is not None
    assert dead.recommended_price is not None
    assert dead.recommended_price <= stale.recommended_price


@pytest.mark.parametrize(
    "overrides",
    (
        {"stale_age_half_life_days": Decimal("0")},
        {
            "stale_markdown_beta": Decimal("0.6"),
            "dead_stock_markdown_beta": Decimal("0.5"),
        },
        {
            "stale_age_threshold_days": Decimal("30"),
            "dead_stock_age_threshold_days": Decimal("31"),
        },
        {
            "stale_age_half_life_days": Decimal("180"),
            "dead_stock_age_half_life_days": Decimal("181"),
        },
    ),
)
def test_age_policy_rejects_parameters_that_break_dead_stock_dominance(
    overrides: dict[str, Decimal],
) -> None:
    with pytest.raises(ValueError):
        PricingPolicy(**overrides)


def test_missing_cost_does_not_block_market_clearance_recommendation() -> None:
    result = recommend_price(
        _context(
            "1500",
            stock_status=StockStatus.DEAD_STOCK,
            stock_age_days=Decimal("730"),
            cost=None,
        ),
        _market(),
        _coefficients(),
    )

    assert result.action == RecommendationAction.LOWER
    assert result.recommended_price is not None
    assert "MISSING_COST" not in result.reasons


def test_literal_change_metrics_are_exposed() -> None:
    result = recommend_price(_context("800"), _market(), _coefficients())

    assert result.absolute_recommended_change == abs(
        result.recommended_price - result.current_price
    )
    assert result.percentage_recommended_change == (
        result.absolute_recommended_change / result.current_price
    )
    assert "absolute_recommended_change" in RecommendationResponse.model_fields


def test_generic_pricing_response_does_not_expose_cost_derived_values() -> None:
    assert "cost_floor" not in PricingEvaluateResponse.model_fields
    assert "cost_basis_inventory_value" not in PricingEvaluateResponse.model_fields
    assert "cost_floor" not in RecommendationResponse.model_fields
    assert "cost_basis_inventory_value" not in RecommendationResponse.model_fields
    assert "cost" not in CatalogItemResponse.model_fields


def test_catalog_response_redacts_legacy_cost_columns_and_model_field() -> None:
    item = SimpleNamespace(
        id=uuid4(),
        import_batch_id=uuid4(),
        source_row=2,
        sku="SKU-PRIVACY",
        oe_raw="1K0698151E",
        oe_norm="1K0698151E",
        mpn_raw="",
        mpn_norm="",
        name="Brake pad",
        category="brakes",
        brand="KEMP",
        description=None,
        product_url=None,
        current_price=Decimal("1000"),
        currency="UAH",
        is_available=True,
        is_owned=True,
        stock_status="unknown",
        stock_qty=None,
        stock_age_days=None,
        expected_units_sold=None,
        cost=Decimal("987.65"),
        manual_priority=Decimal("1"),
        raw_row={"Себестоимость, грн": "sensitive", "Цена": "1000"},
        created_at=datetime.now(UTC),
    )

    payload = _catalog_item_response(item).model_dump()

    assert "cost" not in payload
    assert payload["cost_configured"] is False
    assert payload["raw_row"] == {"Цена": "1000"}


def test_catalog_response_does_not_label_private_kemp_code_as_oe() -> None:
    item = SimpleNamespace(
        id=uuid4(),
        import_batch_id=uuid4(),
        source_row=2,
        sku="77641360",
        oe_raw="77641360",
        oe_norm="77641360",
        mpn_raw="115",
        mpn_norm="115",
        part_numbers_norm=["115070"],
        identity_status="MPN_ONLY",
        name="Part",
        category="parts",
        brand="KEMP",
        description=None,
        product_url=None,
        current_price=Decimal("1000"),
        currency="UAH",
        is_available=True,
        is_owned=True,
        stock_status="unknown",
        stock_qty=None,
        stock_age_days=None,
        expected_units_sold=None,
        cost=Decimal("987.65"),
        manual_priority=Decimal("1"),
        raw_row={},
        created_at=datetime.now(UTC),
    )

    payload = _catalog_item_response(item).model_dump()

    assert payload["oe_norm"] == ""
    assert payload["mpn_norm"] == "115"
    assert payload["search_identity"] == "115070"
    assert payload["identity_status"] == "MPN_ONLY"


def test_unknown_budget_coefficient_does_not_fall_back_to_one() -> None:
    budget = [replace(item, tier=ProductTier.BUDGET) for item in _market()]

    result = recommend_price(_context("800"), budget, {})

    assert result.action in {
        RecommendationAction.MANUAL_REVIEW,
        RecommendationAction.INSUFFICIENT_DATA,
    }
    assert not result.evidence
    assert all(
        item.reason == "UNVALIDATED_TIER_COEFFICIENT" for item in result.excluded
    )
