from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from copy import deepcopy
from types import SimpleNamespace

from metis.pricing import (
    CompetitorOffer,
    ProductPricingContext,
    ProductTier,
    robust_dispersion_trace,
    recommend_price,
    verified_comparison_evidence,
)
from marko.services.recommendation_replay import (
    REPLAY_CONTRACT_V1,
    REPLAY_CONTRACT_V2,
    REPLAY_CONTRACT_V6,
    REPLAY_CONTRACT_VERSION,
    compare_replayed_result,
    context_from_snapshot,
)


def _pricing_result():
    context = ProductPricingContext(
        sku="SKU-REPLAY",
        category="brakes",
        current_price=Decimal("800"),
        expected_units_sold=Decimal("10"),
    )
    offers = [
        CompetitorOffer(
            observation_id=f"obs-{index}",
            seller_id=f"seller-{index}",
            seller_name=f"Seller {index}",
            price=Decimal(1000 + index * 50),
            currency="UAH",
            is_available=True,
            age_hours=Decimal("1"),
            match_confidence=Decimal("0.95"),
            tier=ProductTier.BUDGET,
            tier_confidence=Decimal("0.95"),
            source_confidence=Decimal("1"),
            currency_raw="UAH",
            comparison_evidence=verified_comparison_evidence(
                stable_seller_id=f"seller-{index}",
                source_record_id=f"obs-{index}",
            ),
        )
        for index in range(5)
    ]
    return recommend_price(context, offers, {})


def _stored_recommendation(result):
    return SimpleNamespace(
        action=result.action.value,
        current_price=result.current_price,
        fair_price=result.fair_price,
        recommended_price=result.recommended_price,
        lower_bound=result.lower_bound,
        upper_bound=result.upper_bound,
        confidence=result.confidence,
        confidence_grade=result.confidence_grade,
        weakest_factor=result.weakest_factor,
        competitor_count=result.competitor_count,
        raw_competitor_count=result.raw_competitor_count,
        unique_seller_count=result.unique_seller_count,
        clean_competitor_count=result.clean_competitor_count,
        effective_competitor_count=result.effective_competitor_count,
        dispersion=result.dispersion,
        outlier_method=result.outlier_method,
        outlier_count=result.outlier_count,
        sensitivity=result.sensitivity,
        action_gates_passed=result.action_gates_passed,
        cost_floor=result.cost_floor,
        priority_score=result.priority_score,
        priority_score_type=result.priority_score_type.value,
        review_priority=result.review_priority,
        reason_codes=list(result.reasons),
        evidence_observation_ids=[offer.observation_id for offer in result.evidence],
        policy_version=result.policy_version,
    )


def test_context_snapshot_rebuilds_frozen_pricing_input() -> None:
    context = context_from_snapshot(
        {
            "sku": "SKU-1",
            "category": "brakes",
            "currency": "UAH",
            "current_price": "800.00",
            "stock_status": "dead_stock",
            "cost": "600",
            "stock_qty": "12",
            "stock_age_days": "730",
            "expected_units_sold": "0",
            "liquidity_target": "1",
            "urgency": "0.8",
            "manual_priority": "2",
            "allow_below_cost": True,
            "below_cost_floor": "450",
            "below_cost_authorization_id": "override-1",
            "below_cost_authorized_by": "user-1",
            "below_cost_authorized_at": "2026-07-16T10:00:00+00:00",
            "below_cost_reason": "Clearance",
            "below_cost_warning_confirmed": True,
        }
    )

    assert context.sku == "SKU-1"
    assert context.current_price == Decimal("800.00")
    assert context.stock_status.value == "dead_stock"
    assert context.cost is None
    assert context.below_cost_floor is None
    assert context.below_cost_warning_confirmed is True


def test_current_replay_contract_is_v6_and_compares_current_trace() -> None:
    result = _pricing_result()
    stored = _stored_recommendation(result)
    stored.calculation_trace = {
        "replay_contract_version": REPLAY_CONTRACT_V6,
        "robust_dispersion": robust_dispersion_trace(
            selected_method=result.dispersion_method,
            pre_clean=result.pre_clean_dispersion_profile,
            post_clean=result.dispersion_profile,
        ),
        "comparability": {
            "automatic_eligible": result.automatic_eligible,
            "verified_seller_count": result.verified_seller_count,
            "policy_id": result.comparability_policy_id,
            "policy_hash": result.comparability_policy_hash,
            "hard_gates": dict(result.hard_gate_results),
            "failed_hard_gates": list(result.failed_hard_gates),
            "unknown_hard_fields": list(result.unknown_hard_fields),
        },
        "robust_diagnostic": None,
        "robust_policy_fingerprint": dict(result.robust_policy_fingerprint),
        "llm_comparability": {
            "mode": "off",
            "required": False,
            "reviews": [],
        },
    }

    assert REPLAY_CONTRACT_VERSION == REPLAY_CONTRACT_V6
    mismatches = compare_replayed_result(
        stored,
        result,
        replay_contract_version=REPLAY_CONTRACT_V6,
    )
    # The synthetic result has a diagnostic while this minimal frozen test
    # trace intentionally does not.  All other V6 contract fields replay.
    assert set(mismatches) <= {"robust_diagnostic"}


def test_replay_comparator_detects_exact_match_and_drift() -> None:
    result = _pricing_result()
    stored = _stored_recommendation(result)

    assert compare_replayed_result(stored, result) == {}

    drifted = replace(result, recommended_price=Decimal("999"))
    mismatches = compare_replayed_result(stored, drifted)

    assert (
        mismatches["recommended_price"]["stored"]
        != mismatches["recommended_price"]["replayed"]
    )


def test_replay_v1_remains_accepted_without_new_profile_fields() -> None:
    result = _pricing_result()
    stored = _stored_recommendation(result)

    assert (
        compare_replayed_result(
            stored,
            result,
            replay_contract_version=REPLAY_CONTRACT_V1,
        )
        == {}
    )


def test_replay_v2_compares_method_profile_versions_and_constants() -> None:
    result = _pricing_result()
    stored = _stored_recommendation(result)
    stored.calculation_trace = {
        "replay_contract_version": REPLAY_CONTRACT_V2,
        "robust_dispersion": robust_dispersion_trace(
            selected_method=result.dispersion_method,
            pre_clean=result.pre_clean_dispersion_profile,
            post_clean=result.dispersion_profile,
        ),
    }

    assert compare_replayed_result(stored, result) == {}

    mutations = {
        "dispersion_method": ("selected_method", "qn"),
        "profile_version": ("profile_version", "rc-scale-mutated"),
    }
    for expected_field, (trace_field, mutated_value) in mutations.items():
        mutated = deepcopy(stored.calculation_trace)
        mutated["robust_dispersion"][trace_field] = mutated_value
        stored.calculation_trace = mutated
        mismatches = compare_replayed_result(stored, result)
        assert expected_field in mismatches

    mutated = deepcopy(stored.calculation_trace)
    mutated["robust_dispersion"]["profile_version"] = "rc-scale-v1"
    mutated["robust_dispersion"]["constants"]["qn_normal"] = "2.2219"
    stored.calculation_trace = mutated
    assert "robust_constants" in compare_replayed_result(stored, result)
