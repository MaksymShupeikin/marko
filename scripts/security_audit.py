#!/usr/bin/env python3
"""Read-only Marko production security and SEO smoke test.

The script deliberately sends only ordinary GET/OPTIONS requests. It does not
authenticate, mutate data, fuzz endpoints, or attempt to bypass access control.
"""

from __future__ import annotations

import argparse
import re
import ssl
import sys
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

try:
    import certifi
except ImportError:  # pragma: no cover - system trust store is the normal fallback
    certifi = None


_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where() if certifi else None)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
) -> Response:
    handlers = [HTTPSHandler(context=_SSL_CONTEXT)]
    if not follow_redirects:
        handlers.append(_NoRedirect())
    opener = build_opener(*handlers)
    request = Request(
        url,
        method=method,
        headers={"User-Agent": "MarkoSecurityAudit/1.0", **(headers or {})},
    )
    try:
        with opener.open(request, timeout=15) as response:
            return Response(
                response.status,
                {key.casefold(): value for key, value in response.headers.items()},
                response.read(8 * 1024 * 1024),
            )
    except HTTPError as error:
        return Response(
            error.code,
            {key.casefold(): value for key, value in error.headers.items()},
            error.read(8 * 1024 * 1024),
        )


def _header(response: Response, name: str) -> str:
    return response.headers.get(name.casefold(), "")


def _contains_all(value: str, expected: tuple[str, ...]) -> bool:
    folded = value.casefold()
    return all(token.casefold() in folded for token in expected)


def run(frontend: str, api: str, *, check_redirects: bool) -> list[Check]:
    checks: list[Check] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append(Check(name, ok, detail))

    index = _fetch(urljoin(frontend, "/"))
    add("frontend root", index.status == 200, f"HTTP {index.status}")

    hsts = _header(index, "strict-transport-security")
    match = re.search(r"(?:^|;)\s*max-age=(\d+)", hsts, re.IGNORECASE)
    hsts_seconds = int(match.group(1)) if match else 0
    add("frontend HSTS", hsts_seconds >= 31_536_000, hsts or "missing")

    csp = _header(index, "content-security-policy")
    csp_tokens = (
        "default-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
    )
    add("frontend CSP", _contains_all(csp, csp_tokens), csp or "missing")
    add(
        "clickjacking protection",
        _header(index, "x-frame-options").casefold() == "deny",
        _header(index, "x-frame-options") or "missing",
    )
    add(
        "permissions policy",
        bool(_header(index, "permissions-policy")),
        _header(index, "permissions-policy") or "missing",
    )
    add(
        "MIME sniffing protection",
        _header(index, "x-content-type-options").casefold() == "nosniff",
        _header(index, "x-content-type-options") or "missing",
    )
    add(
        "referrer policy",
        bool(_header(index, "referrer-policy")),
        _header(index, "referrer-policy") or "missing",
    )
    add(
        "real metadata",
        "A new Flutter project." not in index.text
        and '<meta name="description"' in index.text
        and 'property="og:title"' in index.text,
        "description and Open Graph present, no Flutter placeholder",
    )

    robots = _fetch(urljoin(frontend, "/robots.txt"))
    add(
        "robots.txt",
        robots.status == 200
        and _header(robots, "content-type").casefold().startswith("text/plain")
        and robots.text.startswith("User-agent: *\n"),
        f"HTTP {robots.status}, {_header(robots, 'content-type') or 'no content-type'}",
    )
    sitemap = _fetch(urljoin(frontend, "/sitemap.xml"))
    add(
        "sitemap.xml",
        sitemap.status == 200 and "<urlset" in sitemap.text,
        f"HTTP {sitemap.status}",
    )
    landing = _fetch(urljoin(frontend, "/about/"))
    add(
        "indexable landing page",
        landing.status == 200
        and "<h1" in landing.text.casefold()
        and "<main" in landing.text.casefold()
        and "A new Flutter project." not in landing.text,
        f"HTTP {landing.status}, static H1={('<h1' in landing.text.casefold())}",
    )
    missing = _fetch(urljoin(frontend, "/security-audit-definitely-missing-404"))
    add("real frontend 404", missing.status == 404, f"HTTP {missing.status}")

    bootstrap = _fetch(urljoin(frontend, "/flutter_bootstrap.js"))
    bundle_match = re.search(r"main\.[0-9a-f]{16}\.dart\.js", bootstrap.text)
    if bundle_match:
        bundle = _fetch(urljoin(frontend, f"/{bundle_match.group(0)}"))
        cache_control = _header(bundle, "cache-control")
        add(
            "fingerprinted immutable bundle",
            bundle.status == 200
            and "max-age=31536000" in cache_control
            and "immutable" in cache_control,
            f"{bundle_match.group(0)}; {cache_control or 'no cache-control'}",
        )
    else:
        add(
            "fingerprinted immutable bundle",
            False,
            "flutter_bootstrap.js does not reference a fingerprinted main bundle",
        )

    api_root = _fetch(urljoin(api, "/"))
    api_hsts = _header(api_root, "strict-transport-security")
    api_hsts_match = re.search(
        r"(?:^|;)\s*max-age=(\d+)", api_hsts, re.IGNORECASE
    )
    api_hsts_seconds = int(api_hsts_match.group(1)) if api_hsts_match else 0
    add("API HSTS", api_hsts_seconds >= 31_536_000, api_hsts or "missing")
    add(
        "API security headers",
        _header(api_root, "x-frame-options").casefold() == "deny"
        and bool(_header(api_root, "content-security-policy"))
        and bool(_header(api_root, "permissions-policy"))
        and _header(api_root, "cache-control").casefold() == "no-store",
        "X-Frame-Options, CSP, Permissions-Policy, no-store",
    )
    for route in ("/docs", "/redoc", "/openapi.json"):
        response = _fetch(urljoin(api, route))
        add(f"closed API {route}", response.status in {401, 403, 404}, f"HTTP {response.status}")

    live = _fetch(urljoin(api, "/api/v1/health/live"))
    add("public liveness", live.status == 200, f"HTTP {live.status}")
    protected = _fetch(urljoin(api, "/api/v1/products"))
    add("API authentication", protected.status == 401, f"HTTP {protected.status}")

    allowed_cors = _fetch(
        urljoin(api, "/api/v1/products"),
        method="OPTIONS",
        headers={
            "Origin": "https://markoprice.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    add(
        "allowed CORS origin",
        allowed_cors.status == 200
        and _header(allowed_cors, "access-control-allow-origin")
        == "https://markoprice.com",
        f"HTTP {allowed_cors.status}; allow-origin={_header(allowed_cors, 'access-control-allow-origin') or 'missing'}",
    )
    rejected_cors = _fetch(
        urljoin(api, "/api/v1/products"),
        method="OPTIONS",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    add(
        "rejected CORS origin",
        rejected_cors.status >= 400
        and not _header(rejected_cors, "access-control-allow-origin"),
        f"HTTP {rejected_cors.status}; allow-origin={_header(rejected_cors, 'access-control-allow-origin') or 'missing'}",
    )

    if check_redirects:
        http_apex = _fetch(
            "http://markoprice.com/", follow_redirects=False
        )
        add(
            "HTTP to HTTPS redirect",
            http_apex.status in {301, 302, 307, 308}
            and _header(http_apex, "location").startswith("https://markoprice.com"),
            f"HTTP {http_apex.status}; location={_header(http_apex, 'location') or 'missing'}",
        )
        www = _fetch("https://www.markoprice.com/", follow_redirects=False)
        add(
            "www to apex redirect",
            www.status in {301, 302, 307, 308}
            and _header(www, "location").startswith("https://markoprice.com"),
            f"HTTP {www.status}; location={_header(www, 'location') or 'missing'}",
        )

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="https://markoprice.com")
    parser.add_argument("--api", default="https://api.markoprice.com")
    parser.add_argument(
        "--skip-redirects",
        action="store_true",
        help="skip public-domain redirect checks (useful for localhost)",
    )
    arguments = parser.parse_args()

    try:
        checks = run(
            arguments.frontend.rstrip("/"),
            arguments.api.rstrip("/"),
            check_redirects=not arguments.skip_redirects,
        )
    except (URLError, TimeoutError, OSError) as error:
        print(f"ERROR: audit could not complete: {error}", file=sys.stderr)
        return 2

    for check in checks:
        marker = "PASS" if check.ok else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}")
    failures = sum(not check.ok for check in checks)
    print(f"\n{len(checks) - failures}/{len(checks)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
