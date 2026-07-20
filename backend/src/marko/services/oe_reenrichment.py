"""Bounded, network-free re-enrichment of retained market observations.

The job deliberately reuses the canonical offer identity service.  It never
uses ``search_oe_norm`` as candidate evidence and never performs HTTP calls.
Rows with deterministic data failures retain a persistent error code; unknown
exceptions abort the batch so they cannot become silent data loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from metis.pricing import (
    HardGateResult,
    comparison_evidence_from_dict,
    comparison_evidence_to_dict,
)
from metis.pricing.observability import pricing_event
from marko.infrastructure.db.models import (
    CatalogItem,
    MarketObservation,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    ScrapeTarget,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.market_collection import (
    _candidate_raw_manifest,
    _load_confirmed_crosses,
)
from marko.services.offer_identity import (
    OE_EXTRACTOR_VERSION,
    ConfirmedCross,
    OeVerificationStatus,
    bind_oe_verification,
    evidence_items_to_dicts,
    extract_oe_evidence,
    verify_offer_identity,
)
from marko.services.offer_processing import (
    AcceptedCandidate,
    process_offer_candidate,
)
from marko.services.pricing_runs import policy_from_dict
from marko.services.scraper_contract import ScrapeOutput, ScraperBoundaryError


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


def build_reenrichment_patch(
    *,
    observation: MarketObservation,
    catalog_item: CatalogItem,
    capture: RawMarketCapture,
    run: PricingRun,
    confirmed_crosses: tuple[ConfirmedCross, ...] = (),
    structured_payload: Mapping[str, Any] | None = None,
) -> OeReenrichmentPatch:
    """Derive a deterministic identity patch from retained capture bytes only."""

    candidate = _candidate_for_observation(
        structured_payload if structured_payload is not None else capture.payload,
        observation.source_listing_id,
    )
    raw_manifest = _candidate_raw_manifest(
        capture,
        source_record_id=candidate.source_listing_id,
    )
    evidence_source = dict(candidate.product)
    if candidate.upstream_comparison_evidence is not None:
        evidence_source["comparison_evidence"] = dict(
            candidate.upstream_comparison_evidence
        )
    oe_items = extract_oe_evidence(evidence_source, raw_manifest)
    verification = verify_offer_identity(
        observation.search_oe_norm,
        oe_items,
        confirmed_crosses,
    )
    comparison = comparison_evidence_from_dict(observation.comparison_evidence)
    comparison = bind_oe_verification(
        comparison,
        verification,
        seller_id=observation.seller_id or None,
        currency_raw=observation.currency_raw,
        currency_normalized=observation.currency,
        required_currency="UAH",
        category=catalog_item.category,
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
    policy = policy_from_dict(run.policy_config)
    automatic_eligible = bool(
        verification.verified
        and comparison.hard_gate_result == HardGateResult.PASS
        and observation.seller_identity_verified
        and observation.source_provenance_verified
        and observation.currency_raw
        and observation.currency == "UAH"
        and observation.source_confidence >= policy.source_confidence_min
    )
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
    statement = (
        select(
            MarketObservation,
            CatalogItem,
            RawMarketCapture,
            PricingRun,
            ScrapeTarget,
        )
        .join(CatalogItem, CatalogItem.id == MarketObservation.catalog_item_id)
        .join(RawMarketCapture, RawMarketCapture.id == MarketObservation.raw_capture_id)
        .outerjoin(ScrapeTarget, ScrapeTarget.id == RawMarketCapture.scrape_target_id)
        .join(
            PricingRunItem,
            PricingRunItem.id == MarketObservation.pricing_run_item_id,
        )
        .join(PricingRun, PricingRun.id == PricingRunItem.pricing_run_id)
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
    for observation, catalog_item, capture, run, target in rows:
        try:
            crosses = await _load_confirmed_crosses(
                session,
                run=run,
                catalog_item=catalog_item,
            )
            patch = build_reenrichment_patch(
                observation=observation,
                catalog_item=catalog_item,
                capture=capture,
                run=run,
                confirmed_crosses=crosses,
                structured_payload=(target.payload if target is not None else None),
            )
        except (
            OeReenrichmentDataError,
            ScraperBoundaryError,
            TypeError,
            ValueError,
        ) as exc:
            if isinstance(exc, OeReenrichmentDataError):
                code = exc.code
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
    output = ScrapeOutput.from_payload(structured_payload)
    matches: list[AcceptedCandidate] = []
    for index, raw_offer in enumerate(output.candidate_records):
        result = process_offer_candidate(raw_offer, fallback_index=index)
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
    "re_enrich_retained_observations",
    "re_enrich_retained_observations_in_session",
]
