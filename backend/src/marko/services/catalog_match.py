"""Second stage of the card lane: narrow the collected offers, then price them.

The first button casts a wide net -- the parser collects every offer that could
plausibly be the same part. The second button is where the collection becomes
an answer: the paid reviewer judges each *distinct product* the net caught, and
what survives sets the customer's number.

Three decisions of the owner, taken 2026-08-22, shape this module:

* Offers the free deterministic gates refused are reviewed rather than dropped.
  A gate can be wrong, so its reason travels into the review instead of ending
  the candidate's life silently.
* One question per distinct product, not per offer. See
  ``candidate_offer_grouping``: 99 offers on card ``2141006`` are 42 products.
* The number is "cheapest comparable minus five percent" -- the same rule the
  pricing runs already apply, so a card and a run can never disagree.

Nothing here applies a price. The customer decided on 2026-08-21 that the
product performs no automatic pricing of any kind; this lane prepares evidence
and a proposal, and an operator decides.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select

from marko.core.config import Settings, get_settings
from marko.infrastructure.db.models import (
    CatalogDiscoveryOffer,
    CatalogDiscoveryRun,
    CatalogMatchRun,
    CatalogMatchReview,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.candidate_offer_grouping import (
    CandidateOfferGroup,
    group_candidate_offers,
    grouping_summary,
)
from marko.services.decision_fingerprint import canonical_sha256
from marko.services.llm_comparability import (
    ComparabilityProvider,
    IdentityVerdict,
    _SYSTEM_INSTRUCTIONS,
    _strict_output_schema,
    usage_and_cost_metadata,
    validate_comparability_provider_output,
)
from marko.services.no_oe_pricing import (
    NoOeQueryPlan,
    _provider,
    build_no_oe_review_input,
    offer_snapshot,
)
from metis.pricing.raise_policy import load_raise_policy
from metis.pricing.statistics import round_down_to_tick


CATALOG_MATCH_CONTRACT_VERSION = "catalog-match-v1"

#: The only verdict that may set the customer's floor.
COMPARABLE_VERDICT = "MATCH"


@dataclass(frozen=True, slots=True)
class CatalogMatchOutcome:
    """What the reviewed groups say the card's price should be."""

    minimum_comparable_price: Decimal | None
    advisory_price: Decimal | None
    comparable_group_count: int
    currency: str | None


def summarize_catalog_match(
    groups: Sequence[Any],
    verdicts: Mapping[str, str],
    *,
    minimum_discount: Decimal,
    price_tick: Decimal,
) -> CatalogMatchOutcome:
    """Turn per-group verdicts into the customer's advisory number.

    Only ``MATCH`` groups count. ``NO_MATCH`` is a different part and
    ``INSUFFICIENT_EVIDENCE`` is an unanswered question -- letting either near
    the floor would price the card against something nobody confirmed, and the
    cheapest offer in a collection is very often exactly the wrong part.
    """

    comparable = [
        group
        for group in groups
        if verdicts.get(getattr(group, "key", "")) == COMPARABLE_VERDICT
    ]
    priced = [
        group.lowest_price
        for group in comparable
        if getattr(group, "lowest_price", None) is not None
    ]
    if not priced:
        return CatalogMatchOutcome(
            minimum_comparable_price=None,
            advisory_price=None,
            comparable_group_count=len(comparable),
            currency=_first_currency(comparable),
        )
    minimum = min(priced)
    target = minimum * (Decimal("1") - minimum_discount)
    advisory = round_down_to_tick(target, price_tick)
    if advisory <= Decimal("0"):
        advisory = None
    return CatalogMatchOutcome(
        minimum_comparable_price=minimum,
        advisory_price=advisory,
        comparable_group_count=len(comparable),
        currency=_first_currency(comparable),
    )


def _first_currency(groups: Sequence[Any]) -> str | None:
    for group in groups:
        currency = getattr(group, "currency", None)
        if currency:
            return str(currency)
    return None


class CatalogMatchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


_VERDICT_BY_IDENTITY = {
    IdentityVerdict.MATCH: "MATCH",
    IdentityVerdict.NOT_MATCH: "NO_MATCH",
    IdentityVerdict.MANUAL_REVIEW: "INSUFFICIENT_EVIDENCE",
}


async def start_catalog_match(
    session: Any,
    *,
    workspace_id: UUID,
    discovery_run_id: UUID,
    product_snapshot: Mapping[str, Any],
) -> CatalogMatchRun:
    """Register one operator click against one completed collection.

    The click is bound to a specific ``catalog_discovery_run``: the offers it
    judges are the ones that collection actually saved, never a fresh search
    and never someone else's cache.
    """

    discovery = await session.get(CatalogDiscoveryRun, discovery_run_id)
    if discovery is None:
        raise CatalogMatchError(
            "CATALOG_MATCH_DISCOVERY_NOT_FOUND",
            "Сбор объявлений для этой карточки не найден.",
        )
    if discovery.workspace_id != workspace_id:
        raise CatalogMatchError(
            "CATALOG_MATCH_DISCOVERY_NOT_FOUND",
            "Сбор объявлений для этой карточки не найден.",
        )
    if discovery.status != "completed":
        raise CatalogMatchError(
            "CATALOG_MATCH_DISCOVERY_INCOMPLETE",
            "Сбор ещё не завершён — сопоставлять пока нечего.",
        )
    run = CatalogMatchRun(
        workspace_id=workspace_id,
        product_key=discovery.product_key,
        discovery_run_id=discovery.id,
        product_snapshot=dict(product_snapshot),
        status="queued",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


def _price_policy(settings: Settings) -> tuple[Decimal, Decimal]:
    """The customer's discount and price step, read from the pricing config.

    Deliberately the same file the pricing runs read. A card that priced by its
    own constant would sooner or later disagree with a run about the same part,
    and neither number would be defensible.
    """

    from marko.services.catalog_discovery import resolve_backend_path

    policy = load_raise_policy(
        resolve_backend_path(settings.pricing_raise_policy_path.strip())
    )
    return policy.minimum_discount, policy.psychological_step


def _gate_assessment(group: CandidateOfferGroup) -> dict[str, Any] | None:
    if not group.was_rejected_by_gates:
        return None
    return {
        "deterministic_gates": "REJECTED",
        "reasons": list(group.rejected_reasons),
        "instruction": (
            "Deterministic gates refused this candidate for the reasons above. "
            "Judge the evidence yourself and say whether that refusal holds."
        ),
    }


async def process_catalog_match_run(
    match_run_id: UUID,
    *,
    settings: Settings | None = None,
    provider: ComparabilityProvider | None = None,
) -> UUID | None:
    """Review every distinct product of one collection and price the card."""

    selected = settings or get_settings()
    if not selected.catalog_match_enabled:
        return None
    async with async_session_factory() as session:
        run = await session.get(CatalogMatchRun, match_run_id)
        if run is None or run.status != "queued":
            return None
        run.status = "running"
        await session.commit()
        try:
            offers = list(
                (
                    await session.scalars(
                        select(CatalogDiscoveryOffer).where(
                            CatalogDiscoveryOffer.discovery_run_id
                            == run.discovery_run_id,
                            # Наши собственные витрины не конкуренты сами себе.
                            CatalogDiscoveryOffer.is_owned.is_(False),
                        )
                    )
                ).all()
            )
            groups = group_candidate_offers(offers)
            summary = grouping_summary(groups, offer_count=len(offers))
            bounded = groups[: selected.catalog_match_max_groups]
            summary["groups_reviewed"] = len(bounded)
            summary["groups_dropped_by_limit"] = len(groups) - len(bounded)
            run.offer_count = len(offers)
            run.group_count = len(groups)
            run.grouping_summary = summary

            verdicts = await _review_groups(
                session, run=run, groups=bounded, settings=selected, provider=provider
            )
            minimum_discount, price_tick = _price_policy(selected)
            outcome = summarize_catalog_match(
                bounded,
                verdicts,
                minimum_discount=minimum_discount,
                price_tick=price_tick,
            )
            run.reviewed_group_count = len(verdicts)
            run.comparable_group_count = outcome.comparable_group_count
            run.minimum_comparable_price = outcome.minimum_comparable_price
            run.advisory_price = outcome.advisory_price
            run.currency = outcome.currency
            run.status = "completed"
            run.finished_at = datetime.now(UTC)
            await session.commit()
            return run.id
        except Exception as exc:
            await session.rollback()
            failed = await session.get(CatalogMatchRun, match_run_id)
            if failed is not None:
                failed.status = "failed"
                failed.error_code = str(getattr(exc, "code", type(exc).__name__))[:100]
                failed.error_detail = str(exc)[:2000]
                failed.finished_at = datetime.now(UTC)
                await session.commit()
            raise


async def _review_groups(
    session: Any,
    *,
    run: CatalogMatchRun,
    groups: Sequence[CandidateOfferGroup],
    settings: Settings,
    provider: ComparabilityProvider | None,
) -> dict[str, str]:
    if not groups:
        return {}
    discovery = await session.get(CatalogDiscoveryRun, run.discovery_run_id)
    plan = NoOeQueryPlan(
        queries=(discovery.query,),
        source_fields=("catalog_discovery_run",),
        frozen_input_sha256=canonical_sha256(
            {"discovery_run_id": str(run.discovery_run_id), "query": discovery.query}
        ),
    )
    offers_by_id = {
        offer.id: offer
        for offer in (
            await session.scalars(
                select(CatalogDiscoveryOffer).where(
                    CatalogDiscoveryOffer.discovery_run_id == run.discovery_run_id
                )
            )
        ).all()
    }
    prompt_hash = hashlib.sha256(_SYSTEM_INSTRUCTIONS.encode()).hexdigest()
    schema_hash = canonical_sha256(_strict_output_schema())
    model_hash = canonical_sha256(
        {
            "provider": settings.pricing_llm_provider,
            "model": settings.pricing_llm_model,
            "reasoning_effort": settings.pricing_llm_reasoning_effort,
        }
    )

    prepared: list[tuple[CandidateOfferGroup, dict[str, Any], str]] = []
    for group in groups:
        representative = offers_by_id.get(group.representative_id)
        if representative is None:
            continue
        input_snapshot = build_no_oe_review_input(
            start_snapshot=run.product_snapshot,
            exact_offer=offer_snapshot(representative),
            plan=plan,
            gate_assessment=_gate_assessment(group),
        )
        prepared.append((group, input_snapshot, canonical_sha256(input_snapshot)))

    cached = await _cached_verdicts(
        session,
        workspace_id=run.workspace_id,
        input_hashes=[input_hash for _, _, input_hash in prepared],
    )
    to_call = [item for item in prepared if item[2] not in cached]

    adapter = provider or _provider(settings)
    gate = asyncio.Semaphore(max(1, settings.pricing_llm_max_concurrency))

    async def _review(snapshot: dict[str, Any]) -> Any:
        async with gate:
            return await adapter.review(input_snapshot=snapshot, image_urls=())

    responses = await asyncio.gather(
        *(_review(snapshot) for _, snapshot, _ in to_call)
    )

    verdicts: dict[str, str] = {
        group.key: cached[input_hash]
        for group, _snapshot, input_hash in prepared
        if input_hash in cached
    }
    for (group, input_snapshot, input_hash), response in zip(
        to_call, responses, strict=True
    ):
        # Расход книжится до валидации: прогон, который не может назвать
        # потраченное, учит оператора неверной цене работы.
        call_usage, call_cost, call_rate_version = usage_and_cost_metadata(
            getattr(response, "usage", None), settings
        )
        validate_comparability_provider_output(
            input_snapshot=input_snapshot,
            output=response.output,
            image_urls=(),
        )
        output = response.output.model_dump(mode="json")
        verdict = _VERDICT_BY_IDENTITY[response.output.identity_verdict]
        verdicts[group.key] = verdict
        session.add(
            CatalogMatchReview(
                workspace_id=run.workspace_id,
                catalog_match_run_id=run.id,
                catalog_discovery_offer_id=group.representative_id,
                group_key=group.key,
                offer_ids=[str(value) for value in group.offer_ids],
                seller_ids=list(group.seller_ids),
                gate_rejected_reasons=list(group.rejected_reasons),
                verdict=verdict,
                rationale=response.output.rationale,
                evidence_references=[
                    reference.model_dump(mode="json")
                    for finding in response.output.dimension_findings
                    for reference in finding.evidence
                ],
                conflicts=[
                    value.model_dump(mode="json")
                    for value in response.output.hard_stop_conflicts
                ],
                prompt_sha256=prompt_hash,
                schema_sha256=schema_hash,
                model_sha256=model_hash,
                input_sha256=input_hash,
                output_sha256=canonical_sha256(output),
                provider=settings.pricing_llm_provider,
                model=settings.pricing_llm_model,
                reasoning_effort=settings.pricing_llm_reasoning_effort,
                canonical_input=input_snapshot,
                canonical_output=output,
                usage=call_usage,
                estimated_cost=call_cost,
                rate_card_version=call_rate_version,
            )
        )
    return verdicts


async def catalog_match_spend(session: Any, *, match_run_id: UUID) -> Decimal:
    """What one click actually cost, read from its own reviews.

    A third cost table nobody sums is how $0.83 went unnoticed on 2026-08-21:
    the panel's query read one lane's table while the other lane was spending.
    This lane's number therefore travels with the click that caused it.
    """

    rows = (
        await session.scalars(
            select(CatalogMatchReview.estimated_cost).where(
                CatalogMatchReview.catalog_match_run_id == match_run_id
            )
        )
    ).all()
    total = Decimal("0")
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        value = row.get("total_usd")
        if value is None:
            continue
        try:
            total += Decimal(str(value))
        except (ArithmeticError, ValueError):
            continue
    return total


async def _cached_verdicts(
    session: Any, *, workspace_id: UUID, input_hashes: Sequence[str]
) -> dict[str, str]:
    """Reuse an identical earlier answer instead of buying it again.

    A second click on a card nobody touched must not cost a second time. The
    key is the input snapshot's hash, so any change to our product, to the
    candidate, or to the gate reasons makes it a different question.
    """

    if not input_hashes:
        return {}
    rows = (
        await session.execute(
            select(CatalogMatchReview.input_sha256, CatalogMatchReview.verdict).where(
                CatalogMatchReview.workspace_id == workspace_id,
                CatalogMatchReview.input_sha256.in_(list(input_hashes)),
            )
        )
    ).all()
    return {input_hash: verdict for input_hash, verdict in rows}


__all__ = [
    "CATALOG_MATCH_CONTRACT_VERSION",
    "COMPARABLE_VERDICT",
    "CatalogMatchError",
    "CatalogMatchOutcome",
    "catalog_match_spend",
    "process_catalog_match_run",
    "start_catalog_match",
    "summarize_catalog_match",
]
