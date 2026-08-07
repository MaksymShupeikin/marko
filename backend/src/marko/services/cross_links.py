"""Append-only Marko persistence adapter for Metis cross stages A and B."""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, select

from marko.infrastructure.db.models import (
    CatalogItem,
    CrossLink,
    MarketObservation,
    MarketplaceStore,
    ObservationTierClassification,
    PricingRun,
    PricingRunItem,
    StoreKind,
    WorkspaceStore,
)
from marko.services.market_price import effective_observation_price
from metis.pricing import (
    CrossABResult,
    CrossListing,
    load_cross_config,
    run_cross_stages_ab,
)


logger = logging.getLogger(__name__)

CATALOG_IDENTITY_RUN_SNAPSHOT_METHOD = "catalog-identity-run-snapshot-v1"
CATALOG_IDENTITY_RUN_SNAPSHOT_EXTRACTION = "CATALOG_IDENTITY_SNAPSHOT"
# Cross-link persistence currently has a single permitted marketplace family.
# Keep the namespace explicit: a future non-Prom observation may reuse a
# numeric seller id, but it must never be excluded by a Prom-owned store row or
# enter a Prom cross graph accidentally.
PROM_MARKETPLACE = "prom"
PROM_OBSERVATION_SOURCES = frozenset(
    {"prom", "prom_public", "prom_legacy_untraced"}
)


class CrossLinkPersistenceError(RuntimeError):
    """Raised instead of mutating an incompatible append-only run snapshot."""


@dataclass(frozen=True, slots=True)
class CrossLinkPersistenceResult:
    analysis: CrossABResult
    inserted: int
    reused: int
    method_version: str
    config_sha256: str


async def persist_cross_links_for_run(
    session: Any,
    *,
    pricing_run_id: UUID,
    config_path: str | Path,
) -> CrossLinkPersistenceResult:
    """Build a deterministic run snapshot and insert each canonical pair once.

    Existing rows are never updated or deleted. Run-start rows copied from the
    confirmed catalog identity graph are stronger, independent evidence, so
    Stage A/B inserts only decisions that graph does not already cover. A
    repeated Stage A/B invocation may otherwise only reuse a complete snapshot
    created with the identical method/config hash.
    """

    config = load_cross_config(config_path)
    run = await session.get(PricingRun, pricing_run_id)
    if run is None:
        raise CrossLinkPersistenceError(f"Pricing run does not exist: {pricing_run_id}")
    raw_rows = list(
        (
            await session.execute(
                # An observation can have historical tier rows after a
                # reclassification.  Joining all of them would let an old
                # non-owned classification resurrect a currently owned
                # listing as an independent cross source.  Bind the graph to
                # the latest deterministic classification only.
                select(
                    MarketObservation,
                    CatalogItem,
                    ObservationTierClassification,
                )
                .join(CatalogItem, CatalogItem.id == MarketObservation.catalog_item_id)
                .join(
                    PricingRunItem,
                    PricingRunItem.id == MarketObservation.pricing_run_item_id,
                )
                .join(
                    ObservationTierClassification,
                    ObservationTierClassification.id
                    == (
                        select(ObservationTierClassification.id)
                        .where(
                            ObservationTierClassification.market_observation_id
                            == MarketObservation.id
                        )
                        .order_by(
                            ObservationTierClassification.classified_at.desc(),
                            ObservationTierClassification.id.desc(),
                        )
                        .limit(1)
                        .correlate(MarketObservation)
                        .scalar_subquery()
                    ),
                )
                .where(
                    PricingRunItem.pricing_run_id == pricing_run_id,
                    MarketObservation.source.in_(PROM_OBSERVATION_SOURCES),
                    CatalogItem.identity_status == "OE_CONFIRMED",
                    ObservationTierClassification.is_owned.is_(False),
                    # KEMP is the customer's reference/target brand, not an
                    # independent market seller.  Its descriptions may be
                    # useful raw evidence, but must never count as one of the
                    # independent sources that confirms a cross edge.
                    ObservationTierClassification.is_kemp.is_(False),
                    # Only an already admitted target-market observation may
                    # contribute a cross edge.  MANUAL_REVIEW, USED_REJECTED,
                    # dumping diagnostics and hard rejects are retained for
                    # audit, but their descriptions are not identity evidence.
                    ObservationTierClassification.cohort_role == "TARGET_MARKET",
                    ObservationTierClassification.is_used.is_(False),
                    ObservationTierClassification.is_dumping.is_(False),
                    ~exists(
                        select(1)
                        .select_from(WorkspaceStore)
                        .join(
                            MarketplaceStore,
                            MarketplaceStore.id == WorkspaceStore.store_id,
                        )
                        .where(
                            WorkspaceStore.workspace_id == run.workspace_id,
                            WorkspaceStore.kind == StoreKind.owned,
                            MarketplaceStore.external_id
                            == MarketObservation.seller_id,
                            MarketplaceStore.marketplace == PROM_MARKETPLACE,
                        )
                    ),
                )
                .order_by(
                    CatalogItem.oe_norm,
                    MarketObservation.source_listing_id,
                    MarketObservation.id,
                )
            )
        ).all()
    )
    # Test/replay adapters from before the classification join return the
    # original two-tuple.  Keep that adapter shape usable, but apply the same
    # owned/identity guard when those attributes are available.  Production
    # rows always use the three-column query above and therefore fail closed
    # when their current tier classification is missing.
    rows: list[tuple[Any, Any]] = []
    for raw_row in raw_rows:
        if len(raw_row) == 3:
            observation, catalog_item, classification = raw_row
            if (
                getattr(classification, "is_owned", False)
                or getattr(classification, "is_kemp", False)
                or getattr(classification, "is_used", False)
                or getattr(classification, "is_dumping", False)
                or str(getattr(classification, "cohort_role", "")).strip()
                != "TARGET_MARKET"
            ):
                continue
        elif len(raw_row) == 2:
            observation, catalog_item = raw_row
        else:  # pragma: no cover - SQLAlchemy always returns 2/3 columns here
            continue
        if getattr(observation, "is_owned", False):
            continue
        if getattr(observation, "is_kemp", False) or str(
            getattr(observation, "cohort_role", "")
        ).strip() in {"OWNED_STORE", "KEMP_REFERENCE"}:
            continue
        if getattr(observation, "is_used", False) or getattr(
            observation, "is_dumping", False
        ):
            continue
        # Compatibility/replay adapters may expose the classification directly
        # on the observation.  When present, require the same target-market
        # role as the production SQL query; a manual/used/rejected row must not
        # become a cross source merely because it has a seller id.
        raw_observation_role = getattr(observation, "cohort_role", None)
        observation_role = str(raw_observation_role or "").strip()
        if observation_role and observation_role != "TARGET_MARKET":
            continue
        # Compatibility/replay adapters may bypass the SQL predicate above.
        # If a concrete observation declares a source, require the same Prom
        # namespace in Python as a second line of defence.
        raw_source = getattr(observation, "source", None)
        if (
            raw_source is not None
            and str(raw_source).strip()
            and str(raw_source).strip() not in PROM_OBSERVATION_SOURCES
        ):
            continue
        identity_status = getattr(catalog_item, "identity_status", None)
        if identity_status is not None and str(identity_status).strip() != "OE_CONFIRMED":
            continue
        rows.append((observation, catalog_item))
    listings = tuple(
        CrossListing(
            listing_id=str(observation.source_listing_id),
            our_oem_norm=catalog_item.oe_norm,
            description=observation.description,
            source_listing_url=observation.url,
            source_seller=observation.seller_name,
            source_seller_id=(
                str(getattr(observation, "seller_id", "")).strip() or None
            ),
            price=effective_observation_price(observation),
            our_category=catalog_item.category,
            source_category=_source_category(observation.comparison_evidence),
        )
        for observation, catalog_item in rows
    )
    analysis = run_cross_stages_ab(listings, config)
    analysis = _apply_persistence_admission(analysis)
    _log_rejections(analysis)

    existing_rows = list(
        (
            await session.scalars(
                select(CrossLink)
                .where(CrossLink.pricing_run_id == pricing_run_id)
                .order_by(CrossLink.our_oem_norm, CrossLink.extracted_oem_norm)
            )
        ).all()
    )
    catalog_snapshot_rows = [
        row for row in existing_rows if _is_catalog_identity_snapshot(row)
    ]
    stage_rows = [
        row for row in existing_rows if not _is_catalog_identity_snapshot(row)
    ]
    catalog_pairs = {
        _undirected_pair(record.our_oem_norm, record.extracted_oem_norm)
        for record in catalog_snapshot_rows
    }
    missing_decisions = tuple(
        decision
        for decision in analysis.pair_decisions
        if _undirected_pair(decision.our_oem_norm, decision.extracted_oem_norm)
        not in catalog_pairs
    )
    if stage_rows:
        _require_reusable_snapshot(stage_rows, missing_decisions, config)
        return CrossLinkPersistenceResult(
            analysis=analysis,
            inserted=0,
            reused=len(analysis.pair_decisions),
            method_version=config.method_version,
            config_sha256=config.source_sha256,
        )

    if not missing_decisions:
        return CrossLinkPersistenceResult(
            analysis=analysis,
            inserted=0,
            reused=len(analysis.pair_decisions),
            method_version=config.method_version,
            config_sha256=config.source_sha256,
        )

    catalog_ids: dict[str, UUID] = {}
    for _, catalog_item in rows:
        current = catalog_ids.get(catalog_item.oe_norm)
        if current is None or str(catalog_item.id) < str(current):
            catalog_ids[catalog_item.oe_norm] = catalog_item.id
    for decision in missing_decisions:
        catalog_item_id = catalog_ids.get(decision.our_oem_norm)
        if catalog_item_id is None:
            raise CrossLinkPersistenceError(
                f"No catalog item found for cross source OE {decision.our_oem_norm}"
            )
        session.add(
            CrossLink(
                workspace_id=run.workspace_id,
                pricing_run_id=pricing_run_id,
                catalog_item_id=catalog_item_id,
                our_oem_norm=decision.our_oem_norm,
                extracted_oem_norm=decision.extracted_oem_norm,
                source_listing_url=decision.source_listing_url,
                source_seller=decision.source_seller[:255],
                raw_context=decision.raw_context,
                extraction_method=decision.extraction_method,
                validation_status=decision.validation_status.value,
                rejection_reason=(
                    decision.rejection_reason.value
                    if decision.rejection_reason is not None
                    else None
                ),
                reciprocal_evidence_url=decision.reciprocal_evidence_url,
                source_evidence=[dict(item) for item in decision.source_evidence],
                validation_details=dict(decision.validation_details),
                method_version=config.method_version,
                config_sha256=config.source_sha256,
            )
        )
    await session.flush()
    return CrossLinkPersistenceResult(
        analysis=analysis,
        inserted=len(missing_decisions),
        reused=len(analysis.pair_decisions) - len(missing_decisions),
        method_version=config.method_version,
        config_sha256=config.source_sha256,
    )


def _apply_persistence_admission(result: CrossABResult) -> CrossABResult:
    """Require stable seller IDs before a description cross enters a run.

    The generic Path-2 evaluator can use display names as a diagnostic
    fallback.  A persisted pricing cross is stronger: a seller network can
    expose several names for one owner, and the four owned Prom storefronts
    are a concrete example.  Without two stable seller IDs the edge remains
    visible evidence but is not allowed to widen automatic identity.
    """

    decisions = []
    for decision in result.pair_decisions:
        details = dict(decision.validation_details)
        seller_ids = {
            str(value).strip()
            for value in (details.get("source_seller_ids") or ())
            if str(value).strip()
        }
        if len(seller_ids) < 2:
            details["automatic_eligible"] = False
            details["confidence"] = "0"
            details["automatic_eligibility_reason"] = (
                "STABLE_SELLER_ID_REQUIRED"
            )
        decisions.append(
            replace(decision, validation_details=details)
        )
    return replace(result, pair_decisions=tuple(decisions))


def _source_category(comparison_evidence: dict[str, Any] | None) -> str | None:
    if not isinstance(comparison_evidence, dict):
        return None
    value = comparison_evidence.get("source_category")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _log_rejections(analysis: CrossABResult) -> None:
    for rejection in analysis.rejections:
        logger.info(
            "description cross candidate rejected: listing=%s our_oe=%s "
            "token=%r normalized=%s reason=%s",
            rejection.listing_id,
            rejection.our_oem_norm,
            rejection.raw_token,
            rejection.normalized_token,
            rejection.reason.value,
        )


def _is_catalog_identity_snapshot(record: CrossLink) -> bool:
    """Recognize only the run-start snapshot contract, never arbitrary rows."""

    return (
        record.extraction_method == CATALOG_IDENTITY_RUN_SNAPSHOT_EXTRACTION
        and record.method_version == CATALOG_IDENTITY_RUN_SNAPSHOT_METHOD
    )


def _undirected_pair(left: str, right: str) -> tuple[str, str]:
    """Cross identity is symmetric even though the storage columns are not."""

    return (left, right) if left <= right else (right, left)


def _require_reusable_snapshot(existing_rows, expected_decisions, config) -> None:
    expected_pairs = {
        (decision.our_oem_norm, decision.extracted_oem_norm)
        for decision in expected_decisions
    }
    actual_pairs = {
        (record.our_oem_norm, record.extracted_oem_norm) for record in existing_rows
    }
    if actual_pairs != expected_pairs:
        raise CrossLinkPersistenceError(
            "Append-only cross snapshot differs from the current deterministic replay"
        )
    if any(
        record.method_version != config.method_version
        or record.config_sha256 != config.source_sha256
        for record in existing_rows
    ):
        raise CrossLinkPersistenceError(
            "Append-only cross snapshot was created with another method/config version"
        )


async def count_cross_links_for_run(session: Any, pricing_run_id: UUID) -> int:
    """Small read boundary used by orchestration and operational checks."""

    return int(
        await session.scalar(
            select(func.count(CrossLink.id)).where(
                CrossLink.pricing_run_id == pricing_run_id
            )
        )
        or 0
    )
