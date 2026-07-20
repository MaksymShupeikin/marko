"""Stable black-box contract around the existing Prom extraction component.

Parser and matching internals remain unchanged.  The gateway exposes only an
opt-in fail-fast mode for orchestrated calls.  This module owns input
validation, deterministic output serialization, error taxonomy, and
per-attempt resource measurement so orchestration code does not depend on
parser internals.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import re
import resource
import sys
import time
from typing import Any
import unicodedata
from urllib.parse import urlsplit, urlunsplit

import requests

from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import (
    ParseError,
    ParserSchemaChanged,
    RequestFailed,
    UnsafeResponse,
)
from marko.parsers.prom.gateway import PromGateway
from marko.services.collection_guard import CollectionCircuitOpen
from marko.services.matching import PriceComparison
from marko.services.parser_models import Product
from marko.services.scrape_journal import EvidenceIntegrityError
from marko.services.scrape_runtime import ReplayIntegrityError
from marko.services.source_access import SourceAccessBlocked


PROM_ADAPTER_VERSION = "prom-parser-adapter-v3"
PROM_OUTPUT_SCHEMA_VERSION = "prom-market-acquisition-v2"
LEGACY_PROM_OUTPUT_SCHEMA_VERSION = "prom-price-comparison-v1"

_PRODUCT_PATH_RE = re.compile(
    r"^/(?:(?P<lang>[a-z]{2})/)?p(?P<product_id>\d+)-(?P<slug>[\w-]+)\.html$",
    re.IGNORECASE,
)
_HTTP_STATUS_RE = re.compile(r"\bHTTP\s+(?P<status>\d{3})\b", re.IGNORECASE)


class ScraperErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    TIMEOUT = "timeout"
    NETWORK = "network"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_3XX = "upstream_3xx"
    UPSTREAM_5XX = "upstream_5xx"
    UPSTREAM_4XX = "upstream_4xx"
    PARSE_CONTRACT = "parse_contract"
    PARSER_SCHEMA_CHANGED = "parser_schema_changed"
    SERIALIZATION = "serialization"
    CIRCUIT_OPEN = "circuit_open"
    TARGET_BUSY = "target_busy"
    SOURCE_ACCESS_BLOCKED = "source_access_blocked"
    RETRY_EXHAUSTED = "retry_exhausted"
    EVIDENCE_PERSISTENCE = "evidence_persistence"
    UNSAFE_RESPONSE = "unsafe_response"
    UNEXPECTED = "unexpected"


class ScraperBoundaryError(RuntimeError):
    """Typed failure crossing the frozen parser adapter boundary."""

    def __init__(
        self,
        code: ScraperErrorCode,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def canonicalize_prom_product_url(product_url: str | None) -> str:
    """Validate a Prom product URL and map seller hosts to the central host."""
    raw_url = (product_url or "").strip()
    if not raw_url:
        raise ScraperBoundaryError(
            ScraperErrorCode.INVALID_INPUT,
            "Product URL is required",
            retryable=False,
        )

    parsed = urlsplit(raw_url)
    hostname = (parsed.hostname or "").casefold()
    if parsed.username is not None or parsed.password is not None:
        raise ScraperBoundaryError(
            ScraperErrorCode.INVALID_INPUT,
            "Credentials embedded in a scraper URL are forbidden",
            retryable=False,
        )
    host_allowed = hostname in {"prom.ua", "www.prom.ua"} or hostname.endswith(
        ".prom.ua"
    )
    if parsed.scheme.casefold() not in {"http", "https"} or not host_allowed:
        raise ScraperBoundaryError(
            ScraperErrorCode.INVALID_INPUT,
            "Only absolute prom.ua product URLs are accepted",
            retryable=False,
        )
    match = _PRODUCT_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise ScraperBoundaryError(
            ScraperErrorCode.INVALID_INPUT,
            "URL does not match the Prom product-page contract",
            retryable=False,
        )

    lang = (match.group("lang") or "ua").casefold()
    product_id = match.group("product_id")
    slug = match.group("slug")
    return urlunsplit(
        ("https", "prom.ua", f"/{lang}/p{product_id}-{slug}.html", "", "")
    )


def normalize_prom_query(query: str | None) -> str:
    """Normalize a query without ever interpreting it as a URL."""

    value = unicodedata.normalize("NFKC", query or "")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ScraperBoundaryError(
            ScraperErrorCode.INVALID_INPUT,
            "Comparison query contains control characters",
            retryable=False,
        )
    normalized = " ".join(value.strip().upper().split())
    if not normalized:
        raise ScraperBoundaryError(
            ScraperErrorCode.INVALID_INPUT,
            "Comparison query is required",
            retryable=False,
        )
    if len(normalized) > 255:
        raise ScraperBoundaryError(
            ScraperErrorCode.INVALID_INPUT,
            "Comparison query exceeds 255 characters",
            retryable=False,
        )
    if "://" in normalized or normalized.casefold().startswith("invalid:"):
        raise ScraperBoundaryError(
            ScraperErrorCode.INVALID_INPUT,
            "Comparison query must not contain a URL or sentinel",
            retryable=False,
        )
    return normalized


@dataclass(frozen=True)
class ProductSeedInput:
    """Canonical extraction input.

    The operational idempotency key includes the Prom product identity and
    normalized query.  The query is part of the input because the existing
    gateway's comparison output depends on it.
    """

    product_url: str
    canonical_url: str
    product_key: str
    query: str
    adapter_version: str
    input_hash: str
    input_kind: str = field(default="product_seed", init=False)

    @classmethod
    def build(
        cls,
        product_url: str | None,
        query: str | None,
        *,
        adapter_version: str = PROM_ADAPTER_VERSION,
    ) -> ProductSeedInput:
        raw_url = (product_url or "").strip()
        normalized_query = normalize_prom_query(query)
        if not raw_url:
            raise ScraperBoundaryError(
                ScraperErrorCode.INVALID_INPUT,
                "Product URL is required",
                retryable=False,
            )
        canonical_url = canonicalize_prom_product_url(raw_url)
        canonical_path = urlsplit(canonical_url).path
        match = _PRODUCT_PATH_RE.fullmatch(canonical_path)
        assert match is not None
        product_id = match.group("product_id")
        product_key = f"prom:product:{product_id}"
        digest_source = json.dumps(
            {
                "adapter_version": adapter_version,
                "input_kind": "product_seed",
                "product_key": product_key,
                "query": normalized_query,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls(
            product_url=canonical_url,
            canonical_url=canonical_url,
            product_key=product_key,
            query=normalized_query,
            adapter_version=adapter_version,
            input_hash=hashlib.sha256(digest_source.encode()).hexdigest(),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "input_kind": self.input_kind,
            "product_url": self.product_url,
            "canonical_url": self.canonical_url,
            "product_key": self.product_key,
            "query": self.query,
            "adapter_version": self.adapter_version,
            "input_hash": self.input_hash,
        }


# Backward-compatible public name for the historical URL/product-seed input.
ScrapeInput = ProductSeedInput


@dataclass(frozen=True)
class QueryInput:
    """Canonical query-only acquisition input for catalog items without URLs."""

    query: str
    language: str
    query_key: str
    adapter_version: str
    input_hash: str
    input_kind: str = field(default="query", init=False)

    @classmethod
    def build(
        cls,
        query: str | None,
        *,
        language: str = "ua",
        adapter_version: str = PROM_ADAPTER_VERSION,
    ) -> QueryInput:
        normalized_query = normalize_prom_query(query)
        normalized_language = unicodedata.normalize("NFKC", language).strip().casefold()
        if not re.fullmatch(r"[a-z]{2}", normalized_language):
            raise ScraperBoundaryError(
                ScraperErrorCode.INVALID_INPUT,
                "Prom query language must be a two-letter code",
                retryable=False,
            )
        query_digest = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()
        query_key = f"prom:query:{normalized_language}:{query_digest}"
        digest_source = json.dumps(
            {
                "adapter_version": adapter_version,
                "input_kind": "query",
                "source": "prom_public",
                "language": normalized_language,
                "query": normalized_query,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls(
            query=normalized_query,
            language=normalized_language,
            query_key=query_key,
            adapter_version=adapter_version,
            input_hash=hashlib.sha256(digest_source.encode()).hexdigest(),
        )

    def as_dict(self) -> dict[str, str | None]:
        return {
            "input_kind": self.input_kind,
            "query": self.query,
            "language": self.language,
            "query_key": self.query_key,
            "canonical_url": None,
            "adapter_version": self.adapter_version,
            "input_hash": self.input_hash,
        }


AcquisitionInput = ProductSeedInput | QueryInput


def build_acquisition_input(
    input_kind: str,
    input_value: str | None,
    *,
    query: str | None = None,
    language: str = "ua",
    adapter_version: str = PROM_ADAPTER_VERSION,
) -> AcquisitionInput:
    if input_kind == "query":
        return QueryInput.build(
            input_value,
            language=language,
            adapter_version=adapter_version,
        )
    if input_kind in {"url", "product_seed"}:
        return ProductSeedInput.build(
            input_value,
            query,
            adapter_version=adapter_version,
        )
    raise ScraperBoundaryError(
        ScraperErrorCode.INVALID_INPUT,
        f"Unsupported acquisition input kind: {input_kind}",
        retryable=False,
    )


def fallback_input_hash(
    product_url: str | None,
    query: str | None,
    *,
    input_kind: str = "product_seed",
    adapter_version: str = PROM_ADAPTER_VERSION,
) -> str:
    """Stable key for invalid inputs so repeated delivery is still idempotent."""

    payload = {
        "adapter_version": adapter_version,
        "input_kind": input_kind,
        "product_url": (product_url or "").strip(),
        "query": " ".join((query or "").strip().upper().split()),
        "invalid": True,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ScrapeOutput:
    """Deterministic, serializable output of the frozen parser adapter."""

    payload: dict[str, Any]
    content_sha256: str
    raw_size_bytes: int
    structured_size_bytes: int
    metadata_size_bytes: int
    structured_completeness: float

    @classmethod
    def from_comparison(
        cls,
        scrape_input: ProductSeedInput,
        comparison: PriceComparison,
    ) -> ScrapeOutput:
        try:
            comparison_payload = comparison.as_dict()
        except Exception as exc:
            raise ScraperBoundaryError(
                ScraperErrorCode.SERIALIZATION,
                f"Comparison cannot be serialized: {exc}",
                retryable=False,
            ) from exc
        # ``PriceComparison.as_dict`` intentionally remains unchanged because
        # it is also a public presentation contract.  The adapter enriches its
        # frozen output boundary with the identity and availability fields
        # required to replay Metis evidence persistence without calling the
        # scraper again.
        offers = comparison_payload.get("offers")
        if not isinstance(offers, list) or len(offers) != len(comparison.offers):
            raise ScraperBoundaryError(
                ScraperErrorCode.SERIALIZATION,
                "Comparison offers do not match the serialized output",
                retryable=False,
            )
        records: list[dict[str, Any]] = []
        for raw_offer_index, (serialized, offer) in enumerate(
            zip(offers, comparison.offers, strict=True)
        ):
            if not isinstance(serialized, dict):
                raise ScraperBoundaryError(
                    ScraperErrorCode.SERIALIZATION,
                    "Serialized comparison offer must be an object",
                    retryable=False,
                )
            serialized["product_id"] = offer.product.id
            serialized["is_available"] = offer.product.is_available
            product = {
                key: value
                for key, value in serialized.items()
                if key
                not in {
                    "automatic_eligible",
                    "comparison_evidence",
                    "match_kind",
                    "match_score",
                }
            }
            records.append(
                {
                    "raw_offer_index": raw_offer_index,
                    "retrieval_kind": "product_seed_comparison",
                    "retrieval_score": serialized.get("match_score"),
                    "product": product,
                    "upstream_comparison_evidence": serialized.get(
                        "comparison_evidence"
                    ),
                }
            )

        payload = {
            "schema_version": PROM_OUTPUT_SCHEMA_VERSION,
            "adapter_version": scrape_input.adapter_version,
            "input": scrape_input.as_dict(),
            "output": {
                "acquisition_outcome": (
                    "RESULTS" if records else "EMPTY_SEARCH_RESULT"
                ),
                "candidates_scanned": comparison.candidates_scanned,
                "records": records,
                "comparison_summary": {
                    "seed": comparison_payload.get("seed"),
                    "query": comparison_payload.get("query"),
                    "stats": comparison_payload.get("stats"),
                },
            },
        }
        return cls.from_payload(payload)

    @classmethod
    def from_search(
        cls,
        scrape_input: QueryInput,
        products: list[Product],
    ) -> ScrapeOutput:
        records = [
            {
                "raw_offer_index": index,
                "retrieval_kind": "search_query",
                "retrieval_score": None,
                "product": product.as_dict(),
                "upstream_comparison_evidence": None,
            }
            for index, product in enumerate(products)
        ]
        return cls.from_payload(
            {
                "schema_version": PROM_OUTPUT_SCHEMA_VERSION,
                "adapter_version": scrape_input.adapter_version,
                "input": scrape_input.as_dict(),
                "output": {
                    "acquisition_outcome": (
                        "RESULTS" if records else "EMPTY_SEARCH_RESULT"
                    ),
                    "candidates_scanned": len(records),
                    "records": records,
                },
            }
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ScrapeOutput:
        schema_version = payload.get("schema_version")
        if schema_version not in {
            PROM_OUTPUT_SCHEMA_VERSION,
            LEGACY_PROM_OUTPUT_SCHEMA_VERSION,
        }:
            raise ScraperBoundaryError(
                ScraperErrorCode.SERIALIZATION,
                "Unsupported scraper output schema version",
                retryable=False,
            )
        input_payload = payload.get("input")
        output_payload = payload.get("output")
        if not isinstance(input_payload, Mapping) or not isinstance(
            output_payload, Mapping
        ):
            raise ScraperBoundaryError(
                ScraperErrorCode.SERIALIZATION,
                "Scraper output must contain input and output mappings",
                retryable=False,
            )
        if schema_version == PROM_OUTPUT_SCHEMA_VERSION:
            if input_payload.get("input_kind") not in {"query", "product_seed"}:
                raise ScraperBoundaryError(
                    ScraperErrorCode.SERIALIZATION,
                    "Scraper output input_kind is invalid",
                    retryable=False,
                )
            if (
                not isinstance(input_payload.get("query"), str)
                or not str(input_payload.get("query")).strip()
            ):
                raise ScraperBoundaryError(
                    ScraperErrorCode.SERIALIZATION,
                    "Scraper output query is missing",
                    retryable=False,
                )
            input_hash = str(input_payload.get("input_hash") or "").casefold()
            if not re.fullmatch(r"[0-9a-f]{64}", input_hash):
                raise ScraperBoundaryError(
                    ScraperErrorCode.SERIALIZATION,
                    "Scraper output input_hash is invalid",
                    retryable=False,
                )
            records = output_payload.get("records")
            if not isinstance(records, list):
                raise ScraperBoundaryError(
                    ScraperErrorCode.SERIALIZATION,
                    "Scraper output records must be a list",
                    retryable=False,
                )
            acquisition_outcome = output_payload.get("acquisition_outcome")
            if acquisition_outcome not in {"RESULTS", "EMPTY_SEARCH_RESULT"}:
                raise ScraperBoundaryError(
                    ScraperErrorCode.SERIALIZATION,
                    "Scraper output acquisition_outcome is invalid",
                    retryable=False,
                )
            if (acquisition_outcome == "RESULTS") != bool(records):
                raise ScraperBoundaryError(
                    ScraperErrorCode.SERIALIZATION,
                    "Scraper output outcome and records are inconsistent",
                    retryable=False,
                )
            candidates_scanned = output_payload.get("candidates_scanned")
            if (
                not isinstance(candidates_scanned, int)
                or isinstance(candidates_scanned, bool)
                or candidates_scanned < len(records)
            ):
                raise ScraperBoundaryError(
                    ScraperErrorCode.SERIALIZATION,
                    "Scraper output candidates_scanned is invalid",
                    retryable=False,
                )
        else:
            records = output_payload.get("offers")
            if not isinstance(records, list):
                raise ScraperBoundaryError(
                    ScraperErrorCode.SERIALIZATION,
                    "Legacy scraper output offers must be a list",
                    retryable=False,
                )
        try:
            canonical = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
            structured = json.dumps(
                output_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
            metadata = json.dumps(
                {
                    "schema_version": payload.get("schema_version"),
                    "adapter_version": payload.get("adapter_version"),
                    "input": input_payload,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ScraperBoundaryError(
                ScraperErrorCode.SERIALIZATION,
                f"Scraper output is not deterministic JSON: {exc}",
                retryable=False,
            ) from exc
        return cls(
            payload=dict(payload),
            content_sha256=hashlib.sha256(canonical).hexdigest(),
            raw_size_bytes=len(canonical),
            structured_size_bytes=len(structured),
            metadata_size_bytes=len(metadata),
            structured_completeness=_structured_completeness(
                records,
                schema_version=str(schema_version),
            ),
        )

    @property
    def comparison_payload(self) -> Mapping[str, Any]:
        value = self.payload["output"]
        if not isinstance(value, Mapping):
            raise ScraperBoundaryError(
                ScraperErrorCode.SERIALIZATION,
                "Stored comparison payload is not a mapping",
                retryable=False,
            )
        return value

    @property
    def candidate_records(self) -> list[Any]:
        """Return v2 candidate envelopes, adapting retained v1 payloads explicitly."""

        output = self.comparison_payload
        if self.payload.get("schema_version") == PROM_OUTPUT_SCHEMA_VERSION:
            records = output.get("records")
            assert isinstance(records, list)
            # Preserve every raw array element. Validation owns the terminal
            # partition; filtering here would violate R = O + J + F.
            return list(records)
        offers = output.get("offers")
        assert isinstance(offers, list)
        legacy_records: list[Any] = []
        for index, offer in enumerate(offers):
            if not isinstance(offer, Mapping):
                legacy_records.append(offer)
                continue
            legacy_records.append(
                {
                    "raw_offer_index": index,
                    "retrieval_kind": "legacy_product_seed_comparison",
                    "retrieval_score": offer.get("match_score"),
                    "product": {
                        key: value
                        for key, value in offer.items()
                        if key
                        not in {
                            "automatic_eligible",
                            "comparison_evidence",
                            "match_kind",
                            "match_score",
                        }
                    },
                    "upstream_comparison_evidence": offer.get("comparison_evidence"),
                    "legacy_unverified": True,
                }
            )
        return legacy_records


def _structured_completeness(
    records: list[Any],
    *,
    schema_version: str,
) -> float:
    """Return a bounded completeness ratio for fields used by evidence storage."""

    if not records:
        return 1.0
    ratios: list[float] = []
    for record in records:
        raw = (
            record.get("product")
            if schema_version == PROM_OUTPUT_SCHEMA_VERSION
            and isinstance(record, Mapping)
            else record
        )
        if not isinstance(raw, Mapping):
            ratios.append(0.0)
            continue
        seller_present = bool(raw.get("seller_id") or raw.get("seller_name"))
        price = _finite_positive_number(raw.get("price"))
        checks = (
            seller_present,
            price,
            isinstance(raw.get("currency"), str) and bool(raw.get("currency")),
            isinstance(raw.get("name"), str) and bool(raw.get("name")),
            isinstance(raw.get("url"), str)
            and raw.get("url", "").startswith(("https://", "http://")),
        )
        ratios.append(sum(checks) / len(checks))
    return round(sum(ratios) / len(ratios), 6)


def _finite_positive_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number > 0 and number != float("inf") and number == number


def _bounded_number(value: Any, *, minimum: float, maximum: float) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return minimum <= number <= maximum


def classify_scraper_exception(exc: Exception) -> ScraperBoundaryError:
    """Map parser/network failures to stable retry semantics."""

    if isinstance(exc, ScraperBoundaryError):
        return exc
    if isinstance(exc, CollectionCircuitOpen):
        return ScraperBoundaryError(
            ScraperErrorCode.CIRCUIT_OPEN, str(exc), retryable=True
        )
    if isinstance(exc, SourceAccessBlocked):
        return ScraperBoundaryError(
            ScraperErrorCode.SOURCE_ACCESS_BLOCKED,
            str(exc),
            retryable=False,
        )
    if isinstance(exc, (EvidenceIntegrityError, ReplayIntegrityError)):
        return ScraperBoundaryError(
            ScraperErrorCode.EVIDENCE_PERSISTENCE,
            str(exc),
            retryable=False,
        )
    if isinstance(exc, (requests.Timeout, TimeoutError)):
        return ScraperBoundaryError(ScraperErrorCode.TIMEOUT, str(exc), retryable=True)
    if isinstance(exc, requests.RequestException):
        return ScraperBoundaryError(ScraperErrorCode.NETWORK, str(exc), retryable=True)
    if isinstance(exc, UnsafeResponse):
        return ScraperBoundaryError(
            ScraperErrorCode.UNSAFE_RESPONSE,
            str(exc),
            retryable=False,
        )
    if isinstance(exc, ParserSchemaChanged):
        return ScraperBoundaryError(
            ScraperErrorCode.PARSER_SCHEMA_CHANGED, str(exc), retryable=False
        )
    if isinstance(exc, ParseError):
        return ScraperBoundaryError(
            ScraperErrorCode.PARSE_CONTRACT, str(exc), retryable=False
        )
    if isinstance(exc, RequestFailed):
        cause = exc.__cause__
        if isinstance(cause, (requests.Timeout, TimeoutError)):
            return ScraperBoundaryError(
                ScraperErrorCode.TIMEOUT,
                str(exc),
                retryable=True,
            )
        message = str(exc)
        status_match = _HTTP_STATUS_RE.search(message)
        status = int(status_match.group("status")) if status_match is not None else None
        if status == 408:
            code, retryable = ScraperErrorCode.TIMEOUT, True
        elif status == 429:
            code, retryable = ScraperErrorCode.RATE_LIMITED, True
        elif status is not None and 500 <= status <= 599:
            code, retryable = ScraperErrorCode.UPSTREAM_5XX, True
        elif status is not None and 400 <= status <= 499:
            code, retryable = ScraperErrorCode.UPSTREAM_4XX, False
        elif status is not None and 300 <= status <= 399:
            code, retryable = ScraperErrorCode.UPSTREAM_3XX, False
        else:
            code, retryable = ScraperErrorCode.NETWORK, True
        return ScraperBoundaryError(code, message, retryable=retryable)
    if isinstance(exc, ValueError):
        return ScraperBoundaryError(
            ScraperErrorCode.INVALID_INPUT, str(exc), retryable=False
        )
    return ScraperBoundaryError(
        ScraperErrorCode.UNEXPECTED,
        f"{type(exc).__name__}: {exc}",
        retryable=True,
    )


class FrozenPromScraperAdapter:
    """Process/thread-safe wrapper that creates a fresh gateway per extraction."""

    def __init__(
        self,
        config: ScrapeConfig | None = None,
        *,
        gateway_factory: Callable[[ScrapeConfig], Any] | None = None,
    ) -> None:
        self._config = config or ScrapeConfig()
        self._gateway_factory = gateway_factory or PromGateway

    def extract(self, scrape_input: AcquisitionInput) -> ScrapeOutput:
        try:
            gateway = self._gateway_factory(self._config)
            if isinstance(scrape_input, QueryInput):
                products = list(
                    gateway.search(
                        scrape_input.query,
                        lang=scrape_input.language,
                        strict=True,
                    )
                )
                if not all(isinstance(product, Product) for product in products):
                    raise ScraperBoundaryError(
                        ScraperErrorCode.SERIALIZATION,
                        "Gateway returned an unsupported query product type",
                        retryable=False,
                    )
                return ScrapeOutput.from_search(scrape_input, products)
            comparison = gateway.compare(
                scrape_input.product_url,
                query=scrape_input.query,
                strict=True,
            )
            if not isinstance(comparison, PriceComparison):
                raise ScraperBoundaryError(
                    ScraperErrorCode.SERIALIZATION,
                    "Gateway returned an unsupported output type",
                    retryable=False,
                )
            return ScrapeOutput.from_comparison(scrape_input, comparison)
        except ScraperBoundaryError:
            raise
        except Exception as exc:
            raise classify_scraper_exception(exc) from exc


@dataclass(frozen=True)
class AttemptMeasurement:
    wall_time_ms: int
    cpu_time_ms: int
    memory_peak_bytes: int

    @property
    def cpu_average_percent(self) -> float:
        if self.wall_time_ms <= 0:
            return 0.0
        return round(100 * self.cpu_time_ms / self.wall_time_ms, 3)


class AttemptResourceProbe:
    """Measure wall time, process CPU, and process peak RSS around one call."""

    def __init__(self) -> None:
        self._wall_started = time.perf_counter()
        self._cpu_started = time.process_time()

    def finish(self) -> AttemptMeasurement:
        wall_ms = max(0, round((time.perf_counter() - self._wall_started) * 1000))
        cpu_ms = max(0, round((time.process_time() - self._cpu_started) * 1000))
        return AttemptMeasurement(
            wall_time_ms=wall_ms,
            cpu_time_ms=cpu_ms,
            memory_peak_bytes=_process_peak_rss_bytes(),
        )


def _process_peak_rss_bytes() -> int:
    try:
        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (ValueError, OSError):
        return 0
    # macOS reports bytes; Linux and most BSD builds report KiB.
    return rss if sys.platform == "darwin" else rss * 1024


__all__ = [
    "AcquisitionInput",
    "AttemptMeasurement",
    "AttemptResourceProbe",
    "FrozenPromScraperAdapter",
    "PROM_ADAPTER_VERSION",
    "PROM_OUTPUT_SCHEMA_VERSION",
    "LEGACY_PROM_OUTPUT_SCHEMA_VERSION",
    "ProductSeedInput",
    "QueryInput",
    "ScrapeInput",
    "ScrapeOutput",
    "ScraperBoundaryError",
    "ScraperErrorCode",
    "build_acquisition_input",
    "classify_scraper_exception",
    "fallback_input_hash",
    "normalize_prom_query",
]
