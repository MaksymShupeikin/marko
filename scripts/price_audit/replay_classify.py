#!/usr/bin/env python3
"""Frozen first-pass LLM replay with an explicit call budget.

Run from the repository root so Settings reads the root .env. The script never
prints credentials and does not touch Redis or the product database.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from marko.core.config import get_settings  # noqa: E402
from marko.services import llm_filter  # noqa: E402


ABSOLUTE_MAX_LLM_CALLS = 60


def _source_offers(report: dict[str, Any], source_name: str) -> list[dict[str, Any]]:
    return next(
        list(source.get("offers") or [])
        for source in report.get("sources") or []
        if source.get("source") == source_name
    )


async def replay(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.max_calls <= ABSOLUTE_MAX_LLM_CALLS:
        raise RuntimeError(
            f"--max-calls must be between 1 and {ABSOLUTE_MAX_LLM_CALLS}"
        )
    report = json.loads(args.fixture.read_text(encoding="utf-8"))
    offers = _source_offers(report, args.source)[: args.limit]
    titles = [str(offer.get("title") or "") for offer in offers]
    query = report.get("query") or {}
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    expected_calls = args.repeats * math.ceil(len(titles) / llm_filter._CHUNK_SIZE)
    if expected_calls > args.max_calls:
        raise RuntimeError(
            f"expected {expected_calls} calls, above --max-calls={args.max_calls}"
        )

    original_ask = llm_filter._ask_openai
    call_log: list[dict[str, Any]] = []
    active_repeat = 0

    async def captured_ask(
        prompt: str,
        system: str = llm_filter._SYSTEM,
        *,
        image_url: str | None = None,
        model: str | None = None,
    ) -> str:
        started = time.monotonic()
        raw = await original_ask(
            prompt, system, image_url=image_url, model=model
        )
        call_log.append(
            {
                "repeat": active_repeat,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "response": json.loads(raw),
            }
        )
        return raw

    llm_filter._ask_openai = captured_ask
    runs: list[dict[int, str]] = []
    started = time.monotonic()
    try:
        for repeat in range(1, args.repeats + 1):
            active_repeat = repeat
            runs.append(
                await llm_filter.classify(
                    name=str(query.get("name") or ""),
                    brand=(
                        None
                        if str(query.get("brand") or "").strip().casefold() == "kemp"
                        else query.get("brand")
                    ),
                    oem_numbers=tuple(query.get("oem_numbers") or []),
                    titles=titles,
                )
            )
    finally:
        llm_filter._ask_openai = original_ask

    rows: list[dict[str, Any]] = []
    changed = 0
    for index, (title, offer) in enumerate(zip(titles, offers)):
        verdicts = [run.get(index, "missing") for run in runs]
        drift = len(set(verdicts)) > 1
        changed += drift
        rows.append(
            {
                "index": index,
                "title": title,
                "price": offer.get("price"),
                "production_confidence": offer.get("confidence"),
                "production_is_analog": offer.get("is_analog"),
                "verdicts": verdicts,
                "drift": drift,
            }
        )

    pairwise: list[dict[str, Any]] = []
    for left in range(len(runs)):
        for right in range(left + 1, len(runs)):
            disagreements = sum(
                runs[left].get(index, "missing")
                != runs[right].get(index, "missing")
                for index in range(len(titles))
            )
            pairwise.append(
                {
                    "runs": [left + 1, right + 1],
                    "disagreements": disagreements,
                    "rate": round(disagreements / len(titles), 4) if titles else 0,
                }
            )

    return {
        "scope": "one frozen recommendation-driving source batch; not a prevalence estimate",
        "fixture": str(args.fixture.relative_to(ROOT)),
        "source": args.source,
        "query": query,
        "model": settings.competitor_filter_model,
        "provider": "custom" if settings.openai_base_url else "openai",
        "titles": len(titles),
        "repeats": args.repeats,
        "chunk_size": llm_filter._CHUNK_SIZE,
        "budget": {
            "max_calls": args.max_calls,
            "expected_calls": expected_calls,
            "actual_calls": len(call_log),
            "serper_calls": 0,
            "marketplace_fetches": 0,
        },
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "run_verdict_counts": [dict(Counter(run.values())) for run in runs],
        "items_with_drift": changed,
        "item_drift_rate": round(changed / len(titles), 4) if titles else 0,
        "pairwise": pairwise,
        "items": rows,
        "raw_call_log": sorted(
            call_log, key=lambda item: (item["repeat"], item["prompt_sha256"])
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--source", default="prom")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--max-calls", type=int, default=3)
    args = parser.parse_args()
    args.fixture = args.fixture.resolve()
    print(json.dumps(asyncio.run(replay(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
