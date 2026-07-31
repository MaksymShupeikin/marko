#!/usr/bin/env python3
"""Re-derive stored candidate verdicts from the current rules. Network-free.

A verdict is written once, at collection time, and never revisited.  That was
adequate while the rules only grew stricter in ways nobody had measured, but two
changes have since made the stored values wrong in both directions:

* the customer's 2026-07-30 decision retired the two tier gates, so thousands of
  comparable offers sit in ``REFERENCE_ONLY`` for a reason that no longer
  exists;
* the category blocklist grew from 7 prefixes to 22 after most offers had been
  collected, so junk that a numeric collision dragged in is still filed as
  admissible.

Re-collecting them live would cost thousands of requests and answer a different
question, because the market has moved.  The verdict, though, is a pure function
of fields that are already stored, so it can simply be recomputed.

Faithfulness is the whole point, so the real ``check_candidate`` is called rather
than reimplemented, and every input is reproduced from the same source
production reads:

    brand tiers        Settings.pricing_brand_tiers_path (unset -> {KEMP: kemp})
    owned sellers      workspace_stores, kind = owned
    confirmed crosses  cross_links + catalog_identity_links, CONFIRMED
    premiums           tier_coefficients, validated
    tier_agnostic      raise_policy.yaml, via tier_agnostic_pricing()
    category context   rebuilt per run from all of that run's offers

One input is deliberately *not* reproduced.  ``collect_catalog_discovery`` is
called without a price for all but 16 of 512 runs, so ``_gate_price_anomaly``
reported ``REFERENCE_PRICE_MISSING`` and never ran.  Leaving it that way would
write fresh verdicts with the price guard still switched off, which is the wrong
direction to be lax in when the target is now a minimum.  The catalogue price
for the same OE is used as a fallback, and the choice is recorded per offer
under ``reference_price_source``.

The previous verdict is preserved under ``selection_details.reclassified_from``,
so a reclassified row still shows what was decided at collection time and why it
changed.  Dry run is the default; ``--apply`` is required to write.

    python scripts/reclassify_discovery_offers.py
    python scripts/reclassify_discovery_offers.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import func, or_, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from marko.core.config import Settings, get_settings  # noqa: E402
from marko.infrastructure.db.models import (  # noqa: E402
    CatalogDiscoveryOffer,
    CatalogDiscoveryRun,
    CatalogIdentityLink,
    CatalogItem,
    CrossLink,
    MarketplaceStore,
    StoreKind,
    TierCoefficientRecord,
    WorkspaceStore,
)
from marko.services.catalog_discovery import (  # noqa: E402
    optional_backend_path,
    resolve_backend_path,
    tier_agnostic_pricing,
)
from marko.services.owned_catalog import normalize_catalog_code  # noqa: E402
from metis.pricing import (  # noqa: E402
    CandidateItem,
    ProductTier,
    ReferenceItem,
    build_category_domain_context,
    check_candidate,
    load_approved_brand_rules,
    load_candidate_selection_config,
    normalize_candidate_oem,
)

RECLASSIFY_METHOD = "reclassify-discovery-offers-v1"
MUTABLE_FIELDS = (
    "selection_status",
    "selection_reason",
    "passed_gates",
    "selection_flags",
    "selection_details",
    "predicted_tier",
    "tier_confidence",
)


def category_path(snapshot: Any) -> tuple[int, ...]:
    """Read Prom's root-to-leaf ancestry out of the stored raw snapshot."""

    raw = snapshot if isinstance(snapshot, dict) else json.loads(snapshot or "{}")
    values = raw.get("categoryIds") or raw.get("category_ids") or []
    path: list[int] = []
    for value in values:
        try:
            path.append(int(value))
        except (TypeError, ValueError):
            return tuple(path)
    return tuple(path)


def category_id(snapshot: Any) -> int | None:
    raw = snapshot if isinstance(snapshot, dict) else json.loads(snapshot or "{}")
    for key in ("categoryId", "category_id"):
        try:
            return int(raw[key])
        except (KeyError, TypeError, ValueError):
            continue
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the recomputed verdicts; without it nothing is modified",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after this many offers, for a quick look",
    )
    args = parser.parse_args()

    settings = get_settings()
    selection_config = load_candidate_selection_config(
        resolve_backend_path(settings.pricing_candidate_selection_path)
    )
    brand_rules = load_approved_brand_rules(
        optional_backend_path(settings.pricing_brand_tiers_path)
    )
    tier_agnostic = tier_agnostic_pricing(settings)

    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    transitions: collections.Counter[str] = collections.Counter()
    flag_counts: collections.Counter[str] = collections.Counter()
    price_source: collections.Counter[str] = collections.Counter()
    changed = 0
    total = 0

    try:
        async with sessions() as session:
            runs = list(
                (
                    await session.scalars(
                        select(CatalogDiscoveryRun).order_by(
                            CatalogDiscoveryRun.created_at
                        )
                    )
                ).all()
            )
            catalog_price = {
                oe: price
                for oe, price in (
                    await session.execute(
                        select(CatalogItem.oe_norm, CatalogItem.current_price)
                    )
                ).all()
            }
            catalog_meta = {
                oe: (name, category, brand)
                for oe, name, category, brand in (
                    await session.execute(
                        select(
                            CatalogItem.oe_norm,
                            CatalogItem.name,
                            CatalogItem.category,
                            CatalogItem.brand,
                        )
                    )
                ).all()
            }

            owned_by_workspace: dict[Any, frozenset[str]] = {}
            premiums_by_workspace: dict[Any, dict[tuple[str, ProductTier], Decimal]] = {}

            print(f"runs: {len(runs)}  tier_agnostic: {tier_agnostic}")
            print(f"brand tiers: {dict(brand_rules.tiers)}")
            print(f"config sha256: {selection_config.source_sha256[:16]}")
            print()

            for run in runs:
                if args.limit is not None and total >= args.limit:
                    break

                if run.workspace_id not in owned_by_workspace:
                    owned_by_workspace[run.workspace_id] = frozenset(
                        str(value).strip()
                        for value in (
                            await session.scalars(
                                select(MarketplaceStore.external_id)
                                .join(
                                    WorkspaceStore,
                                    WorkspaceStore.store_id == MarketplaceStore.id,
                                )
                                .where(
                                    WorkspaceStore.workspace_id == run.workspace_id,
                                    WorkspaceStore.kind == StoreKind.owned,
                                )
                            )
                        ).all()
                        if str(value).strip()
                    )
                    premiums_by_workspace[run.workspace_id] = {
                        (str(category or "").strip().casefold(), ProductTier(tier)): (
                            multiplier
                        )
                        for category, tier, multiplier in (
                            await session.execute(
                                select(
                                    TierCoefficientRecord.category,
                                    TierCoefficientRecord.tier,
                                    TierCoefficientRecord.multiplier,
                                ).where(
                                    TierCoefficientRecord.workspace_id == run.workspace_id,
                                    TierCoefficientRecord.validated.is_(True),
                                )
                            )
                        ).all()
                    }

                offers = list(
                    (
                        await session.scalars(
                            select(CatalogDiscoveryOffer)
                            .where(CatalogDiscoveryOffer.discovery_run_id == run.id)
                            .order_by(CatalogDiscoveryOffer.raw_offer_index)
                        )
                    ).all()
                )
                if not offers:
                    continue

                normalized_reference = normalize_candidate_oem(run.query)
                cross_rows = list(
                    (
                        await session.execute(
                            select(
                                CrossLink.our_oem_norm, CrossLink.extracted_oem_norm
                            ).where(
                                CrossLink.workspace_id == run.workspace_id,
                                CrossLink.validation_status == "CONFIRMED",
                                or_(
                                    CrossLink.our_oem_norm == normalized_reference,
                                    CrossLink.extracted_oem_norm == normalized_reference,
                                ),
                            )
                        )
                    ).all()
                )
                cross_rows.extend(
                    (
                        await session.execute(
                            select(
                                CatalogIdentityLink.our_oem_norm,
                                CatalogIdentityLink.extracted_oem_norm,
                            ).where(
                                CatalogIdentityLink.workspace_id == run.workspace_id,
                                CatalogIdentityLink.validation_status == "CONFIRMED",
                                or_(
                                    CatalogIdentityLink.our_oem_norm
                                    == normalized_reference,
                                    CatalogIdentityLink.extracted_oem_norm
                                    == normalized_reference,
                                ),
                            )
                        )
                    ).all()
                )
                cross_oems = frozenset(
                    value
                    for pair in cross_rows
                    for value in pair
                    if value and value != normalized_reference
                )

                oe_key = run.oe_norm or normalize_catalog_code(run.query)
                name, category, brand = catalog_meta.get(oe_key, (None, None, None))
                if run.reference_price is not None:
                    reference_price = run.reference_price
                    source = "RUN_REFERENCE_PRICE"
                elif oe_key in catalog_price:
                    reference_price = catalog_price[oe_key]
                    source = "CATALOG_CURRENT_PRICE"
                else:
                    reference_price = None
                    source = "NONE_AVAILABLE"

                reference = ReferenceItem(
                    oem=run.query,
                    title=(run.reference_title or name or "").strip() or run.query,
                    price=reference_price,
                    brand=(run.brand or brand or "").strip() or None,
                    category=(run.reference_category or category or "").strip() or None,
                )

                context = build_category_domain_context(
                    [category_path(offer.raw_snapshot) for offer in offers],
                    selection_config.category_domain,
                )

                for offer in offers:
                    if args.limit is not None and total >= args.limit:
                        break
                    total += 1
                    price_source[source] += 1

                    verdict = check_candidate(
                        reference,
                        CandidateItem(
                            seller_id=offer.seller_id,
                            seller_name=offer.seller_name,
                            title=offer.title,
                            description=None,
                            article_field=offer.sku,
                            brand=offer.brand,
                            price=offer.sale_price,
                            condition=None,
                            category_id=category_id(offer.raw_snapshot),
                            category_path=category_path(offer.raw_snapshot),
                        ),
                        selection_config,
                        owned_seller_ids=owned_by_workspace[run.workspace_id],
                        confirmed_cross_oems=cross_oems,
                        brand_tiers=brand_rules.tiers,
                        category_context=context,
                        calibrated_premiums=premiums_by_workspace[run.workspace_id],
                        tier_agnostic=tier_agnostic,
                    )

                    before = f"{offer.selection_status}/{offer.selection_reason}"
                    after = f"{verdict.status.value}/{verdict.reason}"
                    transitions[f"{before} -> {after}"] += 1
                    for flag in verdict.flags:
                        flag_counts[flag] += 1
                    if before == after:
                        continue
                    changed += 1

                    if not args.apply:
                        continue

                    details = dict(verdict.details)
                    details["reference_price_source"] = source
                    # Keep the collection-time verdict readable next to the new
                    # one: a reclassified row must never look like the original.
                    details["reclassified_from"] = {
                        "selection_status": offer.selection_status,
                        "selection_reason": offer.selection_reason,
                        "selection_flags": list(offer.selection_flags or []),
                        "predicted_tier": offer.predicted_tier,
                        "reclassified_at": datetime.now(UTC).isoformat(),
                        "method": RECLASSIFY_METHOD,
                    }
                    offer.selection_status = verdict.status.value
                    offer.selection_reason = verdict.reason
                    offer.passed_gates = list(verdict.passed_gates)
                    offer.selection_flags = list(verdict.flags)
                    offer.selection_details = details
                    offer.predicted_tier = verdict.predicted_tier.value
                    offer.tier_confidence = verdict.tier_confidence

            if args.apply:
                # The run-level counters are what the UI and the funnel read, so
                # leaving them at their collection-time values would show the old
                # picture over reclassified rows.
                for run in runs:
                    counts = dict(
                        (
                            await session.execute(
                                select(
                                    CatalogDiscoveryOffer.selection_status,
                                    func.count(),
                                )
                                .where(
                                    CatalogDiscoveryOffer.discovery_run_id == run.id
                                )
                                .group_by(CatalogDiscoveryOffer.selection_status)
                            )
                        ).all()
                    )
                    await session.execute(
                        update(CatalogDiscoveryRun)
                        .where(CatalogDiscoveryRun.id == run.id)
                        .values(
                            pricing_evidence_count=counts.get("PRICING_EVIDENCE", 0),
                            reference_only_count=counts.get("REFERENCE_ONLY", 0),
                            rejected_candidate_count=counts.get("REJECTED", 0),
                        )
                    )
                await session.commit()
    finally:
        await engine.dispose()

    print(f"offers examined: {total}")
    print(f"verdicts changed: {changed}")
    print(f"mode: {'APPLIED' if args.apply else 'DRY RUN (nothing written)'}")
    print("\nreference price source:")
    for key, count in price_source.most_common():
        print(f"  {count:6d}  {key}")
    print("\ntransitions:")
    for key, count in transitions.most_common():
        marker = " " if key.split(" -> ")[0] == key.split(" -> ")[1] else "*"
        print(f" {marker}{count:6d}  {key}")
    print("\nflags after:")
    for key, count in flag_counts.most_common():
        print(f"  {count:6d}  {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
