"""Stable black-box contract around the existing Prom extraction component.

Parser and matching internals remain unchanged.  The gateway exposes only an
opt-in fail-fast mode for orchestrated calls.  This module owns input
validation, deterministic output serialization, error taxonomy, and
per-attempt resource measurement so orchestration code does not depend on
parser internals.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
import resource
import sys
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import ParseError, RequestFailed, UnsafeResponse
from marko.parsers.prom.gateway import PromGateway
from marko.services.collection_guard import CollectionCircuitOpen
from marko.services.matching import PriceComparison
from marko.services.scrape_journal import EvidenceIntegrityError
from marko.services.scrape_runtime import ReplayIntegrityError
from marko.services.source_access import SourceAccessBlocked


PROM_ADAPTER_VERSION = "prom-parser-adapter-v2"
PROM_OUTPUT_SCHEMA_VERSION = "prom-price-comparison-v1"

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


@dataclass(frozen=True)
class ScrapeInput:
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

    @classmethod
    def build(
        cls,
        product_url: str | None,
        query: str | None,
        *,
        adapter_version: str = PROM_ADAPTER_VERSION,
    ) -> ScrapeInput:
        raw_url = (product_url or "").strip()
        normalized_query = " ".join((query or "").strip().upper().split())
        if not raw_url:
            raise ScraperBoundaryError(
                ScraperErrorCode.INVALID_INPUT,
                "Product URL is required",
                retryable=False,
            )
        if not normalized_query:
            raise ScraperBoundaryError(
                ScraperErrorCode.INVALID_INPUT,
                "Comparison query is required",
                retryable=False,
            )
        if len(normalized_query) > 255:
            raise ScraperBoundaryError(
                ScraperErrorCode.INVALID_INPUT,
                "Comparison query exceeds 255 characters",
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
        if parsed.scheme.casefold() not in {"http", "https"} or hostname not in {
            "prom.ua",
            "www.prom.ua",
        }:
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
        canonical_url = urlunsplit(
            ("https", "prom.ua", f"/{lang}/p{product_id}-{slug}.html", "", "")
        )
        product_key = f"prom:product:{product_id}"
        digest_source = json.dumps(
            {
                "adapter_version": adapter_version,
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
            "product_url": self.product_url,
            "canonical_url": self.canonical_url,
            "product_key": self.product_key,
            "query": self.query,
            "adapter_version": self.adapter_version,
            "input_hash": self.input_hash,
        }


def fallback_input_hash(
    product_url: str | None,
    query: str | None,
    *,
    adapter_version: str = PROM_ADAPTER_VERSION,
) -> str:
    """Stable key for invalid inputs so repeated delivery is still idempotent."""

    payload = {
        "adapter_version": adapter_version,
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
        scrape_input: ScrapeInput,
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
        for serialized, offer in zip(offers, comparison.offers, strict=True):
            if not isinstance(serialized, dict):
                raise ScraperBoundaryError(
                    ScraperErrorCode.SERIALIZATION,
                    "Serialized comparison offer must be an object",
                    retryable=False,
                )
            serialized["product_id"] = offer.product.id
            serialized["is_available"] = offer.product.is_available

        payload = {
            "schema_version": PROM_OUTPUT_SCHEMA_VERSION,
            "adapter_version": scrape_input.adapter_version,
            "input": scrape_input.as_dict(),
            "output": comparison_payload,
        }
        return cls.from_payload(payload)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ScrapeOutput:
        if payload.get("schema_version") != PROM_OUTPUT_SCHEMA_VERSION:
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
        offers = output_payload.get("offers")
        if not isinstance(offers, list):
            raise ScraperBoundaryError(
                ScraperErrorCode.SERIALIZATION,
                "Scraper output offers must be a list",
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
            structured_completeness=_structured_completeness(offers),
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


def _structured_completeness(offers: list[Any]) -> float:
    """Return a bounded completeness ratio for fields used by evidence storage."""

    if not offers:
        return 1.0
    ratios: list[float] = []
    for raw in offers:
        if not isinstance(raw, Mapping):
            ratios.append(0.0)
            continue
        seller_present = bool(raw.get("seller_id") or raw.get("seller_name"))
        price = _finite_positive_number(raw.get("price"))
        match_score = _bounded_number(raw.get("match_score"), minimum=0, maximum=1)
        checks = (
            seller_present,
            price,
            isinstance(raw.get("currency"), str) and bool(raw.get("currency")),
            match_score,
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
        return ScraperBoundaryError(
            ScraperErrorCode.TIMEOUT, str(exc), retryable=True
        )
    if isinstance(exc, requests.RequestException):
        return ScraperBoundaryError(
            ScraperErrorCode.NETWORK, str(exc), retryable=True
        )
    if isinstance(exc, UnsafeResponse):
        return ScraperBoundaryError(
            ScraperErrorCode.UNSAFE_RESPONSE,
            str(exc),
            retryable=False,
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
        status = (
            int(status_match.group("status"))
            if status_match is not None
            else None
        )
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

    def extract(self, scrape_input: ScrapeInput) -> ScrapeOutput:
        try:
            gateway = self._gateway_factory(self._config)
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
    "AttemptMeasurement",
    "AttemptResourceProbe",
    "FrozenPromScraperAdapter",
    "PROM_ADAPTER_VERSION",
    "PROM_OUTPUT_SCHEMA_VERSION",
    "ScrapeInput",
    "ScrapeOutput",
    "ScraperBoundaryError",
    "ScraperErrorCode",
    "classify_scraper_exception",
    "fallback_input_hash",
]
