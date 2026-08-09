"""Read-only catalog-to-owned-listing join over the private KEMP code.

The join intentionally returns every owned storefront card in a group.  It
never chooses an arbitrary first card and it does not alter the existing owned
catalog identity or public product identifier.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from marko.services.catalog_identity_safety import is_internal_catalog_code
from marko.services.xlsx_catalog import normalize_identifier


CATALOG_INTERNAL_CODE_JOIN_REPORT_VERSION = "catalog-internal-code-join-v1"

_JOIN_SQL = text(
    """
    WITH owned_listings AS (
      SELECT
        l.id,
        l.store_id,
        l.external_id,
        l.url,
        l.raw_data,
        l.catalog_internal_code_norm,
        l.catalog_internal_code_count
      FROM listings AS l
      JOIN workspace_stores AS ws
        ON ws.store_id = l.store_id
       AND ws.workspace_id = :workspace_id
       AND ws.kind = 'owned'
    )
    SELECT
      ci.id::text AS catalog_item_id,
      ci.source_row,
      ci.internal_code_norm,
      COALESCE(
        array_agg(DISTINCT matched.id::text)
          FILTER (WHERE matched.id IS NOT NULL),
        ARRAY[]::text[]
      ) AS listing_ids,
      COALESCE(
        array_agg(DISTINCT matched.store_id::text)
          FILTER (WHERE matched.store_id IS NOT NULL),
        ARRAY[]::text[]
      ) AS store_ids,
      COALESCE(
        array_agg(DISTINCT ambiguous.id::text)
          FILTER (WHERE ambiguous.id IS NOT NULL),
        ARRAY[]::text[]
      ) AS ambiguous_listing_ids
    FROM catalog_items AS ci
    LEFT JOIN owned_listings AS matched
      ON ci.internal_code_norm <> ''
     AND matched.catalog_internal_code_count = 1
     AND matched.catalog_internal_code_norm = ci.internal_code_norm
    LEFT JOIN owned_listings AS ambiguous
      ON ci.internal_code_norm <> ''
     AND ambiguous.catalog_internal_code_count > 1
     AND ci.internal_code_norm = ANY(
       public.marko_listing_internal_codes(ambiguous.raw_data)
     )
    WHERE ci.workspace_id = :workspace_id
      AND ci.import_batch_id = :import_batch_id
    GROUP BY ci.id, ci.source_row, ci.internal_code_norm
    ORDER BY ci.source_row, ci.id
    """
)

_LISTING_DIAGNOSTICS_SQL = text(
    """
    SELECT
      count(*)::bigint AS owned_listing_count,
      count(*) FILTER (
        WHERE l.raw_data ->> 'part_numbers' IS NULL
      )::bigint AS snapshots_without_part_numbers,
      count(*) FILTER (
        WHERE l.catalog_internal_code_count = 1
      )::bigint AS listings_with_one_internal_code,
      count(*) FILTER (
        WHERE l.catalog_internal_code_count > 1
      )::bigint AS listings_with_multiple_internal_codes
    FROM listings AS l
    JOIN workspace_stores AS ws
      ON ws.store_id = l.store_id
     AND ws.workspace_id = :workspace_id
     AND ws.kind = 'owned'
    """
)


def extract_listing_internal_codes(
    raw_data: Mapping[str, object] | None,
) -> tuple[str, ...]:
    """Mirror the generated-column contract for offline tests and diagnostics."""

    if not isinstance(raw_data, Mapping):
        return ()
    values = raw_data.get("part_numbers")
    if not isinstance(values, (list, tuple)):
        return ()
    normalized = {
        normalize_identifier(value)
        for value in values
        if is_internal_catalog_code(value)
    }
    normalized.discard("")
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class CatalogInternalCodeJoinRow:
    catalog_item_id: str
    source_row: int
    internal_code_norm: str
    listing_ids: tuple[str, ...]
    store_ids: tuple[str, ...]
    ambiguous_listing_ids: tuple[str, ...]
    status: str = ""
    requires_single_card_consumer_stop: bool = False

    def classified(self) -> "CatalogInternalCodeJoinRow":
        if not self.internal_code_norm:
            status = "CATALOG_INTERNAL_CODE_MISSING"
        elif self.ambiguous_listing_ids:
            status = "AMBIGUOUS_OWNED_LISTING_INTERNAL_CODES"
        elif self.listing_ids:
            status = "MATCHED_OWNED_LISTING_GROUP"
        else:
            status = "NO_OWNED_LISTING_MATCH"
        return replace(
            self,
            status=status,
            requires_single_card_consumer_stop=(
                len(self.listing_ids) != 1 or bool(self.ambiguous_listing_ids)
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self.classified())


@dataclass(frozen=True, slots=True)
class CatalogInternalCodeJoinReport:
    report_version: str
    generated_at: str
    catalog_positions: int
    catalog_positions_with_code: int
    catalog_positions_without_code: int
    matched_catalog_positions: int
    matched_listing_cards: int
    unmatched_catalog_positions: int
    ambiguous_catalog_positions: int
    owned_listing_count: int
    snapshots_without_part_numbers: int
    listings_with_one_internal_code: int
    listings_with_multiple_internal_codes: int
    rows: tuple[CatalogInternalCodeJoinRow, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rows"] = [row.as_dict() for row in self.rows]
        payload["interpretation"] = {
            "join_returns_card_groups": True,
            "single_card_selected": False,
            "existing_product_ids_changed": False,
            "old_snapshot_indicator": "raw_data ->> 'part_numbers' IS NULL",
        }
        return payload


def summarize_catalog_internal_code_join(
    rows: Sequence[CatalogInternalCodeJoinRow],
    *,
    owned_listing_count: int,
    snapshots_without_part_numbers: int,
    listings_with_one_internal_code: int,
    listings_with_multiple_internal_codes: int,
) -> CatalogInternalCodeJoinReport:
    classified = tuple(row.classified() for row in rows)
    with_code = sum(bool(row.internal_code_norm) for row in classified)
    matched = sum(row.status == "MATCHED_OWNED_LISTING_GROUP" for row in classified)
    return CatalogInternalCodeJoinReport(
        report_version=CATALOG_INTERNAL_CODE_JOIN_REPORT_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        catalog_positions=len(classified),
        catalog_positions_with_code=with_code,
        catalog_positions_without_code=len(classified) - with_code,
        matched_catalog_positions=matched,
        matched_listing_cards=sum(
            len(row.listing_ids)
            for row in classified
            if row.status == "MATCHED_OWNED_LISTING_GROUP"
        ),
        unmatched_catalog_positions=with_code - matched,
        ambiguous_catalog_positions=sum(
            row.status == "AMBIGUOUS_OWNED_LISTING_INTERNAL_CODES" for row in classified
        ),
        owned_listing_count=owned_listing_count,
        snapshots_without_part_numbers=snapshots_without_part_numbers,
        listings_with_one_internal_code=listings_with_one_internal_code,
        listings_with_multiple_internal_codes=listings_with_multiple_internal_codes,
        rows=classified,
    )


async def catalog_internal_code_join_report(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
) -> CatalogInternalCodeJoinReport:
    """Read the generated keys and return a reason-preserving group join."""

    result = await session.execute(
        _JOIN_SQL,
        {"workspace_id": workspace_id, "import_batch_id": import_batch_id},
    )
    rows = tuple(
        CatalogInternalCodeJoinRow(
            catalog_item_id=str(row.catalog_item_id),
            source_row=int(row.source_row),
            internal_code_norm=str(row.internal_code_norm or ""),
            listing_ids=tuple(str(value) for value in (row.listing_ids or ())),
            store_ids=tuple(str(value) for value in (row.store_ids or ())),
            ambiguous_listing_ids=tuple(
                str(value) for value in (row.ambiguous_listing_ids or ())
            ),
        )
        for row in result
    )
    diagnostics = (
        await session.execute(
            _LISTING_DIAGNOSTICS_SQL,
            {"workspace_id": workspace_id},
        )
    ).one()
    return summarize_catalog_internal_code_join(
        rows,
        owned_listing_count=int(diagnostics.owned_listing_count or 0),
        snapshots_without_part_numbers=int(
            diagnostics.snapshots_without_part_numbers or 0
        ),
        listings_with_one_internal_code=int(
            diagnostics.listings_with_one_internal_code or 0
        ),
        listings_with_multiple_internal_codes=int(
            diagnostics.listings_with_multiple_internal_codes or 0
        ),
    )


__all__ = [
    "CATALOG_INTERNAL_CODE_JOIN_REPORT_VERSION",
    "CatalogInternalCodeJoinReport",
    "CatalogInternalCodeJoinRow",
    "catalog_internal_code_join_report",
    "extract_listing_internal_codes",
    "summarize_catalog_internal_code_join",
]
