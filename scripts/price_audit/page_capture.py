#!/usr/bin/env python3
"""Capture full HTTP response bodies as deterministic gzip+base64 fixtures."""

from __future__ import annotations

import argparse
import asyncio
import base64
import gzip
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import httpx


ABSOLUTE_MAX_PAGE_FETCHES = 100


async def capture(urls: list[str], max_fetches: int) -> dict[str, Any]:
    if not 1 <= max_fetches <= ABSOLUTE_MAX_PAGE_FETCHES:
        raise RuntimeError(
            f"--max-fetches must be between 1 and {ABSOLUTE_MAX_PAGE_FETCHES}"
        )
    if len(urls) > max_fetches:
        raise RuntimeError(f"{len(urls)} URLs exceeds --max-fetches={max_fetches}")
    entries: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=10.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
    ) as client:
        for url in urls:
            try:
                response = await client.get(url)
                body = response.content
                entries.append(
                    {
                        "requested_url": url,
                        "final_url": str(response.url),
                        "status_code": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "body_bytes": len(body),
                        "body_sha256": hashlib.sha256(body).hexdigest(),
                        "body_encoding": "gzip+base64; gzip mtime=0",
                        "body": base64.b64encode(gzip.compress(body, mtime=0)).decode("ascii"),
                    }
                )
            except Exception as exc:
                entries.append(
                    {
                        "requested_url": url,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "budget": {
            "max_fetches_for_this_run": max_fetches,
            "actual_fetches": len(urls),
            "serper_queries": 0,
            "llm_calls": 0,
        },
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="+")
    parser.add_argument("--max-fetches", type=int, default=1)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(capture(args.url, args.max_fetches)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
