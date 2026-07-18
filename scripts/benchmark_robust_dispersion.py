#!/usr/bin/env python3
"""Deterministic, network-free exact Sn/Qn capacity benchmark."""

from __future__ import annotations

import argparse
from decimal import Decimal, getcontext
import json
from pathlib import Path
import platform
from statistics import median
import sys
from time import perf_counter_ns
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from metis.pricing.statistics import (  # noqa: E402
    qn_scale,
    robust_price_dispersion,
    sn_scale,
)


DEFAULT_SAMPLE_SIZES = (10, 25, 50, 100, 250, 500)


def _sample(sample_size: int) -> tuple[Decimal, ...]:
    return tuple(
        Decimal(100_000 + ((index * 7919) % 10_007)) / Decimal("100")
        for index in range(sample_size)
    )


def _median_ms(call: Callable[[], object], repeats: int) -> float:
    timings: list[float] = []
    for _ in range(repeats):
        started = perf_counter_ns()
        call()
        timings.append((perf_counter_ns() - started) / 1_000_000)
    return round(median(timings), 6)


def run_benchmark(
    sample_sizes: tuple[int, ...] = DEFAULT_SAMPLE_SIZES,
    *,
    repeats: int = 5,
) -> dict[str, object]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    results: list[dict[str, object]] = []
    for sample_size in sample_sizes:
        if sample_size < 2:
            raise ValueError("sample sizes must be at least two")
        values = _sample(sample_size)
        results.append(
            {
                "n": sample_size,
                "sn_ms": _median_ms(lambda: sn_scale(values), repeats),
                "qn_ms": _median_ms(lambda: qn_scale(values), repeats),
                "full_profile_ms": _median_ms(
                    lambda: robust_price_dispersion(values), repeats
                ),
                "pair_count": sample_size * (sample_size - 1) // 2,
                "repeats": repeats,
            }
        )
    return {
        "benchmark_environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "decimal_precision": getcontext().prec,
        },
        "results": results,
        "validated_ceiling": max(sample_sizes),
        "validation_meaning": (
            "largest exact cohort completed for Sn, Qn and the full profile; "
            "this is a capacity guard, not a latency SLO"
        ),
        "upstream_bound_evidence": (
            "The pricing collector passes Settings.pricing_scraper_max_sellers "
            "(default 10) to ScrapeConfig; preview/API inputs remain guarded by "
            "PricingPolicy.robust_scale_max_cohort_size=500."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--sizes", type=int, nargs="+", default=DEFAULT_SAMPLE_SIZES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(
        run_benchmark(tuple(args.sizes), repeats=args.repeats),
        indent=2,
        sort_keys=True,
    ) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
