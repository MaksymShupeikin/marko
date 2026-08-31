#!/usr/bin/env python3
"""Replay current snippet extraction against archived, real Serper payloads."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from marko.services import competitor_prices as cp  # noqa: E402

FIXTURES = (
    ROOT / "backend" / "tests" / "fixtures" / "audit" / "serper-211217-rozetka-2026-08-31.json",
    ROOT / "backend" / "tests" / "fixtures" / "audit" / "serper-installments-2026-08-31.json",
    ROOT / "backend" / "tests" / "fixtures" / "audit" / "serper-peugeot206-2026-08-31.json",
)
CATEGORY_OR_INFO_RE = re.compile(
    r"/(?:payment|oplata|rassrochka)(?:[/?-]|$)|/section/|/c\d+/?$",
    re.I,
)


def analyse(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for result in payload.get("results") or []:
        organic = (result.get("response") or {}).get("organic") or []
        for item in organic:
            text = f"{item.get('title') or ''} {item.get('snippet') or ''}"
            price = cp._price_from_text(text)
            rows.append(
                {
                    "title": item.get("title"),
                    "url": item.get("link"),
                    "snippet": item.get("snippet"),
                    "price_from_text": str(price) if price is not None else None,
                    "category_or_finance_page": bool(
                        CATEGORY_OR_INFO_RE.search(item.get("link") or "")
                    ),
                }
            )
    return {
        "fixture": str(path.relative_to(ROOT)),
        "captured_at": payload.get("captured_at"),
        "rows": rows,
    }


def b1_live_candidate_replay() -> dict[str, Any]:
    path = FIXTURES[-1]
    payload = json.loads(path.read_text(encoding="utf-8"))
    organic = (payload["results"][0].get("response") or {}).get("organic") or []
    query = cp.PartSearchQuery(
        listing_id="734a12c2-67c5-4419-94a2-f1a63887b550",
        oem_numbers=("PEUGEOT206", "PEUGEOT207", "PEUGEOT307", "1509352", "77648927"),
        brand="PARTNER",
        name=(
            "Прокладка впускного колектора peugeot/citroen "
            "206,207,307,partner,tepee 1,6hdi 0"
        ),
        source_url=(
            "https://kemp-cs2847093.prom.ua/"
            "p1522313819-prokladka-vpusknogo-kolektora.html"
        ),
    )
    picked = cp.GooglePriceSource()._candidates(query, [organic])
    return {
        "fixture": str(path.relative_to(ROOT)),
        "listing_id": query.listing_id,
        "human_reference_product": "intake manifold gasket",
        "raw_results": len(organic),
        "accepted_before_price_fetch": [
            {
                "title": item.get("title"),
                "url": item.get("link"),
                "score": score,
                "human_label": "not the gasket; page about whole Peugeot 206 cars",
            }
            for item, _domain, score in picked
        ],
        "warning": (
            "Candidate acceptance is proven live; final offer inclusion remains unknown "
            "because these pages were not fetched for structured prices."
        ),
    }


def main() -> None:
    analysed = [analyse(path) for path in FIXTURES]
    print(
        json.dumps(
            {
                "scope": (
                    "real snippet format replay only; extraction does not prove "
                    "that a result passes product matching"
                ),
                "serper_queries": len(FIXTURES),
                "fixtures": analysed,
                "b1_live_candidate_replay": b1_live_candidate_replay(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
