"""Production shadow orchestration after deterministic market persistence.

The worker never accepts model target fields from an API caller.  It derives
them from the persisted four-valued comparison evidence, applies the existing
owned/reject/candidate-cap selector, and only then reaches the paid runtime.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    CatalogItem,
    MarketObservation,
    ObservationTierClassification,
    PricingRun,
    PricingRunItem,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.ai_evidence_extraction import (
    AiEvidenceProvider,
    EvidenceFieldName,
    ExtractionCandidate,
    SelectionOutcome,
    resolve_ai_evidence_config,
    select_extraction_candidates,
)
from marko.services.ai_evidence_runtime import request_or_reuse_ai_evidence
from marko.services.market_price import effective_observation_price
from metis.pricing import EvidenceState, HardGateResult, comparison_evidence_from_dict
from metis.pricing.types import ComparisonEvidence


_DIMENSION_FIELDS: Mapping[str, tuple[EvidenceFieldName, ...]] = {
    "oe_reference": (EvidenceFieldName.OE_NUMBERS,),
    "part_type": (EvidenceFieldName.PART_TYPE,),
    "brand_manufacturer": (EvidenceFieldName.BRAND,),
    "fitment": (
        EvidenceFieldName.FITMENT,
        EvidenceFieldName.VEHICLE_MAKE,
        EvidenceFieldName.VEHICLE_MODEL,
    ),
    "vehicle_generation": (EvidenceFieldName.VEHICLE_GENERATION,),
    "year_interval": (EvidenceFieldName.YEAR_FROM, EvidenceFieldName.YEAR_TO),
    "engine": (EvidenceFieldName.ENGINE,),
    "body_variant": (EvidenceFieldName.BODY_VARIANT,),
    "side": (EvidenceFieldName.SIDE,),
    "position": (EvidenceFieldName.INSTALLATION_POSITION,),
    "condition": (EvidenceFieldName.CONDITION,),
    "package_quantity": (
        EvidenceFieldName.PACKAGE_QUANTITY,
        EvidenceFieldName.UNIT_BASIS,
    ),
}


@dataclass(frozen=True, slots=True)
class AiEvidenceShadowBatchResult:
    pricing_run_item_id: UUID
    selected: int
    completed: int
    cached: int
    failed: int
    refused: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "pricing_run_item_id": str(self.pricing_run_item_id),
            "selected": self.selected,
            "completed": self.completed,
            "cached": self.cached,
            "failed": self.failed,
            "refused": [list(item) for item in self.refused],
            "shadow_only": True,
        }


def open_ai_evidence_fields(
    observation: MarketObservation,
    comparison: ComparisonEvidence | None,
) -> frozenset[EvidenceFieldName]:
    """Map only persisted UNKNOWN dimensions to model extraction fields."""

    if comparison is None:
        return frozenset()
    fields: set[EvidenceFieldName] = set()
    for dimension, requested in _DIMENSION_FIELDS.items():
        evidence = comparison.dimensions.get(dimension)
        if evidence is not None and evidence.state is EvidenceState.UNKNOWN:
            fields.update(requested)
    return frozenset(fields)


def _has_bound_source_locator(observation: MarketObservation) -> bool:
    snapshot = observation.candidate_snapshot
    locator = snapshot.get("source_locator") if isinstance(snapshot, Mapping) else None
    return isinstance(locator, Mapping) and bool(locator)


def _deterministically_rejected(
    observation: MarketObservation,
    comparison: ComparisonEvidence | None,
    tier: ObservationTierClassification | None,
) -> bool:
    if comparison is None or not _has_bound_source_locator(observation):
        return True
    return bool(
        comparison.hard_gate_result is HardGateResult.REJECT
        or observation.oe_verification_status == "CONFLICT"
        or observation.condition_state in {"USED_OR_REFURBISHED", "CONFLICT"}
        or (tier is not None and tier.is_used)
    )


async def process_ai_evidence_position(
    pricing_run_item_id: UUID,
    *,
    settings: Any | None = None,
    provider: AiEvidenceProvider | None = None,
) -> AiEvidenceShadowBatchResult:
    """Run the bounded selector and paid runtime for one persisted position."""

    effective_settings = settings or get_settings()
    config = resolve_ai_evidence_config(effective_settings)
    async with async_session_factory() as session:
        bound = (
            await session.execute(
                select(PricingRunItem, PricingRun, CatalogItem)
                .join(PricingRun, PricingRun.id == PricingRunItem.pricing_run_id)
                .join(CatalogItem, CatalogItem.id == PricingRunItem.catalog_item_id)
                .where(PricingRunItem.id == pricing_run_item_id)
            )
        ).one_or_none()
        if bound is None:
            raise LookupError(f"pricing run item {pricing_run_item_id} not found")
        run_item, run, catalog_item = bound
        observations = list(
            (
                await session.scalars(
                    select(MarketObservation)
                    .where(MarketObservation.pricing_run_item_id == pricing_run_item_id)
                    .order_by(MarketObservation.id)
                )
            ).all()
        )
        tier_rows = (
            list(
                (
                    await session.scalars(
                        select(ObservationTierClassification)
                        .where(
                            ObservationTierClassification.market_observation_id.in_(
                                [item.id for item in observations]
                            )
                        )
                        .order_by(
                            ObservationTierClassification.classified_at.desc(),
                            ObservationTierClassification.id.desc(),
                        )
                    )
                ).all()
            )
            if observations
            else []
        )

    latest_tier: dict[UUID, ObservationTierClassification] = {}
    for tier in tier_rows:
        latest_tier.setdefault(tier.market_observation_id, tier)

    comparisons: dict[UUID, ComparisonEvidence | None] = {}
    candidates: list[ExtractionCandidate] = []
    for observation in observations:
        try:
            comparison = comparison_evidence_from_dict(observation.comparison_evidence)
        except (TypeError, ValueError):
            comparison = None
        comparisons[observation.id] = comparison
        tier = latest_tier.get(observation.id)
        candidates.append(
            ExtractionCandidate(
                observation_id=str(observation.id),
                source_listing_id=observation.source_listing_id,
                price=effective_observation_price(observation),
                is_owned_seller=bool(tier and tier.is_owned),
                deterministically_rejected=_deterministically_rejected(
                    observation, comparison, tier
                ),
                open_fields=open_ai_evidence_fields(observation, comparison),
            )
        )
    selection: SelectionOutcome = select_extraction_candidates(
        candidates,
        config=config,
    )
    if not selection.selected:
        return AiEvidenceShadowBatchResult(
            pricing_run_item_id=pricing_run_item_id,
            selected=0,
            completed=0,
            cached=0,
            failed=0,
            refused=tuple((key, value.value) for key, value in selection.refused),
        )

    by_id = {str(item.id): item for item in observations}
    semaphore = asyncio.Semaphore(config.max_concurrency)
    our_values = {
        "part_type": catalog_item.category,
        "brand_manufacturer": catalog_item.brand,
    }

    async def run_selected(selected):
        observation = by_id[selected.candidate.observation_id]
        async with semaphore, async_session_factory() as session:
            return await request_or_reuse_ai_evidence(
                session,
                workspace_id=run.workspace_id,
                pricing_run_item_id=run_item.id,
                market_observation_id=observation.id,
                settings=effective_settings,
                target_fields=selected.target_fields,
                provider=provider,
                comparison_evidence=comparisons[observation.id],
                our_values=our_values,
            )

    results = await asyncio.gather(
        *(run_selected(selected) for selected in selection.selected)
    )
    return AiEvidenceShadowBatchResult(
        pricing_run_item_id=pricing_run_item_id,
        selected=len(selection.selected),
        completed=sum(result.row.status == "COMPLETED" for result in results),
        cached=sum(result.row.status == "CACHED" for result in results),
        failed=sum(result.row.status == "FAILED" for result in results),
        refused=tuple((key, value.value) for key, value in selection.refused),
    )


__all__ = [
    "AiEvidenceShadowBatchResult",
    "open_ai_evidence_fields",
    "process_ai_evidence_position",
]
