"""Read-only catalog-to-owned-listing join over the private KEMP code.

The join intentionally returns every owned storefront card in a group.  It
never chooses an arbitrary first card and it does not alter the existing owned
catalog identity or public product identifier.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from uuid import UUID

from openpyxl import load_workbook
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    CatalogItem,
    CatalogKempLinkResolution,
    CatalogKempOwnedListingLink,
    Listing,
    StoreKind,
    WorkspaceStore,
)
from marko.core.config import backend_config_path
from marko.services.catalog_identity_safety import is_internal_catalog_code
from marko.services.xlsx_catalog import normalize_identifier


CATALOG_INTERNAL_CODE_JOIN_REPORT_VERSION = "catalog-internal-code-join-v1"
KEMP_LINK_METHOD = "EXACT_NORMALIZED_KEMP_CHARACTERISTIC"
KEMP_LINK_METHOD_VERSION = "kemp-owned-link-v2"
KEMP_PROM_BOOTSTRAP_PATH = "data/kemp_prom_catalog.xlsx"
_BOOTSTRAP_SHEET = "Export Products Sheet"
_BOOTSTRAP_CODE_LABELS = frozenset({"кодзапчастини", "кодзапчасти", "коддетали"})
_BOOTSTRAP_SPLIT_RE = re.compile(r"[,;|/\n\r]+")

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
    ), catalog_codes AS (
      SELECT internal_code_norm, count(*)::integer AS catalog_code_count
      FROM catalog_items
      WHERE workspace_id = :workspace_id
        AND import_batch_id = :import_batch_id
        AND internal_code_norm <> ''
      GROUP BY internal_code_norm
    )
    SELECT
      ci.id::text AS catalog_item_id,
      ci.source_row,
      ci.internal_code_norm,
      COALESCE(catalog_codes.catalog_code_count, 0) AS catalog_code_count,
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
      , COALESCE(
        array_agg(DISTINCT evidence_missing.id::text)
          FILTER (WHERE evidence_missing.id IS NOT NULL),
        ARRAY[]::text[]
      ) AS evidence_missing_listing_ids
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
    LEFT JOIN owned_listings AS evidence_missing
      ON evidence_missing.external_id = ci.sku
     AND evidence_missing.catalog_internal_code_count = 0
    LEFT JOIN catalog_codes
      ON catalog_codes.internal_code_norm = ci.internal_code_norm
    WHERE ci.workspace_id = :workspace_id
      AND ci.import_batch_id = :import_batch_id
    GROUP BY ci.id, ci.source_row, ci.internal_code_norm,
             catalog_codes.catalog_code_count
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
    catalog_code_count: int = 1
    evidence_missing_listing_ids: tuple[str, ...] = ()
    status: str = ""
    requires_single_card_consumer_stop: bool = False

    def classified(self) -> "CatalogInternalCodeJoinRow":
        if not self.internal_code_norm:
            status = "KEMP_CODE_MISSING"
        elif self.catalog_code_count > 1:
            status = "DUPLICATE_CATALOG_INTERNAL_CODE"
        elif self.ambiguous_listing_ids:
            status = "AMBIGUOUS_LISTING_INTERNAL_CODES"
        elif self.listing_ids:
            status = "LINKED_OWNED_LISTING_GROUP"
        elif self.evidence_missing_listing_ids:
            status = "SOURCE_EVIDENCE_MISSING"
        else:
            status = "NO_CURRENT_OWNED_LISTING"
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
    bootstrap_evidence_rows: int = 0
    bootstrap_source_sha256: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rows"] = [row.as_dict() for row in self.rows]
        payload["interpretation"] = {
            "join_returns_card_groups": True,
            "single_card_selected": False,
            "existing_product_ids_changed": False,
            "old_snapshot_indicator": "raw_data ->> 'part_numbers' IS NULL",
            "bootstrap_locates_listing_but_does_not_prove_link": True,
            "link_requires_exact_saved_kemp_characteristic": True,
        }
        return payload


def summarize_catalog_internal_code_join(
    rows: Sequence[CatalogInternalCodeJoinRow],
    *,
    owned_listing_count: int,
    snapshots_without_part_numbers: int,
    listings_with_one_internal_code: int,
    listings_with_multiple_internal_codes: int,
    bootstrap_evidence_rows: int = 0,
    bootstrap_source_sha256: str | None = None,
) -> CatalogInternalCodeJoinReport:
    classified = tuple(row.classified() for row in rows)
    with_code = sum(bool(row.internal_code_norm) for row in classified)
    matched = sum(row.status == "LINKED_OWNED_LISTING_GROUP" for row in classified)
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
            if row.status == "LINKED_OWNED_LISTING_GROUP"
        ),
        unmatched_catalog_positions=with_code - matched,
        ambiguous_catalog_positions=sum(
            row.status == "AMBIGUOUS_LISTING_INTERNAL_CODES" for row in classified
        ),
        owned_listing_count=owned_listing_count,
        snapshots_without_part_numbers=snapshots_without_part_numbers,
        listings_with_one_internal_code=listings_with_one_internal_code,
        listings_with_multiple_internal_codes=listings_with_multiple_internal_codes,
        rows=classified,
        bootstrap_evidence_rows=bootstrap_evidence_rows,
        bootstrap_source_sha256=bootstrap_source_sha256,
    )


@dataclass(frozen=True, slots=True)
class KempPromBootstrapEvidence:
    source_row: int
    source_listing_id: str
    source_url: str | None
    internal_code_raw: tuple[str, ...]
    internal_code_norm: tuple[str, ...]
    row_sha256: str
    source_sha256: str


def _bootstrap_label(value: object) -> str:
    return re.sub(r"[^a-zа-яіїєґ0-9]", "", str(value or "").casefold())


def parse_kemp_prom_bootstrap(
    content: bytes,
) -> dict[str, tuple[KempPromBootstrapEvidence, ...]]:
    """Read exact labelled KEMP evidence; Prom ID is only a locator."""

    source_sha256 = hashlib.sha256(content).hexdigest()
    workbook = load_workbook(
        BytesIO(content), read_only=True, data_only=True, keep_links=False
    )
    try:
        if _BOOTSTRAP_SHEET not in workbook.sheetnames:
            return {}
        sheet = workbook[_BOOTSTRAP_SHEET]
        iterator = sheet.iter_rows(values_only=True)
        try:
            headers = tuple(str(value or "").strip() for value in next(iterator))
        except StopIteration:
            return {}
        try:
            listing_id_index = headers.index("Унікальний_ідентифікатор")
        except ValueError:
            return {}
        url_index = (
            headers.index("Продукт_на_сайті") if "Продукт_на_сайті" in headers else None
        )
        label_indexes = [
            index
            for index, header in enumerate(headers)
            if header == "Назва_Характеристики"
        ]
        value_indexes = [
            index
            for index, header in enumerate(headers)
            if header == "Значення_Характеристики"
        ]
        result: dict[str, list[KempPromBootstrapEvidence]] = {}
        for source_row, values in enumerate(iterator, start=2):
            listing_id = str(values[listing_id_index] or "").strip()
            if not listing_id:
                continue
            raw_codes: list[str] = []
            normalized_codes: set[str] = set()
            for label_index, value_index in zip(
                label_indexes, value_indexes, strict=True
            ):
                if _bootstrap_label(values[label_index]) not in _BOOTSTRAP_CODE_LABELS:
                    continue
                raw_value = str(values[value_index] or "").strip()
                for token in _BOOTSTRAP_SPLIT_RE.split(raw_value):
                    candidate = token.strip()
                    normalized = normalize_identifier(candidate)
                    if not candidate or not is_internal_catalog_code(normalized):
                        continue
                    raw_codes.append(candidate)
                    normalized_codes.add(normalized)
            if not raw_codes:
                continue
            source_url = (
                str(values[url_index] or "").strip() or None
                if url_index is not None
                else None
            )
            row_payload = {
                "source_row": source_row,
                "source_listing_id": listing_id,
                "source_url": source_url,
                "internal_code_raw": raw_codes,
                "internal_code_norm": sorted(normalized_codes),
                "source_sha256": source_sha256,
            }
            evidence = KempPromBootstrapEvidence(
                source_row=source_row,
                source_listing_id=listing_id,
                source_url=source_url,
                internal_code_raw=tuple(raw_codes),
                internal_code_norm=tuple(sorted(normalized_codes)),
                row_sha256=_canonical_sha256(row_payload),
                source_sha256=source_sha256,
            )
            result.setdefault(listing_id, []).append(evidence)
        return {key: tuple(value) for key, value in result.items()}
    finally:
        workbook.close()


def _default_bootstrap_content() -> bytes | None:
    path = backend_config_path(KEMP_PROM_BOOTSTRAP_PATH)
    return Path(path).read_bytes() if path.is_file() else None


async def _bootstrap_evidence_by_listing(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    content: bytes | None,
) -> tuple[dict[UUID, tuple[KempPromBootstrapEvidence, ...]], int, str | None]:
    if not content:
        return {}, 0, None
    by_external_id = parse_kemp_prom_bootstrap(content)
    if not by_external_id:
        return {}, 0, hashlib.sha256(content).hexdigest()
    listings = list(
        (
            await session.scalars(
                select(Listing)
                .join(WorkspaceStore, WorkspaceStore.store_id == Listing.store_id)
                .where(
                    WorkspaceStore.workspace_id == workspace_id,
                    WorkspaceStore.kind == StoreKind.owned,
                    Listing.external_id.in_(by_external_id),
                )
            )
        ).all()
    )
    return (
        {
            listing.id: by_external_id[listing.external_id]
            for listing in listings
            if listing.external_id in by_external_id
        },
        sum(len(value) for value in by_external_id.values()),
        hashlib.sha256(content).hexdigest(),
    )


def _augment_rows_with_bootstrap(
    rows: Sequence[CatalogInternalCodeJoinRow],
    evidence_by_listing: Mapping[UUID, tuple[KempPromBootstrapEvidence, ...]],
) -> tuple[CatalogInternalCodeJoinRow, ...]:
    result: list[CatalogInternalCodeJoinRow] = []
    for row in rows:
        exact_ids: list[str] = list(row.listing_ids)
        ambiguous_ids: list[str] = list(row.ambiguous_listing_ids)
        unresolved_ids: list[str] = []
        for listing_id_text in row.evidence_missing_listing_ids:
            evidence = evidence_by_listing.get(UUID(listing_id_text), ())
            codes = {code for item in evidence for code in item.internal_code_norm}
            if codes == {row.internal_code_norm}:
                exact_ids.append(listing_id_text)
            elif row.internal_code_norm in codes or len(codes) > 1:
                ambiguous_ids.append(listing_id_text)
            else:
                unresolved_ids.append(listing_id_text)
        result.append(
            replace(
                row,
                listing_ids=tuple(dict.fromkeys(exact_ids)),
                ambiguous_listing_ids=tuple(dict.fromkeys(ambiguous_ids)),
                evidence_missing_listing_ids=tuple(unresolved_ids),
            )
        )
    return tuple(result)


async def catalog_internal_code_join_report(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    bootstrap_content: bytes | None = None,
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
            catalog_code_count=int(row.catalog_code_count or 0),
            listing_ids=tuple(str(value) for value in (row.listing_ids or ())),
            store_ids=tuple(str(value) for value in (row.store_ids or ())),
            ambiguous_listing_ids=tuple(
                str(value) for value in (row.ambiguous_listing_ids or ())
            ),
            evidence_missing_listing_ids=tuple(
                str(value) for value in (row.evidence_missing_listing_ids or ())
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
    (
        evidence_by_listing,
        bootstrap_rows,
        bootstrap_sha256,
    ) = await _bootstrap_evidence_by_listing(
        session,
        workspace_id=workspace_id,
        content=(
            bootstrap_content
            if bootstrap_content is not None
            else _default_bootstrap_content()
        ),
    )
    augmented_rows = _augment_rows_with_bootstrap(rows, evidence_by_listing)
    return summarize_catalog_internal_code_join(
        augmented_rows,
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
        bootstrap_evidence_rows=bootstrap_rows,
        bootstrap_source_sha256=bootstrap_sha256,
    )


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


async def rebuild_catalog_internal_code_links(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    max_items: int | None = None,
    bootstrap_content: bytes | None = None,
) -> CatalogInternalCodeJoinReport:
    """Persist one terminal, reason-preserving result for every selected row."""

    report = await catalog_internal_code_join_report(
        session,
        workspace_id=workspace_id,
        import_batch_id=import_batch_id,
        bootstrap_content=bootstrap_content,
    )
    (
        evidence_by_listing,
        _bootstrap_rows,
        _bootstrap_sha256,
    ) = await _bootstrap_evidence_by_listing(
        session,
        workspace_id=workspace_id,
        content=(
            bootstrap_content
            if bootstrap_content is not None
            else _default_bootstrap_content()
        ),
    )
    rows = report.rows[:max_items] if max_items is not None else report.rows
    listing_ids = {
        UUID(value)
        for row in rows
        for value in (*row.listing_ids, *row.ambiguous_listing_ids)
    }
    listings = (
        {
            listing.id: listing
            for listing in (
                await session.scalars(
                    select(Listing).where(Listing.id.in_(listing_ids))
                )
            ).all()
        }
        if listing_ids
        else {}
    )
    items = {
        item.id: item
        for item in (
            await session.scalars(
                select(CatalogItem).where(
                    CatalogItem.workspace_id == workspace_id,
                    CatalogItem.import_batch_id == import_batch_id,
                )
            )
        ).all()
    }
    for raw_row in rows:
        row = raw_row.classified()
        item_id = UUID(row.catalog_item_id)
        item = items[item_id]
        evidence = {
            "catalog_item_id": row.catalog_item_id,
            "source_row": row.source_row,
            "internal_code_raw": item.internal_code_raw,
            "internal_code_norm": row.internal_code_norm,
            "status": row.status,
            "catalog_code_count": row.catalog_code_count,
            "listing_ids": list(row.listing_ids),
            "ambiguous_listing_ids": list(row.ambiguous_listing_ids),
            "evidence_missing_listing_ids": list(row.evidence_missing_listing_ids),
            "method": KEMP_LINK_METHOD,
            "method_version": KEMP_LINK_METHOD_VERSION,
        }
        evidence_sha256 = _canonical_sha256(evidence)
        input_sha256 = _canonical_sha256(
            {
                "workspace_id": str(workspace_id),
                "import_batch_id": str(import_batch_id),
                **evidence,
            }
        )
        existing = await session.scalar(
            select(CatalogKempLinkResolution).where(
                CatalogKempLinkResolution.workspace_id == workspace_id,
                CatalogKempLinkResolution.catalog_item_id == item_id,
                CatalogKempLinkResolution.input_sha256 == input_sha256,
            )
        )
        if existing is not None:
            continue
        resolution = CatalogKempLinkResolution(
            workspace_id=workspace_id,
            import_batch_id=import_batch_id,
            catalog_item_id=item_id,
            status=row.status,
            internal_code_raw=item.internal_code_raw,
            internal_code_norm=row.internal_code_norm,
            method=KEMP_LINK_METHOD,
            method_version=KEMP_LINK_METHOD_VERSION,
            input_sha256=input_sha256,
            evidence_snapshot=evidence,
            evidence_sha256=evidence_sha256,
            listing_count=(
                len(row.listing_ids)
                if row.status == "LINKED_OWNED_LISTING_GROUP"
                else 0
            ),
        )
        session.add(resolution)
        await session.flush()
        if row.status != "LINKED_OWNED_LISTING_GROUP":
            continue
        for listing_id_text in row.listing_ids:
            listing = listings[UUID(listing_id_text)]
            raw_codes = [
                str(value)
                for value in ((listing.raw_data or {}).get("part_numbers") or ())
                if normalize_identifier(value) == row.internal_code_norm
            ]
            bootstrap_evidence = evidence_by_listing.get(listing.id, ())
            if not raw_codes:
                raw_codes = [
                    raw
                    for evidence_row in bootstrap_evidence
                    for raw in evidence_row.internal_code_raw
                    if normalize_identifier(raw) == row.internal_code_norm
                ]
            link_evidence = {
                "listing_id": str(listing.id),
                "source_listing_id": listing.external_id,
                "url": listing.url,
                "store_id": str(listing.store_id),
                "part_numbers": raw_codes,
                "bootstrap_evidence": [asdict(value) for value in bootstrap_evidence],
                "prom_id_used_as_locator_only": True,
                "exact_characteristic_proof": bool(raw_codes),
                "last_seen_at": listing.last_seen_at.isoformat(),
            }
            link_hash = _canonical_sha256(link_evidence)
            session.add(
                CatalogKempOwnedListingLink(
                    resolution_id=resolution.id,
                    workspace_id=workspace_id,
                    catalog_item_id=item_id,
                    listing_id=listing.id,
                    store_id=listing.store_id,
                    source_listing_id=listing.external_id,
                    source_url=listing.url,
                    internal_code_raw=raw_codes[0]
                    if raw_codes
                    else row.internal_code_norm,
                    internal_code_norm=row.internal_code_norm,
                    evidence_snapshot=link_evidence,
                    evidence_sha256=link_hash,
                )
            )
    await session.commit()
    return report


__all__ = [
    "CATALOG_INTERNAL_CODE_JOIN_REPORT_VERSION",
    "CatalogInternalCodeJoinReport",
    "CatalogInternalCodeJoinRow",
    "catalog_internal_code_join_report",
    "rebuild_catalog_internal_code_links",
    "extract_listing_internal_codes",
    "parse_kemp_prom_bootstrap",
    "summarize_catalog_internal_code_join",
]
