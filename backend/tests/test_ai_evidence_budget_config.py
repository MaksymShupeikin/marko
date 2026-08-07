"""Configuration contract and the bounded physical-attempt driver.

No database and no network: every provider call here is an ``httpx.MockTransport``
handler, and the ledger is the in-memory one.  The durable half of the same
claims is proved against real PostgreSQL in
``test_ai_evidence_extraction_postgres.py``; this file exists so the arithmetic
of "one reservation per POST" is readable without a container.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
import yaml

from marko.core.config import Settings
from marko.infrastructure.db.models import AiEvidenceExtraction
from marko.services.llm_call_budget import (
    AI_EVIDENCE_EXTRACTION_PURPOSE,
    COMPARABILITY_PURPOSE,
    MAX_PHYSICAL_ATTEMPTS,
    AttemptBudgetExhausted,
    BudgetedAttempts,
    InMemoryProviderCallLedger,
    PositionCallBudget,
    evidence_extraction_budget,
)


ROOT = Path(__file__).resolve().parents[2]


def _settings(**overrides: object) -> Settings:
    return Settings(**{"environment": "test", **overrides})  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


def test_ai_evidence_extraction_is_off_by_default_with_the_stated_defaults() -> None:
    settings = _settings()

    assert settings.pricing_ai_evidence_mode == "off"
    assert settings.ai_evidence_extraction_enabled is False
    assert settings.pricing_ai_evidence_model == "gpt-5.6-luna"
    assert settings.pricing_ai_evidence_reasoning_effort == "medium"
    assert settings.pricing_ai_evidence_max_output_tokens == 1200
    assert settings.pricing_ai_evidence_max_input_chars == 20_000
    assert settings.pricing_ai_evidence_max_calls_per_position == 4
    assert settings.pricing_ai_evidence_max_candidates_per_position == 4
    assert settings.pricing_ai_evidence_max_concurrency == 2


def test_production_compose_forwards_every_documented_ai_evidence_setting() -> None:
    example_keys = {
        line.partition("=")[0]
        for line in (ROOT / "deploy/.env.production.example")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.startswith("PRICING_AI_EVIDENCE_")
    }
    production = yaml.safe_load(
        (ROOT / "deploy/compose.production.yaml").read_text(encoding="utf-8")
    )
    environment = production["x-backend-environment"]

    assert example_keys
    assert example_keys <= set(environment)
    assert environment["PRICING_AI_EVIDENCE_MODE"] == (
        "${PRICING_AI_EVIDENCE_MODE:-off}"
    )
    assert environment["PRICING_AI_EVIDENCE_MODEL"] == (
        "${PRICING_AI_EVIDENCE_MODEL:-gpt-5.6-luna}"
    )


def test_default_reasoning_effort_is_not_above_medium() -> None:
    """The default is a spend decision, so it is asserted as an ordering.

    Equality alone would let a later edit move it to ``high`` and "fix" the test
    by editing the literal.  Naming the ladder makes the raise the thing that
    fails.
    """

    ladder = ["none", "low", "medium", "high", "xhigh", "max"]
    default = Settings.model_fields["pricing_ai_evidence_reasoning_effort"].default

    assert ladder.index(default) <= ladder.index("medium")


def test_escalation_is_disabled_and_unconfigured_by_default() -> None:
    settings = _settings()

    assert settings.pricing_ai_evidence_escalation_enabled is False
    assert settings.pricing_ai_evidence_escalation_model == ""
    assert settings.pricing_ai_evidence_escalation_reasoning_effort is None
    assert settings.ai_evidence_escalation_configured is False


def test_empty_environment_escalation_effort_is_unconfigured_not_invalid() -> None:
    settings = _settings(pricing_ai_evidence_escalation_reasoning_effort="")

    assert settings.pricing_ai_evidence_escalation_reasoning_effort is None
    assert settings.ai_evidence_escalation_configured is False


def test_shadow_mode_without_an_api_key_is_accepted_and_reports_unconfigured() -> None:
    """A missing credential must be a typed result, never a boot failure.

    If this raised, flipping an off-by-default shadow feature would take the API
    down, and the operator would read a crash loop instead of a row saying
    exactly which position was not extracted and why.
    """

    settings = _settings(
        pricing_ai_evidence_mode="shadow",
        pricing_llm_api_key=SecretStr("   "),
    )

    assert settings.ai_evidence_extraction_enabled is True
    assert settings.ai_evidence_api_key_configured is False


def test_shadow_mode_with_an_api_key_reports_configured() -> None:
    settings = _settings(
        pricing_ai_evidence_mode="shadow",
        pricing_llm_api_key=SecretStr("sk-test-not-a-real-key"),
    )

    assert settings.ai_evidence_api_key_configured is True


def test_the_api_key_is_never_rendered_by_repr_or_dump() -> None:
    secret = "sk-live-must-never-appear-anywhere"
    settings = _settings(
        pricing_ai_evidence_mode="shadow",
        pricing_llm_api_key=SecretStr(secret),
    )

    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert secret not in str(settings.model_dump())
    assert secret not in str(settings.model_dump_json())
    assert secret not in str(settings.pricing_llm_api_key)


async def test_a_missing_api_key_yields_unconfigured_without_any_request() -> None:
    """The contract stated as behaviour, not as a boolean.

    ``ai_evidence_api_key_configured`` is the only gate between an enabled
    shadow mode and a POST, so asserting the flag alone would still pass if the
    flag stopped meaning anything.  ``_gated_extraction`` is the exact shape the
    extraction service is expected to use, and the transport counts requests, so
    a gate that starts letting an unauthenticated call through fails here with
    ``requests == 1`` rather than with a subtly wrong string.
    """

    settings = _settings(
        pricing_ai_evidence_mode="shadow",
        pricing_llm_api_key=SecretStr(""),
    )
    poster = _Poster([200])

    status = await _gated_extraction(settings, poster)

    assert status == "UNCONFIGURED"
    assert poster.requests == 0


async def test_a_present_api_key_lets_the_same_gate_through() -> None:
    """The negative test above is only meaningful if the gate can open."""

    settings = _settings(
        pricing_ai_evidence_mode="shadow",
        pricing_llm_api_key=SecretStr("sk-test-not-a-real-key"),
    )
    poster = _Poster([200])

    status = await _gated_extraction(settings, poster)

    assert status == "COMPLETED"
    assert poster.requests == 1


async def _gated_extraction(settings: Settings, poster: "_Poster") -> str:
    if not settings.ai_evidence_api_key_configured:
        return "UNCONFIGURED"
    async with httpx.AsyncClient(transport=poster.transport()) as client:
        await client.post("https://provider.invalid/v1/responses")
    return "COMPLETED"


def test_shadow_mode_requires_a_model_name() -> None:
    with pytest.raises(ValueError, match="PRICING_AI_EVIDENCE_MODEL"):
        _settings(pricing_ai_evidence_mode="shadow", pricing_ai_evidence_model="  ")


@pytest.mark.parametrize(
    "model",
    (
        "gpt-5.6-luna-latest",
        "gpt-5.6-luna-2026-02-30",
        "gpt-5.6-luna\nunsafe",
        "x" * 161 + "-2026-07-30",
    ),
)
def test_shadow_mode_requires_a_bounded_immutable_model_snapshot(model: str) -> None:
    with pytest.raises(ValueError, match="immutable, bounded ASCII snapshot"):
        _settings(pricing_ai_evidence_mode="shadow", pricing_ai_evidence_model=model)


def test_enabled_escalation_must_name_a_model_and_an_effort() -> None:
    with pytest.raises(ValueError, match="PRICING_AI_EVIDENCE_ESCALATION_MODEL"):
        _settings(
            pricing_ai_evidence_mode="shadow",
            pricing_ai_evidence_escalation_enabled=True,
            pricing_ai_evidence_escalation_reasoning_effort="high",
        )
    with pytest.raises(
        ValueError, match="PRICING_AI_EVIDENCE_ESCALATION_REASONING_EFFORT"
    ):
        _settings(
            pricing_ai_evidence_mode="shadow",
            pricing_ai_evidence_escalation_enabled=True,
            pricing_ai_evidence_escalation_model="gpt-5.6-luna-pro-2026-07-30",
        )


def test_enabled_extraction_still_requires_https_outside_local_environments() -> None:
    with pytest.raises(ValueError, match="PRICING_LLM_BASE_URL"):
        _settings(
            environment="staging",
            pricing_ai_evidence_mode="shadow",
            pricing_llm_base_url="http://api.openai.com/v1",
        )


# --------------------------------------------------------------------------
# request identity
# --------------------------------------------------------------------------


_IDENTITY = {
    "capture_sha256": "a" * 64,
    "candidate_snapshot_hash": "b" * 64,
    "prompt_version": "ai-evidence-v1",
    "schema_version": "ai-evidence-schema-v1",
    "extractor_version": "extractor-v1",
    "provider": "openai_responses",
    "model_id": "gpt-5.6-luna",
    "reasoning_effort": "medium",
    "verifier_version": "marko-ai-evidence-verifier-v1",
    "oe_normalization_version": "oe-extractor-v2",
}


def test_identical_immutable_input_yields_one_identity() -> None:
    first = AiEvidenceExtraction.build_input_hash(**_IDENTITY)
    second = AiEvidenceExtraction.build_input_hash(**_IDENTITY)

    assert first == second
    assert len(first) == 64


@pytest.mark.parametrize("changed", sorted(_IDENTITY))
def test_changing_any_identity_fact_changes_the_input_hash(changed: str) -> None:
    """Every field, not a sample of them.

    A sampled version of this test is how ``capture_sha256`` gets dropped from
    the digest and nobody notices: the remaining assertions still pass, and the
    only symptom is a stale extraction that presents as a cache hit.
    """

    baseline = AiEvidenceExtraction.build_input_hash(**_IDENTITY)
    mutated = dict(_IDENTITY)
    mutated[changed] = ("c" * 64) if changed.endswith(("sha256", "hash")) else "changed"

    assert AiEvidenceExtraction.build_input_hash(**mutated) != baseline


def test_request_key_separates_observations_and_attempts() -> None:
    observation = uuid4()
    other_observation = uuid4()
    input_hash = AiEvidenceExtraction.build_input_hash(**_IDENTITY)

    first = AiEvidenceExtraction.build_request_key(
        market_observation_id=observation, input_hash=input_hash, attempt_no=1
    )

    assert first == AiEvidenceExtraction.build_request_key(
        market_observation_id=str(observation), input_hash=input_hash, attempt_no=1
    )
    assert first != AiEvidenceExtraction.build_request_key(
        market_observation_id=observation, input_hash=input_hash, attempt_no=2
    )
    assert first != AiEvidenceExtraction.build_request_key(
        market_observation_id=other_observation,
        input_hash=input_hash,
        attempt_no=1,
    )


# --------------------------------------------------------------------------
# bounded physical attempts
# --------------------------------------------------------------------------


class _Poster:
    """A provider endpoint that never leaves the process."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.requests = 0

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests += 1
            status = self._statuses.pop(0) if self._statuses else 200
            return httpx.Response(status, json={"id": f"resp-{self.requests}"})

        return httpx.MockTransport(handle)


async def _drive(
    budget: PositionCallBudget,
    poster: _Poster,
    *,
    max_attempts: int = MAX_PHYSICAL_ATTEMPTS,
) -> BudgetedAttempts:
    """The shape every paid adapter is expected to use, verbatim."""

    attempts = BudgetedAttempts(budget, max_attempts=max_attempts)
    async with httpx.AsyncClient(transport=poster.transport()) as client:
        async for _ in attempts:
            response = await client.post("https://provider.invalid/v1/responses")
            if response.status_code == 429 or response.status_code >= 500:
                attempts.last_failure = f"HTTP {response.status_code}"
                continue
            break
    return attempts


async def test_each_physical_attempt_including_the_retry_reserves_one_slot() -> None:
    ledger = InMemoryProviderCallLedger()
    position, workspace = uuid4(), uuid4()
    budget = evidence_extraction_budget(
        position_id=position, workspace_id=workspace, limit=5, ledger=ledger
    )
    poster = _Poster([429, 200])

    attempts = await _drive(budget, poster)

    assert poster.requests == 2
    assert attempts.made == 2
    assert attempts.refused is False
    assert (
        await ledger.spent(position_id=position, purpose=AI_EVIDENCE_EXTRACTION_PURPOSE)
        == 2
    )


async def test_the_retry_is_abandoned_when_the_budget_only_covers_one_post() -> None:
    ledger = InMemoryProviderCallLedger()
    position, workspace = uuid4(), uuid4()
    budget = evidence_extraction_budget(
        position_id=position, workspace_id=workspace, limit=1, ledger=ledger
    )
    poster = _Poster([500, 200])

    attempts = await _drive(budget, poster)

    assert poster.requests == 1
    assert attempts.refused_at_start is False
    assert attempts.refused_retry_after == "HTTP 500"
    with pytest.raises(AttemptBudgetExhausted, match="retry after HTTP 500"):
        attempts.raise_if_refused()
    assert (
        await ledger.spent(position_id=position, purpose=AI_EVIDENCE_EXTRACTION_PURPOSE)
        == 1
    )


async def test_a_spent_budget_makes_no_request_at_all() -> None:
    ledger = InMemoryProviderCallLedger()
    position, workspace = uuid4(), uuid4()
    budget = evidence_extraction_budget(
        position_id=position, workspace_id=workspace, limit=1, ledger=ledger
    )
    assert await budget.reserve() is True
    poster = _Poster([200])

    attempts = await _drive(budget, poster)

    assert poster.requests == 0
    assert attempts.made == 0
    assert attempts.refused_at_start is True
    with pytest.raises(AttemptBudgetExhausted, match="no request was made"):
        attempts.raise_if_refused()


async def test_the_attempt_loop_is_bounded_even_when_the_budget_is_generous() -> None:
    """The ledger caps a position; this caps one candidate within it.

    Without the second bound a single unparseable candidate can retry until the
    whole position's allowance is gone, and every one of those POSTs is billed.
    """

    ledger = InMemoryProviderCallLedger()
    budget = evidence_extraction_budget(
        position_id=uuid4(), workspace_id=uuid4(), limit=1000, ledger=ledger
    )
    poster = _Poster([500] * 50)

    attempts = await _drive(budget, poster)

    assert poster.requests == MAX_PHYSICAL_ATTEMPTS == 2
    assert attempts.made == MAX_PHYSICAL_ATTEMPTS
    assert attempts.refused is False


async def test_an_unattributed_call_is_refused_rather_than_unbounded() -> None:
    budget = evidence_extraction_budget(
        position_id=None,
        workspace_id=None,
        limit=10,
        ledger=InMemoryProviderCallLedger(),
    )
    poster = _Poster([200])

    attempts = await _drive(budget, poster)

    assert poster.requests == 0
    assert attempts.refused_at_start is True


async def test_extraction_and_comparability_spend_separate_counters() -> None:
    """One row per position would make the two paths narrow each other.

    ``least(call_limit, limit)`` is deliberately one-way, so an extraction
    reserving with its ceiling of 2 against a shared row would permanently drop
    a comparability allowance of 10 to 2 -- and the narrowing would be
    indistinguishable from the bound working.
    """

    ledger = InMemoryProviderCallLedger()
    position, workspace = uuid4(), uuid4()
    extraction = evidence_extraction_budget(
        position_id=position, workspace_id=workspace, limit=2, ledger=ledger
    )
    comparability = PositionCallBudget(
        ledger=ledger, position_id=position, workspace_id=workspace, limit=10
    )

    assert await extraction.reserve() is True
    assert await extraction.reserve() is True
    assert await extraction.reserve() is False

    assert await comparability.effective_limit() == 10
    for _ in range(10):
        assert await comparability.reserve() is True
    assert await comparability.reserve() is False

    assert (
        await ledger.spent(position_id=position, purpose=AI_EVIDENCE_EXTRACTION_PURPOSE)
        == 2
    )
    assert await ledger.spent(position_id=position, purpose=COMPARABILITY_PURPOSE) == 10


async def test_an_unknown_purpose_is_refused_instead_of_opening_a_new_counter() -> None:
    ledger = InMemoryProviderCallLedger()

    with pytest.raises(ValueError, match="unknown provider-call budget purpose"):
        await ledger.reserve(
            position_id=uuid4(),
            workspace_id=uuid4(),
            limit=1,
            purpose="typo_purpose",
        )
