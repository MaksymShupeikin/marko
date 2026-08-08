"""Parse Avto.pro seller/product HTML for offline identity harvest (OPTKiev).

Customer-owned channel (owner-confirmed 2026-08-07: ``/seller/optkiev/``), but
field labels are not trusted for automatic OE confirmation.  Extraction is
deliberately pure: network access, access policy and identity promotion live
outside this module.

Live product listing is frequently blocked by Azure WAF; callers must treat
:func:`classify_page_kind` ``WAF`` as a hard stop, not a retry storm.

Part pages (``/part-{code}-{BRAND}-{id}/``) carry OE candidates in the
``#original-manufacturers`` tile list.  Those are harvested as review material
(``source_field=oe``), never auto-promoted to ``OE_CONFIRMED``.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from html import unescape
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import unquote, urljoin, urlparse

import yaml

from metis.pricing.crosses import normalize_cross_oem

AVTO_PRO_TOKENS_SCHEMA_VERSION = "metis-avto-pro-tokens-v1"
EXTRACTION_METHOD = "AVTO_PRO_OPTKIEV"
DEFAULT_BASE_URL = "https://avto.pro"

_TAG_RE = re.compile(r"<[^>]+>", re.S)
_WS_RE = re.compile(r"\s+")
_PRODUCT_ID_RE = re.compile(r"-m(\d+)/?$", re.I)
# Brand slug is the last non-numeric path segment; code may contain hyphens
# (e.g. A112915010BA-MARKET). Match from the right: ...-BRAND-ID/
_PART_PATH_RE = re.compile(
    r"/part-(?P<code>.+)-(?P<brand>[A-Za-z0-9][A-Za-z0-9._]*)-(?P<id>\d+)/?",
    re.I,
)
_HREF_RE = re.compile(
    r"""href\s*=\s*["'](?P<href>(?:https?://avto\.pro)?/catalog/[^"'>\s]+-m\d+/?)["']""",
    re.I,
)
_PART_HREF_RE = re.compile(
    r"""href\s*=\s*["'](?P<href>(?:https?://avto\.pro)?/part-[^"'>\s]+/)["']""",
    re.I,
)
_H1_RE = re.compile(r"<h1\b[^>]*(?:title=\"(?P<title>[^\"]*)\")?[^>]*>(?P<body>.*?)</h1>", re.I | re.S)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(?P<title>.*?)</title>", re.I | re.S)
# <dt>Label</dt> ... <dd ...>value</dd> (possibly with nested tags in dd)
_DT_DD_RE = re.compile(
    r"<dt\b[^>]*>\s*(?P<label>.*?)\s*</dt>\s*"
    r"(?:<dd\b[^>]*>\s*(?P<value>.*?)\s*</dd>)",
    re.I | re.S,
)
# class-based fallbacks used in fixtures / simplified cards
_CLASS_FIELD_RE = re.compile(
    r'class="[^"]*product-attr__(?P<field>brand|article|oe|mpn)[^"]*"[^>]*>'
    r"\s*(?P<value>.*?)\s*</",
    re.I | re.S,
)
_NUMBER_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яІіЇїЄєҐґ0-9][A-Za-zА-Яа-яІіЇїЄєҐґ0-9./_-]{1,}")
_JS_SEARCH_CONTEXT_RE = re.compile(
    r'<script\b[^>]*\bid=["\']js-search-context["\'][^>]*>\s*(?P<body>.*?)\s*</script>',
    re.I | re.S,
)
_SECTION_RE_TMPL = (
    r'<section\b[^>]*\bid=["\']{section_id}["\'][^>]*>'
    r"(?P<body>.*?)</section>"
)
# Seller showcase carousel tiles (live OPTKiev 2026-08-07).
_SHOWCASE_SLIDE_RE = re.compile(
    r"<article\b(?P<attrs>[^>]*\bembla__slide\b[^>]*)>(?P<body>.*?)</article>",
    re.I | re.S,
)
_ATTR_RE = re.compile(
    r"""(?P<name>data-href|data-category-id|data-part-number|data-brand-id)"""
    r"""\s*=\s*["'](?P<value>[^"']*)["']""",
    re.I,
)
_CARD_NAME_RE = re.compile(
    r'class="[^"]*products-slider__card-name[^"]*"[^>]*>\s*(?P<name>.*?)\s*</',
    re.I | re.S,
)
_CARD_BRAND_RE = re.compile(
    r'class="[^"]*products-slider__code[^"]*"[^>]*>\s*(?P<code>.*?)\s*'
    r"<span\b[^>]*>\s*(?P<brand>.*?)\s*</span>",
    re.I | re.S,
)
_CARD_PRICE_RE = re.compile(
    r'class="[^"]*products-slider__price[^"]*"[^>]*>\s*(?P<price>.*?)\s*</',
    re.I | re.S,
)
_DATA_QA_RE = re.compile(
    r'data-qa=["\'](?P<qa>email|phone|name)["\'][^>]*>(?P<body>.*?)</',
    re.I | re.S,
)
_PHONE_TEXT_RE = re.compile(
    r'class="[^"]*pro-phone__text[^"]*"[^>]*>\s*(?P<phone>.*?)\s*</',
    re.I | re.S,
)
_REG_DATE_RE = re.compile(
    r"Зарегистрирован\s*</span>\s*<span[^>]*>\s*(?P<date>[^<]+?)\s*</span>",
    re.I | re.S,
)
_PRODUCT_GROUPS_COUNT_RE = re.compile(
    r"Товарн(?:ые|і)\s+групп\w*\s*</[^>]+>\s*<[^>]+>\s*(?P<count>\d+)",
    re.I | re.S,
)
_LOCATION_RE = re.compile(
    r"(?:Украина|Україна)\s*,\s*(?P<city>[А-Яа-яІіЇїЄєҐґA-Za-z\-]+)",
    re.I,
)
_HOURS_LINE_RE = re.compile(
    r"(?P<line>(?:Пн|Пн\s*-\s*Пт|Сб|Сб\s*-\s*Вс)[^<\n]{0,40})",
    re.I,
)
_WORK_TIME_SPAN_RE = re.compile(
    r'class="[^"]*pro-work-time__spans__span__day[^"]*"[^>]*>\s*(?P<day>.*?)\s*</span>'
    r"\s*<span[^>]*>\s*(?P<hours>.*?)\s*</span>",
    re.I | re.S,
)


class AvtoProConfigError(ValueError):
    """Token config missing, malformed, or unknown schema."""


class PageKind(str, Enum):
    SELLER_PROFILE = "SELLER_PROFILE"
    PRODUCT_CARD = "PRODUCT_CARD"
    PART_PAGE = "PART_PAGE"
    LISTING = "LISTING"
    WAF = "WAF"
    UNKNOWN = "UNKNOWN"


class ExtractionStatus(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    WAF = "WAF"
    PARSE_ERROR = "PARSE_ERROR"
    NO_NUMBERS = "NO_NUMBERS"
    EMPTY = "EMPTY"


@dataclass(frozen=True, slots=True)
class AvtoProTokensConfig:
    method_version: str
    source_key: str
    default_seller_slug: str
    base_url: str
    product_href_pattern: re.Pattern[str]
    field_labels: Mapping[str, tuple[str, ...]]
    waf_title_markers: tuple[str, ...]
    waf_body_markers: tuple[str, ...]
    min_number_length: int
    max_number_length: int
    original_section_id: str = "original-manufacturers"
    analog_section_id: str = "analog-parts"
    filter_by_oem_brand: bool = True
    oem_brands: frozenset[str] = frozenset()
    oem_brand_aliases: Mapping[str, str] = MappingProxyType({})  # set in loader
    noise_code_substrings: tuple[str, ...] = ()
    source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ProductRef:
    """Seed product reference from a seller profile page."""

    product_id: str
    path: str
    url: str
    title: str | None = None


@dataclass(frozen=True, slots=True)
class SellerShowcaseCard:
    """One tile from the seller-profile product carousel (``article.embla__slide``).

    Avto.pro only embeds a short showcase (~20 tiles) on ``/seller/{slug}/`` —
    this is not the full inventory.  Each card links to a ``/part-`` page that
    :func:`parse_part_page` can enrich for OE candidates.
    """

    title: str | None
    article: str
    brand: str | None
    price_raw: str | None
    path: str
    url: str
    category_id: str | None = None
    brand_id: str | None = None


@dataclass(frozen=True, slots=True)
class SellerProfile:
    seller_slug: str
    display_name: str | None
    page_title: str | None
    product_refs: tuple[ProductRef, ...]
    product_groups: tuple[str, ...]
    page_kind: PageKind
    extraction_status: ExtractionStatus
    content_sha256: str
    showcase_cards: tuple[SellerShowcaseCard, ...] = ()
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    registration_date: str | None = None
    working_hours: tuple[str, ...] = ()
    product_groups_count: int | None = None


@dataclass(frozen=True, slots=True)
class ExtractedNumber:
    raw: str
    normalized: str
    source_field: str  # brand | article | oe | mpn | analog | unknown
    brand_raw: str | None = None


@dataclass(frozen=True, slots=True)
class ProductCardExtract:
    page_kind: PageKind
    extraction_status: ExtractionStatus
    content_sha256: str
    title: str | None = None
    brand_raw: str | None = None
    article_raw: str | None = None
    oe_raw: str | None = None
    mpn_raw: str | None = None
    product_id: str | None = None
    numbers: tuple[ExtractedNumber, ...] = ()
    seller_slug: str | None = None
    crossgroup_id: str | None = None
    is_original_brand: bool | None = None


def _strip_html(value: str) -> str:
    text = _TAG_RE.sub(" ", unescape(value))
    return _WS_RE.sub(" ", text).strip()


def content_sha256(body: str | bytes) -> str:
    raw = body if isinstance(body, bytes) else body.encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AvtoProConfigError(f"{name} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AvtoProConfigError(f"{name} must be a positive integer")
    return value


def load_avto_pro_tokens(path: str | Path) -> AvtoProTokensConfig:
    """Load and hash Avto.pro extract config."""

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise AvtoProConfigError(f"Token config does not exist: {source_path}")
    raw = source_path.read_bytes()
    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise AvtoProConfigError("Token config is not valid YAML") from exc
    if not isinstance(payload, dict):
        raise AvtoProConfigError("Token config root must be a mapping")
    if payload.get("schema_version") != AVTO_PRO_TOKENS_SCHEMA_VERSION:
        raise AvtoProConfigError(
            f"Unsupported token config schema: {payload.get('schema_version')!r}"
        )

    seller = payload.get("seller_profile") or {}
    if not isinstance(seller, dict):
        raise AvtoProConfigError("seller_profile must be a mapping")
    product = payload.get("product_card") or {}
    if not isinstance(product, dict):
        raise AvtoProConfigError("product_card must be a mapping")
    labels_raw = product.get("field_labels") or {}
    if not isinstance(labels_raw, dict) or not labels_raw:
        raise AvtoProConfigError("product_card.field_labels must be a non-empty mapping")
    field_labels: dict[str, tuple[str, ...]] = {}
    for key, values in labels_raw.items():
        if not isinstance(values, list) or not values:
            raise AvtoProConfigError(f"field_labels.{key} must be a non-empty list")
        field_labels[str(key)] = tuple(str(v).strip() for v in values if str(v).strip())

    waf = payload.get("waf") or {}
    if not isinstance(waf, dict):
        raise AvtoProConfigError("waf must be a mapping")
    title_markers = tuple(str(v) for v in (waf.get("title_markers") or []) if str(v).strip())
    body_markers = tuple(str(v) for v in (waf.get("body_markers") or []) if str(v).strip())
    if not title_markers and not body_markers:
        raise AvtoProConfigError("waf markers must not be empty")

    limits = payload.get("limits") or {}
    if not isinstance(limits, dict):
        raise AvtoProConfigError("limits must be a mapping")
    min_len = _positive_int(limits.get("min_number_length"), "min_number_length")
    max_len = _positive_int(limits.get("max_number_length"), "max_number_length")
    if min_len > max_len:
        raise AvtoProConfigError("min_number_length must not exceed max_number_length")

    href_pat = _text(
        seller.get("product_href_pattern")
        or r'/catalog/[^"\s>]+-m(\d+)/?',
        "product_href_pattern",
    )
    try:
        product_href_pattern = re.compile(href_pat, re.I)
    except re.error as exc:
        raise AvtoProConfigError("product_href_pattern is not valid regex") from exc

    part_page = payload.get("part_page") or {}
    if part_page is not None and not isinstance(part_page, dict):
        raise AvtoProConfigError("part_page must be a mapping when present")
    part_page = part_page if isinstance(part_page, dict) else {}
    original_section_id = str(
        part_page.get("original_section_id") or "original-manufacturers"
    ).strip()
    analog_section_id = str(
        part_page.get("analog_section_id") or "analog-parts"
    ).strip()
    filter_by_oem_brand = bool(part_page.get("filter_by_oem_brand", True))
    oem_brands_raw = part_page.get("oem_brands") or []
    if not isinstance(oem_brands_raw, list):
        raise AvtoProConfigError("part_page.oem_brands must be a list")
    oem_brands = frozenset(
        _fold_brand(str(v)) for v in oem_brands_raw if str(v).strip()
    )
    aliases_raw = part_page.get("oem_brand_aliases") or {}
    if not isinstance(aliases_raw, dict):
        raise AvtoProConfigError("part_page.oem_brand_aliases must be a mapping")
    oem_brand_aliases = MappingProxyType(
        {
            _fold_brand(str(k)): _fold_brand(str(v))
            for k, v in aliases_raw.items()
            if str(k).strip() and str(v).strip()
        }
    )
    noise_raw = part_page.get("noise_code_substrings") or []
    if not isinstance(noise_raw, list):
        raise AvtoProConfigError("part_page.noise_code_substrings must be a list")
    noise_code_substrings = tuple(
        str(v).strip().upper() for v in noise_raw if str(v).strip()
    )

    return AvtoProTokensConfig(
        method_version=_text(payload.get("method_version"), "method_version"),
        source_key=_text(payload.get("source_key"), "source_key"),
        default_seller_slug=_text(
            payload.get("default_seller_slug"), "default_seller_slug"
        ),
        base_url=_text(payload.get("base_url") or DEFAULT_BASE_URL, "base_url").rstrip(
            "/"
        ),
        product_href_pattern=product_href_pattern,
        field_labels=field_labels,
        waf_title_markers=title_markers,
        waf_body_markers=body_markers,
        min_number_length=min_len,
        max_number_length=max_len,
        original_section_id=original_section_id,
        analog_section_id=analog_section_id,
        filter_by_oem_brand=filter_by_oem_brand,
        oem_brands=oem_brands,
        oem_brand_aliases=oem_brand_aliases,
        noise_code_substrings=noise_code_substrings,
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _fold_brand(value: str) -> str:
    """Fold a brand for OEM-list membership (case/spacing/NFKC only)."""

    folded = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"\s+", " ", folded)


def resolve_oem_brand_key(brand: str, config: AvtoProTokensConfig) -> str:
    """Map a displayed brand onto the config OEM key space."""

    key = _fold_brand(brand)
    return config.oem_brand_aliases.get(key, key)


def is_oem_brand(brand: str | None, config: AvtoProTokensConfig) -> bool:
    if not brand or not brand.strip():
        return False
    return resolve_oem_brand_key(brand, config) in config.oem_brands


def _is_noise_code(code: str, config: AvtoProTokensConfig) -> bool:
    upper = code.upper()
    return any(marker in upper for marker in config.noise_code_substrings)


def is_waf_challenge(html: str, config: AvtoProTokensConfig) -> bool:
    """Return True when the body is an Azure WAF interstitial, not a product page."""

    if not html or not html.strip():
        return False
    title_match = _TITLE_TAG_RE.search(html)
    title = _strip_html(title_match.group("title")) if title_match else ""
    for marker in config.waf_title_markers:
        if marker.casefold() in title.casefold():
            return True
    head = html[:4000]
    for marker in config.waf_body_markers:
        if marker.casefold() in head.casefold():
            return True
    return False


def classify_page_kind(html: str, config: AvtoProTokensConfig, *, url: str | None = None) -> PageKind:
    if is_waf_challenge(html, config):
        return PageKind.WAF
    path = urlparse(url or "").path if url else ""
    if path.startswith("/part-") or _PART_PATH_RE.search(path):
        return PageKind.PART_PAGE
    # Live /part- bodies without a URL: original-manufacturers section is unique
    # to part cross pages (vehicle catalog pages do not carry it).
    if f'id="{config.original_section_id}"' in html:
        return PageKind.PART_PAGE
    if "part-page" in html[:5000] and 'id="js-search-context"' in html:
        return PageKind.PART_PAGE
    if "/seller/" in path or 'class="seller-page"' in html or "seller-page" in html[:5000]:
        if _HREF_RE.search(html) or "seller-page" in html:
            return PageKind.SELLER_PROFILE
    if "product-page" in html or "product-attr" in html or path.startswith("/catalog/"):
        return PageKind.PRODUCT_CARD
    if "/parts/" in path:
        return PageKind.LISTING
    if _HREF_RE.search(html) and "OPTKiev" in html:
        return PageKind.SELLER_PROFILE
    return PageKind.UNKNOWN


def _absolute_url(base_url: str, href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin(base_url + "/", href.lstrip("/"))


def _product_id_from_path(path: str) -> str | None:
    match = _PRODUCT_ID_RE.search(path.rstrip("/") + "/")
    if not match:
        match = re.search(r"-m(\d+)/?$", path, re.I)
    return match.group(1) if match else None


def parse_seller_showcase_cards(
    html: str,
    config: AvtoProTokensConfig,
) -> tuple[SellerShowcaseCard, ...]:
    """Extract carousel product tiles from a seller profile HTML body.

    Prefer ``data-part-number`` / ``data-href`` on ``article.embla__slide`` over
    free-floating ``/part-`` anchors (those can appear in SEO blocks too).
    """

    cards: list[SellerShowcaseCard] = []
    seen: set[str] = set()
    for match in _SHOWCASE_SLIDE_RE.finditer(html):
        attrs = {m.group("name").lower(): m.group("value") for m in _ATTR_RE.finditer(match.group("attrs"))}
        href = attrs.get("data-href") or ""
        article = (attrs.get("data-part-number") or "").strip()
        body = match.group("body")
        brand = None
        brand_match = _CARD_BRAND_RE.search(body)
        if brand_match:
            brand = _strip_html(brand_match.group("brand")) or None
            if not article:
                article = _strip_html(brand_match.group("code")) or ""
        if not href:
            href_match = _PART_HREF_RE.search(body)
            if href_match:
                href = href_match.group("href")
        if not article and href:
            parsed = _parse_part_href(href)
            if parsed:
                article, brand_from_url, _pid = parsed
                if not brand:
                    brand = brand_from_url.replace("_", " ")
        if not article:
            continue
        path = urlparse(href).path if href.startswith("http") else href
        if not path.startswith("/"):
            path = f"/{path}" if path else ""
        if not path and article:
            # reconstruct when only data-part-number is present
            brand_slug = (brand or "UNKNOWN").replace(" ", "_")
            path = f"/part-{article}-{brand_slug}-0/"
        url = _absolute_url(config.base_url, path or href)
        dedupe_key = f"{article.casefold()}|{(brand or '').casefold()}|{path}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        name_match = _CARD_NAME_RE.search(body)
        title = _strip_html(name_match.group("name")) if name_match else None
        price_match = _CARD_PRICE_RE.search(body)
        price_raw = _strip_html(price_match.group("price")) if price_match else None
        cards.append(
            SellerShowcaseCard(
                title=title or None,
                article=article,
                brand=brand,
                price_raw=price_raw,
                path=path,
                url=url,
                category_id=(attrs.get("data-category-id") or None) or None,
                brand_id=(attrs.get("data-brand-id") or None) or None,
            )
        )
    return tuple(cards)


def _parse_seller_contacts(html: str) -> dict[str, Any]:
    """Pull contact / meta fields off the seller profile (best-effort)."""

    email = None
    phone = None
    for match in _DATA_QA_RE.finditer(html):
        qa = match.group("qa").lower()
        value = _strip_html(match.group("body"))
        if qa == "email" and value and "@" in value:
            email = value
        elif qa == "phone" and value:
            # body may be empty when the number sits in a nested span
            phone = value or phone
    if not phone:
        phone_match = _PHONE_TEXT_RE.search(html)
        if phone_match:
            phone = _strip_html(phone_match.group("phone"))
    if phone:
        # HTML entities like &#x2B;380... already unescaped by _strip_html? 
        # unescape happens in _strip_html via unescape()
        phone = phone.replace(" ", "")
        if not phone.startswith("+") and phone.startswith("380"):
            phone = f"+{phone}"

    registration_date = None
    reg = _REG_DATE_RE.search(html)
    if reg:
        registration_date = reg.group("date").strip()
    else:
        # fixture-style: Зарегистрирован</span><span>20 июля 2015
        reg2 = re.search(
            r"Зарегистрирован\s*</[^>]+>\s*<[^>]+>\s*(?P<date>[^<]{4,40})",
            html,
            re.I | re.S,
        )
        if reg2:
            registration_date = reg2.group("date").strip()

    location = None
    loc = _LOCATION_RE.search(html)
    if loc:
        location = f"Украина, {loc.group('city')}"

    hours: list[str] = []
    for hm in _WORK_TIME_SPAN_RE.finditer(html):
        day = _strip_html(hm.group("day"))
        span = _strip_html(hm.group("hours"))
        if day and span:
            line = f"{day}: {span}"
            if line not in hours:
                hours.append(line)
    if not hours:
        for hm in _HOURS_LINE_RE.finditer(html):
            line = _WS_RE.sub(" ", hm.group("line")).strip()
            if line and line not in hours and len(line) >= 4:
                hours.append(line)
        for weekend in re.finditer(
            r"(Сб\s*-\s*Вс\s*:\s*[^<\n]{2,30})", html, re.I
        ):
            line = _WS_RE.sub(" ", weekend.group(1)).strip()
            if line not in hours:
                hours.append(line)

    product_groups_count = None
    cg = _PRODUCT_GROUPS_COUNT_RE.search(html)
    if cg:
        product_groups_count = int(cg.group("count"))
    else:
        # Live OPTKiev: label, then pro-stock-block__head__stat__count span.
        count_span = re.search(
            r"Товарн(?:ые|і)\s+групп\w*[\s\S]{0,400}?"
            r'pro-stock-block__head__stat__count[^>]*>\s*(?P<count>\d{1,4})\s*<',
            html,
            re.I,
        )
        if count_span:
            product_groups_count = int(count_span.group("count"))
        else:
            loose = re.search(
                r"Товарн(?:ые|і)\s+групп\w*[\s\S]{0,400}?(?P<count>\d{1,4})",
                html,
                re.I,
            )
            if loose:
                product_groups_count = int(loose.group("count"))

    return {
        "email": email,
        "phone": phone,
        "location": location,
        "registration_date": registration_date,
        "working_hours": tuple(hours),
        "product_groups_count": product_groups_count,
    }


def parse_seller_profile(
    html: str,
    config: AvtoProTokensConfig,
    *,
    seller_slug: str | None = None,
) -> SellerProfile:
    """Extract contacts, showcase cards, and catalog seed URLs from a seller page."""

    slug = (seller_slug or config.default_seller_slug).strip()
    digest = content_sha256(html)
    if not html.strip():
        return SellerProfile(
            seller_slug=slug,
            display_name=None,
            page_title=None,
            product_refs=(),
            product_groups=(),
            page_kind=PageKind.UNKNOWN,
            extraction_status=ExtractionStatus.EMPTY,
            content_sha256=digest,
        )

    kind = classify_page_kind(html, config, url=f"{config.base_url}/seller/{slug}/")
    if kind is PageKind.WAF:
        return SellerProfile(
            seller_slug=slug,
            display_name=None,
            page_title=None,
            product_refs=(),
            product_groups=(),
            page_kind=PageKind.WAF,
            extraction_status=ExtractionStatus.WAF,
            content_sha256=digest,
        )

    title_match = _TITLE_TAG_RE.search(html)
    page_title = _strip_html(title_match.group("title")) if title_match else None
    h1_match = _H1_RE.search(html)
    display_name = None
    if h1_match:
        display_name = (h1_match.group("title") or "").strip() or _strip_html(
            h1_match.group("body")
        )

    contacts = _parse_seller_contacts(html)
    showcase = parse_seller_showcase_cards(html, config)

    refs: list[ProductRef] = []
    seen: set[str] = set()
    for match in _HREF_RE.finditer(html):
        href = match.group("href")
        path = urlparse(href).path if href.startswith("http") else href
        product_id = _product_id_from_path(path)
        if not product_id or product_id in seen:
            continue
        if config.product_href_pattern.search(path) is None and not _PRODUCT_ID_RE.search(
            path
        ):
            continue
        seen.add(product_id)
        # optional title from surrounding title= or anchor text — best-effort
        start = max(0, match.start() - 120)
        window = html[start : match.end() + 200]
        title_attr = re.search(r'title="([^"]+)"', window)
        anchor_text = re.search(
            r">\s*([^<>]{3,120}?)\s*</a>", window[match.end() - match.start() :], re.S
        )
        title = None
        if title_attr:
            title = title_attr.group(1).strip()
        elif anchor_text:
            title = _WS_RE.sub(" ", anchor_text.group(1)).strip() or None
        refs.append(
            ProductRef(
                product_id=product_id,
                path=path if path.startswith("/") else f"/{path}",
                url=_absolute_url(config.base_url, href),
                title=title,
            )
        )

    groups: list[str] = []
    for group_match in re.finditer(
        r'avtotovary/[^"]+"[^>]*title="([^"]+)"', html, re.I
    ):
        groups.append(group_match.group(1).strip())
    # fixture-style group anchors
    for group_match in re.finditer(
        r'href="https?://avto\.pro/avtotovary/[^"]+"[^>]*title="([^"]+)"', html, re.I
    ):
        value = group_match.group(1).strip()
        if value and value not in groups:
            groups.append(value)

    status = (
        ExtractionStatus.OK
        if refs or showcase
        else ExtractionStatus.PARTIAL
        if display_name or page_title or contacts.get("email")
        else ExtractionStatus.NO_NUMBERS
    )
    return SellerProfile(
        seller_slug=slug,
        display_name=display_name or None,
        page_title=page_title,
        product_refs=tuple(refs),
        product_groups=tuple(groups),
        page_kind=PageKind.SELLER_PROFILE if kind is not PageKind.UNKNOWN else kind,
        extraction_status=status,
        content_sha256=digest,
        showcase_cards=showcase,
        email=contacts.get("email"),
        phone=contacts.get("phone"),
        location=contacts.get("location"),
        registration_date=contacts.get("registration_date"),
        working_hours=contacts.get("working_hours") or (),
        product_groups_count=contacts.get("product_groups_count"),
    )


def seller_profile_to_dict(profile: SellerProfile) -> dict[str, Any]:
    """JSON-ready dump of a seller profile (showcase cards + contacts)."""

    return {
        "seller_info": {
            "seller_slug": profile.seller_slug,
            "title": profile.display_name or "",
            "registration_date": profile.registration_date or "",
            "email": profile.email or "",
            "phone": profile.phone or "",
            "location": profile.location or "",
            "working_hours": list(profile.working_hours),
            "product_groups_count": profile.product_groups_count or 0,
            "page_title": profile.page_title or "",
            "content_sha256": profile.content_sha256,
            "extraction_status": profile.extraction_status.value,
        },
        "product_groups": list(profile.product_groups),
        "catalog_seeds": [
            {
                "product_id": ref.product_id,
                "title": ref.title or "",
                "url": ref.url,
                "path": ref.path,
            }
            for ref in profile.product_refs
        ],
        "cards_count": len(profile.showcase_cards),
        "cards": [
            {
                "title": card.title or "",
                "article": card.article,
                "brand": card.brand or "",
                "price": card.price_raw or "",
                "url": card.url,
                "path": card.path,
                "category_id": card.category_id or "",
                "brand_id": card.brand_id or "",
            }
            for card in profile.showcase_cards
        ],
        "note": (
            "Showcase carousel only (~20 tiles on /seller/{slug}/). "
            "Not the full OPTKiev inventory. Follow card.url with parse_part_page for OE."
        ),
    }


def _label_to_field(label: str, config: AvtoProTokensConfig) -> str | None:
    normalized = _WS_RE.sub(" ", label).strip().casefold()
    for field_name, aliases in config.field_labels.items():
        for alias in aliases:
            if normalized == alias.casefold():
                return field_name
    return None


def _split_numbers(value: str, config: AvtoProTokensConfig) -> tuple[str, ...]:
    parts: list[str] = []
    for piece in re.split(r"[,;|+]", value):
        piece = piece.strip()
        if not piece:
            continue
        for token in _NUMBER_TOKEN_RE.findall(piece):
            token = token.strip(".-_/ ")
            if not token:
                continue
            if len(token) < config.min_number_length or len(token) > config.max_number_length:
                continue
            parts.append(token)
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        key = part.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(part)
    return tuple(out)


def _section_body(html: str, section_id: str) -> str | None:
    if not section_id:
        return None
    pattern = re.compile(
        _SECTION_RE_TMPL.format(section_id=re.escape(section_id)),
        re.I | re.S,
    )
    match = pattern.search(html)
    return match.group("body") if match else None


def _parse_part_href(href: str) -> tuple[str, str, str] | None:
    """Return (code, brand, id) from a /part-CODE-BRAND-ID/ path."""

    path = urlparse(href).path if href.startswith("http") else href
    path = unquote(path)
    match = _PART_PATH_RE.search(path)
    if not match:
        return None
    code = match.group("code").strip()
    brand = match.group("brand").strip()
    part_id = match.group("id").strip()
    if not code or not brand:
        return None
    return code, brand, part_id


def _part_links_in(html_fragment: str) -> list[tuple[str, str, str]]:
    """Unique (code, brand, id) from /part- hrefs inside a fragment, order preserved."""

    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _PART_HREF_RE.finditer(html_fragment):
        parsed = _parse_part_href(match.group("href"))
        if not parsed:
            continue
        code, brand, part_id = parsed
        key = (code.casefold(), brand.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append((code, brand, part_id))
    return out


@dataclass(frozen=True, slots=True)
class TileCensus:
    """How much cross markup a page carries, before any filtering.

    :func:`parse_part_page` reports what it understood.  A harvest also needs to
    know what was there to understand, because the two silent redesigns look
    identical downstream: a renamed section id makes both sections vanish, and a
    changed tile link format empties sections that are still found.  Either one
    turns into "avto.pro knows no OE for these parts" unless someone counts.
    """

    sections_present: int
    tiles_in_sections: int
    #: Raw ``/part-`` occurrences anywhere in the markup.  Deliberately counted
    #: by substring rather than by :data:`_PART_HREF_RE`: a census that shares
    #: the parser's regex cannot notice the parser's regex going stale, which is
    #: half of what it is for.
    part_paths_in_markup: int


def census_part_tiles(html: str, config: AvtoProTokensConfig) -> TileCensus:
    """Count cross tiles without applying the brand or noise filters."""

    bodies = [
        body
        for body in (
            _section_body(html, config.original_section_id),
            _section_body(html, config.analog_section_id),
        )
        if body
    ]
    return TileCensus(
        sections_present=len(bodies),
        tiles_in_sections=sum(len(_part_links_in(body)) for body in bodies),
        part_paths_in_markup=html.count("/part-"),
    )


def _load_js_search_context(html: str) -> dict[str, Any] | None:
    match = _JS_SEARCH_CONTEXT_RE.search(html)
    if not match:
        return None
    body = match.group("body").strip()
    if not body:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_part_page(
    html: str,
    config: AvtoProTokensConfig,
    *,
    url: str | None = None,
) -> ProductCardExtract:
    """Extract self identity + OE candidates from a ``/part-`` page.

    OE candidates are taken only from ``#original-manufacturers`` (Avto's
    "original manufacturer substitutes" tiles).  Aftermarket analogues stay
    under ``source_field=analog`` for audit and are never mixed into ``oe_raw``.

    Nothing here promotes identity to ``OE_CONFIRMED`` — harvest only.
    """

    digest = content_sha256(html)
    if not html.strip():
        return ProductCardExtract(
            page_kind=PageKind.UNKNOWN,
            extraction_status=ExtractionStatus.EMPTY,
            content_sha256=digest,
        )
    if is_waf_challenge(html, config):
        return ProductCardExtract(
            page_kind=PageKind.WAF,
            extraction_status=ExtractionStatus.WAF,
            content_sha256=digest,
        )

    title = None
    h1 = _H1_RE.search(html)
    if h1:
        title = (h1.group("title") or "").strip() or _strip_html(h1.group("body"))
    if not title:
        t = _TITLE_TAG_RE.search(html)
        if t:
            title = _strip_html(t.group("title"))

    brand_raw: str | None = None
    article_raw: str | None = None
    crossgroup_id: str | None = None
    is_original_brand: bool | None = None
    ctx = _load_js_search_context(html)
    if ctx:
        brand_val = ctx.get("BrandName")
        if isinstance(brand_val, str) and brand_val.strip():
            brand_raw = brand_val.strip()
        part_num = ctx.get("PartNumber")
        if isinstance(part_num, str) and part_num.strip():
            article_raw = part_num.strip()
        cg = ctx.get("ResultCrossgroupId") or ctx.get("CrossgroupId")
        if cg is not None and str(cg).strip() and str(cg) not in {"0", "None"}:
            crossgroup_id = str(cg)
        part_obj = ctx.get("Part")
        if isinstance(part_obj, dict):
            if not article_raw:
                for key in ("FullNr", "ShortNr"):
                    val = part_obj.get(key)
                    if isinstance(val, str) and val.strip():
                        article_raw = val.strip()
                        break
            brand_obj = part_obj.get("Brand")
            if isinstance(brand_obj, dict):
                if not brand_raw:
                    for key in ("Path", "Name", "ViewName"):
                        val = brand_obj.get(key)
                        if isinstance(val, str) and val.strip():
                            brand_raw = val.strip()
                            break
                if isinstance(brand_obj.get("IsOriginal"), bool):
                    is_original_brand = brand_obj["IsOriginal"]
            if crossgroup_id is None and part_obj.get("CrossgroupId") not in (None, 0, "0"):
                crossgroup_id = str(part_obj.get("CrossgroupId"))

    # URL fallback for self code/brand/id when JSON is missing
    product_id: str | None = None
    if url:
        parsed_self = _parse_part_href(urlparse(url).path)
        if parsed_self:
            code, brand, part_id = parsed_self
            product_id = part_id
            if not article_raw:
                article_raw = code
            if not brand_raw:
                brand_raw = brand

    seller_slug = None
    seller_match = re.search(
        r'href="[^"]*/seller/(?P<slug>[a-z0-9_-]+)/?"', html, re.I
    )
    if seller_match:
        seller_slug = seller_match.group("slug")

    numbers: list[ExtractedNumber] = []
    seen_norms: set[str] = set()

    # Self article as mpn/article evidence (aftermarket private brand is common).
    if article_raw:
        for token in _split_numbers(article_raw, config):
            if _is_noise_code(token, config):
                continue
            normalized = normalize_cross_oem(token)
            if not normalized or normalized in seen_norms:
                continue
            seen_norms.add(normalized)
            numbers.append(
                ExtractedNumber(
                    raw=token,
                    normalized=normalized,
                    source_field="article",
                    brand_raw=brand_raw,
                )
            )

    original_body = _section_body(html, config.original_section_id)
    oe_raw_parts: list[str] = []
    if original_body:
        for code, brand, _part_id in _part_links_in(original_body):
            if _is_noise_code(code, config):
                continue
            if len(code) < config.min_number_length or len(code) > config.max_number_length:
                continue
            if config.filter_by_oem_brand and not is_oem_brand(brand, config):
                continue
            # Drop the self article when it reappears under an OEM brand tile.
            normalized = normalize_cross_oem(code)
            if not normalized:
                continue
            if article_raw and normalized == normalize_cross_oem(article_raw):
                continue
            if normalized in seen_norms:
                continue
            seen_norms.add(normalized)
            oe_raw_parts.append(code)
            numbers.append(
                ExtractedNumber(
                    raw=code,
                    normalized=normalized,
                    source_field="oe",
                    brand_raw=brand,
                )
            )

    analog_body = _section_body(html, config.analog_section_id)
    if analog_body:
        for code, brand, _part_id in _part_links_in(analog_body):
            if _is_noise_code(code, config):
                continue
            if len(code) < config.min_number_length or len(code) > config.max_number_length:
                continue
            # Analogues are aftermarket crosses — keep for audit, not OE.
            if config.filter_by_oem_brand and is_oem_brand(brand, config):
                # Rare: OEM brand in analog list still counts as OE candidate.
                normalized = normalize_cross_oem(code)
                if not normalized or normalized in seen_norms:
                    continue
                if article_raw and normalized == normalize_cross_oem(article_raw):
                    continue
                seen_norms.add(normalized)
                oe_raw_parts.append(code)
                numbers.append(
                    ExtractedNumber(
                        raw=code,
                        normalized=normalized,
                        source_field="oe",
                        brand_raw=brand,
                    )
                )
                continue
            normalized = normalize_cross_oem(code)
            if not normalized or normalized in seen_norms:
                continue
            seen_norms.add(normalized)
            numbers.append(
                ExtractedNumber(
                    raw=code,
                    normalized=normalized,
                    source_field="analog",
                    brand_raw=brand,
                )
            )

    oe_raw = ", ".join(oe_raw_parts) if oe_raw_parts else None
    oe_count = sum(1 for n in numbers if n.source_field == "oe")
    if oe_count:
        status = ExtractionStatus.OK
    elif brand_raw or article_raw or title:
        status = ExtractionStatus.PARTIAL
    else:
        status = ExtractionStatus.NO_NUMBERS

    return ProductCardExtract(
        page_kind=PageKind.PART_PAGE,
        extraction_status=status,
        content_sha256=digest,
        title=title,
        brand_raw=brand_raw,
        article_raw=article_raw,
        oe_raw=oe_raw,
        mpn_raw=article_raw if brand_raw and not is_original_brand else None,
        product_id=product_id,
        numbers=tuple(numbers),
        seller_slug=seller_slug,
        crossgroup_id=crossgroup_id,
        is_original_brand=is_original_brand,
    )


def parse_product_card(
    html: str,
    config: AvtoProTokensConfig,
    *,
    url: str | None = None,
) -> ProductCardExtract:
    """Extract labelled brand/article/OE/MPN from a product card body.

    Part pages are routed to :func:`parse_part_page` automatically.
    """

    kind = classify_page_kind(html, config, url=url)
    if kind is PageKind.PART_PAGE:
        return parse_part_page(html, config, url=url)

    digest = content_sha256(html)
    if not html.strip():
        return ProductCardExtract(
            page_kind=PageKind.UNKNOWN,
            extraction_status=ExtractionStatus.EMPTY,
            content_sha256=digest,
        )
    if is_waf_challenge(html, config):
        return ProductCardExtract(
            page_kind=PageKind.WAF,
            extraction_status=ExtractionStatus.WAF,
            content_sha256=digest,
        )

    title = None
    h1 = _H1_RE.search(html)
    if h1:
        title = (h1.group("title") or "").strip() or _strip_html(h1.group("body"))
    if not title:
        t = _TITLE_TAG_RE.search(html)
        if t:
            title = _strip_html(t.group("title"))

    fields: dict[str, str] = {}
    for match in _DT_DD_RE.finditer(html):
        label = _strip_html(match.group("label"))
        value = _strip_html(match.group("value"))
        field_name = _label_to_field(label, config)
        if field_name and value and field_name not in fields:
            fields[field_name] = value
    for match in _CLASS_FIELD_RE.finditer(html):
        field_name = match.group("field").lower()
        value = _strip_html(match.group("value"))
        if value and field_name not in fields:
            fields[field_name] = value

    seller_slug = None
    seller_match = re.search(
        r'href="[^"]*/seller/(?P<slug>[a-z0-9_-]+)/?"', html, re.I
    )
    if seller_match:
        seller_slug = seller_match.group("slug")

    product_id = None
    if url:
        product_id = _product_id_from_path(urlparse(url).path)

    numbers: list[ExtractedNumber] = []
    for field_name in ("oe", "article", "mpn"):
        raw_value = fields.get(field_name)
        if not raw_value:
            continue
        for token in _split_numbers(raw_value, config):
            normalized = normalize_cross_oem(token)
            if not normalized:
                continue
            numbers.append(
                ExtractedNumber(
                    raw=token,
                    normalized=normalized,
                    source_field=field_name,
                )
            )

    brand_raw = fields.get("brand")
    article_raw = fields.get("article")
    oe_raw = fields.get("oe")
    mpn_raw = fields.get("mpn")

    if numbers:
        status = ExtractionStatus.OK
    elif brand_raw or title or article_raw or oe_raw or mpn_raw:
        status = ExtractionStatus.PARTIAL
    else:
        status = ExtractionStatus.NO_NUMBERS

    return ProductCardExtract(
        page_kind=PageKind.PRODUCT_CARD,
        extraction_status=status,
        content_sha256=digest,
        title=title,
        brand_raw=brand_raw,
        article_raw=article_raw,
        oe_raw=oe_raw,
        mpn_raw=mpn_raw,
        product_id=product_id,
        numbers=tuple(numbers),
        seller_slug=seller_slug,
    )


def extraction_rows_for_csv(
    card: ProductCardExtract,
    *,
    seller_slug: str,
    product_url: str,
    query: str = "",
) -> list[dict[str, str]]:
    """Flatten a card into CSV-oriented row dicts (one per extracted number)."""

    base = {
        "query": query,
        "seller_slug": seller_slug,
        "product_id": card.product_id or "",
        "product_url": product_url,
        "title": card.title or "",
        "brand_raw": card.brand_raw or "",
        "article_raw": card.article_raw or "",
        "oe_raw": card.oe_raw or "",
        "mpn_raw": card.mpn_raw or "",
        "crossgroup_id": card.crossgroup_id or "",
        "page_kind": card.page_kind.value,
        "extraction_status": card.extraction_status.value,
        "content_sha256": card.content_sha256,
        "extraction_method": EXTRACTION_METHOD,
    }
    if not card.numbers:
        return [
            {
                **base,
                "number_raw": "",
                "number_norm": "",
                "source_field": "",
                "number_brand": "",
            }
        ]
    rows: list[dict[str, str]] = []
    for number in card.numbers:
        rows.append(
            {
                **base,
                "number_raw": number.raw,
                "number_norm": number.normalized,
                "source_field": number.source_field,
                "number_brand": number.brand_raw or "",
            }
        )
    return rows


__all__ = [
    "AVTO_PRO_TOKENS_SCHEMA_VERSION",
    "EXTRACTION_METHOD",
    "AvtoProConfigError",
    "AvtoProTokensConfig",
    "ExtractedNumber",
    "ExtractionStatus",
    "PageKind",
    "ProductCardExtract",
    "ProductRef",
    "SellerProfile",
    "TileCensus",
    "census_part_tiles",
    "classify_page_kind",
    "content_sha256",
    "extraction_rows_for_csv",
    "is_oem_brand",
    "is_waf_challenge",
    "load_avto_pro_tokens",
    "parse_part_page",
    "parse_product_card",
    "parse_seller_profile",
    "parse_seller_showcase_cards",
    "resolve_oem_brand_key",
    "seller_profile_to_dict",
    "SellerShowcaseCard",
]
