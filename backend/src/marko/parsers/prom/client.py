"""HTTP client with retries and polite rate limiting."""
from __future__ import annotations

import logging
import random
import time

import requests

from marko.services.scrape_runtime import current_scrape_trace

from .config import ScrapeConfig
from .exceptions import RequestFailed

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
                    url, params=params, timeout=self._config.timeout, allow_redirects=True
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
                        f"HTTP {response.status_code} для {response.url}"
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
                last_error = RequestFailed(f"HTTP {response.status_code}")
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
                log.warning("HTTP %d (спроба %d) для %s", response.status_code, attempt, url)

            if attempt < self._config.max_attempts:
                backoff = self._backoff_seconds(attempt)
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
        return (
            status_code in self._RETRYABLE_STATUS
            or 500 <= status_code <= 599
        )

    def _backoff_seconds(self, attempt: int) -> float:
        return self._config.backoff_factor ** attempt

    def _sleep_backoff(self, delay: float) -> None:
        log.debug("Backoff %.1fs перед наступною спробою", delay)
        time.sleep(delay)
