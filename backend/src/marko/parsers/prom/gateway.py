"""Orchestrates catalog scraping and cross-seller price comparison."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any, Iterator

from .config import BASE_URL, ScrapeConfig
from .exceptions import (
    ParseError,
    RequestFailed,
    is_canonical_pagination_redirect,
)
from marko.services.matching import (
    ComparisonParams,
    Offer,
    PriceComparison,
    build_comparison,
    build_product_comparison_evidence,
    build_search_query,
    normalize_tokens,
    normalize_oe,
    _price_value,
)
from marko.services.parser_models import (
    ListingPage,
    MotorsContext,
    Product,
    SeedInfo,
    Seller,
    extract_labelled_original_oe_evidence,
)
from marko.services.catalog_identity_safety import is_internal_catalog_code
from marko.services.source_access import SourceAccessBlocked
from metis.pricing.crosses import normalize_cross_oem

from .client import HttpClient
from .parser import (
    parse_listing,
    parse_motors_context,
    parse_oe_listing,
    parse_product_page,
    parse_search,
)

#: prom.ua returns thirty products per automotive listing page.
OE_OFFERS_PER_PAGE = 30
#: Recorded on a comparison whose candidates came from the marketplace's own
#: part-code listing rather than from a text search.
MOTORS_IDENTITY_SOURCE = "PROM_OE_PAGE"
# Stable normalized contract for one retained candidate product-card response.
PROM_PRODUCT_DETAIL_SCHEMA_VERSION = "prom-product-detail-evidence-v1"

_DETAIL_MERGE_FIELDS: tuple[str, ...] = (
    "sku",
    "mpn",
    "part_numbers",
    "measure_unit",
    "category_id",
    "category_ids",
    "category",
    "brand",
    "oe_raw",
    "fitment",
    "vehicle_generation",
    "year_from",
    "year_to",
    "engine",
    "body_variant",
    "side",
    "position",
    "condition",
    "package_quantity",
    "characteristics",
    "description",
)
_DETAIL_SOURCE_PATHS: dict[str, str] = {
    "sku": "$.result.product.sku",
    "mpn": "$.result.product.identifiers.mpn",
    "part_numbers": "$.result.product.attributes[*].values[*].value",
    "measure_unit": "$.result.product.measureUnit",
    "category_id": "$.result.product.categoryId",
    "category_ids": "$.result.product.categoryIds",
    "category": "$.result.product.category.caption",
    "brand": "$.result.product.manufacturerInfo.name",
    "oe_raw": "$.result.product.comparisonEvidence.oeRaw",
    "fitment": "$.result.product.comparisonEvidence.fitment",
    "vehicle_generation": "$.result.product.comparisonEvidence.vehicleGeneration",
    "year_from": "$.result.product.comparisonEvidence.yearFrom",
    "year_to": "$.result.product.comparisonEvidence.yearTo",
    "engine": "$.result.product.comparisonEvidence.engine",
    "body_variant": "$.result.product.comparisonEvidence.bodyVariant",
    "side": "$.result.product.comparisonEvidence.side",
    "position": "$.result.product.comparisonEvidence.position",
    "condition": "$.result.product.attributes[*].values[*].value",
    "package_quantity": "$.result.product.attributes[*].values[*].value",
    "characteristics": "$.result.product.attributes[*].values[*].value",
    "description": ("$.result.product.descriptionPlain|descriptionFull|description"),
}

log = logging.getLogger(__name__)

_PRODUCT_URL_RE = re.compile(
    r"prom\.ua/(?:(?P<lang>[a-z]{2})/)?p(?P<product_id>\d+)-(?P<word>[\w-]+)\.html",
    re.I,
)
_SHORT_NUMERIC_DETAIL_MAX_DIGITS = 6
_IDENTIFIER_LABEL_RE = re.compile(
    r"(?:\b(?:oe|oem|art|article|артикул|арт)\b|"
    r"\bpart\s+(?:no|number)\b|"
    r"\bкод\s+(?:запчасти|запчастини|виробника|производителя)\b|[#№])",
    re.IGNORECASE,
)
_IDENTIFIER_BOUNDARY_CHARS = r"A-Za-zА-Яа-яЇїІіЄєҐґ0-9"


def _motors_context_is_public(context: MotorsContext) -> bool:
    """Whether a Prom automotive grouping is safe to use as public identity.

    Prom's motors block is authoritative only for the public part-number
    namespace.  A customer's private KEMP shelf code can still leak into a
    card's normalized part code, especially on owned storefront pages.  Such a
    block may be useful for diagnostics, but it must not become the market
    cohort key or a source assertion for competitors.
    """

    values = (context.normalized_part_code, context.via_oe_number)
    return bool(
        context.has_oe_page
        and any(value and not is_internal_catalog_code(value) for value in values)
        and all(
            not value or not is_internal_catalog_code(value) for value in values
        )
    )


def _identity_token(value: object) -> str:
    return re.sub(r"[^0-9A-ZА-ЯІЇЄ]", "", str(value or "").upper())


def _product_identity(product: Product) -> tuple[str, str]:
    """Stable discovery identity even when Prom omits both id and URL."""

    if product.id is not None:
        return ("id", str(product.id))
    if product.url:
        return ("url", product.url)
    return (
        "fallback",
        "|".join(
            (
                product.name or "",
                product.sku or "",
                product.seller_name or "",
            )
        ),
    )


def _ambiguous_numeric_query(query: str) -> bool:
    token = _identity_token(query)
    return token.isdigit() and 4 <= len(token) <= 6


def _identifier_query_for_seed(query: str, seed: Product) -> str | None:
    """Return ``query`` as an identity only when it is code-shaped.

    ``PromGateway.compare`` also accepts a natural-language phrase.  Passing
    that phrase as ``search_number`` makes ``normalize_oe`` collapse words
    into one giant identifier and can incorrectly reject otherwise valid
    fuzzy retrieval rows with a native MPN.  Seed equality is authoritative;
    otherwise accept only a short code-shaped query (one alphanumeric token,
    grouped numeric/code tokens, or a short Cyrillic prefix plus digits).
    """

    raw = str(query or "").strip()
    wanted = normalize_oe(raw)
    if not wanted:
        return None
    if wanted in {
        normalized
        for value in (seed.oe_raw, seed.mpn)
        if (normalized := normalize_oe(value))
    }:
        return raw
    tokens = re.findall(r"[A-Za-zА-Яа-яЇїІіЄєҐґ0-9]+", raw)
    if not tokens or len(tokens) > 3 or len(wanted) > 32:
        return None
    if not any(character.isdigit() for character in raw):
        return None
    natural_words = [
        token
        for token in tokens
        if not any(character.isdigit() for character in token)
    ]
    if natural_words:
        # Latin words such as ``VW``, ``Toyota`` or ``KEMP`` are catalogue
        # context, not part-code fragments.  A short Cyrillic prefix (for
        # example ``КМ 533``) is retained because it is a known identifier
        # notation handled by the shared OEM normalizer.
        if any(
            any("A" <= character.upper() <= "Z" for character in token)
            for token in natural_words
        ):
            return None
        if len(natural_words) > 1 or any(len(token) > 3 for token in natural_words):
            return None
    return raw


def _title_contains_identity(title: str | None, wanted: str) -> bool:
    """Check a title identity with boundaries before ranking detail fetches."""

    if not title or not wanted:
        return False
    pieces = r"[\s./_-]*".join(re.escape(character) for character in wanted)
    pattern = re.compile(
        rf"(?<![{_IDENTIFIER_BOUNDARY_CHARS}]){pieces}"
        rf"(?![{_IDENTIFIER_BOUNDARY_CHARS}])",
        re.IGNORECASE,
    )
    if wanted.isdigit() and len(wanted) <= _SHORT_NUMERIC_DETAIL_MAX_DIGITS:
        for match in pattern.finditer(title):
            prefix = title[max(0, match.start() - 48) : match.start()]
            if _IDENTIFIER_LABEL_RE.search(prefix):
                return True
        return False
    return pattern.search(title) is not None


def _contextual_search_query(query: str, context: str | None) -> str | None:
    """Build a bounded retrieval phrase; the returned text is never OE proof."""

    if not context or not _ambiguous_numeric_query(query):
        return None
    query_token = _identity_token(query)
    selected: list[str] = []
    seen: set[str] = set()
    for token in normalize_tokens(context):
        identity = _identity_token(token)
        if not identity or identity == query_token or identity in seen:
            continue
        seen.add(identity)
        selected.append(token)
        if len(selected) == 6:
            break
    if not selected:
        return None
    return f"{query} {' '.join(selected)}"


def _detail_priority(
    product: Product,
    query: str,
    index: int,
    *,
    context: str | None = None,
) -> tuple[int, int, int, int]:
    """Prefer contextual code-bearing cards while preserving stable order."""

    wanted = _identity_token(query)
    if not wanted:
        return (0, 3, 0, index)
    # Explicitly labelled card codes are a third native namespace.  They are
    # not interchangeable with the seller SKU, but when one exactly equals
    # the query they are the best detail-fetch signal available on a listing
    # that did not expose MPN/OE.  Omitting them here spent the detail budget
    # on weaker title hits and left the strongest candidate evidence
    # unenriched.
    exact_fields = (
        _identity_token(product.sku),
        _identity_token(product.mpn),
        _identity_token(product.oe_raw),
        *(_identity_token(value) for value in product.part_numbers),
    )
    if wanted in exact_fields:
        identity_rank = 0
    else:
        identity_rank = 1 if _title_contains_identity(product.name, wanted) else 2
    if context and _ambiguous_numeric_query(query):
        context_tokens = set(normalize_tokens(context))
        product_tokens = set(normalize_tokens(product.name))
        overlap = len(context_tokens & product_tokens)
        context_rank = 0 if overlap else 1
        return (context_rank, identity_rank, -overlap, index)
    return (0, identity_rank, 0, index)


def _detail_metadata(
    product: Product,
    *,
    status: str,
    selected: bool,
    source_url: str | None = None,
    content_sha256: str | None = None,
    error_code: str | None = None,
    conflicts: dict[str, dict[str, Any]] | None = None,
    field_sources: dict[str, str] | None = None,
    motors: MotorsContext | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "schema_version": PROM_PRODUCT_DETAIL_SCHEMA_VERSION,
        "status": status,
        "selected": selected,
        "source_url": source_url or product.url,
        "content_sha256": content_sha256,
        "product_id": product.id,
        "seller_id": str(product.seller_id) if product.seller_id is not None else None,
        "error_code": error_code,
        "conflicts": conflicts or {},
        "field_sources": field_sources or {},
    }
    if motors is not None:
        metadata["motors"] = {
            "normalized_part_code": motors.normalized_part_code,
            "via_oe_number": motors.via_oe_number,
            "compatible_oe_numbers": list(motors.compatible_oe_numbers),
            "compatible_vehicles": [
                asdict(vehicle) for vehicle in motors.compatible_vehicles
            ],
            "part_group_id": motors.part_group_id,
            # The two fields the grouping URL is built from.  Dropping them
            # left the evidence unable to say which cross-seller listing this
            # card pointed at, and left every query-only position unable to
            # reach it at all.
            "oe_page_id": motors.oe_page_id,
            "oe_page_alias": motors.oe_page_alias,
        }
    owner_evidence: list[dict[str, Any]] = []
    captured_at = datetime.now(UTC).isoformat()
    for evidence in extract_labelled_original_oe_evidence(product.characteristics):
        normalized = normalize_cross_oem(evidence["raw"])
        if not normalized:
            continue
        owner_evidence.append(
            {
                **evidence,
                "normalized": normalized,
                "source_url": source_url or product.url,
                "content_sha256": content_sha256,
                "parser_version": PROM_PRODUCT_DETAIL_SCHEMA_VERSION,
                "bound": bool(source_url or product.url),
                "publisher": "kemp_owned_store",
                "source_version": PROM_PRODUCT_DETAIL_SCHEMA_VERSION,
                "captured_at": captured_at,
                "card_title": product.name,
                "card_brand": product.brand,
                "card_spec": {
                    "description": product.description,
                    "characteristics": product.characteristics,
                },
            }
        )
    if owner_evidence:
        metadata["owner_oe_evidence"] = owner_evidence
    return metadata


def _with_identity_origin(product: Product, origin: str) -> Product:
    """Record which retrieval route produced a candidate.

    Rows off the part-code listing are ordinary candidates — they earn their
    identity from their own evidence, not from having been grouped — but a
    measurement that cannot tell the two routes apart cannot say what the
    grouping is worth.
    """

    detail = product.detail_evidence
    if not isinstance(detail, dict):
        return product
    return replace(product, detail_evidence={**detail, "identity_origin": origin})


def _with_found_by_query(product: Product, query: str) -> Product:
    """Record which declared number retrieved a row.

    A row found by a cross must have its identity checked against that cross,
    not against the primary OE. Without this the two retrievals become one
    anonymous pile and the check silently uses the wrong number.
    """

    detail = product.detail_evidence
    if not isinstance(detail, dict):
        return product
    return replace(product, detail_evidence={**detail, "found_by_query": query})


def _independent_sellers(products: list[Product], *, owned: set[str]) -> int:
    """Distinct external sellers retrieved so far; ours are not a market."""

    return len(
        {
            seller
            for product in products
            if (seller := str(product.seller_id or "").strip())
            and seller not in owned
        }
    )


def _enriched_seller_ids(products: list[Product]) -> frozenset[str]:
    """Sellers whose card was already fetched, so the budget is not spent twice."""

    return frozenset(
        seller
        for product in products
        if isinstance(product.detail_evidence, dict)
        and product.detail_evidence.get("selected")
        and (seller := str(product.seller_id or "").strip())
    )


def _motors_from_detail(detail: Any) -> MotorsContext | None:
    """Rebuild the grouping pointer from retained detail evidence.

    Only the scalars the URL and the public-namespace check need are restored;
    the compatibility lists stay where they were captured.
    """

    if not isinstance(detail, dict):
        return None
    motors = detail.get("motors")
    if not isinstance(motors, dict):
        return None
    page_id = motors.get("oe_page_id")
    if not isinstance(page_id, int):
        return None
    return MotorsContext(
        normalized_part_code=motors.get("normalized_part_code"),
        part_group_id=motors.get("part_group_id"),
        oe_page_id=page_id,
        oe_page_alias=motors.get("oe_page_alias"),
        via_oe_number=motors.get("via_oe_number"),
    )


def _detail_identity_conflicts_with_comparison(
    comparison: PriceComparison,
    offer: Offer,
    product: Product,
) -> bool:
    """Return whether detail evidence disproves the retained listing.

    A search title can contain the requested code while the product-card
    payload exposes another manufacturer number.  Once the detail response is
    available, that structured disagreement is stronger than retrieval text:
    keeping the row as ``MANUAL_REVIEW`` would still leak a false competitor
    into the comparison surface.  The raw discovery path keeps the source
    card separately; the pricing/comparison path must fail closed.
    """

    detail = product.detail_evidence
    if isinstance(detail, dict):
        conflicts = detail.get("conflicts")
        if isinstance(conflicts, dict) and any(
            str(field).strip().casefold() in {"mpn", "oe_raw", "part_numbers"}
            for field in conflicts
        ):
            return True

    # A field absent on the listing may appear only after detail enrichment.
    # If the listing matched a searched identifier by title, validate the
    # newly available structured namespaces against that exact query.
    if comparison.source != "SEARCH" or offer.match.kind != "number":
        return False
    wanted = normalize_oe(comparison.query)
    if not wanted:
        return False
    native_values = tuple(
        normalized
        for raw in (product.mpn, product.oe_raw, *product.part_numbers)
        if (normalized := normalize_oe(raw))
    )
    # A listing may expose the searched code in one native namespace and a
    # legitimate cross/manufacturer code in the other (for example exact OE
    # plus an aftermarket MPN).  That is not a detail contradiction.  Reject
    # only when detail evidence has native identifiers but none equals the
    # searched code; the candidate then needs a different identity proof.
    if native_values and wanted not in native_values:
        return True
    return False


def _is_pagination_end(exc: RequestFailed, page_num: int) -> bool:
    """Tell "there is no such page" apart from "the fetch broke".

    Prom's reported result total can exceed what it actually serves — measured
    on 2026-07-26, query ``8E0121251L`` reported 67 but served 66 across three
    pages. The next page then answers ``301`` to the canonical search URL.
    Treating that as a failure discarded every product already collected, which
    cost 2 of 30 measured positions. A redirect on the first page is *not*
    covered here: with no page fetched there is nothing to salvage, and a moved
    or blocked endpoint must still surface as an error.
    """

    return is_canonical_pagination_redirect(
        status_code=exc.status_code,
        request_url=exc.request_url,
        redirect_location=exc.redirect_location,
        page_num=page_num,
    )


class PromGateway:
    """Access seller catalogs and comparable offers on prom.ua."""

    def __init__(self, config: ScrapeConfig | None = None) -> None:
        self._config = config or ScrapeConfig()

    def scrape(self, seller_url: str, *, strict: bool = False) -> Iterator[Product]:
        """Lazily yield unique seller products, page by page."""
        seller = Seller.from_url(seller_url)
        log.info(
            "Продавець: company_id=%s slug=%s lang=%s",
            seller.company_id,
            seller.slug,
            seller.lang,
        )

        seen_products: set[tuple[str, str]] = set()
        with HttpClient(self._config) as client:
            for page in self._iter_pages(client, seller, strict=strict):
                new_on_page = 0
                for product in page.products:
                    identity = _product_identity(product)
                    if identity in seen_products:
                        continue
                    seen_products.add(identity)
                    new_on_page += 1
                    if self._config.enrich_details:
                        product = self._fetch_candidate_detail(
                            client, product, lang=seller.lang
                        )
                    yield product
                if page.products and new_on_page == 0:
                    log.info("Нових товарів немає — зупиняюсь (кінець каталогу).")
                    break

        log.info("Готово. Унікальних товарів: %d", len(seen_products))

    def _iter_pages(
        self, client: HttpClient, seller: Seller, *, strict: bool = False
    ) -> Iterator[ListingPage]:
        page_num = self._config.start_page
        fetched = 0
        while True:
            if self._config.max_pages and fetched >= self._config.max_pages:
                log.info("Досягнуто max_pages=%d.", self._config.max_pages)
                return

            page = self._fetch_page(client, seller, page_num, strict=strict)
            if page is None:
                return
            if page.is_empty:
                log.info("Сторінка %d порожня — кінець.", page_num)
                return

            log.info(
                "Сторінка %d: %d товарів (total за сайтом: %s)",
                page_num,
                len(page.products),
                page.total,
            )
            yield page
            fetched += 1
            page_num += 1

    def _fetch_page(
        self,
        client: HttpClient,
        seller: Seller,
        page_num: int,
        *,
        strict: bool = False,
    ) -> ListingPage | None:
        params = {"page": page_num} if page_num > 1 else None
        try:
            return client.get_parsed(
                seller.listing_url,
                lambda html: parse_listing(html, seller.lang),
                params=params,
            )
        except RequestFailed as exc:
            if _is_pagination_end(exc, page_num):
                log.info(
                    "Сторінка %d відсутня (HTTP %s) — кінець лістингу.",
                    page_num,
                    exc.status_code,
                )
                return None
            log.error("Сторінку %d не завантажено: %s", page_num, exc)
            if strict:
                raise
            return None
        except ParseError as exc:
            log.error("Сторінку %d не розібрано: %s", page_num, exc)
            if strict:
                raise
            return None

    # -- Cross-seller price comparison --

    def search(
        self,
        query: str,
        *,
        lang: str = "ua",
        strict: bool = False,
    ) -> Iterator[Product]:
        """Yield raw Prom search results without inventing comparability.

        This is an extraction-boundary operation for discovery/replay.  It
        deliberately does not call ``build_comparison`` and therefore cannot
        by itself authorize a price recommendation.
        """

        normalized_query = query.strip()
        normalized_lang = lang.strip().casefold()
        if not normalized_query:
            raise ValueError("Prom search query must not be empty")
        if is_internal_catalog_code(normalized_query):
            raise ValueError(
                "Prom public search requires a public OE/MPN; "
                "private KEMP catalog codes are join keys only"
            )
        if not re.fullmatch(r"[a-z]{2}", normalized_lang):
            raise ValueError(f"Unsupported Prom language: {lang!r}")
        with HttpClient(self._config) as client:
            yield from self._collect_candidates(
                client,
                normalized_query,
                normalized_lang,
                strict=strict,
            )

    def search_enriched(
        self,
        query: str,
        *,
        lang: str = "ua",
        strict: bool = False,
        excluded_seller_ids: frozenset[str] = frozenset(),
        context: str | None = None,
        fallback_queries: tuple[str, ...] = (),
        discovery_queries: tuple[str, ...] = (),
        min_independent_sellers: int = 0,
    ) -> list[Product]:
        """Run the exact query plus at most one bounded contextual retrieval.

        The second retrieval is allowed only for ambiguous 4-6 digit queries;
        its context never becomes identity evidence. Search results from both
        passes form the complete discovery set. At most
        ``max_sellers`` distinct external sellers receive a detail request;
        every other row carries an explicit ``NOT_SELECTED`` state.  A broken
        detail card never turns into an empty market and never discards the
        original listing candidate.
        """

        normalized_query = query.strip()
        normalized_lang = lang.strip().casefold()
        if not normalized_query:
            raise ValueError("Prom search query must not be empty")
        if is_internal_catalog_code(normalized_query):
            raise ValueError(
                "Prom public search requires a public OE/MPN; "
                "private KEMP catalog codes are join keys only"
            )
        if not re.fullmatch(r"[a-z]{2}", normalized_lang):
            raise ValueError(f"Unsupported Prom language: {lang!r}")
        with HttpClient(self._config) as client:
            products = list(
                self._collect_candidates(
                    client,
                    normalized_query,
                    normalized_lang,
                    strict=strict,
                )
            )
            contextual_query = _contextual_search_query(normalized_query, context)
            if contextual_query is not None:
                contextual = list(
                    self._collect_candidates(
                        client,
                        contextual_query,
                        normalized_lang,
                        strict=strict,
                    )
                )
                seen = {_product_identity(product) for product in products}
                for product in contextual:
                    identity = _product_identity(product)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    products.append(product)
            enriched = self._enrich_search_shortlist(
                client,
                products,
                query=normalized_query,
                lang=normalized_lang,
                excluded_seller_ids=excluded_seller_ids,
                context=context,
            )
            enriched = self._extend_via_oe_page(
                client,
                enriched,
                query=normalized_query,
                lang=normalized_lang,
                excluded_seller_ids=excluded_seller_ids,
                context=context,
            )
            widened = self._extend_via_declared_widenings(
                client,
                enriched,
                lang=normalized_lang,
                strict=strict,
                excluded_seller_ids=excluded_seller_ids,
                context=context,
                fallback_queries=fallback_queries,
                min_independent_sellers=min_independent_sellers,
            )
            # Retrieval-only keys go last. They assert no identity, so a row
            # they found can never price; spending them before the confirmed
            # crosses would fill the shortlist with rows the run is not
            # allowed to use and leave the permitted market unsearched.
            return self._extend_via_declared_widenings(
                client,
                widened,
                lang=normalized_lang,
                strict=strict,
                excluded_seller_ids=excluded_seller_ids,
                context=context,
                fallback_queries=discovery_queries,
                min_independent_sellers=min_independent_sellers,
            )

    def compare(
        self,
        seed_url: str,
        query: str | None = None,
        *,
        strict: bool = False,
        excluded_seller_ids: frozenset[str] = frozenset(),
    ) -> PriceComparison:
        """Compare a seed product against similar offers from other sellers."""
        # Catalog imports commonly retain seller-host URLs such as
        # ``kemp-cs2847093.prom.ua``. The marketplace can return an HTML shell
        # without a usable content type for those hosts, while the same card
        # is available at the canonical ``prom.ua`` URL. Normalize at the
        # gateway boundary so direct callers cannot silently turn a valid
        # product into an upstream ``UnsafeResponse``.
        try:
            from marko.services.scraper_contract import (
                ScraperBoundaryError,
                canonicalize_prom_product_url,
            )

            seed_url = canonicalize_prom_product_url(seed_url)
        except ScraperBoundaryError as exc:
            raise ValueError(str(exc)) from exc
        match = _PRODUCT_URL_RE.search(seed_url)
        if not match:
            raise ValueError(
                f"Не схоже на URL товару prom.ua: {seed_url!r}\n"
                "Очікую щось на кшталт https://prom.ua/ua/p1483068331-slug.html"
            )
        lang = (match.group("lang") or "ua").lower()

        with HttpClient(self._config) as client:
            seed, motors = self._fetch_seed_with_motors(client, seed_url, lang)
            if motors is not None and motors.has_oe_page and _motors_context_is_public(motors):
                comparison = self._compare_via_oe_page(
                    client, seed, motors, lang, excluded_seller_ids
                )
            else:
                # A caller may have passed a stale private shelf code even
                # when the seed card itself contains a usable public MPN/OE.
                # Never send that code to Prom; rebuild the query from the
                # seed's public namespaces instead.
                search_query = (
                    query
                    if query and not is_internal_catalog_code(query)
                    else build_search_query(seed.product)
                )
                log.info(
                    "Seed: %s | бренд=%s | model_id=%s | buyBox=%s продавців (%s–%s)",
                    seed.product.name,
                    seed.product.brand,
                    seed.product.model_id,
                    seed.seller_count,
                    seed.min_price,
                    seed.max_price,
                )
                log.info("Пошуковий запит: %r", search_query)

                candidates = self._collect_candidates(
                    client,
                    search_query,
                    lang,
                    strict=strict,
                )
                search_number = _identifier_query_for_seed(
                    search_query,
                    seed.product,
                )
                comparison = build_comparison(
                    seed,
                    candidates,
                    ComparisonParams(
                        query=search_query,
                        threshold=self._config.similarity_threshold,
                        max_sellers=self._config.max_sellers,
                        search_number=search_number,
                        excluded_seller_ids=excluded_seller_ids,
                    ),
                )
            comparison = self._enrich_comparison(client, comparison, lang=lang)

        log.info(
            "Порівняно продавців: %d (переглянуто кандидатів: %d)",
            len(comparison.offers),
            comparison.candidates_scanned,
        )
        return comparison

    def _extend_via_declared_widenings(
        self,
        client: HttpClient,
        products: list[Product],
        *,
        lang: str,
        strict: bool,
        excluded_seller_ids: frozenset[str],
        context: str | None,
        fallback_queries: tuple[str, ...],
        min_independent_sellers: int,
    ) -> list[Product]:
        """Search a declared cross number when the primary found too few sellers.

        The original vehicle OE stays the market identity, so a cross is tried
        only after it has done its work and come back thin, and only if the run
        froze that number into its acquisition input. One seller is not a
        market: a recommendation wants several independent ones, and the
        catalogue holds a confirmed cross for roughly a third of its rows.

        Each widened row records the number that retrieved it. Identity is then
        verified against that number rather than against the primary, which is
        the whole reason the two cannot be merged into one anonymous pile.
        """

        if not fallback_queries or min_independent_sellers <= 0:
            return products
        owned = {str(value).strip() for value in excluded_seller_ids}
        seen = {_product_identity(product) for product in products}
        for widening in fallback_queries:
            if _independent_sellers(products, owned=owned) >= min_independent_sellers:
                break
            extra: list[Product] = []
            for product in self._collect_candidates(
                client,
                widening,
                lang,
                strict=strict,
            ):
                identity = _product_identity(product)
                if identity in seen:
                    continue
                seen.add(identity)
                extra.append(product)
            if not extra:
                continue
            log.info("Розширення за кросом %s: +%d кандидатів", widening, len(extra))
            products = products + [
                _with_found_by_query(product, widening)
                for product in self._enrich_search_shortlist(
                    client,
                    extra,
                    query=widening,
                    lang=lang,
                    excluded_seller_ids=excluded_seller_ids,
                    context=context,
                    sellers_already_enriched=_enriched_seller_ids(products),
                )
            ]
        return products

    def _extend_via_oe_page(
        self,
        client: HttpClient,
        products: list[Product],
        *,
        query: str,
        lang: str,
        excluded_seller_ids: frozenset[str],
        context: str | None = None,
    ) -> list[Product]:
        """Read the marketplace's own grouping once a card exposes a public one.

        A search finds what the words happen to say; the part-code listing
        finds what prom.ua itself filed under the code.  Measured 2026-07-31
        over 28 identical OE numbers: 4 of 28 positions reached three retained
        sellers through search, 27 of 28 through the grouping.  ``compare``
        has taken this route since it was written, but only for a catalog item
        carrying a seed URL; a query-only position had no route to it at all.

        The grouping is entered only through a candidate's own card, so it
        costs no extra request when the search already found nothing worth
        enriching.  Its rows are ordinary candidates afterwards: identity is
        still proven from each row's own evidence, never from the fact that
        the marketplace grouped it.
        """

        motors = next(
            (
                found
                for product in products
                if (found := _motors_from_detail(product.detail_evidence)) is not None
                and _motors_context_is_public(found)
            ),
            None,
        )
        if motors is None:
            return products
        seen = {_product_identity(product) for product in products}
        extra: list[Product] = []
        for product in self._collect_oe_candidates(client, motors, lang):
            identity = _product_identity(product)
            if identity in seen:
                continue
            seen.add(identity)
            extra.append(product)
        if not extra:
            return products
        log.info(
            "Група коду %s: +%d кандидатів понад пошук",
            motors.normalized_part_code,
            len(extra),
        )
        return products + [
            _with_identity_origin(product, MOTORS_IDENTITY_SOURCE)
            for product in self._enrich_search_shortlist(
                client,
                extra,
                query=query,
                lang=lang,
                excluded_seller_ids=excluded_seller_ids,
                context=context,
                sellers_already_enriched=_enriched_seller_ids(products),
            )
        ]

    def _enrich_search_shortlist(
        self,
        client: HttpClient,
        products: list[Product],
        *,
        query: str,
        lang: str,
        excluded_seller_ids: frozenset[str],
        context: str | None = None,
        sellers_already_enriched: frozenset[str] = frozenset(),
    ) -> list[Product]:
        owned = {str(value).strip() for value in excluded_seller_ids}
        ranked = sorted(
            enumerate(products),
            key=lambda item: _detail_priority(item[1], query, item[0], context=context),
        )
        selected: set[int] = set()
        sellers: set[str] = set(sellers_already_enriched)
        configured = max(0, self._config.max_detail_cards)
        unbounded = configured == 0
        detail_budget = 0 if unbounded else max(0, configured - len(sellers))
        for index, product in ranked if unbounded or detail_budget else ():
            seller_id = str(product.seller_id or "").strip()
            if not product.url or not seller_id or seller_id in owned:
                continue
            # One card per seller is a budget rule, not an identity rule: a
            # seller whose best-ranked row is the wrong variant may well list
            # the right one second. With no budget there is nothing to ration.
            if not unbounded and seller_id in sellers:
                continue
            selected.add(index)
            sellers.add(seller_id)
            if not unbounded and len(selected) >= detail_budget:
                break

        enriched: list[Product] = []
        for index, product in enumerate(products):
            if index not in selected:
                enriched.append(
                    replace(
                        product,
                        detail_evidence=_detail_metadata(
                            product,
                            status="NOT_SELECTED",
                            selected=False,
                            error_code=(
                                "OWNED_SELLER"
                                if str(product.seller_id or "").strip() in owned
                                else "DETAIL_BUDGET"
                            ),
                        ),
                    )
                )
                continue
            enriched.append(self._fetch_candidate_detail(client, product, lang=lang))
        return enriched

    def _enrich_comparison(
        self,
        client: HttpClient,
        comparison: PriceComparison,
        *,
        lang: str,
    ) -> PriceComparison:
        offers: list[Offer] = []
        for offer in comparison.offers:
            product = self._fetch_candidate_detail(client, offer.product, lang=lang)
            if _detail_identity_conflicts_with_comparison(comparison, offer, product):
                # Detail enrichment is the last identity checkpoint before an
                # offer reaches the comparison API.  Do not retain a row whose
                # structured MPN/OE disproves the listing/title match.
                continue
            # Detail cards can expose a live promotion that was not present in
            # the search listing. Recompute the active sale price after detail
            # enrichment instead of carrying the stale listing price forward.
            active_price = _price_value(product) or offer.price
            detail = product.detail_evidence or {}
            success = detail.get("status") in {"SUCCESS", "SUCCESS_WITH_CONFLICTS"}
            evidence = build_product_comparison_evidence(
                comparison.seed.product,
                product,
                retrieval_kind=offer.match.kind,
                source_type="PROM_PRODUCT_DETAIL" if success else None,
                source_record_id=(str(detail.get("source_url")) if success else None),
                raw_evidence_sha256=(
                    str(detail.get("content_sha256")) if success else None
                ),
                parser_contract_version=(
                    PROM_PRODUCT_DETAIL_SCHEMA_VERSION if success else None
                ),
            )
            offers.append(
                Offer(
                    product=product,
                    match=offer.match,
                    price=active_price,
                    comparison_evidence=evidence,
                )
            )
        return replace(
            comparison,
            offers=sorted(offers, key=lambda item: item.price),
        )

    def _fetch_candidate_detail(
        self,
        client: HttpClient,
        listing: Product,
        *,
        lang: str,
    ) -> Product:
        if not listing.url:
            return replace(
                listing,
                detail_evidence=_detail_metadata(
                    listing,
                    status="FAILED",
                    selected=True,
                    error_code="MISSING_PRODUCT_URL",
                ),
            )
        try:
            document = client.get_document(listing.url)
        except SourceAccessBlocked:
            # Persisted listing replays created before detail capture existed
            # must stay replayable without opening an unauthorized live path.
            return replace(
                listing,
                detail_evidence=_detail_metadata(
                    listing,
                    status="FAILED",
                    selected=True,
                    error_code="DETAIL_REQUEST_NOT_PERMITTED",
                ),
            )
        except RequestFailed as exc:
            return replace(
                listing,
                detail_evidence=_detail_metadata(
                    listing,
                    status="FAILED",
                    selected=True,
                    error_code=f"DETAIL_REQUEST_{exc.status_code or 'NETWORK'}",
                ),
            )
        try:
            detail = parse_product_page(document.text, lang).product
            motors = parse_motors_context(document.text, lang)
        except ParseError:
            return replace(
                listing,
                detail_evidence=_detail_metadata(
                    listing,
                    status="FAILED",
                    selected=True,
                    source_url=document.request_url,
                    content_sha256=document.content_sha256,
                    error_code="PARSER_SCHEMA_CHANGED",
                ),
            )
        if listing.id is None or detail.id != listing.id:
            return replace(
                listing,
                detail_evidence=_detail_metadata(
                    listing,
                    status="FAILED",
                    selected=True,
                    source_url=document.request_url,
                    content_sha256=document.content_sha256,
                    error_code="PRODUCT_IDENTITY_MISMATCH",
                ),
            )
        listing_seller = str(listing.seller_id or "").strip()
        detail_seller = str(detail.seller_id or "").strip()
        if not listing_seller or detail_seller != listing_seller:
            return replace(
                listing,
                detail_evidence=_detail_metadata(
                    listing,
                    status="FAILED",
                    selected=True,
                    source_url=document.request_url,
                    content_sha256=document.content_sha256,
                    error_code="SELLER_IDENTITY_MISMATCH",
                ),
            )

        updates: dict[str, Any] = {}
        field_sources: dict[str, str] = {}
        conflicts: dict[str, dict[str, Any]] = {}
        for field in _DETAIL_MERGE_FIELDS:
            listing_value = getattr(listing, field)
            detail_value = getattr(detail, field)
            if detail_value in (None, "", [], {}):
                continue
            if listing_value in (None, "", [], {}):
                updates[field] = detail_value
                field_sources[field] = _DETAIL_SOURCE_PATHS[field]
            elif listing_value != detail_value:
                conflicts[field] = {
                    "listing": listing_value,
                    "detail": detail_value,
                }
        merged_product = replace(listing, **updates)
        metadata = _detail_metadata(
            merged_product,
            status="SUCCESS_WITH_CONFLICTS" if conflicts else "SUCCESS",
            selected=True,
            source_url=document.request_url,
            content_sha256=document.content_sha256,
            conflicts=conflicts,
            field_sources=field_sources,
            motors=motors,
        )
        # Price, availability, title, images and seller identity intentionally
        # stay at listing time.  The detail page is an evidence enrichment, not
        # a second pricing snapshot that can silently overwrite the cohort.
        return replace(merged_product, detail_evidence=metadata)

    def _compare_via_oe_page(
        self,
        client: HttpClient,
        seed: SeedInfo,
        context: MotorsContext,
        lang: str,
        excluded_seller_ids: frozenset[str] = frozenset(),
    ) -> PriceComparison:
        """Compare against the marketplace's own grouping instead of a search.

        Measured on 2026-07-31: searching for one Touareg radiator's OE returned
        22 offers priced 1087 to 12968 — the matching was right and the cohort
        was still four classes of radiator — while prom.ua files that same code
        with 114 offers behind it.  A search finds what the words happen to say;
        this finds what the marketplace itself grouped.

        ``via_oe_number`` and ``is_widened`` leave with the comparison.  When
        our own code has no listing the walk falls back to one from its
        supersession chain, and an offer taken from a *related* number's market
        is not the same sellable part until something downstream says so.  The
        context has known this since the parser was written; dropping it here
        was what made the widening invisible past this method.
        """

        if not _motors_context_is_public(context):
            raise ValueError(
                "Prom automotive grouping is not public OE/MPN evidence"
            )

        candidates = self._collect_oe_candidates(client, context, lang)
        comparison = build_comparison(
            seed,
            candidates,
            ComparisonParams(
                query=context.normalized_part_code or "",
                threshold=self._config.similarity_threshold,
                max_sellers=self._config.max_sellers,
                identity_source=MOTORS_IDENTITY_SOURCE,
                via_oe_number=context.via_oe_number,
                is_widened=context.is_widened,
                excluded_seller_ids=excluded_seller_ids,
            ),
        )
        log.info(
            "Джерело: сторінка коду %s (взято за %s%s) | продавців %d (переглянуто %d)",
            context.normalized_part_code,
            context.via_oe_number or context.normalized_part_code,
            ", розширення" if context.is_widened else "",
            len(comparison.offers),
            comparison.candidates_scanned,
        )
        return comparison

    def _fetch_seed(self, client: HttpClient, seed_url: str, lang: str) -> SeedInfo:
        return self._fetch_seed_with_motors(client, seed_url, lang)[0]

    def _fetch_seed_with_motors(
        self, client: HttpClient, seed_url: str, lang: str
    ) -> tuple[SeedInfo, MotorsContext | None]:
        """One fetch, both readings: the card and its automotive context."""

        html = client.get_html(seed_url)
        return parse_product_page(html, lang), parse_motors_context(html, lang)

    def _collect_oe_candidates(
        self, client: HttpClient, context: MotorsContext, lang: str
    ) -> Iterator[Product]:
        """Every seller's offer prom.ua filed under our normalized part code.

        The marketplace ignores the sort parameters tried on 2026-07-31, so the
        cheap end is only reachable after the pages are in hand.

        A second, gate-applying copy of this walk lives in
        ``marko.services.prom_motors``.  They are deliberately not shared: this
        is an extraction boundary and must not import the pricing gates.
        """

        base = context.oe_page_url(lang)
        if base is None:
            return
        first = client.get_html(base)
        page = parse_oe_listing(first, lang)
        yield from page.products
        reported = page.total or 0
        pages = math.ceil(reported / OE_OFFERS_PER_PAGE) if reported else 1
        for number in range(2, min(self._config.max_oe_page_pages, pages) + 1):
            yield from parse_oe_listing(
                client.get_html(f"{base}?page={number}"), lang
            ).products

    def _collect_candidates(
        self,
        client: HttpClient,
        query: str,
        lang: str,
        *,
        strict: bool = False,
    ) -> Iterator[Product]:
        """Yield unique search products until total, exhaustion, or safety cap."""
        search_url = f"{BASE_URL}/{lang}/search"
        seen_products: set[tuple[str, str]] = set()
        reported_total: int | None = None
        for page_num in range(1, self._config.max_search_pages + 1):
            params: dict[str, Any] = {"search_term": query}
            if page_num > 1:
                params["page"] = page_num
            try:
                page = client.get_parsed(
                    search_url,
                    lambda html: parse_search(html, lang),
                    params=params,
                )
            except RequestFailed as exc:
                if _is_pagination_end(exc, page_num):
                    log.info(
                        "Пошукова сторінка %d відсутня (HTTP %s) — кінець вибірки, "
                        "зібране збережено.",
                        page_num,
                        exc.status_code,
                    )
                    return
                log.error("Пошукову сторінку %d не завантажено: %s", page_num, exc)
                if strict:
                    raise
                return
            except ParseError as exc:
                log.error("Пошукову сторінку %d не розібрано: %s", page_num, exc)
                if strict:
                    raise
                return
            if page.is_empty:
                log.info("Пошукова сторінка %d порожня — кінець.", page_num)
                return
            if page.total is not None:
                reported_total = max(reported_total or 0, page.total)
            log.info(
                "Пошук, стор. %d: %d кандидатів (total: %s)",
                page_num,
                len(page.products),
                page.total,
            )
            new_on_page = 0
            for product in page.products:
                identity = (
                    ("id", str(product.id))
                    if product.id is not None
                    else (
                        "fallback",
                        product.url
                        or "|".join(
                            (
                                product.name or "",
                                product.sku or "",
                                product.seller_name or "",
                            )
                        ),
                    )
                )
                if identity in seen_products:
                    continue
                seen_products.add(identity)
                new_on_page += 1
                yield product
            if page.products and new_on_page == 0:
                log.info(
                    "Пошукова сторінка %d повторює вже зібрані товари — зупиняюсь.",
                    page_num,
                )
                return
            if reported_total is not None and len(seen_products) >= reported_total:
                log.info(
                    "Зібрано повідомлений Prom total=%d за %d сторінок.",
                    reported_total,
                    page_num,
                )
                return
