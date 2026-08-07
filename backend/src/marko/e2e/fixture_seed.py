"""Seed immutable replay evidence into an E2E pricing run without live requests."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import zlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    ScrapeEvidenceBlob,
    ScrapeHttpRequest,
    ScrapeTarget,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.scraper_contract import (
    PROM_OUTPUT_SCHEMA_VERSION,
    ScrapeOutput,
    build_acquisition_input,
)
from metis.pricing import (
    comparison_evidence_to_dict,
    verified_comparison_evidence,
)

FIXTURE_SCHEMA_VERSION = "prompt-15.015-e2e-replay-v1"
DEFAULT_FIXTURE = Path(__file__).with_name("fixtures") / "pricing_replay_v1.json"


class E2eFixtureError(RuntimeError):
    pass


def _load_fixture(path: Path) -> tuple[dict, bytes, str]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise E2eFixtureError("Unsupported E2E fixture schema")
    offers = payload.get("offers")
    if not isinstance(offers, list) or len(offers) < 2:
        raise E2eFixtureError("E2E fixture requires at least two offers")
    return payload, raw, hashlib.sha256(raw).hexdigest()


def _target_output(
    target: ScrapeTarget, fixture: dict, fixture_hash: str
) -> ScrapeOutput:
    records: list[dict] = []
    for index, value in enumerate(fixture["offers"]):
        seller_id = str(value["seller_id"])
        source_record_id = str(value.get("source_record_id") or f"fixture-{index + 1}")
        evidence = verified_comparison_evidence(
            stable_seller_id=seller_id,
            source_record_id=source_record_id,
            raw_evidence_sha256=fixture_hash,
            retrieval_kind="fixture_replay",
            source_type="persisted_replay",
            parser_contract_version=target.adapter_version,
        )
        product = {
            "product_id": int(value.get("product_id", index + 1)),
            "seller_name": str(value.get("seller_name") or f"Seller {index + 1}"),
            "seller_id": seller_id,
            "price": str(value["price"]),
            "currency": str(value.get("currency", "UAH")),
            "presence": "available",
            "is_available": True,
            "name": str(value.get("name") or "E2E verified brake pad"),
            "brand": str(value.get("brand") or "Bosch"),
            "oe_raw": target.query,
            "condition": "NEW",
            "url": str(
                value.get("url")
                or f"https://prom.ua/ua/p{index + 1}-{source_record_id}.html"
            ),
        }
        records.append(
            {
                "raw_offer_index": index,
                "retrieval_kind": "fixture_replay",
                "retrieval_score": None,
                "product": product,
                "upstream_comparison_evidence": comparison_evidence_to_dict(evidence),
            }
        )
    prices = sorted(Decimal(item["product"]["price"]) for item in records)
    output_payload = {
        "acquisition_outcome": "RESULTS",
        "candidates_scanned": len(records),
        "records": records,
        "comparison_summary": {
            "seed": {"oe": target.query},
            "query": target.query,
            "stats": {
                "sellers_compared": len(records),
                "min_price": str(prices[0]),
                "median_price": str(prices[len(prices) // 2]),
                "max_price": str(prices[-1]),
            },
        },
    }
    input_kind = str(getattr(target, "input_kind", "product_seed"))
    scrape_input = build_acquisition_input(
        input_kind,
        target.query if input_kind == "query" else target.original_url,
        query=target.query,
        language="ua",
        adapter_version=target.adapter_version,
    )
    if scrape_input.input_hash != target.input_hash:
        raise E2eFixtureError(
            "Replay target input hash does not match its canonical acquisition input"
        )
    return ScrapeOutput.from_payload(
        {
            "schema_version": PROM_OUTPUT_SCHEMA_VERSION,
            "adapter_version": target.adapter_version,
            "input": scrape_input.as_dict(),
            "output": output_payload,
        }
    )


async def seed_fixture_replay(
    run_id: UUID,
    fixture_path: Path,
    *,
    max_targets: int | None = None,
) -> dict[str, object]:
    settings = get_settings()
    if not (
        settings.environment.strip().casefold() == "e2e" and settings.e2e_auth_bypass
    ):
        raise E2eFixtureError("Fixture seeding is isolated to authenticated E2E mode")
    fixture, raw_fixture, fixture_hash = _load_fixture(fixture_path)
    compressed = zlib.compress(raw_fixture, level=6)
    now = datetime.now(UTC)
    target_ids: list[str] = []
    output_hashes: list[str] = []
    async with async_session_factory() as session:
        targets = list(
            (
                await session.scalars(
                    select(ScrapeTarget)
                    .where(ScrapeTarget.pricing_run_id == run_id)
                    .order_by(ScrapeTarget.id)
                    .with_for_update()
                )
            ).all()
        )
        if not targets:
            raise E2eFixtureError("Pricing run has no replay targets")
        if max_targets is not None:
            if max_targets < 1:
                raise E2eFixtureError("max_targets must be positive")
            targets = targets[:max_targets]
        blob = await session.scalar(
            select(ScrapeEvidenceBlob).where(
                ScrapeEvidenceBlob.content_sha256 == fixture_hash
            )
        )
        if blob is None:
            blob = ScrapeEvidenceBlob(
                content_sha256=fixture_hash,
                content_zlib=compressed,
                raw_size_bytes=len(raw_fixture),
                stored_size_bytes=len(compressed),
                content_type="application/json",
                encoding="utf-8",
            )
            session.add(blob)
            await session.flush()
        for target in targets:
            output = _target_output(target, fixture, fixture_hash)
            request = await session.scalar(
                select(ScrapeHttpRequest).where(
                    ScrapeHttpRequest.scrape_target_id == target.id,
                    ScrapeHttpRequest.execution_no == 1,
                    ScrapeHttpRequest.sequence_no == 1,
                )
            )
            if request is None:
                session.add(
                    ScrapeHttpRequest(
                        sync_run_id=None,
                        scrape_target_id=target.id,
                        evidence_blob_id=blob.id,
                        execution_no=1,
                        sequence_no=1,
                        request_kind="fixture_replay",
                        request_key=hashlib.sha256(
                            f"{target.id}:{fixture_hash}".encode()
                        ).hexdigest(),
                        prepared_url=f"fixture://prompt-15.015/{fixture_hash}",
                        outcome="replayed",
                        replayed=True,
                        attempt_count=0,
                        response_status_code=200,
                        latency_ms=0,
                        rate_wait_ms=0,
                        backoff_ms=0,
                        error_category=None,
                        error_detail=None,
                        started_at=now,
                        finished_at=now,
                    )
                )
            target.source = "fixture"
            target.source_type = "persisted_replay"
            target.source_lane = "REPLAY"
            target.source_policy_state = "NOT_PERMITTED"
            target.status = "succeeded"
            target.execution_status = "SUCCEEDED"
            target.acquisition_status = "SUCCEEDED"
            target.parse_status = "SUCCEEDED"
            target.evidence_status = "STRUCTURED_AVAILABLE"
            target.downstream_eligibility = "UNKNOWN"
            target.operator_action = "NO_RECOMMENDATION"
            target.reason_codes = ["E2E_PERSISTED_REPLAY"]
            target.payload = output.payload
            target.content_sha256 = output.content_sha256
            target.parse_key = output.content_sha256
            target.raw_size_bytes = len(raw_fixture)
            target.structured_size_bytes = output.structured_size_bytes
            target.metadata_size_bytes = output.metadata_size_bytes
            target.structured_completeness = Decimal(
                str(output.structured_completeness)
            )
            target.error_category = None
            target.error_detail = None
            target.owner_task_id = None
            target.lease_expires_at = None
            target.finished_at = now
            target_ids.append(str(target.id))
            output_hashes.append(output.content_sha256)
        await session.commit()
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "run_id": str(run_id),
        "fixture_sha256": fixture_hash,
        "target_ids": target_ids,
        "output_sha256": sorted(output_hashes),
        "live_requests": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=UUID)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--max-targets", type=int)
    args = parser.parse_args()
    result = asyncio.run(
        seed_fixture_replay(
            args.run_id,
            args.fixture,
            max_targets=args.max_targets,
        )
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
