"""Workspace catalog assembled from listings of connected owned stores."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import re
import unicodedata
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import Settings, get_settings
from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    StoreKind,
    WorkspaceStore,
)
from marko.parsers.prom.client import HttpClient
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.parser import parse_product_page
from marko.services.source_access import require_live_prom_marketplace_collection


@dataclass(frozen=True)
class OwnedCatalogListing:
    listing_id: UUID
    store_id: UUID
    store_external_id: str
    store_name: str | None
    store_url: str
    name: str
    listing_url: str
    sku: str | None
    model_id: str | None
    brand: str | None
    currency: str
    current_price: Decimal | None
    is_available: bool | None
    image_url: str | None
    oe_raw: str | None
    description: str | None
    # Candidate-native manufacturer part number from the immutable Prom
    # snapshot.  It remains distinct from the seller SKU and from OE.
    mpn: str | None = None


@dataclass(frozen=True)
class OwnedCatalogStorePresence:
    store_id: UUID
    external_id: str
    name: str
    url: str
    listing_url: str
    listing_count: int
    price: Decimal | None
    currency: str
    is_available: bool | None
    is_owned: bool


@dataclass(frozen=True)
class OwnedCatalogStoreOption:
    store_id: UUID
    external_id: str
    name: str


@dataclass(frozen=True)
class OwnedCatalogProduct:
    id: str
    identity_kind: str
    name: str
    sku: str | None
    oe: str | None
    mpn: str | None
    model_id: str | None
    brand: str | None
    image_url: str | None
    price_min: Decimal | None
    price_max: Decimal | None
    currency: str | None
    listing_count: int
    stores: tuple[OwnedCatalogStorePresence, ...]


@dataclass(frozen=True)
class OwnedCatalogPage:
    items: tuple[OwnedCatalogProduct, ...]
    total: int
    catalog_total: int
    listing_total: int
    duplicates_removed: int
    store_total: int
    stores: tuple[OwnedCatalogStoreOption, ...]
    limit: int
    offset: int


@dataclass(frozen=True)
class ListingIdentifierEnrichment:
    """Identifiers and typed fields read from one owned Prom detail page.

    This is deliberately a small, source-bound result.  It is used to repair
    legacy listings that were imported before MPN was persisted; it never
    claims that a missing field is an OE or invents a cross-reference.
    """

    oe: str | None
    mpn: str | None
    status: str


async def list_owned_catalog(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    query: str | None,
    store_ids: frozenset[UUID] | None,
    limit: int,
    offset: int,
) -> OwnedCatalogPage:
    """Return one bounded catalog page without materialising the whole catalog.

    Identity grouping, filtering, deterministic sorting and pagination happen
    in PostgreSQL.  Python only assembles listings belonging to the selected
    identities, preserving the response semantics of
    :func:`build_owned_catalog_page`.
    """

    store_parameters = list(store_ids or ())
    normalized_query = normalize_catalog_code(query)
    text_query = (query or "").strip().casefold()
    normalized_tokens = [
        token
        for raw_token in re.split(r"\s+", (query or "").strip())
        if (token := normalize_catalog_code(raw_token))
    ]
    identity_query = _is_identity_query(text_query, normalized_query)
    parameters = {
        "workspace_id": workspace_id,
        "filter_stores": bool(store_ids),
        "store_ids": store_parameters,
        "normalized_query": normalized_query,
        "text_query": text_query,
        "normalized_tokens": normalized_tokens,
        "identity_query": identity_query,
        "identity_title_pattern": (
            _identity_title_pattern(normalized_query)
            if identity_query
            else "$^"
        ),
        "identity_title_label_pattern": (
            _identity_title_label_pattern(normalized_query)
            if identity_query
            else "$^"
        ),
        "has_query": bool(normalized_query or text_query),
        "limit": limit,
        "offset": offset,
    }
    page_result = await session.execute(
        _owned_catalog_page_statement(
            has_query=bool(normalized_query or text_query),
        ),
        parameters,
    )
    page_row = page_result.mappings().one()
    identities_payload = page_row["page_identities"]
    if isinstance(identities_payload, str):
        identities_payload = json.loads(identities_payload)
    identities = tuple(
        (item["identity_kind"], item["identity_value"])
        for item in identities_payload
    )

    stores_result = await session.execute(
        _owned_catalog_stores_statement(),
        {"workspace_id": workspace_id},
    )
    stores = tuple(
        sorted(
            (
                OwnedCatalogStoreOption(
                    store_id=row["store_id"],
                    external_id=row["external_id"],
                    name=(row["store_name"] or "").strip()
                    or f"Prom {row['external_id']}",
                )
                for row in stores_result.mappings()
            ),
            key=lambda store: (store.name.casefold(), store.external_id),
        )
    )

    selected_rows: dict[tuple[str, str], list[OwnedCatalogListing]] = {
        identity: [] for identity in identities
    }
    if identities:
        selected_payload = json.dumps(
            [
                {
                    "identity_kind": identity_kind,
                    "identity_value": identity_value,
                }
                for identity_kind, identity_value in identities
            ],
            ensure_ascii=False,
        )
        rows_result = await session.execute(
            _owned_catalog_selected_rows_statement(),
            {
                "workspace_id": workspace_id,
                "filter_stores": bool(store_ids),
                "store_ids": store_parameters,
                "selected_identities": selected_payload,
            },
        )
        for row in rows_result.mappings():
            identity = (row["identity_kind"], row["identity_value"])
            selected_rows[identity].append(
                OwnedCatalogListing(
                    **{
                        key: value
                        for key, value in row.items()
                        if key not in {"identity_kind", "identity_value"}
                    }
                )
            )

    items = tuple(
        _catalog_product(identity, selected_rows[identity])
        for identity in identities
    )
    catalog_total = int(page_row["catalog_total"])
    listing_total = int(page_row["listing_total"])
    return OwnedCatalogPage(
        items=items,
        total=int(page_row["filtered_total"]),
        catalog_total=catalog_total,
        listing_total=listing_total,
        duplicates_removed=max(0, listing_total - catalog_total),
        store_total=len(stores),
        stores=stores,
        limit=limit,
        offset=offset,
    )


async def get_owned_catalog_product(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    product_id: str,
) -> OwnedCatalogProduct | None:
    """Resolve one stable catalog identity without scanning catalog pages.

    The hash is resolved inside the calling workspace.  A foreign and an
    unknown product therefore have the same result and cannot be enumerated
    through this endpoint.
    """

    if re.fullmatch(r"[0-9a-f]{32}", product_id) is None:
        return None
    identity_result = await session.execute(
        _owned_catalog_identity_by_id_statement(),
        {"workspace_id": workspace_id, "product_id": product_id},
    )
    identity_rows = list(identity_result.mappings())
    if len(identity_rows) != 1:
        return None
    identity = (
        identity_rows[0]["identity_kind"],
        identity_rows[0]["identity_value"],
    )
    selected_payload = json.dumps(
        [{"identity_kind": identity[0], "identity_value": identity[1]}],
        ensure_ascii=False,
    )
    rows_result = await session.execute(
        _owned_catalog_selected_rows_statement(),
        {
            "workspace_id": workspace_id,
            "filter_stores": False,
            "store_ids": [],
            "selected_identities": selected_payload,
        },
    )
    rows = [
        OwnedCatalogListing(
            **{
                key: value
                for key, value in row.items()
                if key not in {"identity_kind", "identity_value"}
            }
        )
        for row in rows_result.mappings()
    ]
    if not rows:
        return None
    product = _catalog_product(identity, rows)
    return product if product.id == product_id else None


_OWNED_CATALOG_PAGE_SQL = """
WITH base AS MATERIALIZED (
  SELECT
    l.id AS listing_id,
    l.store_id,
    ms.external_id AS store_external_id,
    l.name,
    l.catalog_identity_kind AS identity_kind,
    l.catalog_identity_value AS identity_value,
    l.catalog_completeness AS completeness,
    l.catalog_sku_norm AS normalized_sku,
    l.catalog_oe_norm AS normalized_oe,
    l.catalog_model_norm AS normalized_model,
    l.catalog_brand_norm AS normalized_brand,
    l.catalog_name_norm AS normalized_name,
    l.catalog_description_norm AS normalized_description,
    public.marko_catalog_normalize(l.raw_data ->> 'mpn') AS normalized_mpn,
    l.raw_data ->> 'description' AS description
  FROM listings AS l
  JOIN marketplace_stores AS ms
    ON ms.id = l.store_id
  JOIN workspace_stores AS ws
    ON ws.store_id = ms.id
  WHERE ws.workspace_id = :workspace_id
    AND ws.kind = 'owned'
    AND (
      NOT CAST(:filter_stores AS boolean)
      OR l.store_id = ANY(CAST(:store_ids AS uuid[]))
    )
),
grouped AS MATERIALIZED (
  SELECT
    identity_kind,
    identity_value,
    (
      array_agg(
        name
        ORDER BY
          completeness DESC,
          char_length(name) DESC,
          lower(name),
          store_external_id,
          listing_id::text
      )
    )[1] AS representative_name,
    bool_or(
      CAST(:text_query AS text) <> ''
      AND strpos(lower(name), CAST(:text_query AS text)) > 0
    ) AS text_match,
    bool_or(
      CAST(:normalized_query AS text) <> ''
      AND (
        strpos(normalized_sku, CAST(:normalized_query AS text)) > 0
        OR strpos(normalized_oe, CAST(:normalized_query AS text)) > 0
        OR strpos(normalized_mpn, CAST(:normalized_query AS text)) > 0
        OR strpos(normalized_model, CAST(:normalized_query AS text)) > 0
        OR strpos(normalized_brand, CAST(:normalized_query AS text)) > 0
        OR strpos(normalized_name, CAST(:normalized_query AS text)) > 0
        OR strpos(normalized_description, CAST(:normalized_query AS text)) > 0
      )
    ) AS normalized_match,
    bool_or(
      CAST(:identity_query AS boolean)
      AND (
        normalized_sku = CAST(:normalized_query AS text)
        OR normalized_oe = CAST(:normalized_query AS text)
        OR normalized_mpn = CAST(:normalized_query AS text)
        OR normalized_model = CAST(:normalized_query AS text)
        OR (
          NOT (
            CAST(:normalized_query AS text) ~ '^[0-9]{1,6}$'
          )
          AND (
            name ~* CAST(:identity_title_pattern AS text)
            OR coalesce(description, '') ~* CAST(:identity_title_pattern AS text)
          )
        )
        OR (
          CAST(:normalized_query AS text) ~ '^[0-9]{1,6}$'
          AND (
            name ~* CAST(:identity_title_label_pattern AS text)
            OR coalesce(description, '') ~* CAST(:identity_title_label_pattern AS text)
          )
        )
      )
    ) AS identity_match,
    array_agg(normalized_sku)
      || array_agg(normalized_oe)
      || array_agg(normalized_mpn)
      || array_agg(normalized_model)
      || array_agg(normalized_brand)
      || array_agg(normalized_name)
      || array_agg(normalized_description) AS search_values
  FROM base
  GROUP BY identity_kind, identity_value
),
filtered AS MATERIALIZED (
  SELECT
    identity_kind,
    identity_value,
    representative_name
  FROM grouped
  WHERE
    NOT CAST(:has_query AS boolean)
    OR (
      CAST(:identity_query AS boolean)
      AND identity_match
    )
    OR (
      NOT CAST(:identity_query AS boolean)
      AND (
        text_match
        OR normalized_match
        OR (
      cardinality(CAST(:normalized_tokens AS text[])) > 0
      AND NOT EXISTS (
        SELECT 1
        FROM unnest(CAST(:normalized_tokens AS text[])) AS requested(token)
        WHERE NOT EXISTS (
          SELECT 1
          FROM unnest(grouped.search_values) AS candidate(value)
          WHERE strpos(candidate.value, requested.token) > 0
        )
      )
      )
    )
)),
stats AS (
  SELECT
    (SELECT count(*) FROM base) AS listing_total,
    (SELECT count(*) FROM grouped) AS catalog_total,
    (SELECT count(*) FROM filtered) AS filtered_total
),
page AS (
  SELECT
    identity_kind,
    identity_value,
    lower(representative_name) AS sort_name,
    encode(
      sha256(
        convert_to(identity_kind || ':' || identity_value, 'UTF8')
      ),
      'hex'
    ) AS stable_id
  FROM filtered
  ORDER BY
    lower(representative_name),
    encode(
      sha256(
        convert_to(identity_kind || ':' || identity_value, 'UTF8')
      ),
      'hex'
    )
  LIMIT :limit
  OFFSET :offset
)
SELECT
  stats.listing_total,
  stats.catalog_total,
  stats.filtered_total,
  coalesce(
    (
      SELECT jsonb_agg(
        jsonb_build_object(
          'identity_kind', page.identity_kind,
          'identity_value', page.identity_value
        )
        ORDER BY page.sort_name, page.stable_id
      )
      FROM page
    ),
    '[]'::jsonb
  ) AS page_identities
FROM stats
"""


_OWNED_CATALOG_PAGE_NO_SEARCH_SQL = """
WITH base AS MATERIALIZED (
  SELECT
    l.id AS listing_id,
    ms.external_id AS store_external_id,
    l.name,
    l.catalog_identity_kind AS identity_kind,
    l.catalog_identity_value AS identity_value,
    l.catalog_completeness AS completeness
  FROM listings AS l
  JOIN marketplace_stores AS ms
    ON ms.id = l.store_id
  JOIN workspace_stores AS ws
    ON ws.store_id = ms.id
  WHERE ws.workspace_id = :workspace_id
    AND ws.kind = 'owned'
    AND (
      NOT CAST(:filter_stores AS boolean)
      OR l.store_id = ANY(CAST(:store_ids AS uuid[]))
    )
),
grouped AS MATERIALIZED (
  SELECT
    identity_kind,
    identity_value,
    (
      array_agg(
        name
        ORDER BY
          completeness DESC,
          char_length(name) DESC,
          lower(name),
          store_external_id,
          listing_id::text
      )
    )[1] AS representative_name
  FROM base
  GROUP BY identity_kind, identity_value
),
page AS (
  SELECT
    identity_kind,
    identity_value,
    lower(representative_name) AS sort_name,
    encode(
      sha256(
        convert_to(identity_kind || ':' || identity_value, 'UTF8')
      ),
      'hex'
    ) AS stable_id
  FROM grouped
  ORDER BY
    lower(representative_name),
    encode(
      sha256(
        convert_to(identity_kind || ':' || identity_value, 'UTF8')
      ),
      'hex'
    )
  LIMIT :limit
  OFFSET :offset
)
SELECT
  (SELECT count(*) FROM base) AS listing_total,
  (SELECT count(*) FROM grouped) AS catalog_total,
  (SELECT count(*) FROM grouped) AS filtered_total,
  coalesce(
    (
      SELECT jsonb_agg(
        jsonb_build_object(
          'identity_kind', page.identity_kind,
          'identity_value', page.identity_value
        )
        ORDER BY page.sort_name, page.stable_id
      )
      FROM page
    ),
    '[]'::jsonb
  ) AS page_identities
"""


_OWNED_CATALOG_STORES_SQL = """
SELECT
  ms.id AS store_id,
  ms.external_id,
  coalesce(
    first_listing.seller_name,
    ms.name
  ) AS store_name
FROM workspace_stores AS ws
JOIN marketplace_stores AS ms
  ON ms.id = ws.store_id
JOIN LATERAL (
  SELECT l.raw_data ->> 'seller_name' AS seller_name
  FROM listings AS l
  WHERE l.store_id = ms.id
  ORDER BY l.name, l.id
  LIMIT 1
) AS first_listing ON true
WHERE ws.workspace_id = :workspace_id
  AND ws.kind = 'owned'
"""


_OWNED_CATALOG_SELECTED_ROWS_SQL = """
WITH selected AS MATERIALIZED (
  SELECT
    item.value ->> 'identity_kind' AS identity_kind,
    item.value ->> 'identity_value' AS identity_value,
    item.ordinality
  FROM jsonb_array_elements(
    CAST(:selected_identities AS jsonb)
  ) WITH ORDINALITY AS item(value, ordinality)
)
SELECT
  selected.identity_kind,
  selected.identity_value,
  l.id AS listing_id,
  l.store_id,
  ms.external_id AS store_external_id,
  coalesce(
    l.raw_data ->> 'seller_name',
    ms.name
  ) AS store_name,
  ms.canonical_url AS store_url,
  l.name,
  l.url AS listing_url,
  l.sku,
  l.model_id,
  l.brand,
  l.currency,
  l.current_price,
  l.is_available,
  l.raw_data ->> 'image' AS image_url,
  l.raw_data ->> 'oe_raw' AS oe_raw,
  l.raw_data ->> 'description' AS description,
  l.raw_data ->> 'mpn' AS mpn
FROM selected
JOIN listings AS l
  ON l.catalog_identity_kind = selected.identity_kind
  AND l.catalog_identity_value = selected.identity_value
JOIN marketplace_stores AS ms
  ON ms.id = l.store_id
JOIN workspace_stores AS ws
  ON ws.store_id = ms.id
WHERE ws.workspace_id = :workspace_id
  AND ws.kind = 'owned'
  AND (
    NOT CAST(:filter_stores AS boolean)
    OR l.store_id = ANY(CAST(:store_ids AS uuid[]))
  )
ORDER BY
  selected.ordinality,
  ms.external_id,
  l.name,
  l.id
"""

_OWNED_CATALOG_IDENTITY_BY_ID_SQL = """
SELECT
  l.catalog_identity_kind AS identity_kind,
  l.catalog_identity_value AS identity_value
FROM listings AS l
JOIN workspace_stores AS ws
  ON ws.store_id = l.store_id
WHERE ws.workspace_id = :workspace_id
  AND ws.kind = 'owned'
  AND left(
    encode(
      sha256(
        convert_to(
          l.catalog_identity_kind || ':' || l.catalog_identity_value,
          'UTF8'
        )
      ),
      'hex'
    ),
    32
  ) = :product_id
GROUP BY l.catalog_identity_kind, l.catalog_identity_value
ORDER BY l.catalog_identity_kind, l.catalog_identity_value
LIMIT 2
"""


def _owned_catalog_page_statement(*, has_query: bool = True):
    return text(
        _OWNED_CATALOG_PAGE_SQL
        if has_query
        else _OWNED_CATALOG_PAGE_NO_SEARCH_SQL
    )


def _owned_catalog_stores_statement():
    return text(_OWNED_CATALOG_STORES_SQL)


def _owned_catalog_selected_rows_statement():
    return text(_OWNED_CATALOG_SELECTED_ROWS_SQL)


def _owned_catalog_identity_by_id_statement():
    return text(_OWNED_CATALOG_IDENTITY_BY_ID_SQL)


async def enrich_listing_oe(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    store_id: UUID,
    external_id: str,
    settings: Settings | None = None,
) -> str | None:
    """Best-effort, cached lookup of one listing's OE/OEM code.

    Prom's search-result feed rarely carries an OE field, so this fetches the
    listing's own product page on demand (one physical request, only for a
    listing this workspace owns) instead of re-scraping the whole catalog.
    A prior result — including a confirmed absence — is cached in
    ``Listing.raw_data`` so repeat opens never re-request the page.
    """
    listing = await _owned_listing(
        session,
        workspace_id=workspace_id,
        store_id=store_id,
        external_id=external_id,
    )
    if listing is None:
        return None

    raw_data = listing.raw_data or {}
    if raw_data.get("oe_checked_at") is not None:
        return normalize_oe_value(raw_data.get("oe_raw"))

    require_live_prom_marketplace_collection(settings)
    resolved_settings = settings or get_settings()
    oe = await asyncio.to_thread(_fetch_listing_oe, listing.url, resolved_settings)

    listing.raw_data = {
        **raw_data,
        "oe_raw": oe,
        "oe_checked_at": datetime.now(UTC).isoformat(),
    }
    await session.commit()
    return oe


async def enrich_listing_identifiers(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    store_id: UUID,
    external_id: str,
    settings: Settings | None = None,
) -> ListingIdentifierEnrichment | None:
    """Read and cache OE/MPN evidence for one owned listing.

    Store-sync snapshots created before the MPN field existed are common in
    the local database.  Fetching one exact detail page on the operator's
    explicit discovery action repairs that card without a full 30k-listing
    resync.  A successful absence is cached as ``NO_IDENTIFIER``; network or
    parser failures are not cached so a later retry can recover.
    """

    listing = await _owned_listing(
        session,
        workspace_id=workspace_id,
        store_id=store_id,
        external_id=external_id,
    )
    if listing is None:
        return None

    raw_data = dict(listing.raw_data or {})
    checked_at = raw_data.get("identifier_enrichment_checked_at")
    if checked_at is not None:
        oe = normalize_oe_value(raw_data.get("oe_raw"))
        mpn = _normalize_optional_text(raw_data.get("mpn"))
        return ListingIdentifierEnrichment(
            oe=oe,
            mpn=mpn,
            status=str(raw_data.get("identifier_enrichment_status") or "CACHED"),
        )

    require_live_prom_marketplace_collection(settings)
    resolved_settings = settings or get_settings()
    product = await asyncio.to_thread(
        _fetch_listing_product,
        listing.url,
        resolved_settings,
    )
    fetched_oe = normalize_oe_value(product.oe_raw) or extract_labeled_oe(
        product.name
    )
    fetched_mpn = _normalize_optional_text(product.mpn)
    # A detail page can omit a field that an earlier enrichment already
    # established.  Preserve that evidence instead of turning a partial
    # response into a destructive null overwrite.
    oe = fetched_oe or normalize_oe_value(raw_data.get("oe_raw"))
    mpn = fetched_mpn or _normalize_optional_text(raw_data.get("mpn"))
    status = "IDENTIFIERS_FOUND" if oe or mpn else "NO_IDENTIFIER"
    detail_fields = {
        "condition": product.condition,
        "package_quantity": product.package_quantity,
        "measure_unit": product.measure_unit,
        "characteristics": product.characteristics,
        "description": product.description,
    }
    enriched = {
        **raw_data,
        "oe_raw": oe,
        "mpn": mpn,
        **{
            key: value
            for key, value in detail_fields.items()
            if value is not None or key not in raw_data
        },
        "identifier_enrichment_checked_at": datetime.now(UTC).isoformat(),
        "identifier_enrichment_status": status,
        "identifier_enrichment_source": "PROM_PRODUCT_DETAIL",
        "identifier_enrichment_url": listing.url,
    }
    listing.raw_data = enriched
    await session.commit()
    return ListingIdentifierEnrichment(oe=oe, mpn=mpn, status=status)


async def _owned_listing(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    store_id: UUID,
    external_id: str,
) -> Listing | None:
    result = await session.execute(
        select(Listing)
        .join(WorkspaceStore, WorkspaceStore.store_id == Listing.store_id)
        .where(
            Listing.store_id == store_id,
            Listing.external_id == external_id,
            WorkspaceStore.workspace_id == workspace_id,
            WorkspaceStore.kind == StoreKind.owned,
        )
    )
    return result.scalar_one_or_none()


def _fetch_listing_oe(url: str, settings: Settings) -> str | None:
    config = ScrapeConfig(
        delay=settings.pricing_scraper_request_delay_seconds,
        delay_jitter=settings.pricing_scraper_request_jitter_seconds,
        timeout=settings.pricing_scraper_http_timeout_seconds,
        max_attempts=max(1, settings.pricing_scraper_http_max_attempts),
    )
    with HttpClient(config) as client:
        html = client.get_html(url)
    seed = parse_product_page(html)
    return normalize_oe_value(seed.product.oe_raw) or extract_labeled_oe(
        seed.product.name
    )


def _fetch_listing_product(url: str, settings: Settings):
    config = ScrapeConfig(
        delay=settings.pricing_scraper_request_delay_seconds,
        delay_jitter=settings.pricing_scraper_request_jitter_seconds,
        timeout=settings.pricing_scraper_http_timeout_seconds,
        max_attempts=max(1, settings.pricing_scraper_http_max_attempts),
    )
    with HttpClient(config) as client:
        html = client.get_html(url)
    return parse_product_page(html).product


def _normalize_optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _owned_catalog_statement(workspace_id: UUID):
    return (
        select(
            Listing.id.label("listing_id"),
            Listing.store_id.label("store_id"),
            MarketplaceStore.external_id.label("store_external_id"),
            func.coalesce(
                Listing.raw_data["seller_name"].as_string(),
                MarketplaceStore.name,
            ).label("store_name"),
            MarketplaceStore.canonical_url.label("store_url"),
            Listing.name.label("name"),
            Listing.url.label("listing_url"),
            Listing.sku.label("sku"),
            Listing.model_id.label("model_id"),
            Listing.brand.label("brand"),
            Listing.currency.label("currency"),
            Listing.current_price.label("current_price"),
            Listing.is_available.label("is_available"),
            Listing.raw_data["image"].as_string().label("image_url"),
            Listing.raw_data["oe_raw"].as_string().label("oe_raw"),
            Listing.raw_data["description"].as_string().label("description"),
            Listing.raw_data["mpn"].as_string().label("mpn"),
        )
        .join(MarketplaceStore, MarketplaceStore.id == Listing.store_id)
        .join(WorkspaceStore, WorkspaceStore.store_id == MarketplaceStore.id)
        .where(
            WorkspaceStore.workspace_id == workspace_id,
            WorkspaceStore.kind == StoreKind.owned,
        )
        .order_by(
            MarketplaceStore.external_id,
            Listing.name,
            Listing.id,
        )
    )


def build_owned_catalog_page(
    rows: tuple[OwnedCatalogListing, ...] | list[OwnedCatalogListing],
    *,
    query: str | None,
    limit: int,
    offset: int,
    store_ids: frozenset[UUID] | None = None,
) -> OwnedCatalogPage:
    store_options = _catalog_store_options(rows)
    filtered_rows = (
        [row for row in rows if row.store_id in store_ids] if store_ids else list(rows)
    )
    grouped: dict[tuple[str, str], list[OwnedCatalogListing]] = {}
    for row in filtered_rows:
        grouped.setdefault(catalog_identity(row), []).append(row)

    products_with_rows = [
        (_catalog_product(identity, group), group)
        for identity, group in grouped.items()
    ]
    products_with_rows.sort(key=lambda item: (item[0].name.casefold(), item[0].id))

    normalized_query = normalize_catalog_code(query)
    text_query = (query or "").strip().casefold()
    normalized_tokens = tuple(
        token
        for raw_token in re.split(r"\s+", (query or "").strip())
        if (token := normalize_catalog_code(raw_token))
    )
    if normalized_query or text_query:
        products_with_rows = [
            item
            for item in products_with_rows
            if _matches_query(
                item[0],
                item[1],
                normalized_query=normalized_query,
                normalized_tokens=normalized_tokens,
                text_query=text_query,
            )
        ]

    catalog_total = len(grouped)
    listing_total = len(filtered_rows)
    total = len(products_with_rows)
    return OwnedCatalogPage(
        items=tuple(
            product for product, _ in products_with_rows[offset : offset + limit]
        ),
        total=total,
        catalog_total=catalog_total,
        listing_total=listing_total,
        duplicates_removed=max(0, listing_total - catalog_total),
        store_total=len(store_options),
        stores=store_options,
        limit=limit,
        offset=offset,
    )


def _catalog_store_options(
    rows: tuple[OwnedCatalogListing, ...] | list[OwnedCatalogListing],
) -> tuple[OwnedCatalogStoreOption, ...]:
    stores: dict[UUID, OwnedCatalogStoreOption] = {}
    for row in rows:
        original_name = (row.store_name or "").strip()
        stores.setdefault(
            row.store_id,
            OwnedCatalogStoreOption(
                store_id=row.store_id,
                external_id=row.store_external_id,
                name=original_name or f"Prom {row.store_external_id}",
            ),
        )
    return tuple(
        sorted(
            stores.values(),
            key=lambda store: (store.name.casefold(), store.external_id),
        )
    )


def catalog_identity(row: OwnedCatalogListing) -> tuple[str, str]:
    brand = normalize_catalog_code(row.brand)
    sku = canonical_catalog_sku(row.sku, row.brand)
    if brand and sku:
        return "brand_sku", f"{brand}:{sku}"

    model_id = (row.model_id or "").strip()
    if model_id:
        return "prom_model", model_id

    oe = normalize_catalog_code(row.oe_raw)
    if brand and oe:
        return "brand_oe", f"{brand}:{oe}"
    if sku and len(sku) >= 3:
        return "sku", sku
    return "listing", f"{row.store_id}:{row.listing_id}"


def canonical_catalog_sku(value: str | None, brand: str | None) -> str:
    sku = normalize_catalog_code(value)
    brand_code = normalize_catalog_code(brand)
    if not sku or not brand_code:
        return sku
    if sku.startswith(brand_code) and len(sku) - len(brand_code) >= 3:
        sku = sku[len(brand_code) :]
    if sku.endswith(brand_code) and len(sku) - len(brand_code) >= 3:
        sku = sku[: -len(brand_code)]
    return sku


def normalize_catalog_code(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).upper()
    return "".join(character for character in normalized if character.isalnum())


def _catalog_product(
    identity: tuple[str, str],
    rows: list[OwnedCatalogListing],
) -> OwnedCatalogProduct:
    representative = _representative(rows)
    store_groups: dict[UUID, list[OwnedCatalogListing]] = {}
    for row in rows:
        store_groups.setdefault(row.store_id, []).append(row)
    stores = tuple(
        sorted(
            (_store_presence(group) for group in store_groups.values()),
            key=lambda store: (store.name.casefold(), store.external_id),
        )
    )

    currencies = {row.currency for row in rows if row.current_price is not None}
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    prices = (
        [row.current_price for row in rows if row.current_price is not None]
        if currency is not None
        else []
    )
    display_sku = min(
        (value for value in (row.sku for row in rows) if value),
        key=lambda value: (len(normalize_catalog_code(value)), len(value), value),
        default=None,
    )
    display_mpn = min(
        (
            value.strip()
            for value in (row.mpn for row in rows)
            if value and value.strip()
        ),
        key=lambda value: (len(normalize_catalog_code(value)), len(value), value),
        default=None,
    )
    oe = next(
        (
            normalized
            for row in rows
            if (normalized := normalize_oe_value(row.oe_raw)) is not None
        ),
        None,
    ) or next(
        (
            extracted
            for row in rows
            if (extracted := extract_labeled_oe(row.name)) is not None
        ),
        None,
    )
    stable_id = hashlib.sha256(f"{identity[0]}:{identity[1]}".encode()).hexdigest()
    return OwnedCatalogProduct(
        id=stable_id[:32],
        identity_kind=identity[0],
        name=representative.name,
        sku=display_sku,
        oe=oe,
        mpn=display_mpn,
        model_id=representative.model_id,
        brand=representative.brand,
        image_url=_safe_image_url(representative.image_url),
        price_min=min(prices) if prices else None,
        price_max=max(prices) if prices else None,
        currency=currency,
        listing_count=len(rows),
        stores=stores,
    )


def _store_presence(rows: list[OwnedCatalogListing]) -> OwnedCatalogStorePresence:
    representative = _representative(rows)
    original_name = next(
        (name for row in rows if (name := (row.store_name or "").strip())),
        None,
    )
    return OwnedCatalogStorePresence(
        store_id=representative.store_id,
        external_id=representative.store_external_id,
        name=original_name or f"Prom {representative.store_external_id}",
        url=representative.store_url,
        listing_url=representative.listing_url,
        listing_count=len(rows),
        price=representative.current_price,
        currency=representative.currency,
        is_available=representative.is_available,
        is_owned=True,
    )


def _representative(rows: list[OwnedCatalogListing]) -> OwnedCatalogListing:
    return min(
        rows,
        key=lambda row: (
            -sum(
                (
                    bool(_safe_image_url(row.image_url)),
                    bool(row.brand),
                    bool(row.sku),
                    row.current_price is not None,
                    row.is_available is not None,
                    bool(row.model_id),
                )
            ),
            -len(row.name),
            row.name.casefold(),
            row.store_external_id,
            str(row.listing_id),
        ),
    )


def _safe_image_url(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized if normalized.startswith(("https://", "http://")) else None


_LABELED_OE_RE = re.compile(
    r"\b(?:OEM|OE)\s*(?:[:#№-]\s*)?"
    r"(?P<value>(?=[A-Z0-9 ._/-]{3,32}\b)(?=[A-Z0-9 ._/-]*\d)"
    r"[A-Z0-9]+(?:[ ._/-]+[A-Z0-9]+){0,5})",
    re.IGNORECASE,
)
_IDENTITY_TOKEN_RE = re.compile(
    r"[A-ZА-ЯЇІЄҐґ0-9]+",
    re.IGNORECASE,
)


def normalize_oe_value(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def extract_labeled_oe(value: str | None) -> str | None:
    match = _LABELED_OE_RE.search(value or "")
    if match is None:
        return None
    return match.group("value").strip(" ._/-")


def _matches_query(
    product: OwnedCatalogProduct,
    rows: list[OwnedCatalogListing],
    *,
    normalized_query: str,
    normalized_tokens: tuple[str, ...],
    text_query: str,
) -> bool:
    # A compact number-bearing query is an identity lookup, not a wording
    # search.  Substring matching here makes ``123456`` select ``1234567`` and
    # can make the operator open a different catalog part before the market
    # comparison even starts.  Keep descriptive queries (for example
    # ``Mercedes 124``) on the wording lane, but require exact normalized
    # structured identity or an exact token span for OE-like queries.
    if _is_identity_query(text_query, normalized_query):
        structured_values = (
            product.sku,
            product.oe,
            product.mpn,
            product.model_id,
            *(row.sku for row in rows),
            *(row.oe_raw for row in rows),
            *(row.mpn for row in rows),
            *(row.model_id for row in rows),
        )
        if any(
            normalized_query == normalize_catalog_code(value)
            for value in structured_values
            if value
        ):
            return True
        text_values = (
            product.name,
            *(row.name for row in rows),
            *(row.description for row in rows),
        )
        return any(
            _identity_token_span_contains(value, normalized_query)
            for value in text_values
            if value
        )
    if text_query and any(text_query in row.name.casefold() for row in rows):
        return True
    if not normalized_query:
        return False
    values = (
        product.sku,
        product.oe,
        product.mpn,
        product.model_id,
        product.brand,
        product.name,
        *(row.sku for row in rows),
        *(row.oe_raw for row in rows),
        *(row.mpn for row in rows),
        *(row.name for row in rows),
        *(row.description for row in rows),
    )
    normalized_values = tuple(normalize_catalog_code(value) for value in values)
    if any(normalized_query in value for value in normalized_values):
        return True
    return bool(normalized_tokens) and all(
        any(token in value for value in normalized_values)
        for token in normalized_tokens
    )


def _is_identity_query(query: str | None, normalized_query: str) -> bool:
    """Recognize an OE/article-shaped query without rejecting normal wording."""

    if not normalized_query or not any(character.isdigit() for character in normalized_query):
        return False
    raw_tokens = _IDENTITY_TOKEN_RE.findall(query or "")
    if not raw_tokens:
        return False
    # A formatted number may be split into several digit-bearing tokens.  A
    # descriptive phrase with a model year (``Mercedes 124``) keeps at least
    # one lexical token and remains on the ordinary wording lane.
    if all(any(character.isdigit() for character in token) for token in raw_tokens):
        return True
    # OE titles frequently put a one/two-letter manufacturer suffix in its own
    # token (``7E5 827 505 A``) or prefix the number with a short make code
    # (``VW 7E5 827 505 A``).  Treat those as identity lookups too; a natural
    # language query such as ``Mercedes 124`` remains on the wording lane
    # because its lexical token is longer than two characters.
    lexical_tokens = [
        token for token in raw_tokens if not any(character.isdigit() for character in token)
    ]
    digit_tokens = [
        token for token in raw_tokens if any(character.isdigit() for character in token)
    ]
    return bool(digit_tokens) and bool(lexical_tokens) and all(
        len(token) <= 2 for token in lexical_tokens
    )


def _identity_token_span_contains(value: str, wanted: str) -> bool:
    """Match grouped identifiers as a whole token span, never a suffix."""

    tokens = _IDENTITY_TOKEN_RE.findall(value)
    for start in range(len(tokens)):
        joined = ""
        for token in tokens[start : start + 8]:
            joined += normalize_catalog_code(token)
            if len(joined) >= len(wanted):
                if joined == wanted:
                    return True
                break
    return False


def _identity_title_pattern(wanted: str) -> str:
    """Build a PostgreSQL regex for a whole identifier token span.

    The stored catalog normalization removes punctuation, so SQL substring
    matching cannot distinguish ``123456`` from ``1234567``.  Matching the
    original title with explicit non-alphanumeric boundaries preserves grouped
    forms while rejecting suffix/prefix collisions.
    """

    pieces = r"[^[:alnum:]]*".join(re.escape(character) for character in wanted)
    return rf"(^|[^[:alnum:]]){pieces}($|[^[:alnum:]])"


def _identity_title_label_pattern(wanted: str) -> str:
    """Build a labelled PostgreSQL regex for short all-numeric identities."""

    pieces = r"[^[:alnum:]]*".join(re.escape(character) for character in wanted)
    label = (
        r"(?:^|[^[:alnum:]])"
        r"(?:oe|oem|art(?:icle)?|артикул|арт|№|"
        r"код(?:[^[:alnum:]]+(?:запчасти|запчастини|виробника|производителя))?)"
        r"[^[:alnum:]]+"
    )
    return rf"{label}{pieces}($|[^[:alnum:]])"


__all__ = [
    "ListingIdentifierEnrichment",
    "OwnedCatalogListing",
    "OwnedCatalogPage",
    "OwnedCatalogProduct",
    "OwnedCatalogStorePresence",
    "build_owned_catalog_page",
    "canonical_catalog_sku",
    "catalog_identity",
    "extract_labeled_oe",
    "enrich_listing_identifiers",
    "list_owned_catalog",
    "normalize_catalog_code",
    "normalize_oe_value",
]
