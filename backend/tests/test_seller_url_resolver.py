from __future__ import annotations

from collections import deque

import pytest
import requests
from pydantic import ValidationError

from marko.api.schemas.stores import StoreCreateRequest
from marko.services.seller_url_resolver import (
    PromSellerUrlError,
    PromSellerUrlUnavailable,
    resolve_prom_seller_sync,
)


class _FakeSession:
    def __init__(self, responses: list[requests.Response | Exception]) -> None:
        self.responses = deque(responses)
        self.requested_urls: list[str] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **_kwargs) -> requests.Response:
        self.requested_urls.append(url)
        value = self.responses.popleft()
        if isinstance(value, Exception):
            raise value
        return value


def _response(
    status: int,
    body: str = "",
    *,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {"Content-Type": "text/html; charset=utf-8"})
    response.encoding = "utf-8"
    response._content = body.encode()  # noqa: SLF001 - requests test fixture
    response._content_consumed = True  # noqa: SLF001 - requests test fixture
    return response


def test_store_request_accepts_public_prom_subdomain() -> None:
    request = StoreCreateRequest(url="  https://pilot-avto.prom.ua/ua/  ")
    assert request.url == "https://pilot-avto.prom.ua/ua/"


@pytest.mark.parametrize(
    "url",
    [
        "http://pilot-avto.prom.ua/ua/",
        "https://prom.ua.evil.example/ua/",
        "https://attacker.example/prom.ua/ua/c2847093-kemp.html",
        "https://user@pilot-avto.prom.ua/ua/",
    ],
)
def test_store_request_rejects_unsafe_or_lookalike_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        StoreCreateRequest(url=url)


def test_resolver_passes_through_canonical_marketplace_url() -> None:
    seller = resolve_prom_seller_sync("https://prom.ua/ua/c2847093-kemp.html")
    assert seller.company_id == "2847093"
    assert seller.slug == "kemp"
    assert seller.listing_url == "https://prom.ua/ua/c2847093-kemp.html"


def test_resolver_extracts_canonical_seller_metadata() -> None:
    html = """
    <html><head>
      <meta property="og:page_url"
            content="https://prom.ua/ua/c2257594-pilot-avto-avtozapchasti.html">
      <link rel="canonical"
            href="https://prom.ua/ua/c2257594-pilot-avto-avtozapchasti.html">
    </head></html>
    """
    session = _FakeSession([_response(200, html)])

    seller = resolve_prom_seller_sync(
        "https://pilot-avto.prom.ua/ua/",
        session=session,
    )

    assert seller.company_id == "2257594"
    assert seller.slug == "pilot-avto-avtozapchasti"
    assert session.requested_urls == ["https://pilot-avto.prom.ua/ua/"]


def test_resolver_follows_only_bounded_internal_redirects() -> None:
    redirect = _response(
        302,
        headers={"Location": "https://pilot-avto.prom.ua/ua/"},
    )
    html = (
        '<link rel="canonical" '
        'href="https://prom.ua/ua/c2257594-pilot-avto-avtozapchasti.html">'
    )
    session = _FakeSession([redirect, _response(200, html)])

    seller = resolve_prom_seller_sync(
        "https://pilot-avto.prom.ua/",
        max_redirects=1,
        session=session,
    )

    assert seller.company_id == "2257594"
    assert session.requested_urls == [
        "https://pilot-avto.prom.ua/",
        "https://pilot-avto.prom.ua/ua/",
    ]


def test_resolver_rejects_redirect_outside_prom() -> None:
    session = _FakeSession(
        [_response(302, headers={"Location": "https://attacker.example/store"})]
    )

    with pytest.raises(PromSellerUrlError, match="межі"):
        resolve_prom_seller_sync(
            "https://pilot-avto.prom.ua/ua/",
            session=session,
        )

    assert session.requested_urls == ["https://pilot-avto.prom.ua/ua/"]


def test_resolver_returns_clear_error_when_metadata_is_missing() -> None:
    session = _FakeSession([_response(200, "<html><head></head></html>")])
    with pytest.raises(PromSellerUrlError, match="канонічний company URL"):
        resolve_prom_seller_sync(
            "https://pilot-avto.prom.ua/ua/",
            session=session,
        )


def test_resolver_classifies_timeout_as_temporary_unavailability() -> None:
    session = _FakeSession([requests.Timeout("slow")])
    with pytest.raises(PromSellerUrlUnavailable, match="вчасно"):
        resolve_prom_seller_sync(
            "https://pilot-avto.prom.ua/ua/",
            session=session,
        )
