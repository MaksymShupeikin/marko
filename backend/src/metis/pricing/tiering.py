"""Metis brand/tier classification with explicit conflict states."""

from __future__ import annotations

from decimal import Decimal
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from .types import ConditionState, ProductTier, TierClassification


TIER_METHOD_VERSION = "brand-tier-v1"
CONDITION_METHOD_VERSION = "yuri-v1-condition-v4"
CROSS_CANDIDATE_METHOD_VERSION = "description-cross-candidate-v1"

UNAPPROVED_ENGINEERING_BRAND_TIERS: dict[str, ProductTier] = {
    "AUDI": ProductTier.OEM,
    "BMW": ProductTier.OEM,
    "MERCEDESBENZ": ProductTier.OEM,
    "PORSCHE": ProductTier.OEM,
    "SEAT": ProductTier.OEM,
    "SKODA": ProductTier.OEM,
    "VAG": ProductTier.OEM,
    "VOLKSWAGEN": ProductTier.OEM,
    "BOSCH": ProductTier.OES,
    "CONTINENTAL": ProductTier.OES,
    "HELLA": ProductTier.OES,
    "LEMFORDER": ProductTier.OES,
    "NISSENS": ProductTier.OES,
    "SACHS": ProductTier.OES,
    "FEBI": ProductTier.AFTERMARKET_A,
    "MEYLE": ProductTier.AFTERMARKET_A,
    "SKF": ProductTier.AFTERMARKET_A,
    "TRW": ProductTier.AFTERMARKET_A,
    "DELPHI": ProductTier.AFTERMARKET_B,
    "FEBEST": ProductTier.AFTERMARKET_B,
    "MAXGEAR": ProductTier.AFTERMARKET_B,
    "RIDEX": ProductTier.BUDGET,
    "STARK": ProductTier.BUDGET,
    "KEMP": ProductTier.KEMP,
}

# Runtime callers must provide a reviewed dictionary explicitly.  KEMP is the
# sole safe default because its separate tier is a client requirement, not a
# market-quality inference.  The legacy engineering guesses above remain named
# and visible for audit/migration only; they are never a production default.
DEFAULT_BRAND_TIERS: dict[str, ProductTier] = {"KEMP": ProductTier.KEMP}

_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_NON_UNICODE_WORD = re.compile(r"[\W_]+", re.UNICODE)
_CYRILLIC_BRAND_ALIASES: dict[str, str] = {
    # Prom sellers use both a phonetic spelling and look-alike Cyrillic
    # characters for these frequent brands.  Keep the alias set explicit:
    # unknown Cyrillic text must still abstain instead of becoming a new rule.
    "КЕМР": "KEMP",
    "КЕМП": "KEMP",
    "БОШ": "BOSCH",
    "ФЕБИ": "FEBI",
}
_USED_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.UNICODE)
    for pattern in (
        r"(?<!\w)б\s*[./\\-]\s*у(?:\s*\.)?(?!\w)",
        r"(?<!\w)бу(?!\w)",
        r"(?<!\w)b\s*[./\\-]\s*u(?:\s*\.)?(?!\w)",
        r"(?<=\d)\s+bu(?=\s+_)",
        r"\bбывш(?:ий|ая|ее|ие)?\s+в\s+употреблении\b",
        r"\bвживан\w*\b",
        r"\bуживан\w*\b",
        r"\b(?:розборк|разборк|шрот)\w*\b",
        r"\b(?:used|refurbished|remanufactured)\b",
        r"\b(?:pre[- ]?owned|second[- ]?hand)\b",
        r"\b(?:відновлен|восстановлен)\w*\b",
    )
)
_NEW_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.UNICODE)
    for pattern in (
        r"\b(?:new|нов(?:ий|ая|ое|ые)|нов(?:а|е|і))\b",
        r"\bне\s+вживан\w*\b",
    )
)
_OEM_MARKERS = ("оригинал", "original", "genuine", "оем", " oem ")
_CROSS_TOKEN_RE = re.compile(
    r"(?<![\w])(?=[A-ZА-ЯІЇЄ0-9._/\- ]{5,28}(?![\w]))"
    r"(?=[A-ZА-ЯІЇЄ0-9._/\- ]*[A-ZА-ЯІЇЄ])"
    r"(?=[A-ZА-ЯІЇЄ0-9._/\- ]*\d)"
    r"[A-ZА-ЯІЇЄ0-9]+(?:[._/\- ][A-ZА-ЯІЇЄ0-9]+){1,5}(?![\w])",
    re.IGNORECASE | re.UNICODE,
)


@dataclass(frozen=True, slots=True)
class ConditionAssessment:
    state: ConditionState
    is_used: bool
    reason_codes: tuple[str, ...]
    evidence_sources: tuple[str, ...]
    method_version: str = CONDITION_METHOD_VERSION


@dataclass(frozen=True, slots=True)
class CrossCandidate:
    raw_token: str
    normalized_token: str
    context_window: str
    source_observation_id: str
    extraction_method_version: str = CROSS_CANDIDATE_METHOD_VERSION
    confidence: Decimal = Decimal("0.25")
    validation_state: str = "UNVALIDATED"
    automatic_identity_eligible: bool = False


def classify_condition(
    *,
    title: str | None,
    description: str | None,
    explicit_condition: str | None,
) -> ConditionAssessment:
    """Classify condition from every available lane.

    Владельческое решение 2026-08-21: карточка, молчащая о состоянии, читается
    как «новый товар» — на Prom про б/у пишут явно, и любой такой маркер
    по-прежнему уводит в USED_OR_REFURBISHED/CONFLICT.  До v4 молчание давало
    UNKNOWN и парковало предложение в ручной разбор.
    """

    fields = {
        "title": unicodedata.normalize("NFKC", title or ""),
        "description": unicodedata.normalize("NFKC", description or ""),
        "explicit_condition": unicodedata.normalize("NFKC", explicit_condition or ""),
    }
    used_sources = tuple(
        name
        for name, value in fields.items()
        if value and any(pattern.search(value) for pattern in _USED_PATTERNS)
    )
    new_sources = tuple(
        name
        for name, value in fields.items()
        if value and any(pattern.search(value) for pattern in _NEW_PATTERNS)
    )
    explicit = fields["explicit_condition"].casefold().strip()
    if explicit in {
        "used",
        "refurbished",
        "remanufactured",
        "б/у",
        "бу",
        "b/u",
        "bu",
        "вживаний",
    }:
        used_sources = tuple(dict.fromkeys(used_sources + ("explicit_condition",)))
    if explicit in {"new", "новий", "новая", "новое", "новий товар"}:
        new_sources = tuple(dict.fromkeys(new_sources + ("explicit_condition",)))

    if used_sources and new_sources:
        return ConditionAssessment(
            state=ConditionState.CONFLICT,
            is_used=True,
            reason_codes=("CONDITION_CONFLICT", "USED_SIGNAL_PRESENT"),
            evidence_sources=tuple(dict.fromkeys(used_sources + new_sources)),
        )
    if used_sources:
        return ConditionAssessment(
            state=ConditionState.USED_OR_REFURBISHED,
            is_used=True,
            reason_codes=("USED_OR_REFURBISHED",),
            evidence_sources=used_sources,
        )
    if new_sources:
        return ConditionAssessment(
            state=ConditionState.NEW,
            is_used=False,
            reason_codes=("CONDITION_NEW_VERIFIED",),
            evidence_sources=new_sources,
        )
    return ConditionAssessment(
        state=ConditionState.NEW,
        is_used=False,
        reason_codes=("CONDITION_NEW_ASSUMED_NO_USED_MARKERS",),
        evidence_sources=(),
    )


def extract_description_cross_candidates(
    description: str | None,
    *,
    source_observation_id: str,
) -> tuple[CrossCandidate, ...]:
    """Extract disabled phase-2 tokens; they never become automatic OE identity."""

    if not description:
        return ()
    normalized_description = unicodedata.normalize("NFKC", description)
    candidates: dict[str, CrossCandidate] = {}
    for match in _CROSS_TOKEN_RE.finditer(normalized_description.upper()):
        raw_token = normalized_description[match.start() : match.end()].strip()
        normalized_token = _NON_ALNUM.sub("", raw_token.upper())
        if len(normalized_token) < 5:
            continue
        start = max(0, match.start() - 40)
        end = min(len(normalized_description), match.end() + 40)
        candidates.setdefault(
            normalized_token,
            CrossCandidate(
                raw_token=raw_token,
                normalized_token=normalized_token,
                context_window=normalized_description[start:end],
                source_observation_id=source_observation_id,
            ),
        )
    return tuple(candidates[key] for key in sorted(candidates))


def normalize_brand(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).upper()
    unicode_token = _NON_UNICODE_WORD.sub("", normalized)
    alias = _CYRILLIC_BRAND_ALIASES.get(unicode_token)
    if alias is not None:
        return alias
    if any(
        character.isalpha() and not ("A" <= character <= "Z")
        for character in unicode_token
    ):
        return ""
    return _NON_ALNUM.sub("", normalized)


def classify_tier(
    *,
    brand: str | None,
    title: str,
    description: str | None = None,
    condition: str | None = None,
    manual_override: ProductTier | None = None,
    brand_tiers: Mapping[str, ProductTier] | None = None,
    method_version: str = TIER_METHOD_VERSION,
) -> TierClassification:
    text = f" {title} {description or ''} ".casefold()
    normalized_brand = normalize_brand(brand)
    rules = brand_tiers or DEFAULT_BRAND_TIERS

    if manual_override is not None:
        return TierClassification(
            tier=manual_override,
            confidence=Decimal("1"),
            is_used=manual_override == ProductTier.USED,
            is_kemp=manual_override == ProductTier.KEMP,
            exclusion_reason="USED" if manual_override == ProductTier.USED else None,
            reasons=("MANUAL_OVERRIDE",),
            method_version=method_version,
        )

    condition_assessment = classify_condition(
        title=title,
        description=description,
        explicit_condition=condition,
    )
    if condition_assessment.is_used:
        return TierClassification(
            tier=ProductTier.USED,
            confidence=Decimal("0.99"),
            is_used=True,
            is_kemp=False,
            exclusion_reason=condition_assessment.state.value,
            reasons=condition_assessment.reason_codes
            + tuple(
                f"CONDITION_SOURCE_{source.upper()}"
                for source in condition_assessment.evidence_sources
            ),
            method_version=method_version,
        )

    brand_tier = rules.get(normalized_brand)
    has_kemp_marker = re.search(r"\bkemp\b", text) is not None
    if normalized_brand == "KEMP":
        return TierClassification(
            tier=ProductTier.KEMP,
            confidence=Decimal("0.99"),
            is_used=False,
            is_kemp=True,
            exclusion_reason=None,
            reasons=("KEMP_MARKER",),
            method_version=method_version,
        )

    if has_kemp_marker and brand_tier not in (None, ProductTier.KEMP):
        return TierClassification(
            tier=ProductTier.UNKNOWN,
            confidence=Decimal("0.20"),
            is_used=False,
            is_kemp=False,
            exclusion_reason="TIER_CONFLICT",
            reasons=("KEMP_TEXT_BRAND_CONFLICT",),
            method_version=method_version,
        )

    has_oem_marker = any(marker in text for marker in _OEM_MARKERS)
    if has_oem_marker and brand_tier not in (None, ProductTier.OEM):
        return TierClassification(
            tier=ProductTier.UNKNOWN,
            confidence=Decimal("0.20"),
            is_used=False,
            is_kemp=False,
            exclusion_reason="TIER_CONFLICT",
            reasons=("OEM_TEXT_BRAND_CONFLICT",),
            method_version=method_version,
        )

    if brand_tier is not None:
        return TierClassification(
            tier=brand_tier,
            confidence=Decimal("0.95"),
            is_used=False,
            is_kemp=brand_tier == ProductTier.KEMP,
            exclusion_reason=None,
            reasons=("EXACT_BRAND_RULE",),
            method_version=method_version,
        )

    if has_kemp_marker:
        return TierClassification(
            tier=ProductTier.KEMP,
            confidence=Decimal("0.99"),
            is_used=False,
            is_kemp=True,
            exclusion_reason=None,
            reasons=("KEMP_MARKER",),
            method_version=method_version,
        )

    if has_oem_marker:
        return TierClassification(
            tier=ProductTier.OEM,
            confidence=Decimal("0.65"),
            is_used=False,
            is_kemp=False,
            exclusion_reason=None,
            reasons=("OEM_TEXT_MARKER",),
            method_version=method_version,
        )

    return TierClassification(
        tier=ProductTier.UNKNOWN,
        confidence=Decimal("0"),
        is_used=False,
        is_kemp=False,
        exclusion_reason="UNKNOWN_TIER",
        reasons=("NO_TIER_EVIDENCE",),
        method_version=method_version,
    )
