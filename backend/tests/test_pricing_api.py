from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from marko.api.dependencies import get_current_user
from marko.api.main import app
from marko.infrastructure.db.models import User
from marko.services.auth import AuthContext
from marko.services.pricing_runs import (
    PricingRunError,
    _merge_catalog_override_snapshot,
    _validate_decision_price,
    policy_from_dict,
    policy_to_dict,
)


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
    assert snapshot["cost"] == Decimal("600")
    assert snapshot["stock_qty"] == Decimal("10")
    assert snapshot["below_cost_floor"] is None
    assert snapshot["below_cost_warning_confirmed"] is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"allow_below_cost": False}, "explicit allow_below_cost"),
        ({"warning_confirmed": False}, "explicitly confirmed"),
        ({"stock_status": "stale"}, "only for dead_stock"),
        ({"approved_floor": None}, "approved floor"),
        ({"new_price": Decimal("600")}, "below the approved"),
    ],
)
def test_decision_api_rejects_unsafe_below_cost_price(overrides, message) -> None:
    values = {
        "new_price": Decimal("850"),
        "cost": Decimal("1200"),
        "stock_status": "dead_stock",
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
            stock_status="dead_stock",
            approved_floor=Decimal("700"),
            allow_below_cost=True,
            warning_confirmed=True,
        )
        is True
    )


@pytest.mark.asyncio
async def test_authenticated_evaluate_endpoint_returns_actionable_result():
    user = User(id=uuid4(), email="seller@example.com", is_active=True)

    async def current_user_override():
        return AuthContext(user=user, workspace_id=uuid4())

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
                    "age_hours": "1",
                    "match_confidence": "0.95",
                    "tier": "budget",
                    "tier_confidence": "0.95",
                }
                for index in range(5)
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
    assert body["recommended_price"] == "920"
    assert body["competitor_count"] == 5
    assert body["priority_score_type"] == "gross_uplift_opportunity"
    assert body["raw_competitor_count"] == 5
    assert body["unique_seller_count"] == 5
    assert body["clean_competitor_count"] == 5
    assert body["outlier_method"] == "mad"
    assert body["action_gates_passed"] is True
    assert body["evidence"][0]["multiplier"] == "1"
    assert body["evidence"][0]["normalized_price"] == body["evidence"][0]["raw_price"]
