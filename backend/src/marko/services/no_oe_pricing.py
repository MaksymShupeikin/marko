"""Bounded no-OE discovery, Luna review, human decisions, and safe resume."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import Settings, get_settings
from marko.infrastructure.db.models import (
    CatalogDiscoveryOffer,
    CatalogItem,
    PricingDiscoveryDecision,
    PricingDiscoveryReview,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.catalog_discovery import collect_catalog_discovery
from marko.services.catalog_identity_safety import is_internal_catalog_code
from marko.services.decision_fingerprint import canonical_sha256
from marko.services.llm_comparability import (
    CodexCliComparabilityProvider,
    ComparabilityProvider,
    IdentityVerdict,
    OpenAIResponsesComparabilityProvider,
    _SYSTEM_INSTRUCTIONS,
    _strict_output_schema,
    usage_and_cost_metadata,
    validate_comparability_provider_output,
)
from marko.services.market_collection import _validated_listing_url
from marko.services.market_collection import fail_pricing_item
from marko.services.offer_integrity import (
    OfferIntegrityStatus,
    assess_offer_integrity,
    assessment_from_context,
    build_offer_amount_context,
)


NO_OE_QUERY_PLAN_VERSION = "no-oe-query-plan-v1"
NO_OE_REVIEW_CONTRACT_VERSION = "no-oe-review-v1"
_PROM_PRODUCT_ID = re.compile(r"^\d{8,12}$")
_PRIVATE_MODEL_KEY_MARKERS = (
    "price",
    "cost",
    "recommended",
    "desired",
    "цен",
    "цін",
    "себесто",
)
_PUBLIC_PRODUCT_FIELDS = frozenset(
    {
        "sku",
        "mpn_norm",
        "mpn_raw",
        "brand",
        "name",
        "category",
        "description",
        "part_numbers_norm",
        "applicability_brands",
        "applicability_models",
        "characteristics_raw",
    }
)


class NoOePricingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class NoOeQueryPlan:
    queries: tuple[str, ...]
    source_fields: tuple[str, ...]
    frozen_input_sha256: str
    planner_version: str = NO_OE_QUERY_PLAN_VERSION


def plan_no_oe_queries(snapshot: Mapping[str, Any]) -> NoOeQueryPlan:
    """Use only frozen public fields and prove each query's provenance."""

    frozen_hash = canonical_sha256(snapshot)
    candidates: list[tuple[str, str]] = []
    for field in ("mpn_norm", "mpn_raw"):
        value = " ".join(str(snapshot.get(field) or "").split())
        if value and not is_internal_catalog_code(value):
            candidates.append((field, value))
            break
    sku = " ".join(str(snapshot.get("sku") or "").split())
    if (
        sku
        and not is_internal_catalog_code(sku)
        and not _PROM_PRODUCT_ID.fullmatch(sku)
    ):
        candidates.append(("sku", sku))
    descriptive = " ".join(
        str(snapshot.get(field) or "").strip()
        for field in ("brand", "name", "category")
        if str(snapshot.get(field) or "").strip()
    )[:255]
    if descriptive:
        candidates.append(("brand+name+category", descriptive))
    result: list[tuple[str, str]] = []
    frozen_text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    for field, query in candidates:
        if is_internal_catalog_code(query):
            continue
        for match in re.findall(r"776[0-9A-ZА-Я]{1,9}", query.upper()):
            if is_internal_catalog_code(match):
                raise NoOePricingError(
                    "PRIVATE_KEMP_QUERY_BLOCKED", "query contains a private KEMP key"
                )
        if field != "brand+name+category" and query not in frozen_text:
            raise NoOePricingError(
                "INVENTED_QUERY_TOKEN", "query token is absent from frozen input"
            )
        if query not in {value for _, value in result}:
            result.append((field, query))
    if not result:
        raise NoOePricingError(
            "NO_SAFE_PUBLIC_QUERY", "frozen item has no safe public discovery query"
        )
    return NoOeQueryPlan(
        queries=tuple(value for _, value in result[:2]),
        source_fields=tuple(field for field, _ in result[:2]),
        frozen_input_sha256=frozen_hash,
    )


def offer_snapshot(offer: CatalogDiscoveryOffer) -> dict[str, Any]:
    return {
        "offer_id": str(offer.id),
        "source_listing_id": offer.source_listing_id,
        "seller_id": offer.seller_id,
        "seller_name": offer.seller_name,
        "title": offer.title,
        "url": offer.url,
        "sku": offer.sku,
        "brand": offer.brand,
        "sale_price": str(offer.sale_price),
        "currency": offer.currency,
        "measure_unit": offer.measure_unit,
        "is_available": offer.is_available,
        "is_owned": offer.is_owned,
        "raw_snapshot": offer.raw_snapshot,
    }


def _without_pricing_fields(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _without_pricing_fields(child)
            for key, child in value.items()
            if not any(
                marker in str(key).casefold() for marker in _PRIVATE_MODEL_KEY_MARKERS
            )
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_without_pricing_fields(child) for child in value]
    return value


def build_no_oe_review_input(
    *,
    start_snapshot: Mapping[str, Any],
    exact_offer: Mapping[str, Any],
    plan: NoOeQueryPlan,
    offer_integrity_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical Luna input with identity plus bounded public amount integrity.

    Procurement cost, desired/recommended price and private KEMP keys remain
    forbidden.  The public displayed amount and neighbouring seller amounts are
    exposed only inside a server-authored commercial-integrity context; Luna
    cannot choose or calculate the recommendation.
    """

    public_product = {
        key: value
        for key, value in start_snapshot.items()
        if key in _PUBLIC_PRODUCT_FIELDS
    }
    sku = str(public_product.get("sku") or "").strip()
    if is_internal_catalog_code(sku) or _PROM_PRODUCT_ID.fullmatch(sku):
        public_product.pop("sku", None)
    payload = {
        "contract_version": NO_OE_REVIEW_CONTRACT_VERSION,
        "our_product": public_product,
        "candidate": dict(exact_offer),
        "deterministic_context": {
            "no_confirmed_oe": True,
            "pricing_admission": "MANUAL_REVIEW_ONLY",
            "query_plan": {
                "queries": list(plan.queries),
                "source_fields": list(plan.source_fields),
                "frozen_input_sha256": plan.frozen_input_sha256,
            },
            "offer_integrity_context": dict(offer_integrity_context or {}),
        },
    }
    scrubbed = _without_pricing_fields(payload)
    serialized = json.dumps(scrubbed, ensure_ascii=False, sort_keys=True)
    for match in re.findall(r"776[0-9A-ZА-Я]{1,9}", serialized.upper()):
        if is_internal_catalog_code(match):
            raise NoOePricingError(
                "PRIVATE_KEMP_MODEL_INPUT_BLOCKED",
                "canonical Luna input contains a private KEMP key",
            )
    return scrubbed


def _provider(settings: Settings) -> ComparabilityProvider:
    if settings.pricing_llm_provider == "codex_cli":
        return CodexCliComparabilityProvider(settings)
    return OpenAIResponsesComparabilityProvider(settings)


async def fail_no_oe_discovery_batch(run_item_id: UUID, error: Exception) -> None:
    """Stop every still-discovering item after an upstream access block."""

    async with async_session_factory() as session:
        anchor = await session.get(PricingRunItem, run_item_id)
        if anchor is None:
            return
        item_ids = list(
            (
                await session.scalars(
                    select(PricingRunItem.id).where(
                        PricingRunItem.pricing_run_id == anchor.pricing_run_id,
                        PricingRunItem.status == "discovering",
                    )
                )
            ).all()
        )
    for item_id in item_ids:
        await fail_pricing_item(item_id, error)


async def _stop_cancelled_no_oe_item(session: Any, run_item: Any) -> None:
    """Close one no-OE position because the operator cancelled the run.

    The OE lane has had this since the beginning (``market_collection`` checks
    ``cancel_requested`` before it materialises evidence).  This lane did not,
    and on 2026-08-21 it kept calling the paid provider for nine hours after a
    cancel, spending $0.83 that no one could see because the panel's query read
    the other lane's table.
    """

    run_item.status = "cancelled"
    run_item.finished_at = datetime.now(UTC)
    await session.commit()
    return None


async def process_no_oe_discovery_item(
    run_item_id: UUID,
    *,
    settings: Settings | None = None,
    provider: ComparabilityProvider | None = None,
) -> UUID | None:
    selected = settings or get_settings()
    if not selected.pricing_no_oe_discovery_enabled:
        return None
    async with async_session_factory() as session:
        run_item = await session.scalar(
            select(PricingRunItem)
            .where(PricingRunItem.id == run_item_id)
            .with_for_update()
        )
        if run_item is None or run_item.status not in {
            "discovering",
            "awaiting_discovery_review",
        }:
            return None
        if run_item.status == "awaiting_discovery_review":
            return run_item.pricing_run_id
        run = await session.get(PricingRun, run_item.pricing_run_id)
        if run is None:
            return None
        if run.cancel_requested:
            return await _stop_cancelled_no_oe_item(session, run_item)
        plan = plan_no_oe_queries(run_item.start_snapshot)
        query = plan.queries[0]
        snapshot = await collect_catalog_discovery(
            session,
            workspace_id=run.workspace_id,
            sku=None,
            oe=None,
            mpn=None,
            brand=str(run_item.start_snapshot.get("brand") or "") or None,
            title=str(run_item.start_snapshot.get("name") or "") or None,
            current_price=None,
            currency=str(run_item.start_snapshot.get("currency") or "UAH"),
            category=str(run_item.start_snapshot.get("category") or "") or None,
            settings=selected,
            safe_query_override=query,
        )
        run_item.no_oe_discovery_run_id = snapshot.run_id
        await session.commit()
        # Живой сбор длится 2–4 минуты, и сразу за ним уходит до десяти
        # параллельных платных вызовов. Отмена, нажатая во время сбора, обязана
        # быть замечена здесь — иначе повторяется 21.08, когда дорожка платила
        # ещё девять часов после отмены.
        if run.cancel_requested:
            return await _stop_cancelled_no_oe_item(session, run_item)
        offers = list(
            (
                await session.scalars(
                    select(CatalogDiscoveryOffer)
                    .where(
                        CatalogDiscoveryOffer.discovery_run_id == snapshot.run_id,
                        CatalogDiscoveryOffer.is_owned.is_(False),
                        CatalogDiscoveryOffer.selection_status != "REJECTED",
                    )
                    .order_by(
                        CatalogDiscoveryOffer.sale_price, CatalogDiscoveryOffer.id
                    )
                    .limit(selected.pricing_no_oe_max_provider_calls)
                )
            ).all()
        )
        offers = [
            offer
            for offer in offers
            if offer.seller_id.strip() and _validated_listing_url(offer.url)[0]
        ]
        adapter = provider or _provider(selected)
        prompt_hash = hashlib.sha256(_SYSTEM_INSTRUCTIONS.encode()).hexdigest()
        schema_hash = canonical_sha256(_strict_output_schema())
        model_hash = canonical_sha256(
            {
                "provider": selected.pricing_llm_provider,
                "model": selected.pricing_llm_model,
                "reasoning_effort": selected.pricing_llm_reasoning_effort,
            }
        )
        prepared_calls: list[
            tuple[CatalogDiscoveryOffer, str, dict[str, Any], str]
        ] = []
        for offer in offers:
            exact_offer = offer_snapshot(offer)
            exact_hash = canonical_sha256(exact_offer)
            integrity = assess_offer_integrity(
                title=offer.title,
                description=offer.raw_snapshot.get("description")
                if isinstance(offer.raw_snapshot, Mapping)
                else None,
                condition=offer.raw_snapshot.get("condition")
                if isinstance(offer.raw_snapshot, Mapping)
                else None,
                characteristics=offer.raw_snapshot.get("characteristics")
                if isinstance(offer.raw_snapshot, Mapping)
                else None,
                measure_unit=offer.measure_unit,
                is_available=offer.is_available,
                detail_evidence_safe=None,
            )
            amount_context = build_offer_amount_context(
                displayed_amount=offer.sale_price,
                currency=offer.currency,
                customer_amount=run_item.start_snapshot.get("current_price"),
                peer_offers=[
                    (peer.sale_price, peer.seller_id)
                    for peer in offers
                    if peer.id != offer.id
                ],
                assessment=integrity,
            )
            input_snapshot = build_no_oe_review_input(
                start_snapshot=run_item.start_snapshot,
                exact_offer=exact_offer,
                plan=plan,
                offer_integrity_context=amount_context.as_dict(),
            )
            input_hash = canonical_sha256(input_snapshot)
            prepared_calls.append((offer, exact_hash, input_snapshot, input_hash))

        # One provider call per offer, run under a shared semaphore instead of
        # one after another. At an average 99 s per call a ten-offer position
        # took ~16 minutes of pure waiting; the offers are independent, so the
        # only thing serialising them was this loop. The semaphore keeps the
        # provider seeing at most ``pricing_llm_max_concurrency`` calls, exactly
        # like the OE lane.
        gate = asyncio.Semaphore(max(1, selected.pricing_llm_max_concurrency))

        async def _review(snapshot: dict[str, Any]) -> Any:
            async with gate:
                return await adapter.review(input_snapshot=snapshot, image_urls=())

        responses = await asyncio.gather(
            *(_review(snapshot) for _, _, snapshot, _ in prepared_calls)
        )

        for (offer, exact_hash, input_snapshot, input_hash), response in zip(
            prepared_calls, responses, strict=True
        ):
            # Book the call before anything can reject its answer: a run that
            # cannot say what it spent on this lane teaches the operator a cost
            # that is not the real one.
            call_usage, call_cost, call_rate_version = usage_and_cost_metadata(
                getattr(response, "usage", None), selected
            )
            validate_comparability_provider_output(
                input_snapshot=input_snapshot,
                output=response.output,
                image_urls=(),
            )
            output = response.output.model_dump(mode="json")
            verdict = {
                IdentityVerdict.MATCH: "MATCH",
                IdentityVerdict.NOT_MATCH: "NO_MATCH",
                IdentityVerdict.MANUAL_REVIEW: "INSUFFICIENT_EVIDENCE",
            }[response.output.identity_verdict]
            session.add(
                PricingDiscoveryReview(
                    workspace_id=run.workspace_id,
                    pricing_run_id=run.id,
                    pricing_run_item_id=run_item.id,
                    catalog_discovery_offer_id=offer.id,
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
                    offer_sha256=exact_hash,
                    prompt_sha256=prompt_hash,
                    schema_sha256=schema_hash,
                    model_sha256=model_hash,
                    input_sha256=input_hash,
                    output_sha256=canonical_sha256(output),
                    provider=selected.pricing_llm_provider,
                    model=selected.pricing_llm_model,
                    reasoning_effort=selected.pricing_llm_reasoning_effort,
                    canonical_input=input_snapshot,
                    canonical_output=output,
                    usage=call_usage,
                    estimated_cost=call_cost,
                    rate_card_version=call_rate_version,
                )
            )
        run_item.status = "awaiting_discovery_review"
        run_item.checkpoint = {
            "stage": "awaiting_discovery_review",
            "query_plan": {
                "queries": list(plan.queries),
                "source_fields": list(plan.source_fields),
                "frozen_input_sha256": plan.frozen_input_sha256,
            },
            "offers_reviewed": len(offers),
        }
        run.status = "awaiting_review"
        await session.commit()
        return run.id


async def review_queue(
    session: AsyncSession, *, workspace_id: UUID, run_id: UUID
) -> dict[str, Any]:
    run = await session.scalar(
        select(PricingRun).where(
            PricingRun.id == run_id, PricingRun.workspace_id == workspace_id
        )
    )
    if run is None:
        raise NoOePricingError("RUN_NOT_FOUND", "pricing run was not found")
    rows = (
        await session.execute(
            select(
                PricingDiscoveryReview,
                CatalogDiscoveryOffer,
                PricingRunItem,
                CatalogItem,
            )
            .join(
                CatalogDiscoveryOffer,
                CatalogDiscoveryOffer.id
                == PricingDiscoveryReview.catalog_discovery_offer_id,
            )
            .join(
                PricingRunItem,
                PricingRunItem.id == PricingDiscoveryReview.pricing_run_item_id,
            )
            .join(CatalogItem, CatalogItem.id == PricingRunItem.catalog_item_id)
            .where(
                PricingDiscoveryReview.workspace_id == workspace_id,
                PricingDiscoveryReview.pricing_run_id == run_id,
            )
            .order_by(
                PricingRunItem.membership_position, CatalogDiscoveryOffer.sale_price
            )
        )
    ).all()
    decisions = list(
        (
            await session.scalars(
                select(PricingDiscoveryDecision)
                .where(
                    PricingDiscoveryDecision.workspace_id == workspace_id,
                    PricingDiscoveryDecision.pricing_run_id == run_id,
                )
                .order_by(
                    PricingDiscoveryDecision.created_at, PricingDiscoveryDecision.id
                )
            )
        ).all()
    )
    latest = {decision.catalog_discovery_offer_id: decision for decision in decisions}
    items = []
    for review, offer, run_item, catalog_item in rows:
        if canonical_sha256(offer_snapshot(offer)) != review.offer_sha256:
            raise NoOePricingError(
                "OFFER_SNAPSHOT_CHANGED",
                "a discovery offer changed after Luna review",
            )
        decision = latest.get(offer.id)
        items.append(
            {
                "offer_id": offer.id,
                "run_item_id": run_item.id,
                "catalog_item_id": catalog_item.id,
                "source_name": catalog_item.name,
                "source_sku": catalog_item.sku,
                "source_internal_code": catalog_item.internal_code_norm or None,
                "candidate_title": offer.title,
                "candidate_url": offer.url,
                "seller_id": offer.seller_id,
                "seller_name": offer.seller_name,
                "price": offer.sale_price,
                "currency": offer.currency,
                "measure_unit": offer.measure_unit,
                "is_available": offer.is_available,
                "offer_sha256": review.offer_sha256,
                "luna_review_id": review.id,
                "luna_verdict": review.verdict,
                "luna_rationale": review.rationale,
                "evidence_references": review.evidence_references,
                "conflicts": review.conflicts,
                "decision": decision.decision if decision else None,
                "decision_reason": decision.reason if decision else None,
                "decision_id": decision.id if decision else None,
                "decision_actor_id": decision.actor_id if decision else None,
                "decision_created_at": decision.created_at if decision else None,
            }
        )
    snapshot_hash = canonical_sha256(
        [
            {
                "offer_id": str(item["offer_id"]),
                "offer_sha256": item["offer_sha256"],
                "decision": item["decision"],
                "decision_reason": item["decision_reason"],
                "decision_id": (
                    str(item["decision_id"]) if item["decision_id"] else None
                ),
                "decision_actor_id": item["decision_actor_id"],
                "decision_created_at": (
                    item["decision_created_at"].isoformat()
                    if item["decision_created_at"]
                    else None
                ),
            }
            for item in items
        ]
    )
    return {
        "run_id": run.id,
        "run_status": run.status,
        "review_snapshot_hash": snapshot_hash,
        "items": items,
    }


async def decide_offer(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    run_id: UUID,
    offer_id: UUID,
    decision: str,
    reason: str,
    idempotency_key: str,
    expected_offer_sha256: str,
    actor_id: str,
    actor_type: str = "USER",
) -> PricingDiscoveryDecision:
    existing = await session.scalar(
        select(PricingDiscoveryDecision).where(
            PricingDiscoveryDecision.workspace_id == workspace_id,
            PricingDiscoveryDecision.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.pricing_run_id != run_id
            or existing.catalog_discovery_offer_id != offer_id
            or existing.decision != decision
            or existing.reason != reason.strip()
            or existing.offer_sha256 != expected_offer_sha256
            or existing.actor_id != actor_id
            or existing.actor_type != actor_type
        ):
            raise NoOePricingError("IDEMPOTENCY_CONFLICT", "idempotency key was reused")
        return existing
    row = (
        await session.execute(
            select(
                PricingDiscoveryReview,
                CatalogDiscoveryOffer,
                PricingRunItem,
                PricingRun,
            )
            .join(
                CatalogDiscoveryOffer,
                CatalogDiscoveryOffer.id
                == PricingDiscoveryReview.catalog_discovery_offer_id,
            )
            .join(
                PricingRunItem,
                PricingRunItem.id == PricingDiscoveryReview.pricing_run_item_id,
            )
            .join(PricingRun, PricingRun.id == PricingRunItem.pricing_run_id)
            .where(
                PricingDiscoveryReview.workspace_id == workspace_id,
                PricingDiscoveryReview.pricing_run_id == run_id,
                PricingDiscoveryReview.catalog_discovery_offer_id == offer_id,
                PricingRun.workspace_id == workspace_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise NoOePricingError("OFFER_NOT_FOUND", "offer is outside this run/workspace")
    review, offer, run_item, run = row
    if (
        run.status != "awaiting_review"
        or run_item.status != "awaiting_discovery_review"
    ):
        raise NoOePricingError("REVIEW_NOT_ACTIVE", "run item is not awaiting review")
    current_snapshot = offer_snapshot(offer)
    current_hash = canonical_sha256(current_snapshot)
    if review.offer_sha256 != current_hash or expected_offer_sha256 != current_hash:
        raise NoOePricingError("OFFER_SNAPSHOT_CHANGED", "offer snapshot hash changed")
    if offer.is_owned:
        raise NoOePricingError(
            "OWNED_SELLER_FORBIDDEN", "owned seller cannot be approved"
        )
    if not offer.seller_id.strip():
        raise NoOePricingError(
            "SELLER_ID_REQUIRED",
            "an offer without an exact seller ID cannot be independent evidence",
        )
    if _validated_listing_url(offer.url)[0] is None:
        raise NoOePricingError(
            "EXACT_LISTING_URL_REQUIRED",
            "an offer without an exact safe listing URL cannot be approved",
        )
    if decision == "APPROVE" and (review.verdict != "MATCH" or bool(review.conflicts)):
        raise NoOePricingError(
            "LUNA_MATCH_REQUIRED",
            "only a conflict-free positive Luna review can enter manual approval",
        )
    integrity_context = review.canonical_input.get("deterministic_context", {})
    integrity_context = (
        integrity_context.get("offer_integrity_context", {})
        if isinstance(integrity_context, Mapping)
        else {}
    )
    integrity = assessment_from_context(
        integrity_context if isinstance(integrity_context, Mapping) else None
    )
    if decision == "APPROVE" and integrity.status is not OfferIntegrityStatus.PASS:
        raise NoOePricingError(
            "OFFER_INTEGRITY_REVIEW_REQUIRED",
            "a commercially suspicious displayed amount cannot be approved",
        )
    if decision == "APPROVE" and not offer.is_available:
        raise NoOePricingError(
            "UNAVAILABLE_OFFER_FORBIDDEN",
            "an unavailable offer cannot enter pricing evidence",
        )
    record = PricingDiscoveryDecision(
        workspace_id=workspace_id,
        pricing_run_id=run_id,
        pricing_run_item_id=run_item.id,
        catalog_discovery_offer_id=offer.id,
        luna_review_id=review.id,
        decision=decision,
        actor_id=actor_id,
        actor_type=actor_type,
        reason=reason.strip(),
        idempotency_key=idempotency_key,
        offer_sha256=current_hash,
        price=offer.sale_price,
        currency=offer.currency,
        measure_unit=offer.measure_unit,
        is_available=offer.is_available,
        seller_id=offer.seller_id,
        offer_snapshot=current_snapshot,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


# Дорожка без OE считает не по статистической модели OE-дорожки, а по
# минимальной одобренной человеком цене.  Её повтор поэтому обязан быть
# ОТДЕЛЬНЫМ контрактом: версии ``recommendation-replay-v*`` описывают вход,
# которого у этой рекомендации нет (наблюдения рынка, коэффициенты, политика).
NO_OE_REPLAY_CONTRACT_V1 = "no-oe-human-approved-replay-v1"


def _five_percent_below(value: Decimal) -> Decimal:
    return (value * Decimal("0.95")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


async def resume_pricing_run(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    run_id: UUID,
    expected_review_snapshot_hash: str,
    min_sellers: int,
) -> PricingRun:
    run = await session.scalar(
        select(PricingRun)
        .where(PricingRun.id == run_id, PricingRun.workspace_id == workspace_id)
        .with_for_update()
    )
    if run is None:
        raise NoOePricingError("RUN_NOT_FOUND", "pricing run was not found")
    if run.status != "awaiting_review":
        raise NoOePricingError("RUN_NOT_AWAITING_REVIEW", "run is not awaiting review")
    queue = await review_queue(session, workspace_id=workspace_id, run_id=run_id)
    if queue["review_snapshot_hash"] != expected_review_snapshot_hash:
        raise NoOePricingError("REVIEW_SNAPSHOT_CHANGED", "review decisions changed")
    run.review_snapshot_hash = expected_review_snapshot_hash
    run.review_frozen_at = datetime.now(UTC)
    run_items = list(
        (
            await session.scalars(
                select(PricingRunItem)
                .where(
                    PricingRunItem.pricing_run_id == run_id,
                    PricingRunItem.status == "awaiting_discovery_review",
                )
                .with_for_update()
            )
        ).all()
    )
    for run_item in run_items:
        run_item.status = "review_frozen"
        decisions = list(
            (
                await session.scalars(
                    select(PricingDiscoveryDecision)
                    .where(PricingDiscoveryDecision.pricing_run_item_id == run_item.id)
                    .order_by(
                        PricingDiscoveryDecision.created_at, PricingDiscoveryDecision.id
                    )
                )
            ).all()
        )
        latest = {
            decision.catalog_discovery_offer_id: decision for decision in decisions
        }
        approved = [
            decision for decision in latest.values() if decision.decision == "APPROVE"
        ]
        by_seller: dict[str, PricingDiscoveryDecision] = {}
        for value in approved:
            by_seller.setdefault(value.seller_id, value)
        source = run_item.start_snapshot
        calculated_at = datetime.now(UTC)
        enough = len(by_seller) >= min_sellers
        fair_price = min((value.price for value in by_seller.values()), default=None)
        recommended_price = (
            _five_percent_below(fair_price) if enough and fair_price else None
        )
        current_price = Decimal(str(source["current_price"]))
        reason_codes = [
            "NO_OE_HUMAN_APPROVED_OFFERS",
            "AUTOMATIC_ELIGIBILITY_FORCED_FALSE",
            "NO_GLOBAL_IDENTITY_CREATED",
        ]
        action = "MANUAL_REVIEW" if enough else "INSUFFICIENT_DATA"
        if not enough:
            reason_codes.append("INSUFFICIENT_INDEPENDENT_SELLERS")
        recommendation = PricingRecommendation(
            pricing_run_id=run.id,
            pricing_run_item_id=run_item.id,
            catalog_item_id=run_item.catalog_item_id,
            catalog_snapshot_id=run.import_batch_id,
            context_snapshot={
                **source,
                "review_snapshot_hash": expected_review_snapshot_hash,
                "approved_decision_ids": [
                    str(value.id) for value in by_seller.values()
                ],
            },
            calculation_trace={
                "replay_contract_version": NO_OE_REPLAY_CONTRACT_V1,
                "calculated_at": calculated_at.isoformat(),
                # Порог продавцов — НАСТРОЙКА развёртывания, и она уже менялась
                # на живом проекте.  Повтор, читающий её из текущего окружения,
                # повторял бы не тот расчёт, что был выполнен: смена порога
                # молча переписала бы историю.  Он хранится здесь.
                "min_independent_sellers": min_sellers,
                "method": "human-approved-no-oe-lowest-minus-5pct-v1",
                "market_basis": "minimum_human_approved_comparable_price",
                "discount": "0.05",
                "offer_hashes": [value.offer_sha256 for value in by_seller.values()],
                "automatic_publication": False,
                "operator_cost_warning": (
                    "Account for procurement, Prom commission, payment fees, taxes, "
                    "packaging, delivery, returns, warranty, and minimum margin before "
                    "accepting the recommendation."
                ),
            },
            action=action,
            current_price=current_price,
            fair_price=fair_price,
            recommended_price=recommended_price,
            lower_bound=recommended_price,
            upper_bound=recommended_price,
            confidence=Decimal("0"),
            confidence_grade="MANUAL",
            weakest_factor="identity",
            factor_scores={"identity": "0"},
            competitor_count=len(by_seller),
            raw_competitor_count=len(latest),
            unique_seller_count=len(by_seller),
            clean_competitor_count=len(by_seller),
            target_market_count=len(by_seller),
            kemp_reference_count=0,
            owned_store_count=0,
            rejected_count=len(latest) - len(by_seller),
            effective_competitor_count=Decimal(len(by_seller)),
            dispersion=None,
            outlier_method="none",
            outlier_count=0,
            sensitivity=None,
            action_gates_passed=False,
            automatic_eligible=False,
            verified_seller_count=len(by_seller),
            comparability_policy_id=None,
            comparability_policy_hash=None,
            decision_fingerprint=canonical_sha256(
                {
                    "run_item_id": str(run_item.id),
                    "review_snapshot_hash": expected_review_snapshot_hash,
                    "decision_ids": [str(value.id) for value in by_seller.values()],
                }
            ),
            hard_gate_trace={"identity": "MANUAL_NO_OE"},
            robust_diagnostic=None,
            cost_floor=None,
            cost_basis_inventory_value=None,
            priority_score=Decimal("0"),
            priority_score_type="none",
            review_priority=Decimal("1"),
            absolute_recommended_change=(
                abs(recommended_price - current_price) if recommended_price else None
            ),
            percentage_recommended_change=(
                abs(recommended_price - current_price) / current_price
                if recommended_price
                else None
            ),
            reason_codes=reason_codes,
            evidence_observation_ids=[],
            kemp_reference_observation_ids=[],
            excluded_observations=[],
            policy_version=run.policy_version,
            parser_version=run.parser_version,
            classifier_version=run.classifier_version,
            coefficient_version=run.coefficient_version,
            calibration_dataset_hash=run.calibration_dataset_hash,
            currency=str(source.get("currency") or "UAH")[:3],
            price_tick=Decimal("0.01"),
            price_tick_version="manual-no-oe-v1",
        )
        session.add(recommendation)
        run_item.status = "manual_review"
        run_item.finished_at = calculated_at
        run_item.checkpoint = {
            "stage": "manual_no_oe_calculated",
            "action": action,
            "review_snapshot_hash": expected_review_snapshot_hash,
        }
    run.status = "collecting"
    await session.commit()
    await session.refresh(run)
    return run


__all__ = [
    "NO_OE_REPLAY_CONTRACT_V1",
    "NoOePricingError",
    "NoOeQueryPlan",
    "build_no_oe_review_input",
    "decide_offer",
    "fail_no_oe_discovery_batch",
    "plan_no_oe_queries",
    "process_no_oe_discovery_item",
    "resume_pricing_run",
    "review_queue",
]
