"""Deterministic description-cross extraction and fail-closed validation.

This module implements Path 2 stages A and B only. A confirmed link remains
evidence, not a market observation: Stage C collection is guarded separately.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any
import unicodedata

import yaml

from .types import ProductTier


CROSSES_SCHEMA_VERSION = "metis-description-crosses-v1"


class CrossConfigError(ValueError):
    """Raised when crosses.yaml cannot support deterministic execution."""


class CrossStageCBlocked(RuntimeError):
    """Raised when Stage C is attempted without an approved market taxonomy."""


class CrossValidationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class CrossRejectionReason(str, Enum):
    DIMENSION = "dimension"
    YEAR_OR_RANGE = "year_or_range"
    PHONE = "phone"
    VIN = "vin"
    GTIN = "gtin"
    ENGINE_DISPLACEMENT = "engine_displacement"
    OWN_OEM = "own_oem"
    PRICE = "price"
    NON_ASCII = "non_ascii"
    OUTSIDE_LENGTH = "outside_length"
    MISSING_ALPHA_OR_DIGIT = "missing_alpha_or_digit"
    CATEGORY_MISMATCH = "category_mismatch"
    PRICE_OUT_OF_BAND = "price_out_of_band"


@dataclass(frozen=True, slots=True)
class CrossExtractionConfig:
    minimum_description_chars: int
    candidate_raw_max_chars: int
    alphanumeric_min_length: int
    alphanumeric_max_length: int
    numeric_min_length: int
    numeric_max_length: int
    context_chars_each_side: int
    explicit_marker_window_chars: int
    currency_context_chars: int
    engine_context_chars: int
    phone_min_digits: int
    phone_prefixes: tuple[str, ...]
    vin_length: int
    gtin_lengths: tuple[int, ...]
    year_min: int
    year_max: int
    token_delimiters: tuple[str, ...]
    edge_strip_chars: str
    marker_delimiters: Mapping[str, tuple[str, ...]]
    extraction_method_precedence: tuple[str, ...]
    currency_markers: tuple[str, ...]
    engine_markers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CrossValidationConfig:
    reject_price_ratio_min: Decimal
    reject_price_ratio_max: Decimal
    review_price_ratio_min: Decimal
    review_price_ratio_max: Decimal
    reciprocal_window_chars: int
    status_precedence: tuple[CrossValidationStatus, ...]


@dataclass(frozen=True, slots=True)
class CrossStageCConfig:
    minimum_approved_non_kemp_tiers: int
    via_cross_match_confidence_step: Decimal
    all_via_cross_max_confidence: str


@dataclass(frozen=True, slots=True)
class CrossReportingConfig:
    baseline_mean_offers: Decimal
    baseline_median_offers: Decimal
    weak_growth_ceiling: Decimal


@dataclass(frozen=True, slots=True)
class CrossConfig:
    schema_version: str
    method_version: str
    extraction: CrossExtractionConfig
    validation: CrossValidationConfig
    stage_c: CrossStageCConfig
    reporting: CrossReportingConfig
    source_path: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class CrossListing:
    listing_id: str
    our_oem_norm: str
    description: str | None
    source_listing_url: str
    source_seller: str
    price: Decimal | None
    source_seller_id: str | None = None
    our_category: str | None = None
    source_category: str | None = None


@dataclass(frozen=True, slots=True)
class CrossCandidateEvidence:
    listing_id: str
    our_oem_norm: str
    extracted_oem_norm: str
    source_listing_url: str
    source_seller: str
    source_seller_id: str | None
    raw_context: str
    extraction_method: str
    source_price: Decimal | None
    our_category: str | None
    source_category: str | None


@dataclass(frozen=True, slots=True)
class CrossExtractionRejection:
    listing_id: str
    our_oem_norm: str
    raw_token: str
    normalized_token: str
    raw_context: str
    reason: CrossRejectionReason


@dataclass(frozen=True, slots=True)
class CrossExtractionResult:
    listing_id: str
    description_state: str
    segments_scanned: int
    candidates: tuple[CrossCandidateEvidence, ...]
    rejections: tuple[CrossExtractionRejection, ...]


@dataclass(frozen=True, slots=True)
class CrossSourceDecision:
    candidate: CrossCandidateEvidence
    status: CrossValidationStatus
    rejection_reason: CrossRejectionReason | None
    reciprocal_evidence_url: str | None
    validation_details: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CrossPairDecision:
    our_oem_norm: str
    extracted_oem_norm: str
    source_listing_url: str
    source_seller: str
    raw_context: str
    extraction_method: str
    validation_status: CrossValidationStatus
    rejection_reason: CrossRejectionReason | None
    reciprocal_evidence_url: str | None
    source_evidence: tuple[Mapping[str, Any], ...]
    validation_details: Mapping[str, Any]

    @property
    def automatic_eligible(self) -> bool:
        return (
            self.validation_status is CrossValidationStatus.CONFIRMED
            and int(self.validation_details.get("independent_seller_count", 0)) >= 2
        )


@dataclass(frozen=True, slots=True)
class CrossABResult:
    listings_total: int
    descriptions_available: int
    descriptions_empty_or_short: int
    candidates: tuple[CrossCandidateEvidence, ...]
    rejections: tuple[CrossExtractionRejection, ...]
    source_decisions: tuple[CrossSourceDecision, ...]
    pair_decisions: tuple[CrossPairDecision, ...]
    rejection_counts: Mapping[str, int] = field(default_factory=dict)
    status_counts: Mapping[str, int] = field(default_factory=dict)


def evaluate_real_fixture_checks(
    result: CrossABResult,
    rows: Sequence[Mapping[str, str]],
) -> dict[str, bool]:
    """Evaluate the mandatory safety checks over a real replay corpus."""

    rejections_by_listing: dict[str, set[str]] = {}
    for rejection in result.rejections:
        rejections_by_listing.setdefault(rejection.listing_id, set()).add(
            rejection.reason.value
        )
    candidates_by_listing: dict[str, int] = {}
    for candidate in result.candidates:
        candidates_by_listing[candidate.listing_id] = (
            candidates_by_listing.get(candidate.listing_id, 0) + 1
        )
    empty_listing_ids = {
        row["listing_id"]
        for row in rows
        if not (row.get("description") or "").strip()
    }
    empty_rows_are_safe = not empty_listing_ids or not any(
        item.listing_id in empty_listing_ids
        for item in (*result.candidates, *result.rejections)
    )
    return {
        "real_description_with_dimension_filtered": any(
            "dimension" in reasons for reasons in rejections_by_listing.values()
        ),
        "real_description_with_three_analog_numbers_extracted": any(
            count >= 3 for count in candidates_by_listing.values()
        ),
        "real_description_with_phone_and_year_filtered": any(
            {"phone", "year_or_range"}.issubset(reasons)
            for reasons in rejections_by_listing.values()
        ),
        "real_empty_or_short_description_safe": empty_rows_are_safe,
    }


def load_cross_config(path: str | Path) -> CrossConfig:
    """Load every Stage A-D threshold from a versioned YAML contract."""

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise CrossConfigError(f"Cross config does not exist: {source_path}")
    raw = source_path.read_bytes()
    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise CrossConfigError("Cross config is not valid YAML") from exc
    root = _mapping(payload, "root")
    if root.get("schema_version") != CROSSES_SCHEMA_VERSION:
        raise CrossConfigError(
            f"Unsupported cross config schema: {root.get('schema_version')!r}"
        )
    method_version = _text(root.get("method_version"), "method_version")
    extraction_raw = _mapping(root.get("extraction"), "extraction")
    validation_raw = _mapping(root.get("validation"), "validation")
    stage_c_raw = _mapping(root.get("stage_c"), "stage_c")
    reporting_raw = _mapping(root.get("reporting"), "reporting")

    marker_raw = _mapping(
        extraction_raw.get("marker_delimiters"), "extraction.marker_delimiters"
    )
    marker_delimiters = {
        _text(method, "extraction.marker_delimiters key"): _string_tuple(
            phrases, f"extraction.marker_delimiters.{method}"
        )
        for method, phrases in marker_raw.items()
    }
    method_precedence = _string_tuple(
        extraction_raw.get("extraction_method_precedence"),
        "extraction.extraction_method_precedence",
    )
    if set(method_precedence) != set(marker_delimiters) | {"UNMARKED"}:
        raise CrossConfigError(
            "extraction_method_precedence must contain every marker method and UNMARKED"
        )

    extraction = CrossExtractionConfig(
        minimum_description_chars=_positive_int(
            extraction_raw.get("minimum_description_chars"),
            "extraction.minimum_description_chars",
        ),
        candidate_raw_max_chars=_positive_int(
            extraction_raw.get("candidate_raw_max_chars"),
            "extraction.candidate_raw_max_chars",
        ),
        alphanumeric_min_length=_positive_int(
            extraction_raw.get("alphanumeric_min_length"),
            "extraction.alphanumeric_min_length",
        ),
        alphanumeric_max_length=_positive_int(
            extraction_raw.get("alphanumeric_max_length"),
            "extraction.alphanumeric_max_length",
        ),
        numeric_min_length=_positive_int(
            extraction_raw.get("numeric_min_length"),
            "extraction.numeric_min_length",
        ),
        numeric_max_length=_positive_int(
            extraction_raw.get("numeric_max_length"),
            "extraction.numeric_max_length",
        ),
        context_chars_each_side=_positive_int(
            extraction_raw.get("context_chars_each_side"),
            "extraction.context_chars_each_side",
        ),
        explicit_marker_window_chars=_positive_int(
            extraction_raw.get("explicit_marker_window_chars"),
            "extraction.explicit_marker_window_chars",
        ),
        currency_context_chars=_positive_int(
            extraction_raw.get("currency_context_chars"),
            "extraction.currency_context_chars",
        ),
        engine_context_chars=_positive_int(
            extraction_raw.get("engine_context_chars"),
            "extraction.engine_context_chars",
        ),
        phone_min_digits=_positive_int(
            extraction_raw.get("phone_min_digits"),
            "extraction.phone_min_digits",
        ),
        phone_prefixes=_string_tuple(
            extraction_raw.get("phone_prefixes"), "extraction.phone_prefixes"
        ),
        vin_length=_positive_int(
            extraction_raw.get("vin_length"), "extraction.vin_length"
        ),
        gtin_lengths=_int_tuple(
            extraction_raw.get("gtin_lengths"), "extraction.gtin_lengths"
        ),
        year_min=_positive_int(extraction_raw.get("year_min"), "extraction.year_min"),
        year_max=_positive_int(extraction_raw.get("year_max"), "extraction.year_max"),
        token_delimiters=_raw_string_tuple(
            extraction_raw.get("token_delimiters"),
            "extraction.token_delimiters",
        ),
        edge_strip_chars=_text(
            extraction_raw.get("edge_strip_chars"), "extraction.edge_strip_chars"
        ),
        marker_delimiters=MappingProxyType(marker_delimiters),
        extraction_method_precedence=method_precedence,
        currency_markers=_string_tuple(
            extraction_raw.get("currency_markers"), "extraction.currency_markers"
        ),
        engine_markers=_string_tuple(
            extraction_raw.get("engine_markers"), "extraction.engine_markers"
        ),
    )
    if extraction.alphanumeric_min_length > extraction.alphanumeric_max_length:
        raise CrossConfigError("alphanumeric length bounds are reversed")
    if extraction.numeric_min_length > extraction.numeric_max_length:
        raise CrossConfigError("numeric length bounds are reversed")
    if extraction.year_min > extraction.year_max:
        raise CrossConfigError("year bounds are reversed")

    status_precedence_raw = _string_tuple(
        validation_raw.get("status_precedence"), "validation.status_precedence"
    )
    try:
        status_precedence = tuple(
            CrossValidationStatus(value) for value in status_precedence_raw
        )
    except ValueError as exc:
        raise CrossConfigError("status_precedence contains an invalid status") from exc
    if set(status_precedence) != set(CrossValidationStatus):
        raise CrossConfigError(
            "status_precedence must contain every status exactly once"
        )
    validation = CrossValidationConfig(
        reject_price_ratio_min=_decimal(
            validation_raw.get("reject_price_ratio_min"),
            "validation.reject_price_ratio_min",
        ),
        reject_price_ratio_max=_decimal(
            validation_raw.get("reject_price_ratio_max"),
            "validation.reject_price_ratio_max",
        ),
        review_price_ratio_min=_decimal(
            validation_raw.get("review_price_ratio_min"),
            "validation.review_price_ratio_min",
        ),
        review_price_ratio_max=_decimal(
            validation_raw.get("review_price_ratio_max"),
            "validation.review_price_ratio_max",
        ),
        reciprocal_window_chars=_positive_int(
            validation_raw.get("reciprocal_window_chars"),
            "validation.reciprocal_window_chars",
        ),
        status_precedence=status_precedence,
    )
    if not (
        Decimal("0")
        < validation.reject_price_ratio_min
        <= validation.review_price_ratio_min
        <= validation.review_price_ratio_max
        <= validation.reject_price_ratio_max
    ):
        raise CrossConfigError("price ratio bands must be nested and positive")

    stage_c = CrossStageCConfig(
        minimum_approved_non_kemp_tiers=_positive_int(
            stage_c_raw.get("minimum_approved_non_kemp_tiers"),
            "stage_c.minimum_approved_non_kemp_tiers",
        ),
        via_cross_match_confidence_step=_unit_decimal(
            stage_c_raw.get("via_cross_match_confidence_step"),
            "stage_c.via_cross_match_confidence_step",
        ),
        all_via_cross_max_confidence=_text(
            stage_c_raw.get("all_via_cross_max_confidence"),
            "stage_c.all_via_cross_max_confidence",
        ),
    )
    reporting = CrossReportingConfig(
        baseline_mean_offers=_decimal(
            reporting_raw.get("baseline_mean_offers"),
            "reporting.baseline_mean_offers",
        ),
        baseline_median_offers=_decimal(
            reporting_raw.get("baseline_median_offers"),
            "reporting.baseline_median_offers",
        ),
        weak_growth_ceiling=_decimal(
            reporting_raw.get("weak_growth_ceiling"),
            "reporting.weak_growth_ceiling",
        ),
    )
    return CrossConfig(
        schema_version=CROSSES_SCHEMA_VERSION,
        method_version=method_version,
        extraction=extraction,
        validation=validation,
        stage_c=stage_c,
        reporting=reporting,
        source_path=str(source_path.resolve()),
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )


def normalize_cross_oem(value: str | None) -> str:
    """NFKC + uppercase + ASCII alphanumeric normalization for Path 2."""

    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).upper()
    return re.sub(r"[^A-Z0-9]", "", normalized)


def extract_cross_candidates(
    listing: CrossListing,
    config: CrossConfig,
) -> CrossExtractionResult:
    """Stage A: tokenize before normalization and retain every rejection reason."""

    description = unicodedata.normalize("NFKC", listing.description or "")
    if len(description.strip()) < config.extraction.minimum_description_chars:
        return CrossExtractionResult(
            listing_id=listing.listing_id,
            description_state="EMPTY_OR_SHORT",
            segments_scanned=0,
            candidates=(),
            rejections=(),
        )
    own_oem = normalize_cross_oem(listing.our_oem_norm)
    marker_matches = _marker_matches(description, config.extraction)
    candidates: dict[str, CrossCandidateEvidence] = {}
    rejections: list[CrossExtractionRejection] = []
    segments_scanned = 0
    for start, end, raw_token in _token_spans(description, config.extraction):
        if not any(character.isdigit() for character in raw_token):
            continue
        segments_scanned += 1
        normalized_token = normalize_cross_oem(raw_token)
        context = _context(
            description,
            start,
            end,
            config.extraction.context_chars_each_side,
        )
        reason = _candidate_rejection_reason(
            raw_token=raw_token,
            normalized_token=normalized_token,
            own_oem=own_oem,
            description=description,
            token_start=start,
            token_end=end,
            config=config.extraction,
        )
        if reason is not None:
            rejections.append(
                CrossExtractionRejection(
                    listing_id=listing.listing_id,
                    our_oem_norm=own_oem,
                    raw_token=raw_token,
                    normalized_token=normalized_token,
                    raw_context=context,
                    reason=reason,
                )
            )
            continue
        method = _extraction_method(
            marker_matches,
            token_start=start,
            description=description,
            config=config.extraction,
        )
        candidate = CrossCandidateEvidence(
            listing_id=listing.listing_id,
            our_oem_norm=own_oem,
            extracted_oem_norm=normalized_token,
            source_listing_url=listing.source_listing_url,
            source_seller=listing.source_seller,
            source_seller_id=listing.source_seller_id,
            raw_context=context,
            extraction_method=method,
            source_price=listing.price,
            our_category=_optional_text(listing.our_category),
            source_category=_optional_text(listing.source_category),
        )
        current = candidates.get(normalized_token)
        if current is None or _method_rank(
            candidate.extraction_method, config.extraction
        ) < _method_rank(current.extraction_method, config.extraction):
            candidates[normalized_token] = candidate
    return CrossExtractionResult(
        listing_id=listing.listing_id,
        description_state="AVAILABLE",
        segments_scanned=segments_scanned,
        candidates=tuple(candidates[key] for key in sorted(candidates)),
        rejections=tuple(rejections),
    )


def run_cross_stages_ab(
    listings: Sequence[CrossListing],
    config: CrossConfig,
) -> CrossABResult:
    """Execute Stages A+B on a pinned replay without performing network I/O."""

    ordered = tuple(
        sorted(
            listings,
            key=lambda row: (
                normalize_cross_oem(row.our_oem_norm),
                row.listing_id,
                row.source_listing_url,
            ),
        )
    )
    extraction_results = tuple(
        extract_cross_candidates(listing, config) for listing in ordered
    )
    candidates = tuple(
        candidate for result in extraction_results for candidate in result.candidates
    )
    rejections = tuple(
        rejection for result in extraction_results for rejection in result.rejections
    )
    known_prices = _known_prices_by_oe(ordered)
    source_decisions = tuple(
        _validate_candidate(
            candidate,
            listings=ordered,
            known_prices=known_prices,
            config=config,
        )
        for candidate in candidates
    )
    pair_decisions = _deduplicate_pair_decisions(source_decisions, config)
    rejection_counts = Counter(item.reason.value for item in rejections)
    rejection_counts.update(
        item.rejection_reason.value
        for item in source_decisions
        if item.rejection_reason is not None
    )
    status_counts = Counter(item.validation_status.value for item in pair_decisions)
    return CrossABResult(
        listings_total=len(ordered),
        descriptions_available=sum(
            result.description_state == "AVAILABLE" for result in extraction_results
        ),
        descriptions_empty_or_short=sum(
            result.description_state == "EMPTY_OR_SHORT"
            for result in extraction_results
        ),
        candidates=candidates,
        rejections=rejections,
        source_decisions=source_decisions,
        pair_decisions=pair_decisions,
        rejection_counts=MappingProxyType(dict(sorted(rejection_counts.items()))),
        status_counts=MappingProxyType(dict(sorted(status_counts.items()))),
    )


def require_stage_c_brand_dictionary(
    approved_tiers: Mapping[str, ProductTier],
    config: CrossConfig,
) -> int:
    """Runtime Stage C stop-gate; never infer approval from draft rows."""

    approved_non_kemp = sum(
        normalized != "KEMP"
        and tier not in {ProductTier.KEMP, ProductTier.UNKNOWN, ProductTier.USED}
        for normalized, tier in approved_tiers.items()
    )
    if approved_non_kemp < config.stage_c.minimum_approved_non_kemp_tiers:
        raise CrossStageCBlocked(
            "brand dictionary is empty; Stage C is pointless: "
            "new offers would all classify as UNKNOWN"
        )
    return approved_non_kemp


def _validate_candidate(
    candidate: CrossCandidateEvidence,
    *,
    listings: Sequence[CrossListing],
    known_prices: Mapping[str, tuple[Decimal, ...]],
    config: CrossConfig,
) -> CrossSourceDecision:
    details: dict[str, Any] = {}
    our_category = _category(candidate.our_category)
    source_category = _category(candidate.source_category)
    if our_category is not None and source_category is not None:
        if our_category != source_category:
            details["category_check"] = "mismatch"
            return CrossSourceDecision(
                candidate=candidate,
                status=CrossValidationStatus.REJECTED,
                rejection_reason=CrossRejectionReason.CATEGORY_MISMATCH,
                reciprocal_evidence_url=None,
                validation_details=MappingProxyType(details),
            )
        details["category_check"] = "matched"
    else:
        details["category_check"] = "skipped_unknown"

    price_status = CrossValidationStatus.UNKNOWN
    prices = known_prices.get(candidate.our_oem_norm, ())
    if not prices:
        details["price_check"] = "skipped_no_known_prices"
    elif candidate.source_price is None or candidate.source_price <= 0:
        details["price_check"] = "skipped_missing_source_price"
        price_status = CrossValidationStatus.REVIEW
    else:
        market_median = _median(prices)
        ratio = candidate.source_price / market_median
        details.update(
            {
                "price_check": "evaluated",
                "market_median": str(market_median),
                "source_price": str(candidate.source_price),
                "price_ratio": str(ratio.quantize(Decimal("0.0001"))),
            }
        )
        if (
            ratio < config.validation.reject_price_ratio_min
            or ratio > config.validation.reject_price_ratio_max
        ):
            return CrossSourceDecision(
                candidate=candidate,
                status=CrossValidationStatus.REJECTED,
                rejection_reason=CrossRejectionReason.PRICE_OUT_OF_BAND,
                reciprocal_evidence_url=None,
                validation_details=MappingProxyType(details),
            )
        if (
            ratio < config.validation.review_price_ratio_min
            or ratio > config.validation.review_price_ratio_max
        ):
            price_status = CrossValidationStatus.REVIEW
            details["price_check"] = "review_band"
        else:
            details["price_check"] = "passed"

    reciprocal_url = _reciprocal_evidence_url(candidate, listings, config)
    details["reciprocal"] = bool(reciprocal_url)
    details["explicit_marker"] = candidate.extraction_method != "UNMARKED"
    if price_status is CrossValidationStatus.REVIEW:
        status = CrossValidationStatus.REVIEW
    elif reciprocal_url or candidate.extraction_method != "UNMARKED":
        status = CrossValidationStatus.CONFIRMED
    else:
        status = CrossValidationStatus.REVIEW
    return CrossSourceDecision(
        candidate=candidate,
        status=status,
        rejection_reason=None,
        reciprocal_evidence_url=reciprocal_url,
        validation_details=MappingProxyType(details),
    )


def _deduplicate_pair_decisions(
    source_decisions: Sequence[CrossSourceDecision],
    config: CrossConfig,
) -> tuple[CrossPairDecision, ...]:
    grouped: defaultdict[tuple[str, str], list[CrossSourceDecision]] = defaultdict(list)
    for decision in source_decisions:
        grouped[
            (
                decision.candidate.our_oem_norm,
                decision.candidate.extracted_oem_norm,
            )
        ].append(decision)
    status_rank = {
        status: index
        for index, status in enumerate(config.validation.status_precedence)
    }
    pair_decisions: list[CrossPairDecision] = []
    for pair in sorted(grouped):
        decisions = sorted(
            grouped[pair],
            key=lambda item: (
                status_rank[item.status],
                _method_rank(item.candidate.extraction_method, config.extraction),
                not bool(item.reciprocal_evidence_url),
                item.candidate.source_listing_url,
                item.candidate.listing_id,
            ),
        )
        best = decisions[0]
        evidence = tuple(
            MappingProxyType(
                {
                    "listing_id": item.candidate.listing_id,
                    "source_listing_url": item.candidate.source_listing_url,
                    "source_seller": item.candidate.source_seller,
                    "source_seller_id": item.candidate.source_seller_id,
                    "raw_context": item.candidate.raw_context,
                    "extraction_method": item.candidate.extraction_method,
                    "status": item.status.value,
                    "rejection_reason": (
                        item.rejection_reason.value
                        if item.rejection_reason is not None
                        else None
                    ),
                    "reciprocal_evidence_url": item.reciprocal_evidence_url,
                    "validation_details": dict(item.validation_details),
                }
            )
            for item in sorted(
                decisions,
                key=lambda item: (
                    item.candidate.source_listing_url,
                    item.candidate.listing_id,
                    item.candidate.raw_context,
                ),
            )
        )
        reciprocal_urls = sorted(
            {
                item.reciprocal_evidence_url
                for item in decisions
                if item.reciprocal_evidence_url
            }
        )
        source_sellers = sorted(
            {
                item.candidate.source_seller.strip()
                for item in decisions
                if item.candidate.source_seller.strip()
            },
            key=str.casefold,
        )
        source_seller_ids = sorted(
            {
                item.candidate.source_seller_id.strip()
                for item in decisions
                if item.candidate.source_seller_id
                and item.candidate.source_seller_id.strip()
            }
        )
        source_seller_identities = {
            (
                f"id:{item.candidate.source_seller_id.strip()}"
                if item.candidate.source_seller_id
                and item.candidate.source_seller_id.strip()
                else f"name:{item.candidate.source_seller.strip().casefold()}"
            )
            for item in decisions
            if (
                item.candidate.source_seller_id
                and item.candidate.source_seller_id.strip()
            )
            or item.candidate.source_seller.strip()
        }
        pair_decisions.append(
            CrossPairDecision(
                our_oem_norm=pair[0],
                extracted_oem_norm=pair[1],
                source_listing_url=best.candidate.source_listing_url,
                source_seller=best.candidate.source_seller,
                raw_context=best.candidate.raw_context,
                extraction_method=best.candidate.extraction_method,
                validation_status=best.status,
                rejection_reason=best.rejection_reason,
                reciprocal_evidence_url=(
                    reciprocal_urls[0] if reciprocal_urls else None
                ),
                source_evidence=evidence,
                validation_details=MappingProxyType(
                    {
                        "source_count": len(evidence),
                        "independent_seller_count": len(source_seller_identities),
                        "source_seller_ids": source_seller_ids,
                        "source_sellers": source_sellers,
                        "source_statuses": [item.status.value for item in decisions],
                        "selected_source": best.candidate.listing_id,
                    }
                ),
            )
        )
    return tuple(pair_decisions)


def _candidate_rejection_reason(
    *,
    raw_token: str,
    normalized_token: str,
    own_oem: str,
    description: str,
    token_start: int,
    token_end: int,
    config: CrossExtractionConfig,
) -> CrossRejectionReason | None:
    compact_raw = raw_token.strip()
    if re.fullmatch(
        r"\d+(?:[.,]\d+)?(?:\s*[*xх×]\s*\d+(?:[.,]\d+)?){1,2}",
        compact_raw,
        flags=re.IGNORECASE,
    ):
        return CrossRejectionReason.DIMENSION
    year_range = re.fullmatch(r"(\d{4})(?:\s*[-–—]\s*(\d{4}))?", compact_raw)
    if year_range and all(
        config.year_min <= int(value) <= config.year_max
        for value in year_range.groups()
        if value is not None
    ):
        return CrossRejectionReason.YEAR_OR_RANGE
    if (
        normalized_token.isdigit()
        and len(normalized_token) >= config.phone_min_digits
        and any(normalized_token.startswith(prefix) for prefix in config.phone_prefixes)
    ):
        return CrossRejectionReason.PHONE
    if len(normalized_token) == config.vin_length and re.fullmatch(
        r"[A-HJ-NPR-Z0-9]+", normalized_token
    ):
        return CrossRejectionReason.VIN
    if normalized_token.isdigit() and len(normalized_token) in config.gtin_lengths:
        return CrossRejectionReason.GTIN
    engine_context = _context(
        description, token_start, token_end, config.engine_context_chars
    ).casefold()
    if re.fullmatch(r"[12][.,]\d", compact_raw) and any(
        marker.casefold() in engine_context for marker in config.engine_markers
    ):
        return CrossRejectionReason.ENGINE_DISPLACEMENT
    if normalized_token == own_oem:
        return CrossRejectionReason.OWN_OEM
    currency_context = _context(
        description, token_start, token_end, config.currency_context_chars
    ).casefold()
    if re.fullmatch(r"\d+(?:[.,]\d{1,2})?", compact_raw) and any(
        marker.casefold() in currency_context for marker in config.currency_markers
    ):
        return CrossRejectionReason.PRICE
    if not normalized_token or re.search(r"[^\x00-\x7F]", compact_raw):
        return CrossRejectionReason.NON_ASCII
    if normalized_token.isdigit():
        if (
            not config.numeric_min_length
            <= len(normalized_token)
            <= config.numeric_max_length
        ):
            return CrossRejectionReason.OUTSIDE_LENGTH
        return None
    if not (
        config.alphanumeric_min_length
        <= len(normalized_token)
        <= config.alphanumeric_max_length
    ):
        return CrossRejectionReason.OUTSIDE_LENGTH
    if not (
        any(character.isalpha() for character in normalized_token)
        and any(character.isdigit() for character in normalized_token)
    ):
        return CrossRejectionReason.MISSING_ALPHA_OR_DIGIT
    return None


def _token_spans(
    description: str, config: CrossExtractionConfig
) -> Iterable[tuple[int, int, str]]:
    character_delimiters = "".join(config.token_delimiters)
    marker_phrases = sorted(
        {phrase for phrases in config.marker_delimiters.values() for phrase in phrases},
        key=lambda value: (-len(value), value.casefold()),
    )
    marker_pattern = "|".join(re.escape(value) for value in marker_phrases)
    parts = [f"[{re.escape(character_delimiters)}]+"]
    if marker_pattern:
        parts.append(rf"(?i:\b(?:{marker_pattern})\b)")
    delimiter = re.compile("|".join(parts), re.UNICODE)
    position = 0
    for match in delimiter.finditer(description):
        yield from _trimmed_span(description, position, match.start(), config)
        position = match.end()
    yield from _trimmed_span(description, position, len(description), config)


def _trimmed_span(
    description: str,
    start: int,
    end: int,
    config: CrossExtractionConfig,
) -> Iterable[tuple[int, int, str]]:
    while start < end and description[start] in config.edge_strip_chars:
        start += 1
    while end > start and description[end - 1] in config.edge_strip_chars:
        end -= 1
    if start >= end or end - start > config.candidate_raw_max_chars:
        return
    yield start, end, description[start:end]


def _marker_matches(
    description: str, config: CrossExtractionConfig
) -> tuple[tuple[int, int, str], ...]:
    matches: list[tuple[int, int, str]] = []
    for method, phrases in config.marker_delimiters.items():
        for phrase in phrases:
            for match in re.finditer(
                rf"(?i:\b{re.escape(phrase)}\b)", description, re.UNICODE
            ):
                matches.append((match.start(), match.end(), method))
    return tuple(sorted(matches, key=lambda value: (value[0], value[1], value[2])))


def _extraction_method(
    marker_matches: Sequence[tuple[int, int, str]],
    *,
    token_start: int,
    description: str,
    config: CrossExtractionConfig,
) -> str:
    eligible = [
        match
        for match in marker_matches
        if match[1] <= token_start
        and token_start - match[1] <= config.explicit_marker_window_chars
        and not any(
            character.isalnum() for character in description[match[1] : token_start]
        )
    ]
    if not eligible:
        return "UNMARKED"
    return max(eligible, key=lambda value: (value[1], -value[0], value[2]))[2]


def _reciprocal_evidence_url(
    candidate: CrossCandidateEvidence,
    listings: Sequence[CrossListing],
    config: CrossConfig,
) -> str | None:
    urls: list[str] = []
    for listing in listings:
        if listing.listing_id == candidate.listing_id or not listing.description:
            continue
        normalized_description = normalize_cross_oem(listing.description)
        if _identifiers_are_near(
            normalized_description,
            candidate.our_oem_norm,
            candidate.extracted_oem_norm,
            config.validation.reciprocal_window_chars,
        ):
            urls.append(listing.source_listing_url)
    return sorted(url for url in urls if url)[0] if urls else None


def _identifiers_are_near(
    normalized_description: str,
    left: str,
    right: str,
    max_distance: int,
) -> bool:
    return any(
        abs(left_position - right_position) <= max_distance
        for left_position in _all_positions(normalized_description, left)
        for right_position in _all_positions(normalized_description, right)
    )


def _all_positions(value: str, needle: str) -> tuple[int, ...]:
    if not needle:
        return ()
    positions: list[int] = []
    start = 0
    while True:
        position = value.find(needle, start)
        if position < 0:
            return tuple(positions)
        positions.append(position)
        start = position + 1


def _known_prices_by_oe(
    listings: Sequence[CrossListing],
) -> Mapping[str, tuple[Decimal, ...]]:
    grouped: defaultdict[str, list[Decimal]] = defaultdict(list)
    for listing in listings:
        our_oem = normalize_cross_oem(listing.our_oem_norm)
        if listing.price is not None and listing.price > 0:
            grouped[our_oem].append(listing.price)
    return MappingProxyType(
        {key: tuple(sorted(values)) for key, values in sorted(grouped.items())}
    )


def _median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("median requires at least one value")
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _context(value: str, start: int, end: int, each_side: int) -> str:
    return value[max(0, start - each_side) : min(len(value), end + each_side)]


def _method_rank(method: str, config: CrossExtractionConfig) -> int:
    try:
        return config.extraction_method_precedence.index(method)
    except ValueError:
        return len(config.extraction_method_precedence)


def _category(value: str | None) -> str | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    return " ".join(normalized.casefold().split())


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CrossConfigError(f"{field_name} must be a mapping")
    return value


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CrossConfigError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CrossConfigError(f"{field_name} must be a positive integer")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CrossConfigError(f"{field_name} must be a non-empty list")
    result = tuple(_text(item, f"{field_name}[]") for item in value)
    if len(set(result)) != len(result):
        raise CrossConfigError(f"{field_name} must not contain duplicates")
    return result


def _raw_string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CrossConfigError(f"{field_name} must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in value):
        raise CrossConfigError(f"{field_name}[] must be a non-empty string")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise CrossConfigError(f"{field_name} must not contain duplicates")
    return result


def _int_tuple(value: Any, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise CrossConfigError(f"{field_name} must be a non-empty list")
    result = tuple(_positive_int(item, f"{field_name}[]") for item in value)
    if len(set(result)) != len(result):
        raise CrossConfigError(f"{field_name} must not contain duplicates")
    return result


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CrossConfigError(f"{field_name} must be numeric") from exc
    if not result.is_finite():
        raise CrossConfigError(f"{field_name} must be finite")
    return result


def _unit_decimal(value: Any, field_name: str) -> Decimal:
    result = _decimal(value, field_name)
    if not Decimal("0") < result < Decimal("1"):
        raise CrossConfigError(f"{field_name} must be between 0 and 1")
    return result
