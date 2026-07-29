"""Execution-scoped HTTP telemetry and replay for the frozen Prom gateway.

The gateway and parser keep their extraction behavior.  ``HttpClient`` calls
this boundary to expose logical requests, physical attempts, raw responses,
global source pacing, and deterministic network-free replay.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import time
from typing import Any
from urllib.parse import urlsplit

import requests

from marko.services.collection_guard import DistributedCollectionGuard


SCRAPE_ITEM_CONTRACT_VERSION = "scrape-logical-item-v1"
HTTP_TRACE_CONTRACT_VERSION = "scrape-http-trace-v1"


class ReplayIntegrityError(RuntimeError):
    """Stored replay bytes do not match their content-addressed identity."""


@dataclass(frozen=True)
class ReplayEvidence:
    request_key: str
    body: bytes
    status_code: int = 200
    encoding: str | None = None
    content_type: str | None = None
    content_sha256: str | None = None


@dataclass
class HttpAttemptTrace:
    attempt_no: int
    outcome: str
    status_code: int | None
    status_class: str
    latency_ms: int
    local_rate_wait_ms: int
    global_rate_wait_ms: int
    retry_backoff_ms: int = 0
    error_category: str | None = None
    error_detail: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class LogicalRequestTrace:
    sequence_no: int
    request_kind: str
    prepared_url: str
    request_key: str
    started_at: datetime
    started_perf: float
    outcome: str = "running"
    attempts: list[HttpAttemptTrace] = field(default_factory=list)
    replayed: bool = False
    response_status_code: int | None = None
    response_encoding: str | None = None
    response_content_type: str | None = None
    response_redirect_location: str | None = None
    raw_body: bytes | None = None
    content_sha256: str | None = None
    total_rate_wait_ms: int = 0
    total_backoff_ms: int = 0
    latency_ms: int = 0
    error_category: str | None = None
    error_detail: str | None = None
    finished_at: datetime | None = None


class ScrapeExecutionTrace:
    """In-memory trace drained into the durable journal by orchestration."""

    def __init__(
        self,
        *,
        item_kind: str,
        item_version: str = SCRAPE_ITEM_CONTRACT_VERSION,
        execution_no: int,
        replay_cache: Mapping[str, ReplayEvidence] | None = None,
        guard: DistributedCollectionGuard | None = None,
        live_request_gate: Callable[[], None] | None = None,
    ) -> None:
        if execution_no < 1:
            raise ValueError("execution_no must be at least one")
        self.item_kind = item_kind
        self.item_version = item_version
        self.execution_no = execution_no
        self.trace_version = HTTP_TRACE_CONTRACT_VERSION
        self._guard = guard
        self._live_request_gate = live_request_gate
        self._replay_cache = dict(replay_cache or {})
        self._sequence = 0
        self._completed: list[LogicalRequestTrace] = []

    def begin_request(
        self,
        url: str,
        params: Mapping[str, Any] | None,
    ) -> LogicalRequestTrace:
        self._sequence += 1
        prepared_url = _prepare_url(url, params)
        request_kind = infer_request_kind(prepared_url)
        request_key = request_fingerprint(request_kind, prepared_url)
        return LogicalRequestTrace(
            sequence_no=self._sequence,
            request_kind=request_kind,
            prepared_url=prepared_url,
            request_key=request_key,
            started_at=datetime.now(UTC),
            started_perf=time.perf_counter(),
        )

    def replay_for(self, request: LogicalRequestTrace) -> requests.Response | None:
        evidence = self._replay_cache.get(request.request_key)
        if evidence is None:
            return None
        actual_hash = hashlib.sha256(evidence.body).hexdigest()
        if (
            evidence.content_sha256 is not None
            and evidence.content_sha256 != actual_hash
        ):
            self.finish_failure(
                request,
                outcome="terminal_failure",
                error_category="evidence_integrity",
                error_detail=("Replay evidence SHA-256 does not match the stored body"),
                status_code=evidence.status_code,
            )
            raise ReplayIntegrityError(
                "Replay evidence SHA-256 does not match the stored body"
            )
        response = requests.Response()
        response.status_code = evidence.status_code
        response.url = request.prepared_url
        response.encoding = evidence.encoding
        response.headers["Content-Type"] = evidence.content_type or "text/html"
        response._content = evidence.body  # noqa: SLF001 - requests replay boundary
        request.replayed = True
        request.outcome = "replayed"
        request.response_status_code = evidence.status_code
        request.response_encoding = evidence.encoding
        request.response_content_type = evidence.content_type
        request.raw_body = evidence.body
        request.content_sha256 = evidence.content_sha256 or actual_hash
        self._finish(request)
        return response

    def acquire_global_attempt_slot(self) -> int:
        if self._live_request_gate is not None:
            self._live_request_gate()
        if self._guard is None:
            return 0
        return round(self._guard.wait_for_slot() * 1000)

    def record_attempt(
        self,
        request: LogicalRequestTrace,
        *,
        attempt_no: int,
        outcome: str,
        status_code: int | None,
        latency_ms: int,
        local_rate_wait_ms: int,
        global_rate_wait_ms: int,
        error_category: str | None = None,
        error_detail: str | None = None,
    ) -> HttpAttemptTrace:
        attempt = HttpAttemptTrace(
            attempt_no=attempt_no,
            outcome=outcome,
            status_code=status_code,
            status_class=_status_class(status_code),
            latency_ms=max(0, latency_ms),
            local_rate_wait_ms=max(0, local_rate_wait_ms),
            global_rate_wait_ms=max(0, global_rate_wait_ms),
            error_category=error_category,
            error_detail=error_detail,
        )
        request.attempts.append(attempt)
        request.total_rate_wait_ms += (
            attempt.local_rate_wait_ms + attempt.global_rate_wait_ms
        )
        if self._guard is not None:
            if outcome == "success":
                self._guard.record_success()
            elif outcome == "retryable_failure":
                self._guard.record_failure()
        return attempt

    def record_backoff(
        self,
        request: LogicalRequestTrace,
        attempt: HttpAttemptTrace,
        seconds: float,
    ) -> None:
        milliseconds = max(0, round(seconds * 1000))
        attempt.retry_backoff_ms = milliseconds
        request.total_backoff_ms += milliseconds

    def finish_success(
        self,
        request: LogicalRequestTrace,
        response: requests.Response,
    ) -> None:
        body = response.content
        request.outcome = "success"
        request.response_status_code = response.status_code
        request.response_encoding = response.encoding
        request.response_content_type = response.headers.get("Content-Type")
        request.raw_body = body
        request.content_sha256 = hashlib.sha256(body).hexdigest()
        self._finish(request)

    def finish_failure(
        self,
        request: LogicalRequestTrace,
        *,
        outcome: str,
        error_category: str,
        error_detail: str,
        status_code: int | None = None,
    ) -> None:
        request.outcome = outcome
        request.response_status_code = status_code
        request.error_category = error_category
        request.error_detail = error_detail
        self._finish(request)

    def finish_response_failure(
        self,
        request: LogicalRequestTrace,
        response: requests.Response,
        *,
        outcome: str,
        error_category: str,
        error_detail: str,
    ) -> None:
        """Finish a non-success HTTP response while retaining bounded evidence."""

        body = response.content
        request.outcome = outcome
        request.response_status_code = response.status_code
        request.response_encoding = response.encoding
        request.response_content_type = response.headers.get("Content-Type")
        request.response_redirect_location = response.headers.get("Location")
        request.raw_body = body
        request.content_sha256 = hashlib.sha256(body).hexdigest()
        request.error_category = error_category
        request.error_detail = error_detail
        self._finish(request)

    def drain_completed_requests(self) -> list[LogicalRequestTrace]:
        completed = self._completed
        self._completed = []
        return completed

    def restore_completed_requests(
        self,
        requests_to_restore: list[LogicalRequestTrace],
    ) -> None:
        """Restore drained traces after a failed persistence transaction."""

        self._completed = requests_to_restore + self._completed

    def failed_requests(
        self,
        *,
        request_kinds: set[str] | None = None,
    ) -> tuple[LogicalRequestTrace, ...]:
        """Return completed required requests that did not produce a response."""

        return tuple(
            request
            for request in self._completed
            if request.outcome not in {"success", "replayed"}
            and (request_kinds is None or request.request_kind in request_kinds)
        )

    def close(self) -> None:
        if self._guard is not None:
            self._guard.close()
            self._guard = None

    def _finish(self, request: LogicalRequestTrace) -> None:
        request.finished_at = datetime.now(UTC)
        request.latency_ms = max(
            0,
            round((time.perf_counter() - request.started_perf) * 1000),
        )
        self._completed.append(request)


_ACTIVE_TRACE: ContextVar[ScrapeExecutionTrace | None] = ContextVar(
    "marko_active_scrape_trace",
    default=None,
)


@contextmanager
def scrape_execution(trace: ScrapeExecutionTrace) -> Iterator[ScrapeExecutionTrace]:
    token = _ACTIVE_TRACE.set(trace)
    try:
        yield trace
    finally:
        _ACTIVE_TRACE.reset(token)


def current_scrape_trace() -> ScrapeExecutionTrace | None:
    return _ACTIVE_TRACE.get()


def request_fingerprint(request_kind: str, prepared_url: str) -> str:
    payload = json.dumps(
        {
            "method": "GET",
            "request_kind": request_kind,
            "url": prepared_url,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def infer_request_kind(prepared_url: str) -> str:
    parsed = urlsplit(prepared_url)
    path = parsed.path.casefold()
    if path.endswith("/search"):
        return "search_page"
    leaf = path.rsplit("/", 1)[-1]
    if leaf.startswith("p") and leaf.endswith(".html"):
        return "product_page"
    return "catalog_page"


def _prepare_url(url: str, params: Mapping[str, Any] | None) -> str:
    request = requests.Request("GET", url, params=dict(params or {})).prepare()
    if request.url is None:
        raise ValueError("HTTP request URL could not be prepared")
    return request.url


def _status_class(status_code: int | None) -> str:
    if status_code is None:
        return "network"
    return f"{status_code // 100}xx"


__all__ = [
    "HTTP_TRACE_CONTRACT_VERSION",
    "HttpAttemptTrace",
    "LogicalRequestTrace",
    "ReplayEvidence",
    "ReplayIntegrityError",
    "SCRAPE_ITEM_CONTRACT_VERSION",
    "ScrapeExecutionTrace",
    "current_scrape_trace",
    "infer_request_kind",
    "request_fingerprint",
    "scrape_execution",
]
