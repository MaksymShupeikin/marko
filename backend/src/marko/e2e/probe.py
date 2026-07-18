"""Secret-safe state and failure-injection probes for the disposable E2E stack."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import time
from uuid import UUID

from sqlalchemy import func, select

from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    PricingRecommendation,
    PricingRunItem,
    RecommendationDecision,
    ScrapeAttempt,
    ScrapeEvidenceBlob,
    ScrapeHttpAttempt,
    ScrapeHttpRequest,
    ScrapeTarget,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.scrape_journal import EvidenceIntegrityError, load_replay_cache
from marko.worker.celery_app import celery_app


def _require_e2e() -> None:
    settings = get_settings()
    if not (
        settings.environment.strip().casefold() == "e2e" and settings.e2e_auth_bypass
    ):
        raise RuntimeError("E2E probes are isolated to authenticated E2E mode")


async def inspect_run(run_id: UUID) -> dict[str, object]:
    _require_e2e()
    async with async_session_factory() as session:
        items = list(
            (
                await session.scalars(
                    select(PricingRunItem)
                    .where(PricingRunItem.pricing_run_id == run_id)
                    .order_by(PricingRunItem.id)
                )
            ).all()
        )
        targets = list(
            (
                await session.scalars(
                    select(ScrapeTarget)
                    .where(ScrapeTarget.pricing_run_id == run_id)
                    .order_by(ScrapeTarget.id)
                )
            ).all()
        )
        recommendations = list(
            (
                await session.scalars(
                    select(PricingRecommendation)
                    .where(PricingRecommendation.pricing_run_id == run_id)
                    .order_by(PricingRecommendation.id)
                )
            ).all()
        )
        attempts = list(
            (
                await session.scalars(
                    select(ScrapeAttempt)
                    .join(
                        ScrapeTarget, ScrapeTarget.id == ScrapeAttempt.scrape_target_id
                    )
                    .where(ScrapeTarget.pricing_run_id == run_id)
                )
            ).all()
        )
        decisions = int(
            await session.scalar(
                select(func.count(RecommendationDecision.id))
                .join(
                    PricingRecommendation,
                    PricingRecommendation.id
                    == RecommendationDecision.recommendation_id,
                )
                .where(PricingRecommendation.pricing_run_id == run_id)
            )
            or 0
        )
        request_kinds = list(
            (
                await session.scalars(
                    select(ScrapeHttpRequest.request_kind)
                    .join(
                        ScrapeTarget,
                        ScrapeTarget.id == ScrapeHttpRequest.scrape_target_id,
                    )
                    .where(ScrapeTarget.pricing_run_id == run_id)
                )
            ).all()
        )
        physical_http_attempt_count = int(
            await session.scalar(
                select(func.count(ScrapeHttpAttempt.id))
                .join(
                    ScrapeHttpRequest,
                    ScrapeHttpRequest.id == ScrapeHttpAttempt.logical_request_id,
                )
                .join(
                    ScrapeTarget,
                    ScrapeTarget.id == ScrapeHttpRequest.scrape_target_id,
                )
                .where(ScrapeTarget.pricing_run_id == run_id)
            )
            or 0
        )
    return {
        "run_id": str(run_id),
        "item_ids": [str(item.id) for item in items],
        "item_statuses": dict(sorted(Counter(item.status for item in items).items())),
        "targets": [
            {
                "id": str(target.id),
                "status": target.status,
                "source_type": target.source_type,
                "source_lane": target.source_lane,
                "network_attempts": target.network_attempts,
                "fencing_token": target.fencing_token,
                "owner_present": bool(target.owner_task_id),
            }
            for target in targets
        ],
        "recommendations": [
            {
                "id": str(item.id),
                "action": item.action,
                "recommended_price": (
                    str(item.recommended_price)
                    if item.recommended_price is not None
                    else None
                ),
                "automatic_eligible": item.automatic_eligible,
                "decision_fingerprint": item.decision_fingerprint,
            }
            for item in recommendations
        ],
        "recommendation_count": len(recommendations),
        "decision_count": decisions,
        "attempt_statuses": dict(
            sorted(Counter(attempt.status for attempt in attempts).items())
        ),
        "logical_request_count": len(request_kinds),
        # Logical requests also exist for deterministic evidence replays. Only
        # physical HTTP attempt rows prove that live network I/O occurred.
        "live_network_request_count": physical_http_attempt_count,
    }


async def wait_for_unseeded_collection(run_id: UUID, timeout_seconds: float) -> dict:
    _require_e2e()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        async with async_session_factory() as session:
            target = await session.scalar(
                select(ScrapeTarget)
                .where(
                    ScrapeTarget.pricing_run_id == run_id,
                    ScrapeTarget.evidence_status == "NONE",
                    ScrapeTarget.status == "collecting",
                )
                .order_by(ScrapeTarget.id)
            )
            if target is not None:
                return {
                    "status": "COLLECTING",
                    "target_id": str(target.id),
                    "fencing_token": target.fencing_token,
                }
        await asyncio.sleep(0.25)
    raise TimeoutError("Unseeded replay target did not enter collecting state")


async def dispatch_duplicate(run_id: UUID) -> dict[str, object]:
    _require_e2e()
    async with async_session_factory() as session:
        item_id = await session.scalar(
            select(PricingRunItem.id)
            .where(PricingRunItem.pricing_run_id == run_id)
            .order_by(PricingRunItem.id)
            .limit(1)
        )
    if item_id is None:
        raise RuntimeError("Pricing run has no item to redeliver")
    task = celery_app.send_task(
        "marko.worker.calculate_pricing_item",
        args=[str(item_id)],
        queue="pricing-calculation",
    )
    return {"status": "DISPATCHED", "item_id": str(item_id), "task_id": task.id}


async def tamper_probe(run_id: UUID) -> dict[str, object]:
    """Corrupt evidence inside one transaction and require integrity rejection."""

    _require_e2e()
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(ScrapeTarget, ScrapeEvidenceBlob)
                .join(
                    ScrapeHttpRequest,
                    ScrapeHttpRequest.scrape_target_id == ScrapeTarget.id,
                )
                .join(
                    ScrapeEvidenceBlob,
                    ScrapeEvidenceBlob.id == ScrapeHttpRequest.evidence_blob_id,
                )
                .where(ScrapeTarget.pricing_run_id == run_id)
                .order_by(ScrapeTarget.id)
                .limit(1)
            )
        ).first()
        if row is None:
            raise RuntimeError("Run has no retained evidence to tamper")
        target, blob = row
        original = blob.content_zlib
        blob.content_zlib = b"deliberately-corrupted-e2e-evidence"
        await session.flush()
        rejected = False
        try:
            await load_replay_cache(session, scrape_target_id=target.id)
        except EvidenceIntegrityError:
            rejected = True
        finally:
            blob.content_zlib = original
            await session.commit()
        if not rejected:
            raise RuntimeError("Tampered evidence was silently accepted")
        return {
            "status": "PASS",
            "reason": "EVIDENCE_INTEGRITY_REJECTED",
            "target_id": str(target.id),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=UUID)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--dispatch-duplicate", action="store_true")
    actions.add_argument("--tamper-evidence", action="store_true")
    actions.add_argument("--wait-for-unseeded-collecting", type=float)
    args = parser.parse_args()
    if args.dispatch_duplicate:
        result = asyncio.run(dispatch_duplicate(args.run_id))
    elif args.tamper_evidence:
        result = asyncio.run(tamper_probe(args.run_id))
    elif args.wait_for_unseeded_collecting is not None:
        result = asyncio.run(
            wait_for_unseeded_collection(
                args.run_id,
                args.wait_for_unseeded_collecting,
            )
        )
    else:
        result = asyncio.run(inspect_run(args.run_id))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
