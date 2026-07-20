"""Network defaults and scraping configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

BASE_URL = "https://prom.ua"

USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
)

DEFAULT_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass(frozen=True)
class ScrapeConfig:
    """Parameters for a scraping session."""

    delay: float = 1.0  # base delay between requests in seconds
    delay_jitter: float = 0.5  # random jitter in seconds
    timeout: float = 30.0  # HTTP request timeout in seconds
    # Maximum physical attempts total for one logical HTTP request.  The old
    # name ``max_retries`` was ambiguous because 4 meant 4 attempts, not
    # 1 initial attempt + 4 retries.
    max_attempts: int = 4
    backoff_factor: float = 1.5  # base seconds for full-jitter exponential backoff
    backoff_max: float = 60.0
    max_response_bytes: int = 10 * 1024 * 1024
    max_compression_ratio: float = 100.0
    allowed_content_types: tuple[str, ...] = (
        "text/html",
        "application/xhtml+xml",
        "application/json",
    )
    max_pages: int = 0
    start_page: int = 1
    # Cross-seller comparison knobs.
    max_sellers: int = 10  # cap of distinct sellers in a comparison
    similarity_threshold: float = 0.55  # min fuzzy name score to accept a match
    max_search_pages: int = 3  # search pages to scan while collecting offers
    user_agents: tuple[str, ...] = USER_AGENTS
    base_headers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HEADERS))
