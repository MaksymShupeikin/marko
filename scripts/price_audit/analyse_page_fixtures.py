#!/usr/bin/env python3
"""Decode archived page bodies and replay current structured-price parsing."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from marko.services import competitor_prices as cp  # noqa: E402

FIXTURES = (
    ROOT / "backend" / "tests" / "fixtures" / "audit" / "page-bossauto-peugeot206-403-2026-08-31.json",
    ROOT / "backend" / "tests" / "fixtures" / "audit" / "page-reono-peugeot206-200-2026-08-31.json",
)


def analyse(path: Path) -> dict:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    entry = snapshot["entries"][0]
    encoded = entry.get("body")
    body = gzip.decompress(base64.b64decode(encoded)) if encoded else b""
    html = body.decode("utf-8", "replace")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    parsed = cp._structured_price(html) if entry.get("status_code") == 200 else None
    result = {
        "fixture": str(path.relative_to(ROOT)),
        "requested_url": entry.get("requested_url"),
        "final_url": entry.get("final_url"),
        "status_code": entry.get("status_code"),
        "content_type": entry.get("content_type"),
        "body_bytes": len(body),
        "body_sha256_matches": hashlib.sha256(body).hexdigest() == entry.get("body_sha256"),
        "html_title": re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else None,
        "json_ld_blocks": len(cp._LD_JSON_RE.findall(html)),
        "structured_price": (
            {
                "price": str(parsed[0]),
                "currency": parsed[1],
                "image": parsed[2],
            }
            if parsed
            else None
        ),
        "classification": (
            "anti-bot/non-200; not parser evidence"
            if entry.get("status_code") != 200
            else "live page parser evidence"
        ),
    }
    if parsed:
        offer = cp.MarketOffer(
            "google",
            "whole Peugeot 206 car page",
            parsed[0],
            parsed[1],
            str(entry.get("final_url") or ""),
            confidence=0.9,
        )
        after_gates = cp._drop_implausible(
            (cp.SourceResult("google", "Google", "ok", (offer,)),)
        )[0].offers
        result["single_offer_thin_market_simulation"] = {
            "survives_positive_and_outlier_gate": bool(after_gates),
            "stats_prices_before_fx": [str(price) for price in cp._stats_prices(after_gates)],
            "recommended_before_fx": (
                str(cp._recommended_price(cp._stats_prices(after_gates)))
                if after_gates
                else None
            ),
            "warning": "Production normally converts USD via NBU before this gate.",
        }
    return result


def main() -> None:
    print(
        json.dumps(
            {
                "scope": "raw archived pages replayed through current parser",
                "fixtures": [analyse(path) for path in FIXTURES],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
