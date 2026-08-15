from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from marko.core.config import Settings
from marko.services.no_oe_pricing import (
    NoOePricingError,
    build_no_oe_review_input,
    plan_no_oe_queries,
)


def _snapshot(**overrides):
    return {
        "sku": "SUP-ABC-42",
        "mpn_norm": "ABC42",
        "mpn_raw": "ABC-42",
        "internal_code_raw": "776А1",
        "internal_code_norm": "776A1",
        "name": "Фильтр масляный",
        "brand": "MANN",
        "category": "Фильтры",
        "description": "Для двигателя 2.0",
        "characteristics_raw": {"thread": "M20", "Цена": "999"},
        "current_price": "800.00",
        "cost": "500.00",
        **overrides,
    }


def test_no_oe_query_plan_uses_only_frozen_public_identifiers() -> None:
    plan = plan_no_oe_queries(_snapshot())

    assert plan.queries == ("ABC42", "SUP-ABC-42")
    assert plan.source_fields == ("mpn_norm", "sku")
    assert all("776" not in query for query in plan.queries)


def test_no_oe_query_plan_rejects_embedded_private_kemp() -> None:
    with pytest.raises(NoOePricingError) as error:
        plan_no_oe_queries(
            _snapshot(
                sku="",
                mpn_norm="",
                mpn_raw="",
                name="Фильтр 776А1",
            )
        )

    assert error.value.code == "PRIVATE_KEMP_QUERY_BLOCKED"


def test_luna_input_excludes_money_cost_and_private_kemp_recursively() -> None:
    snapshot = _snapshot()
    plan = plan_no_oe_queries(snapshot)
    payload = build_no_oe_review_input(
        start_snapshot=snapshot,
        exact_offer={
            "offer_id": "offer-1",
            "title": "MANN ABC42",
            "url": "https://prom.ua/p123456789-test.html",
            "seller_id": "seller-1",
            "sale_price": "750.00",
            "raw_snapshot": {
                "price": "750.00",
                "cost_hint": "400.00",
                "brand": "MANN",
            },
        },
        plan=plan,
    )

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).casefold()
    assert "776a1" not in encoded
    assert "776а1" not in encoded
    assert "800.00" not in encoded
    assert "750.00" not in encoded
    assert "500.00" not in encoded
    assert "400.00" not in encoded
    assert "sale_price" not in encoded
    assert "current_price" not in encoded
    assert "cost" not in encoded
    assert "abc42" in encoded


def test_luna_receives_only_server_authored_public_amount_context() -> None:
    snapshot = _snapshot()
    plan = plan_no_oe_queries(snapshot)
    payload = build_no_oe_review_input(
        start_snapshot=snapshot,
        exact_offer={
            "offer_id": "offer-1",
            "title": "MANN ABC42",
            "url": "https://prom.ua/p123456789-test.html",
            "seller_id": "seller-1",
            "sale_price": "300.00",
        },
        plan=plan,
        offer_integrity_context={
            "purpose": "commercial_integrity_only_not_price_setting",
            "displayed_amount": "300.00",
            "customer_amount": "700.00",
            "next_independent_seller_amount": "1000.00",
            "floor_gap_ratio": "0.3",
            "assessment": {
                "status": "MANUAL_REVIEW",
                "reason_codes": ["SINGLE_LISTING_FLOOR_GAP"],
                "evidence": [],
            },
        },
    )

    context = payload["deterministic_context"]["offer_integrity_context"]
    assert context["purpose"] == "commercial_integrity_only_not_price_setting"
    assert context["displayed_amount"] == "300.00"
    assert context["customer_amount"] == "700.00"
    assert context["next_independent_seller_amount"] == "1000.00"
    assert context["assessment"]["reason_codes"] == ["SINGLE_LISTING_FLOOR_GAP"]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).casefold()
    assert "sale_price" not in encoded
    assert "current_price" not in encoded
    assert '"cost"' not in encoded


def test_no_oe_feature_is_disabled_and_bounded_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.pricing_no_oe_discovery_enabled is False
    assert settings.pricing_no_oe_max_items == 20
    assert settings.pricing_no_oe_max_provider_calls == 10


def test_codex_cli_is_rejected_outside_local_test_environments() -> None:
    with pytest.raises(ValidationError, match="codex_cli is local/test only"):
        Settings(
            _env_file=None,
            environment="production",
            pricing_llm_provider="codex_cli",
        )


def test_no_oe_requires_luna_xhigh() -> None:
    with pytest.raises(ValidationError, match="requires gpt-5.6-luna"):
        Settings(
            _env_file=None,
            environment="test",
            pricing_no_oe_discovery_enabled=True,
            pricing_llm_provider="codex_cli",
            pricing_llm_model="different-model",
            pricing_llm_reasoning_effort="xhigh",
        )
    with pytest.raises(ValidationError, match="requires xhigh"):
        Settings(
            _env_file=None,
            environment="test",
            pricing_no_oe_discovery_enabled=True,
            pricing_llm_provider="codex_cli",
            pricing_llm_model="gpt-5.6-luna",
            pricing_llm_reasoning_effort="high",
        )


def test_no_oe_refuses_a_budget_xhigh_reasoning_would_spend_on_itself() -> None:
    """A measured xhigh review spends ~6.2k reasoning tokens and 71 s.

    Below these floors nothing degrades: the provider is paid, answers
    ``incomplete``, and the run records no verdict at all.  Boot has to fail.
    """

    with pytest.raises(ValidationError, match="MAX_OUTPUT_TOKENS"):
        Settings(
            _env_file=None,
            environment="test",
            pricing_no_oe_discovery_enabled=True,
            pricing_llm_provider="codex_cli",
            pricing_llm_model="gpt-5.6-luna",
            pricing_llm_reasoning_effort="xhigh",
            pricing_llm_max_output_tokens=1600,
        )
    with pytest.raises(ValidationError, match="TIMEOUT_SECONDS"):
        Settings(
            _env_file=None,
            environment="test",
            pricing_no_oe_discovery_enabled=True,
            pricing_llm_provider="codex_cli",
            pricing_llm_model="gpt-5.6-luna",
            pricing_llm_reasoning_effort="xhigh",
            pricing_llm_timeout_seconds=60,
        )


def test_default_llm_budget_can_hold_an_xhigh_verdict() -> None:
    settings = Settings(_env_file=None)

    assert settings.pricing_llm_max_output_tokens >= 12_000
    assert settings.pricing_llm_timeout_seconds >= 120


def test_no_oe_task_time_limit_can_hold_the_work_it_schedules() -> None:
    """Enrichment plus every review it is allowed to make must fit.

    The task used to carry a hardcoded 600 s soft limit while its own budget
    permits ``pricing_no_oe_max_provider_calls`` reviews at up to
    ``pricing_llm_timeout_seconds`` each -- 1800 s of reviews alone.  It could
    only ever end in SoftTimeLimitExceeded and a retry.
    """

    settings = Settings(_env_file=None)
    reviews = (
        settings.pricing_no_oe_max_provider_calls * settings.pricing_llm_timeout_seconds
    )

    assert settings.no_oe_discovery_task_soft_time_limit_seconds >= reviews
    assert (
        settings.no_oe_discovery_task_time_limit_seconds
        > settings.no_oe_discovery_task_soft_time_limit_seconds
    )
