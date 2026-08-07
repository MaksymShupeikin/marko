"""Opt-in PostgreSQL proof for AI-evidence persistence, identity and budget.

Every claim here is one the in-memory versions cannot make: append-only is a
trigger, idempotency is a unique index, and the call budget is a row that
survives the process that wrote it.  No provider is contacted -- the only HTTP
in this file goes through ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from marko.infrastructure.db.models import (
    AiEvidenceExtraction,
    AiEvidenceRequestClaim,
    AiEvidenceRequestEvent,
    CatalogImportBatch,
    CatalogItem,
    MarketObservation,
    ObservationTierClassification,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    User,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.ai_evidence_extraction import (
    AiEvidenceCandidateValue,
    AiEvidenceExtractionOutput,
    AiEvidenceFinding,
    AiEvidenceProviderError,
    AiEvidenceProviderResult,
    EvidenceFieldName,
    EvidenceSourceKind,
    FindingState,
    build_extraction_input,
    resolve_ai_evidence_config,
)
from marko.services.ai_evidence_runtime import (
    AiEvidenceRuntimeError,
    _load_bound_evidence,
    _request_event,
    ai_evidence_runtime_input_hash,
    request_or_reuse_ai_evidence,
)
from marko.services.ai_evidence_shadow import process_ai_evidence_position
from marko.services.llm_call_budget import (
    AI_EVIDENCE_EXTRACTION_PURPOSE,
    COMPARABILITY_PURPOSE,
    MAX_PHYSICAL_ATTEMPTS,
    BudgetedAttempts,
    DurableProviderCallLedger,
    PositionCallBudget,
    evidence_extraction_budget,
    provider_call_budget_table,
)
from marko.services.scraper_metrics import (
    ai_evidence_telemetry_snapshot,
    reset_ai_evidence_telemetry,
)
from metis.pricing import comparison_evidence_to_dict, verified_comparison_evidence


pytestmark = pytest.mark.postgres

BACKEND_ROOT = Path(__file__).resolve().parents[1]

_ENABLED = os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") == "1"
_SKIP = pytest.mark.skipif(
    not _ENABLED, reason="Set MARKO_RUN_POSTGRES_INTEGRATION=1 to run"
)

_PROMPT_VERSION = "ai-evidence-prompt-v1"
_SCHEMA_VERSION = "ai-evidence-schema-v1"
_EXTRACTOR_VERSION = "ai-evidence-extractor-v1"
_PROVIDER = "openai_responses"
_MODEL = "gpt-5.6-luna"
_EFFORT = "medium"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


class _Seeded:
    __slots__ = (
        "workspace_id",
        "user_id",
        "run_item_id",
        "capture_id",
        "capture_sha256",
        "observation_ids",
    )

    def __init__(self, **values: object) -> None:
        for key, value in values.items():
            setattr(self, key, value)


async def _seed(
    *,
    observations: int = 2,
    shadow_scenarios: tuple[str, ...] | None = None,
) -> _Seeded:
    workspace_id = uuid4()
    user_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    run_id = uuid4()
    run_item_id = uuid4()
    capture_id = uuid4()
    capture_sha256 = uuid4().hex + uuid4().hex
    observation_ids = [uuid4() for _ in range(observations)]
    raw_offers = [
        {
            "raw_offer_index": index,
            "retrieval_kind": "search_query",
            "product": {
                "id": f"listing-ai-evidence-{index}",
                "name": "Front brake disc 1K0615301",
                "description": "New front brake disc for VW Golf",
                "characteristics": {"part_type": "brake disc"},
                "price": "1100",
                "url": f"https://prom.ua/ua/p{index}-front-brake-disc.html",
            },
        }
        for index in range(observations)
    ]
    offer_hashes = [
        hashlib.sha256(
            json.dumps(
                offer,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        for offer in raw_offers
    ]
    now = datetime.now(UTC)
    evidence = comparison_evidence_to_dict(
        verified_comparison_evidence(
            stable_seller_id="seller-ai-evidence",
            source_record_id="listing-ai-evidence",
        )
    )

    async with async_session_factory() as session:
        session.add_all(
            [
                Workspace(
                    id=workspace_id,
                    name="AI evidence integration",
                    slug=f"ai-evidence-{workspace_id.hex}",
                ),
                User(
                    id=user_id,
                    email=f"ai-evidence-{user_id.hex}@example.test",
                    is_active=True,
                ),
            ]
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename="ai-evidence.xlsx",
                content_sha256=uuid4().hex + uuid4().hex,
                request_fingerprint=uuid4().hex * 2,
                content_size=1,
                status="completed",
                column_mapping={"sku": "SKU"},
                total_rows=1,
                imported_rows=1,
                rejected_rows=0,
                error_log=[],
            )
        )
        await session.flush()
        session.add(
            CatalogItem(
                id=item_id,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                source_row=2,
                sku="SKU-AI-EVIDENCE",
                oe_raw="1K0 615 301",
                oe_norm="1K0615301",
                name="Front brake disc",
                category="brake_pad",
                brand="KEMP",
                description="New front brake disc",
                product_url=None,
                current_price=Decimal("1000"),
                currency="UAH",
                is_available=True,
                raw_row={},
                part_numbers_norm=["1K0615301"],
                applicability_brands=["VW"],
                applicability_models=["Golf"],
                characteristics_raw={"part_type": "brake disc"},
                identity_status="OE_CONFIRMED",
            )
        )
        await session.flush()
        session.add(
            PricingRun(
                id=run_id,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                status="collecting",
                policy_version="integration-v1",
                policy_config={},
                parser_version="integration-v1",
                total_items=1,
            )
        )
        await session.flush()
        session.add(
            PricingRunItem(
                id=run_item_id,
                pricing_run_id=run_id,
                catalog_item_id=item_id,
                status="classified",
                idempotency_key=f"ai-evidence:{run_item_id}",
            )
        )
        await session.flush()
        session.add(
            RawMarketCapture(
                id=capture_id,
                pricing_run_item_id=run_item_id,
                source="prom_public",
                payload={"candidate_records": raw_offers},
                content_sha256=capture_sha256,
                parser_version="integration-v1",
            )
        )
        await session.flush()
        for index, observation_id in enumerate(observation_ids):
            scenario = (
                shadow_scenarios[index]
                if shadow_scenarios is not None and index < len(shadow_scenarios)
                else "known"
            )
            observation_evidence = deepcopy(evidence)
            hard_gate_result = "PASS"
            if scenario == "unknown":
                observation_evidence["dimensions"]["condition"] = {
                    "state": "UNKNOWN",
                    "raw_value": None,
                    "normalized_value": None,
                    "evidence_refs": [],
                    "reason_code": "DETERMINISTIC_FIELD_MISSING",
                }
                observation_evidence["hard_gate_result"] = "MANUAL_REVIEW"
                hard_gate_result = "MANUAL_REVIEW"
            elif scenario == "reject":
                observation_evidence["hard_gate_result"] = "REJECT"
                hard_gate_result = "REJECT"
            session.add(
                MarketObservation(
                    id=observation_id,
                    pricing_run_item_id=run_item_id,
                    catalog_item_id=item_id,
                    raw_capture_id=capture_id,
                    source="prom_public",
                    source_listing_id=f"listing-ai-evidence-{index}",
                    seller_id="seller-ai-evidence",
                    seller_name="Competitor",
                    url=f"https://prom.ua/ua/p{index}-front-brake-disc.html",
                    title="Front brake disc 1K0615301",
                    description="New front brake disc for VW Golf",
                    description_available=True,
                    condition_raw="new",
                    condition_state="NEW",
                    candidate_snapshot={
                        "schema_version": "marko-candidate-review-snapshot-v1",
                        "source_locator": {
                            "locator_version": "marko-ai-evidence-source-locator-v1",
                            "raw_capture_id": str(capture_id),
                            "capture_content_sha256": capture_sha256,
                            "raw_offer_index": index,
                            "raw_offer_sha256": offer_hashes[index],
                            "source_listing_id": f"listing-ai-evidence-{index}",
                            "source_pointer": f"/candidate_records/{index}",
                        },
                        "product": {
                            "name": "Front brake disc 1K0615301",
                            "description": "New front brake disc for VW Golf",
                            "characteristics": {"part_type": "brake disc"},
                        },
                    },
                    brand_raw="Budget analogue",
                    matched_oe_norm="1K0615301",
                    search_oe_norm="1K0615301",
                    extracted_oe_norms=["1K0615301"],
                    verified_matched_oe_norm="1K0615301",
                    comparison_identity_key="oe:1K0615301",
                    oe_verification_status="VERIFIED_EXACT",
                    oe_evidence=[],
                    oe_extractor_version="integration-v1",
                    price=Decimal("1100"),
                    sale_price=Decimal("1100"),
                    currency="UAH",
                    currency_raw="UAH",
                    currency_inferred=False,
                    is_available=True,
                    match_confidence=Decimal("1"),
                    source_confidence=Decimal("1"),
                    parser_version="integration-v1",
                    evidence_contract_version="comparison-evidence-v3",
                    comparability_policy_id="integration-v1",
                    comparability_policy_hash="b" * 64,
                    comparison_evidence=observation_evidence,
                    comparability_hard_gate_result=hard_gate_result,
                    seller_identity_verified=True,
                    source_provenance_verified=True,
                    automatic_eligible=False,
                    observed_at=now,
                )
            )
            if scenario == "owned":
                session.add(
                    ObservationTierClassification(
                        market_observation_id=observation_id,
                        tier="kemp",
                        tier_confidence=Decimal("1"),
                        is_used=False,
                        is_kemp=True,
                        is_owned=True,
                        cohort_role="OWNED_STORE",
                        reason_codes=["OWNED_SELLER"],
                        method_version="integration-v1",
                    )
                )
        await session.commit()

    return _Seeded(
        workspace_id=workspace_id,
        user_id=user_id,
        run_item_id=run_item_id,
        capture_id=capture_id,
        capture_sha256=capture_sha256,
        observation_ids=observation_ids,
    )


_APPEND_ONLY_TABLES = (
    "ai_evidence_request_claims",
    "ai_evidence_request_events",
    "ai_evidence_extractions",
    "observation_tier_classifications",
    "market_observations",
    "raw_market_captures",
)


async def _cleanup(seeded: _Seeded) -> None:
    async with async_session_factory() as session:
        try:
            for table_name in _APPEND_ONLY_TABLES:
                await session.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"DISABLE TRIGGER trg_{table_name}_append_only"
                    )
                )
            # Self-referencing RESTRICT: a cache-hit row cites the row it
            # reused, so the citing rows have to go first.
            await session.execute(
                delete(AiEvidenceExtraction).where(
                    AiEvidenceExtraction.workspace_id == seeded.workspace_id,
                    AiEvidenceExtraction.cache_hit_extraction_id.is_not(None),
                )
            )
            await session.execute(
                delete(AiEvidenceExtraction).where(
                    AiEvidenceExtraction.workspace_id == seeded.workspace_id
                )
            )
            await session.execute(
                delete(AiEvidenceRequestClaim).where(
                    AiEvidenceRequestClaim.request_event_id.in_(
                        select(AiEvidenceRequestEvent.id).where(
                            AiEvidenceRequestEvent.workspace_id == seeded.workspace_id
                        )
                    )
                )
            )
            await session.execute(
                delete(AiEvidenceRequestEvent).where(
                    AiEvidenceRequestEvent.workspace_id == seeded.workspace_id
                )
            )
            await session.execute(
                provider_call_budget_table.delete().where(
                    provider_call_budget_table.c.workspace_id == seeded.workspace_id
                )
            )
            await session.execute(
                text(
                    "DELETE FROM market_observations WHERE catalog_item_id IN "
                    "(SELECT id FROM catalog_items WHERE workspace_id=:workspace_id)"
                ),
                {"workspace_id": seeded.workspace_id},
            )
            await session.execute(
                text(
                    "DELETE FROM raw_market_captures WHERE pricing_run_item_id IN "
                    "(SELECT item.id FROM pricing_run_items AS item "
                    "JOIN pricing_runs AS run ON run.id=item.pricing_run_id "
                    "WHERE run.workspace_id=:workspace_id)"
                ),
                {"workspace_id": seeded.workspace_id},
            )
            await session.execute(
                text(
                    "DELETE FROM pricing_run_items WHERE pricing_run_id IN "
                    "(SELECT id FROM pricing_runs WHERE workspace_id=:workspace_id)"
                ),
                {"workspace_id": seeded.workspace_id},
            )
            await session.execute(
                delete(Workspace).where(Workspace.id == seeded.workspace_id)
            )
            await session.execute(delete(User).where(User.id == seeded.user_id))
            for table_name in reversed(_APPEND_ONLY_TABLES):
                await session.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"ENABLE TRIGGER trg_{table_name}_append_only"
                    )
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _input_hash(**overrides: str) -> str:
    identity = {
        "capture_sha256": "a" * 64,
        "candidate_snapshot_hash": "b" * 64,
        "prompt_version": _PROMPT_VERSION,
        "schema_version": _SCHEMA_VERSION,
        "extractor_version": _EXTRACTOR_VERSION,
        "provider": _PROVIDER,
        "model_id": _MODEL,
        "reasoning_effort": _EFFORT,
        "verifier_version": "marko-ai-evidence-verifier-v1",
        "oe_normalization_version": "oe-extractor-v2",
    }
    identity.update(overrides)
    return AiEvidenceExtraction.build_input_hash(**identity)  # type: ignore[arg-type]


def _row(
    seeded: _Seeded,
    *,
    observation_index: int = 0,
    input_hash: str | None = None,
    capture_sha256: str | None = None,
    candidate_snapshot_hash: str = "b" * 64,
    attempt_no: int = 1,
    status: str = "COMPLETED",
    workspace_id: UUID | None = None,
    **overrides: object,
) -> AiEvidenceExtraction:
    observation_id = seeded.observation_ids[observation_index]
    resolved_capture = capture_sha256 or seeded.capture_sha256
    resolved_hash = input_hash or _input_hash(
        capture_sha256=resolved_capture,
        candidate_snapshot_hash=candidate_snapshot_hash,
    )
    values: dict[str, object] = {
        "workspace_id": workspace_id or seeded.workspace_id,
        "pricing_run_item_id": seeded.run_item_id,
        "market_observation_id": observation_id,
        "raw_capture_id": seeded.capture_id,
        "request_key": AiEvidenceExtraction.build_request_key(
            market_observation_id=observation_id,
            input_hash=resolved_hash,
            attempt_no=attempt_no,
        ),
        "input_hash": resolved_hash,
        "candidate_snapshot_hash": candidate_snapshot_hash,
        "capture_sha256": resolved_capture,
        "source_listing_id": f"listing-ai-evidence-{observation_index}",
        "source_offer_locator_sha256": "c" * 64,
        "document_sha256": "d" * 64,
        "prepared_input_sha256": "e" * 64,
        "model_settings_sha256": "f" * 64,
        "attempt_no": attempt_no,
        "prompt_version": _PROMPT_VERSION,
        "schema_version": _SCHEMA_VERSION,
        "extractor_version": _EXTRACTOR_VERSION,
        "provider": _PROVIDER,
        "model_id": _MODEL,
        "reasoning_effort": _EFFORT,
        "max_output_tokens": 1200,
        "max_input_chars": 20_000,
        "target_fields": ["OE_NUMBERS"],
        "verifier_version": "marko-ai-evidence-verifier-v1",
        "oe_normalization_version": "oe-extractor-v2",
        "mode": "shadow",
        "outcome": "EXTRACTED",
        "status": status,
        "raw_output": {"fields": [{"name": "oe", "value": "1K0615301"}]},
        "findings": [{"field": "oe", "value": "1K0615301"}],
        "verification_status": "VERIFIED",
        "verification_reasons": {
            "OE_NUMBERS": {
                "status": "VERIFIED",
                "reason_codes": ["LITERAL_SUBSTRING_MATCH"],
            }
        },
        "verification_report": {"status": "VERIFIED"},
        "verified_field_count": 1,
        "rejected_field_count": 0,
        "input_snapshot": {"title": "Front brake disc 1K0615301"},
        "provider_response_id": "resp_ai_evidence_1",
        "provider_model": _MODEL,
        "usage": {"input_tokens": 120, "output_tokens": 40},
        "latency_ms": 350,
    }
    values.update(overrides)
    return AiEvidenceExtraction(**values)  # type: ignore[arg-type]


class _FakeRuntimeProvider:
    def __init__(
        self,
        *,
        delay_seconds: float = 0.0,
        budget: PositionCallBudget | None = None,
        returned_model: str = _MODEL,
    ) -> None:
        self.calls = 0
        self.delay_seconds = delay_seconds
        self.budget = budget
        self.returned_model = returned_model

    async def extract(self, *, request: object) -> AiEvidenceProviderResult:
        if self.budget is not None and not await self.budget.reserve():
            raise AiEvidenceProviderError(
                "LLM_PROVIDER_CALL_BUDGET_EXHAUSTED",
                "provider-call budget is spent; no request was made",
            )
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        requested = {
            EvidenceFieldName(value)
            for value in request.input_snapshot["target_fields"]  # type: ignore[attr-defined]
        }
        findings = []
        for field_name in EvidenceFieldName:
            if field_name not in requested:
                continue
            if field_name is EvidenceFieldName.OE_NUMBERS:
                findings.append(
                    AiEvidenceFinding(
                        field_name=field_name,
                        state=FindingState.FOUND,
                        candidates=(
                            AiEvidenceCandidateValue(
                                raw_value="1K0615301",
                                normalized_value="1K0615301",
                                source_kind=EvidenceSourceKind.TITLE,
                                source_path="/title",
                                source_excerpt="1K0615301",
                                confidence=0.99,
                                explanation="The part number is literal in the title.",
                            ),
                        ),
                    )
                )
            else:
                findings.append(
                    AiEvidenceFinding(
                        field_name=field_name,
                        state=FindingState.NOT_FOUND,
                    )
                )
        return AiEvidenceProviderResult(
            output=AiEvidenceExtractionOutput(
                schema_version="marko-ai-evidence-output-v1",
                findings=tuple(findings),
            ),
            response_id=f"resp-runtime-{self.calls}",
            model=self.returned_model,
            usage={
                "input_tokens": 500,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens": 100,
                "output_tokens_details": {"reasoning_tokens": 40},
                "total_tokens": 600,
            },
            latency_ms=17,
        )


def _runtime_settings(*, mode: str = "shadow", api_key: str = "sk-test") -> object:
    return SimpleNamespace(
        pricing_ai_evidence_mode=mode,
        pricing_ai_evidence_model="gpt-5.6-luna",
        pricing_ai_evidence_reasoning_effort="medium",
        pricing_ai_evidence_max_output_tokens=1200,
        pricing_ai_evidence_max_input_chars=20_000,
        pricing_ai_evidence_max_calls_per_position=4,
        pricing_ai_evidence_max_candidates_per_position=4,
        pricing_ai_evidence_max_concurrency=2,
        pricing_llm_api_key=SecretStr(api_key),
        pricing_llm_base_url="https://provider.invalid/v1",
        pricing_llm_timeout_seconds=1.0,
    )


# --------------------------------------------------------------------------
# production runtime orchestration (fake provider, real PostgreSQL)
# --------------------------------------------------------------------------


@_SKIP
async def test_runtime_persists_verified_shadow_result_without_authority_mutation() -> (
    None
):
    seeded = await _seed(observations=1)
    provider = _FakeRuntimeProvider()
    try:
        async with async_session_factory() as session:
            result = await request_or_reuse_ai_evidence(
                session,
                workspace_id=seeded.workspace_id,
                pricing_run_item_id=seeded.run_item_id,
                market_observation_id=seeded.observation_ids[0],
                settings=_runtime_settings(),
                target_fields=(EvidenceFieldName.OE_NUMBERS,),
                provider=provider,
            )
            await session.commit()
            extraction_id = result.row.id

        async with async_session_factory() as session:
            row = await session.get(AiEvidenceExtraction, extraction_id)
            observation = await session.get(
                MarketObservation, seeded.observation_ids[0]
            )

        assert provider.calls == 1
        assert row is not None
        assert row.status == "COMPLETED"
        assert row.model_id == _MODEL
        assert row.provider_model == _MODEL
        assert row.verification_status == "VERIFIED"
        assert row.verified_field_count == 1
        assert row.candidate_snapshot_hash != "0" * 64
        assert row.usage["output_tokens_details"]["reasoning_tokens"] == 40
        assert row.usage["reasoning_tokens"] == 40
        assert row.usage["spend_estimate"]["rate_version"] == (
            "openai-gpt-5.6-luna-standard-2026-07-30"
        )
        assert row.usage["spend_estimate"]["disclaimer"] == (
            "ESTIMATE_NOT_BILLING_TRUTH"
        )
        assert row.verification_reasons["OE_NUMBERS"]["status"] == "VERIFIED"
        assert result.preview is None
        assert observation is not None
        assert observation.automatic_eligible is False
        assert observation.verified_matched_oe_norm == "1K0615301"
    finally:
        await _cleanup(seeded)


@_SKIP
@pytest.mark.parametrize(
    ("returned_model", "expected_code"),
    (
        ("gpt-5.6-luna-2026-08-01", "AI_EVIDENCE_PROVIDER_MODEL_REVISION_MISMATCH"),
        ("x" * 161, "AI_EVIDENCE_PROVIDER_MODEL_INVALID"),
    ),
)
async def test_runtime_model_mismatch_is_a_persisted_failure_not_a_database_error(
    returned_model: str, expected_code: str
) -> None:
    seeded = await _seed(observations=1)
    provider = _FakeRuntimeProvider(returned_model=returned_model)
    try:
        async with async_session_factory() as session:
            result = await request_or_reuse_ai_evidence(
                session,
                workspace_id=seeded.workspace_id,
                pricing_run_item_id=seeded.run_item_id,
                market_observation_id=seeded.observation_ids[0],
                settings=_runtime_settings(),
                target_fields=(EvidenceFieldName.OE_NUMBERS,),
                provider=provider,
            )
            await session.commit()
            extraction_id = result.row.id

        async with async_session_factory() as session:
            row = await session.get(AiEvidenceExtraction, extraction_id)

        assert provider.calls == 1
        assert row is not None
        assert row.status == "FAILED"
        assert row.error_code == expected_code
        assert row.provider_model is None
        assert row.raw_output is None
        assert returned_model not in (row.error_detail or "")
    finally:
        await _cleanup(seeded)


@_SKIP
@pytest.mark.parametrize(
    ("mode", "api_key", "expected_status"),
    (("off", "sk-test", "SKIPPED"), ("shadow", "", "UNCONFIGURED")),
)
async def test_runtime_off_or_missing_key_persists_zero_call_state(
    mode: str, api_key: str, expected_status: str
) -> None:
    seeded = await _seed(observations=1)
    provider = _FakeRuntimeProvider()
    try:
        async with async_session_factory() as session:
            result = await request_or_reuse_ai_evidence(
                session,
                workspace_id=seeded.workspace_id,
                pricing_run_item_id=seeded.run_item_id,
                market_observation_id=seeded.observation_ids[0],
                settings=_runtime_settings(mode=mode, api_key=api_key),
                target_fields=(EvidenceFieldName.OE_NUMBERS,),
                provider=provider,
            )
            await session.commit()

        assert provider.calls == 0
        assert result.row.status == expected_status
        assert result.row.raw_output is None
        assert result.row.provider_response_id is None
        assert result.row.provider_model is None
        assert result.row.usage == {}
        assert result.row.latency_ms == 0
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_runtime_exact_input_is_called_once_then_cached_once() -> None:
    seeded = await _seed(observations=1)
    provider = _FakeRuntimeProvider()
    reset_ai_evidence_telemetry()
    try:

        async def invoke() -> tuple[str, UUID, bool, bool, bool]:
            async with async_session_factory() as session:
                result = await request_or_reuse_ai_evidence(
                    session,
                    workspace_id=seeded.workspace_id,
                    pricing_run_item_id=seeded.run_item_id,
                    market_observation_id=seeded.observation_ids[0],
                    settings=_runtime_settings(),
                    target_fields=(EvidenceFieldName.OE_NUMBERS,),
                    provider=provider,
                )
                await session.commit()
                return (
                    result.row.status,
                    result.row.id,
                    result.reused,
                    result.extraction is not None,
                    bool(result.verification and result.verification.bound),
                )

        first = await invoke()
        second = await invoke()
        third = await invoke()

        async with async_session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(AiEvidenceExtraction)
                        .where(AiEvidenceExtraction.workspace_id == seeded.workspace_id)
                        .order_by(AiEvidenceExtraction.attempt_no)
                    )
                ).all()
            )

        assert provider.calls == 1
        assert first == ("COMPLETED", first[1], False, True, True)
        assert second == ("CACHED", second[1], True, True, True)
        assert third == ("CACHED", second[1], True, True, True)
        assert [row.status for row in rows] == ["COMPLETED", "CACHED"]
        assert rows[1].cache_hit_extraction_id == rows[0].id
        assert rows[0].input_hash == rows[1].input_hash
        telemetry = ai_evidence_telemetry_snapshot()
        assert telemetry["counters"]["requested"] == 1
        assert telemetry["counters"]["provider_attempts"] == 1
        assert telemetry["counters"]["completed"] == 1
        assert telemetry["counters"]["cached"] == 2
        assert telemetry["tokens"]["reasoning_tokens"] == 40
        assert telemetry["rate_versions"] == {
            "openai-gpt-5.6-luna-standard-2026-07-30": 1
        }
    finally:
        reset_ai_evidence_telemetry()
        await _cleanup(seeded)


@_SKIP
async def test_runtime_changed_target_fields_are_a_cache_miss() -> None:
    seeded = await _seed(observations=1)
    provider = _FakeRuntimeProvider()
    try:
        hashes: list[str] = []
        for target in (EvidenceFieldName.OE_NUMBERS, EvidenceFieldName.BRAND):
            async with async_session_factory() as session:
                result = await request_or_reuse_ai_evidence(
                    session,
                    workspace_id=seeded.workspace_id,
                    pricing_run_item_id=seeded.run_item_id,
                    market_observation_id=seeded.observation_ids[0],
                    settings=_runtime_settings(),
                    target_fields=(target,),
                    provider=provider,
                )
                hashes.append(result.row.input_hash)
                await session.commit()

        assert provider.calls == 2
        assert len(set(hashes)) == 2
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_runtime_workspace_mismatch_fails_before_provider_or_persistence() -> (
    None
):
    seeded = await _seed(observations=1)
    provider = _FakeRuntimeProvider()
    try:
        async with async_session_factory() as session:
            with pytest.raises(AiEvidenceRuntimeError) as raised:
                await request_or_reuse_ai_evidence(
                    session,
                    workspace_id=uuid4(),
                    pricing_run_item_id=seeded.run_item_id,
                    market_observation_id=seeded.observation_ids[0],
                    settings=_runtime_settings(),
                    target_fields=(EvidenceFieldName.OE_NUMBERS,),
                    provider=provider,
                )
            await session.rollback()

        async with async_session_factory() as session:
            count = await session.scalar(
                select(func.count(AiEvidenceExtraction.id)).where(
                    AiEvidenceExtraction.market_observation_id
                    == seeded.observation_ids[0]
                )
            )

        assert raised.value.code == "AI_EVIDENCE_BOUND_INPUT_NOT_FOUND"
        assert provider.calls == 0
        assert count == 0
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_runtime_concurrent_exact_requests_make_one_provider_call() -> None:
    seeded = await _seed(observations=1)
    provider = _FakeRuntimeProvider(delay_seconds=0.1)
    try:

        async def invoke() -> str:
            async with async_session_factory() as session:
                result = await request_or_reuse_ai_evidence(
                    session,
                    workspace_id=seeded.workspace_id,
                    pricing_run_item_id=seeded.run_item_id,
                    market_observation_id=seeded.observation_ids[0],
                    settings=_runtime_settings(),
                    target_fields=(EvidenceFieldName.OE_NUMBERS,),
                    provider=provider,
                )
                await session.commit()
                return result.row.status

        statuses = await asyncio.gather(invoke(), invoke())

        async with async_session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(AiEvidenceExtraction).where(
                            AiEvidenceExtraction.workspace_id == seeded.workspace_id
                        )
                    )
                ).all()
            )

        assert provider.calls == 1
        assert sorted(statuses) == ["CACHED", "COMPLETED"]
        assert sorted(row.status for row in rows) == ["CACHED", "COMPLETED"]
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_concurrent_waiter_propagates_failed_terminal_without_cache_row() -> None:
    class _DelayedFailureProvider:
        calls = 0

        async def extract(self, *, request: object) -> AiEvidenceProviderResult:
            del request
            self.calls += 1
            await asyncio.sleep(0.1)
            raise AiEvidenceProviderError(
                "AI_EVIDENCE_HTTP_ERROR",
                "provider returned HTTP 503",
                provider_attempts=1,
            )

    seeded = await _seed(observations=1)
    provider = _DelayedFailureProvider()
    try:

        async def invoke() -> AiEvidenceExtraction:
            async with async_session_factory() as session:
                result = await request_or_reuse_ai_evidence(
                    session,
                    workspace_id=seeded.workspace_id,
                    pricing_run_item_id=seeded.run_item_id,
                    market_observation_id=seeded.observation_ids[0],
                    settings=_runtime_settings(),
                    target_fields=(EvidenceFieldName.OE_NUMBERS,),
                    provider=provider,
                )
                return result.row

        returned = await asyncio.gather(invoke(), invoke())

        async with async_session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(AiEvidenceExtraction).where(
                            AiEvidenceExtraction.workspace_id == seeded.workspace_id
                        )
                    )
                ).all()
            )
        assert provider.calls == 1
        assert [row.status for row in returned] == ["FAILED", "FAILED"]
        assert returned[0].id == returned[1].id
        assert len(rows) == 1
        assert rows[0].status == "FAILED"
        assert rows[0].cache_hit_extraction_id is None
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_runtime_recovery_spends_a_second_bounded_physical_attempt() -> None:
    """A possible accepted POST and its recovery are two bounded transmissions."""

    seeded = await _seed(observations=1)
    settings = _runtime_settings()
    settings.pricing_ai_evidence_max_calls_per_position = 2
    try:
        async with async_session_factory() as session:
            observation, capture, _retained_payload = await _load_bound_evidence(
                session,
                workspace_id=seeded.workspace_id,
                pricing_run_item_id=seeded.run_item_id,
                market_observation_id=seeded.observation_ids[0],
            )
            config = resolve_ai_evidence_config(settings)
            prepared = build_extraction_input(
                capture=capture,
                observation=observation,
                config=config,
                target_fields=(EvidenceFieldName.OE_NUMBERS,),
            )
            input_hash = ai_evidence_runtime_input_hash(prepared.binding.as_dict())
            budget = evidence_extraction_budget(
                position_id=seeded.run_item_id,
                workspace_id=seeded.workspace_id,
                limit=2,
            )
            # The first worker may have reached the provider before it died.
            # Its physical transmission therefore remains spent.
            assert await budget.reserve() is True
            request_event = _request_event(
                workspace_id=seeded.workspace_id,
                pricing_run_item_id=seeded.run_item_id,
                observation=observation,
                capture=capture,
                prepared=prepared,
                input_hash=input_hash,
                attempt_no=1,
                config=config,
            )
            session.add(request_event)
            await session.flush()
            session.add(
                AiEvidenceRequestClaim(
                    request_event_id=request_event.id,
                    claim_token=uuid4(),
                    recovery=False,
                    lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
            await session.commit()
            request_event_id = request_event.id
            request_key = request_event.request_key

        recovery_budget = evidence_extraction_budget(
            position_id=seeded.run_item_id,
            workspace_id=seeded.workspace_id,
            limit=2,
        )
        provider = _FakeRuntimeProvider(budget=recovery_budget)

        async with async_session_factory() as session:
            result = await request_or_reuse_ai_evidence(
                session,
                workspace_id=seeded.workspace_id,
                pricing_run_item_id=seeded.run_item_id,
                market_observation_id=seeded.observation_ids[0],
                settings=settings,
                target_fields=(EvidenceFieldName.OE_NUMBERS,),
                provider=provider,
            )

        budget = evidence_extraction_budget(
            position_id=seeded.run_item_id,
            workspace_id=seeded.workspace_id,
            limit=2,
        )
        async with async_session_factory() as session:
            claims = list(
                (
                    await session.scalars(
                        select(AiEvidenceRequestClaim)
                        .where(
                            AiEvidenceRequestClaim.request_event_id == request_event_id
                        )
                        .order_by(AiEvidenceRequestClaim.claimed_at)
                    )
                ).all()
            )
            events = list(
                (
                    await session.scalars(
                        select(AiEvidenceRequestEvent).where(
                            AiEvidenceRequestEvent.workspace_id == seeded.workspace_id
                        )
                    )
                ).all()
            )

        assert provider.calls == 1
        assert result.row.status == "COMPLETED"
        assert result.row.request_event_id == request_event_id
        assert result.row.request_key == request_key
        assert await budget.spent() == 2
        assert len(events) == 1
        assert len(claims) == 2
        assert claims[-1].recovery is True
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_runtime_recovery_refuses_post_when_physical_budget_is_spent() -> None:
    seeded = await _seed(observations=1)
    settings = _runtime_settings()
    settings.pricing_ai_evidence_max_calls_per_position = 1
    try:
        async with async_session_factory() as session:
            observation, capture, _retained_payload = await _load_bound_evidence(
                session,
                workspace_id=seeded.workspace_id,
                pricing_run_item_id=seeded.run_item_id,
                market_observation_id=seeded.observation_ids[0],
            )
            config = resolve_ai_evidence_config(settings)
            prepared = build_extraction_input(
                capture=capture,
                observation=observation,
                config=config,
                target_fields=(EvidenceFieldName.OE_NUMBERS,),
            )
            input_hash = ai_evidence_runtime_input_hash(prepared.binding.as_dict())
            spent = evidence_extraction_budget(
                position_id=seeded.run_item_id,
                workspace_id=seeded.workspace_id,
                limit=1,
            )
            assert await spent.reserve() is True
            request_event = _request_event(
                workspace_id=seeded.workspace_id,
                pricing_run_item_id=seeded.run_item_id,
                observation=observation,
                capture=capture,
                prepared=prepared,
                input_hash=input_hash,
                attempt_no=1,
                config=config,
            )
            session.add(request_event)
            await session.flush()
            session.add(
                AiEvidenceRequestClaim(
                    request_event_id=request_event.id,
                    claim_token=uuid4(),
                    recovery=False,
                    lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
            await session.commit()
            event_id = request_event.id

        provider = _FakeRuntimeProvider(
            budget=evidence_extraction_budget(
                position_id=seeded.run_item_id,
                workspace_id=seeded.workspace_id,
                limit=1,
            )
        )
        async with async_session_factory() as session:
            result = await request_or_reuse_ai_evidence(
                session,
                workspace_id=seeded.workspace_id,
                pricing_run_item_id=seeded.run_item_id,
                market_observation_id=seeded.observation_ids[0],
                settings=settings,
                target_fields=(EvidenceFieldName.OE_NUMBERS,),
                provider=provider,
            )

        assert provider.calls == 0
        assert result.row.status == "FAILED"
        assert result.row.error_code == "LLM_PROVIDER_CALL_BUDGET_EXHAUSTED"
        assert result.row.request_event_id == event_id
        assert await spent.spent() == 1
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_production_shadow_selector_calls_only_parser_unknown_candidate() -> None:
    seeded = await _seed(
        observations=4,
        shadow_scenarios=("unknown", "known", "owned", "reject"),
    )
    provider = _FakeRuntimeProvider()
    try:
        result = await process_ai_evidence_position(
            seeded.run_item_id,
            settings=_runtime_settings(),
            provider=provider,
        )

        assert provider.calls == 1
        assert result.selected == 1
        assert result.completed == 1
        assert result.failed == 0
        assert dict(result.refused) == {
            str(seeded.observation_ids[1]): "NO_TARGET_FIELDS",
            str(seeded.observation_ids[2]): "OWNED_SELLER",
            str(seeded.observation_ids[3]): "DETERMINISTIC_REJECT",
        }
        async with async_session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(AiEvidenceExtraction).where(
                            AiEvidenceExtraction.workspace_id == seeded.workspace_id
                        )
                    )
                ).all()
            )
            requests = list(
                (
                    await session.scalars(
                        select(AiEvidenceRequestEvent).where(
                            AiEvidenceRequestEvent.workspace_id == seeded.workspace_id
                        )
                    )
                ).all()
            )
        assert len(rows) == 1
        assert len(requests) == 1
        assert rows[0].market_observation_id == seeded.observation_ids[0]
        assert requests[0].target_fields == ["CONDITION"]
    finally:
        await _cleanup(seeded)


# --------------------------------------------------------------------------
# append-only / immutability
# --------------------------------------------------------------------------


@_SKIP
async def test_extraction_rows_cannot_be_updated_or_deleted() -> None:
    seeded = await _seed()
    try:
        async with async_session_factory() as session:
            row = _row(seeded)
            session.add(row)
            await session.commit()
            row_id = row.id

        for statement in (
            text(
                "UPDATE ai_evidence_extractions SET verification_status='REJECTED' "
                "WHERE id=:id"
            ),
            text("DELETE FROM ai_evidence_extractions WHERE id=:id"),
        ):
            async with async_session_factory() as session:
                with pytest.raises(DBAPIError, match="append-only"):
                    await session.execute(statement, {"id": row_id})
                await session.rollback()

        async with async_session_factory() as session:
            surviving = await session.get(AiEvidenceExtraction, row_id)
            assert surviving is not None
            assert surviving.verification_status == "VERIFIED"
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_request_event_and_claim_rows_are_append_only() -> None:
    seeded = await _seed(observations=1)
    try:
        async with async_session_factory() as session:
            await request_or_reuse_ai_evidence(
                session,
                workspace_id=seeded.workspace_id,
                pricing_run_item_id=seeded.run_item_id,
                market_observation_id=seeded.observation_ids[0],
                settings=_runtime_settings(),
                target_fields=(EvidenceFieldName.OE_NUMBERS,),
                provider=_FakeRuntimeProvider(),
            )

        async with async_session_factory() as session:
            event = await session.scalar(
                select(AiEvidenceRequestEvent).where(
                    AiEvidenceRequestEvent.workspace_id == seeded.workspace_id
                )
            )
            assert event is not None
            claim = await session.scalar(
                select(AiEvidenceRequestClaim).where(
                    AiEvidenceRequestClaim.request_event_id == event.id
                )
            )
        assert claim is not None

        for table_name, row_id in (
            ("ai_evidence_request_events", event.id),
            ("ai_evidence_request_claims", claim.id),
        ):
            for statement in (
                text(f"UPDATE {table_name} SET id=id WHERE id=:id"),
                text(f"DELETE FROM {table_name} WHERE id=:id"),
            ):
                async with async_session_factory() as session:
                    with pytest.raises(DBAPIError, match="append-only"):
                        await session.execute(statement, {"id": row_id})
                    await session.rollback()
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_a_no_request_status_cannot_carry_provider_evidence() -> None:
    """The persisted half of "a missing key performs no request".

    A service that regressed into calling the provider and then labelling the
    row ``UNCONFIGURED`` would have nowhere to put the response id, so the
    regression cannot be hidden behind a status string.
    """

    seeded = await _seed()
    try:
        async with async_session_factory() as session:
            session.add(
                _row(
                    seeded,
                    status="UNCONFIGURED",
                    raw_output=None,
                    provider_response_id="resp_should_not_exist",
                    provider_model=None,
                    usage={},
                    latency_ms=0,
                    verification_status="NOT_RUN",
                    findings=[],
                    verification_reasons={},
                    verified_field_count=0,
                )
            )
            with pytest.raises(IntegrityError, match="no_request_states"):
                await session.commit()
            await session.rollback()

        async with async_session_factory() as session:
            session.add(
                _row(
                    seeded,
                    status="UNCONFIGURED",
                    raw_output=None,
                    provider_response_id=None,
                    provider_model=None,
                    usage={},
                    latency_ms=0,
                    verification_status="NOT_RUN",
                    findings=[],
                    verification_reasons={},
                    verified_field_count=0,
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            stored = await session.scalar(
                select(AiEvidenceExtraction).where(
                    AiEvidenceExtraction.workspace_id == seeded.workspace_id
                )
            )
            assert stored is not None
            assert stored.status == "UNCONFIGURED"
            assert stored.provider_response_id is None
            assert stored.latency_ms == 0
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_a_cached_row_must_name_the_row_it_reused() -> None:
    seeded = await _seed()
    try:
        async with async_session_factory() as session:
            session.add(_row(seeded, status="CACHED", cache_hit_extraction_id=None))
            with pytest.raises(DBAPIError, match="AI_EVIDENCE_CACHE_SOURCE_INVALID"):
                await session.commit()
            await session.rollback()
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_database_rejects_cache_row_pointing_to_failed_extraction() -> None:
    seeded = await _seed()
    try:
        async with async_session_factory() as session:
            failed = _row(
                seeded,
                status="FAILED",
                raw_output=None,
                findings=[],
                verification_status="NOT_RUN",
                verification_reasons={},
                verification_report={"status": "NO_OUTPUT"},
                verified_field_count=0,
                rejected_field_count=0,
                provider_response_id=None,
                provider_model=None,
                usage={},
                latency_ms=0,
                error_code="AI_EVIDENCE_HTTP_ERROR",
                error_detail="provider returned HTTP 503",
            )
            session.add(failed)
            await session.commit()

        async with async_session_factory() as session:
            poisoned = _row(
                seeded,
                attempt_no=2,
                status="CACHED",
                cache_hit_extraction_id=failed.id,
                provider_response_id=None,
                usage={},
                latency_ms=0,
            )
            session.add(poisoned)
            with pytest.raises(DBAPIError, match="AI_EVIDENCE_CACHE_SOURCE_INVALID"):
                await session.commit()
            await session.rollback()
    finally:
        await _cleanup(seeded)


# --------------------------------------------------------------------------
# identity, idempotency and cache
# --------------------------------------------------------------------------


@_SKIP
async def test_retrying_the_exact_same_immutable_input_is_one_row() -> None:
    seeded = await _seed()
    try:
        async with async_session_factory() as session:
            session.add(_row(seeded))
            await session.commit()

        async with async_session_factory() as session:
            session.add(_row(seeded))
            with pytest.raises(IntegrityError, match="request_key"):
                await session.commit()
            await session.rollback()

        async with async_session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(AiEvidenceExtraction)
                .where(AiEvidenceExtraction.workspace_id == seeded.workspace_id)
            )
            assert count == 1
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_the_stored_row_is_found_by_the_cache_key_of_an_identical_input() -> None:
    seeded = await _seed()
    try:
        async with async_session_factory() as session:
            session.add(_row(seeded))
            await session.commit()

        wanted = _input_hash(capture_sha256=seeded.capture_sha256)
        async with async_session_factory() as session:
            hit = await session.scalar(
                select(AiEvidenceExtraction).where(
                    AiEvidenceExtraction.workspace_id == seeded.workspace_id,
                    AiEvidenceExtraction.input_hash == wanted,
                    AiEvidenceExtraction.status.in_(("COMPLETED", "CACHED")),
                )
            )
            assert hit is not None
            assert hit.capture_sha256 == seeded.capture_sha256
    finally:
        await _cleanup(seeded)


@_SKIP
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capture_sha256", "f" * 64),
        ("candidate_snapshot_hash", "e" * 64),
        ("model_id", "gpt-5.6-luna-pro"),
        ("prompt_version", "ai-evidence-prompt-v2"),
        ("schema_version", "ai-evidence-schema-v2"),
        ("extractor_version", "ai-evidence-extractor-v2"),
        ("reasoning_effort", "high"),
    ],
)
async def test_a_changed_input_or_version_misses_the_cache(
    field: str, value: str
) -> None:
    """Each of the seven facts, checked against a real index lookup.

    The unit-level version of this asserts the digest differs; this one asserts
    the *query* misses, which is what a caller actually relies on.
    """

    seeded = await _seed()
    try:
        stored_hash = _input_hash(capture_sha256=seeded.capture_sha256)
        async with async_session_factory() as session:
            session.add(_row(seeded))
            await session.commit()

        changed_hash = _input_hash(
            **{"capture_sha256": seeded.capture_sha256, field: value}
        )
        assert changed_hash != stored_hash

        async with async_session_factory() as session:
            miss = await session.scalar(
                select(AiEvidenceExtraction).where(
                    AiEvidenceExtraction.workspace_id == seeded.workspace_id,
                    AiEvidenceExtraction.input_hash == changed_hash,
                )
            )
            assert miss is None
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_a_second_attempt_on_the_same_input_is_a_distinct_row() -> None:
    seeded = await _seed()
    try:
        async with async_session_factory() as session:
            session.add(_row(seeded, attempt_no=1))
            session.add(
                _row(
                    seeded,
                    attempt_no=2,
                    status="FAILED",
                    error_code="LLM_HTTP_ERROR",
                    error_detail="provider returned HTTP 500",
                    raw_output=None,
                    verification_status="NOT_RUN",
                    findings=[],
                    verification_reasons={},
                    verified_field_count=0,
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AiEvidenceExtraction)
                        .where(AiEvidenceExtraction.workspace_id == seeded.workspace_id)
                        .order_by(AiEvidenceExtraction.attempt_no)
                    )
                )
                .scalars()
                .all()
            )
            assert [row.attempt_no for row in rows] == [1, 2]
            assert rows[0].input_hash == rows[1].input_hash
            assert rows[0].request_key != rows[1].request_key
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_an_identical_input_in_another_workspace_is_not_a_cache_hit() -> None:
    first = await _seed()
    second = await _seed()
    try:
        shared_hash = _input_hash(capture_sha256="d" * 64)
        async with async_session_factory() as session:
            session.add(_row(first, input_hash=shared_hash, capture_sha256="d" * 64))
            await session.commit()

        async with async_session_factory() as session:
            leaked = await session.scalar(
                select(AiEvidenceExtraction).where(
                    AiEvidenceExtraction.workspace_id == second.workspace_id,
                    AiEvidenceExtraction.input_hash == shared_hash,
                )
            )
            assert leaked is None

            unscoped = (
                (
                    await session.execute(
                        select(AiEvidenceExtraction).where(
                            AiEvidenceExtraction.input_hash == shared_hash
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [row.workspace_id for row in unscoped] == [first.workspace_id]
    finally:
        await _cleanup(second)
        await _cleanup(first)


# --------------------------------------------------------------------------
# durable call budget
# --------------------------------------------------------------------------


class _Poster:
    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.requests = 0

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests += 1
            status = self._statuses.pop(0) if self._statuses else 200
            return httpx.Response(status, json={"id": f"resp-{self.requests}"})

        return httpx.MockTransport(handle)


async def _drive(budget: PositionCallBudget, poster: _Poster) -> BudgetedAttempts:
    attempts = BudgetedAttempts(budget)
    async with httpx.AsyncClient(transport=poster.transport()) as client:
        async for _ in attempts:
            response = await client.post("https://provider.invalid/v1/responses")
            if response.status_code == 429 or response.status_code >= 500:
                attempts.last_failure = f"HTTP {response.status_code}"
                continue
            break
    return attempts


@_SKIP
async def test_every_physical_http_attempt_consumes_one_durable_slot() -> None:
    seeded = await _seed()
    ledger = DurableProviderCallLedger()
    try:
        budget = evidence_extraction_budget(
            position_id=seeded.run_item_id,
            workspace_id=seeded.workspace_id,
            limit=5,
            ledger=ledger,
        )
        poster = _Poster([429, 200])

        attempts = await _drive(budget, poster)

        assert poster.requests == MAX_PHYSICAL_ATTEMPTS == 2
        assert attempts.made == 2
        assert (
            await ledger.spent(
                position_id=seeded.run_item_id,
                purpose=AI_EVIDENCE_EXTRACTION_PURPOSE,
            )
            == 2
        )
        # The count survives the object that made it: a restarted worker reads
        # the same row rather than starting from zero.
        assert (
            await DurableProviderCallLedger().spent(
                position_id=seeded.run_item_id,
                purpose=AI_EVIDENCE_EXTRACTION_PURPOSE,
            )
            == 2
        )
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_a_budget_of_one_buys_one_post_and_no_retry() -> None:
    seeded = await _seed()
    try:
        budget = evidence_extraction_budget(
            position_id=seeded.run_item_id,
            workspace_id=seeded.workspace_id,
            limit=1,
        )
        poster = _Poster([500, 200])

        attempts = await _drive(budget, poster)

        assert poster.requests == 1
        assert attempts.refused_retry_after == "HTTP 500"
        assert await budget.spent() == 1
        assert await budget.remaining() == 0
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_concurrent_and_restarted_claimants_share_one_bound() -> None:
    seeded = await _seed()
    try:
        # Twelve simultaneous claimants, each with its own ledger object, which
        # is what a concurrency wave plus a restarted second worker looks like.
        budgets = [
            evidence_extraction_budget(
                position_id=seeded.run_item_id,
                workspace_id=seeded.workspace_id,
                limit=3,
                ledger=DurableProviderCallLedger(),
            )
            for _ in range(12)
        ]
        granted = await asyncio.gather(*(budget.reserve() for budget in budgets))

        assert sum(1 for value in granted if value) == 3
        assert (
            await DurableProviderCallLedger().spent(
                position_id=seeded.run_item_id,
                purpose=AI_EVIDENCE_EXTRACTION_PURPOSE,
            )
            == 3
        )
        # A "force" style path is just another claimant: it cannot mint slots.
        forced = evidence_extraction_budget(
            position_id=seeded.run_item_id,
            workspace_id=seeded.workspace_id,
            limit=3,
        )
        assert await forced.reserve() is False
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_a_started_budget_cannot_be_widened_by_a_later_setting() -> None:
    """A raised setting plus a restart must not hand a spent position more calls.

    This is the exact regression the durable ledger exists for: the failure mode
    is invisible -- no error, no log line, just a position that quietly bought
    nine more calls it had already been refused.
    """

    seeded = await _seed()
    try:
        started = evidence_extraction_budget(
            position_id=seeded.run_item_id,
            workspace_id=seeded.workspace_id,
            limit=2,
        )
        assert await started.reserve() is True
        assert await started.reserve() is True
        assert await started.reserve() is False

        # Deployment raises PRICING_AI_EVIDENCE_MAX_CALLS_PER_POSITION and the
        # worker restarts.
        raised = evidence_extraction_budget(
            position_id=seeded.run_item_id,
            workspace_id=seeded.workspace_id,
            limit=50,
            ledger=DurableProviderCallLedger(),
        )
        assert await raised.effective_limit() == 2
        assert await raised.remaining() == 0
        assert await raised.reserve() is False

        async with async_session_factory() as session:
            stored_limit = await session.scalar(
                select(provider_call_budget_table.c.call_limit).where(
                    provider_call_budget_table.c.pricing_run_item_id
                    == seeded.run_item_id,
                    provider_call_budget_table.c.purpose
                    == AI_EVIDENCE_EXTRACTION_PURPOSE,
                )
            )
        assert stored_limit == 2
    finally:
        await _cleanup(seeded)


@_SKIP
async def test_extraction_and_comparability_hold_separate_durable_rows() -> None:
    seeded = await _seed()
    try:
        extraction = evidence_extraction_budget(
            position_id=seeded.run_item_id,
            workspace_id=seeded.workspace_id,
            limit=2,
        )
        comparability = PositionCallBudget(
            ledger=DurableProviderCallLedger(),
            position_id=seeded.run_item_id,
            workspace_id=seeded.workspace_id,
            limit=10,
        )

        assert await extraction.reserve() is True
        assert await extraction.reserve() is True
        assert await extraction.reserve() is False

        # The narrow extraction ceiling must not have narrowed comparability.
        assert await comparability.effective_limit() == 10
        assert await comparability.reserve() is True

        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        provider_call_budget_table.c.purpose,
                        provider_call_budget_table.c.spent,
                        provider_call_budget_table.c.call_limit,
                    )
                    .where(
                        provider_call_budget_table.c.pricing_run_item_id
                        == seeded.run_item_id
                    )
                    .order_by(provider_call_budget_table.c.purpose)
                )
            ).all()
        assert [tuple(row) for row in rows] == [
            (AI_EVIDENCE_EXTRACTION_PURPOSE, 2, 2),
            (COMPARABILITY_PURPOSE, 1, 10),
        ]
    finally:
        await _cleanup(seeded)


# --------------------------------------------------------------------------
# migration
# --------------------------------------------------------------------------


def _async_url(database: str) -> str:
    url = make_url(os.environ["DATABASE_URL"])
    return (
        f"postgresql+asyncpg://{url.username}:{url.password}"
        f"@{url.host}:{url.port}/{database}"
    )


def _alembic(database: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "alembic", "-c", "alembic.ini", *args],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": _async_url(database)},
    )


async def _admin(sql: str) -> None:
    url = make_url(os.environ["DATABASE_URL"])
    dsn = f"postgresql://{url.username}:{url.password}@{url.host}:{url.port}/postgres"
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(sql)
    finally:
        await connection.close()


def _seed_populated_ai_evidence_database(
    database: str,
) -> subprocess.CompletedProcess[str]:
    script = """
import asyncio
from test_ai_evidence_extraction_postgres import _row, _seed
from marko.infrastructure.db.session import async_session_factory

async def main():
    seeded = await _seed(observations=1)
    async with async_session_factory() as session:
        session.add(_row(seeded))
        await session.commit()

asyncio.run(main())
"""
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DATABASE_URL": _async_url(database),
            "PYTHONPATH": f"{BACKEND_ROOT / 'src'}:{BACKEND_ROOT / 'tests'}",
        },
    )


def _seed_populated_ai_request_database(
    database: str,
) -> subprocess.CompletedProcess[str]:
    script = """
import asyncio
from test_ai_evidence_extraction_postgres import (
    EvidenceFieldName,
    _FakeRuntimeProvider,
    _runtime_settings,
    _seed,
    request_or_reuse_ai_evidence,
)
from marko.infrastructure.db.session import async_session_factory

async def main():
    seeded = await _seed(observations=1)
    async with async_session_factory() as session:
        await request_or_reuse_ai_evidence(
            session,
            workspace_id=seeded.workspace_id,
            pricing_run_item_id=seeded.run_item_id,
            market_observation_id=seeded.observation_ids[0],
            settings=_runtime_settings(),
            target_fields=(EvidenceFieldName.OE_NUMBERS,),
            provider=_FakeRuntimeProvider(),
        )
        await session.commit()

asyncio.run(main())
"""
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DATABASE_URL": _async_url(database),
            "PYTHONPATH": f"{BACKEND_ROOT / 'src'}:{BACKEND_ROOT / 'tests'}",
        },
    )


@_SKIP
async def test_populated_0041_database_upgrades_through_binding_backfill() -> None:
    """0042 must suspend 0041's append-only trigger for its owned backfill."""

    if "p15017" not in (make_url(os.environ["DATABASE_URL"]).database or "").casefold():
        pytest.fail("DATABASE_URL must name a disposable database containing 'p15017'")
    database = f"marko_p15017_ai_populated_{uuid4().hex[:8]}"
    await _admin(f'DROP DATABASE IF EXISTS "{database}"')
    await _admin(f'CREATE DATABASE "{database}" OWNER marko')
    try:
        head = _alembic(database, "upgrade", "head")
        assert head.returncode == 0, head.stdout + head.stderr
        seeded = _seed_populated_ai_evidence_database(database)
        assert seeded.returncode == 0, seeded.stdout + seeded.stderr

        back = _alembic(database, "downgrade", "20260802_0041")
        assert back.returncode == 0, back.stdout + back.stderr
        forward = _alembic(database, "upgrade", "head")
        assert forward.returncode == 0, forward.stdout + forward.stderr

        connection = await asyncpg.connect(
            make_url(_async_url(database))
            .render_as_string(hide_password=False)
            .replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            row = await connection.fetchrow(
                "SELECT source_listing_id, verifier_version, "
                "source_offer_locator_sha256 "
                "FROM ai_evidence_extractions"
            )
            assert row is not None
            assert row["source_listing_id"] == "listing-ai-evidence-0"
            assert row["verifier_version"] == "legacy-unverifiable"
            assert row["source_offer_locator_sha256"] == "0" * 64
        finally:
            await connection.close()
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')


@_SKIP
async def test_populated_0043_downgrade_refuses_to_erase_request_history() -> None:
    """A downgrade must not silently delete immutable pre-transmission history."""

    if "p15017" not in (make_url(os.environ["DATABASE_URL"]).database or "").casefold():
        pytest.fail("DATABASE_URL must name a disposable database containing 'p15017'")
    database = f"marko_p15017_ai_requests_{uuid4().hex[:8]}"
    await _admin(f'DROP DATABASE IF EXISTS "{database}"')
    await _admin(f'CREATE DATABASE "{database}" OWNER marko')
    try:
        head = _alembic(database, "upgrade", "head")
        assert head.returncode == 0, head.stdout + head.stderr
        seeded = _seed_populated_ai_request_database(database)
        assert seeded.returncode == 0, seeded.stdout + seeded.stderr

        downgrade = _alembic(database, "downgrade", "20260802_0042")
        output = downgrade.stdout + downgrade.stderr
        assert downgrade.returncode != 0
        assert "IRREVERSIBLE_MIGRATION_20260802_0043" in output
        assert "1 AI evidence request event(s)" in output
        assert "1 request claim(s)" in output

        current = _alembic(database, "current")
        assert current.returncode == 0, current.stdout + current.stderr
        # Alembic runs the multi-revision downgrade transactionally.  A
        # refusal in 0043 therefore rolls the whole command back to whichever
        # revision is the current project head, including later additive
        # migrations.
        assert "(head)" in current.stdout

        connection = await asyncpg.connect(
            make_url(_async_url(database))
            .render_as_string(hide_password=False)
            .replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            counts = await connection.fetchrow(
                "SELECT "
                "(SELECT count(*) FROM ai_evidence_request_events) AS events, "
                "(SELECT count(*) FROM ai_evidence_request_claims) AS claims, "
                "(SELECT count(*) FROM ai_evidence_extractions "
                " WHERE request_event_id IS NOT NULL) AS bound_extractions"
            )
            assert counts is not None
            assert dict(counts) == {
                "events": 1,
                "claims": 1,
                "bound_extractions": 1,
            }
            triggers = await connection.fetch(
                "SELECT tgname FROM pg_trigger WHERE tgname = ANY($1::text[])",
                [
                    "trg_ai_evidence_request_events_append_only",
                    "trg_ai_evidence_request_claims_append_only",
                ],
            )
            assert {row["tgname"] for row in triggers} == {
                "trg_ai_evidence_request_events_append_only",
                "trg_ai_evidence_request_claims_append_only",
            }
        finally:
            await connection.close()
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')


@_SKIP
async def test_ai_evidence_migrations_upgrade_downgrade_and_leave_no_drift() -> None:
    """A fresh database, not the shared one, so the whole chain is exercised.

    The database name carries ``p15017`` because that is what marks it
    disposable, and it is dropped at the end whether or not the assertions pass.
    """

    if "p15017" not in (make_url(os.environ["DATABASE_URL"]).database or "").casefold():
        pytest.fail("DATABASE_URL must name a disposable database containing 'p15017'")

    database = f"marko_p15017_ai_evidence_{uuid4().hex[:8]}"
    await _admin(f'DROP DATABASE IF EXISTS "{database}"')
    await _admin(f'CREATE DATABASE "{database}" OWNER marko')
    try:
        upgraded = _alembic(database, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

        current = _alembic(database, "current")
        assert current.returncode == 0, current.stdout + current.stderr
        assert "(head)" in current.stdout

        checked = _alembic(database, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr

        # The append-only trigger is created by the migration, not by the ORM.
        connection = await asyncpg.connect(
            make_url(_async_url(database))
            .render_as_string(hide_password=False)
            .replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            trigger = await connection.fetchval(
                "SELECT tgname FROM pg_trigger WHERE tgname="
                "'trg_ai_evidence_extractions_append_only'"
            )
            assert trigger == "trg_ai_evidence_extractions_append_only"
            binding_columns = await connection.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='ai_evidence_extractions' AND column_name = ANY($1::text[])",
                [
                    "source_listing_id",
                    "source_offer_locator_sha256",
                    "document_sha256",
                    "prepared_input_sha256",
                    "model_settings_sha256",
                    "target_fields",
                    "verifier_version",
                    "oe_normalization_version",
                    "verification_report",
                ],
            )
            assert {record["column_name"] for record in binding_columns} == {
                "source_listing_id",
                "source_offer_locator_sha256",
                "document_sha256",
                "prepared_input_sha256",
                "model_settings_sha256",
                "target_fields",
                "verifier_version",
                "oe_normalization_version",
                "verification_report",
            }
            budget_key = await connection.fetch(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid=i.indrelid "
                "AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid='llm_provider_call_budget'::regclass "
                "AND i.indisprimary ORDER BY a.attname"
            )
            assert [record["attname"] for record in budget_key] == [
                "pricing_run_item_id",
                "purpose",
            ]
        finally:
            await connection.close()

        downgraded = _alembic(database, "downgrade", "20260802_0040")
        assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr

        back = _alembic(database, "current")
        assert "20260802_0040" in back.stdout

        reupgraded = _alembic(database, "upgrade", "head")
        assert reupgraded.returncode == 0, reupgraded.stdout + reupgraded.stderr
        rechecked = _alembic(database, "check")
        assert rechecked.returncode == 0, rechecked.stdout + rechecked.stderr
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
