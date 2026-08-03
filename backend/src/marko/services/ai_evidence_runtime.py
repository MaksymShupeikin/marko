"""Transactional request/reuse/persist orchestration for AI evidence.

This is the runtime path that joins retained captures, the strict extractor,
the paid provider boundary and the independent verifier.  It remains shadow
only: the returned preview is derived in memory and no pricing-eligibility or
market-observation authority column is mutated.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.ai_model_identity import validated_model_identifier
from marko.infrastructure.db.models import (
    AiEvidenceExtraction,
    AiEvidenceRequestClaim,
    AiEvidenceRequestEvent,
    MarketObservation,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    ScrapeTarget,
)
from marko.services.ai_cost_policy import (
    AiCostPolicyError,
    estimate_from_provider_payload,
    usage_from_provider_payload,
    usage_telemetry_payload,
)
from marko.services.ai_evidence_extraction import (
    AI_EVIDENCE_PROMPT_VERSION,
    AI_EVIDENCE_SCHEMA_VERSION,
    AiEvidenceBinding,
    AiEvidenceExtractionOutput,
    AiEvidenceExtractionResult,
    AiEvidenceOutcome,
    AiEvidenceProvider,
    AiEvidenceRuntimeConfig,
    EvidenceFieldName,
    ExtractionInput,
    build_extraction_input,
    extract_observation_evidence,
    resolve_ai_evidence_config,
)
from marko.services.ai_evidence_provider import (
    OpenAIResponsesEvidenceProvider,
    safety_identifier_for_workspace,
)
from marko.services.ai_evidence_verification import (
    AI_EVIDENCE_VERIFIER_VERSION,
    AiEvidenceVerificationReport,
    EvidenceFillProposal,
    ReportStatus,
    VerificationStatus,
    propose_evidence_fill,
    verify_ai_evidence,
)
from marko.services.llm_call_budget import evidence_extraction_budget
from marko.services.scraper_metrics import record_ai_evidence_outcome
from metis.pricing.types import ComparisonEvidence
from marko.services.offer_identity import OE_EXTRACTOR_VERSION


AI_EVIDENCE_EXTRACTOR_VERSION = "marko-ai-evidence-extractor-v1"
AI_EVIDENCE_PROVIDER = "openai_responses"


class AiEvidenceRuntimeError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class AiEvidenceRuntimeResult:
    row: AiEvidenceExtraction
    extraction: AiEvidenceExtractionResult | None
    verification: AiEvidenceVerificationReport | None
    preview: EvidenceFillProposal | None
    reused: bool = False


async def request_or_reuse_ai_evidence(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pricing_run_item_id: UUID,
    market_observation_id: UUID,
    settings: Any,
    target_fields: Sequence[EvidenceFieldName],
    provider: AiEvidenceProvider | None = None,
    comparison_evidence: ComparisonEvidence | None = None,
    our_values: Mapping[str, str | None] | None = None,
) -> AiEvidenceRuntimeResult:
    """Request one extraction or reuse the immutable completed result.

    A PostgreSQL transaction advisory lock serializes the exact request across
    processes.  The lock is released on commit/rollback and a restarted worker
    rechecks the append-only rows before making another paid call.  The durable
    call ledger remains the hard spend bound if a process dies after the
    provider accepted a request but before this transaction commits.
    """

    observation, capture, retained_payload = await _load_bound_evidence(
        session,
        workspace_id=workspace_id,
        pricing_run_item_id=pricing_run_item_id,
        market_observation_id=market_observation_id,
    )
    config = resolve_ai_evidence_config(settings)
    prepared = build_extraction_input(
        capture=capture,
        observation=observation,
        config=config,
        target_fields=target_fields,
    )
    input_hash = ai_evidence_runtime_input_hash(prepared.binding.as_dict())
    await _lock_exact_request(session, workspace_id=workspace_id, input_hash=input_hash)
    rows = await _matching_extractions(
        session,
        workspace_id=workspace_id,
        market_observation_id=market_observation_id,
        input_hash=input_hash,
    )
    cached = next((row for row in rows if row.status == "CACHED"), None)
    if cached is not None:
        source = await session.get(AiEvidenceExtraction, cached.cache_hit_extraction_id)
        if source is None:
            raise AiEvidenceRuntimeError(
                "AI_EVIDENCE_CACHE_SOURCE_MISSING",
                "cached extraction source no longer exists",
            )
        record_ai_evidence_outcome("cached")
        return _rehydrate_cached_result(
            row=cached,
            source=source,
            capture=capture,
            observation=observation,
            retained_payload=retained_payload,
            config=config,
            comparison_evidence=comparison_evidence,
            our_values=our_values,
        )
    completed = next((row for row in rows if row.status == "COMPLETED"), None)
    if completed is not None:
        cache_row = _cache_row(
            source=completed,
            attempt_no=max(row.attempt_no for row in rows) + 1,
        )
        session.add(cache_row)
        await session.flush()
        record_ai_evidence_outcome("cached")
        return _rehydrate_cached_result(
            row=cache_row,
            source=completed,
            capture=capture,
            observation=observation,
            retained_payload=retained_payload,
            config=config,
            comparison_evidence=comparison_evidence,
            our_values=our_values,
        )

    # Off/unconfigured paths never create a provider request event.  They are
    # cheap local terminal facts and may stay in the caller's transaction.
    if not config.enabled:
        extraction = await extract_observation_evidence(
            capture=capture,
            observation=observation,
            provider=provider,
            config=config,
            target_fields=target_fields,
        )
        return await _persist_runtime_result(
            session,
            workspace_id=workspace_id,
            pricing_run_item_id=pricing_run_item_id,
            observation=observation,
            capture=capture,
            retained_payload=retained_payload,
            prepared=prepared,
            input_hash=input_hash,
            attempt_no=max((row.attempt_no for row in rows), default=0) + 1,
            config=config,
            extraction=extraction,
            comparison_evidence=comparison_evidence,
            our_values=our_values,
            request_event_id=None,
            commit=False,
        )

    budget = evidence_extraction_budget(
        position_id=pricing_run_item_id,
        workspace_id=workspace_id,
        limit=config.max_calls_per_position,
    )
    requests = list(
        (
            await session.scalars(
                select(AiEvidenceRequestEvent)
                .where(
                    AiEvidenceRequestEvent.workspace_id == workspace_id,
                    AiEvidenceRequestEvent.market_observation_id
                    == market_observation_id,
                    AiEvidenceRequestEvent.input_hash == input_hash,
                )
                .order_by(AiEvidenceRequestEvent.attempt_no.asc())
            )
        ).all()
    )
    request_event = await _latest_incomplete_request(session, requests)
    recovery = request_event is not None
    if request_event is None:
        # The immutable request event and ownership claim are committed before
        # network I/O.  The provider then reserves one durable budget slot
        # immediately before *each* physical POST, including retries and crash
        # recovery.  There is deliberately no reusable "pre-reserved" flag:
        # replaying one would turn one counter increment into unbounded POSTs.
        attempt_no = (
            max(
                [row.attempt_no for row in rows]
                + [event.attempt_no for event in requests]
                + [0]
            )
            + 1
        )
        request_event = _request_event(
            workspace_id=workspace_id,
            pricing_run_item_id=pricing_run_item_id,
            observation=observation,
            capture=capture,
            prepared=prepared,
            input_hash=input_hash,
            attempt_no=attempt_no,
            config=config,
        )
        session.add(request_event)
        await session.flush()
    else:
        attempt_no = request_event.attempt_no

    active_claim = await _active_request_claim(session, request_event.id)
    if active_claim is not None:
        await session.commit()
        terminal = await _wait_for_request_terminal(
            session,
            request_event_id=request_event.id,
            timeout_seconds=min(
                5.0,
                max(0.25, float(getattr(settings, "pricing_llm_timeout_seconds", 60))),
            ),
        )
        if terminal is None:
            raise AiEvidenceRuntimeError(
                "AI_EVIDENCE_REQUEST_IN_PROGRESS",
                "another worker owns the active provider-request lease",
            )
        observation, capture, retained_payload = await _load_bound_evidence(
            session,
            workspace_id=workspace_id,
            pricing_run_item_id=pricing_run_item_id,
            market_observation_id=market_observation_id,
        )
        await _lock_exact_request(
            session, workspace_id=workspace_id, input_hash=input_hash
        )
        fresh_rows = await _matching_extractions(
            session,
            workspace_id=workspace_id,
            market_observation_id=market_observation_id,
            input_hash=input_hash,
        )
        if terminal.status != "COMPLETED":
            return _reuse_terminal_result(terminal)
        cache_row = _cache_row(
            source=terminal,
            attempt_no=max(row.attempt_no for row in fresh_rows) + 1,
        )
        session.add(cache_row)
        await session.commit()
        record_ai_evidence_outcome("cached")
        return _rehydrate_cached_result(
            row=cache_row,
            source=terminal,
            capture=capture,
            observation=observation,
            retained_payload=retained_payload,
            config=config,
            comparison_evidence=comparison_evidence,
            our_values=our_values,
        )

    lease_seconds = min(
        900.0,
        max(30.0, float(getattr(settings, "pricing_llm_timeout_seconds", 60)) * 2 + 10),
    )
    session.add(
        AiEvidenceRequestClaim(
            request_event_id=request_event.id,
            claim_token=uuid4(),
            recovery=recovery,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds),
        )
    )
    # Releases the advisory lock and every row snapshot before network I/O.
    await session.commit()

    effective_provider = provider or OpenAIResponsesEvidenceProvider(
        settings,
        budget=budget,
        safety_identifier=safety_identifier_for_workspace(workspace_id),
    )
    extraction = await extract_observation_evidence(
        capture=capture,
        observation=observation,
        provider=effective_provider,
        config=config,
        target_fields=target_fields,
        idempotency_key=request_event.request_key,
    )
    await _lock_exact_request(session, workspace_id=workspace_id, input_hash=input_hash)
    terminal = await session.scalar(
        select(AiEvidenceExtraction).where(
            AiEvidenceExtraction.request_event_id == request_event.id
        )
    )
    if terminal is not None:
        if terminal.status != "COMPLETED":
            return _reuse_terminal_result(terminal)
        return _rehydrate_cached_result(
            row=terminal,
            source=terminal,
            capture=capture,
            observation=observation,
            retained_payload=retained_payload,
            config=config,
            comparison_evidence=comparison_evidence,
            our_values=our_values,
        )
    return await _persist_runtime_result(
        session,
        workspace_id=workspace_id,
        pricing_run_item_id=pricing_run_item_id,
        observation=observation,
        capture=capture,
        retained_payload=retained_payload,
        prepared=prepared,
        input_hash=input_hash,
        attempt_no=attempt_no,
        config=config,
        extraction=extraction,
        comparison_evidence=comparison_evidence,
        our_values=our_values,
        request_event_id=request_event.id,
        commit=True,
    )


async def _matching_extractions(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    market_observation_id: UUID,
    input_hash: str,
) -> list[AiEvidenceExtraction]:
    return list(
        (
            await session.scalars(
                select(AiEvidenceExtraction)
                .where(
                    AiEvidenceExtraction.workspace_id == workspace_id,
                    AiEvidenceExtraction.market_observation_id == market_observation_id,
                    AiEvidenceExtraction.input_hash == input_hash,
                )
                .order_by(AiEvidenceExtraction.attempt_no.asc())
            )
        ).all()
    )


async def _latest_incomplete_request(
    session: AsyncSession,
    requests: Sequence[AiEvidenceRequestEvent],
) -> AiEvidenceRequestEvent | None:
    if not requests:
        return None
    terminal_ids = set(
        (
            await session.scalars(
                select(AiEvidenceExtraction.request_event_id).where(
                    AiEvidenceExtraction.request_event_id.in_(
                        [event.id for event in requests]
                    )
                )
            )
        ).all()
    )
    return next(
        (event for event in reversed(requests) if event.id not in terminal_ids),
        None,
    )


async def _active_request_claim(
    session: AsyncSession, request_event_id: UUID
) -> AiEvidenceRequestClaim | None:
    claim = await session.scalar(
        select(AiEvidenceRequestClaim)
        .where(AiEvidenceRequestClaim.request_event_id == request_event_id)
        .order_by(
            AiEvidenceRequestClaim.claimed_at.desc(),
            AiEvidenceRequestClaim.id.desc(),
        )
        .limit(1)
    )
    if claim is None or claim.lease_expires_at <= datetime.now(UTC):
        return None
    return claim


async def _wait_for_request_terminal(
    session: AsyncSession,
    *,
    request_event_id: UUID,
    timeout_seconds: float,
) -> AiEvidenceExtraction | None:
    deadline = monotonic() + timeout_seconds
    while True:
        await session.rollback()
        row = await session.scalar(
            select(AiEvidenceExtraction).where(
                AiEvidenceExtraction.request_event_id == request_event_id
            )
        )
        if row is not None:
            return row
        if monotonic() >= deadline:
            return None
        await asyncio.sleep(0.05)


def _request_event(
    *,
    workspace_id: UUID,
    pricing_run_item_id: UUID,
    observation: MarketObservation,
    capture: RawMarketCapture,
    prepared: ExtractionInput,
    input_hash: str,
    attempt_no: int,
    config: AiEvidenceRuntimeConfig,
) -> AiEvidenceRequestEvent:
    binding = prepared.binding
    request_key = AiEvidenceExtraction.build_request_key(
        market_observation_id=observation.id,
        input_hash=input_hash,
        attempt_no=attempt_no,
    )
    return AiEvidenceRequestEvent(
        workspace_id=workspace_id,
        pricing_run_item_id=pricing_run_item_id,
        market_observation_id=observation.id,
        raw_capture_id=capture.id,
        request_key=request_key,
        input_hash=input_hash,
        attempt_no=attempt_no,
        source_listing_id=binding.source_listing_id,
        capture_sha256=binding.capture_content_sha256,
        candidate_snapshot_sha256=binding.candidate_snapshot_sha256,
        source_offer_locator_sha256=binding.source_offer_locator_sha256,
        document_sha256=binding.document_sha256,
        prepared_input_sha256=binding.input_sha256,
        model_settings_sha256=binding.model_settings_sha256,
        prompt_version=binding.prompt_version,
        schema_version=binding.schema_version,
        extractor_version=AI_EVIDENCE_EXTRACTOR_VERSION,
        verifier_version=AI_EVIDENCE_VERIFIER_VERSION,
        oe_normalization_version=OE_EXTRACTOR_VERSION,
        provider=AI_EVIDENCE_PROVIDER,
        model_id=binding.model,
        reasoning_effort=binding.reasoning_effort,
        max_output_tokens=binding.max_output_tokens,
        max_input_chars=binding.max_input_chars,
        target_fields=[field.value for field in _target_fields(prepared)],
        input_snapshot=prepared.snapshot,
    )


def _target_fields(prepared: ExtractionInput) -> tuple[EvidenceFieldName, ...]:
    return tuple(
        EvidenceFieldName(value) for value in prepared.snapshot.get("target_fields", [])
    )


async def _persist_runtime_result(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pricing_run_item_id: UUID,
    observation: MarketObservation,
    capture: RawMarketCapture,
    retained_payload: Mapping[str, Any],
    prepared: ExtractionInput,
    input_hash: str,
    attempt_no: int,
    config: AiEvidenceRuntimeConfig,
    extraction: AiEvidenceExtractionResult,
    comparison_evidence: ComparisonEvidence | None,
    our_values: Mapping[str, str | None] | None,
    request_event_id: UUID | None,
    commit: bool,
) -> AiEvidenceRuntimeResult:
    verification = verify_ai_evidence(
        extraction,
        capture=capture,
        observation=observation,
        config=config,
        retained_payload=retained_payload,
    )
    preview = (
        propose_evidence_fill(
            comparison_evidence,
            verification,
            our_values=our_values,
        )
        if comparison_evidence is not None
        else None
    )
    row = _result_row(
        workspace_id=workspace_id,
        pricing_run_item_id=pricing_run_item_id,
        observation=observation,
        capture=capture,
        prepared_input=prepared.snapshot,
        prepared_binding=prepared.binding,
        input_hash=input_hash,
        attempt_no=attempt_no,
        config=config,
        extraction=extraction,
        verification=verification,
        request_event_id=request_event_id,
    )
    session.add(row)
    await session.flush()
    if commit:
        await session.commit()
    _record_runtime_telemetry(
        row=row,
        extraction=extraction,
        verification=verification,
    )
    return AiEvidenceRuntimeResult(
        row=row,
        extraction=extraction,
        verification=verification,
        preview=preview,
    )


async def _load_bound_evidence(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pricing_run_item_id: UUID,
    market_observation_id: UUID,
) -> tuple[MarketObservation, RawMarketCapture, Mapping[str, Any]]:
    record = (
        await session.execute(
            select(MarketObservation, RawMarketCapture, PricingRunItem)
            .join(
                RawMarketCapture,
                RawMarketCapture.id == MarketObservation.raw_capture_id,
            )
            .join(
                PricingRunItem,
                PricingRunItem.id == MarketObservation.pricing_run_item_id,
            )
            .join(PricingRun, PricingRun.id == PricingRunItem.pricing_run_id)
            .where(
                MarketObservation.id == market_observation_id,
                MarketObservation.pricing_run_item_id == pricing_run_item_id,
                RawMarketCapture.pricing_run_item_id == pricing_run_item_id,
                PricingRun.workspace_id == workspace_id,
            )
        )
    ).one_or_none()
    if record is None:
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_BOUND_INPUT_NOT_FOUND",
            "observation/capture/position does not exist in this workspace",
        )
    observation, capture, run_item = record
    retained_payload: Any = capture.payload
    if capture.scrape_target_id is not None:
        target = await session.scalar(
            select(ScrapeTarget).where(
                ScrapeTarget.id == capture.scrape_target_id,
                ScrapeTarget.pricing_run_id == run_item.pricing_run_id,
            )
        )
        if target is None or not isinstance(target.payload, Mapping):
            raise AiEvidenceRuntimeError(
                "AI_EVIDENCE_RETAINED_TARGET_MISSING",
                "capture references no retained scrape-target payload",
            )
        target_hash = _canonical_json_sha256(target.payload)
        if (
            target_hash is None
            or target_hash != target.content_sha256
            or target_hash != capture.content_sha256
        ):
            raise AiEvidenceRuntimeError(
                "AI_EVIDENCE_RETAINED_TARGET_HASH_MISMATCH",
                "retained scrape-target bytes do not match the capture binding",
            )
        retained_payload = target.payload
    if not isinstance(retained_payload, Mapping):
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_RETAINED_PAYLOAD_INVALID",
            "retained capture payload is not a mapping",
        )
    return observation, capture, retained_payload


def _canonical_json_sha256(payload: Any) -> str | None:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


async def _lock_exact_request(
    session: AsyncSession, *, workspace_id: UUID, input_hash: str
) -> None:
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    raw = int.from_bytes(
        hashlib.sha256((str(workspace_id) + ":" + input_hash).encode()).digest()[:8],
        "big",
        signed=False,
    )
    key = raw if raw < 2**63 else raw - 2**64
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def ai_evidence_runtime_input_hash(binding: Mapping[str, Any]) -> str:
    """Hash every evidence and interpretation fact used by a provider request."""

    payload = {
        "kind": "marko_ai_evidence_runtime_input",
        "prepared_input_sha256": binding["input_sha256"],
        "capture_sha256": binding["capture_content_sha256"],
        "candidate_snapshot_sha256": binding["candidate_snapshot_sha256"],
        "source_offer_locator_sha256": binding["source_offer_locator_sha256"],
        "document_sha256": binding["document_sha256"],
        "prompt_version": binding["prompt_version"],
        "schema_version": binding["schema_version"],
        "extractor_version": AI_EVIDENCE_EXTRACTOR_VERSION,
        "provider": AI_EVIDENCE_PROVIDER,
        "model": binding["model"],
        "reasoning_effort": binding["reasoning_effort"],
        "model_settings_sha256": binding["model_settings_sha256"],
        "max_output_tokens": binding["max_output_tokens"],
        "max_input_chars": binding["max_input_chars"],
        "verifier_version": AI_EVIDENCE_VERIFIER_VERSION,
        "oe_normalization_version": OE_EXTRACTOR_VERSION,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _result_row(
    *,
    workspace_id: UUID,
    pricing_run_item_id: UUID,
    observation: MarketObservation,
    capture: RawMarketCapture,
    prepared_input: dict[str, Any],
    prepared_binding: AiEvidenceBinding,
    input_hash: str,
    attempt_no: int,
    config: AiEvidenceRuntimeConfig,
    extraction: AiEvidenceExtractionResult,
    verification: AiEvidenceVerificationReport,
    request_event_id: UUID | None,
) -> AiEvidenceExtraction:
    status = _persistence_status(config=config, extraction=extraction)
    request_key = AiEvidenceExtraction.build_request_key(
        market_observation_id=observation.id,
        input_hash=input_hash,
        attempt_no=attempt_no,
    )
    verification_status, verified_count, rejected_count = _verification_summary(
        verification
    )
    raw_output = (
        extraction.output.model_dump(mode="json")
        if extraction.output is not None and status not in {"SKIPPED", "UNCONFIGURED"}
        else None
    )
    findings = _public_findings(extraction, verification) if raw_output else []
    no_request = status in {"SKIPPED", "UNCONFIGURED"}
    error_code = extraction.error_code
    if status == "FAILED" and not error_code:
        error_code = "AI_EVIDENCE_FAILED"
    return AiEvidenceExtraction(
        workspace_id=workspace_id,
        pricing_run_item_id=pricing_run_item_id,
        market_observation_id=observation.id,
        raw_capture_id=capture.id,
        request_event_id=request_event_id,
        request_key=request_key,
        input_hash=input_hash,
        candidate_snapshot_hash=prepared_binding.candidate_snapshot_sha256,
        capture_sha256=capture.content_sha256,
        source_listing_id=prepared_binding.source_listing_id,
        source_offer_locator_sha256=prepared_binding.source_offer_locator_sha256,
        document_sha256=prepared_binding.document_sha256,
        prepared_input_sha256=prepared_binding.input_sha256,
        model_settings_sha256=prepared_binding.model_settings_sha256,
        attempt_no=attempt_no,
        prompt_version=AI_EVIDENCE_PROMPT_VERSION,
        schema_version=AI_EVIDENCE_SCHEMA_VERSION,
        extractor_version=AI_EVIDENCE_EXTRACTOR_VERSION,
        provider=AI_EVIDENCE_PROVIDER,
        model_id=config.model,
        reasoning_effort=config.reasoning_effort,
        max_output_tokens=config.max_output_tokens,
        max_input_chars=config.max_input_chars,
        target_fields=[field.value for field in extraction.target_fields],
        verifier_version=AI_EVIDENCE_VERIFIER_VERSION,
        oe_normalization_version=OE_EXTRACTOR_VERSION,
        mode=config.mode.value,
        outcome=extraction.outcome.value,
        status=status,
        raw_output=raw_output,
        findings=findings,
        verification_status=verification_status,
        verification_reasons=_verification_reasons(verification),
        verification_report=verification.as_dict(),
        verified_field_count=verified_count,
        rejected_field_count=rejected_count,
        input_snapshot=prepared_input,
        cache_hit_extraction_id=None,
        provider_response_id=None if no_request else extraction.response_id,
        provider_model=None if no_request else extraction.model,
        usage={} if no_request else _persisted_usage(extraction, config=config),
        latency_ms=0 if no_request else int(extraction.latency_ms or 0),
        error_code=error_code,
        error_detail=extraction.error_detail,
    )


def _persistence_status(
    *, config: AiEvidenceRuntimeConfig, extraction: AiEvidenceExtractionResult
) -> str:
    if config.mode.value == "off":
        return "SKIPPED"
    if extraction.outcome is AiEvidenceOutcome.UNCONFIGURED:
        return "UNCONFIGURED"
    if extraction.outcome is AiEvidenceOutcome.EXTRACTED:
        return "COMPLETED"
    if extraction.outcome in {
        AiEvidenceOutcome.NO_TARGET_FIELDS,
        AiEvidenceOutcome.NOT_ELIGIBLE,
    }:
        return "SKIPPED"
    return "FAILED"


def _verification_summary(
    report: AiEvidenceVerificationReport,
) -> tuple[str, int, int]:
    if report.status is ReportStatus.NO_OUTPUT:
        return "NOT_RUN", 0, 0
    if not report.bound:
        return "REJECTED", 0, max(1, len(report.binding_failures))
    verified = sum(item.status is VerificationStatus.VERIFIED for item in report.fields)
    rejected = sum(
        item.status
        in {
            VerificationStatus.REJECTED,
            VerificationStatus.CONFLICT,
            VerificationStatus.AMBIGUOUS,
        }
        for item in report.fields
    )
    if rejected == 0:
        return "VERIFIED", verified, 0
    if verified:
        return "PARTIALLY_VERIFIED", verified, rejected
    return "REJECTED", 0, rejected


def _verification_reasons(report: AiEvidenceVerificationReport) -> dict[str, Any]:
    reasons: dict[str, Any] = {
        "report_status": report.status.value,
        "binding_failures": [code.value for code in report.binding_failures],
    }
    for item in report.fields:
        reasons[item.field_name.value] = {
            "status": item.status.value,
            "reason_codes": list(item.reason_codes),
            "citations": [citation.as_dict() for citation in item.citations],
        }
    return reasons


def _persisted_usage(
    extraction: AiEvidenceExtractionResult, *, config: AiEvidenceRuntimeConfig
) -> dict[str, Any]:
    """Keep provider counters and bind every estimate to its dated rate card."""

    raw = dict(extraction.usage)
    if not raw:
        return {}
    try:
        estimate = estimate_from_provider_payload(raw, model_id=config.model)
        normalized = usage_telemetry_payload(estimate.usage, estimate)
    except (AiCostPolicyError, TypeError, ValueError):
        # Usage quality cannot invalidate already verified evidence.  Preserve
        # the provider counters and make the missing estimate explicit.
        return {**raw, "spend_estimate_error": "AI_USAGE_NOT_ESTIMABLE"}
    return {**raw, **normalized}


def _record_runtime_telemetry(
    *,
    row: AiEvidenceExtraction,
    extraction: AiEvidenceExtractionResult,
    verification: AiEvidenceVerificationReport,
) -> None:
    usage = None
    if row.usage:
        try:
            usage = usage_from_provider_payload(row.usage)
        except (AiCostPolicyError, TypeError, ValueError):
            usage = None
    estimate = (
        row.usage.get("spend_estimate") if isinstance(row.usage, Mapping) else None
    )
    rate_version = (
        str(estimate.get("rate_version"))
        if isinstance(estimate, Mapping) and estimate.get("rate_version")
        else None
    )
    if extraction.provider_calls:
        record_ai_evidence_outcome("requested")
    if row.status == "COMPLETED":
        outcome = "completed"
    elif row.status == "UNCONFIGURED":
        outcome = "unconfigured"
    elif row.status == "SKIPPED":
        outcome = "skipped"
    elif extraction.error_code == "LLM_PROVIDER_CALL_BUDGET_EXHAUSTED":
        outcome = "budget_exhausted"
    elif extraction.outcome is AiEvidenceOutcome.SCHEMA_INVALID:
        outcome = "schema_invalid"
    else:
        outcome = "failed"
    record_ai_evidence_outcome(
        outcome,
        latency_ms=extraction.latency_ms,
        usage=usage,
        rate_version=rate_version,
        provider_attempts=extraction.provider_calls,
    )
    if any(
        field.status
        in {
            VerificationStatus.REJECTED,
            VerificationStatus.AMBIGUOUS,
        }
        for field in verification.fields
    ):
        record_ai_evidence_outcome("citation_rejected")
    if any(
        field.status is VerificationStatus.CONFLICT for field in verification.fields
    ):
        record_ai_evidence_outcome("conflict")


def _public_findings(
    extraction: AiEvidenceExtractionResult,
    report: AiEvidenceVerificationReport,
) -> list[dict[str, Any]]:
    output = extraction.output
    if output is None:
        return []
    verified_by_name = {item.field_name: item for item in report.fields}
    rows: list[dict[str, Any]] = []
    for finding in output.findings:
        verified = verified_by_name.get(finding.field_name)
        citation = finding.candidates[0] if finding.candidates else None
        canonical = (
            verified.canonical_values[0]
            if verified and verified.canonical_values
            else None
        )
        rows.append(
            {
                "field": finding.field_name.value,
                "state": finding.state.value,
                "value": canonical or (citation.raw_value if citation else None),
                "excerpt": citation.source_excerpt if citation else None,
                "source_path": citation.source_path if citation else None,
                "confidence": str(citation.confidence) if citation else None,
                "verified": bool(
                    verified and verified.status is VerificationStatus.VERIFIED
                ),
                "verification_reason": (
                    ",".join(verified.reason_codes)
                    if verified and verified.reason_codes
                    else (verified.status.value if verified else "NOT_RUN")
                ),
            }
        )
    return rows


def _cache_row(
    *, source: AiEvidenceExtraction, attempt_no: int
) -> AiEvidenceExtraction:
    if source.status != "COMPLETED" or source.raw_output is None:
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_CACHE_SOURCE_INVALID",
            "only a completed strict extraction may be cached",
        )
    provider_model = validated_model_identifier(source.provider_model)
    if provider_model is None or provider_model != source.model_id:
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_CACHE_MODEL_REVISION_INVALID",
            "cache source model revision is missing or differs from its pinned model",
        )
    return AiEvidenceExtraction(
        workspace_id=source.workspace_id,
        pricing_run_item_id=source.pricing_run_item_id,
        market_observation_id=source.market_observation_id,
        raw_capture_id=source.raw_capture_id,
        request_key=AiEvidenceExtraction.build_request_key(
            market_observation_id=source.market_observation_id,
            input_hash=source.input_hash,
            attempt_no=attempt_no,
        ),
        input_hash=source.input_hash,
        candidate_snapshot_hash=source.candidate_snapshot_hash,
        capture_sha256=source.capture_sha256,
        source_listing_id=source.source_listing_id,
        source_offer_locator_sha256=source.source_offer_locator_sha256,
        document_sha256=source.document_sha256,
        prepared_input_sha256=source.prepared_input_sha256,
        model_settings_sha256=source.model_settings_sha256,
        attempt_no=attempt_no,
        prompt_version=source.prompt_version,
        schema_version=source.schema_version,
        extractor_version=source.extractor_version,
        provider=source.provider,
        model_id=source.model_id,
        reasoning_effort=source.reasoning_effort,
        max_output_tokens=source.max_output_tokens,
        max_input_chars=source.max_input_chars,
        target_fields=source.target_fields,
        verifier_version=source.verifier_version,
        oe_normalization_version=source.oe_normalization_version,
        mode=source.mode,
        outcome=source.outcome,
        status="CACHED",
        raw_output=source.raw_output,
        findings=source.findings,
        verification_status=source.verification_status,
        verification_reasons=source.verification_reasons,
        verification_report=source.verification_report,
        verified_field_count=source.verified_field_count,
        rejected_field_count=source.rejected_field_count,
        input_snapshot=source.input_snapshot,
        cache_hit_extraction_id=source.id,
        provider_response_id=None,
        provider_model=provider_model,
        usage={},
        latency_ms=0,
        error_code=None,
        error_detail=None,
    )


def _rehydrate_cached_result(
    *,
    row: AiEvidenceExtraction,
    source: AiEvidenceExtraction,
    capture: RawMarketCapture,
    observation: MarketObservation,
    retained_payload: Mapping[str, Any],
    config: AiEvidenceRuntimeConfig,
    comparison_evidence: ComparisonEvidence | None,
    our_values: Mapping[str, str | None] | None,
) -> AiEvidenceRuntimeResult:
    """Rebuild and reverify a cached source; cached semantics equal a fresh run."""

    provider_model = validated_model_identifier(source.provider_model)
    if provider_model is None or provider_model != source.model_id:
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_CACHE_MODEL_REVISION_INVALID",
            "cache source model revision is missing or differs from its pinned model",
        )

    if source.status != "COMPLETED" or source.raw_output is None:
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_CACHE_SOURCE_INVALID",
            "cached extraction does not reference a completed strict output",
        )
    if (
        source.verifier_version != AI_EVIDENCE_VERIFIER_VERSION
        or source.oe_normalization_version != OE_EXTRACTOR_VERSION
    ):
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_CACHE_VERSION_STALE",
            "cached extraction was verified by a different deterministic version",
        )
    try:
        target_fields = tuple(
            EvidenceFieldName(value) for value in source.target_fields
        )
        output = AiEvidenceExtractionOutput.model_validate(source.raw_output)
    except (TypeError, ValueError) as exc:
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_CACHE_SCHEMA_INVALID",
            "cached extraction no longer satisfies the strict evidence schema",
        ) from exc
    expected = build_extraction_input(
        capture=capture,
        observation=observation,
        config=config,
        target_fields=target_fields,
    )
    binding = _binding_from_row(source)
    if binding != expected.binding:
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_CACHE_BINDING_INVALID",
            "cached extraction binding does not match retained evidence",
        )
    if _canonical_sha256(source.input_snapshot) != source.prepared_input_sha256:
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_CACHE_INPUT_TAMPERED",
            "cached provider input digest does not match its persisted snapshot",
        )
    if ai_evidence_runtime_input_hash(binding.as_dict()) != source.input_hash:
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_CACHE_IDENTITY_INVALID",
            "cached extraction identity does not match its complete binding",
        )
    extraction = AiEvidenceExtractionResult(
        outcome=AiEvidenceOutcome.EXTRACTED,
        target_fields=target_fields,
        binding=binding,
        output=output,
        provider_calls=0,
        response_id=source.provider_response_id,
        model=provider_model,
        usage=dict(source.usage),
        latency_ms=0,
    )
    verification = verify_ai_evidence(
        extraction,
        capture=capture,
        observation=observation,
        config=config,
        retained_payload=retained_payload,
    )
    if not verification.bound:
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_CACHE_REVERIFICATION_FAILED",
            "cached extraction failed deterministic reverification",
        )
    preview = (
        propose_evidence_fill(
            comparison_evidence,
            verification,
            our_values=our_values,
        )
        if comparison_evidence is not None
        else None
    )
    return AiEvidenceRuntimeResult(
        row=row,
        extraction=extraction,
        verification=verification,
        preview=preview,
        reused=True,
    )


def _reuse_terminal_result(source: AiEvidenceExtraction) -> AiEvidenceRuntimeResult:
    """Return an already persisted failure without inventing a cache success."""

    if source.status == "COMPLETED":
        raise AiEvidenceRuntimeError(
            "AI_EVIDENCE_TERMINAL_REUSE_INVALID",
            "completed terminal rows must be reverified before reuse",
        )
    return AiEvidenceRuntimeResult(
        row=source,
        extraction=None,
        verification=None,
        preview=None,
        reused=True,
    )


def _binding_from_row(row: AiEvidenceExtraction) -> AiEvidenceBinding:
    return AiEvidenceBinding(
        raw_capture_id=str(row.raw_capture_id),
        capture_content_sha256=row.capture_sha256,
        market_observation_id=str(row.market_observation_id),
        source_listing_id=row.source_listing_id,
        candidate_snapshot_sha256=row.candidate_snapshot_hash,
        source_offer_locator_sha256=row.source_offer_locator_sha256,
        document_sha256=row.document_sha256,
        input_sha256=row.prepared_input_sha256,
        prompt_version=row.prompt_version,
        schema_version=row.schema_version,
        model=row.model_id,
        reasoning_effort=row.reasoning_effort,
        max_output_tokens=row.max_output_tokens,
        max_input_chars=row.max_input_chars,
        model_settings_sha256=row.model_settings_sha256,
    )


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "AI_EVIDENCE_EXTRACTOR_VERSION",
    "AiEvidenceRuntimeError",
    "AiEvidenceRuntimeResult",
    "ai_evidence_runtime_input_hash",
    "request_or_reuse_ai_evidence",
]
