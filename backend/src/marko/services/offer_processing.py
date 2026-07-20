"""Total candidate validation and versioned source-confidence assessment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
from typing import Any
from urllib.parse import urlsplit


SOURCE_CONFIDENCE_METHOD_VERSION = "source-confidence-v1"
_ZERO = Decimal("0")
_ONE = Decimal("1")
_WEIGHTS = {
    "listing_identity": Decimal("0.20"),
    "seller_identity": Decimal("0.20"),
    "price_currency": Decimal("0.20"),
    "availability": Decimal("0.10"),
    "url": Decimal("0.10"),
    "structured_completeness": Decimal("0.20"),
}


class EvidenceAccountingError(ValueError):
    """The terminal offer partition does not conserve retrieved elements."""


class OfferOutcomeCode(StrEnum):
    OBSERVATION_PERSISTED = "OBSERVATION_PERSISTED"
    REJECTED_NOT_MAPPING = "REJECTED_NOT_MAPPING"
    REJECTED_INVALID_PRICE = "REJECTED_INVALID_PRICE"
    REJECTED_INVALID_MATCH_SCORE = "REJECTED_INVALID_MATCH_SCORE"
    REJECTED_MISSING_LISTING_IDENTITY = "REJECTED_MISSING_LISTING_IDENTITY"
    REJECTED_SCHEMA_MISMATCH = "REJECTED_SCHEMA_MISMATCH"
    REJECTED_SERIALIZATION = "REJECTED_SERIALIZATION"
    FAILED_INTERNAL_PROCESSING = "FAILED_INTERNAL_PROCESSING"


@dataclass(frozen=True, slots=True)
class RejectedOffer:
    raw_offer_index: int
    outcome_code: OfferOutcomeCode
    reason_codes: tuple[str, ...]
    safe_sample: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AcceptedCandidate:
    raw_offer_index: int
    retrieval_kind: str
    retrieval_score: Decimal | None
    product: Mapping[str, Any]
    upstream_comparison_evidence: Mapping[str, Any] | None
    price: Decimal
    source_listing_id: str
    listing_identity_quality: Decimal


@dataclass(frozen=True, slots=True)
class SourceConfidenceAssessment:
    value: Decimal
    method_version: str
    factors: Mapping[str, str | bool]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OfferAccounting:
    retrieved: int
    observations_persisted: int
    rejected: int
    internal_failures: int

    def validate(self) -> None:
        values = (
            self.retrieved,
            self.observations_persisted,
            self.rejected,
            self.internal_failures,
        )
        if any(value < 0 for value in values):
            raise EvidenceAccountingError(
                "offer accounting counters cannot be negative"
            )
        if self.retrieved != sum(values[1:]):
            raise EvidenceAccountingError("EVIDENCE_ACCOUNTING_ERROR: R != O + J + F")

    def as_dict(self) -> dict[str, int]:
        self.validate()
        return {
            "retrieved": self.retrieved,
            "observations_persisted": self.observations_persisted,
            "rejected": self.rejected,
            "internal_failures": self.internal_failures,
        }


def process_offer_candidate(
    raw_offer: Any,
    *,
    fallback_index: int,
) -> AcceptedCandidate | RejectedOffer:
    """Return exactly one typed validation result for one retrieved element."""

    if not isinstance(raw_offer, Mapping):
        return _rejected(
            fallback_index,
            OfferOutcomeCode.REJECTED_NOT_MAPPING,
            "OFFER_NOT_MAPPING",
            raw_offer,
        )
    is_envelope = "product" in raw_offer or "raw_offer_index" in raw_offer
    raw_index = raw_offer.get("raw_offer_index", fallback_index)
    if not isinstance(raw_index, int) or isinstance(raw_index, bool) or raw_index < 0:
        return _rejected(
            fallback_index,
            OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
            "RAW_OFFER_INDEX_INVALID",
            raw_offer,
        )
    if raw_index != fallback_index:
        return _rejected(
            fallback_index,
            OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
            "RAW_OFFER_INDEX_NOT_CANONICAL",
            raw_offer,
        )
    product: Any = raw_offer.get("product") if is_envelope else raw_offer
    if not isinstance(product, Mapping):
        return _rejected(
            raw_index,
            OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
            "CANDIDATE_PRODUCT_NOT_MAPPING",
            raw_offer,
        )
    raw_price = product.get("price")
    try:
        price = Decimal(str(raw_price)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return _rejected(
            raw_index,
            OfferOutcomeCode.REJECTED_INVALID_PRICE,
            "PRICE_NOT_DECIMAL",
            product,
        )
    if not price.is_finite() or price <= 0:
        return _rejected(
            raw_index,
            OfferOutcomeCode.REJECTED_INVALID_PRICE,
            "PRICE_NOT_FINITE_POSITIVE",
            product,
        )

    retrieval_raw = (
        raw_offer.get("retrieval_score")
        if is_envelope
        else raw_offer.get("match_score")
    )
    retrieval_score: Decimal | None = None
    if retrieval_raw is not None:
        try:
            retrieval_score = Decimal(str(retrieval_raw)).quantize(Decimal("0.0001"))
        except (InvalidOperation, TypeError, ValueError):
            return _rejected(
                raw_index,
                OfferOutcomeCode.REJECTED_INVALID_MATCH_SCORE,
                "RETRIEVAL_SCORE_NOT_DECIMAL",
                product,
            )
        if (
            not retrieval_score.is_finite()
            or retrieval_score < 0
            or retrieval_score > 1
        ):
            return _rejected(
                raw_index,
                OfferOutcomeCode.REJECTED_INVALID_MATCH_SCORE,
                "RETRIEVAL_SCORE_OUT_OF_RANGE",
                product,
            )

    product_id = product.get("product_id", product.get("id"))
    url = str(product.get("url") or "").strip()
    if product_id is not None and str(product_id).strip():
        source_listing_id = str(product_id).strip()[:255]
        listing_quality = Decimal("1")
    elif _valid_http_url(url):
        source_listing_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
        listing_quality = Decimal("0.75")
    else:
        return _rejected(
            raw_index,
            OfferOutcomeCode.REJECTED_MISSING_LISTING_IDENTITY,
            "LISTING_IDENTITY_MISSING",
            product,
        )

    upstream = (
        raw_offer.get("upstream_comparison_evidence")
        if is_envelope
        else raw_offer.get("comparison_evidence")
    )
    if upstream is not None and not isinstance(upstream, Mapping):
        return _rejected(
            raw_index,
            OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
            "COMPARISON_EVIDENCE_NOT_MAPPING",
            product,
        )
    try:
        json.dumps(
            raw_offer,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return _rejected(
            raw_index,
            OfferOutcomeCode.REJECTED_SERIALIZATION,
            "OFFER_NOT_DETERMINISTIC_JSON",
            raw_offer,
        )
    return AcceptedCandidate(
        raw_offer_index=raw_index,
        retrieval_kind=str(
            raw_offer.get("retrieval_kind")
            or raw_offer.get("match_kind")
            or "legacy_unknown"
        )[:80],
        retrieval_score=retrieval_score,
        product=dict(product),
        upstream_comparison_evidence=(dict(upstream) if upstream is not None else None),
        price=price,
        source_listing_id=source_listing_id,
        listing_identity_quality=listing_quality,
    )


def assess_source_confidence(
    *,
    raw_capture_verified: bool,
    parser_contract_verified: bool,
    listing_identity_quality: Decimal,
    seller_identity_quality: Decimal,
    price_currency_quality: Decimal,
    availability_quality: Decimal,
    url_quality: Decimal,
    structured_completeness: Decimal,
) -> SourceConfidenceAssessment:
    values = {
        "listing_identity": _bounded(listing_identity_quality),
        "seller_identity": _bounded(seller_identity_quality),
        "price_currency": _bounded(price_currency_quality),
        "availability": _bounded(availability_quality),
        "url": _bounded(url_quality),
        "structured_completeness": _bounded(structured_completeness),
    }
    reasons: list[str] = []
    if not raw_capture_verified:
        reasons.append("SOURCE_RAW_CAPTURE_UNVERIFIED")
    if not parser_contract_verified:
        reasons.append("SOURCE_PARSER_CONTRACT_UNRECOGNIZED")
    for name, value in values.items():
        if value < _ONE:
            reasons.append(f"SOURCE_{name.upper()}_INCOMPLETE")
    confidence = (
        sum((_WEIGHTS[name] * value for name, value in values.items()), _ZERO)
        if raw_capture_verified and parser_contract_verified
        else _ZERO
    )
    confidence = confidence.quantize(Decimal("0.0001"))
    return SourceConfidenceAssessment(
        value=confidence,
        method_version=SOURCE_CONFIDENCE_METHOD_VERSION,
        factors={
            "raw_capture_verified": raw_capture_verified,
            "parser_contract_verified": parser_contract_verified,
            **{name: format(value, "f") for name, value in values.items()},
        },
        reason_codes=tuple(reasons),
    )


def assess_candidate_source(
    candidate: AcceptedCandidate,
    *,
    raw_capture_verified: bool,
    parser_contract_verified: bool,
) -> SourceConfidenceAssessment:
    product = candidate.product
    seller_id = str(product.get("seller_id") or "").strip()
    seller_name = str(product.get("seller_name") or "").strip()
    seller_quality = _ONE if seller_id else Decimal("0.35") if seller_name else _ZERO
    currency = str(product.get("currency") or "").strip()
    price_currency_quality = (
        _ONE
        if currency.casefold() in {"uah", "грн", "₴", "гривня", "гривень"}
        else Decimal("0.60")
        if currency
        else Decimal("0.30")
    )
    availability_quality = (
        _ONE
        if isinstance(product.get("is_available"), bool)
        else Decimal("0.60")
        if str(product.get("presence") or "").strip()
        else _ZERO
    )
    url = str(product.get("url") or "").strip()
    url_quality = (
        _ONE
        if _valid_prom_url(url)
        else Decimal("0.40")
        if _valid_http_url(url)
        else _ZERO
    )
    completeness_fields = (
        bool(str(product.get("name") or "").strip()),
        candidate.price > 0,
        bool(currency),
        bool(seller_id or seller_name),
        isinstance(product.get("is_available"), bool)
        or bool(str(product.get("presence") or "").strip()),
        bool(url),
    )
    completeness = Decimal(sum(completeness_fields)) / Decimal(len(completeness_fields))
    return assess_source_confidence(
        raw_capture_verified=raw_capture_verified,
        parser_contract_verified=parser_contract_verified,
        listing_identity_quality=candidate.listing_identity_quality,
        seller_identity_quality=seller_quality,
        price_currency_quality=price_currency_quality,
        availability_quality=availability_quality,
        url_quality=url_quality,
        structured_completeness=completeness,
    )


def safe_offer_sample(raw_offer: Any, *, raw_offer_index: int) -> dict[str, Any]:
    if not isinstance(raw_offer, Mapping):
        return {
            "raw_offer_index": raw_offer_index,
            "value_type": type(raw_offer).__name__,
        }
    product = raw_offer.get("product")
    value = product if isinstance(product, Mapping) else raw_offer
    return {
        "raw_offer_index": raw_offer_index,
        "keys": sorted(str(key)[:80] for key in value.keys())[:40],
        "has_product_id": bool(value.get("product_id") or value.get("id")),
        "has_url": bool(value.get("url")),
        "has_seller_id": bool(value.get("seller_id")),
        "has_price": value.get("price") is not None,
        "has_currency": bool(value.get("currency")),
    }


def _rejected(
    index: int,
    code: OfferOutcomeCode,
    reason: str,
    raw_offer: Any,
) -> RejectedOffer:
    return RejectedOffer(
        raw_offer_index=index,
        outcome_code=code,
        reason_codes=(reason,),
        safe_sample=safe_offer_sample(raw_offer, raw_offer_index=index),
    )


def _bounded(value: Decimal) -> Decimal:
    decimal = Decimal(str(value))
    if not decimal.is_finite() or decimal < _ZERO or decimal > _ONE:
        raise ValueError("source-confidence factor must be finite and in [0, 1]")
    return decimal


def _valid_http_url(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)


def _valid_prom_url(value: str) -> bool:
    if not _valid_http_url(value):
        return False
    hostname = (urlsplit(value).hostname or "").casefold()
    return hostname in {"prom.ua", "www.prom.ua"} or hostname.endswith(".prom.ua")


__all__ = [
    "AcceptedCandidate",
    "EvidenceAccountingError",
    "OfferAccounting",
    "OfferOutcomeCode",
    "RejectedOffer",
    "SOURCE_CONFIDENCE_METHOD_VERSION",
    "SourceConfidenceAssessment",
    "assess_candidate_source",
    "assess_source_confidence",
    "process_offer_candidate",
    "safe_offer_sample",
]
