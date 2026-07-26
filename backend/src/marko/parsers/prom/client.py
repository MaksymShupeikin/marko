"""HTTP client with retries and polite rate limiting."""

from __future__ import annotations

import logging
import random
import time

import requests

from marko.services.scrape_runtime import current_scrape_trace

from .config import ScrapeConfig
from .exceptions import RequestFailed, UnsafeResponse

log = logging.getLogger(__name__)


class HttpClient:
    """Wrapper around requests.Session with retries and rate limiting."""

    _RETRYABLE_STATUS = frozenset({408, 429})

    def __init__(self, config: ScrapeConfig) -> None:
        self._config = config
        self._session = requests.Session()
        self._session.headers.update(config.base_headers)
        self._last_request_ts = 0.0

    def get_html(self, url: str, params: dict | None = None) -> str:
        """Return page HTML content as text. Raises RequestFailed on failure."""
        response = self._request(url, params)
        return response.text

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _request(self, url: str, params: dict | None) -> requests.Response:
        last_error: Exception | None = None
        trace = current_scrape_trace()
        request_trace = trace.begin_request(url, params) if trace is not None else None
        if trace is not None and request_trace is not None:
            replayed = trace.replay_for(request_trace)
            if replayed is not None:
                return replayed

        for attempt in range(1, self._config.max_attempts + 1):
            retry_after_seconds: float | None = None
            local_wait_ms = round(self._respect_rate_limit() * 1000)
            try:
                global_wait_ms = (
                    trace.acquire_global_attempt_slot() if trace is not None else 0
                )
            except Exception as exc:
                if trace is not None and request_trace is not None:
                    trace.finish_failure(
                        request_trace,
                        outcome="retryable_failure",
                        error_category="circuit_open",
                        error_detail=f"{type(exc).__name__}: {exc}",
                    )
                raise
            self._rotate_user_agent()
            attempt_started = time.perf_counter()
            try:
                response = self._session.get(
                    # Redirects are fail-closed.  The trusted admission layer
                    # validates the original Prom host, while requests would
                    # otherwise follow a Location to an unvalidated host.
                    # Supporting redirects later requires per-hop admission
                    # and separate physical-attempt telemetry.
                    url,
                    params=params,
                    timeout=self._config.timeout,
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException as exc:
                last_error = exc
                error_category = (
                    "timeout" if isinstance(exc, requests.Timeout) else "network"
                )
                if trace is not None and request_trace is not None:
                    attempt_trace = trace.record_attempt(
                        request_trace,
                        attempt_no=attempt,
                        outcome="retryable_failure",
                        status_code=None,
                        latency_ms=round(
                            (time.perf_counter() - attempt_started) * 1000
                        ),
                        local_rate_wait_ms=local_wait_ms,
                        global_rate_wait_ms=global_wait_ms,
                        error_category=error_category,
                        error_detail=f"{type(exc).__name__}: {exc}",
                    )
                log.warning("Мережева помилка (спроба %d): %s", attempt, exc)
            else:
                if 200 <= response.status_code < 300:
                    try:
                        self._consume_bounded_response(response)
                    except UnsafeResponse as error:
                        if trace is not None and request_trace is not None:
                            trace.record_attempt(
                                request_trace,
                                attempt_no=attempt,
                                outcome="terminal_failure",
                                status_code=response.status_code,
                                latency_ms=round(
                                    (time.perf_counter() - attempt_started) * 1000
                                ),
                                local_rate_wait_ms=local_wait_ms,
                                global_rate_wait_ms=global_wait_ms,
                                error_category="unsafe_response",
                                error_detail=str(error),
                            )
                            trace.finish_failure(
                                request_trace,
                                outcome="terminal_failure",
                                error_category="unsafe_response",
                                error_detail=str(error),
                                status_code=response.status_code,
                            )
                        raise
                    if trace is not None and request_trace is not None:
                        trace.record_attempt(
                            request_trace,
                            attempt_no=attempt,
                            outcome="success",
                            status_code=response.status_code,
                            latency_ms=round(
                                (time.perf_counter() - attempt_started) * 1000
                            ),
                            local_rate_wait_ms=local_wait_ms,
                            global_rate_wait_ms=global_wait_ms,
                        )
                        trace.finish_success(request_trace, response)
                    return response
                if not self._is_retryable_status(response.status_code):
                    error = RequestFailed(
                        f"HTTP {response.status_code} для {response.url}",
                        status_code=response.status_code,
                    )
                    error_category = (
                        "upstream_3xx"
                        if 300 <= response.status_code < 400
                        else "upstream_4xx"
                    )
                    if trace is not None and request_trace is not None:
                        trace.record_attempt(
                            request_trace,
                            attempt_no=attempt,
                            outcome="terminal_failure",
                            status_code=response.status_code,
                            latency_ms=round(
                                (time.perf_counter() - attempt_started) * 1000
                            ),
                            local_rate_wait_ms=local_wait_ms,
                            global_rate_wait_ms=global_wait_ms,
                            error_category=error_category,
                            error_detail=str(error),
                        )
                        trace.finish_failure(
                            request_trace,
                            outcome="terminal_failure",
                            error_category=error_category,
                            error_detail=str(error),
                            status_code=response.status_code,
                        )
                    raise error
                last_error = RequestFailed(
                    f"HTTP {response.status_code}",
                    status_code=response.status_code,
                )
                retry_after_seconds = self._retry_after_seconds(response)
                if trace is not None and request_trace is not None:
                    attempt_trace = trace.record_attempt(
                        request_trace,
                        attempt_no=attempt,
                        outcome="retryable_failure",
                        status_code=response.status_code,
                        latency_ms=round(
                            (time.perf_counter() - attempt_started) * 1000
                        ),
                        local_rate_wait_ms=local_wait_ms,
                        global_rate_wait_ms=global_wait_ms,
                        error_category=(
                            "timeout"
                            if response.status_code == 408
                            else (
                                "rate_limited"
                                if response.status_code == 429
                                else "upstream_5xx"
                            )
                        ),
                        error_detail=str(last_error),
                    )
                log.warning(
                    "HTTP %d (спроба %d) для %s", response.status_code, attempt, url
                )

            if attempt < self._config.max_attempts:
                backoff = (
                    retry_after_seconds
                    if retry_after_seconds is not None
                    else self._backoff_seconds(attempt)
                )
                if trace is not None and request_trace is not None:
                    trace.record_backoff(request_trace, attempt_trace, backoff)
                self._sleep_backoff(backoff)

        error = RequestFailed(
            f"Вичерпано {self._config.max_attempts} спроб для {url}: {last_error}"
        )
        if trace is not None and request_trace is not None:
            trace.finish_failure(
                request_trace,
                outcome="retryable_failure",
                error_category="retry_exhausted",
                error_detail=str(error),
            )
        raise error from last_error

    def _respect_rate_limit(self) -> float:
        wait = self._config.delay + random.uniform(0, self._config.delay_jitter)
        elapsed = time.monotonic() - self._last_request_ts
        actual_wait = 0.0
        if self._last_request_ts and elapsed < wait:
            actual_wait = wait - elapsed
            time.sleep(actual_wait)
        self._last_request_ts = time.monotonic()
        return actual_wait

    def _rotate_user_agent(self) -> None:
        self._session.headers["User-Agent"] = random.choice(self._config.user_agents)

    def _is_retryable_status(self, status_code: int) -> bool:
        return status_code in self._RETRYABLE_STATUS or 500 <= status_code <= 599

    def _backoff_seconds(self, attempt: int) -> float:
        cap = min(
            max(0.0, self._config.backoff_max),
            max(0.0, self._config.backoff_factor) * (2 ** (attempt - 1)),
        )
        return random.uniform(0, cap)

    def _retry_after_seconds(self, response: requests.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            seconds = float(raw)
        except ValueError:
            return None
        if seconds < 0:
            return None
        return min(seconds, max(0.0, self._config.backoff_max))

    def _consume_bounded_response(self, response: requests.Response) -> None:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        content_type = content_type.strip().casefold()
        if content_type not in self._config.allowed_content_types:
            self._close_response(response)
            raise UnsafeResponse(
                f"Unsupported response content type: {content_type or 'none'}"
            )
        raw_length = self._content_length(response)
        if raw_length is not None and raw_length > self._config.max_response_bytes:
            self._close_response(response)
            raise UnsafeResponse("Response Content-Length exceeds configured limit")
        existing = getattr(response, "_content", False)
        if isinstance(existing, bytes):
            body = existing
        else:
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > self._config.max_response_bytes:
                    self._close_response(response)
                    raise UnsafeResponse(
                        "Decoded response exceeds configured byte limit"
                    )
                chunks.append(chunk)
            body = b"".join(chunks)
        if len(body) > self._config.max_response_bytes:
            self._close_response(response)
            raise UnsafeResponse("Decoded response exceeds configured byte limit")
        if (
            raw_length is not None
            and raw_length > 0
            and len(body) / raw_length > self._config.max_compression_ratio
        ):
            self._close_response(response)
            raise UnsafeResponse("Response exceeds configured compression ratio")
        response._content = body  # noqa: SLF001 - bounded buffering boundary
        response._content_consumed = True  # noqa: SLF001

    @staticmethod
    def _content_length(response: requests.Response) -> int | None:
        raw = response.headers.get("Content-Length")
        if raw is None:
            return None
        try:
            value = int(raw)
        except ValueError:
            raise UnsafeResponse("Invalid Content-Length header") from None
        if value < 0:
            raise UnsafeResponse("Invalid negative Content-Length header")
        return value

    @staticmethod
    def _close_response(response: requests.Response) -> None:
        try:
            response.close()
        except AttributeError:
            # Unit-test/replay responses may have no transport object.
            return

    def _sleep_backoff(self, delay: float) -> None:
        log.debug("Backoff %.1fs перед наступною спробою", delay)
        time.sleep(delay)
