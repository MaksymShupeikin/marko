#!/usr/bin/env python3
"""Measure P0 identity-spine overhead on the retained replay fixture.

The comparison is intentionally current-code A/B, not a fabricated historical
benchmark: ``boundary_only`` measures candidate validation, while
``verified_identity_spine`` adds OE extraction, verification, and source
confidence.  No network-capable object is constructed.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from statistics import median
import time
import tracemalloc
from types import SimpleNamespace

from marko.e2e.fixture_seed import (
    DEFAULT_FIXTURE,
    _load_fixture,
    _target_output,
)
from marko.services.offer_identity import (
    extract_oe_evidence,
    verify_offer_identity,
)
from marko.services.offer_processing import (
    AcceptedCandidate,
    assess_candidate_source,
    process_offer_candidate,
)
from marko.services.scraper_contract import PROM_ADAPTER_VERSION, QueryInput


def _percentile(values: list[float], fraction: Decimal) -> float:
    ordered = sorted(values)
    index = int(
        (Decimal(len(ordered)) * fraction).to_integral_value(rounding="ROUND_CEILING")
    )
    return ordered[max(0, min(index - 1, len(ordered) - 1))]


def _milliseconds(start_ns: int) -> float:
    return (time.perf_counter_ns() - start_ns) / 1_000_000


def benchmark(*, fixture_path: Path, iterations: int) -> dict[str, object]:
    fixture, raw_fixture, fixture_hash = _load_fixture(fixture_path)
    query_input = QueryInput.build("1K0 121 251")
    target = SimpleNamespace(
        adapter_version=PROM_ADAPTER_VERSION,
        input_kind="query",
        original_url=None,
        canonical_url=None,
        product_key=None,
        query=query_input.query,
        input_hash=query_input.input_hash,
    )
    output = _target_output(target, fixture, fixture_hash)
    records = output.candidate_records
    boundary_latencies: list[float] = []
    full_latencies: list[float] = []
    extraction_latencies: list[float] = []
    verification_counts: dict[str, int] = {}

    for _ in range(iterations):
        for index, record in enumerate(records):
            started = time.perf_counter_ns()
            result = process_offer_candidate(record, fallback_index=index)
            boundary_latencies.append(_milliseconds(started))
            if not isinstance(result, AcceptedCandidate):
                raise RuntimeError("Replay benchmark fixture contains a rejected offer")

    tracemalloc.start()
    for _ in range(iterations):
        for index, record in enumerate(records):
            started = time.perf_counter_ns()
            result = process_offer_candidate(record, fallback_index=index)
            if not isinstance(result, AcceptedCandidate):
                raise RuntimeError("Replay benchmark fixture contains a rejected offer")
            extraction_started = time.perf_counter_ns()
            evidence = extract_oe_evidence(
                result.product,
                {
                    "source_record_id": result.source_listing_id,
                    "raw_capture_id": "00000000-0000-0000-0000-000000000001",
                    "raw_content_sha256": fixture_hash,
                },
            )
            extraction_latencies.append(_milliseconds(extraction_started))
            verification = verify_offer_identity(query_input.query, evidence)
            assess_candidate_source(
                result,
                raw_capture_verified=True,
                parser_contract_verified=True,
            )
            verification_counts[verification.status.value] = (
                verification_counts.get(verification.status.value, 0) + 1
            )
            full_latencies.append(_milliseconds(started))
    _, memory_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    def latency(values: list[float]) -> dict[str, float]:
        return {
            "p50_ms": round(median(values), 6),
            "p95_ms": round(_percentile(values, Decimal("0.95")), 6),
        }

    candidates = len(records)
    return {
        "schema_version": "prompt-15.017-replay-benchmark-v1",
        "measurement_kind": "current_code_ab_not_historical_build",
        "fixture_path": str(fixture_path.resolve()),
        "fixture_sha256": hashlib.sha256(raw_fixture).hexdigest(),
        "iterations": iterations,
        "samples_per_mode": iterations * candidates,
        "query_targets_total": 1,
        "candidates_per_query": {"p50": candidates, "p95": candidates},
        "before_boundary_only": {
            "offer_processing_latency": latency(boundary_latencies),
        },
        "after_verified_identity_spine": {
            "offer_processing_latency": latency(full_latencies),
            "oe_extraction_latency": latency(extraction_latencies),
            "verification_counts": dict(sorted(verification_counts.items())),
        },
        "memory_peak_bytes": memory_peak,
        "raw_storage_bytes": len(raw_fixture),
        "structured_storage_bytes": output.structured_size_bytes,
        "metadata_storage_bytes": output.metadata_size_bytes,
        "retry_amplification": "0",
        "physical_network_requests": 0,
        "detail_page_requests_per_query": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--iterations", type=int, default=500)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    print(
        json.dumps(
            benchmark(fixture_path=args.fixture, iterations=args.iterations),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
