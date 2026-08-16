"""Deterministic commercial-integrity checks for marketplace offers.

The pricing rule may deliberately use the cheapest comparable offer.  That
makes the displayed amount itself a high-impact input: a price-on-request card,
deposit, used part, wholesale-only amount, or a lone placeholder floor must not
silently become the recommendation.  These checks do not decide product
identity and do not invent a replacement price.  They either pass the card,
exclude an explicit commercial contradiction, or require a human review.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import re
from typing import Any


OFFER_INTEGRITY_METHOD_VERSION = "offer-integrity-v3"
DEFAULT_FLOOR_GAP_RATIO = Decimal("0.75")


class OfferIntegrityStatus(StrEnum):
    PASS = "PASS"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class OfferIntegrityAssessment:
    status: OfferIntegrityStatus
    reason_codes: tuple[str, ...]
    evidence: tuple[dict[str, str], ...]
    method_version: str = OFFER_INTEGRITY_METHOD_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason_codes": list(self.reason_codes),
            "evidence": [dict(value) for value in self.evidence],
            "method_version": self.method_version,
        }


@dataclass(frozen=True, slots=True)
class OfferAmountContext:
    displayed_amount: Decimal
    currency: str
    customer_amount: Decimal | None
    lowest_peer_amount: Decimal | None
    next_independent_seller_amount: Decimal | None
    floor_gap_ratio: Decimal | None
    assessment: OfferIntegrityAssessment

    def as_dict(self) -> dict[str, Any]:
        return {
            "purpose": "commercial_integrity_only_not_price_setting",
            "displayed_amount": str(self.displayed_amount),
            "currency": self.currency,
            "customer_amount": (
                None if self.customer_amount is None else str(self.customer_amount)
            ),
            "lowest_peer_amount": (
                None
                if self.lowest_peer_amount is None
                else str(self.lowest_peer_amount)
            ),
            "next_independent_seller_amount": (
                None
                if self.next_independent_seller_amount is None
                else str(self.next_independent_seller_amount)
            ),
            "floor_gap_ratio": (
                None if self.floor_gap_ratio is None else str(self.floor_gap_ratio)
            ),
            "assessment": self.assessment.as_dict(),
        }


_REJECT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "PRICE_ON_REQUEST",
        re.compile(
            r"\b(?:price\s+on\s+request|ask\s+for\s+price|contact\s+for\s+price|"
            r"цена\s+(?:по\s+запросу|условн(?:ая|а)|не\s+актуальна)|"
            r"цен[ау]\s+уточн|уточн(?:яйте|ити)\s+цен|"
            r"ц[іi]на\s+(?:за\s+запитом|умовна|не\s+актуальна)|"
            r"варт[іi]сть\s+уточн|догов[іi]рна\s+ц[іi]на)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "SERVICE_NOT_PART",
        re.compile(
            r"\b(?:услуга\s+(?:по\s+)?(?:ремонту|реставрации|диагностике)|"
            r"послуга\s+(?:з\s+)?(?:ремонту|реставрації|діагностики)|"
            r"ремонт\s+на\s+заказ|реставрация\s+вашей|"
            r"реставрація\s+вашої|оренда|аренда)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "USED_OR_REFURBISHED",
        re.compile(
            r"(?:\bб\s*[/\\.-]?\s*у\b|\bвживан\w*\b|\bused\b|"
            r"\brefurbished\b|\bвідновлен\w*\b|\bвосстановлен\w*\b|"
            r"\bразборк\w*\b|\bшрот\b)",
            re.IGNORECASE,
        ),
    ),
    (
        # A parts donor or a non-working unit is never a price for a new part.
        # «В нерабочее время» is a phone-hours phrase, not a defect, so the
        # non-working adjective excludes time words explicitly.
        "PARTS_DONOR",
        re.compile(
            r"(?:\bна\s+запчаст\w+|\bна\s+запчастин\w*|\bдонор\w*\b|"
            r"\bfor\s+parts\b|\bparts\s+(?:only|donor)\b|"
            r"\bнерабоч\w*\b(?!\s+(?:врем\w+|дн\w+|день|час\w*|график\w*))|"
            r"\bнеробоч\w*\b(?!\s+(?:час\w*|дн\w*|день|графік\w*)))",
            re.IGNORECASE,
        ),
    ),
)

_REVIEW_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "STARTING_OR_VARIANT_PRICE",
        re.compile(
            r"(?:\b(?:цена|ц[іi]на|price)\s+от\b|\bвід\s+\d|\bfrom\s+\d|"
            r"залежить\s+від|зависит\s+от\s+(?:модел|комплект|вариант))",
            re.IGNORECASE,
        ),
    ),
    (
        "DEPOSIT_OR_EXCHANGE_AMOUNT",
        re.compile(
            r"\b(?:залог|застав[ауи]|депозит|обменн(?:ый|ая)\s+фонд|"
            r"обм[іi]нний\s+фонд|core\s+charge|exchange\s+unit)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "WHOLESALE_OR_MINIMUM_QUANTITY",
        re.compile(
            r"\b(?:опт(?:ом|ова|овий)?|wholesale|мінімальн\w+\s+(?:замовлення|"
            r"кількість)|минимальн\w+\s+(?:заказ|количеств)|від\s+\d+\s*шт|"
            r"от\s+\d+\s*шт)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "DAMAGED_OR_INCOMPLETE",
        re.compile(
            r"\b(?:поврежден\w*|пошкоджен\w*|дефект\w*|некомплект\w*|"
            r"без\s+(?:датчика|кронштейна|кришки|крышки|мотора|упаковки))\b",
            re.IGNORECASE,
        ),
    ),
    (
        # "Без предоплаты" is an ordinary cash-on-delivery listing, so the
        # prepayment marker fires only when it is not negated.
        "PREPAYMENT_OR_PREORDER",
        re.compile(
            r"(?:(?<!без\s)(?<!без\s\s)\bпредоплат\w*|"
            r"(?<!без\s)\bпередплат\w*|\bпредзаказ\w*|\bpre-?order\w*\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "MADE_TO_ORDER",
        re.compile(
            r"\b(?:под\s+заказ|п[іi]д\s+замовлення|made\s+to\s+order|"
            r"on\s+order|изгот\w+\s+под\s+заказ)\b",
            re.IGNORECASE,
        ),
    ),
    (
        # Word boundaries keep «торг» away from «торговый».
        "BARGAIN_OR_AUCTION",
        re.compile(
            r"\b(?:торг|торгом|торгуюсь|аукцион\w*|аукц[іi]он\w*|auction\w*)\b",
            re.IGNORECASE,
        ),
    ),
)

# «Без пошкоджень», «без дефектів та подряпин» is a seller asserting the item
# is intact -- the opposite of damage.  The whole negated phrase is removed
# before the markers run, because a bare lookbehind on «без » cannot reach the
# second noun of a conjunction («… без пошкоджень та дефектів») and three
# exact-OE VW T4 carriages were parked by their own "brand new, undamaged"
# boilerplate.  «Без упаковки/датчика/…» stays: a missing part is real
# incompleteness, and this phrase only swallows the damage nouns themselves.
_NEGATED_DAMAGE_PHRASE = re.compile(
    r"\bбез\s+(?:будь[-\s]яких\s+|каких[-\s]либо\s+)?"
    r"(?:поврежден\w*|пошкоджен\w*|дефект\w*|некомплект\w*)"
    r"(?:\s*(?:,|та|і|и|and|/)\s*"
    r"(?:поврежден\w*|пошкоджен\w*|дефект\w*|некомплект\w*|"
    r"подряпин\w*|царапин\w*|сколів|сколов))*",
    re.IGNORECASE,
)

_PRICE_PER_PIECE = re.compile(
    r"\b(?:цена|ц[іi]на|price)\s+за\s+(?:штуку|шт\.?|одиницю|единицу|одну|1\s*шт)",
    re.IGNORECASE,
)
_PRICE_PER_SET = re.compile(
    r"\b(?:цена|ц[іi]на|price)\s+за\s+(?:комплект|набор|набір|пару|kit|set)\b",
    re.IGNORECASE,
)
_UNIT_SET_TOKENS = ("компл", "набор", "набір", "пара", "парн", "kit", "set")
_UNIT_PIECE_TOKENS = ("шт", "штук", "одиниц", "piece", "pc")


def _bounded_text(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, Mapping):
            for key, child in value.items():
                parts.extend((str(key), str(child)))
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            parts.extend(str(child) for child in value)
        else:
            parts.append(str(value))
    return " ".join(" ".join(parts).split())[:24_000]


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed > 0 else None


def assess_offer_integrity(
    *,
    title: Any = None,
    description: Any = None,
    condition: Any = None,
    characteristics: Any = None,
    measure_unit: Any = None,
    is_available: bool | None = None,
    detail_evidence_safe: bool | None = None,
) -> OfferIntegrityAssessment:
    """Classify explicit commercial traps without using statistical inference."""

    text = _NEGATED_DAMAGE_PHRASE.sub(" ", _bounded_text(
        title,
        description,
        condition,
        characteristics,
        measure_unit,
    ))
    rejects: list[str] = []
    reviews: list[str] = []
    evidence: list[dict[str, str]] = []
    for code, pattern in _REJECT_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            rejects.append(code)
            evidence.append({"reason_code": code, "excerpt": match.group(0)[:240]})
    for code, pattern in _REVIEW_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            reviews.append(code)
            evidence.append({"reason_code": code, "excerpt": match.group(0)[:240]})
    # A listing whose own unit contradicts the unit its price phrase refers to
    # («ціна за штуку» on a card sold in pairs) cannot set a target until a
    # human decides which amount is real.  Only explicit phrases count, and
    # only against the card's own measure unit — never a guess about ours.
    unit_text = " ".join(str(measure_unit or "").casefold().split())
    unit_match: re.Match[str] | None = None
    if unit_text:
        piece_phrase = _PRICE_PER_PIECE.search(text)
        set_phrase = _PRICE_PER_SET.search(text)
        if piece_phrase is not None and any(
            token in unit_text for token in _UNIT_SET_TOKENS
        ):
            unit_match = piece_phrase
        elif set_phrase is not None and any(
            token in unit_text for token in _UNIT_PIECE_TOKENS
        ):
            unit_match = set_phrase
    if unit_match is not None:
        reviews.append("UNIT_AMBIGUITY")
        evidence.append(
            {"reason_code": "UNIT_AMBIGUITY", "excerpt": unit_match.group(0)[:240]}
        )
    if is_available is False:
        rejects.append("NOT_AVAILABLE")
    elif is_available is None:
        reviews.append("AVAILABILITY_UNKNOWN")
    if detail_evidence_safe is False:
        reviews.append("EXACT_DETAIL_EVIDENCE_MISSING")

    if rejects:
        status = OfferIntegrityStatus.REJECT
        reasons = tuple(dict.fromkeys((*rejects, *reviews)))
    elif reviews:
        status = OfferIntegrityStatus.MANUAL_REVIEW
        reasons = tuple(dict.fromkeys(reviews))
    else:
        status = OfferIntegrityStatus.PASS
        reasons = ("DISPLAYED_PRICE_COMMERCIALLY_USABLE",)
    return OfferIntegrityAssessment(status, reasons, tuple(evidence))


def build_offer_amount_context(
    *,
    displayed_amount: Any,
    currency: str,
    customer_amount: Any = None,
    peer_offers: Sequence[tuple[Any, str | None]] = (),
    assessment: OfferIntegrityAssessment,
    floor_gap_ratio: Decimal = DEFAULT_FLOOR_GAP_RATIO,
) -> OfferAmountContext:
    """Add simple cross-seller floor logic to a content assessment.

    The rule is intentionally not a statistical outlier model.  Prices are
    reduced to one lowest amount per stable seller.  A candidate that is the
    sole floor and is below ``floor_gap_ratio`` of the next seller is labelled
    for review; it is never silently discarded and the next price is never
    substituted as if it were proven correct.
    """

    displayed = _decimal(displayed_amount)
    if displayed is None:
        raise ValueError("displayed_amount must be a positive finite number")
    customer = _decimal(customer_amount)
    by_seller: dict[str, Decimal] = {}
    for raw_amount, seller_id in peer_offers:
        amount = _decimal(raw_amount)
        seller = str(seller_id or "").strip()
        if amount is None or not seller:
            continue
        current = by_seller.get(seller)
        if current is None or amount < current:
            by_seller[seller] = amount
    ordered = sorted(by_seller.values())
    lowest = ordered[0] if ordered else None
    # ``peer_offers`` excludes the candidate.  Therefore an independent peer
    # at or below the displayed amount corroborates the floor and suppresses
    # the lone-floor warning even if a third seller is much more expensive.
    floor_is_corroborated = any(value <= displayed for value in ordered)
    next_amount = next((value for value in ordered if value > displayed), None)
    gap = displayed / next_amount if next_amount is not None else None

    reasons = list(assessment.reason_codes)
    evidence = list(assessment.evidence)
    status = assessment.status
    if not floor_is_corroborated and gap is not None and gap < floor_gap_ratio:
        reasons.append("SINGLE_LISTING_FLOOR_GAP")
        evidence.append(
            {
                "reason_code": "SINGLE_LISTING_FLOOR_GAP",
                "excerpt": (
                    f"displayed={displayed}; next_seller={next_amount}; "
                    f"ratio={gap.quantize(Decimal('0.0001'))}"
                ),
            }
        )
        if status is OfferIntegrityStatus.PASS:
            status = OfferIntegrityStatus.MANUAL_REVIEW
    merged = OfferIntegrityAssessment(
        status=status,
        reason_codes=tuple(dict.fromkeys(reasons)),
        evidence=tuple(evidence),
    )
    return OfferAmountContext(
        displayed_amount=displayed,
        currency=str(currency or "").strip().upper(),
        customer_amount=customer,
        lowest_peer_amount=lowest,
        next_independent_seller_amount=next_amount,
        floor_gap_ratio=gap,
        assessment=merged,
    )


def assessment_from_context(
    value: Mapping[str, Any] | None,
) -> OfferIntegrityAssessment:
    raw = value or {}
    assessment = raw.get("assessment")
    assessment = assessment if isinstance(assessment, Mapping) else raw
    try:
        status = OfferIntegrityStatus(str(assessment.get("status") or "MANUAL_REVIEW"))
    except ValueError:
        status = OfferIntegrityStatus.MANUAL_REVIEW
    reasons = tuple(
        str(code) for code in assessment.get("reason_codes", ()) if str(code).strip()
    )
    evidence = tuple(
        {str(key): str(child) for key, child in row.items()}
        for row in assessment.get("evidence", ())
        if isinstance(row, Mapping)
    )
    return OfferIntegrityAssessment(
        status=status,
        reason_codes=reasons or ("OFFER_INTEGRITY_CONTEXT_MISSING",),
        evidence=evidence,
        method_version=str(
            assessment.get("method_version") or OFFER_INTEGRITY_METHOD_VERSION
        ),
    )


__all__ = [
    "DEFAULT_FLOOR_GAP_RATIO",
    "OFFER_INTEGRITY_METHOD_VERSION",
    "OfferAmountContext",
    "OfferIntegrityAssessment",
    "OfferIntegrityStatus",
    "assess_offer_integrity",
    "assessment_from_context",
    "build_offer_amount_context",
]
