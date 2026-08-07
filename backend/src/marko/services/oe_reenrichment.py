"""Bounded, network-free re-enrichment of retained market observations.

The job deliberately reuses the canonical offer identity service.  It never
uses ``search_oe_norm`` as candidate evidence and never performs HTTP calls.
Rows with deterministic data failures retain a persistent error code; unknown
exceptions abort the batch so they cannot become silent data loss.

Two properties this module is responsible for:

* it reads the **frozen** execution view of the catalog position, never the
  live ``CatalogItem`` row.  Re-running identity against a catalog edited after
  the run started would silently rewrite history under a different part number
  and category;
* it **reconstructs and revalidates** the persisted source assertion instead of
  discarding it.  Dropping it downgraded every marketplace-grouped offer to
  ``UNKNOWN`` on the next pass, which is a silent loss of verified identity;
  accepting it unchecked would let stale evidence promote a row forever.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from marko.infrastructure.db.models import (
    MarketObservation,
    ObservationTierClassification,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    ScrapeTarget,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.market_collection import (
    _acquisition_capture_binding,
    _candidate_raw_manifest,
    _detail_evidence_automatic_safe,
    _load_confirmed_crosses,
    _verified_capture_raw_evidence,
    resolve_bound_execution_item,
)
from marko.services.offer_identity import (
    IdentityNamespace,
    IDENTITY_NAMESPACE_VERSION,
    OE_EXTRACTOR_VERSION,
    ConfirmedCross,
    OeVerificationStatus,
    SourceAssertion,
    automatic_identity_evidence_sufficient,
    bind_oe_verification,
    evidence_items_to_dicts,
    extract_oe_evidence,
    extract_prom_motors_cross_proposals,
    customer_identity_namespace,
    namespace_bound_verification,
    namespace_identity_admission,
    verified_identity_namespace,
    verify_offer_identity,
)
from marko.services.offer_processing import (
    AcceptedCandidate,
    AcquisitionLineage,
    process_offer_candidate,
)
from marko.services.pricing_runs import (
    FrozenCatalogItem,
    PricingRunSnapshotError,
    customer_identity_query,
    load_run_execution_policy,
)
from marko.services.scraper_contract import ScrapeOutput, ScraperBoundaryError
from marko.services.semantic_candidate_gate import semantic_gate_snapshot_is_current
from metis.pricing import (
    CohortRole,
    HardGateResult,
    comparison_evidence_from_dict,
    comparison_evidence_to_dict,
)
from metis.pricing.observability import pricing_event

MAX_REENRICHMENT_BATCH_SIZE = 1_000


class OeReenrichmentDataError(ValueError):
    """A deterministic retained-data defect that is safe to persist and skip."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class OeReenrichmentPatch:
    extracted_oe_norms: tuple[str, ...]
    verified_matched_oe_norm: str | None
    comparison_identity_key: str | None
    oe_verification_status: str
    oe_evidence: tuple[dict[str, Any], ...]
    match_confidence: Decimal
    comparison_evidence: dict[str, Any]
    comparability_hard_gate_result: str
    automatic_eligible: bool
    via_cross: bool
    cross_link_id: UUID | None
    identity_admission: dict[str, Any]

    def deterministic_dict(self) -> dict[str, Any]:
        """Return the timestamp-free patch used by idempotency tests and reports."""

        return {
            "extracted_oe_norms": list(self.extracted_oe_norms),
            "verified_matched_oe_norm": self.verified_matched_oe_norm,
            "comparison_identity_key": self.comparison_identity_key,
            "oe_verification_status": self.oe_verification_status,
            "oe_evidence": list(self.oe_evidence),
            "match_confidence": format(self.match_confidence, "f"),
            "comparison_evidence": self.comparison_evidence,
            "comparability_hard_gate_result": self.comparability_hard_gate_result,
            "automatic_eligible": self.automatic_eligible,
            "via_cross": self.via_cross,
            "cross_link_id": str(self.cross_link_id) if self.cross_link_id else None,
            "identity_admission": self.identity_admission,
            "oe_extractor_version": OE_EXTRACTOR_VERSION,
        }


@dataclass(frozen=True, slots=True)
class OeReenrichmentReport:
    dry_run: bool
    scanned: int
    updated: int
    status_counts: Mapping[str, int]
    failed: int
    failure_counts: Mapping[str, int]
    extractor_version: str = OE_EXTRACTOR_VERSION
    network_requests: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "scanned": self.scanned,
            "updated": self.updated,
            "status_counts": dict(sorted(self.status_counts.items())),
            "failed": self.failed,
            "failure_counts": dict(sorted(self.failure_counts.items())),
            "extractor_version": self.extractor_version,
            "network_requests": self.network_requests,
        }


def reconstruct_source_assertion(
    observation: MarketObservation,
    lineage: AcquisitionLineage,
    raw_manifest: Mapping[str, Any],
) -> SourceAssertion | None:
    """Rebuild the persisted assertion and prove it still holds.

    Four things have to agree before a stored assertion may be believed again:
    the row actually carries one, the acquisition retained on disk still asserts
    identity the same way, it still names the same widening number, and the
    retained bytes still bind to the same request.  Anything else is a conflict
    and fails closed — the row keeps its market datum and loses its promotion.

    A row that never carried an assertion is never given one here: promotion is
    a decision made at collection, against evidence that existed then.
    """

    persisted_kind = (observation.source_assertion_retrieval_kind or "").strip()
    persisted_sha = (observation.source_assertion_capture_sha256 or "").strip()
    persisted_confidence = observation.source_assertion_confidence
    persisted_via = (observation.via_oe_number or "").strip() or None
    if not persisted_kind:
        # Никакого заявления не было — и повторное обогащение его не выдумывает.
        return None
    if not persisted_sha or persisted_confidence is None:
        raise OeReenrichmentDataError("REENRICHMENT_ASSERTION_INCOMPLETE")
    if not lineage.asserts_identity:
        raise OeReenrichmentDataError("REENRICHMENT_ASSERTION_CONFLICT")
    if lineage.retrieval_kind.strip() != persisted_kind:
        raise OeReenrichmentDataError("REENRICHMENT_ASSERTION_CONFLICT")
    if ((lineage.via_oe_number or "").strip() or None) != persisted_via:
        raise OeReenrichmentDataError("REENRICHMENT_ASSERTION_CONFLICT")
    recomputed = _acquisition_capture_binding(raw_manifest, lineage)
    # Хранимая привязка бывает двух форм: нынешняя (запрос + байты) и прежняя
    # (только хеш манифеста) для строк, собранных до введения привязки. Обе
    # пересчитываются здесь из тех же удержанных улик; догадок нет ни в одной.
    legacy_binding = str(raw_manifest.get("raw_content_sha256") or "").strip()
    if persisted_sha not in {recomputed, legacy_binding} or not recomputed:
        raise OeReenrichmentDataError("REENRICHMENT_ASSERTION_CAPTURE_MISMATCH")
    return SourceAssertion.from_lineage(
        lineage,
        capture_sha256=persisted_sha,
        confidence=persisted_confidence,
    )


def build_reenrichment_patch(
    *,
    observation: MarketObservation,
    frozen_item: FrozenCatalogItem,
    capture: RawMarketCapture,
    run: PricingRun,
    classification: ObservationTierClassification | None = None,
    confirmed_crosses: tuple[ConfirmedCross, ...] = (),
    structured_payload: Mapping[str, Any] | None = None,
) -> OeReenrichmentPatch:
    """Derive a deterministic identity patch from retained capture bytes only.

    ``frozen_item`` is the catalog position **as the run froze it**.  It is not
    an ORM row: passing the live ``CatalogItem`` here would let a category or
    part-number edit made after the run started rewrite an already-computed
    identity, and nothing in the observation would record that it happened.
    """

    frozen_search_identity = customer_identity_query(frozen_item)
    if frozen_search_identity != str(observation.search_oe_norm or "").strip():
        # Наблюдение и замороженная позиция описывают разные номера: одно из
        # двух записано не туда, и догадываться какое — не наша роль.
        raise OeReenrichmentDataError("REENRICHMENT_FROZEN_OE_CONFLICT")
    seed_identity_namespace = customer_identity_namespace(frozen_item)
    candidate = _candidate_for_observation(
        structured_payload if structured_payload is not None else capture.payload,
        observation.source_listing_id,
    )
    raw_manifest = _candidate_raw_manifest(
        capture,
        source_record_id=candidate.source_listing_id,
    )
    retained_raw_evidence = _verified_capture_raw_evidence(capture)
    seller_id = str(
        candidate.product.get("seller_id") or observation.seller_id or ""
    ).strip()
    detail_evidence_safe = _detail_evidence_automatic_safe(
        candidate.product,
        seller_id=seller_id,
        retained_raw_evidence=retained_raw_evidence,
    )
    detail = candidate.product.get("detail_evidence")
    verified_detail_manifest = (
        {
            "source_record_id": str(detail.get("source_url") or ""),
            "raw_capture_id": str(capture.id),
            "raw_content_sha256": str(
                detail.get("content_sha256") or ""
            ).casefold(),
        }
        if detail_evidence_safe and isinstance(detail, Mapping)
        else None
    )
    evidence_source = dict(candidate.product)
    if candidate.upstream_comparison_evidence is not None:
        evidence_source["comparison_evidence"] = dict(
            candidate.upstream_comparison_evidence
        )
    oe_items = extract_oe_evidence(
        evidence_source,
        raw_manifest,
        verified_detail_manifest=verified_detail_manifest,
    )
    proposed_crosses = extract_prom_motors_cross_proposals(
        evidence_source,
        verified_detail_manifest,
        search_oe_norm=observation.search_oe_norm,
    )
    # Заявление источника не выбрасывается и не принимается на веру: оно
    # восстанавливается из удержанного приобретения и перепроверяется.
    source_assertion = reconstruct_source_assertion(
        observation, candidate.acquisition, raw_manifest
    )
    verification = verify_offer_identity(
        observation.search_oe_norm,
        oe_items,
        confirmed_crosses,
        proposed_crosses,
        source_assertion=source_assertion,
        allow_short_numeric_native=(
            seed_identity_namespace is IdentityNamespace.MPN
        ),
    )
    verification = namespace_bound_verification(
        verification,
        seed_identity_namespace,
    )
    base_automatic_identity_evidence = automatic_identity_evidence_sufficient(
        verification,
        oe_items,
        authoritative_identity=bool(
            source_assertion is not None
            and source_assertion.authoritative_for(observation.search_oe_norm)
        ),
        # Re-enrichment must use the same OE namespace floor as first
        # materialization; otherwise replay could promote an MPN/SKU-only row.
        require_oe_namespace=True,
    )
    automatic_identity_evidence, identity_namespace_reason = (
        namespace_identity_admission(
            seed_namespace=seed_identity_namespace,
            verification=verification,
            evidence_items=oe_items,
            base_automatic_evidence=base_automatic_identity_evidence,
        )
    )
    comparison = comparison_evidence_from_dict(observation.comparison_evidence)
    comparison = bind_oe_verification(
        comparison,
        verification,
        seller_id=observation.seller_id or None,
        currency_raw=observation.currency_raw,
        currency_normalized=observation.currency,
        required_currency="UAH",
        category=frozen_item.category,
    )
    # Re-enrichment must not be a second, weaker admission path.  The first
    # materialization evaluated the category-aware semantic pricing gate and
    # persisted its result inside the immutable candidate snapshot.  If that
    # proof is absent (or was only ``REFERENCE_ONLY``), the new OE evidence may
    # improve identity diagnostics but it cannot promote the row into a price
    # cohort.  Keep the generic comparability evidence fail-closed as well;
    # otherwise the pricing engine could see ``PASS`` and admit a legacy row
    # even though this replay has no semantic proof.
    semantic_gate_allowed = _persisted_semantic_gate_allowed(observation)
    if not semantic_gate_allowed:
        comparison = replace(
            comparison,
            hard_gate_result=HardGateResult.MANUAL_REVIEW,
            reason_codes=tuple(
                dict.fromkeys(
                    (*comparison.reason_codes, "REENRICHMENT_SEMANTIC_GATE_REQUIRED")
                )
            ),
        )
    if not automatic_identity_evidence:
        identity_reasons = [
            *comparison.reason_codes,
            "OE_AUTOMATIC_IDENTITY_EVIDENCE_INSUFFICIENT",
        ]
        if identity_namespace_reason not in {
            None,
            "IDENTITY_EVIDENCE_INSUFFICIENT",
        }:
            identity_reasons.append(identity_namespace_reason)
        comparison = replace(
            comparison,
            hard_gate_result=HardGateResult.MANUAL_REVIEW,
            reason_codes=tuple(dict.fromkeys(identity_reasons)),
        )
    selected_cross = next(
        (
            cross
            for cross in confirmed_crosses
            if verification.status == OeVerificationStatus.VERIFIED_CROSS
            and cross.candidate_oe_norm == verification.verified_matched_oe_norm
        ),
        None,
    )
    if selected_cross is not None and not selected_cross.cross_link_id:
        raise OeReenrichmentDataError("REENRICHMENT_CROSS_LINK_ID_MISSING")
    cross_link_id = (
        UUID(selected_cross.cross_link_id) if selected_cross is not None else None
    )
    # Замороженный снимок прогона, а не текущее развёртывание: загрузчик
    # пересчитывает ``policy_snapshot_hash`` и падает на расхождении. Иначе
    # правка развёрнутой политики меняла бы результат идущего прогона.
    policy = load_run_execution_policy(run)
    cohort_allows_automatic = _classification_allows_automatic(classification)
    automatic_eligible = bool(
        verification.verified
        and automatic_identity_evidence
        and comparison.hard_gate_result == HardGateResult.PASS
        and observation.seller_identity_verified
        and observation.source_provenance_verified
        and detail_evidence_safe
        and observation.currency_raw
        and observation.currency == "UAH"
        and observation.source_confidence >= policy.source_confidence_min
        and semantic_gate_allowed
        # Identity replay may improve evidence, but it must not turn a
        # customer-owned/KEMP/used/manual observation into a market datum.
        # The current tier classification is therefore an explicit proof
        # obligation; missing classification is fail-closed.
        and cohort_allows_automatic
    )
    identity_admission = {
        "automatic_evidence_sufficient": bool(automatic_identity_evidence),
        "authoritative_identity": bool(
            source_assertion is not None
            and source_assertion.authoritative_for(observation.search_oe_norm)
            and seed_identity_namespace is IdentityNamespace.OE
        ),
        "namespace_version": IDENTITY_NAMESPACE_VERSION,
        "seed_identity_namespace": seed_identity_namespace.value,
        "verified_identity_namespace": verified_identity_namespace(
            seed_identity_namespace, verification.status
        ).value,
        "comparison_identity_key": verification.comparison_identity_key,
        "verification_status": verification.status.value,
        "namespace_reason": identity_namespace_reason,
        "reason": identity_namespace_reason,
    }
    return OeReenrichmentPatch(
        extracted_oe_norms=verification.extracted_oe_norms,
        verified_matched_oe_norm=verification.verified_matched_oe_norm,
        comparison_identity_key=verification.comparison_identity_key,
        oe_verification_status=verification.status.value,
        oe_evidence=tuple(evidence_items_to_dicts(oe_items)),
        match_confidence=verification.confidence,
        comparison_evidence=comparison_evidence_to_dict(comparison),
        comparability_hard_gate_result=comparison.hard_gate_result.value,
        automatic_eligible=automatic_eligible,
        via_cross=verification.status == OeVerificationStatus.VERIFIED_CROSS,
        cross_link_id=cross_link_id,
        identity_admission=identity_admission,
    )


def _persisted_semantic_gate_allowed(observation: MarketObservation) -> bool:
    """Return whether the original materialization proved pricing semantics.

    Re-enrichment is intentionally identity-only.  It may reconstruct OE
    evidence from retained bytes, but it cannot re-run the semantic extractor
    without the original category-selection configuration and therefore must
    never infer a new pricing admission.  Missing snapshots are treated as
    legacy/unproven rather than as an implicit pass.
    """

    # Re-enrichment must use the exact same freshness predicate as the pricing
    # engine and calibration boundary.  Keeping a local, weaker copy here
    # allowed a snapshot with a current gate version but without the mandatory
    # ``identity_admission.automatic_evidence_sufficient`` proof to be reused
    # during identity replay.  That is especially dangerous for a retained
    # Prom source assertion, because it can make an old, pre-admission row
    # eligible again without re-materialising the candidate.
    return semantic_gate_snapshot_is_current(
        getattr(observation, "candidate_snapshot", None),
        expected_source_listing_id=getattr(observation, "source_listing_id", None),
        expected_raw_capture_id=getattr(observation, "raw_capture_id", None),
        expected_identity_key=getattr(
            observation, "comparison_identity_key", None
        ),
        require_identity_namespace=(
            getattr(observation, "catalog_item_id", None) is not None
        ),
    )


def _classification_allows_automatic(
    classification: ObservationTierClassification | None,
) -> bool:
    """Return whether a tier row is eligible for automatic market use.

    Re-enrichment is an identity replay, not a fresh market-classification
    pass.  It therefore cannot infer ownership or cohort membership from the
    candidate payload.  A missing classification, an owned/KEMP/used row, or
    any non-target role must stay manual-review only.
    """

    if classification is None:
        return False
    return bool(
        not classification.is_owned
        and not classification.is_kemp
        and not classification.is_used
        and str(classification.cohort_role or "").strip()
        == CohortRole.TARGET_MARKET.value
    )


async def re_enrich_retained_observations(
    *,
    batch_size: int,
    dry_run: bool = True,
    retry_failed: bool = False,
) -> OeReenrichmentReport:
    """Process one bounded batch; intended as the Celery task implementation."""

    bounded_size = max(1, min(int(batch_size), MAX_REENRICHMENT_BATCH_SIZE))
    async with async_session_factory() as session:
        return await re_enrich_retained_observations_in_session(
            session,
            batch_size=bounded_size,
            dry_run=dry_run,
            retry_failed=retry_failed,
        )


async def re_enrich_retained_observations_in_session(
    session: AsyncSession,
    *,
    batch_size: int,
    dry_run: bool,
    retry_failed: bool = False,
) -> OeReenrichmentReport:
    bounded_size = max(1, min(int(batch_size), MAX_REENRICHMENT_BATCH_SIZE))
    # Живая строка ``CatalogItem`` здесь больше не читается вовсе: позиция
    # приезжает из замороженного снимка строки членства, привязанного к своему
    # прогону. Иначе правка каталога после старта переписывала бы уже
    # посчитанную идентичность задним числом.
    classification_alias = aliased(ObservationTierClassification)
    latest_classification_id = (
        select(classification_alias.id)
        .where(
            classification_alias.market_observation_id == MarketObservation.id
        )
        .order_by(
            classification_alias.classified_at.desc(),
            classification_alias.id.desc(),
        )
        .limit(1)
        .correlate(MarketObservation)
        .scalar_subquery()
    )
    statement = (
        select(
            MarketObservation,
            PricingRunItem,
            RawMarketCapture,
            PricingRun,
            ScrapeTarget,
            classification_alias,
        )
        .join(RawMarketCapture, RawMarketCapture.id == MarketObservation.raw_capture_id)
        .outerjoin(ScrapeTarget, ScrapeTarget.id == RawMarketCapture.scrape_target_id)
        .join(
            PricingRunItem,
            PricingRunItem.id == MarketObservation.pricing_run_item_id,
        )
        .join(PricingRun, PricingRun.id == PricingRunItem.pricing_run_id)
        .outerjoin(
            classification_alias,
            classification_alias.id == latest_classification_id,
        )
        .where(MarketObservation.oe_extractor_version != OE_EXTRACTOR_VERSION)
        .order_by(MarketObservation.id)
        .limit(bounded_size)
    )
    if not retry_failed:
        statement = statement.where(
            MarketObservation.oe_reenrichment_error_code.is_(None)
        )
    if not dry_run:
        await session.execute(
            select(
                func.set_config(
                    "marko.identity_reenrichment",
                    OE_EXTRACTOR_VERSION,
                    True,
                )
            )
        )
        statement = statement.with_for_update(
            of=MarketObservation,
            skip_locked=True,
        )
    rows = list((await session.execute(statement)).all())
    status_counts: dict[str, int] = {}
    failure_counts: dict[str, int] = {}
    updated = 0
    attempted_at = datetime.now(UTC)
    for observation, run_item, capture, run, target, classification in rows:
        try:
            frozen_item = resolve_bound_execution_item(run, run_item)
            crosses = await _load_confirmed_crosses(
                session,
                run=run,
                search_identity=observation.search_oe_norm,
            )
            patch = build_reenrichment_patch(
                observation=observation,
                frozen_item=frozen_item,
                capture=capture,
                run=run,
                classification=classification,
                confirmed_crosses=crosses,
                structured_payload=(target.payload if target is not None else None),
            )
        except (
            OeReenrichmentDataError,
            PricingRunSnapshotError,
            ScraperBoundaryError,
            TypeError,
            ValueError,
        ) as exc:
            if isinstance(exc, OeReenrichmentDataError):
                code = exc.code
            elif isinstance(exc, PricingRunSnapshotError):
                code = f"REENRICHMENT_{str(exc).split(':', 1)[0][:60]}"
            elif isinstance(exc, ScraperBoundaryError):
                code = f"REENRICHMENT_{exc.code.value.upper()}"
            else:
                code = f"REENRICHMENT_{type(exc).__name__.upper()}"
            failure_counts[code] = failure_counts.get(code, 0) + 1
            if not dry_run:
                observation.automatic_eligible = False
                observation.oe_reenriched_at = attempted_at
                observation.oe_reenrichment_error_code = code[:100]
            continue

        status_counts[patch.oe_verification_status] = (
            status_counts.get(patch.oe_verification_status, 0) + 1
        )
        if dry_run:
            continue
        _apply_patch(observation, patch, attempted_at=attempted_at)
        updated += 1

    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    report = OeReenrichmentReport(
        dry_run=dry_run,
        scanned=len(rows),
        updated=updated,
        status_counts=status_counts,
        failed=sum(failure_counts.values()),
        failure_counts=failure_counts,
    )
    for status, count in report.status_counts.items():
        pricing_event(
            "oe_reenrichment_total",
            status=status,
            dry_run=dry_run,
            extractor_version=OE_EXTRACTOR_VERSION,
            value=count,
        )
    for reason, count in report.failure_counts.items():
        pricing_event(
            "oe_reenrichment_total",
            status="FAILED",
            reason=reason,
            dry_run=dry_run,
            extractor_version=OE_EXTRACTOR_VERSION,
            value=count,
        )
    return report


def _candidate_for_observation(
    structured_payload: Mapping[str, Any],
    source_listing_id: str,
) -> AcceptedCandidate:
    # ``from_payload`` re-runs the closed acquisition contract over the retained
    # bytes, so a record whose lineage no longer holds together cannot silently
    # regain an identity claim on the second pass.
    output = ScrapeOutput.from_payload(structured_payload)
    prepared_url = output.prepared_url
    input_hash = output.input_hash
    acquisition_query = output.acquisition_query
    matches: list[AcceptedCandidate] = []
    for index, raw_offer in enumerate(output.candidate_records):
        result = process_offer_candidate(
            raw_offer,
            fallback_index=index,
            prepared_url=prepared_url,
            input_hash=input_hash,
            fallback_queried_oe=acquisition_query,
        )
        if (
            isinstance(result, AcceptedCandidate)
            and result.source_listing_id == source_listing_id
        ):
            matches.append(result)
    if not matches:
        raise OeReenrichmentDataError("REENRICHMENT_SOURCE_RECORD_NOT_FOUND")
    if len(matches) != 1:
        raise OeReenrichmentDataError("REENRICHMENT_SOURCE_RECORD_AMBIGUOUS")
    return matches[0]


def _apply_patch(
    observation: MarketObservation,
    patch: OeReenrichmentPatch,
    *,
    attempted_at: datetime,
) -> None:
    snapshot = getattr(observation, "candidate_snapshot", None)
    if isinstance(snapshot, dict):
        snapshot["identity_admission"] = dict(patch.identity_admission)
        observation.candidate_snapshot = snapshot
    observation.extracted_oe_norms = list(patch.extracted_oe_norms)
    observation.verified_matched_oe_norm = patch.verified_matched_oe_norm
    observation.matched_oe_norm = patch.verified_matched_oe_norm
    observation.comparison_identity_key = patch.comparison_identity_key
    observation.oe_verification_status = patch.oe_verification_status
    observation.oe_evidence = list(patch.oe_evidence)
    observation.oe_extractor_version = OE_EXTRACTOR_VERSION
    observation.oe_reenriched_at = attempted_at
    observation.oe_reenrichment_error_code = None
    observation.match_confidence = patch.match_confidence
    observation.comparison_evidence = patch.comparison_evidence
    observation.comparability_hard_gate_result = patch.comparability_hard_gate_result
    observation.automatic_eligible = patch.automatic_eligible
    observation.via_cross = patch.via_cross
    observation.cross_link_id = patch.cross_link_id
    observation.calibration_exclusion_codes = ["CAL_REENRICHMENT_PENDING_RECALIBRATION"]


__all__ = [
    "MAX_REENRICHMENT_BATCH_SIZE",
    "OeReenrichmentDataError",
    "OeReenrichmentPatch",
    "OeReenrichmentReport",
    "build_reenrichment_patch",
    "reconstruct_source_assertion",
    "re_enrich_retained_observations",
    "re_enrich_retained_observations_in_session",
]
