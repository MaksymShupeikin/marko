"""Freeze authoritative fitment crosses into a pricing-run identity snapshot.

``fitment_cross_references`` already records source- or human-confirmed pairs,
but pricing acquisition historically read only ``catalog_identity_links``.  A
confirmed Avto.pro/Exist.ua relation could therefore be visible to an operator
and still have no effect on candidate discovery.

This module closes that read gap without turning the fitment table into a
second mutable pricing input.  Only an effective leaf record with persisted
evidence can be copied into the same hash-bound start snapshot as the customer
reference graph.  Context-limited relations, ambiguous catalog fan-out, stale
method versions, weak confidence and any live rejection/conflict all fail
closed.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    FitmentAnalysis,
    FitmentCandidateAssessment,
    FitmentEvidenceClaim,
    FitmentHumanReview,
    FitmentSource,
    FitmentSourceDocument,
)
from marko.services.catalog_identity_safety import (
    catalog_identity_pair_has_safe_shape,
    is_internal_catalog_code,
)
from marko.services.fitment_intelligence import FITMENT_CROSS_METHOD_VERSION
from marko.services.fitment_source_routing import (
    FITMENT_CROSS_MIN_CONFIDENCE,
    FITMENT_CROSS_MIN_DIRECTNESS,
    FITMENT_CROSS_MIN_EXTRACTION_CONFIDENCE,
    FITMENT_CROSS_MIN_INDEPENDENCE,
    FITMENT_CROSS_MIN_SOURCE_RELIABILITY,
    claim_names_both_numbers,
    source_access_policy_allows,
    source_claim_quality_allows,
    source_confirmation_policy_allows,
    source_url_matches_domain,
)
from metis.pricing.crosses import normalize_cross_oem

FITMENT_CROSS_IDENTITY_KIND = "FITMENT_CROSS_REFERENCE"
FITMENT_CROSS_EXTRACTION_METHOD = "FITMENT_CROSS_REFERENCE"
_CONFIRMED_STATUSES = frozenset({"source_confirmed", "human_confirmed"})
_BLOCKING_STATUSES = frozenset(
    {"human_rejected", "conflicting", "deprecated", "superseded"}
)
_IDENTITY_FEATURES = frozenset({"oe_exact", "oe_supersession", "cross_confirmed"})
_POSITIVE_HUMAN_DECISION = "mark_candidate_compatible"
_NEGATIVE_HUMAN_DECISION = "mark_candidate_incompatible"


class FitmentCrossBridgeError(ValueError):
    """A purported frozen fitment cross is not safe to use for acquisition."""


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise FitmentCrossBridgeError(f"{field} must be a non-negative integer")
    if isinstance(value, float) and not value.is_integer():
        raise FitmentCrossBridgeError(f"{field} must be a non-negative integer")
    if isinstance(value, Decimal) and value != value.to_integral_value():
        raise FitmentCrossBridgeError(f"{field} must be a non-negative integer")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or not stripped.isascii() or not stripped.isdecimal():
            raise FitmentCrossBridgeError(f"{field} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise FitmentCrossBridgeError(
            f"{field} must be a non-negative integer"
        ) from exc
    if parsed < 0:
        raise FitmentCrossBridgeError(f"{field} must be a non-negative integer")
    return parsed


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _source_policy_is_approved(source: FitmentSource) -> bool:
    return source_access_policy_allows(
        access_status=source.access_status,
        access_reference=source.access_reference,
        robots_checked=source.robots_checked,
        terms_checked=source.terms_checked,
    )


def fitment_cross_authority_sha256(authority: Mapping[str, Any]) -> str:
    return _canonical_sha256(
        {key: value for key, value in authority.items() if key != "authority_sha256"}
    )


def _validate_authority_snapshot(
    raw: Mapping[str, Any],
    *,
    record: Any,
) -> dict[str, Any]:
    authority = dict(raw)
    record_id = str(UUID(str(getattr(record, "id"))))
    if _text(authority.get("fitment_cross_reference_id")) != record_id:
        raise FitmentCrossBridgeError("cross authority belongs to another record")
    article = normalize_cross_oem(_text(getattr(record, "normalized_article", None)))
    oe = normalize_cross_oem(_text(getattr(record, "normalized_oe", None)))
    if authority.get("normalized_pair") != [article, oe]:
        raise FitmentCrossBridgeError("cross authority pair does not match the record")
    evidence_ids = sorted(
        {
            _text(value)
            for value in (getattr(record, "evidence_ids", None) or ())
            if _text(value)
        }
    )
    if authority.get("evidence_claim_ids") != evidence_ids:
        raise FitmentCrossBridgeError("cross authority evidence set is incomplete")
    assessment_ids = authority.get("assessment_ids")
    if not isinstance(assessment_ids, list) or not assessment_ids:
        raise FitmentCrossBridgeError("cross authority has no assessment binding")
    source_evidence = authority.get("source_evidence")
    if not isinstance(source_evidence, list):
        raise FitmentCrossBridgeError("cross authority source evidence is invalid")
    review_ids = authority.get("human_review_ids")
    if not isinstance(review_ids, list):
        raise FitmentCrossBridgeError("cross authority human reviews are invalid")
    source_group_count = _non_negative_int(
        authority.get("source_group_count"), field="source_group_count"
    )
    recorded_source_count = _non_negative_int(
        getattr(record, "source_count", None), field="source_count"
    )
    if source_group_count != recorded_source_count:
        raise FitmentCrossBridgeError("cross authority source count changed")
    status = _text(getattr(record, "relation_status", None))
    if status == "source_confirmed" and not source_evidence:
        raise FitmentCrossBridgeError("source-confirmed cross has no live source chain")
    if status == "human_confirmed" and not review_ids:
        raise FitmentCrossBridgeError("human-confirmed cross has no current review")
    expected = _text(authority.get("authority_sha256"))
    if expected != fitment_cross_authority_sha256(authority):
        raise FitmentCrossBridgeError("cross authority hash mismatch")
    return authority


async def load_fitment_cross_authorities(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    records: Sequence[Any],
    now: datetime | None = None,
) -> dict[UUID, dict[str, Any]]:
    """Re-prove every usable cross from append-only primary evidence.

    A cross row is a cached conclusion, not authority by itself.  This loader
    rejects orphan claims, pair rebinding, expired documents, superseded source
    policy, weak or correlated source evidence, and a later incompatible human
    verdict before a pricing run can widen its acquisition query.
    """

    checked_at = _aware(now or datetime.now(UTC))
    evidence_ids_by_record: dict[UUID, tuple[UUID, ...]] = {}
    all_claim_ids: set[UUID] = set()
    for record in records:
        if getattr(record, "id", None) is None:
            continue
        try:
            record_id = UUID(str(record.id))
            claim_ids = tuple(
                sorted(
                    {UUID(_text(value)) for value in (record.evidence_ids or ())},
                    key=str,
                )
            )
        except (AttributeError, TypeError, ValueError):
            continue
        if not claim_ids:
            continue
        evidence_ids_by_record[record_id] = claim_ids
        all_claim_ids.update(claim_ids)
    if not all_claim_ids:
        return {}

    claim_rows = list(
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
                    FitmentEvidenceClaim.id.in_(all_claim_ids),
                    FitmentAnalysis.workspace_id == workspace_id,
                )
            )
        ).all()
    )
    rows_by_claim = {
        claim.id: (claim, assessment, analysis)
        for claim, assessment, analysis in claim_rows
    }
    assessment_ids = {assessment.id for _, assessment, _ in claim_rows}
    reviews = (
        list(
            (
                await session.scalars(
                    select(FitmentHumanReview)
                    .where(
                        FitmentHumanReview.workspace_id == workspace_id,
                        FitmentHumanReview.assessment_id.in_(assessment_ids),
                    )
                    .order_by(
                        FitmentHumanReview.assessment_id,
                        FitmentHumanReview.created_at,
                        FitmentHumanReview.id,
                    )
                )
            ).all()
        )
        if assessment_ids
        else []
    )
    latest_review: dict[UUID, FitmentHumanReview] = {}
    for review in reviews:
        latest_review[review.assessment_id] = review

    document_ids = {
        claim.source_document_id
        for claim, _, _ in claim_rows
        if claim.source_document_id is not None
    }
    document_rows = (
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
    documents = {document.id: (document, source) for document, source in document_rows}
    source_keys = {source.source_key for _, source in document_rows}
    policy_rows = (
        list(
            (
                await session.scalars(
                    select(FitmentSource).where(
                        FitmentSource.source_key.in_(source_keys),
                        or_(
                            FitmentSource.workspace_id.is_(None),
                            FitmentSource.workspace_id == workspace_id,
                        ),
                    )
                )
            ).all()
        )
        if source_keys
        else []
    )
    current_policy: dict[str, FitmentSource] = {}
    for source in policy_rows:
        previous = current_policy.get(source.source_key)
        candidate_key = (
            source.workspace_id == workspace_id,
            _aware(source.reviewed_at),
            _aware(source.created_at),
            str(source.id),
        )
        previous_key = (
            (
                previous.workspace_id == workspace_id,
                _aware(previous.reviewed_at),
                _aware(previous.created_at),
                str(previous.id),
            )
            if previous is not None
            else None
        )
        if previous_key is None or candidate_key > previous_key:
            current_policy[source.source_key] = source

    authorities: dict[UUID, dict[str, Any]] = {}
    for record in records:
        if getattr(record, "id", None) is None:
            continue
        record_id = UUID(str(record.id))
        claim_ids = evidence_ids_by_record.get(record_id)
        if not claim_ids or any(
            claim_id not in rows_by_claim for claim_id in claim_ids
        ):
            continue
        article = normalize_cross_oem(_text(record.normalized_article))
        oe = normalize_cross_oem(_text(record.normalized_oe))
        if not catalog_identity_pair_has_safe_shape(article, oe):
            continue
        claims: list[FitmentEvidenceClaim] = []
        bound_rows: list[
            tuple[FitmentEvidenceClaim, FitmentCandidateAssessment, FitmentAnalysis]
        ] = []
        bound_assessment_ids: set[UUID] = set()
        valid = True
        for claim_id in claim_ids:
            claim, assessment, analysis = rows_by_claim[claim_id]
            candidate_article = normalize_cross_oem(
                _text((assessment.candidate_identity or {}).get("manufacturer_article"))
            )
            target_oes = {
                normalized
                for value in (analysis.target_identity or {}).get("oe_numbers", ())
                if (normalized := normalize_cross_oem(_text(value)))
            }
            assessment_evidence_ids = {
                _text(value) for value in (assessment.evidence_ids or ())
            }
            if (
                candidate_article != article
                or oe not in target_oes
                or str(claim.id) not in assessment_evidence_ids
                or claim.feature not in _IDENTITY_FEATURES
                or Decimal(claim.evidence_value) <= 0
                or claim.polarity != "supports"
                or claim.statement_status not in {"FACT", "INFERENCE"}
                or not _text(claim.correlation_group)
            ):
                valid = False
                break
            claims.append(claim)
            bound_rows.append((claim, assessment, analysis))
            bound_assessment_ids.add(assessment.id)
        if not valid:
            continue

        current_reviews = [
            latest_review[assessment_id]
            for assessment_id in sorted(bound_assessment_ids, key=str)
            if assessment_id in latest_review
        ]
        if any(
            review.decision == _NEGATIVE_HUMAN_DECISION for review in current_reviews
        ):
            continue
        status = _text(record.relation_status)
        if status == "human_confirmed" and not any(
            review.decision == _POSITIVE_HUMAN_DECISION for review in current_reviews
        ):
            continue

        source_evidence: list[dict[str, Any]] = []
        if status == "source_confirmed":
            confirmation_groups: list[tuple[str, str]] = []
            for claim, assessment, analysis in bound_rows:
                if (
                    not source_claim_quality_allows(
                        statement_status=claim.statement_status,
                        evidence_value=claim.evidence_value,
                        polarity=claim.polarity,
                        source_reliability=claim.source_reliability,
                        extraction_confidence=claim.extraction_confidence,
                        directness=claim.directness,
                        independence_factor=claim.independence_factor,
                    )
                    or not claim_names_both_numbers(
                        claim_value=claim.claim_value,
                        raw_fragment=claim.raw_fragment,
                        article=article,
                        oe=oe,
                    )
                    or analysis.status not in {"completed", "partial"}
                    or assessment.compatibility_status
                    not in {"confirmed_compatible", "likely_compatible"}
                    or not assessment.authoritative_confirmation
                    or bool(assessment.hard_rejections)
                    or claim.source_document_id is None
                ):
                    valid = False
                    break
                document_source = documents.get(claim.source_document_id)
                if document_source is None:
                    valid = False
                    break
                document, source = document_source
                policy = current_policy.get(source.source_key)
                expires_at = (
                    _aware(document.expires_at) if document.expires_at else None
                )
                if (
                    policy is None
                    or not _source_policy_is_approved(policy)
                    or (expires_at is not None and expires_at <= checked_at)
                    or claim.source_document_sha256 != document.content_sha256
                    or _text(claim.source_url) != _text(document.source_url)
                    or claim.source_external_id != source.source_key
                    or claim.source_type != source.source_type
                    or claim.source_tier != source.source_tier
                    or not source_url_matches_domain(
                        document.source_url, source.domain
                    )
                    or claim.source_type != policy.source_type
                    or claim.source_tier != policy.source_tier
                    or not source_url_matches_domain(
                        document.source_url, policy.domain
                    )
                    or not (
                        _text(document.content_locator) or _text(claim.raw_fragment)
                    )
                ):
                    valid = False
                    break
                group = _text(claim.correlation_group)
                confirmation_groups.append((claim.source_tier, group))
                source_evidence.append(
                    {
                        "claim_id": str(claim.id),
                        "correlation_group": group,
                        "source_document_id": str(document.id),
                        "source_document_sha256": document.content_sha256,
                        "source_id": str(source.id),
                        "source_key": source.source_key,
                        "source_tier": source.source_tier,
                        "active_policy_id": str(policy.id),
                        "active_policy_version": policy.policy_version,
                        "access_status": policy.access_status,
                        "retrieved_at": _aware(document.retrieved_at).isoformat(),
                        "expires_at": expires_at.isoformat() if expires_at else None,
                    }
                )
            if not valid or not source_confirmation_policy_allows(confirmation_groups):
                continue

        correlation_groups = sorted(
            {_text(claim.correlation_group) for claim in claims}
        )
        try:
            if len(correlation_groups) != _non_negative_int(
                record.source_count, field="source_count"
            ):
                continue
        except FitmentCrossBridgeError:
            continue
        authority: dict[str, Any] = {
            "fitment_cross_reference_id": str(record_id),
            "normalized_pair": [article, oe],
            "evidence_claim_ids": sorted(str(value) for value in claim_ids),
            "assessment_ids": sorted(str(value) for value in bound_assessment_ids),
            "source_group_count": len(correlation_groups),
            "source_evidence": sorted(
                source_evidence,
                key=lambda value: (value["claim_id"], value["source_document_id"]),
            ),
            "human_review_ids": sorted(
                str(review.id)
                for review in current_reviews
                if review.decision == _POSITIVE_HUMAN_DECISION
            ),
            "checked_at": checked_at.isoformat(),
        }
        authority["authority_sha256"] = fitment_cross_authority_sha256(authority)
        try:
            authorities[record_id] = _validate_authority_snapshot(
                authority, record=record
            )
        except FitmentCrossBridgeError:
            continue
    return authorities


def _record_is_confirmation_eligible(
    record: Any,
    *,
    authority: Mapping[str, Any] | None,
) -> bool:
    if authority is None:
        return False
    try:
        _validate_authority_snapshot(authority, record=record)
    except FitmentCrossBridgeError:
        return False
    status = _text(getattr(record, "relation_status", None))
    if status not in _CONFIRMED_STATUSES:
        return False
    if _text(getattr(record, "method_version", None)) != FITMENT_CROSS_METHOD_VERSION:
        return False
    if getattr(record, "installation_position", None) or getattr(
        record, "vehicle_key", None
    ):
        # The catalog start snapshot does not yet carry enough structured
        # fitment to prove this narrower relation applies to this exact row.
        return False
    try:
        confidence = Decimal(str(getattr(record, "confidence", "")))
    except (InvalidOperation, ValueError):
        return False
    if confidence < FITMENT_CROSS_MIN_CONFIDENCE or confidence > 1:
        return False
    evidence_ids = {
        _text(value) for value in (getattr(record, "evidence_ids", None) or ())
    }
    evidence_ids.discard("")
    if not evidence_ids:
        return False
    try:
        source_count = _non_negative_int(
            getattr(record, "source_count", None), field="source_count"
        )
        human_count = _non_negative_int(
            getattr(record, "human_feedback_count", None),
            field="human_feedback_count",
        )
    except FitmentCrossBridgeError:
        return False
    if status == "source_confirmed" and source_count < 1:
        return False
    return not (status == "human_confirmed" and human_count < 1)


def _record_pair(record: Any) -> tuple[str, str]:
    article = normalize_cross_oem(_text(getattr(record, "normalized_article", None)))
    oe = normalize_cross_oem(_text(getattr(record, "normalized_oe", None)))
    if not catalog_identity_pair_has_safe_shape(article, oe):
        return "", ""
    return (article, oe) if article <= oe else (oe, article)


def _record_snapshot(
    record: Any,
    *,
    catalog_item_id: UUID,
    query: str,
    extracted: str,
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    evidence_ids = sorted(
        {
            _text(value)
            for value in (getattr(record, "evidence_ids", None) or ())
            if _text(value)
        }
    )
    status = _text(getattr(record, "relation_status", None))
    confidence = str(Decimal(str(getattr(record, "confidence", "0"))))
    source_count = _non_negative_int(
        getattr(record, "source_count", None), field="source_count"
    )
    human_count = _non_negative_int(
        getattr(record, "human_feedback_count", None),
        field="human_feedback_count",
    )
    record_id = str(UUID(str(getattr(record, "id"))))
    last_verified = getattr(record, "last_verified_at", None)
    if not isinstance(last_verified, datetime):
        raise FitmentCrossBridgeError("last_verified_at must be a datetime")
    details = {
        "relation_status": status,
        "confidence": confidence,
        "source_count": source_count,
        "human_feedback_count": human_count,
        "evidence_ids": evidence_ids,
        "last_verified_at": last_verified.isoformat(),
        "installation_position": None,
        "vehicle_key": None,
        "authority": dict(authority),
    }
    snapshot: dict[str, Any] = {
        "identity_evidence_kind": FITMENT_CROSS_IDENTITY_KIND,
        "fitment_cross_reference_id": record_id,
        "catalog_item_id": str(catalog_item_id),
        "our_oem_norm": query,
        "extracted_oem_norm": extracted,
        "extracted_raw": _text(getattr(record, "article", None))
        if extracted
        == normalize_cross_oem(_text(getattr(record, "normalized_article", None)))
        else _text(getattr(record, "oe", None)),
        "raw_context": (
            f"fitment_cross_reference:{record_id}:"
            f"{_text(getattr(record, 'brand', None))}:"
            f"{_text(getattr(record, 'article', None))}->"
            f"{_text(getattr(record, 'oe', None))}"
        ),
        "extraction_method": FITMENT_CROSS_EXTRACTION_METHOD,
        "validation_status": "CONFIRMED",
        "anomaly": None,
        "corroborating_sources": [FITMENT_CROSS_EXTRACTION_METHOD],
        "validation_details": details,
        "method_version": FITMENT_CROSS_METHOD_VERSION,
    }
    snapshot["config_sha256"] = fitment_cross_snapshot_sha256(snapshot)
    return snapshot


def fitment_cross_snapshot_sha256(snapshot: Mapping[str, Any]) -> str:
    """Fingerprint every byte that gives a frozen fitment cross authority."""

    return _canonical_sha256(
        {key: value for key, value in snapshot.items() if key != "config_sha256"}
    )


def validate_fitment_cross_snapshot(
    raw: Mapping[str, Any],
    *,
    catalog_item_id: UUID,
    customer_query: str,
) -> dict[str, Any]:
    """Re-check a hand-built or deserialized snapshot before run persistence."""

    snapshot = dict(raw)
    if snapshot.get("identity_evidence_kind") != FITMENT_CROSS_IDENTITY_KIND:
        raise FitmentCrossBridgeError("unknown identity evidence kind")
    if snapshot.get("validation_status") != "CONFIRMED" or snapshot.get("anomaly"):
        raise FitmentCrossBridgeError("fitment cross is not confirmed")
    if snapshot.get("extraction_method") != FITMENT_CROSS_EXTRACTION_METHOD:
        raise FitmentCrossBridgeError("fitment cross extraction method is invalid")
    if snapshot.get("method_version") != FITMENT_CROSS_METHOD_VERSION:
        raise FitmentCrossBridgeError("fitment cross method version is stale")
    if _text(snapshot.get("catalog_item_id")) != str(catalog_item_id):
        raise FitmentCrossBridgeError("fitment cross belongs to another catalog item")
    try:
        UUID(_text(snapshot.get("fitment_cross_reference_id")))
    except ValueError as exc:
        raise FitmentCrossBridgeError("fitment cross reference id is invalid") from exc

    query = normalize_cross_oem(customer_query)
    our_oem = normalize_cross_oem(_text(snapshot.get("our_oem_norm")))
    extracted = normalize_cross_oem(_text(snapshot.get("extracted_oem_norm")))
    if not query or is_internal_catalog_code(query) or our_oem != query:
        raise FitmentCrossBridgeError(
            "fitment cross is not bound to the customer query"
        )
    if not catalog_identity_pair_has_safe_shape(our_oem, extracted):
        raise FitmentCrossBridgeError("fitment cross pair is private or malformed")

    details = snapshot.get("validation_details")
    if not isinstance(details, Mapping):
        raise FitmentCrossBridgeError("fitment cross validation details are missing")
    status = _text(details.get("relation_status"))
    if status not in _CONFIRMED_STATUSES:
        raise FitmentCrossBridgeError("fitment cross relation status is not confirmed")
    try:
        confidence = Decimal(_text(details.get("confidence")))
    except InvalidOperation as exc:
        raise FitmentCrossBridgeError("fitment cross confidence is invalid") from exc
    if confidence < FITMENT_CROSS_MIN_CONFIDENCE or confidence > 1:
        raise FitmentCrossBridgeError("fitment cross confidence is below the gate")
    source_count = _non_negative_int(details.get("source_count"), field="source_count")
    human_count = _non_negative_int(
        details.get("human_feedback_count"), field="human_feedback_count"
    )
    evidence_ids = details.get("evidence_ids")
    if (
        not isinstance(evidence_ids, list)
        or not evidence_ids
        or any(not _text(value) for value in evidence_ids)
    ):
        raise FitmentCrossBridgeError("fitment cross evidence ids are missing")
    if status == "source_confirmed" and source_count < 1:
        raise FitmentCrossBridgeError("source-confirmed cross has no source evidence")
    if status == "human_confirmed" and human_count < 1:
        raise FitmentCrossBridgeError("human-confirmed cross has no human feedback")
    if details.get("installation_position") or details.get("vehicle_key"):
        raise FitmentCrossBridgeError("context-limited cross cannot widen globally")
    authority = details.get("authority")
    if not isinstance(authority, Mapping):
        raise FitmentCrossBridgeError("fitment cross authority is missing")
    normalized_pair = authority.get("normalized_pair")
    if not isinstance(normalized_pair, list) or len(normalized_pair) != 2:
        raise FitmentCrossBridgeError("fitment cross authority pair is invalid")
    _validate_authority_snapshot(
        authority,
        record=SimpleNamespace(
            id=snapshot.get("fitment_cross_reference_id"),
            normalized_article=normalized_pair[0],
            normalized_oe=normalized_pair[1],
            evidence_ids=evidence_ids,
            source_count=source_count,
            relation_status=status,
        ),
    )

    expected = _text(snapshot.get("config_sha256"))
    actual = fitment_cross_snapshot_sha256(snapshot)
    if expected != actual:
        raise FitmentCrossBridgeError("fitment cross snapshot hash mismatch")
    return snapshot


def fitment_cross_snapshots_by_candidate(
    *,
    candidate_queries: Mapping[UUID, str],
    records: Sequence[Any],
    authorities: Mapping[UUID, Mapping[str, Any]],
) -> dict[UUID, tuple[dict[str, Any], ...]]:
    """Map effective confirmed cross leaves to one unambiguous catalog row.

    ``candidate_queries`` deliberately contains one primary query per row.  A
    relation that touches only a secondary part number would require a second
    transitive hop, which this bridge refuses.
    """

    normalized_queries = {
        item_id: normalize_cross_oem(query)
        for item_id, query in candidate_queries.items()
        if normalize_cross_oem(query)
        and not is_internal_catalog_code(normalize_cross_oem(query))
    }
    owners: dict[str, set[UUID]] = defaultdict(set)
    for item_id, query in normalized_queries.items():
        owners[query].add(item_id)

    record_by_id = {
        UUID(str(record.id)): record
        for record in records
        if getattr(record, "id", None) is not None
    }
    superseded_ids = {
        UUID(str(record.supersedes_id))
        for record in records
        if getattr(record, "supersedes_id", None) is not None
    }
    active = [
        record
        for record_id, record in record_by_id.items()
        if record_id not in superseded_ids
    ]
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for record in active:
        pair = _record_pair(record)
        if pair != ("", ""):
            grouped[pair].append(record)

    snapshots: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for pair, leaves in grouped.items():
        statuses = {
            _text(getattr(record, "relation_status", None)) for record in leaves
        }
        if statuses & _BLOCKING_STATUSES:
            continue
        confirmations = [
            record
            for record in leaves
            if _record_is_confirmation_eligible(
                record,
                authority=authorities.get(UUID(str(record.id))),
            )
        ]
        if not confirmations:
            continue
        left, right = pair
        # A relation that touches two current catalog rows is fan-out, not a
        # safe one-hop enrichment.  This also blocks duplicate primary queries.
        pair_owners = owners.get(left, set()) | owners.get(right, set())
        if len(pair_owners) != 1:
            continue
        item_id = next(iter(pair_owners))
        query = normalized_queries[item_id]
        if query not in pair:
            continue
        extracted = right if query == left else left
        if owners.get(extracted, set()) - {item_id}:
            continue
        for record in sorted(confirmations, key=lambda item: str(item.id)):
            authority = _validate_authority_snapshot(
                authorities[UUID(str(record.id))],
                record=record,
            )
            snapshot = _record_snapshot(
                record,
                catalog_item_id=item_id,
                query=query,
                extracted=extracted,
                authority=authority,
            )
            validate_fitment_cross_snapshot(
                snapshot,
                catalog_item_id=item_id,
                customer_query=query,
            )
            snapshots[item_id].append(snapshot)

    return {
        item_id: tuple(
            sorted(
                values,
                key=lambda value: (
                    value["our_oem_norm"],
                    value["extracted_oem_norm"],
                    value["fitment_cross_reference_id"],
                ),
            )
        )
        for item_id, values in snapshots.items()
    }


__all__ = [
    "FITMENT_CROSS_EXTRACTION_METHOD",
    "FITMENT_CROSS_IDENTITY_KIND",
    "FITMENT_CROSS_MIN_DIRECTNESS",
    "FITMENT_CROSS_MIN_EXTRACTION_CONFIDENCE",
    "FITMENT_CROSS_MIN_INDEPENDENCE",
    "FITMENT_CROSS_MIN_CONFIDENCE",
    "FITMENT_CROSS_MIN_SOURCE_RELIABILITY",
    "FitmentCrossBridgeError",
    "fitment_cross_authority_sha256",
    "fitment_cross_snapshot_sha256",
    "fitment_cross_snapshots_by_candidate",
    "load_fitment_cross_authorities",
    "validate_fitment_cross_snapshot",
]
