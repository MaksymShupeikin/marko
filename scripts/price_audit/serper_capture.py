#!/usr/bin/env python3
"""Capture raw Serper responses with a hard query cap and no secret output."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

import httpx  # noqa: E402

from marko.core.config import get_settings  # noqa: E402
from marko.services.competitor_prices import SERPER_URL  # noqa: E402


ABSOLUTE_MAX_SERPER_QUERIES = 30


async def capture(queries: list[str], max_queries: int) -> dict[str, Any]:
    if not 1 <= max_queries <= ABSOLUTE_MAX_SERPER_QUERIES:
        raise RuntimeError(
            "--max-queries must be between 1 and "
            f"{ABSOLUTE_MAX_SERPER_QUERIES}"
        )
    if len(queries) > max_queries:
        raise RuntimeError(f"{len(queries)} queries exceeds --max-queries={max_queries}")
    settings = get_settings()
    if not settings.serper_api_key:
        raise RuntimeError("SERPER_API_KEY is not configured")
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for query in queries:
            response = await client.post(
                SERPER_URL,
                json={"q": query, "gl": "ua", "hl": "uk", "num": 20},
                headers={"X-API-KEY": settings.serper_api_key},
            )
            entry: dict[str, Any] = {
                "query": query,
                "request": {"gl": "ua", "hl": "uk", "num": 20},
                "status_code": response.status_code,
            }
            try:
                entry["response"] = response.json()
            except ValueError:
                entry["response_text"] = response.text[:2000]
            results.append(entry)
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "budget": {
            "max_queries_for_this_run": max_queries,
            "actual_queries": len(results),
            "llm_calls": 0,
            "marketplace_fetches": 0,
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="+")
    parser.add_argument("--max-queries", type=int, default=1)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(capture(args.query, args.max_queries)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
