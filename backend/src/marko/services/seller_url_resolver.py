"""Admission and canonicalization for public Prom seller URLs.

The existing Prom parser accepts canonical marketplace company URLs.  Public
seller storefronts normally use ``<store>.prom.ua`` instead, so this module
resolves that presentation URL at the input boundary without changing parser
internals.
"""

from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from marko.core.config import Settings, get_settings
from marko.parsers.prom.config import DEFAULT_HEADERS, USER_AGENTS
from marko.services.parser_models import Seller


class PromSellerUrlError(ValueError):
    """The submitted URL is not a recognizable public Prom seller URL."""


class PromSellerUrlUnavailable(RuntimeError):
    """Prom could not be reached while resolving a valid seller storefront."""


class _CanonicalSellerMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value for key, value in attrs if value is not None}
        normalized_tag = tag.casefold()
        if normalized_tag == "link":
            rel = {part.casefold() for part in values.get("rel", "").split()}
            href = values.get("href")
            if "canonical" in rel and href:
                self.candidates.append(href)
        elif normalized_tag == "meta":
            property_name = (
                values.get("property") or values.get("name") or ""
            ).casefold()
            content = values.get("content")
            if property_name == "og:page_url" and content:
                self.candidates.append(content)


def validate_prom_seller_input(raw_url: str) -> str:
    """Validate the transport boundary without performing network I/O."""

    normalized = raw_url.strip()
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as exc:
        raise PromSellerUrlError("Некорректна адреса магазину Prom.ua") from exc
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or not _is_prom_host(host)
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise PromSellerUrlError(
            "Очікується HTTPS-посилання магазину на prom.ua або *.prom.ua"
        )

    # Root marketplace hosts are useful only when they already identify a
    # company.  Subdomain storefronts are resolved asynchronously later.
    if _is_marketplace_host(host):
        _seller_from_canonical_url(normalized)
    return urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))


async def resolve_prom_seller(
    raw_url: str,
    *,
    settings: Settings | None = None,
) -> Seller:
    """Return the canonical seller identity for a marketplace or storefront URL."""

    normalized = validate_prom_seller_input(raw_url)
    parsed = urlsplit(normalized)
    if _is_marketplace_host((parsed.hostname or "").casefold().rstrip(".")):
        return _seller_from_canonical_url(normalized)

    config = settings or get_settings()
    return await asyncio.to_thread(
        resolve_prom_seller_sync,
        normalized,
        timeout_seconds=config.store_url_resolver_timeout_seconds,
        max_redirects=config.store_url_resolver_max_redirects,
        max_response_bytes=config.store_url_resolver_max_response_bytes,
    )


def resolve_prom_seller_sync(
    raw_url: str,
    *,
    timeout_seconds: float = 10.0,
    max_redirects: int = 3,
    max_response_bytes: int = 2 * 1024 * 1024,
    session: requests.Session | None = None,
) -> Seller:
    """Synchronous implementation, exposed for deterministic boundary tests."""

    normalized = validate_prom_seller_input(raw_url)
    parsed = urlsplit(normalized)
    if _is_marketplace_host((parsed.hostname or "").casefold().rstrip(".")):
        return _seller_from_canonical_url(normalized)
    if timeout_seconds <= 0 or max_redirects < 0 or max_response_bytes < 1:
        raise ValueError("Resolver bounds must be positive")

    owns_session = session is None
    client = session or requests.Session()
    client.headers.update(DEFAULT_HEADERS)
    client.headers["User-Agent"] = USER_AGENTS[0]
    current_url = normalized
    try:
        for redirect_no in range(max_redirects + 1):
            try:
                response = client.get(
                    current_url,
                    timeout=timeout_seconds,
                    allow_redirects=False,
                    stream=True,
                )
            except requests.Timeout as exc:
                raise PromSellerUrlUnavailable(
                    "Prom.ua не відповів вчасно під час визначення магазину"
                ) from exc
            except requests.RequestException as exc:
                raise PromSellerUrlUnavailable(
                    "Не вдалося завантажити сторінку магазину Prom.ua"
                ) from exc

            try:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("Location")
                    if not location or redirect_no >= max_redirects:
                        raise PromSellerUrlError(
                            "Забагато або некоректні перенаправлення сторінки магазину"
                        )
                    next_url = urljoin(current_url, location)
                    current_url = _validate_prom_transport_url(next_url)
                    continue
                if not 200 <= response.status_code < 300:
                    if response.status_code >= 500 or response.status_code in {
                        408,
                        429,
                    }:
                        raise PromSellerUrlUnavailable(
                            f"Prom.ua тимчасово повернув HTTP {response.status_code}"
                        )
                    raise PromSellerUrlError(
                        f"Сторінка магазину Prom.ua повернула HTTP {response.status_code}"
                    )
                html = _read_bounded_html(response, max_response_bytes)
            finally:
                response.close()
            return _seller_from_storefront_html(html, base_url=current_url)
    finally:
        if owns_session:
            client.close()

    raise PromSellerUrlError("Не вдалося визначити канонічну адресу магазину Prom.ua")


def _seller_from_storefront_html(html: str, *, base_url: str) -> Seller:
    parser = _CanonicalSellerMetadataParser()
    parser.feed(html)
    for candidate in parser.candidates:
        absolute = urljoin(base_url, candidate)
        try:
            return _seller_from_canonical_url(absolute)
        except PromSellerUrlError:
            continue
    raise PromSellerUrlError(
        "Prom.ua не опублікував канонічний company URL для цього магазину"
    )


def _seller_from_canonical_url(url: str) -> Seller:
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme.casefold() != "https" or not _is_marketplace_host(host):
        raise PromSellerUrlError("Посилання не є канонічною адресою продавця Prom.ua")
    try:
        return Seller.from_url(url)
    except ValueError as exc:
        raise PromSellerUrlError(
            "Очікується адреса продавця на кшталт https://prom.ua/ua/c2847093-kemp.html"
        ) from exc


def _validate_prom_transport_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise PromSellerUrlError("Некоректне перенаправлення Prom.ua") from exc
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or not _is_prom_host(host)
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise PromSellerUrlError(
            "Prom.ua перенаправив запит за межі дозволеного домену"
        )
    return urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))


def _read_bounded_html(response: requests.Response, maximum: int) -> str:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
    if content_type.strip().casefold() not in {"text/html", "application/xhtml+xml"}:
        raise PromSellerUrlError("Сторінка магазину повернула не HTML")
    raw_length = response.headers.get("Content-Length")
    if raw_length:
        try:
            if int(raw_length) > maximum:
                raise PromSellerUrlError(
                    "Сторінка магазину перевищує дозволений розмір"
                )
        except ValueError as exc:
            raise PromSellerUrlError(
                "Некоректний Content-Length сторінки магазину"
            ) from exc
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > maximum:
            raise PromSellerUrlError("Сторінка магазину перевищує дозволений розмір")
        chunks.append(chunk)
    encoding = response.encoding or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace")


def _is_marketplace_host(host: str) -> bool:
    return host in {"prom.ua", "www.prom.ua"}


def _is_prom_host(host: str) -> bool:
    return _is_marketplace_host(host) or host.endswith(".prom.ua")


__all__ = [
    "PromSellerUrlError",
    "PromSellerUrlUnavailable",
    "resolve_prom_seller",
    "resolve_prom_seller_sync",
    "validate_prom_seller_input",
]
