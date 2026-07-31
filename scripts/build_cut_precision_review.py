#!/usr/bin/env python3
"""Build the review sheet that gates shipping price cuts. Network-free.

The existing ``GOLD_SET.csv`` cannot answer whether cuts are safe, and no amount
of labelling will change that: all 120 of its rows are *rejections*, sampled by
``selection_reason`` at a time when only 39 of 42435 offers were admitted.
Precision is ``TP / (TP + FP)`` over the offers the system **admits**, so a
sample containing none of them leaves it undefined.  What that file does measure
is the false-rejection rate, which is a different and less urgent question.

Under the customer's minimum-based rule the decision rests on one offer per
position: the cheapest admitted one.  It alone sets the target, so it alone
determines whether a cut recommendation is right.  A wrong match anywhere else
in the basis is harmless; a wrong match at the minimum is the recommendation.

Rows are therefore emitted in risk order, so a reviewer who stops early still
has a usable answer:

    1  CUT_DEEP     implied cut steeper than 50%
    2  CUT_MODERATE implied cut between the significance threshold and 50%
    3  RAISE        the market sits above us
    4  HOLD         inside the band, no action

``manual_label`` is left empty on purpose.  The triage columns are objective
signals to speed a reviewer up, never a proposed answer: filling the labels from
the system's own reasoning would measure the system against itself and
manufacture the number that is supposed to authorise real price cuts.

    python scripts/build_cut_precision_review.py --out review.csv
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import csv
import re
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from marko.core.config import get_settings  # noqa: E402
from marko.infrastructure.db.models import (  # noqa: E402
    CatalogDiscoveryOffer,
    CatalogDiscoveryRun,
    CatalogItem,
)

UNDERCUT = Decimal("0.97")
SIGNIFICANCE = Decimal("0.03")
DEEP_CUT = Decimal("0.50")

FIELDS = (
    "stratum",
    "rank",
    "offer_id",
    "our_oe",
    "our_title",
    "our_price",
    "offer_title",
    "offer_sku",
    "offer_brand",
    "offer_price",
    "offer_url",
    "basis_size",
    "price_ratio",
    "implied_action",
    "implied_change_pct",
    "price_anomaly_flag",
    "our_oe_token_in_offer",
    "manual_label",
    "reviewer_notes",
    "label_status",
)


def norm_oem(value: str | None) -> str:
    """Uppercase ASCII alphanumerics, matching metis.pricing.candidate_selection."""

    return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKC", value or "").upper())


def oe_token_present(our_oe: str, *fields: str | None) -> bool:
    """Whether our OE appears as a *bounded* token, not merely as a substring.

    Substring presence is not evidence: KEMP position 863130 is a substring of
    Zelmer meat-grinder screw 86.3130, and that single collision is what put 15
    meat grinders into the pricing basis.  Requiring the surrounding characters
    to be non-alphanumeric removes that class of false confirmation, so this
    column is a genuine signal rather than a restatement of the bug.
    """

    needle = norm_oem(our_oe)
    if not needle:
        return False
    for field in fields:
        haystack = norm_oem(field)
        for match in re.finditer(re.escape(needle), haystack):
            before = haystack[match.start() - 1] if match.start() else ""
            after = haystack[match.end()] if match.end() < len(haystack) else ""
            if not before.isalnum() and not after.isalnum():
                return True
    return False


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="CUT_PRECISION_REVIEW.csv")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with sessions() as session:
            rows = list(
                (
                    await session.execute(
                        select(
                            CatalogDiscoveryRun.oe_norm,
                            CatalogDiscoveryRun.reference_title,
                            CatalogItem.name,
                            CatalogItem.current_price,
                            CatalogDiscoveryOffer.id,
                            CatalogDiscoveryOffer.title,
                            CatalogDiscoveryOffer.sku,
                            CatalogDiscoveryOffer.brand,
                            CatalogDiscoveryOffer.sale_price,
                            CatalogDiscoveryOffer.url,
                            CatalogDiscoveryOffer.selection_flags,
                        )
                        .join(
                            CatalogItem,
                            CatalogItem.oe_norm == CatalogDiscoveryRun.oe_norm,
                        )
                        .join(
                            CatalogDiscoveryOffer,
                            CatalogDiscoveryOffer.discovery_run_id
                            == CatalogDiscoveryRun.id,
                        )
                        .where(
                            CatalogDiscoveryOffer.selection_status
                            == "PRICING_EVIDENCE",
                            CatalogDiscoveryOffer.sale_price > 0,
                        )
                    )
                ).all()
            )
    finally:
        await engine.dispose()

    by_position: dict[str, list[tuple]] = collections.defaultdict(list)
    for row in rows:
        by_position[row[0]].append(row)

    records = []
    for oe, offers in by_position.items():
        if len(offers) < 3:
            continue
        cheapest = min(offers, key=lambda row: row[8])
        (
            _oe, run_title, item_name, ours, offer_id, offer_title,
            offer_sku, offer_brand, offer_price, url, flags,
        ) = cheapest

        target = (offer_price * UNDERCUT).quantize(Decimal("0.01"))
        change = (target - ours) / ours
        if change > SIGNIFICANCE:
            action, stratum = "RAISE", "3_RAISE"
        elif change < -SIGNIFICANCE:
            action = "CUT"
            stratum = "1_CUT_DEEP" if change < -DEEP_CUT else "2_CUT_MODERATE"
        else:
            action, stratum = "HOLD", "4_HOLD"

        records.append(
            {
                "stratum": stratum,
                "rank": 0,
                "offer_id": str(offer_id),
                "our_oe": oe,
                "our_title": (run_title or item_name or "")[:160],
                "our_price": str(ours),
                "offer_title": offer_title[:160],
                "offer_sku": offer_sku or "",
                "offer_brand": offer_brand or "",
                "offer_price": str(offer_price),
                "offer_url": url,
                "basis_size": len(offers),
                "price_ratio": f"{offer_price / ours:.4f}",
                "implied_action": action,
                "implied_change_pct": f"{change * 100:.1f}",
                "price_anomaly_flag": "YES" if "PRICE_ANOMALY" in (flags or []) else "",
                "our_oe_token_in_offer": (
                    "YES" if oe_token_present(oe, offer_sku, offer_title) else "NO"
                ),
                "manual_label": "",
                "reviewer_notes": "",
                "label_status": "UNLABELED",
            }
        )

    records.sort(key=lambda r: (r["stratum"], Decimal(r["price_ratio"])))
    for index, record in enumerate(records, 1):
        record["rank"] = index

    out = Path(args.out)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FIELDS))
        writer.writeheader()
        writer.writerows(records)

    strata = collections.Counter(r["stratum"] for r in records)
    print(f"wrote {out}  rows: {len(records)}")
    print("\nrisk order (review from the top; each stratum answers on its own):")
    for name in sorted(strata):
        subset = [r for r in records if r["stratum"] == name]
        no_token = sum(1 for r in subset if r["our_oe_token_in_offer"] == "NO")
        flagged = sum(1 for r in subset if r["price_anomaly_flag"] == "YES")
        print(
            f"  {name:16s} {strata[name]:4d} rows"
            f"   OE token absent: {no_token:3d}"
            f"   price-anomaly: {flagged:3d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
