"""Persistence and orchestration for distributed fitment intelligence.

The service is intentionally evidence-in/evaluation-out.  It does not crawl
third-party catalogues and it has no code path that publishes a marketplace
price.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
import hashlib
import json
import unicodedata
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from celery import Celery
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    CatalogItem,
    FitmentAnalysis,
    FitmentAuditEvent,
    FitmentCandidateAssessment,
    FitmentCrossReference,
    FitmentEvidenceClaim,
    FitmentFeedbackEvent,
    FitmentHumanReview,
    FitmentMarketRecommendation,
    FitmentRecommendationReview,
    FitmentSource,
    FitmentSourceCapability,
    FitmentSourceDocument,
    FitmentSourceReliabilitySnapshot,
    MarketObservation,
    MarketplaceStore,
    ObservationTierClassification,
    PricingRun,
    ScrapeDispatchOutbox,
    SellerRelationRecord,
    StoreKind,
    WorkspaceStore,
)
from metis.fitment import (
    FITMENT_CONTRACT_VERSION,
    FITMENT_SCORING_VERSION,
    Availability,
    CommercialContext,
    Condition,
    EvidenceClaim,
    EvidencePolarity,
    FitmentFeature,
    PartIdentity,
    PriceUnitStatus,
    SellerRelation,
    SourceTier,
    StatementStatus,
    assess_compatibility,
    assess_price_comparability,
    normalize_price_unit,
    normalize_part_number,
    posterior_source_reliability,
)
from metis.pricing.types import ProductTier

from marko.services.scraper_outbox import enqueue_dispatch, publish_dispatch


FITMENT_SOURCE_POLICY_VERSION = "fitment-source-policy-v1"
FITMENT_CROSS_METHOD_VERSION = "fitment-cross-human-v1"
FITMENT_ANALYSIS_TASK_NAME = "marko.worker.process_fitment_analysis"
FITMENT_ANALYSIS_LEASE_SECONDS = 300
_ALLOWED_UNREGISTERED_SOURCE_TYPES = frozenset(
    {"prom", "prom_public", "persisted_replay"}
)
_SOURCE_RELIABILITY_BOUNDS: Mapping[SourceTier, tuple[Decimal, Decimal]] = {
    SourceTier.A: (Decimal("0.95"), Decimal("1.00")),
    SourceTier.B: (Decimal("0.75"), Decimal("0.90")),
    SourceTier.C: (Decimal("0.55"), Decimal("0.75")),
    SourceTier.D: (Decimal("0.30"), Decimal("0.55")),
    SourceTier.E: (Decimal("0.10"), Decimal("0.35")),
}


class FitmentIntelligenceError(RuntimeError):
    pass


class FitmentNotFoundError(LookupError):
    pass


class FitmentIdempotencyConflict(FitmentIntelligenceError):
    pass


class FitmentSourceBlocked(FitmentIntelligenceError):
    pass


@dataclass(frozen=True, slots=True)
class SubmittedEvidence:
    claim: EvidenceClaim
    source_document_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CandidateAnalysisSpec:
    market_observation_id: UUID
    identity: PartIdentity
    commercial_context: CommercialContext
    evidence: tuple[SubmittedEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisSpec:
    target_identity: PartIdentity
    target_commercial_context: CommercialContext
    candidates: tuple[CandidateAnalysisSpec, ...]
    source_policy_snapshot: Mapping[str, Any]


async def _lock_analysis_idempotency_scope(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    idempotency_key: str,
) -> None:
    """Serialize concurrent admission for one workspace/idempotency key.

    A row-level lock cannot protect the first insert because no row exists yet.
    PostgreSQL's transaction advisory lock closes that race; the unique
    constraint remains the final invariant.
    """

    digest = hashlib.blake2b(
        workspace_id.bytes + idempotency_key.encode("utf-8"),
        digest_size=8,
        person=b"fitment",
    ).digest()
    lock_key = int.from_bytes(digest, byteorder="big", signed=True)
    await session.execute(select(func.pg_advisory_xact_lock(lock_key)))


async def _lock_source_reliability_scope(
    session: AsyncSession,
    *,
    source_id: UUID,
    claim_type: str,
) -> None:
    """Serialize Beta-counter updates, including the first snapshot insert."""

    digest = hashlib.blake2b(
        source_id.bytes + claim_type.encode("utf-8"),
        digest_size=8,
        person=b"fit-beta",
    ).digest()
    lock_key = int.from_bytes(digest, byteorder="big", signed=True)
    await session.execute(select(func.pg_advisory_xact_lock(lock_key)))


async def register_fitment_source(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    source_key: str,
    source_type: str,
    source_tier: SourceTier,
    base_reliability: Decimal,
    domain: str,
    access_method: str,
    access_status: str,
    access_reference: str,
    robots_checked: bool,
    terms_checked: bool,
    rate_limit: str,
    cache_policy: str,
    policy_version: str,
    reviewed_at: datetime,
    capabilities: Sequence[Mapping[str, Any]] = (),
) -> FitmentSource:
    if access_status not in {
        "PERMITTED",
        "OWNER_RISK_ACCEPTED",
        "NOT_PERMITTED",
        "UNKNOWN",
    }:
        raise FitmentIntelligenceError("invalid source access status")
    reliability_min, reliability_max = _SOURCE_RELIABILITY_BOUNDS[source_tier]
    if not reliability_min <= base_reliability <= reliability_max:
        raise FitmentIntelligenceError(
            f"tier {source_tier.value} reliability must be in "
            f"[{reliability_min}, {reliability_max}]"
        )
    normalized_key = source_key.strip().casefold()
    normalized_domain = _canonical_domain(domain)
    normalized_reference = access_reference.strip()
    normalized_type = source_type.strip()
    normalized_access_method = access_method.strip()
    normalized_rate_limit = rate_limit.strip()
    normalized_cache_policy = cache_policy.strip()
    normalized_policy_version = policy_version.strip()
    if (
        not normalized_key
        or not normalized_type
        or not normalized_domain
        or not normalized_access_method
        or not normalized_rate_limit
        or not normalized_cache_policy
        or not normalized_policy_version
    ):
        raise FitmentIntelligenceError(
            "source key, type, domain, access method and policy version are required"
        )
    if access_status in {"PERMITTED", "OWNER_RISK_ACCEPTED"}:
        if not normalized_reference:
            raise FitmentIntelligenceError(
                "approved source access requires an auditable access reference"
            )
        if not robots_checked or not terms_checked:
            raise FitmentIntelligenceError(
                "approved source access requires completed robots and terms review"
            )
    existing = await session.scalar(
        select(FitmentSource).where(
            FitmentSource.workspace_id == workspace_id,
            FitmentSource.source_key == normalized_key,
            FitmentSource.policy_version == normalized_policy_version,
        )
    )
    if existing is not None:
        expected = (
            normalized_type,
            source_tier.value,
            base_reliability,
            normalized_domain,
            normalized_access_method,
            access_status,
            normalized_reference,
            robots_checked,
            terms_checked,
            normalized_rate_limit,
            normalized_cache_policy,
        )
        actual = (
            existing.source_type,
            existing.source_tier,
            existing.base_reliability,
            existing.domain.casefold(),
            existing.access_method,
            existing.access_status,
            existing.access_reference,
            existing.robots_checked,
            existing.terms_checked,
            existing.rate_limit,
            existing.cache_policy,
        )
        if actual != expected:
            raise FitmentIdempotencyConflict(
                "source policy version already exists with different content"
            )
        await _ensure_source_capabilities(
            session,
            source=existing,
            capabilities=capabilities,
            policy_version=normalized_policy_version,
        )
        await session.commit()
        return existing
    record = FitmentSource(
        workspace_id=workspace_id,
        source_key=normalized_key,
        source_type=normalized_type,
        source_tier=source_tier.value,
        base_reliability=base_reliability,
        domain=normalized_domain,
        access_method=normalized_access_method,
        access_status=access_status,
        access_reference=normalized_reference,
        robots_checked=robots_checked,
        terms_checked=terms_checked,
        rate_limit=normalized_rate_limit,
        cache_policy=normalized_cache_policy,
        policy_version=normalized_policy_version,
        reviewed_at=reviewed_at,
    )
    session.add(record)
    await session.flush()
    await _ensure_source_capabilities(
        session,
        source=record,
        capabilities=capabilities,
        policy_version=normalized_policy_version,
    )
    session.add(
        _audit_event(
            workspace_id=workspace_id,
            event_type="fitment_source_registered",
            entity_type="fitment_source",
            entity_id=str(record.id),
            actor_user_id=actor_user_id,
            payload={
                "source_key": record.source_key,
                "policy_version": record.policy_version,
                "access_status": record.access_status,
                "access_reference": record.access_reference,
                "capabilities": [
                    str(item.get("capability")) for item in capabilities
                ],
            },
        )
    )
    await session.commit()
    return record


async def _ensure_source_capabilities(
    session: AsyncSession,
    *,
    source: FitmentSource,
    capabilities: Sequence[Mapping[str, Any]],
    policy_version: str,
) -> None:
    allowed = {
        "search_by_article",
        "search_by_oe",
        "search_fitment",
        "fetch_document",
    }
    seen: set[str] = set()
    for raw in capabilities:
        capability = str(raw.get("capability") or "").strip()
        if capability not in allowed:
            raise FitmentIntelligenceError(f"invalid source capability: {capability}")
        if capability in seen:
            raise FitmentIntelligenceError("duplicate source capability")
        seen.add(capability)
        existing = await session.scalar(
            select(FitmentSourceCapability).where(
                FitmentSourceCapability.source_id == source.id,
                FitmentSourceCapability.capability == capability,
                FitmentSourceCapability.policy_version == policy_version,
            )
        )
        normalized = {
            "enabled": bool(raw.get("enabled", False)),
            "authentication_required": bool(
                raw.get("authentication_required", False)
            ),
            "rate_limit": str(raw.get("rate_limit") or source.rate_limit).strip(),
            "retry_policy": _json_safe(raw.get("retry_policy") or {}),
            "cache_policy": _json_safe(raw.get("cache_policy") or {}),
        }
        if not normalized["rate_limit"]:
            raise FitmentIntelligenceError("source capability rate_limit is required")
        if existing is not None:
            actual = {
                "enabled": existing.enabled,
                "authentication_required": existing.authentication_required,
                "rate_limit": existing.rate_limit,
                "retry_policy": existing.retry_policy,
                "cache_policy": existing.cache_policy,
            }
            if actual != normalized:
                raise FitmentIdempotencyConflict(
                    "source capability policy exists with different content"
                )
            continue
        session.add(
            FitmentSourceCapability(
                source_id=source.id,
                capability=capability,
                policy_version=policy_version,
                **normalized,
            )
        )


async def register_source_document(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    source_id: UUID,
    source_url: str,
    retrieval_query: str,
    content_sha256: str,
    content_locator: str | None,
    response_metadata: Mapping[str, Any],
    retrieved_at: datetime,
    expires_at: datetime | None,
) -> FitmentSourceDocument:
    source = await _get_source_for_workspace(session, workspace_id, source_id)
    _require_source_access(source)
    source_host = _canonical_domain(source_url)
    if not (source_host == source.domain or source_host.endswith(f".{source.domain}")):
        raise FitmentSourceBlocked(
            "source document URL is outside the registered source domain"
        )
    final_url = response_metadata.get("final_url")
    if final_url:
        final_host = _canonical_domain(str(final_url))
        if not (
            final_host == source.domain or final_host.endswith(f".{source.domain}")
        ):
            raise FitmentSourceBlocked(
                "source document redirect left the registered source domain"
            )
    if not retrieval_query.strip():
        raise FitmentIntelligenceError("retrieval query is required")
    if expires_at is not None:
        retrieved_for_compare = (
            retrieved_at
            if retrieved_at.tzinfo is not None
            else retrieved_at.replace(tzinfo=UTC)
        )
        expires_for_compare = (
            expires_at
            if expires_at.tzinfo is not None
            else expires_at.replace(tzinfo=UTC)
        )
        if expires_for_compare <= retrieved_for_compare:
            raise FitmentIntelligenceError(
                "source document expiry must follow retrieval"
            )
    digest = content_sha256.strip().casefold()
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise FitmentIntelligenceError("content_sha256 must be a lowercase SHA-256")
    existing = await session.scalar(
        select(FitmentSourceDocument).where(
            FitmentSourceDocument.source_id == source_id,
            FitmentSourceDocument.content_sha256 == digest,
        )
    )
    if existing is not None:
        return existing
    document = FitmentSourceDocument(
        source_id=source_id,
        source_url=source_url.strip(),
        retrieval_query=retrieval_query.strip(),
        content_sha256=digest,
        content_locator=content_locator.strip() if content_locator else None,
        response_metadata=_json_safe(response_metadata),
        retrieved_at=retrieved_at,
        expires_at=expires_at,
    )
    session.add(document)
    await session.flush()
    session.add(
        _audit_event(
            workspace_id=workspace_id,
            event_type="fitment_source_document_registered",
            entity_type="fitment_source_document",
            entity_id=str(document.id),
            actor_user_id=actor_user_id,
            payload={"source_id": str(source_id), "content_sha256": digest},
        )
    )
    await session.commit()
    return document


def _validate_analysis_key_and_candidates(
    idempotency_key: str, spec: AnalysisSpec
) -> str:
    if not spec.candidates:
        raise FitmentIntelligenceError("at least one candidate is required")
    if len(spec.candidates) > 100:
        raise FitmentIntelligenceError("at most 100 candidates are allowed per job")
    key = idempotency_key.strip()
    if not key or len(key) > 64:
        raise FitmentIntelligenceError("idempotency key must contain 1-64 characters")
    candidate_ids = [item.market_observation_id for item in spec.candidates]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise FitmentIntelligenceError("duplicate market observation in request")
    evidence_count = sum(len(item.evidence) for item in spec.candidates)
    if evidence_count > 2_000:
        raise FitmentIntelligenceError(
            "at most 2000 evidence claims are allowed per analysis job"
        )
    return key


def _analysis_request_hash(
    catalog_item_id: UUID,
    pricing_run_id: UUID | None,
    spec: AnalysisSpec,
) -> str:
    return _sha256(
        {
            "catalog_item_id": catalog_item_id,
            "pricing_run_id": pricing_run_id,
            "spec": spec,
            "contract_version": FITMENT_CONTRACT_VERSION,
            "scoring_version": FITMENT_SCORING_VERSION,
        }
    )


async def _validate_analysis_scope(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    catalog_item_id: UUID,
    pricing_run_id: UUID | None,
    spec: AnalysisSpec,
    authorize_evidence: bool,
) -> None:
    catalog_item = await session.get(CatalogItem, catalog_item_id)
    if catalog_item is None or catalog_item.workspace_id != workspace_id:
        raise FitmentNotFoundError("catalog item not found")
    if pricing_run_id is not None:
        run = await session.get(PricingRun, pricing_run_id)
        if run is None or run.workspace_id != workspace_id:
            raise FitmentNotFoundError("pricing run not found")
    candidate_ids = {item.market_observation_id for item in spec.candidates}
    found_ids = set(
        (
            await session.scalars(
                select(MarketObservation.id).where(
                    MarketObservation.id.in_(candidate_ids),
                    MarketObservation.catalog_item_id == catalog_item_id,
                )
            )
        ).all()
    )
    missing = candidate_ids - found_ids
    if missing:
        raise FitmentNotFoundError(
            "market observations not found: "
            + ", ".join(sorted(str(item) for item in missing))
        )
    if authorize_evidence:
        await _authorize_submitted_evidence_batch(
            session,
            workspace_id=workspace_id,
            submissions=[
                item for candidate in spec.candidates for item in candidate.evidence
            ],
        )


async def enqueue_fitment_analysis(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    catalog_item_id: UUID,
    pricing_run_id: UUID | None,
    idempotency_key: str,
    spec: AnalysisSpec,
    celery_app: Celery,
) -> FitmentAnalysis:
    """Atomically admit an analysis and dispatch an idempotent worker task."""

    key = _validate_analysis_key_and_candidates(idempotency_key, spec)
    await _validate_analysis_scope(
        session,
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        pricing_run_id=pricing_run_id,
        spec=spec,
        authorize_evidence=True,
    )
    await _lock_analysis_idempotency_scope(
        session,
        workspace_id=workspace_id,
        idempotency_key=key,
    )
    request_hash = _analysis_request_hash(catalog_item_id, pricing_run_id, spec)
    existing = await session.scalar(
        select(FitmentAnalysis)
        .where(
            FitmentAnalysis.workspace_id == workspace_id,
            FitmentAnalysis.idempotency_key == key,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.request_sha256 != request_hash:
            raise FitmentIdempotencyConflict(
                "idempotency key already belongs to another analysis request"
            )
        dispatch = await session.scalar(
            select(ScrapeDispatchOutbox).where(
                ScrapeDispatchOutbox.task_id == existing.dispatch_task_id
            )
        )
        if dispatch is not None and dispatch.status != "published":
            await publish_dispatch(
                session,
                event_id=dispatch.id,
                celery_app=celery_app,
            )
        return existing

    source_document_ids = sorted(
        {
            str(item.source_document_id)
            for candidate in spec.candidates
            for item in candidate.evidence
            if item.source_document_id is not None
        }
    )
    enforced_policy_snapshot = {
        "policy_version": FITMENT_SOURCE_POLICY_VERSION,
        "submitted_metadata": _json_safe(spec.source_policy_snapshot),
        "source_document_ids": source_document_ids,
        "unregistered_sources": "marketplace_or_replay_tier_d_only",
        "retrieval_mode": "query_level",
    }
    analysis = FitmentAnalysis(
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        pricing_run_id=pricing_run_id,
        requested_by=actor_user_id,
        idempotency_key=key,
        status="queued",
        workflow_state="EVIDENCE_COLLECTION_STARTED",
        target_identity=_json_safe(spec.target_identity),
        target_commercial_context=_json_safe(spec.target_commercial_context),
        source_policy_snapshot=enforced_policy_snapshot,
        request_payload=_json_safe(spec),
        contract_version=FITMENT_CONTRACT_VERSION,
        scoring_version=FITMENT_SCORING_VERSION,
        request_sha256=request_hash,
        candidate_count=len(spec.candidates),
        completed_candidate_count=0,
        failed_candidate_count=0,
        attempt_count=0,
    )
    session.add(analysis)
    await session.flush()
    dispatch = await enqueue_dispatch(
        session,
        event_key=f"fitment-analysis:{analysis.id}:{request_hash}",
        aggregate_type="fitment_analysis",
        aggregate_id=analysis.id,
        workspace_id=workspace_id,
        task_name=FITMENT_ANALYSIS_TASK_NAME,
        task_args=[str(analysis.id)],
        queue="celery",
        max_attempts=20,
    )
    analysis.dispatch_task_id = dispatch.task_id
    session.add(
        _audit_event(
            workspace_id=workspace_id,
            event_type="fitment_analysis_queued",
            entity_type="fitment_analysis",
            entity_id=str(analysis.id),
            actor_user_id=actor_user_id,
            payload={
                "catalog_item_id": str(catalog_item_id),
                "candidate_count": len(spec.candidates),
                "request_sha256": request_hash,
                "dispatch_task_id": dispatch.task_id,
            },
        )
    )
    await session.commit()
    await session.refresh(analysis)
    await publish_dispatch(
        session,
        event_id=dispatch.id,
        celery_app=celery_app,
    )
    return analysis


async def create_fitment_analysis(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID | None,
    catalog_item_id: UUID,
    pricing_run_id: UUID | None,
    idempotency_key: str,
    spec: AnalysisSpec,
    execute_existing: bool = False,
) -> FitmentAnalysis:
    key = _validate_analysis_key_and_candidates(idempotency_key, spec)
    await _validate_analysis_scope(
        session,
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        pricing_run_id=pricing_run_id,
        spec=spec,
        authorize_evidence=False,
    )
    request_hash = _analysis_request_hash(catalog_item_id, pricing_run_id, spec)
    existing = await session.scalar(
        select(FitmentAnalysis).where(
            FitmentAnalysis.workspace_id == workspace_id,
            FitmentAnalysis.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.request_sha256 != request_hash:
            raise FitmentIdempotencyConflict(
                "idempotency key already belongs to another analysis request"
            )
        if not execute_existing or existing.status == "completed":
            return existing

    candidate_ids = [item.market_observation_id for item in spec.candidates]
    observations = {
        observation.id: observation
        for observation in (
            await session.scalars(
                select(MarketObservation).where(
                    MarketObservation.id.in_(candidate_ids),
                    MarketObservation.catalog_item_id == catalog_item_id,
                )
            )
        ).all()
    }
    missing_observations = set(candidate_ids) - set(observations)
    if missing_observations:
        missing = sorted(str(item) for item in missing_observations)
        raise FitmentNotFoundError(
            "market observations not found: " + ", ".join(missing)
        )
    relation_by_seller = await _current_seller_relations(
        session,
        workspace_id=workspace_id,
        marketplace="prom",
        seller_external_ids={item.seller_id for item in observations.values()},
    )
    classification_by_observation = await _current_tier_classifications(
        session, set(candidate_ids)
    )
    submitted = [item for candidate in spec.candidates for item in candidate.evidence]
    authorized_claim_by_submission = await _authorize_submitted_evidence_batch(
        session,
        workspace_id=workspace_id,
        submissions=submitted,
    )
    if existing is None:
        analysis = FitmentAnalysis(
            workspace_id=workspace_id,
            catalog_item_id=catalog_item_id,
            pricing_run_id=pricing_run_id,
            requested_by=actor_user_id,
            idempotency_key=key,
            status="running",
            workflow_state="EVIDENCE_COLLECTION_STARTED",
            target_identity=_json_safe(spec.target_identity),
            target_commercial_context=_json_safe(spec.target_commercial_context),
            source_policy_snapshot=_json_safe(spec.source_policy_snapshot),
            request_payload=_json_safe(spec),
            contract_version=FITMENT_CONTRACT_VERSION,
            scoring_version=FITMENT_SCORING_VERSION,
            request_sha256=request_hash,
            candidate_count=len(spec.candidates),
            completed_candidate_count=0,
            failed_candidate_count=0,
            attempt_count=1,
            started_at=datetime.now(UTC),
            last_attempt_at=datetime.now(UTC),
        )
        session.add(analysis)
        await session.flush()
    else:
        analysis = existing
        analysis.status = "running"
        analysis.error = None
        analysis.completed_candidate_count = 0
        analysis.failed_candidate_count = 0
        analysis.finished_at = None
        if analysis.started_at is None:
            analysis.started_at = datetime.now(UTC)

    for candidate in spec.candidates:
        observation = observations[candidate.market_observation_id]
        relation_record, relation = relation_by_seller[observation.seller_id]
        commercial = _authoritative_commercial_context(
            observation=observation,
            submitted=candidate.commercial_context,
            relation=relation,
            classification=classification_by_observation.get(observation.id),
        )
        submitted_claims = tuple(
            authorized_claim_by_submission[id(item)] for item in candidate.evidence
        )
        derived_claims = _claims_from_observation(observation)
        claims = _deduplicate_claims((*submitted_claims, *derived_claims))
        fitment = assess_compatibility(
            spec.target_identity,
            candidate.identity,
            claims,
        )
        price_unit = normalize_price_unit(
            Decimal(observation.sale_price or observation.price),
            quantity_in_offer=commercial.package_quantity,
            unit_basis=commercial.unit_basis,
        )
        target_unit = normalize_price_unit(
            Decimal("1"),
            quantity_in_offer=spec.target_commercial_context.package_quantity,
            unit_basis=spec.target_commercial_context.unit_basis,
        )
        price = assess_price_comparability(
            fitment,
            _commercial_context_after_unit_normalization(
                spec.target_commercial_context,
                status=target_unit.status,
            ),
            _commercial_context_after_unit_normalization(
                commercial,
                status=price_unit.status,
            ),
            source_quality=_source_quality(claims),
            freshness_factor=_observation_freshness(observation),
        )
        record = FitmentCandidateAssessment(
            id=uuid4(),
            analysis_id=analysis.id,
            market_observation_id=observation.id,
            seller_relation_record_id=(
                relation_record.id if relation_record is not None else None
            ),
            candidate_identity=_json_safe(candidate.identity),
            candidate_commercial_context=_json_safe(commercial),
            compatibility_status=fitment.status.value,
            compatibility_probability=fitment.probability,
            positive_evidence=fitment.positive_evidence,
            negative_evidence=fitment.negative_evidence,
            coverage=fitment.coverage,
            contradiction_rate=fitment.contradiction_rate,
            missing_critical_ratio=fitment.missing_critical_ratio,
            hard_rejections=list(fitment.hard_rejections),
            reason_codes=list(fitment.reason_codes),
            missing_critical_fields=list(fitment.missing_critical_fields),
            feature_consensus={
                feature.value: _json_safe(value)
                for feature, value in fitment.feature_consensus.items()
            },
            authoritative_confirmation=fitment.authoritative_confirmation,
            requires_manual_review=fitment.requires_manual_review,
            evidence_ids=list(fitment.evidence_ids),
            price_comparability_status=price.status.value,
            price_eligible=price.eligible_for_pricing,
            competitor_weight=price.competitor_weight,
            normalized_unit_price=price_unit.normalized_price_per_piece,
            price_unit_status=price_unit.status.value,
            price_unit_certainty=price_unit.certainty_factor,
            price_factor_trace={
                "compatibility": str(price.compatibility_factor),
                "source_quality": str(price.source_quality_factor),
                "seller_independence": str(price.seller_independence_factor),
                "availability": str(price.availability_factor),
                "freshness": str(price.freshness_factor),
                "tier": str(price.tier_factor),
                "condition": str(price.condition_factor),
            },
            price_reason_codes=list(price.reason_codes),
            automatic_price_change_allowed=False,
            contract_version=fitment.contract_version,
            scoring_version=fitment.scoring_version,
        )
        session.add(record)
        source_document_by_evidence = {
            submitted.claim.evidence_id: submitted.source_document_id
            for submitted in candidate.evidence
        }
        for claim in claims:
            session.add(
                FitmentEvidenceClaim(
                    analysis_id=analysis.id,
                    assessment_id=record.id,
                    source_document_id=source_document_by_evidence.get(
                        claim.evidence_id
                    ),
                    evidence_key=f"{observation.id}:{claim.evidence_id}"[:255],
                    feature=claim.feature.value,
                    evidence_value=claim.value,
                    source_external_id=claim.source_id,
                    source_type=claim.source_type,
                    source_tier=claim.source_tier.value,
                    source_reliability=claim.source_reliability,
                    extraction_confidence=claim.extraction_confidence,
                    directness=claim.directness,
                    independence_factor=claim.independence_factor,
                    freshness_factor=claim.freshness_factor,
                    correlation_group=claim.correlation_group,
                    polarity=claim.polarity.value,
                    statement_status=claim.statement_status.value,
                    claim_value=_json_safe(claim.claim_value),
                    source_url=claim.source_url,
                    raw_fragment=claim.raw_fragment,
                    source_document_sha256=claim.source_document_sha256,
                    retrieved_at=claim.retrieved_at,
                )
            )
        analysis.completed_candidate_count += 1

    analysis.status = "completed"
    analysis.workflow_state = "PRICE_COMPARABILITY_EVALUATED"
    analysis.finished_at = datetime.now(UTC)
    analysis.lease_expires_at = None
    session.add(
        _audit_event(
            workspace_id=workspace_id,
            event_type="fitment_analysis_completed",
            entity_type="fitment_analysis",
            entity_id=str(analysis.id),
            actor_user_id=actor_user_id,
            payload={
                "catalog_item_id": str(catalog_item_id),
                "candidate_count": len(spec.candidates),
                "request_sha256": request_hash,
                "automatic_price_change_allowed": False,
            },
        )
    )
    await session.commit()
    return analysis


def _commercial_context_from_payload(payload: Mapping[str, Any]) -> CommercialContext:
    package_quantity = payload.get("package_quantity")
    return CommercialContext(
        condition=Condition(str(payload.get("condition", Condition.UNKNOWN.value))),
        package_quantity=(
            Decimal(str(package_quantity)) if package_quantity is not None else None
        ),
        unit_basis=(
            str(payload["unit_basis"])
            if payload.get("unit_basis") is not None
            else None
        ),
        currency=(
            str(payload["currency"]) if payload.get("currency") is not None else None
        ),
        tier=ProductTier(str(payload.get("tier", ProductTier.UNKNOWN.value))),
        availability=Availability(
            str(payload.get("availability", Availability.UNKNOWN.value))
        ),
        seller_relation=SellerRelation(
            str(payload.get("seller_relation", SellerRelation.UNKNOWN.value))
        ),
        stable_seller_id_verified=bool(payload.get("stable_seller_id_verified", False)),
        seller_group_id=(
            str(payload["seller_group_id"])
            if payload.get("seller_group_id") is not None
            else None
        ),
        product_identity_key=(
            str(payload["product_identity_key"])
            if payload.get("product_identity_key") is not None
            else None
        ),
    )


def _part_identity_from_payload(payload: Mapping[str, Any]) -> PartIdentity:
    values = dict(payload)
    values["oe_numbers"] = tuple(str(item) for item in values.get("oe_numbers", []))
    return PartIdentity(**values)


def _evidence_claim_from_payload(payload: Mapping[str, Any]) -> EvidenceClaim:
    return EvidenceClaim(
        evidence_id=str(payload["evidence_id"]),
        feature=FitmentFeature(str(payload["feature"])),
        value=Decimal(str(payload["value"])),
        source_id=str(payload["source_id"]),
        source_type=str(payload["source_type"]),
        source_tier=SourceTier(str(payload["source_tier"])),
        source_reliability=Decimal(str(payload["source_reliability"])),
        extraction_confidence=Decimal(str(payload["extraction_confidence"])),
        directness=Decimal(str(payload.get("directness", "1"))),
        independence_factor=Decimal(str(payload["independence_factor"])),
        freshness_factor=Decimal(str(payload["freshness_factor"])),
        correlation_group=str(payload["correlation_group"]),
        polarity=EvidencePolarity(str(payload["polarity"])),
        statement_status=StatementStatus(str(payload["statement_status"])),
        claim_value=dict(payload.get("claim_value", {})),
        retrieved_at=datetime.fromisoformat(str(payload["retrieved_at"])),
        source_url=(
            str(payload["source_url"])
            if payload.get("source_url") is not None
            else None
        ),
        raw_fragment=(
            str(payload["raw_fragment"])
            if payload.get("raw_fragment") is not None
            else None
        ),
        source_document_sha256=(
            str(payload["source_document_sha256"])
            if payload.get("source_document_sha256") is not None
            else None
        ),
    )


def _analysis_spec_from_payload(payload: Mapping[str, Any]) -> AnalysisSpec:
    try:
        candidates = tuple(
            CandidateAnalysisSpec(
                market_observation_id=UUID(str(item["market_observation_id"])),
                identity=_part_identity_from_payload(item["identity"]),
                commercial_context=_commercial_context_from_payload(
                    item["commercial_context"]
                ),
                evidence=tuple(
                    SubmittedEvidence(
                        claim=_evidence_claim_from_payload(submitted["claim"]),
                        source_document_id=(
                            UUID(str(submitted["source_document_id"]))
                            if submitted.get("source_document_id") is not None
                            else None
                        ),
                    )
                    for submitted in item.get("evidence", [])
                ),
            )
            for item in payload["candidates"]
        )
        return AnalysisSpec(
            target_identity=_part_identity_from_payload(payload["target_identity"]),
            target_commercial_context=_commercial_context_from_payload(
                payload["target_commercial_context"]
            ),
            candidates=candidates,
            source_policy_snapshot=dict(payload.get("source_policy_snapshot", {})),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FitmentIntelligenceError(
            f"invalid persisted fitment request payload: {exc}"
        ) from exc


async def process_fitment_analysis_job(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    task_id: str,
) -> FitmentAnalysis | None:
    """Claim and execute one durable analysis with a bounded worker lease."""

    now = datetime.now(UTC)
    analysis = await session.scalar(
        select(FitmentAnalysis)
        .where(FitmentAnalysis.id == analysis_id)
        .with_for_update()
    )
    if analysis is None:
        raise FitmentNotFoundError("fitment analysis not found")
    if analysis.status == "completed":
        return analysis
    lease_expires_at = analysis.lease_expires_at
    if lease_expires_at is not None and lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    if (
        analysis.status == "running"
        and analysis.owner_task_id not in {None, task_id}
        and lease_expires_at is not None
        and lease_expires_at > now
    ):
        return None

    analysis.status = "running"
    analysis.owner_task_id = task_id
    analysis.attempt_count += 1
    analysis.last_attempt_at = now
    analysis.lease_expires_at = now + timedelta(seconds=FITMENT_ANALYSIS_LEASE_SECONDS)
    analysis.error = None
    if analysis.started_at is None:
        analysis.started_at = now
    workspace_id = analysis.workspace_id
    actor_user_id = analysis.requested_by
    catalog_item_id = analysis.catalog_item_id
    pricing_run_id = analysis.pricing_run_id
    idempotency_key = analysis.idempotency_key
    request_payload = dict(analysis.request_payload)
    await session.commit()

    spec = _analysis_spec_from_payload(request_payload)
    return await create_fitment_analysis(
        session,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        catalog_item_id=catalog_item_id,
        pricing_run_id=pricing_run_id,
        idempotency_key=idempotency_key,
        spec=spec,
        execute_existing=True,
    )


async def fail_fitment_analysis_job(
    session: AsyncSession,
    *,
    analysis_id: UUID,
    task_id: str,
    error: Exception,
) -> None:
    analysis = await session.scalar(
        select(FitmentAnalysis)
        .where(FitmentAnalysis.id == analysis_id)
        .with_for_update()
    )
    if analysis is None or analysis.status == "completed":
        return
    if analysis.owner_task_id not in {None, task_id}:
        return
    detail = f"{type(error).__name__}: {error}"[:4000]
    analysis.status = "failed"
    analysis.workflow_state = "FAILED"
    analysis.error = detail
    analysis.failed_candidate_count = analysis.candidate_count
    analysis.completed_candidate_count = 0
    analysis.lease_expires_at = None
    analysis.finished_at = datetime.now(UTC)
    session.add(
        _audit_event(
            workspace_id=analysis.workspace_id,
            event_type="fitment_analysis_failed",
            entity_type="fitment_analysis",
            entity_id=str(analysis.id),
            actor_user_id=analysis.requested_by,
            payload={
                "task_id": task_id,
                "attempt_count": analysis.attempt_count,
                "error": detail,
            },
        )
    )
    await session.commit()


async def retry_fitment_analysis(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    analysis_id: UUID,
    celery_app: Celery,
) -> FitmentAnalysis:
    """Requeue a failed/partial analysis through the durable outbox."""

    analysis = await session.scalar(
        select(FitmentAnalysis)
        .where(
            FitmentAnalysis.id == analysis_id,
            FitmentAnalysis.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if analysis is None:
        raise FitmentNotFoundError("fitment analysis not found")
    if analysis.status not in {"failed", "partial"}:
        raise FitmentIntelligenceError(
            "only failed or partial fitment analyses can be retried"
        )
    retry_no = analysis.attempt_count + 1
    dispatch = await enqueue_dispatch(
        session,
        event_key=f"fitment-analysis-retry:{analysis.id}:{retry_no}",
        aggregate_type="fitment_analysis",
        aggregate_id=analysis.id,
        workspace_id=workspace_id,
        task_name=FITMENT_ANALYSIS_TASK_NAME,
        task_args=[str(analysis.id)],
        queue="celery",
        max_attempts=20,
    )
    analysis.status = "queued"
    analysis.workflow_state = "EVIDENCE_COLLECTION_STARTED"
    analysis.error = None
    analysis.owner_task_id = None
    analysis.dispatch_task_id = dispatch.task_id
    analysis.lease_expires_at = None
    analysis.finished_at = None
    analysis.failed_candidate_count = 0
    session.add(
        _audit_event(
            workspace_id=workspace_id,
            event_type="fitment_analysis_retried",
            entity_type="fitment_analysis",
            entity_id=str(analysis.id),
            actor_user_id=actor_user_id,
            payload={"retry_no": retry_no, "dispatch_task_id": dispatch.task_id},
        )
    )
    await session.commit()
    await publish_dispatch(session, event_id=dispatch.id, celery_app=celery_app)
    await session.refresh(analysis)
    return analysis


async def get_fitment_analysis(
    session: AsyncSession, *, workspace_id: UUID, analysis_id: UUID
) -> FitmentAnalysis:
    analysis = await session.get(FitmentAnalysis, analysis_id)
    if analysis is None or analysis.workspace_id != workspace_id:
        raise FitmentNotFoundError("fitment analysis not found")
    return analysis


async def list_fitment_candidates(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    catalog_item_id: UUID,
    analysis_id: UUID | None,
    limit: int,
    offset: int,
) -> tuple[
    list[
        tuple[
            FitmentCandidateAssessment,
            MarketObservation,
            tuple[FitmentEvidenceClaim, ...],
        ]
    ],
    int,
    FitmentAnalysis | None,
]:
    if analysis_id is None:
        analysis = await session.scalar(
            select(FitmentAnalysis)
            .where(
                FitmentAnalysis.workspace_id == workspace_id,
                FitmentAnalysis.catalog_item_id == catalog_item_id,
            )
            .order_by(FitmentAnalysis.created_at.desc(), FitmentAnalysis.id.desc())
            .limit(1)
        )
        if analysis is None:
            return [], 0, None
    else:
        analysis = await get_fitment_analysis(
            session, workspace_id=workspace_id, analysis_id=analysis_id
        )
        if analysis.catalog_item_id != catalog_item_id:
            raise FitmentNotFoundError("analysis does not belong to catalog item")
    filters = (FitmentCandidateAssessment.analysis_id == analysis.id,)
    total = int(
        await session.scalar(
            select(func.count(FitmentCandidateAssessment.id)).where(*filters)
        )
        or 0
    )
    rows = list(
        (
            await session.execute(
                select(FitmentCandidateAssessment, MarketObservation)
                .join(
                    MarketObservation,
                    MarketObservation.id
                    == FitmentCandidateAssessment.market_observation_id,
                )
                .where(*filters)
                .order_by(
                    FitmentCandidateAssessment.compatibility_probability.desc(),
                    FitmentCandidateAssessment.id,
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    assessment_ids = {assessment.id for assessment, _ in rows}
    evidence_claims: dict[UUID, list[FitmentEvidenceClaim]] = defaultdict(list)
    if assessment_ids:
        claim_rows = (
            await session.execute(
                select(FitmentEvidenceClaim)
                .where(FitmentEvidenceClaim.assessment_id.in_(assessment_ids))
                .order_by(
                    FitmentEvidenceClaim.assessment_id,
                    FitmentEvidenceClaim.id,
                )
            )
        ).all()
        for (claim,) in claim_rows:
            evidence_claims[claim.assessment_id].append(claim)
    enriched_rows = [
        (
            assessment,
            observation,
            tuple(evidence_claims[assessment.id]),
        )
        for assessment, observation in rows
    ]
    return enriched_rows, total, analysis


async def add_seller_relation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    marketplace: str,
    seller_external_id: str,
    seller_name: str | None,
    relation: SellerRelation,
    confidence: Decimal,
    evidence: Sequence[Mapping[str, Any]],
    reason: str,
    idempotency_key: str,
) -> SellerRelationRecord:
    if confidence < 0 or confidence > 1:
        raise FitmentIntelligenceError("seller confidence must be in [0, 1]")
    if relation in {SellerRelation.OWN, SellerRelation.RELATED} and not evidence:
        raise FitmentIntelligenceError("own/related seller requires explicit evidence")
    existing = await session.scalar(
        select(SellerRelationRecord).where(
            SellerRelationRecord.workspace_id == workspace_id,
            SellerRelationRecord.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.seller_external_id != seller_external_id
            or existing.relation != relation.value
        ):
            raise FitmentIdempotencyConflict(
                "seller idempotency key already belongs to another decision"
            )
        return existing
    previous, _ = await _current_seller_relation(
        session,
        workspace_id=workspace_id,
        marketplace=marketplace,
        seller_external_id=seller_external_id,
        include_owned_store_fallback=False,
    )
    record = SellerRelationRecord(
        workspace_id=workspace_id,
        marketplace=marketplace.strip().casefold(),
        seller_external_id=seller_external_id.strip(),
        seller_name=seller_name.strip() if seller_name else None,
        relation=relation.value,
        confidence=confidence,
        evidence=[_json_safe(item) for item in evidence],
        reason=reason.strip(),
        idempotency_key=idempotency_key.strip(),
        supersedes_id=previous.id if previous is not None else None,
        created_by=actor_user_id,
    )
    session.add(record)
    await session.flush()
    session.add(
        _audit_event(
            workspace_id=workspace_id,
            event_type="seller_relation_recorded",
            entity_type="seller",
            entity_id=record.seller_external_id,
            actor_user_id=actor_user_id,
            payload={
                "relation": relation.value,
                "confidence": str(confidence),
                "supersedes_id": str(record.supersedes_id)
                if record.supersedes_id
                else None,
            },
        )
    )
    await session.commit()
    return record


async def add_fitment_review(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    assessment_id: UUID,
    idempotency_key: str,
    decision: str,
    reason_code: str,
    comment: str | None,
    evidence_verdicts: Sequence[Mapping[str, Any]] = (),
) -> FitmentHumanReview:
    if decision not in {
        "mark_candidate_compatible",
        "mark_candidate_incompatible",
        "postpone",
        "request_additional_check",
    }:
        raise FitmentIntelligenceError("invalid fitment review decision")
    assessment = await session.get(FitmentCandidateAssessment, assessment_id)
    if assessment is None:
        raise FitmentNotFoundError("candidate assessment not found")
    analysis = await session.get(FitmentAnalysis, assessment.analysis_id)
    if analysis is None or analysis.workspace_id != workspace_id:
        raise FitmentNotFoundError("candidate assessment not found")
    existing = await session.scalar(
        select(FitmentHumanReview).where(
            FitmentHumanReview.workspace_id == workspace_id,
            FitmentHumanReview.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.assessment_id != assessment_id or existing.decision != decision:
            raise FitmentIdempotencyConflict(
                "review idempotency key already belongs to another decision"
            )
        return existing
    evidence_hash = _sha256(
        {
            "assessment_id": assessment_id,
            "status": assessment.compatibility_status,
            "probability": assessment.compatibility_probability,
            "evidence_ids": assessment.evidence_ids,
        }
    )
    review = FitmentHumanReview(
        workspace_id=workspace_id,
        assessment_id=assessment_id,
        reviewer_id=actor_user_id,
        idempotency_key=idempotency_key.strip(),
        decision=decision,
        reason_code=reason_code.strip(),
        comment=comment.strip() if comment else None,
        system_status_snapshot=assessment.compatibility_status,
        system_probability_snapshot=assessment.compatibility_probability,
        evidence_snapshot_sha256=evidence_hash,
    )
    session.add(review)
    await session.flush()
    session.add(
        FitmentFeedbackEvent(
            workspace_id=workspace_id,
            reviewer_id=actor_user_id,
            idempotency_key=_sha256(
                {"review_id": review.id, "event_type": "candidate_review"}
            ),
            entity_type="fitment_candidate_assessment",
            entity_id=str(assessment_id),
            event_type="candidate_fitment_decision",
            reason_code=reason_code.strip(),
            label_payload={
                "decision": decision,
                "system_status": assessment.compatibility_status,
                "system_probability": str(assessment.compatibility_probability),
                "blind_online_learning_allowed": False,
            },
            status="active",
            label_version="fitment-hitl-feedback-v1",
        )
    )
    await _record_evidence_verdicts(
        session,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        review=review,
        assessment=assessment,
        evidence_verdicts=evidence_verdicts,
    )
    session.add(
        _audit_event(
            workspace_id=workspace_id,
            event_type="fitment_candidate_reviewed",
            entity_type="fitment_candidate_assessment",
            entity_id=str(assessment_id),
            actor_user_id=actor_user_id,
            payload={
                "decision": decision,
                "reason_code": reason_code,
                "evidence_snapshot_sha256": evidence_hash,
            },
        )
    )
    await session.commit()
    return review


async def _record_evidence_verdicts(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    review: FitmentHumanReview,
    assessment: FitmentCandidateAssessment,
    evidence_verdicts: Sequence[Mapping[str, Any]],
) -> None:
    if not evidence_verdicts:
        return
    verdict_by_id: dict[UUID, str] = {}
    for raw in evidence_verdicts:
        claim_id = UUID(str(raw.get("evidence_claim_id")))
        verdict = str(raw.get("verdict") or "")
        if verdict not in {"confirmed", "rejected"}:
            raise FitmentIntelligenceError("invalid evidence verdict")
        if claim_id in verdict_by_id:
            raise FitmentIntelligenceError("duplicate evidence verdict")
        verdict_by_id[claim_id] = verdict
    claims = list(
        (
            await session.scalars(
                select(FitmentEvidenceClaim).where(
                    FitmentEvidenceClaim.id.in_(set(verdict_by_id)),
                    FitmentEvidenceClaim.assessment_id == assessment.id,
                )
            )
        ).all()
    )
    if {claim.id for claim in claims} != set(verdict_by_id):
        raise FitmentNotFoundError("reviewed evidence claim not found")
    for claim in claims:
        if claim.source_document_id is None:
            raise FitmentIntelligenceError(
                "unregistered marketplace/replay evidence cannot update source reliability"
            )
        document = await session.get(FitmentSourceDocument, claim.source_document_id)
        if document is None:
            raise FitmentNotFoundError("source document not found")
        source = await _get_source_for_workspace(session, workspace_id, document.source_id)
        await _lock_source_reliability_scope(
            session,
            source_id=source.id,
            claim_type=claim.feature,
        )
        previous = await session.scalar(
            select(FitmentSourceReliabilitySnapshot)
            .where(
                FitmentSourceReliabilitySnapshot.source_id == source.id,
                FitmentSourceReliabilitySnapshot.claim_type == claim.feature,
            )
            .order_by(
                FitmentSourceReliabilitySnapshot.created_at.desc(),
                FitmentSourceReliabilitySnapshot.id.desc(),
            )
            .limit(1)
        )
        confirmed = previous.confirmed_count if previous is not None else 0
        rejected = previous.rejected_count if previous is not None else 0
        if verdict_by_id[claim.id] == "confirmed":
            confirmed += 1
        else:
            rejected += 1
        posterior = posterior_source_reliability(
            SourceTier(source.source_tier),
            claim.feature,
            confirmed_count=confirmed,
            rejected_count=rejected,
        )
        event_key = _sha256(
            {
                "review_id": review.id,
                "evidence_claim_id": claim.id,
                "verdict": verdict_by_id[claim.id],
            }
        )
        session.add(
            FitmentFeedbackEvent(
                workspace_id=workspace_id,
                reviewer_id=actor_user_id,
                idempotency_key=event_key,
                entity_type="fitment_evidence_claim",
                entity_id=str(claim.id),
                event_type="evidence_claim_verdict",
                reason_code=verdict_by_id[claim.id],
                label_payload={
                    "source_id": str(source.id),
                    "claim_type": claim.feature,
                    "verdict": verdict_by_id[claim.id],
                    "review_id": str(review.id),
                },
                status="active",
                label_version="fitment-hitl-feedback-v1",
            )
        )
        session.add(
            FitmentSourceReliabilitySnapshot(
                source_id=source.id,
                claim_type=posterior.claim_type,
                source_tier=source.source_tier,
                prior_alpha=posterior.prior_alpha,
                prior_beta=posterior.prior_beta,
                confirmed_count=posterior.confirmed_count,
                rejected_count=posterior.rejected_count,
                reliability=posterior.reliability,
                label_event_key=event_key,
                method_version=posterior.version,
                supersedes_id=previous.id if previous is not None else None,
            )
        )


async def _resolve_cross_reference_evidence(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    article: str,
    oe: str,
    relation_status: str,
    evidence_claim_ids: Sequence[UUID],
) -> tuple[list[str], int, int]:
    """Resolve cross metrics from persisted evidence instead of trusting input."""

    unique_ids = set(evidence_claim_ids)
    if not unique_ids:
        if relation_status in {"machine_discovered", "deprecated", "superseded"}:
            return [], 0, 0
        raise FitmentIntelligenceError("cross-reference evidence is required")
    rows = list(
        (
            await session.execute(
                select(
                    FitmentEvidenceClaim,
                    FitmentCandidateAssessment,
                    FitmentAnalysis,
                )
                .join(
                    FitmentCandidateAssessment,
                    FitmentCandidateAssessment.id == FitmentEvidenceClaim.assessment_id,
                )
                .join(
                    FitmentAnalysis,
                    FitmentAnalysis.id == FitmentCandidateAssessment.analysis_id,
                )
                .where(
                    FitmentEvidenceClaim.id.in_(unique_ids),
                    FitmentAnalysis.workspace_id == workspace_id,
                )
            )
        ).all()
    )
    found_ids = {claim.id for claim, _, _ in rows}
    missing = unique_ids - found_ids
    if missing:
        raise FitmentNotFoundError(
            "fitment evidence claims not found: "
            + ", ".join(sorted(str(item) for item in missing))
        )

    identity_features = {
        FitmentFeature.OE_EXACT.value,
        FitmentFeature.OE_SUPERSESSION.value,
        FitmentFeature.CROSS_CONFIRMED.value,
    }
    assessment_ids: set[UUID] = set()
    tier_a_groups: set[str] = set()
    tier_b_groups: set[str] = set()
    correlation_groups: set[str] = set()
    for claim, assessment, analysis in rows:
        candidate_article = normalize_part_number(
            assessment.candidate_identity.get("manufacturer_article")
        )
        target_oes = {
            normalized
            for raw_oe in analysis.target_identity.get("oe_numbers", [])
            if (normalized := normalize_part_number(str(raw_oe))) is not None
        }
        if candidate_article != article or oe not in target_oes:
            raise FitmentIntelligenceError(
                "cross evidence is not linked to the submitted article/OE pair"
            )
        if claim.feature not in identity_features or claim.evidence_value <= 0:
            raise FitmentIntelligenceError(
                "cross-reference may use only positive persisted identity evidence"
            )
        assessment_ids.add(assessment.id)
        correlation_groups.add(claim.correlation_group)
        if claim.source_tier == SourceTier.A.value:
            tier_a_groups.add(claim.correlation_group)
        if claim.source_tier == SourceTier.B.value:
            tier_b_groups.add(claim.correlation_group)

    if relation_status == "source_confirmed" and not (
        tier_a_groups or len(tier_b_groups) >= 2
    ):
        raise FitmentIntelligenceError(
            "source-confirmed cross requires Tier A or two independent Tier B sources"
        )

    required_review_decision = {
        "human_confirmed": "mark_candidate_compatible",
        "human_rejected": "mark_candidate_incompatible",
    }.get(relation_status)
    human_feedback_count = 0
    if required_review_decision is not None:
        human_feedback_count = int(
            await session.scalar(
                select(func.count(FitmentHumanReview.id)).where(
                    FitmentHumanReview.workspace_id == workspace_id,
                    FitmentHumanReview.assessment_id.in_(assessment_ids),
                    FitmentHumanReview.decision == required_review_decision,
                )
            )
            or 0
        )
        if human_feedback_count == 0:
            raise FitmentIntelligenceError(
                f"{relation_status} cross requires a matching persisted human review"
            )

    return (
        sorted(str(item) for item in unique_ids),
        len(correlation_groups),
        human_feedback_count,
    )


async def record_cross_reference(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    brand: str,
    article: str,
    oe: str,
    installation_position: str | None,
    vehicle_key: str | None,
    relation_status: str,
    confidence: Decimal,
    evidence_ids: Sequence[UUID],
    supersedes_id: UUID | None = None,
) -> FitmentCrossReference:
    statuses = {
        "machine_discovered",
        "source_confirmed",
        "human_confirmed",
        "human_rejected",
        "conflicting",
        "deprecated",
        "superseded",
    }
    if relation_status not in statuses:
        raise FitmentIntelligenceError("invalid cross-reference status")
    if confidence < 0 or confidence > 1:
        raise FitmentIntelligenceError("invalid cross-reference metrics")
    normalized_article = normalize_part_number(article)
    normalized_oe = normalize_part_number(oe)
    normalized_brand = _normalize_brand(brand)
    if not normalized_brand or not normalized_article or not normalized_oe:
        raise FitmentIntelligenceError("brand, article and OE are required")
    if normalized_article == normalized_oe:
        raise FitmentIntelligenceError("article and OE must describe a cross relation")
    if relation_status in {"source_confirmed", "human_confirmed"} and not evidence_ids:
        raise FitmentIntelligenceError("confirmed cross requires evidence")
    (
        normalized_evidence_ids,
        source_count,
        human_feedback_count,
    ) = await _resolve_cross_reference_evidence(
        session,
        workspace_id=workspace_id,
        article=normalized_article,
        oe=normalized_oe,
        relation_status=relation_status,
        evidence_claim_ids=evidence_ids,
    )
    if supersedes_id is not None:
        previous = await session.get(FitmentCrossReference, supersedes_id)
        if previous is None or previous.workspace_id != workspace_id:
            raise FitmentNotFoundError("superseded cross-reference not found")
    now = datetime.now(UTC)
    fingerprint = _sha256(
        {
            "workspace_id": workspace_id,
            "normalized_brand": normalized_brand,
            "normalized_article": normalized_article,
            "normalized_oe": normalized_oe,
            "installation_position": installation_position,
            "vehicle_key": vehicle_key,
            "relation_status": relation_status,
            "confidence": confidence,
            "evidence_ids": normalized_evidence_ids,
            "source_count": source_count,
            "human_feedback_count": human_feedback_count,
            "supersedes_id": supersedes_id,
            "method_version": FITMENT_CROSS_METHOD_VERSION,
        }
    )
    existing = await session.scalar(
        select(FitmentCrossReference).where(
            FitmentCrossReference.workspace_id == workspace_id,
            FitmentCrossReference.record_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        return existing
    record = FitmentCrossReference(
        workspace_id=workspace_id,
        brand=brand.strip(),
        normalized_brand=normalized_brand,
        article=article.strip(),
        normalized_article=normalized_article,
        oe=oe.strip(),
        normalized_oe=normalized_oe,
        installation_position=(
            installation_position.strip() if installation_position else None
        ),
        vehicle_key=vehicle_key.strip() if vehicle_key else None,
        relation_status=relation_status,
        confidence=confidence,
        evidence_ids=normalized_evidence_ids,
        source_count=source_count,
        human_feedback_count=human_feedback_count,
        record_fingerprint=fingerprint,
        method_version=FITMENT_CROSS_METHOD_VERSION,
        valid_from=now,
        last_verified_at=now,
        supersedes_id=supersedes_id,
        created_by=actor_user_id,
    )
    session.add(record)
    await session.flush()
    session.add(
        _audit_event(
            workspace_id=workspace_id,
            event_type="fitment_cross_reference_recorded",
            entity_type="fitment_cross_reference",
            entity_id=str(record.id),
            actor_user_id=actor_user_id,
            payload={
                "normalized_brand": normalized_brand,
                "normalized_article": normalized_article,
                "normalized_oe": normalized_oe,
                "relation_status": relation_status,
                "source_count": source_count,
                "human_feedback_count": human_feedback_count,
                "record_fingerprint": fingerprint,
            },
        )
    )
    await session.commit()
    return record


async def search_cross_references(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    article: str | None,
    oe: str | None,
    relation_status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[FitmentCrossReference], int]:
    filters = [FitmentCrossReference.workspace_id == workspace_id]
    if article:
        normalized = normalize_part_number(article)
        if not normalized:
            raise FitmentIntelligenceError("invalid article")
        filters.append(FitmentCrossReference.normalized_article == normalized)
    if oe:
        normalized = normalize_part_number(oe)
        if not normalized:
            raise FitmentIntelligenceError("invalid OE")
        filters.append(FitmentCrossReference.normalized_oe == normalized)
    if relation_status:
        filters.append(FitmentCrossReference.relation_status == relation_status)
    total = int(
        await session.scalar(
            select(func.count(FitmentCrossReference.id)).where(*filters)
        )
        or 0
    )
    rows = list(
        (
            await session.scalars(
                select(FitmentCrossReference)
                .where(*filters)
                .order_by(
                    FitmentCrossReference.last_verified_at.desc(),
                    FitmentCrossReference.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return rows, total


async def fitment_metrics(
    session: AsyncSession, *, workspace_id: UUID, analysis_id: UUID
) -> dict[str, Any]:
    analysis = await get_fitment_analysis(
        session, workspace_id=workspace_id, analysis_id=analysis_id
    )
    rows = list(
        (
            await session.execute(
                select(
                    FitmentCandidateAssessment.compatibility_status,
                    FitmentCandidateAssessment.price_comparability_status,
                    FitmentCandidateAssessment.requires_manual_review,
                    func.count(FitmentCandidateAssessment.id),
                )
                .where(FitmentCandidateAssessment.analysis_id == analysis.id)
                .group_by(
                    FitmentCandidateAssessment.compatibility_status,
                    FitmentCandidateAssessment.price_comparability_status,
                    FitmentCandidateAssessment.requires_manual_review,
                )
            )
        ).all()
    )
    compatibility: dict[str, int] = defaultdict(int)
    price: dict[str, int] = defaultdict(int)
    manual = 0
    for compatibility_status, price_status, requires_manual_review, count in rows:
        compatibility[compatibility_status] += int(count)
        price[price_status] += int(count)
        if requires_manual_review:
            manual += int(count)
    total = sum(compatibility.values())
    assessment_rows = list(
        (
            await session.execute(
                select(
                    FitmentCandidateAssessment.id,
                    FitmentCandidateAssessment.compatibility_status,
                    FitmentCandidateAssessment.contradiction_rate,
                    FitmentCandidateAssessment.candidate_commercial_context,
                    FitmentCandidateAssessment.price_eligible,
                ).where(FitmentCandidateAssessment.analysis_id == analysis.id)
            )
        ).all()
    )
    assessment_ids = {row.id for row in assessment_rows}
    source_counts: dict[UUID, int] = {}
    if assessment_ids:
        source_counts = {
            assessment_id_value: int(count)
            for assessment_id_value, count in (
                await session.execute(
                    select(
                        FitmentEvidenceClaim.assessment_id,
                        func.count(
                            func.distinct(FitmentEvidenceClaim.correlation_group)
                        ),
                    )
                    .where(FitmentEvidenceClaim.assessment_id.in_(assessment_ids))
                    .group_by(FitmentEvidenceClaim.assessment_id)
                )
            ).all()
        }
    latest_reviews: dict[UUID, str] = {}
    if assessment_ids:
        review_rows = (
            await session.execute(
                select(
                    FitmentHumanReview.assessment_id,
                    FitmentHumanReview.decision,
                )
                .where(
                    FitmentHumanReview.workspace_id == workspace_id,
                    FitmentHumanReview.assessment_id.in_(assessment_ids),
                )
                .order_by(
                    FitmentHumanReview.assessment_id,
                    FitmentHumanReview.created_at.desc(),
                    FitmentHumanReview.id.desc(),
                )
            )
        ).all()
        for assessment_id_value, decision in review_rows:
            latest_reviews.setdefault(assessment_id_value, decision)

    true_positive = false_positive = true_negative = false_negative = 0
    human_compatible = human_incompatible = 0
    positive_statuses = {"confirmed_compatible", "likely_compatible"}
    conflict_count = own_related_count = price_eligible_count = 0
    for row in assessment_rows:
        conflict_count += int(Decimal(row.contradiction_rate) > 0)
        relation = str(row.candidate_commercial_context.get("seller_relation", ""))
        own_related_count += int(relation in {"own", "related"})
        price_eligible_count += int(row.price_eligible)
        decision = latest_reviews.get(row.id)
        if decision == "mark_candidate_compatible":
            human_compatible += 1
            if row.compatibility_status in positive_statuses:
                true_positive += 1
            elif row.compatibility_status == "not_compatible":
                false_negative += 1
        elif decision == "mark_candidate_incompatible":
            human_incompatible += 1
            if row.compatibility_status in positive_statuses:
                false_positive += 1
            elif row.compatibility_status == "not_compatible":
                true_negative += 1

    def ratio(numerator: int, denominator: int) -> str | None:
        if denominator == 0:
            return None
        return str(
            (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))
        )

    duration_seconds: str | None = None
    if analysis.started_at is not None and analysis.finished_at is not None:
        started = analysis.started_at
        finished = analysis.finished_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=UTC)
        duration_seconds = str(
            Decimal(str(max(0.0, (finished - started).total_seconds()))).quantize(
                Decimal("0.001")
            )
        )
    decisive_reviews = human_compatible + human_incompatible
    recommendation = await session.scalar(
        select(FitmentMarketRecommendation)
        .where(
            FitmentMarketRecommendation.workspace_id == workspace_id,
            FitmentMarketRecommendation.analysis_id == analysis.id,
        )
        .order_by(
            FitmentMarketRecommendation.created_at.desc(),
            FitmentMarketRecommendation.id.desc(),
        )
        .limit(1)
    )
    recommendation_reviews: list[str] = []
    if recommendation is not None:
        recommendation_reviews = list(
            (
                await session.scalars(
                    select(FitmentRecommendationReview.decision).where(
                        FitmentRecommendationReview.workspace_id == workspace_id,
                        FitmentRecommendationReview.recommendation_id
                        == recommendation.id,
                    )
                )
            ).all()
        )
    recommendation_accepts = sum(
        decision in {"accepted", "accepted_with_modification"}
        for decision in recommendation_reviews
    )
    unavailable_metric_reasons = {
        "own_seller_detection_precision": "seller relation gold labels not collected",
        "own_seller_detection_recall": "seller relation gold labels not collected",
        "cache_hit_rate": "cache access events are not yet linked to this analysis",
        "price_recommendation_error": "realized sale outcomes are not available",
    }
    if not recommendation_reviews:
        unavailable_metric_reasons["recommendation_acceptance_rate"] = (
            "recommendation has no human decision labels"
        )
    return {
        "analysis_id": str(analysis.id),
        "candidate_count": total,
        "compatibility": dict(sorted(compatibility.items())),
        "price_comparability": dict(sorted(price.items())),
        "manual_review_rate": str(
            (Decimal(manual) / Decimal(total)).quantize(Decimal("0.0001"))
            if total
            else Decimal("0")
        ),
        "automatic_price_changes": 0,
        "candidate_collection_coverage": ratio(
            analysis.completed_candidate_count, analysis.candidate_count
        ),
        "own_seller_excluded_count": own_related_count,
        "own_seller_detection_precision": None,
        "own_seller_detection_recall": None,
        "compatibility_precision": ratio(true_positive, true_positive + false_positive),
        "compatibility_recall": ratio(true_positive, true_positive + false_negative),
        "false_positive_rate": ratio(false_positive, false_positive + true_negative),
        "false_negative_rate": ratio(false_negative, false_negative + true_positive),
        "human_acceptance_rate": ratio(human_compatible, decisive_reviews),
        "recommendation_acceptance_rate": ratio(
            recommendation_accepts,
            len(recommendation_reviews),
        ),
        "source_failure_rate": ratio(
            analysis.failed_candidate_count, analysis.candidate_count
        ),
        "source_conflict_rate": ratio(conflict_count, total),
        "cache_hit_rate": None,
        "average_sources_per_candidate": (
            str(
                (Decimal(sum(source_counts.values())) / Decimal(total)).quantize(
                    Decimal("0.0001")
                )
            )
            if total
            else None
        ),
        "average_analysis_latency_seconds": duration_seconds,
        "price_recommendation_error": None,
        "price_eligible_count": price_eligible_count,
        "reviewed_candidate_count": decisive_reviews,
        "confusion_matrix": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "true_negative": true_negative,
            "false_negative": false_negative,
        },
        "unavailable_metric_reasons": unavailable_metric_reasons,
        "contract_version": analysis.contract_version,
        "scoring_version": analysis.scoring_version,
    }


async def list_source_capabilities(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    source_id: UUID,
) -> list[FitmentSourceCapability]:
    await _get_source_for_workspace(session, workspace_id, source_id)
    return list(
        (
            await session.scalars(
                select(FitmentSourceCapability)
                .where(FitmentSourceCapability.source_id == source_id)
                .order_by(
                    FitmentSourceCapability.policy_version.desc(),
                    FitmentSourceCapability.capability,
                )
            )
        ).all()
    )


async def list_source_reliability(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    source_id: UUID,
) -> list[FitmentSourceReliabilitySnapshot]:
    await _get_source_for_workspace(session, workspace_id, source_id)
    rows = list(
        (
            await session.scalars(
                select(FitmentSourceReliabilitySnapshot)
                .where(FitmentSourceReliabilitySnapshot.source_id == source_id)
                .order_by(
                    FitmentSourceReliabilitySnapshot.claim_type,
                    FitmentSourceReliabilitySnapshot.created_at.desc(),
                    FitmentSourceReliabilitySnapshot.id.desc(),
                )
            )
        ).all()
    )
    current: dict[str, FitmentSourceReliabilitySnapshot] = {}
    for row in rows:
        current.setdefault(row.claim_type, row)
    return [current[key] for key in sorted(current)]


async def _get_source_for_workspace(
    session: AsyncSession, workspace_id: UUID, source_id: UUID
) -> FitmentSource:
    source = await session.get(FitmentSource, source_id)
    if source is None or source.workspace_id not in {None, workspace_id}:
        raise FitmentNotFoundError("fitment source not found")
    return source


def _require_source_access(source: FitmentSource) -> None:
    if source.access_status not in {"PERMITTED", "OWNER_RISK_ACCEPTED"}:
        raise FitmentSourceBlocked(
            f"source access is not approved: {source.source_key} ({source.access_status})"
        )
    if (
        not source.access_reference.strip()
        or source.access_reference == "legacy-unreviewed"
        or not source.robots_checked
        or not source.terms_checked
    ):
        raise FitmentSourceBlocked(
            f"source access review is incomplete: {source.source_key}"
        )


async def _authorize_submitted_evidence_batch(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    submissions: Sequence[SubmittedEvidence],
) -> dict[int, EvidenceClaim]:
    document_ids = {
        item.source_document_id
        for item in submissions
        if item.source_document_id is not None
    }
    rows = (
        list(
            (
                await session.execute(
                    select(FitmentSourceDocument, FitmentSource)
                    .join(
                        FitmentSource,
                        FitmentSource.id == FitmentSourceDocument.source_id,
                    )
                    .where(
                        FitmentSourceDocument.id.in_(document_ids),
                        or_(
                            FitmentSource.workspace_id.is_(None),
                            FitmentSource.workspace_id == workspace_id,
                        ),
                    )
                )
            ).all()
        )
        if document_ids
        else []
    )
    documents = {document.id: (document, source) for document, source in rows}
    missing = document_ids - set(documents)
    if missing:
        raise FitmentNotFoundError(
            "source documents not found: "
            + ", ".join(sorted(str(item) for item in missing))
        )
    # Source quality is claim-type specific.  A source can be excellent for
    # article/OE identity and weak for installation position, so the newest
    # append-only Beta posterior must be selected per (source, feature).  The
    # database base reliability remains a cold-start fallback only.
    source_ids = {source.id for _, source in rows}
    latest_reliability: dict[tuple[UUID, str], Decimal] = {}
    if source_ids:
        snapshots = list(
            (
                await session.scalars(
                    select(FitmentSourceReliabilitySnapshot)
                    .where(FitmentSourceReliabilitySnapshot.source_id.in_(source_ids))
                    .order_by(
                        FitmentSourceReliabilitySnapshot.source_id,
                        FitmentSourceReliabilitySnapshot.claim_type,
                        FitmentSourceReliabilitySnapshot.created_at.desc(),
                        FitmentSourceReliabilitySnapshot.id.desc(),
                    )
                )
            ).all()
        )
        for snapshot in snapshots:
            latest_reliability.setdefault(
                (snapshot.source_id, snapshot.claim_type),
                Decimal(snapshot.reliability),
            )
    result: dict[int, EvidenceClaim] = {}
    now = datetime.now(UTC)
    for submitted in submissions:
        claim = submitted.claim
        document_id = submitted.source_document_id
        if document_id is None:
            if claim.source_type in _ALLOWED_UNREGISTERED_SOURCE_TYPES:
                result[id(submitted)] = replace(
                    claim,
                    source_tier=SourceTier.D,
                    source_reliability=min(claim.source_reliability, Decimal("0.55")),
                    statement_status=(
                        StatementStatus.INFERENCE
                        if claim.value != 0
                        else StatementStatus.UNKNOWN
                    ),
                )
                continue
            if (
                claim.source_type == "test_fixture"
                and get_settings().environment.strip().casefold() == "e2e"
            ):
                result[id(submitted)] = claim
                continue
            raise FitmentSourceBlocked(
                "external evidence must reference a registered source document"
            )
        document, source = documents[document_id]
        _require_source_access(source)
        expires_at = document.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                raise FitmentSourceBlocked(f"source document expired: {document.id}")
        result[id(submitted)] = replace(
            claim,
            source_id=source.source_key,
            source_type=source.source_type,
            source_tier=SourceTier(source.source_tier),
            source_reliability=latest_reliability.get(
                (source.id, claim.feature.value),
                Decimal(source.base_reliability),
            ),
            source_url=document.source_url,
            source_document_sha256=document.content_sha256,
        )
    return result


async def _current_seller_relation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    marketplace: str,
    seller_external_id: str,
    include_owned_store_fallback: bool = True,
) -> tuple[SellerRelationRecord | None, SellerRelation]:
    record = await session.scalar(
        select(SellerRelationRecord)
        .where(
            SellerRelationRecord.workspace_id == workspace_id,
            SellerRelationRecord.marketplace == marketplace.casefold(),
            SellerRelationRecord.seller_external_id == seller_external_id,
        )
        .order_by(
            SellerRelationRecord.created_at.desc(), SellerRelationRecord.id.desc()
        )
        .limit(1)
    )
    if record is not None:
        return record, SellerRelation(record.relation)
    if include_owned_store_fallback:
        owned = await session.scalar(
            select(MarketplaceStore.id)
            .join(WorkspaceStore, WorkspaceStore.store_id == MarketplaceStore.id)
            .where(
                WorkspaceStore.workspace_id == workspace_id,
                WorkspaceStore.kind == StoreKind.owned,
                MarketplaceStore.marketplace == marketplace.casefold(),
                MarketplaceStore.external_id == seller_external_id,
            )
            .limit(1)
        )
        if owned is not None:
            return None, SellerRelation.OWN
    return None, SellerRelation.UNKNOWN


async def _current_seller_relations(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    marketplace: str,
    seller_external_ids: set[str],
) -> dict[str, tuple[SellerRelationRecord | None, SellerRelation]]:
    if not seller_external_ids:
        return {}
    records = list(
        (
            await session.scalars(
                select(SellerRelationRecord)
                .where(
                    SellerRelationRecord.workspace_id == workspace_id,
                    SellerRelationRecord.marketplace == marketplace.casefold(),
                    SellerRelationRecord.seller_external_id.in_(seller_external_ids),
                )
                .order_by(
                    SellerRelationRecord.seller_external_id,
                    SellerRelationRecord.created_at.desc(),
                    SellerRelationRecord.id.desc(),
                )
            )
        ).all()
    )
    result: dict[str, tuple[SellerRelationRecord | None, SellerRelation]] = {}
    for record in records:
        result.setdefault(
            record.seller_external_id,
            (record, SellerRelation(record.relation)),
        )
    unresolved = seller_external_ids - set(result)
    if unresolved:
        owned_ids = set(
            (
                await session.scalars(
                    select(MarketplaceStore.external_id)
                    .join(
                        WorkspaceStore,
                        WorkspaceStore.store_id == MarketplaceStore.id,
                    )
                    .where(
                        WorkspaceStore.workspace_id == workspace_id,
                        WorkspaceStore.kind == StoreKind.owned,
                        MarketplaceStore.marketplace == marketplace.casefold(),
                        MarketplaceStore.external_id.in_(unresolved),
                    )
                )
            ).all()
        )
        for seller_id in owned_ids:
            result[seller_id] = (None, SellerRelation.OWN)
    for seller_id in seller_external_ids - set(result):
        result[seller_id] = (None, SellerRelation.UNKNOWN)
    return result


async def _current_tier_classifications(
    session: AsyncSession, observation_ids: set[UUID]
) -> dict[UUID, ObservationTierClassification]:
    if not observation_ids:
        return {}
    records = list(
        (
            await session.scalars(
                select(ObservationTierClassification)
                .where(
                    ObservationTierClassification.market_observation_id.in_(
                        observation_ids
                    )
                )
                .order_by(
                    ObservationTierClassification.market_observation_id,
                    ObservationTierClassification.classified_at.desc(),
                    ObservationTierClassification.id.desc(),
                )
            )
        ).all()
    )
    result: dict[UUID, ObservationTierClassification] = {}
    for record in records:
        result.setdefault(record.market_observation_id, record)
    return result


def _authoritative_commercial_context(
    *,
    observation: MarketObservation,
    submitted: CommercialContext,
    relation: SellerRelation,
    classification: ObservationTierClassification | None,
) -> CommercialContext:
    try:
        tier = ProductTier(classification.tier) if classification else submitted.tier
    except ValueError:
        tier = ProductTier.UNKNOWN
    if classification is not None and classification.is_owned:
        relation = SellerRelation.OWN
    condition = {
        "NEW": Condition.NEW,
        "USED_OR_REFURBISHED": Condition.USED,
        "CONFLICT": Condition.UNKNOWN,
        "UNKNOWN": Condition.UNKNOWN,
    }.get(observation.condition_state, Condition.UNKNOWN)
    availability = (
        Availability.IN_STOCK
        if observation.is_available is True
        else Availability.OUT_OF_STOCK
        if observation.is_available is False
        else Availability.UNKNOWN
    )
    return replace(
        submitted,
        condition=condition,
        currency=observation.currency,
        tier=tier,
        availability=availability,
        seller_relation=relation,
        stable_seller_id_verified=bool(
            observation.seller_id and observation.seller_identity_verified
        ),
        seller_group_id=f"prom:{observation.seller_id}",
    )


def _commercial_context_after_unit_normalization(
    context: CommercialContext,
    *,
    status: PriceUnitStatus,
) -> CommercialContext:
    """Expose a comparable per-piece boundary only after deterministic proof.

    Pair and axle-set offers are commercially different at the listing level,
    but become comparable after their price has been divided by the proven
    quantity.  Unknown and contradictory unit declarations stay unchanged so
    the downstream policy still abstains or rejects them.
    """

    if status in {
        PriceUnitStatus.VERIFIED_PIECE,
        PriceUnitStatus.NORMALIZED_PAIR,
        PriceUnitStatus.NORMALIZED_AXLE_SET,
        PriceUnitStatus.NORMALIZED_KIT,
    }:
        return replace(context, package_quantity=Decimal("1"), unit_basis="piece")
    return context


def _claims_from_observation(
    observation: MarketObservation,
) -> tuple[EvidenceClaim, ...]:
    payload = observation.comparison_evidence
    dimensions = payload.get("dimensions", {}) if isinstance(payload, dict) else {}
    mappings = {
        "fitment": FitmentFeature.VEHICLE_MAKE_MODEL,
        "vehicle_generation": FitmentFeature.GENERATION,
        "year_interval": FitmentFeature.YEAR_OVERLAP,
        "engine": FitmentFeature.ENGINE,
        "body_variant": FitmentFeature.BODY,
        "side": FitmentFeature.SIDE,
        "position": FitmentFeature.AXLE,
    }
    values: dict[FitmentFeature, tuple[Decimal, str]] = {}
    if observation.oe_verification_status == "VERIFIED_EXACT":
        values[FitmentFeature.OE_EXACT] = (Decimal("1"), "verified candidate OE")
    elif observation.oe_verification_status == "VERIFIED_CROSS":
        values[FitmentFeature.CROSS_CONFIRMED] = (
            Decimal("1"),
            "verified cross snapshot",
        )
    for dimension_name, feature in mappings.items():
        dimension = dimensions.get(dimension_name)
        if not isinstance(dimension, dict):
            continue
        state = str(dimension.get("state") or "UNKNOWN")
        value = (
            Decimal("1")
            if state == "MATCH"
            else Decimal("-1")
            if state == "CONFLICT"
            else Decimal("0")
        )
        values[feature] = (value, state)
    if not values:
        return ()
    reliability = min(Decimal(str(observation.source_confidence or 0)), Decimal("0.55"))
    if not observation.source_provenance_verified:
        reliability = Decimal("0")
    freshness = _observation_freshness(observation)
    claims: list[EvidenceClaim] = []
    for feature, (value, label) in values.items():
        claims.append(
            EvidenceClaim(
                evidence_id=f"observation:{observation.id}:{feature.value}",
                feature=feature,
                value=value,
                source_id=f"prom:{observation.source_listing_id}",
                source_type="prom_public",
                source_tier=SourceTier.D,
                source_reliability=reliability,
                extraction_confidence=Decimal("0.90"),
                independence_factor=Decimal("1"),
                freshness_factor=freshness,
                correlation_group=f"prom-capture:{observation.raw_capture_id}",
                polarity=(
                    EvidencePolarity.SUPPORTS
                    if value > 0
                    else EvidencePolarity.CONTRADICTS
                    if value < 0
                    else EvidencePolarity.UNKNOWN
                ),
                statement_status=(
                    StatementStatus.INFERENCE if value != 0 else StatementStatus.UNKNOWN
                ),
                claim_value={
                    "observation_id": str(observation.id),
                    "dimension_state": label,
                    "semantics": "marketplace_declaration_not_authoritative_fitment_proof",
                },
                retrieved_at=observation.observed_at,
                source_url=observation.url or None,
                source_document_sha256=None,
            )
        )
    return tuple(claims)


def _observation_freshness(observation: MarketObservation) -> Decimal:
    observed_at = observation.observed_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    age_hours = max(
        Decimal("0"),
        Decimal(str((datetime.now(UTC) - observed_at).total_seconds()))
        / Decimal("3600"),
    )
    if age_hours <= 24:
        return Decimal("1")
    if age_hours <= 24 * 7:
        return Decimal("0.95")
    if age_hours <= 24 * 30:
        return Decimal("0.80")
    return Decimal("0.60")


def _source_quality(claims: Sequence[EvidenceClaim]) -> Decimal:
    if not claims:
        return Decimal("0")
    grouped: dict[str, Decimal] = {}
    for claim in claims:
        grouped[claim.correlation_group] = max(
            grouped.get(claim.correlation_group, Decimal("0")),
            claim.effective_weight,
        )
    return (sum(grouped.values(), Decimal("0")) / Decimal(len(grouped))).quantize(
        Decimal("0.0001")
    )


def _deduplicate_claims(claims: Iterable[EvidenceClaim]) -> tuple[EvidenceClaim, ...]:
    unique: dict[str, EvidenceClaim] = {}
    for claim in claims:
        current = unique.get(claim.evidence_id)
        if current is not None and current != claim:
            raise FitmentIntelligenceError(
                f"evidence id reused with different content: {claim.evidence_id}"
            )
        unique[claim.evidence_id] = claim
    return tuple(sorted(unique.values(), key=lambda item: item.evidence_id))


def _normalize_brand(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold().strip()
        if character.isalnum()
    )


def _canonical_domain(value: str) -> str:
    candidate = value.strip()
    parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FitmentIntelligenceError("source domain/URL must be HTTP(S)")
    return parsed.hostname.casefold().rstrip(".")


def _audit_event(
    *,
    workspace_id: UUID,
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor_user_id: UUID | None,
    payload: Mapping[str, Any],
) -> FitmentAuditEvent:
    normalized_payload = _json_safe(payload)
    return FitmentAuditEvent(
        workspace_id=workspace_id,
        event_key=_sha256(
            {
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "actor_user_id": actor_user_id,
                "payload": normalized_payload,
            }
        ),
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        payload=normalized_payload,
    )


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return value


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "AnalysisSpec",
    "CandidateAnalysisSpec",
    "FITMENT_SOURCE_POLICY_VERSION",
    "FitmentIdempotencyConflict",
    "FitmentIntelligenceError",
    "FitmentNotFoundError",
    "FitmentSourceBlocked",
    "SubmittedEvidence",
    "add_fitment_review",
    "add_seller_relation",
    "create_fitment_analysis",
    "enqueue_fitment_analysis",
    "fail_fitment_analysis_job",
    "fitment_metrics",
    "get_fitment_analysis",
    "list_fitment_candidates",
    "list_source_capabilities",
    "list_source_reliability",
    "process_fitment_analysis_job",
    "record_cross_reference",
    "register_fitment_source",
    "register_source_document",
    "retry_fitment_analysis",
    "search_cross_references",
]
