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
    delay: float = 0.25         # minimum interval between request starts
    delay_jitter: float = 0.1   # random jitter in seconds
    timeout: float = 30.0       # HTTP request timeout in seconds
    max_retries: int = 4        # maximum retries per request
    backoff_factor: float = 1.5 # exponential backoff factor
    max_pages: int = 0
    start_page: int = 1
    page_concurrency: int = 8
    catalog_result_limit: int = 10_000
    expand_product_groups: bool = True
    max_search_pages: int = 3      # search pages to scan while collecting offers
    user_agents: tuple[str, ...] = USER_AGENTS
    base_headers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HEADERS))
