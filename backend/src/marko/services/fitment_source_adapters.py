"""Fail-closed contracts for query-level automotive evidence sources.

Adapters declare capabilities and access policy; registration never grants
permission to retrieve.  Concrete network adapters must be supplied only for
sources whose terms, robots policy and authentication requirements have been
reviewed and persisted as permitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import hashlib
import random
from typing import Any, Protocol, runtime_checkable


class SourceCapability(StrEnum):
    SEARCH_BY_ARTICLE = "search_by_article"
    SEARCH_BY_OE = "search_by_oe"
    SEARCH_FITMENT = "search_fitment"
    FETCH_DOCUMENT = "fetch_document"


class RetrievalErrorCode(StrEnum):
    TEMPORARY_ERROR = "temporary_error"
    PERMANENT_ERROR = "permanent_error"
    ACCESS_DENIED = "access_denied"
    CAPTCHA_REQUIRED = "captcha_required"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    PARSER_ERROR = "parser_error"
    SCHEMA_ERROR = "schema_error"
    CIRCUIT_OPEN = "circuit_open"
    SOURCE_NOT_PERMITTED = "source_not_permitted"


class SourceAccessStatus(StrEnum):
    PERMITTED = "PERMITTED"
    OWNER_RISK_ACCEPTED = "OWNER_RISK_ACCEPTED"
    NOT_PERMITTED = "NOT_PERMITTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class VehicleQuery:
    make: str
    model: str
    generation: str | None = None
    year: int | None = None
    engine: str | None = None
    body: str | None = None
    market: str | None = None


@dataclass(frozen=True, slots=True)
class SourceResult:
    source_id: str
    result_id: str
    url: str
    title: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SourceDocument:
    source_id: str
    source_url: str
    content_sha256: str
    retrieved_at: datetime
    content_locator: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    jitter_fraction: float = 0.25

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.base_delay_seconds <= 0 or self.max_delay_seconds <= 0:
            raise ValueError("retry delays must be positive")
        if not 0 <= self.jitter_fraction <= 1:
            raise ValueError("jitter_fraction must be in [0, 1]")

    def delay(self, attempt_no: int, *, random_value: float | None = None) -> float:
        if attempt_no < 0:
            raise ValueError("attempt_no cannot be negative")
        cap = min(self.max_delay_seconds, self.base_delay_seconds * (2**attempt_no))
        sample = random.random() if random_value is None else random_value
        if not 0 <= sample <= 1:
            raise ValueError("random_value must be in [0, 1]")
        jitter = cap * self.jitter_fraction * sample
        return round(min(self.max_delay_seconds, cap + jitter), 6)


@dataclass(frozen=True, slots=True)
class CachePolicy:
    fact_ttl: timedelta
    document_ttl: timedelta
    retain_human_confirmed: bool = True

    def __post_init__(self) -> None:
        if self.fact_ttl <= timedelta(0) or self.document_ttl <= timedelta(0):
            raise ValueError("cache TTL must be positive")


@dataclass(frozen=True, slots=True)
class SourceAdapterPolicy:
    source_id: str
    capabilities: frozenset[SourceCapability]
    access_status: SourceAccessStatus
    access_reference: str
    robots_checked: bool
    terms_checked: bool
    authentication_required: bool
    rate_limit: str
    retry_policy: RetryPolicy
    cache_policy: CachePolicy
    policy_version: str

    @property
    def retrieval_authorized(self) -> bool:
        return (
            self.access_status
            in {SourceAccessStatus.PERMITTED, SourceAccessStatus.OWNER_RISK_ACCEPTED}
            and self.robots_checked
            and self.terms_checked
            and bool(self.access_reference.strip())
        )

    def require(self, capability: SourceCapability) -> None:
        if not self.retrieval_authorized:
            raise SourceRetrievalError(
                RetrievalErrorCode.SOURCE_NOT_PERMITTED,
                f"source {self.source_id} is not approved for retrieval",
                retryable=False,
            )
        if capability not in self.capabilities:
            raise SourceRetrievalError(
                RetrievalErrorCode.PERMANENT_ERROR,
                f"source {self.source_id} does not support {capability.value}",
                retryable=False,
            )


class SourceRetrievalError(RuntimeError):
    def __init__(
        self,
        code: RetrievalErrorCode,
        detail: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.retryable = retryable


@runtime_checkable
class SourceAdapter(Protocol):
    source_id: str
    policy: SourceAdapterPolicy

    async def is_available(self) -> bool: ...

    async def search_by_article(
        self,
        brand: str | None,
        article: str,
    ) -> list[SourceResult]: ...

    async def search_by_oe(self, oe_number: str) -> list[SourceResult]: ...

    async def search_fitment(
        self,
        article: str,
        vehicle: VehicleQuery,
    ) -> list[SourceResult]: ...

    async def fetch_document(self, result: SourceResult) -> SourceDocument: ...


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: timedelta = timedelta(minutes=5)
    consecutive_failures: int = 0
    opened_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.failure_threshold < 1 or self.recovery_timeout <= timedelta(0):
            raise ValueError("invalid circuit breaker configuration")

    def allow_request(self, *, now: datetime | None = None) -> bool:
        if self.opened_at is None:
            return True
        current = now or datetime.now(UTC)
        if current - self.opened_at >= self.recovery_timeout:
            return True
        return False

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None

    def record_failure(self, *, now: datetime | None = None) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.opened_at = now or datetime.now(UTC)


def cache_key(
    *, source_id: str, capability: SourceCapability, query: dict[str, Any]
) -> str:
    canonical = repr(
        (source_id.strip().casefold(), capability.value, sorted(query.items()))
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = [
    "CachePolicy",
    "CircuitBreaker",
    "RetrievalErrorCode",
    "RetryPolicy",
    "SourceAccessStatus",
    "SourceAdapter",
    "SourceAdapterPolicy",
    "SourceCapability",
    "SourceDocument",
    "SourceResult",
    "SourceRetrievalError",
    "VehicleQuery",
    "cache_key",
]
