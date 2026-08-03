"""Cost estimation, telemetry, and the read surface for AI evidence extraction.

Nothing here talks to a provider.  Every "call" is a fixture, and the point of
the suite is the four ways a token bill goes wrong quietly -- stale rates,
binary floats, unpriced reasoning output, and cache reads charged as fresh
input -- plus the two ways a read surface leaks: another workspace's rows and
the model's hidden reasoning.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from marko.api.dependencies import get_current_user, get_session
from marko.api.main import app
from marko.api.routers.v1 import pricing as pricing_router
from marko.infrastructure.db.models import User, WorkspaceRole
from marko.services.auth import AuthContext
from marko.services.ai_cost_policy import (
    AiCostPolicyError,
    AiRateCard,
    DEFAULT_RATE_REGISTRY,
    DEFAULT_RATE_VERSION,
    ESTIMATE_DISCLAIMER,
    LUNA_STANDARD_2026_07_30,
    RateCardRegistry,
    TokenUsage,
    cost_independent_digest,
    estimate_cost,
    estimate_from_provider_payload,
    rate_card_from_mapping,
    registry_from_config,
    resolve_rate_card,
    usage_from_provider_payload,
    usage_telemetry_payload,
)
from marko.services.cost_privacy import privacy_safe_mapping
from marko.services.scraper_metrics import (
    AiEvidenceExtractionView,
    AiEvidenceTelemetry,
    AiEvidenceTelemetryError,
    ai_evidence_telemetry_snapshot,
    assert_publishable,
    public_evidence_payload,
    record_ai_evidence_outcome,
    render_ai_evidence_prometheus,
    reset_ai_evidence_telemetry,
    summarize_ai_evidence_extractions,
)


FAKE_API_KEY = "sk-live-marko-r6-not-a-real-key-0123456789"
HIDDEN_REASONING = "PRIVATE CHAIN OF THOUGHT THAT MUST NEVER SHIP"


# ---------------------------------------------------------------------------
# 1. Versioned rate policy
# ---------------------------------------------------------------------------


def test_luna_snapshot_carries_the_announced_2026_07_30_standard_rates() -> None:
    """Stale-rate trap: an older $1 / $6-style card must not survive here."""

    card = LUNA_STANDARD_2026_07_30

    assert card.model_id == "gpt-5.6-luna"
    assert card.effective_date == date(2026, 7, 30)
    assert card.uncached_input_usd_per_million == Decimal("0.20")
    assert card.cached_input_usd_per_million == Decimal("0.02")
    assert card.output_usd_per_million == Decimal("1.20")
    assert card.reasoning_billed_as_output is True

    estimate = estimate_cost(
        TokenUsage(
            input_tokens=1_000_000,
            cached_input_tokens=400_000,
            output_tokens=50_000,
            reasoning_tokens=30_000,
        ),
        card,
    )

    assert estimate.uncached_input_usd == Decimal("0.12")
    assert estimate.cached_input_usd == Decimal("0.008")
    assert estimate.output_usd == Decimal("0.06")
    assert estimate.total_usd == Decimal("0.188")
    # A stale $1 uncached / $6 output card would land near USD 0.90.
    assert estimate.total_usd < Decimal("0.25")


def test_every_estimate_is_labelled_an_estimate_and_names_its_rate_version() -> None:
    usage = TokenUsage(input_tokens=10, cached_input_tokens=4, output_tokens=6)
    estimate = estimate_cost(usage)

    assert estimate.disclaimer == ESTIMATE_DISCLAIMER == "ESTIMATE_NOT_BILLING_TRUTH"
    assert estimate.rate_version == DEFAULT_RATE_VERSION
    assert estimate.as_dict()["disclaimer"] == "ESTIMATE_NOT_BILLING_TRUTH"

    persisted = usage_telemetry_payload(usage, estimate)

    assert persisted["spend_estimate"]["rate_version"] == DEFAULT_RATE_VERSION
    assert persisted["spend_estimate"]["rates_effective_date"] == "2026-07-30"
    assert persisted["input_tokens"] == 10
    with pytest.raises(AiCostPolicyError, match="does not describe this usage"):
        usage_telemetry_payload(TokenUsage(input_tokens=11, output_tokens=6), estimate)


def test_estimates_use_exact_decimal_arithmetic_never_binary_floats() -> None:
    """Float trap: these three components all differ under IEEE-754 doubles."""

    estimate = estimate_cost(
        TokenUsage(
            input_tokens=12_345_678,
            cached_input_tokens=7_777_777,
            output_tokens=3_333_333,
            reasoning_tokens=1_111_111,
        )
    )

    assert isinstance(estimate.total_usd, Decimal)
    assert estimate.uncached_input_usd == Decimal("0.9135802")
    assert estimate.cached_input_usd == Decimal("0.15555554")
    assert estimate.output_usd == Decimal("3.9999996")
    assert estimate.total_usd == Decimal("5.06913534")
    # The float results of the same arithmetic, spelled out.
    assert estimate.uncached_input_usd != Decimal("0.9135802000000001")
    assert estimate.cached_input_usd != Decimal("0.15555554000000002")
    assert estimate.output_usd != Decimal("3.9999995999999998")
    assert (
        estimate.uncached_input_usd + estimate.cached_input_usd + estimate.output_usd
        == estimate.total_usd
    )


def test_rate_cards_refuse_float_money_at_every_entry_point() -> None:
    with pytest.raises(AiCostPolicyError, match="must be a Decimal"):
        AiRateCard(
            rate_version="floaty",
            model_id="gpt-5.6-luna",
            effective_date=date(2026, 7, 30),
            uncached_input_usd_per_million=0.20,  # type: ignore[arg-type]
            cached_input_usd_per_million=Decimal("0.02"),
            output_usd_per_million=Decimal("1.20"),
        )
    with pytest.raises(AiCostPolicyError, match="not a float"):
        rate_card_from_mapping(
            {
                "rate_version": "floaty-config",
                "model_id": "gpt-5.6-luna",
                "effective_date": "2026-07-30",
                "uncached_input_usd_per_million": 0.2,
                "cached_input_usd_per_million": "0.02",
                "output_usd_per_million": "1.20",
            }
        )


def test_cached_input_is_priced_at_the_cache_read_rate() -> None:
    """Cache-read trap: cached tokens must not be billed as fresh input."""

    usage = TokenUsage(
        input_tokens=1_000_000,
        cached_input_tokens=900_000,
        output_tokens=0,
    )
    estimate = estimate_cost(usage)

    assert estimate.cached_input_usd == Decimal("0.018")
    assert estimate.uncached_input_usd == Decimal("0.02")
    assert estimate.total_usd == Decimal("0.038")
    # Pricing every input token at the uncached rate would give USD 0.20;
    # double counting the cached tokens on both lines would give USD 0.218.
    assert estimate.total_usd != Decimal("0.20")
    assert estimate.total_usd != Decimal("0.218")
    assert usage.uncached_input_tokens == 100_000


def test_reasoning_output_is_priced_once_and_can_never_go_missing() -> None:
    """Reasoning is billed as output and is already inside ``output_tokens``."""

    payload = {
        "input_tokens": 1_000,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 100_000,
        "output_tokens_details": {"reasoning_tokens": 90_000},
        "total_tokens": 101_000,
    }
    estimate = estimate_from_provider_payload(payload)

    assert estimate.usage.reasoning_tokens == 90_000
    assert estimate.output_usd == Decimal("0.12")
    # Charging reasoning a second time on top of output would give USD 0.228.
    assert estimate.total_usd == Decimal("0.1202")

    with pytest.raises(AiCostPolicyError, match="missing an output token count"):
        usage_from_provider_payload({"input_tokens": 1_000})
    with pytest.raises(AiCostPolicyError, match="internally inconsistent"):
        usage_from_provider_payload(
            {
                "input_tokens": 1_000,
                "output_tokens": 10_000,
                "output_tokens_details": {"reasoning_tokens": 9_000},
                # The provider counted reasoning in the total but the caller
                # dropped it from ``output_tokens``.
                "total_tokens": 20_000,
            }
        )
    with pytest.raises(AiCostPolicyError, match="subset of output_tokens"):
        TokenUsage(input_tokens=10, output_tokens=5, reasoning_tokens=9)


def test_rate_cards_are_versioned_configurable_and_resolvable() -> None:
    later = rate_card_from_mapping(
        {
            "rate_version": "openai-gpt-5.6-luna-standard-2026-09-01",
            "model_id": "gpt-5.6-luna",
            "effective_date": "2026-09-01",
            "uncached_input_usd_per_million": "0.30",
            "cached_input_usd_per_million": "0.03",
            "output_usd_per_million": "1.50",
        }
    )
    registry = DEFAULT_RATE_REGISTRY.extended([later])

    assert resolve_rate_card(registry=registry).rate_version == DEFAULT_RATE_VERSION
    assert (
        resolve_rate_card(
            model_id="gpt-5.6-luna", registry=registry, as_of=date(2026, 8, 15)
        ).rate_version
        == DEFAULT_RATE_VERSION
    )
    assert (
        resolve_rate_card(
            model_id="gpt-5.6-luna", registry=registry, as_of=date(2026, 10, 1)
        )
        is later
    )
    with pytest.raises(AiCostPolicyError, match="unknown rate_version"):
        resolve_rate_card(rate_version="does-not-exist", registry=registry)
    with pytest.raises(AiCostPolicyError, match="no rate card for model"):
        resolve_rate_card(model_id="gpt-4o", registry=registry)
    with pytest.raises(AiCostPolicyError, match="duplicate rate_version"):
        RateCardRegistry((LUNA_STANDARD_2026_07_30, LUNA_STANDARD_2026_07_30))

    from_json = registry_from_config(
        json.dumps(
            [
                {
                    "rate_version": "operator-override-1",
                    "model_id": "gpt-5.6-luna",
                    "effective_date": "2026-10-01",
                    "uncached_input_usd_per_million": "0.25",
                    "cached_input_usd_per_million": "0.025",
                    "output_usd_per_million": "1.40",
                }
            ]
        )
    )
    assert "operator-override-1" in from_json.versions()
    assert DEFAULT_RATE_VERSION in from_json.versions()


def test_a_rate_change_moves_the_estimate_and_nothing_else() -> None:
    """Identity, cached evidence, eligibility, and verification are price-free."""

    doubled = AiRateCard(
        rate_version="synthetic-doubled",
        model_id="gpt-5.6-luna",
        effective_date=date(2026, 12, 1),
        uncached_input_usd_per_million=Decimal("0.40"),
        cached_input_usd_per_million=Decimal("0.04"),
        output_usd_per_million=Decimal("2.40"),
    )
    row = _extraction_row()
    view = AiEvidenceExtractionView.from_row(row)
    usage = view.usage
    assert usage is not None

    before = usage_telemetry_payload(usage, estimate_cost(usage))
    after = usage_telemetry_payload(usage, estimate_cost(usage, doubled))
    record_before = {**view.as_public_dict(), "spend_estimate": before}
    record_after = {**view.as_public_dict(), "spend_estimate": after}

    assert after["spend_estimate"]["total_usd"] != before["spend_estimate"]["total_usd"]
    assert cost_independent_digest(record_before) == cost_independent_digest(
        record_after
    )
    for field_name in (
        "extraction_id",
        "status",
        "verification_result",
        "verification_reasons",
        "fields",
        "prompt_version",
        "schema_version",
        "shadow_only",
    ):
        assert record_before[field_name] == record_after[field_name]


def test_read_surface_prefers_the_rate_version_persisted_with_the_usage() -> None:
    row = _extraction_row()
    row.usage = {
        "input_tokens": 10,
        "cached_input_tokens": 0,
        "output_tokens": 5,
        "reasoning_tokens": 2,
        "spend_estimate": {
            "rate_version": "historical-rate-v1",
            "model_id": "gpt-5.6-luna",
            "rates_effective_date": "2026-07-30",
            "currency": "USD",
            "uncached_input_usd": "0.000002",
            "cached_input_usd": "0",
            "output_usd": "0.000006",
            "total_usd": "0.000008",
            "rates_per_million": {
                "uncached_input": "0.20",
                "cached_input": "0.02",
                "output": "1.20",
            },
            "disclaimer": "ESTIMATE_NOT_BILLING_TRUTH",
        },
    }

    response = pricing_router._ai_evidence_spend_response(
        AiEvidenceExtractionView.from_row(row)
    )

    assert response.available is True
    assert response.rate_version == "historical-rate-v1"
    assert response.total_usd == Decimal("0.000008")


def test_unknown_explicit_model_never_falls_back_to_luna_rates() -> None:
    row = _extraction_row()
    row.model_id = "unpriced-model"
    row.provider_model = "unpriced-model-version"

    response = pricing_router._ai_evidence_spend_response(
        AiEvidenceExtractionView.from_row(row)
    )

    assert response.available is False
    assert response.reason == "rate_card_unavailable"
    assert response.rate_version is None
    assert response.total_usd is None


# ---------------------------------------------------------------------------
# 2. Telemetry
# ---------------------------------------------------------------------------


def test_telemetry_counts_every_outcome_with_latency_tokens_and_estimate() -> None:
    telemetry = AiEvidenceTelemetry()
    usage = TokenUsage(
        input_tokens=200_000,
        cached_input_tokens=150_000,
        output_tokens=20_000,
        reasoning_tokens=12_000,
    )
    for outcome in (
        "requested",
        "cached",
        "completed",
        "schema_invalid",
        "citation_rejected",
        "conflict",
        "unconfigured",
        "budget_exhausted",
    ):
        telemetry.record(outcome)
    telemetry.record(
        "completed",
        latency_ms=850.0,
        usage=usage,
        rate_version=DEFAULT_RATE_VERSION,
        provider_attempts=2,
    )

    snapshot = ai_evidence_telemetry_snapshot(telemetry)

    assert snapshot["counters"]["completed"] == 2
    assert snapshot["counters"]["provider_attempts"] == 2
    assert snapshot["counters"]["budget_exhausted"] == 1
    assert snapshot["counters"]["citation_rejected"] == 1
    assert snapshot["counters"]["unconfigured"] == 1
    assert snapshot["latency_ms"]["p50"] == 850.0
    assert snapshot["tokens"]["cached_input_tokens"] == 150_000
    assert snapshot["tokens"]["reasoning_tokens"] == 12_000
    assert snapshot["spend_estimate"]["available"] is True
    assert snapshot["spend_estimate"]["rate_version"] == DEFAULT_RATE_VERSION
    assert Decimal(snapshot["spend_estimate"]["total_usd"]) == Decimal("0.037")
    assert snapshot["estimate_disclaimer"] == "ESTIMATE_NOT_BILLING_TRUTH"

    with pytest.raises(AiEvidenceTelemetryError, match="unknown ai evidence outcome"):
        telemetry.record("definitely_not_an_outcome")


def test_telemetry_never_carries_secrets_or_hidden_reasoning() -> None:
    telemetry = AiEvidenceTelemetry()
    telemetry.record("completed", latency_ms=10.0, usage=TokenUsage(5, 0, 5))
    snapshot = ai_evidence_telemetry_snapshot(telemetry)
    rendered = json.dumps(snapshot) + render_ai_evidence_prometheus(snapshot)

    assert FAKE_API_KEY not in rendered
    assert "api_key" not in rendered
    assert HIDDEN_REASONING not in rendered

    scrubbed = public_evidence_payload(
        {
            "reasoning_effort": "medium",
            "reasoning_tokens": 42,
            "reasoning_summary": HIDDEN_REASONING,
            "chain_of_thought": HIDDEN_REASONING,
            "raw_response": {"reasoning": HIDDEN_REASONING},
            "api_key": FAKE_API_KEY,
            "note": f"provider replied with {FAKE_API_KEY}",
            "fields": [{"excerpt": "OE 1K0615301AA", "thoughts": HIDDEN_REASONING}],
        }
    )

    assert scrubbed["reasoning_effort"] == "medium"
    assert scrubbed["reasoning_tokens"] == 42
    assert "reasoning_summary" not in scrubbed
    assert "chain_of_thought" not in scrubbed
    assert "raw_response" not in scrubbed
    assert "api_key" not in scrubbed
    assert FAKE_API_KEY not in scrubbed["note"]
    assert scrubbed["fields"][0] == {"excerpt": "OE 1K0615301AA"}
    assert_publishable(scrubbed)

    with pytest.raises(AiEvidenceTelemetryError, match="hidden reasoning"):
        assert_publishable({"reasoning_text": HIDDEN_REASONING})
    with pytest.raises(AiEvidenceTelemetryError, match="secret configuration"):
        assert_publishable({"pricing_ai_evidence_api_key": "x"})


def test_prometheus_render_marks_the_estimate_as_not_billing_truth() -> None:
    telemetry = AiEvidenceTelemetry()
    telemetry.record(
        "completed",
        latency_ms=120.0,
        usage=TokenUsage(1_000_000, 0, 1_000_000),
        rate_version=DEFAULT_RATE_VERSION,
    )
    rendered = render_ai_evidence_prometheus(ai_evidence_telemetry_snapshot(telemetry))

    assert 'marko_ai_evidence_outcomes_total{outcome="completed"} 1' in rendered
    assert 'marko_ai_evidence_tokens_total{kind="output_tokens"} 1000000' in rendered
    assert 'estimate="not_billing_truth"' in rendered
    assert f'rate_version="{DEFAULT_RATE_VERSION}"' in rendered


def test_persisted_rows_summarize_into_verification_and_spend_metrics() -> None:
    rows = [
        _extraction_row(),
        _extraction_row(status="CACHED", verification_result="VERIFIED"),
        _extraction_row(
            status="FAILED",
            verification_result="REJECTED",
            verification_reasons={"oe_number": "CITATION_NOT_FOUND"},
        ),
    ]

    summary = summarize_ai_evidence_extractions(rows)

    assert summary["extractions_total"] == 3
    assert summary["shadow_only_total"] == 3
    assert summary["status_counts"] == {"CACHED": 1, "COMPLETED": 1, "FAILED": 1}
    assert summary["verification_counts"]["VERIFIED"] == 2
    assert summary["verification_counts"]["REJECTED"] == 1
    assert summary["verification_reason_counts"]["CITATION_VERIFIED"] == 2
    assert summary["verification_reason_counts"]["CITATION_NOT_FOUND"] == 1
    assert summary["tokens"]["input_tokens"] == 3 * 120_000
    assert summary["spend_estimate"]["available"] is True
    assert summary["estimate_disclaimer"] == "ESTIMATE_NOT_BILLING_TRUTH"
    assert HIDDEN_REASONING not in json.dumps(summary)


def test_module_level_telemetry_records_and_resets() -> None:
    reset_ai_evidence_telemetry()
    try:
        record_ai_evidence_outcome("requested", emit_event=False)
        record_ai_evidence_outcome(
            "completed",
            latency_ms=5.0,
            usage=TokenUsage(10, 0, 10),
            emit_event=False,
        )
        snapshot = ai_evidence_telemetry_snapshot()
        assert snapshot["counters"]["requested"] == 1
        assert snapshot["counters"]["completed"] == 1
    finally:
        reset_ai_evidence_telemetry()
    assert ai_evidence_telemetry_snapshot()["counters"]["requested"] == 0


def test_provider_spend_estimate_is_not_confused_with_supplier_cost() -> None:
    """Yuri's purchase cost is redacted at API boundaries; our spend is not."""

    estimate = estimate_cost(TokenUsage(1_000, 0, 100)).as_dict()
    safe = privacy_safe_mapping({"spend_estimate": estimate, "cost": "1200.00"})

    assert "cost" not in safe
    assert safe["spend_estimate"]["total_usd"] == estimate["total_usd"]
    assert safe["spend_estimate"]["disclaimer"] == "ESTIMATE_NOT_BILLING_TRUTH"


# ---------------------------------------------------------------------------
# 3. API read surface
# ---------------------------------------------------------------------------


def _extraction_row(
    *,
    workspace_id: UUID | None = None,
    observation_id: UUID | None = None,
    status: str = "COMPLETED",
    verification_result: str = "VERIFIED",
    verification_reasons: dict | None = None,
) -> SimpleNamespace:
    """A stored row shaped like the agreed ``ai_evidence_extractions`` contract.

    It deliberately also carries the things that must never be published, so
    every serialization test is a live leak test.
    """

    return SimpleNamespace(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        workspace_id=workspace_id or UUID("22222222-2222-2222-2222-222222222222"),
        market_observation_id=(
            observation_id or UUID("33333333-3333-3333-3333-333333333333")
        ),
        status=status,
        shadow_only=True,
        provider="openai_responses",
        model_id="gpt-5.6-luna",
        # Provider-controlled metadata is retained internally for audit only and
        # must never be copied into the public response.
        provider_model=HIDDEN_REASONING,
        reasoning_effort="medium",
        prompt_version="ai-evidence-v1",
        schema_version="ai-evidence-schema-v1",
        extractor_version="ai-evidence-extractor-v1",
        latency_ms=1_234,
        input_tokens=120_000,
        cached_input_tokens=80_000,
        output_tokens=9_000,
        reasoning_tokens=6_000,
        verification_result=verification_result,
        verification_reasons=(
            verification_reasons
            if verification_reasons is not None
            else {
                "oe_number": "CITATION_VERIFIED",
                "reasoning_text": HIDDEN_REASONING,
            }
        ),
        fields=[
            {
                "field": "oe_number",
                "value": "1K0615301AA",
                "excerpt": "Оригинальный номер 1K0615301AA",
                "source_path": "$.description.paragraphs[3]",
                "confidence": "0.91",
                "verified": True,
                "reasoning": HIDDEN_REASONING,
            }
        ],
        error_code=None,
        created_at=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        # Never publishable:
        raw_response={"output": [{"reasoning": HIDDEN_REASONING}]},
        reasoning_summary=HIDDEN_REASONING,
        api_key=FAKE_API_KEY,
    )


def _auth_override(workspace_id: UUID):
    async def _override() -> AuthContext:
        return AuthContext(
            user=User(id=uuid4(), email="seller@example.com", is_active=True),
            workspace_id=workspace_id,
            workspace_role=WorkspaceRole.member,
        )

    return _override


class _NoopSession:
    async def execute(self, *args, **kwargs):  # pragma: no cover - never reached
        raise AssertionError("the read surface must not query in this test")

    async def scalar(self, *args, **kwargs):  # pragma: no cover - never reached
        raise AssertionError("the read surface must not query in this test")


async def _noop_session():
    yield _NoopSession()


@pytest.mark.asyncio
async def test_ai_evidence_status_reports_configuration_without_the_secret(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        pricing_router,
        "get_settings",
        lambda: SimpleNamespace(
            pricing_ai_evidence_mode="shadow",
            pricing_ai_evidence_provider="openai_responses",
            pricing_ai_evidence_model="gpt-5.6-luna",
            pricing_ai_evidence_reasoning_effort="medium",
            pricing_ai_evidence_api_key=SecretStr(FAKE_API_KEY),
        ),
    )
    app.dependency_overrides[get_current_user] = _auth_override(uuid4())
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/pricing/ai-evidence/status")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "shadow"
    assert body["model"] == "gpt-5.6-luna"
    assert body["reasoning_effort"] == "medium"
    assert body["configured"] is True
    assert body["shadow_only"] is True
    assert body["automatic_price_publication"] is False
    assert body["rate_version"] == DEFAULT_RATE_VERSION
    assert body["rates_effective_date"] == "2026-07-30"
    assert body["rates_per_million"] == {
        "uncached_input": "0.20",
        "cached_input": "0.02",
        "output": "1.20",
    }
    assert body["estimate_disclaimer"] == "ESTIMATE_NOT_BILLING_TRUTH"
    assert FAKE_API_KEY not in response.text
    assert "api_key" not in response.text


def test_extraction_settings_default_to_off_when_the_settings_are_absent() -> None:
    config = pricing_router._ai_evidence_config(SimpleNamespace())

    assert config == {
        "mode": "off",
        "provider": "openai_responses",
        "model": "gpt-5.6-luna",
        "reasoning_effort": "medium",
        "configured": False,
        "shadow_only": True,
    }


def test_extraction_status_uses_the_same_shared_key_fallback_as_runtime() -> None:
    config = pricing_router._ai_evidence_config(
        SimpleNamespace(
            pricing_ai_evidence_mode="shadow",
            pricing_llm_api_key=SecretStr(FAKE_API_KEY),
        )
    )

    assert config["configured"] is True
    assert config["shadow_only"] is True


def test_extraction_status_refuses_an_undocumented_mutable_model_alias() -> None:
    config = pricing_router._ai_evidence_config(
        SimpleNamespace(
            pricing_ai_evidence_mode="shadow",
            pricing_ai_evidence_model="gpt-5.6-luna-latest",
            pricing_llm_api_key=SecretStr(FAKE_API_KEY),
        )
    )

    assert config["mode"] == "off"
    assert config["configured"] is False


def test_unknown_or_required_mode_fails_closed_to_off() -> None:
    for invalid in ("required", "automatic", "garbage"):
        config = pricing_router._ai_evidence_config(
            SimpleNamespace(
                pricing_ai_evidence_mode=invalid,
                pricing_llm_api_key=SecretStr(FAKE_API_KEY),
            )
        )
        assert config["mode"] == "off"
        assert config["configured"] is False
        assert config["shadow_only"] is True


@pytest.mark.asyncio
async def test_observation_evidence_serializes_excerpts_not_hidden_reasoning(
    monkeypatch,
) -> None:
    workspace_id = UUID("22222222-2222-2222-2222-222222222222")
    observation_id = UUID("33333333-3333-3333-3333-333333333333")

    async def _belongs(session, *, workspace_id, observation_id):
        return True

    async def _load(session, *, workspace_id, observation_id):
        return [_extraction_row(workspace_id=workspace_id)]

    monkeypatch.setattr(pricing_router, "_observation_belongs_to_workspace", _belongs)
    monkeypatch.setattr(pricing_router, "_load_observation_ai_evidence", _load)
    app.dependency_overrides[get_current_user] = _auth_override(workspace_id)
    app.dependency_overrides[get_session] = _noop_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/pricing/observations/{observation_id}/ai-evidence"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload) == 1
    row = payload[0]

    assert row["status"] == "COMPLETED"
    assert row["shadow_only"] is True
    assert row["provider"] == "openai_responses"
    assert row["model_id"] == "gpt-5.6-luna"
    assert "provider_model" not in row
    assert row["reasoning_effort"] == "medium"
    assert row["latency_ms"] == 1_234
    assert row["usage"] == {
        "input_tokens": 120_000,
        "cached_input_tokens": 80_000,
        "uncached_input_tokens": 40_000,
        "output_tokens": 9_000,
        "reasoning_tokens": 6_000,
        "total_tokens": 129_000,
    }
    assert row["verification_result"] == "VERIFIED"
    assert row["verification_reasons"] == {"oe_number": "CITATION_VERIFIED"}
    assert row["fields"][0]["excerpt"] == "Оригинальный номер 1K0615301AA"
    assert row["fields"][0]["source_path"] == "$.description.paragraphs[3]"
    assert row["fields"][0]["verification_reason"] == "CITATION_VERIFIED"
    assert Decimal(row["spend_estimate"]["total_usd"]) == Decimal("0.02040")
    assert row["spend_estimate"]["rate_version"] == DEFAULT_RATE_VERSION
    assert row["spend_estimate"]["disclaimer"] == "ESTIMATE_NOT_BILLING_TRUTH"

    # The leak surface: none of this may appear anywhere in the response.
    assert HIDDEN_REASONING not in response.text
    assert FAKE_API_KEY not in response.text
    for forbidden in (
        "reasoning_text",
        "reasoning_summary",
        "chain_of_thought",
        "raw_response",
        "provider_model",
        "api_key",
    ):
        assert forbidden not in response.text


@pytest.mark.asyncio
async def test_observation_evidence_rejects_another_workspaces_row(
    monkeypatch,
) -> None:
    caller_workspace = uuid4()
    observation_id = UUID("33333333-3333-3333-3333-333333333333")
    seen: dict[str, UUID] = {}

    async def _belongs(session, *, workspace_id, observation_id):
        seen["workspace_id"] = workspace_id
        return True

    async def _load(session, *, workspace_id, observation_id):
        # A repository that ignored its scope would look exactly like this.
        return [_extraction_row(workspace_id=uuid4())]

    monkeypatch.setattr(pricing_router, "_observation_belongs_to_workspace", _belongs)
    monkeypatch.setattr(pricing_router, "_load_observation_ai_evidence", _load)
    app.dependency_overrides[get_current_user] = _auth_override(caller_workspace)
    app.dependency_overrides[get_session] = _noop_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/pricing/observations/{observation_id}/ai-evidence"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404, response.text
    assert HIDDEN_REASONING not in response.text
    assert "1K0615301AA" not in response.text
    assert seen["workspace_id"] == caller_workspace


@pytest.mark.asyncio
async def test_observation_outside_the_workspace_is_not_found(monkeypatch) -> None:
    async def _belongs(session, *, workspace_id, observation_id):
        return False

    async def _load(session, *, workspace_id, observation_id):
        raise AssertionError("evidence must not be loaded for a foreign observation")

    monkeypatch.setattr(pricing_router, "_observation_belongs_to_workspace", _belongs)
    monkeypatch.setattr(pricing_router, "_load_observation_ai_evidence", _load)
    app.dependency_overrides[get_current_user] = _auth_override(uuid4())
    app.dependency_overrides[get_session] = _noop_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/pricing/observations/{uuid4()}/ai-evidence"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_evidence_endpoint_is_unavailable_until_storage_exists(
    monkeypatch,
) -> None:
    async def _belongs(session, *, workspace_id, observation_id):
        return True

    monkeypatch.setattr(pricing_router, "_observation_belongs_to_workspace", _belongs)
    monkeypatch.delattr(
        "marko.infrastructure.db.models.AiEvidenceExtraction", raising=False
    )
    app.dependency_overrides[get_current_user] = _auth_override(uuid4())
    app.dependency_overrides[get_session] = _noop_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/pricing/observations/{uuid4()}/ai-evidence"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "AI evidence storage is not available"


class _IsolationBase(DeclarativeBase):
    """A private registry, so this stand-in never joins the real metadata."""


class _StandInExtraction(_IsolationBase):
    __tablename__ = "ai_evidence_extractions_stand_in"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid)
    market_observation_id: Mapped[UUID] = mapped_column(Uuid)


class _CapturingSession:
    def __init__(self) -> None:
        self.statement = None

    async def scalars(self, statement):
        self.statement = statement

        class _Result:
            @staticmethod
            def all() -> list:
                return []

        return _Result()


@pytest.mark.asyncio
async def test_evidence_query_is_scoped_to_the_caller_workspace(monkeypatch) -> None:
    """The isolation predicate lives in the query, not only in the response."""

    monkeypatch.setattr(
        "marko.infrastructure.db.models.AiEvidenceExtraction",
        _StandInExtraction,
        raising=False,
    )
    workspace_id = uuid4()
    observation_id = uuid4()
    session = _CapturingSession()

    rows = await pricing_router._load_observation_ai_evidence(
        session,
        workspace_id=workspace_id,
        observation_id=observation_id,
    )

    assert rows == []
    compiled = session.statement.compile()
    assert "workspace_id" in str(compiled)
    assert "market_observation_id" in str(compiled)
    assert workspace_id in compiled.params.values()
    assert observation_id in compiled.params.values()


@pytest.mark.asyncio
async def test_evidence_loader_fails_closed_without_a_workspace_column(
    monkeypatch,
) -> None:
    class _UnscopedBase(DeclarativeBase):
        pass

    class _Unscoped(_UnscopedBase):
        __tablename__ = "ai_evidence_extractions_unscoped"

        id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
        market_observation_id: Mapped[UUID] = mapped_column(Uuid)

    monkeypatch.setattr(
        "marko.infrastructure.db.models.AiEvidenceExtraction",
        _Unscoped,
        raising=False,
    )

    with pytest.raises(
        pricing_router._AiEvidenceStorageUnavailable, match="workspace column"
    ):
        await pricing_router._load_observation_ai_evidence(
            _CapturingSession(),
            workspace_id=uuid4(),
            observation_id=uuid4(),
        )


def test_openapi_publishes_evidence_fields_and_no_reasoning_content() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    extraction = schema["components"]["schemas"]["AiEvidenceExtractionResponse"]
    status_schema = schema["components"]["schemas"]["AiEvidenceStatusResponse"]
    field_schema = schema["components"]["schemas"]["AiEvidenceFieldResponse"]

    assert "/api/v1/pricing/ai-evidence/status" in paths
    assert "/api/v1/pricing/observations/{observation_id}/ai-evidence" in paths
    assert {
        "status",
        "shadow_only",
        "provider",
        "model_id",
        "reasoning_effort",
        "usage",
        "verification_result",
        "verification_reasons",
        "fields",
        "spend_estimate",
    } <= set(extraction["properties"])
    assert {"excerpt", "source_path", "verification_reason"} <= set(
        field_schema["properties"]
    )
    published = json.dumps(schema["components"]["schemas"])
    for forbidden in (
        "reasoning_text",
        "reasoning_summary",
        "chain_of_thought",
        "raw_response",
        "provider_model",
        "api_key",
    ):
        assert forbidden not in published
    assert "estimate_disclaimer" in status_schema["properties"]


def test_the_ai_evidence_surface_is_read_only_this_round() -> None:
    """No trigger endpoint exists, so no test here can reach a provider."""

    operations = {
        path: sorted(methods)
        for path, methods in app.openapi()["paths"].items()
        if "ai-evidence" in path
    }

    assert len(operations) == 2
    assert all(methods == ["get"] for methods in operations.values()), operations
