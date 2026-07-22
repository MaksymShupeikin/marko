"""HTTP client with retries and polite rate limiting."""
from __future__ import annotations

import asyncio
import logging
import random
import time

import httpx
import requests

from .config import ScrapeConfig
from .exceptions import RequestFailed

log = logging.getLogger(__name__)


class HttpClient:
    """Wrapper around requests.Session with retries and rate limiting."""
    _RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

    def __init__(self, config: ScrapeConfig) -> None:
        self._config = config
        self._session = requests.Session()
        self._session.headers.update(config.base_headers)
        self._session.headers["User-Agent"] = random.choice(config.user_agents)
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

        for attempt in range(1, self._config.max_retries + 1):
            self._respect_rate_limit()
            try:
                response = self._session.get(
                    url, params=params, timeout=self._config.timeout, allow_redirects=True
                )
            except requests.RequestException as exc:
                last_error = exc
                log.warning("Мережева помилка (спроба %d): %s", attempt, exc)
            else:
                if response.status_code == 200:
                    return response
                if response.status_code not in self._RETRYABLE_STATUS:
                    raise RequestFailed(f"HTTP {response.status_code} для {response.url}")
                last_error = RequestFailed(f"HTTP {response.status_code}")
                log.warning("HTTP %d (спроба %d) для %s", response.status_code, attempt, url)

            self._sleep_backoff(attempt)

        raise RequestFailed(f"Вичерпано {self._config.max_retries} спроб для {url}: {last_error}")

    def _respect_rate_limit(self) -> None:
        wait = self._config.delay + random.uniform(0, self._config.delay_jitter)
        elapsed = time.monotonic() - self._last_request_ts
        if self._last_request_ts and elapsed < wait:
            time.sleep(wait - elapsed)
        self._last_request_ts = time.monotonic()

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self._config.backoff_factor ** attempt
        log.debug("Backoff %.1fs перед наступною спробою", delay)
        time.sleep(delay)


class AsyncHttpClient:
    """Concurrent HTTP client with shared pacing and retry handling."""

    _RETRYABLE_STATUS = HttpClient._RETRYABLE_STATUS

    def __init__(self, config: ScrapeConfig) -> None:
        self._config = config
        connection_limit = max(1, config.page_concurrency)
        self._request_slots = asyncio.Semaphore(connection_limit)
        self._rate_lock = asyncio.Lock()
        self._next_request_at = 0.0
        headers = dict(config.base_headers)
        headers["User-Agent"] = random.choice(config.user_agents)
        limits = httpx.Limits(
            max_connections=connection_limit,
            max_keepalive_connections=connection_limit,
        )
        self._client = httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=config.timeout,
            limits=limits,
        )

    async def get_html(self, url: str, params: dict | None = None) -> str:
        """Return page HTML after applying retries and shared request pacing."""
        response = await self._request(url, params)
        return response.text

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncHttpClient:
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def _request(self, url: str, params: dict | None) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self._config.max_retries + 1):
            async with self._request_slots:
                await self._respect_rate_limit()
                try:
                    response = await self._client.get(url, params=params)
                except httpx.RequestError as exc:
                    last_error = exc
                    log.warning("Мережева помилка (спроба %d): %s", attempt, exc)
                else:
                    if response.status_code == 200:
                        return response
                    if response.status_code not in self._RETRYABLE_STATUS:
                        raise RequestFailed(f"HTTP {response.status_code} для {response.url}")
                    last_error = RequestFailed(f"HTTP {response.status_code}")
                    log.warning(
                        "HTTP %d (спроба %d) для %s",
                        response.status_code,
                        attempt,
                        url,
                    )
            await self._sleep_backoff(attempt)

        raise RequestFailed(
            f"Вичерпано {self._config.max_retries} спроб для {url}: {last_error}"
        )

    async def _respect_rate_limit(self) -> None:
        async with self._rate_lock:
            loop = asyncio.get_running_loop()
            wait = self._next_request_at - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            interval = self._config.delay + random.uniform(
                0,
                self._config.delay_jitter,
            )
            self._next_request_at = loop.time() + interval

    async def _sleep_backoff(self, attempt: int) -> None:
        delay = self._config.backoff_factor ** attempt
        log.debug("Backoff %.1fs перед наступною спробою", delay)
        await asyncio.sleep(delay)
