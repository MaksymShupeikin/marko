"""Build the human markup worksheet for Prom brand tiers (master plan 2.1).

The agent collects evidence; it never assigns a tier. Every number here is a
hint for the reviewer, and the generated draft leaves ``tier``, ``approved``
and the approval metadata for a human to fill in.

Two observation sets are kept apart on purpose, because the master plan §2.2
calls confusing them the main risk of the project:

competitor set
    Offers used to describe what a rival charges. Own stores, KEMP and used
    listings are excluded, exactly as in the pricing selection set.

KEMP anchor set
    KEMP-branded offers used only as the denominator of the price ratio. The
    customer's own stores are *kept* here: their KEMP listing is the anchor
    price, and dropping it would leave most positions with no denominator at
    all. KEMP still never enters the competitor set.

Identity is recomputed from the offer's own fields rather than read off the
gate chain. The chain stops at its first terminal gate, so an owned or
dismantler listing never reaches OEM identity and would silently vanish from
the anchor set if the recorded evidence were trusted here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import yaml

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import CatalogDiscoveryOffer, CatalogDiscoveryRun
from metis.pricing import (
    BRAND_RULES_SCHEMA_VERSION,
    classify_tier,
    normalize_brand,
    normalize_candidate_oem,
)


BRAND_WORKSHEET_SCHEMA_VERSION = "metis-brand-review-worksheet-v1"

#: Tiers a reviewer may assign to a non-KEMP brand. ``kemp``, ``used`` and
#: ``unknown`` are refused by the loader for non-KEMP records.
ASSIGNABLE_TIERS: tuple[str, ...] = (
    "oem",
    "oes",
    "aftermarket_a",
    "aftermarket_b",
    "budget",
)

_RATIO_QUANTUM = Decimal("0.0001")
_PRICE_QUANTUM = Decimal("0.01")
_DEFAULT_EXAMPLE_URLS = 3

#: Widest max/min spread across per-OE ratios still worth showing a reviewer as
#: a usable hint. Chosen to sit above the whole §2.2 sanity band (OEM tops out
#: at 4.0x, AM_B sits near 1.0x, so a genuine tier cannot span more than ~4x)
#: and below the 20x spreads that dirty pairs produce. It marks a row, never
#: filters or assigns one.
MAX_TRUSTWORTHY_RATIO_SPREAD = Decimal("4.0")


class BrandWorksheetError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


# --------------------------------------------------------------------------
# Observations
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BrandObservation:
    """One discovery offer reduced to what brand review needs."""

    target_oe: str
    brand_raw: str | None
    brand_normalized: str
    seller_id: str
    listing_id: str
    url: str
    price: Decimal
    is_owned: bool
    is_kemp: bool
    is_used: bool
    identity_lane: str | None
    selection_reason: str

    @property
    def has_identity(self) -> bool:
        return self.identity_lane is not None

    @property
    def in_competitor_set(self) -> bool:
        return (
            self.has_identity
            and not self.is_owned
            and not self.is_kemp
            and not self.is_used
        )

    @property
    def in_kemp_anchor_set(self) -> bool:
        # Deliberately does not exclude owned sellers: see the module docstring.
        return self.has_identity and self.is_kemp and not self.is_used


def oem_identity_lane(
    target_oe: str,
    *,
    sku: str | None,
    title: str | None,
    description: str | None,
) -> str | None:
    """Report which field carries the target OE, in the gate's own precedence.

    Mirrors ``_gate_oem_identity`` minus the cross-table lane, which cannot
    fire while no cross link is CONFIRMED. Kept as a separate function so the
    anchor set stays independent of where the gate chain happened to stop; a
    test pins it against the gate's recorded evidence.
    """

    expected = normalize_candidate_oem(target_oe)
    if not expected:
        return None
    if normalize_candidate_oem(sku) == expected:
        return "ARTICLE_FIELD"
    if expected in normalize_candidate_oem(title):
        return "TITLE"
    if expected in normalize_candidate_oem(description):
        return "DESCRIPTION"
    return None


def observation_from_offer(
    offer: CatalogDiscoveryOffer,
    *,
    target_oe: str,
) -> BrandObservation:
    snapshot = offer.raw_snapshot if isinstance(offer.raw_snapshot, Mapping) else {}
    description = snapshot.get("description")
    condition = snapshot.get("condition")
    description_text = str(description) if description else None
    tier = classify_tier(
        brand=offer.brand,
        title=offer.title or "",
        description=description_text,
        condition=str(condition) if condition else None,
    )
    return BrandObservation(
        target_oe=normalize_candidate_oem(target_oe),
        brand_raw=(offer.brand or "").strip() or None,
        brand_normalized=normalize_brand(offer.brand),
        seller_id=(offer.seller_id or "").strip(),
        listing_id=offer.source_listing_id,
        url=(offer.url or "").strip(),
        price=offer.sale_price,
        is_owned=bool(offer.is_owned),
        is_kemp=tier.is_kemp,
        is_used=tier.is_used,
        identity_lane=oem_identity_lane(
            target_oe,
            sku=offer.sku,
            title=offer.title,
            description=description_text,
        ),
        selection_reason=offer.selection_reason or "",
    )


def deduplicate_observations(
    observations: Iterable[BrandObservation],
) -> tuple[BrandObservation, ...]:
    """Collapse repeated sightings of one listing under one target OE.

    Evidence is append-only and the same query is re-run over time, so a
    listing appears once per run. Counting each sighting would inflate
    ``offer_count`` by however many times the batch happened to be repeated —
    measured on 2026-07-26, two batches over the same 30 OEs doubled every
    count while ``seller_count`` stayed put. The latest sighting wins, so the
    freshest price is the one that reaches the ratio.
    """

    latest: dict[tuple[str, str], BrandObservation] = {}
    for observation in observations:
        latest[(observation.target_oe, observation.listing_id)] = observation
    return tuple(latest.values())


async def load_brand_observations(
    session: AsyncSession,
    *,
    workspace_id: UUID,
) -> tuple[BrandObservation, ...]:
    """Read the newest sighting of every listing across completed runs."""

    rows = (
        await session.execute(
            select(CatalogDiscoveryOffer, CatalogDiscoveryRun.query)
            .join(
                CatalogDiscoveryRun,
                CatalogDiscoveryRun.id == CatalogDiscoveryOffer.discovery_run_id,
            )
            .where(
                CatalogDiscoveryRun.workspace_id == workspace_id,
                CatalogDiscoveryRun.status == "completed",
            )
            # Ascending run time so the deduplicator's "last wins" keeps the
            # freshest observation of each listing.
            .order_by(
                CatalogDiscoveryRun.query,
                CatalogDiscoveryOffer.source_listing_id,
                CatalogDiscoveryRun.created_at,
            )
        )
    ).all()
    return deduplicate_observations(
        observation_from_offer(offer, target_oe=query) for offer, query in rows
    )


# --------------------------------------------------------------------------
# Robust statistics
# --------------------------------------------------------------------------


def median_decimal(values: Sequence[Decimal]) -> Decimal | None:
    """Median of a Decimal sample, or ``None`` when the sample is empty.

    Median rather than mean throughout: brand samples here are 1-8 listings
    from mixed sellers, where one outlier drags a mean anywhere it likes.
    """

    if not values:
        return None
    ordered = sorted(values)
    size = len(ordered)
    middle = size // 2
    if size % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _optional_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _by_oe(observations: Iterable[BrandObservation]) -> dict[str, list[Decimal]]:
    grouped: dict[str, list[Decimal]] = {}
    for observation in observations:
        grouped.setdefault(observation.target_oe, []).append(observation.price)
    return grouped


@dataclass(frozen=True, slots=True)
class RatioSummary:
    """A brand's price ratio against KEMP, with the spread that qualifies it.

    The median alone misleads. Measured on 2026-07-26, brand ``VOLKSWAGEN``
    paired against KEMP on four OEs at 0.81, 6.88, 11.51 and 16.45; the median
    of 9.20 describes none of them. A ratio is only worth reading when the
    per-OE ratios agree, so the spread travels with it.
    """

    median: Decimal | None
    paired_oe_count: int
    minimum: Decimal | None
    maximum: Decimal | None

    @property
    def spread(self) -> Decimal | None:
        """How many times the widest per-OE ratio exceeds the narrowest."""

        if self.minimum is None or self.maximum is None or self.minimum <= 0:
            return None
        return (self.maximum / self.minimum).quantize(_RATIO_QUANTUM)

    @property
    def is_trustworthy(self) -> bool:
        """Display aid only — never a gate and never an auto-assignment.

        Two or more paired OEs whose ratios stay inside a ``MAX_TRUSTWORTHY
        _RATIO_SPREAD`` band. Anything wider means the pairs are not the same
        part, which §2.2 calls dirt in the data rather than a discovery.
        """

        spread = self.spread
        return (
            self.median is not None
            and self.paired_oe_count >= 2
            and spread is not None
            and spread <= MAX_TRUSTWORTHY_RATIO_SPREAD
        )


def price_ratio_vs_kemp(
    brand_prices_by_oe: Mapping[str, Sequence[Decimal]],
    kemp_prices_by_oe: Mapping[str, Sequence[Decimal]],
) -> RatioSummary:
    """Median across OEs of (brand median price / KEMP median price).

    Collapsing each side to a per-OE median first stops a single seller with
    many listings on one OE from dominating the whole brand's ratio.
    """

    ratios: list[Decimal] = []
    for target_oe in sorted(set(brand_prices_by_oe) & set(kemp_prices_by_oe)):
        brand_median = median_decimal(list(brand_prices_by_oe[target_oe]))
        kemp_median = median_decimal(list(kemp_prices_by_oe[target_oe]))
        if brand_median is None or kemp_median is None or kemp_median <= 0:
            continue
        ratios.append(brand_median / kemp_median)
    if not ratios:
        return RatioSummary(median=None, paired_oe_count=0, minimum=None, maximum=None)
    median = median_decimal(ratios)
    assert median is not None
    return RatioSummary(
        median=median.quantize(_RATIO_QUANTUM),
        paired_oe_count=len(ratios),
        minimum=min(ratios).quantize(_RATIO_QUANTUM),
        maximum=max(ratios).quantize(_RATIO_QUANTUM),
    )


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BrandRow:
    brand_normalized: str
    brand_display: str
    brand_variants: tuple[str, ...]
    offer_count: int
    seller_count: int
    distinct_target_oes: int
    tier_unknown_offers: int
    median_price_uah: Decimal | None
    ratio: RatioSummary
    example_urls: tuple[str, ...]

    @property
    def median_price_vs_kemp(self) -> Decimal | None:
        return self.ratio.median

    @property
    def paired_oe_count(self) -> int:
        return self.ratio.paired_oe_count

    def as_dict(self) -> dict[str, Any]:
        return {
            "brand": self.brand_display,
            "normalized": self.brand_normalized,
            "variants": list(self.brand_variants),
            "offer_count": self.offer_count,
            "seller_count": self.seller_count,
            "distinct_target_oes": self.distinct_target_oes,
            "tier_unknown_offers": self.tier_unknown_offers,
            "median_price_uah": (
                str(self.median_price_uah)
                if self.median_price_uah is not None
                else None
            ),
            "median_price_vs_kemp": _optional_str(self.ratio.median),
            "ratio_min": _optional_str(self.ratio.minimum),
            "ratio_max": _optional_str(self.ratio.maximum),
            "ratio_spread": _optional_str(self.ratio.spread),
            "ratio_is_trustworthy": self.ratio.is_trustworthy,
            "paired_oe_count": self.ratio.paired_oe_count,
            "example_urls": list(self.example_urls),
        }


@dataclass(frozen=True, slots=True)
class BrandWorksheet:
    generated_at: datetime
    observation_count: int
    competitor_observation_count: int
    kemp_anchor_observation_count: int
    distinct_target_oes: int
    rows: tuple[BrandRow, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BRAND_WORKSHEET_SCHEMA_VERSION,
            "generated_at": self.generated_at.isoformat(),
            "observation_count": self.observation_count,
            "competitor_observation_count": self.competitor_observation_count,
            "kemp_anchor_observation_count": self.kemp_anchor_observation_count,
            "distinct_target_oes": self.distinct_target_oes,
            "brand_count": len(self.rows),
            "brands": [row.as_dict() for row in self.rows],
        }


def is_reviewable_evidence_url(value: str) -> bool:
    """Match the loader's evidence contract for the ``prom.ua/ua`` market."""

    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").casefold()
    return (
        parsed.scheme.casefold() == "https"
        and parsed.username is None
        and parsed.password is None
        and (hostname == "prom.ua" or hostname.endswith(".prom.ua"))
        and bool(parsed.path)
    )


def build_brand_worksheet(
    observations: Sequence[BrandObservation],
    *,
    generated_at: datetime,
    example_urls: int = _DEFAULT_EXAMPLE_URLS,
    min_offer_count: int = 1,
) -> BrandWorksheet:
    """Aggregate observations into one reviewable row per normalized brand."""

    competitors = [item for item in observations if item.in_competitor_set]
    anchors = [item for item in observations if item.in_kemp_anchor_set]
    kemp_prices_by_oe = _by_oe(anchors)

    grouped: dict[str, list[BrandObservation]] = {}
    for observation in competitors:
        if not observation.brand_normalized:
            continue
        grouped.setdefault(observation.brand_normalized, []).append(observation)

    rows: list[BrandRow] = []
    for brand_normalized, items in grouped.items():
        if len(items) < min_offer_count:
            continue
        variants = tuple(sorted({item.brand_raw for item in items if item.brand_raw}))
        ratio = price_ratio_vs_kemp(_by_oe(items), kemp_prices_by_oe)
        median_price = median_decimal([item.price for item in items])
        rows.append(
            BrandRow(
                brand_normalized=brand_normalized,
                brand_display=variants[0] if variants else brand_normalized,
                brand_variants=variants,
                offer_count=len(items),
                seller_count=len({item.seller_id or item.listing_id for item in items}),
                distinct_target_oes=len({item.target_oe for item in items}),
                tier_unknown_offers=sum(
                    1 for item in items if item.selection_reason == "TIER_UNKNOWN"
                ),
                median_price_uah=(
                    median_price.quantize(_PRICE_QUANTUM)
                    if median_price is not None
                    else None
                ),
                ratio=ratio,
                example_urls=_example_urls(items, limit=example_urls),
            )
        )

    # Most positions unblocked first: that is what the reviewer's time buys.
    rows.sort(
        key=lambda row: (
            -row.distinct_target_oes,
            -row.tier_unknown_offers,
            -row.offer_count,
            row.brand_normalized,
        )
    )
    return BrandWorksheet(
        generated_at=generated_at,
        observation_count=len(observations),
        competitor_observation_count=len(competitors),
        kemp_anchor_observation_count=len(anchors),
        distinct_target_oes=len({item.target_oe for item in observations}),
        rows=tuple(rows),
    )


def _example_urls(
    items: Sequence[BrandObservation],
    *,
    limit: int,
) -> tuple[str, ...]:
    """Pick deterministic examples, preferring one per distinct target OE."""

    ordered = sorted(items, key=lambda item: (item.target_oe, item.listing_id))
    chosen: list[str] = []
    seen_oes: set[str] = set()
    for item in ordered:
        if len(chosen) >= limit:
            break
        if item.target_oe in seen_oes or not is_reviewable_evidence_url(item.url):
            continue
        seen_oes.add(item.target_oe)
        chosen.append(item.url)
    if len(chosen) < limit:
        for item in ordered:
            if len(chosen) >= limit:
                break
            if item.url in chosen or not is_reviewable_evidence_url(item.url):
                continue
            chosen.append(item.url)
    return tuple(chosen)


# --------------------------------------------------------------------------
# Renderers
# --------------------------------------------------------------------------


_DRAFT_HEADER = """\
# METIS — ЧЕРНОВИК СЛОВАРЯ БРЕНДОВ ДЛЯ РАЗМЕТКИ ЧЕЛОВЕКОМ
#
# Сгенерировано из живых наблюдений Prom. Агент НЕ проставляет tier'ы.
#
# Чтобы активировать бренд, в его записи нужно:
#   1. tier          -> один из: {tiers}
#   2. confidence    -> строка > "0.0000", например "0.9000"
#   3. approved      -> true
#   4. approved_by   -> кто утвердил
#   5. approved_at   -> ISO-8601, например "2026-07-27" или "2026-07-27T10:00:00Z"
#   6. evidence      -> НЕПУСТОЙ СПИСОК https-ссылок на prom.ua (уже заполнен примерами)
# И вверху файла: domain_policy_approved: true + approved_by + approved_at.
#
# Загрузчик fail-closed: если approved: true, а метаданных не хватает, файл
# будет отклонён целиком, а не молча применён частично.
# Проверить перед использованием:
#   uv run brand-review-worksheet validate --path <этот файл>
#
# statistics — это ПОДСКАЗКА для человека, а не основание для автоприсвоения.
#   median_price_vs_kemp — медиана по OE отношения (медиана цены бренда) /
#   (медиана цены KEMP) на одном и том же OE. paired_oe_count — на скольких
#   OE такое сравнение вообще было возможно. Пусто = сравнить не с чем.
"""


def render_brands_draft_yaml(
    worksheet: BrandWorksheet,
    *,
    dataset_id: str,
    existing: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    """Render a ``metis-brand-tiers-v1`` draft, preserving prior human work.

    Records already decided in ``existing`` keep their tier, approval and
    evidence, so regenerating the worksheet after new measurements never
    discards a reviewer's decision.
    """

    decided = dict(existing or {})
    brands: list[dict[str, Any]] = [_kemp_record(decided.get("KEMP"))]
    for row in worksheet.rows:
        if row.brand_normalized == "KEMP":
            continue
        brands.append(_brand_record(row, decided.get(row.brand_normalized)))

    document: dict[str, Any] = {
        "schema_version": BRAND_RULES_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "market": "prom.ua/UA",
        "data_class": "bounded_live_discovery",
        "representative": False,
        "domain_policy_approved": False,
        "approved_by": None,
        "approved_at": None,
        "notes": [
            "Only KEMP is approved as a contractual system invariant.",
            "Every non-KEMP tier stays unknown until Ukrainian Prom domain review.",
            "Price ratios are evidence for review, not automatic tier assignments.",
            f"Generated from {worksheet.competitor_observation_count} competitor "
            f"observations over {worksheet.distinct_target_oes} target OEs.",
        ],
        "brands": brands,
    }
    body = yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )
    header = _DRAFT_HEADER.format(tiers=", ".join(ASSIGNABLE_TIERS))
    return f"{header}\n{body}"


def _kemp_record(existing: Mapping[str, Any] | None) -> dict[str, Any]:
    # KEMP is a contractual invariant, not a market inference: the loader
    # rejects the file outright if this record is anything else.
    record: dict[str, Any] = {
        "brand": "KEMP",
        "normalized": "KEMP",
        "tier": "kemp",
        "confidence": "1.0000",
        "approved": True,
    }
    if existing:
        for key in ("evidence", "statistics"):
            if existing.get(key) is not None:
                record[key] = existing[key]
    return record


def _brand_record(
    row: BrandRow,
    existing: Mapping[str, Any] | None,
) -> dict[str, Any]:
    statistics = {
        "offer_count": row.offer_count,
        "seller_count": row.seller_count,
        "distinct_target_oes": row.distinct_target_oes,
        "tier_unknown_offers": row.tier_unknown_offers,
        "paired_oe_count": row.ratio.paired_oe_count,
        "median_price_uah": _optional_str(row.median_price_uah),
        "median_price_vs_kemp": _optional_str(row.ratio.median),
        "ratio_min": _optional_str(row.ratio.minimum),
        "ratio_max": _optional_str(row.ratio.maximum),
        "ratio_spread": _optional_str(row.ratio.spread),
        "ratio_is_trustworthy": row.ratio.is_trustworthy,
        "brand_variants": list(row.brand_variants),
    }
    record: dict[str, Any] = {
        "brand": row.brand_display,
        "normalized": row.brand_normalized,
        "tier": str((existing or {}).get("tier") or "unknown"),
        "confidence": str((existing or {}).get("confidence") or "0.0000"),
        "approved": bool((existing or {}).get("approved", False)),
        "approved_by": (existing or {}).get("approved_by"),
        "approved_at": (existing or {}).get("approved_at"),
        "evidence": list((existing or {}).get("evidence") or row.example_urls),
        "statistics": statistics,
    }
    return record


def load_existing_records(path: str | Path) -> dict[str, dict[str, Any]]:
    """Read prior human decisions from an existing brand dictionary."""

    source = Path(path).expanduser()
    if not source.is_file():
        raise BrandWorksheetError(
            "BRAND_DICTIONARY_MISSING",
            f"Словарь брендов не найден: {source}",
        )
    payload = yaml.safe_load(source.read_bytes())
    if not isinstance(payload, Mapping):
        raise BrandWorksheetError(
            "BRAND_DICTIONARY_UNREADABLE",
            "Корень словаря брендов должен быть отображением.",
        )
    records = payload.get("brands")
    if not isinstance(records, list):
        return {}
    decided: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        normalized = normalize_brand(str(record.get("brand") or ""))
        if not normalized:
            continue
        kept = {
            key: record[key]
            for key in (
                "tier",
                "confidence",
                "approved",
                "approved_by",
                "approved_at",
            )
            if key in record
        }
        # Only a list of URLs survives; the legacy statistics mapping is
        # regenerated and must not be mistaken for approval evidence.
        if isinstance(record.get("evidence"), list):
            kept["evidence"] = list(record["evidence"])
        decided[normalized] = kept
    return decided


def render_worksheet_csv(worksheet: BrandWorksheet) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "brand",
            "normalized",
            "tier_TO_FILL",
            "distinct_target_oes",
            "tier_unknown_offers",
            "offer_count",
            "seller_count",
            "median_price_uah",
            "median_price_vs_kemp",
            "ratio_min",
            "ratio_max",
            "ratio_spread",
            "ratio_trustworthy",
            "paired_oe_count",
            "brand_variants",
            "example_url_1",
            "example_url_2",
            "example_url_3",
        ]
    )
    for row in worksheet.rows:
        urls = list(row.example_urls) + ["", "", ""]
        writer.writerow(
            [
                row.brand_display,
                row.brand_normalized,
                "",
                row.distinct_target_oes,
                row.tier_unknown_offers,
                row.offer_count,
                row.seller_count,
                row.median_price_uah if row.median_price_uah is not None else "",
                _optional_str(row.ratio.median) or "",
                _optional_str(row.ratio.minimum) or "",
                _optional_str(row.ratio.maximum) or "",
                _optional_str(row.ratio.spread) or "",
                "yes" if row.ratio.is_trustworthy else "no",
                row.ratio.paired_oe_count,
                " | ".join(row.brand_variants),
                urls[0],
                urls[1],
                urls[2],
            ]
        )
    return buffer.getvalue()


def render_worksheet_table(
    worksheet: BrandWorksheet, *, limit: int | None = None
) -> str:
    lines: list[str] = []
    lines.append("РАБОЧИЙ ЛИСТ РАЗМЕТКИ БРЕНДОВ (Фаза 2.1)")
    lines.append(
        f"наблюдений всего {worksheet.observation_count}   "
        f"конкурентных {worksheet.competitor_observation_count}   "
        f"якорь KEMP {worksheet.kemp_anchor_observation_count}   "
        f"целевых OE {worksheet.distinct_target_oes}"
    )
    trustworthy = sum(1 for row in worksheet.rows if row.ratio.is_trustworthy)
    lines.append(
        f"брендов к разметке: {len(worksheet.rows)}   "
        f"с пригодной подсказкой по цене: {trustworthy}"
    )
    lines.append(
        "«!» перед разбросом = отношения по разным OE расходятся сильнее "
        f"{MAX_TRUSTWORTHY_RATIO_SPREAD}x, медиане верить нельзя"
    )
    lines.append("")
    header = (
        f"{'бренд':<26}{'OE':>4}{'TIER_UNK':>9}{'предл.':>8}"
        f"{'прод.':>7}{'медиана,грн':>13}{'к KEMP':>9}{'разброс':>9}{'пар':>5}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    shown = worksheet.rows if limit is None else worksheet.rows[:limit]
    for row in shown:
        ratio = (
            f"{row.median_price_vs_kemp}"
            if row.median_price_vs_kemp is not None
            else "—"
        )
        price = f"{row.median_price_uah}" if row.median_price_uah is not None else "—"
        spread = _optional_str(row.ratio.spread) or "—"
        if not row.ratio.is_trustworthy and row.ratio.median is not None:
            spread = f"!{spread}"
        lines.append(
            f"{row.brand_display[:25]:<26}{row.distinct_target_oes:>4}"
            f"{row.tier_unknown_offers:>9}{row.offer_count:>8}"
            f"{row.seller_count:>7}{price:>13}{ratio:>9}{spread:>9}"
            f"{row.ratio.paired_oe_count:>5}"
        )
    if limit is not None and len(worksheet.rows) > limit:
        lines.append(f"... ещё {len(worksheet.rows) - limit} брендов, см. CSV")
    return "\n".join(lines)


def utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "ASSIGNABLE_TIERS",
    "BRAND_WORKSHEET_SCHEMA_VERSION",
    "BrandObservation",
    "BrandRow",
    "BrandWorksheet",
    "BrandWorksheetError",
    "MAX_TRUSTWORTHY_RATIO_SPREAD",
    "RatioSummary",
    "build_brand_worksheet",
    "deduplicate_observations",
    "is_reviewable_evidence_url",
    "load_brand_observations",
    "load_existing_records",
    "median_decimal",
    "observation_from_offer",
    "oem_identity_lane",
    "price_ratio_vs_kemp",
    "render_brands_draft_yaml",
    "render_worksheet_csv",
    "render_worksheet_table",
    "utc_now",
]
