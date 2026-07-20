"""Append-only Marko persistence adapter for Metis cross stages A and B."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from marko.infrastructure.db.models import (
    CatalogItem,
    CrossLink,
    MarketObservation,
    PricingRun,
    PricingRunItem,
)
from metis.pricing import (
    CrossABResult,
    CrossListing,
    load_cross_config,
    run_cross_stages_ab,
)


logger = logging.getLogger(__name__)


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

    Existing rows are never updated or deleted. A repeated invocation may only
    reuse a complete snapshot created with the identical method/config hash.
    """

    config = load_cross_config(config_path)
    run = await session.get(PricingRun, pricing_run_id)
    if run is None:
        raise CrossLinkPersistenceError(f"Pricing run does not exist: {pricing_run_id}")
    rows = list(
        (
            await session.execute(
                select(MarketObservation, CatalogItem)
                .join(CatalogItem, CatalogItem.id == MarketObservation.catalog_item_id)
                .join(
                    PricingRunItem,
                    PricingRunItem.id == MarketObservation.pricing_run_item_id,
                )
                .where(PricingRunItem.pricing_run_id == pricing_run_id)
                .order_by(
                    CatalogItem.oe_norm,
                    MarketObservation.source_listing_id,
                    MarketObservation.id,
                )
            )
        ).all()
    )
    listings = tuple(
        CrossListing(
            listing_id=str(observation.source_listing_id),
            our_oem_norm=catalog_item.oe_norm,
            description=observation.description,
            source_listing_url=observation.url,
            source_seller=observation.seller_name,
            price=Decimal(observation.price),
            our_category=catalog_item.category,
            source_category=_source_category(observation.comparison_evidence),
        )
        for observation, catalog_item in rows
    )
    analysis = run_cross_stages_ab(listings, config)
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
    if existing_rows:
        _require_reusable_snapshot(existing_rows, analysis, config)
        return CrossLinkPersistenceResult(
            analysis=analysis,
            inserted=0,
            reused=len(existing_rows),
            method_version=config.method_version,
            config_sha256=config.source_sha256,
        )

    catalog_ids: dict[str, UUID] = {}
    for _, catalog_item in rows:
        current = catalog_ids.get(catalog_item.oe_norm)
        if current is None or str(catalog_item.id) < str(current):
            catalog_ids[catalog_item.oe_norm] = catalog_item.id
    for decision in analysis.pair_decisions:
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
        inserted=len(analysis.pair_decisions),
        reused=0,
        method_version=config.method_version,
        config_sha256=config.source_sha256,
    )


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


def _require_reusable_snapshot(existing_rows, analysis, config) -> None:
    expected_pairs = {
        (decision.our_oem_norm, decision.extracted_oem_norm)
        for decision in analysis.pair_decisions
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
