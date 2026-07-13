"""HTTP client with retries and polite rate limiting."""
from __future__ import annotations

import logging
import random
import time

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
            self._rotate_user_agent()
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

    def _rotate_user_agent(self) -> None:
        self._session.headers["User-Agent"] = random.choice(self._config.user_agents)

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self._config.backoff_factor ** attempt
        log.debug("Backoff %.1fs перед наступною спробою", delay)
        time.sleep(delay)
