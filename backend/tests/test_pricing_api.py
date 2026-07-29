from decimal import Decimal
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from marko.api.dependencies import get_current_user
from marko.api.main import app
from marko.infrastructure.db.models import User, WorkspaceRole
from marko.services.auth import AuthContext
from marko.services.pricing_runs import (
    PricingRunError,
    _merge_catalog_override_snapshot,
    _recommendation_sort_order,
    _validate_decision_price,
    activation_artifact_verified,
    policy_from_dict,
    policy_to_dict,
    require_activated_run_policy,
)
from metis.pricing import comparison_evidence_to_dict, verified_comparison_evidence


def test_policy_round_trip_preserves_decimal_and_enum_types():
    policy = policy_from_dict(
        {
            "confidence_aggregation": "minimum",
            "confidence_min": "0.61",
            "min_competitors": 6,
            "kemp_dumping_ratio": "0.80",
        }
    )

    assert policy.confidence_min == Decimal("0.61")
    assert policy.min_competitors == 6
    assert policy.confidence_aggregation.value == "minimum"
    assert policy_to_dict(policy)["confidence_min"] == "0.61"
    assert policy_to_dict(policy)["dispersion_method"] == "legacy_mad"


def test_policy_versions_select_explicit_backward_compatible_dispersion() -> None:
    legacy = policy_from_dict({"version": "pricing-v2"})
    robust = policy_from_dict({"version": "pricing-v3-robust-dispersion"})
    robust_round_trip = policy_from_dict(policy_to_dict(robust))

    assert legacy.dispersion_method.value == "legacy_mad"
    assert robust.dispersion_method.value == "qn"
    assert robust_round_trip == robust


def test_policy_rejects_silent_v2_redefinition_and_unknown_profile() -> None:
    with pytest.raises(PricingRunError, match="pricing-v2 requires"):
        policy_from_dict({"version": "pricing-v2", "dispersion_method": "qn"})
    with pytest.raises(PricingRunError, match="profile_version"):
        policy_from_dict({"robust_dispersion_profile_version": "unversioned"})
    with pytest.raises(PricingRunError, match="at least 2"):
        policy_from_dict({"robust_scale_max_cohort_size": 1})


def test_v3_persisted_run_activation_is_fail_closed_by_default() -> None:
    policy = policy_from_dict({"version": "pricing-v3-robust-dispersion"})

    with pytest.raises(PricingRunError, match="activation is NO_GO"):
        require_activated_run_policy(policy, robust_v3_enabled=False)
    with pytest.raises(PricingRunError, match="activation is NO_GO"):
        require_activated_run_policy(policy, robust_v3_enabled=True)
    require_activated_run_policy(
        policy,
        robust_v3_enabled=True,
        activation_artifact_verified=True,
    )


def test_activation_artifact_requires_exact_file_hash(tmp_path) -> None:
    artifact = tmp_path / "activation.json"
    artifact.write_text('{"approved":false}', encoding="utf-8")
    expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert activation_artifact_verified(str(artifact), expected)
    assert not activation_artifact_verified(str(artifact), "0" * 64)
    assert not activation_artifact_verified(str(tmp_path / "missing"), expected)


def test_policy_rejects_unknown_and_out_of_range_values():
    with pytest.raises(PricingRunError, match="Unknown"):
        policy_from_dict({"magic": 1})
    with pytest.raises(PricingRunError, match=r"\[0, 1\]"):
        policy_from_dict({"confidence_min": "1.1"})
    with pytest.raises(PricingRunError, match="minimum_margin"):
        policy_from_dict({"minimum_margin": "-0.01"})


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"freshness_half_life_hours": "-1"}, "greater than zero"),
        ({"price_tick": "0"}, "greater than zero"),
        (
            {"min_competitors": 5, "iqr_min_competitors": 4},
            "iqr_min_competitors",
        ),
        ({"shrinkage_k": "-1"}, "greater than zero"),
        ({"min_competitors": 2}, "at least 3"),
        ({"currency": "UA"}, "three-letter"),
        ({"max_dispersion": "0"}, "greater than zero"),
    ],
)
def test_policy_validation_rejects_dangerous_configuration(payload, message):
    with pytest.raises(PricingRunError, match=message):
        policy_from_dict(payload)


def test_catalog_override_is_a_cumulative_snapshot() -> None:
    previous = SimpleNamespace(
        stock_status="dead_stock",
        cost=Decimal("600"),
        stock_qty=Decimal("10"),
        stock_age_days=Decimal("800"),
        expected_units_sold=Decimal("0"),
        manual_priority=Decimal("2"),
        liquidity_target=Decimal("1"),
        urgency=Decimal("1"),
        allow_below_cost=True,
        below_cost_floor=Decimal("350"),
    )

    snapshot = _merge_catalog_override_snapshot(
        {"stock_status": "stale", "allow_below_cost": False}, previous
    )

    assert snapshot["stock_status"] == "stale"
    assert "cost" not in snapshot
    assert snapshot["stock_qty"] == Decimal("10")
    assert "below_cost_floor" not in snapshot
    assert snapshot["below_cost_warning_confirmed"] is False


def test_absolute_change_sort_is_literal_and_queue_independent() -> None:
    order = _recommendation_sort_order("ABSOLUTE_RECOMMENDED_CHANGE")

    assert "absolute_recommended_change" in str(order[0])
    assert "priority_score" not in str(order[0])
    assert "confidence" in str(order[1])
    with pytest.raises(PricingRunError, match="Unknown recommendation sort"):
        _recommendation_sort_order("priority")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"allow_below_cost": False}, "explicit allow_below_cost"),
        ({"warning_confirmed": False}, "explicitly confirmed"),
        ({"new_price": Decimal("600")}, "below the approved"),
    ],
)
def test_decision_api_rejects_unsafe_below_cost_price(overrides, message) -> None:
    values = {
        "new_price": Decimal("850"),
        "cost": Decimal("1200"),
        "approved_floor": Decimal("700"),
        "allow_below_cost": True,
        "warning_confirmed": True,
    }
    values.update(overrides)

    with pytest.raises(PricingRunError, match=message):
        _validate_decision_price(**values)


def test_decision_api_accepts_authorized_below_cost_price() -> None:
    assert (
        _validate_decision_price(
            new_price=Decimal("850"),
            cost=Decimal("1200"),
            approved_floor=Decimal("700"),
            allow_below_cost=True,
            warning_confirmed=True,
        )
        is True
    )


def test_below_cost_floor_is_optional_and_not_a_universal_market_floor() -> None:
    assert _validate_decision_price(
        new_price=Decimal("850"),
        cost=Decimal("1200"),
        approved_floor=None,
        allow_below_cost=True,
        warning_confirmed=True,
    )


@pytest.mark.asyncio
async def test_authenticated_evaluate_endpoint_returns_actionable_result():
    user = User(id=uuid4(), email="seller@example.com", is_active=True)

    async def current_user_override():
        return AuthContext(
            user=user,
            workspace_id=uuid4(),
            workspace_role=WorkspaceRole.member,
        )

    app.dependency_overrides[get_current_user] = current_user_override
    try:
        payload = {
            "context": {
                "sku": "SKU-1",
                "category": "brakes",
                "current_price": "800",
                "expected_units_sold": "10",
            },
            "offers": [
                {
                    "observation_id": f"obs-{index}",
                    "seller_id": f"seller-{index}",
                    "seller_name": f"Seller {index}",
                    "price": str(1000 + index * 50),
                    "currency": "UAH",
                    "currency_raw": "UAH",
                    "age_hours": "1",
                    "match_confidence": "0.95",
                    "tier": "budget",
                    "tier_confidence": "0.95",
                    "source_confidence": "1",
                    "comparison_evidence": comparison_evidence_to_dict(
                        verified_comparison_evidence(
                            stable_seller_id=f"seller-{index}",
                            source_record_id=f"obs-{index}",
                        )
                    ),
                }
                for index in range(5)
            ],
            "coefficients": [
                {
                    "category": "brakes",
                    "tier": "budget",
                    "multiplier": "1",
                    "model": "shrinkage",
                    "method_version": "pricing-api-yuri-v1",
                    "coefficient_version": "pricing-api-yuri-v1:synthetic",
                    "sample_size": 20,
                    "effective_sample_size": "18",
                    "confidence": "0.95",
                    "validated": True,
                    "interval_low": "0.9",
                    "interval_high": "1.1",
                    "dataset_hash": "a" * 64,
                }
            ],
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/pricing/evaluate", json=payload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "RAISE"
    assert body["recommended_price"] == "1000"
    assert body["competitor_count"] == 5
    assert body["priority_score_type"] == "gross_uplift_opportunity"
    assert body["raw_competitor_count"] == 5
    assert body["unique_seller_count"] == 5
    assert body["clean_competitor_count"] == 5
    assert body["outlier_method"] == "mad"
    assert body["dispersion_method"] == "legacy_mad"
    assert body["dispersion_profile"]["profile_version"] == "rc-scale-v1"
    assert body["dispersion_profile"]["sample_stage"] == "post_clean"
    assert body["dispersion_profile"]["gaussian_scales"]["qn"]
    assert body["action_gates_passed"] is True
    assert body["evidence"][0]["multiplier"] == "1"
    assert body["evidence"][0]["normalized_price"] == body["evidence"][0]["raw_price"]


def test_openapi_exposes_additive_dispersion_contract() -> None:
    schemas = app.openapi()["components"]["schemas"]
    properties = schemas["PricingEvaluateResponse"]["properties"]
    stored_properties = schemas["RecommendationResponse"]["properties"]

    assert "dispersion_method" in properties
    assert "dispersion_profile" in properties
    assert "dispersion_method" in stored_properties
    assert "dispersion_profile" in stored_properties
