"""Seed the identity graph from sources already on disk (WP-6).

WP-3 built the graph and its table and wrote nothing into it: it had no writer,
so ``catalog_identity_links`` has been empty since the migration created it, and
every rule the graph knows has been inert. This module is that writer.

Three properties are deliberate.

**Planning is separate from writing.** ``plan_identity`` is a pure function of
the catalogue row and the files, so the whole decision surface is testable
without a database, and a dry run is the same computation as a real one minus
the commit.

**Re-running changes nothing that has not changed.** Rows collide on
``uq_catalog_identity_link_pair_source`` and update in place. What a re-run may
legitimately change is a link's status and anomaly — a newer reference file can
turn a lone claim into a corroborated one, or a settled number into a superseded
one — so those are updated, while the identity of the row is not.

**Nothing is deleted.** The table is append-only by design. A link the current
files no longer produce is reported as stale rather than removed: it was real
evidence when it was written, and deciding it is not evidence any more is a
judgement this package does not make on its own.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from metis.pricing.crosses import normalize_cross_oem
from metis.pricing.identity_graph import (
    IdentityGraph,
    IdentityGraphConfig,
    LinkStatus,
    SourceNumbers,
    build_identity_graph,
    shared_article_numbers,
)
from metis.pricing.kemp_reference import (
    ArticleBrandKinds,
    BrandKind,
    IdentityReason,
    IdentityStatus,
    ReferenceMap,
    load_kemp_reference_map,
    resolve_identity,
)
from metis.pricing.kemp_site import (
    KempSiteTokensConfig,
    TokenClass,
    extract_numbers,
    known_number_set,
)

from marko.infrastructure.db.models import CatalogIdentityLink, CatalogItem

SITE_SOURCE = "KEMP_SITE"
OWN_EXPORT_SOURCE = "OWN_EXPORT_CHARACTERISTIC"
#: The supplier article column of the reference book, which names the same part
#: under another maker's number without claiming it is the vehicle maker's.
REFERENCE_ARTICLE_SOURCE = "KEMP_REFERENCE_ARTICLE"
#: The row's own code column, which holds an internal shelf number for some
#: rows and a real part number for the rest.
OWN_EXPORT_CODE_SOURCE = "OWN_EXPORT_CODE"


class CatalogIdentityReparseError(ValueError):
    """The reparse cannot be trusted as configured."""


@dataclass(frozen=True, slots=True)
class SourceIndex:
    """Every file-based source's numbers, keyed by the item's internal code.

    The join key is the internal KEMP code, because that is the only column all
    three files agree on. On the catalogue side it lives in ``oe_norm``, not in
    ``sku``: measured on the live database on 2026-07-31, ``sku`` holds Prom's
    own product id and matches a reference code in 0 of 4647 rows, while
    ``oe_norm`` matches in 550. That column holds an internal code for 554 rows
    and a real part number for the other 4093 — the original defect, and the
    reason this index reaches only an eighth of the catalogue.
    """

    by_code: Mapping[str, tuple[SourceNumbers, ...]]
    shared_articles: frozenset[str]
    #: Source names actually loaded, so a report can say what was consulted
    #: rather than what was configured.
    loaded_sources: tuple[str, ...]
    #: Reference rows whose article is a supplier number rather than an OE.
    #: Counted rather than turned into edges: the reference map is declared as a
    #: source that asserts "this part's OE", and feeding a supplier number
    #: through it would make an MPN contradict a genuine OE that it does not
    #: contradict. Giving those numbers their own non-asserting source is a
    #: config change, and a config change is its own decision.
    mpn_only_rows: int = 0
    #: Reference rows whose internal code was empty, so nothing could be joined.
    rows_without_code: int = 0
    #: Rows where the newer edition's OE column held a number another edition
    #: attributes to a supplier brand.  Refused as an OE and counted, because a
    #: silent refusal at this scale is indistinguishable from a coverage drop.
    supplier_number_claims: int = 0


@dataclass(frozen=True, slots=True)
class PlannedLink:
    """One edge, with the columns the table needs, before any database exists."""

    our_oem_norm: str
    extracted_oem_norm: str
    extracted_raw: str
    raw_context: str
    extraction_method: str
    validation_status: str
    anomaly: str | None
    corroborating_sources: tuple[str, ...]
    validation_details: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ItemPlan:
    """What the reparse would do to one catalogue row."""

    own_code: str
    graph: IdentityGraph
    links: tuple[PlannedLink, ...]
    identity_status: str
    identity_reason: str | None
    #: The OE this row should carry, when the row does not already carry one and
    #: a source supplied it. Empty means leave the imported value alone.
    fill_oe_raw: str = ""
    fill_oe_norm: str = ""


@dataclass(slots=True)
class ReparseReport:
    """What a run did, in the terms a reviewer checks it by."""

    items_seen: int = 0
    items_with_sources: int = 0
    items_with_links: int = 0
    links_created: int = 0
    links_updated: int = 0
    stale_links: int = 0
    #: Only a CONFIRMED link widens an identity at the candidate gate, so this
    #: split is the number that says whether a run changed anything for pricing.
    link_status_counts: dict[str, int] = field(default_factory=dict)
    oe_filled: int = 0
    identity_status_counts: dict[str, int] = field(default_factory=dict)
    anomaly_counts: dict[str, int] = field(default_factory=dict)
    discard_counts: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "items_seen": self.items_seen,
            "items_with_sources": self.items_with_sources,
            "items_with_links": self.items_with_links,
            "links_created": self.links_created,
            "links_updated": self.links_updated,
            "stale_links": self.stale_links,
            "link_status_counts": dict(sorted(self.link_status_counts.items())),
            "oe_filled": self.oe_filled,
            "identity_status_counts": dict(sorted(self.identity_status_counts.items())),
            "anomaly_counts": dict(sorted(self.anomaly_counts.items())),
            "discard_counts": dict(sorted(self.discard_counts.items())),
            "dry_run": self.dry_run,
        }


def _count(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


# --------------------------------------------------------------- loading files


def load_reference_edition(
    path: str | Path, *, config: IdentityGraphConfig
) -> tuple[str, ReferenceMap]:
    """Read one reference edition and resolve which declared source it is.

    The edition is decided by the sha256 of the file's bytes, never by its name:
    a file renamed to look like the checked one would otherwise inherit its
    standing. An unrecognised hash raises rather than defaulting.
    """

    reference = load_kemp_reference_map(path)
    return config.source_for_dataset(reference.source_sha256), reference


def supplier_articles_by_code(
    editions: Sequence[tuple[str, ReferenceMap]], kinds: ArticleBrandKinds
) -> dict[str, set[str]]:
    """Numbers some edition says belong to a supplier rather than a carmaker.

    The 2026-07-29 edition states an OE outright and has no brand column, so on
    its own there is nothing to check that claim against. The year-old edition
    does have the brand column, and for 4639 codes the two files describe the
    same position — which makes the older file the only reader of the newer
    one's OE column that we have.

    Measured over those shared codes: in 3586 the newer file's OE is character
    for character the older file's article, and the brand dictionary classes 704
    of those as an aftermarket supplier and one as not a brand at all. Without
    this check, 705 catalogue rows would be handed a Sachs or FAG number as
    their OE — the exact mistake WP-2 was written to stop, arriving through the
    one door WP-2 does not watch.
    """

    supplier: dict[str, set[str]] = {}
    for _, reference in editions:
        for row in reference.rows:
            code = row.mpn.strip()
            article = row.article.strip()
            if not code or not article or not row.article_brand.strip():
                continue
            if kinds.kind_of(row.article_brand) in _SUPPLIER_BRAND_KINDS:
                normalized = normalize_cross_oem(article)
                if normalized:
                    supplier.setdefault(code, set()).add(normalized)
    return supplier


#: Brand classes whose numbers are never the vehicle maker's number.  ``UNKNOWN``
#: is deliberately absent: an unclassified brand is an open question, and
#: answering it "supplier" here would be the same guess WP-2 refuses to make.
_SUPPLIER_BRAND_KINDS = frozenset({BrandKind.AFTERMARKET, BrandKind.NOT_A_BRAND})


def article_numbers(
    article: str, *, own_code: str, tokens: KempSiteTokensConfig
) -> tuple[str, ...]:
    """Split an article cell into the separate numbers it holds.

    ``61-33950-20/0209.0F`` is two numbers, and normalizing the cell whole turns
    it into ``61339502002090F`` — a string no seller has ever listed anything
    under. The same tokenizer the site harvest uses is used here, so a number
    read off a card and the same number read out of the book come out identical
    instead of drifting apart.

    Our own internal code is dropped here rather than left to the graph's
    self-reference check, because it is not a cross in the first place.
    """

    if not article.strip():
        return ()
    extraction = extract_numbers(
        [("sku", article)],
        config=tokens,
        known=known_number_set([own_code], tokens),
    )
    return tuple(
        token.raw
        for token in extraction.tokens
        if token.token_class is not TokenClass.INTERNAL_CODE
    )


#: The only class of harvested number that is a claim about this part's OE.
#: ``KNOWN_ARTICLE`` is the supplier article we already had, ``INTERNAL_CODE`` is
#: our own number, and ``AFTERMARKET_CROSS`` is a cross that WP-1B identified as
#: a supplier's own designation.  All three are real numbers; none of them is an
#: OE, and the site is declared as a source that asserts OEs.  Feeding the others
#: through it is how a Boge shock-absorber number becomes a catalogue row's OE.
SITE_OE_TOKEN_CLASS = "OE_CANDIDATE"


def load_site_source(path: str | Path) -> tuple[dict[str, SourceNumbers], int]:
    """Read the harvested kemp.ua numbers, grouped by internal code."""

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise CatalogIdentityReparseError(f"Site numbers do not exist: {source_path}")
    grouped: dict[str, list[str]] = {}
    contexts: dict[str, str] = {}
    not_an_oe = 0
    with source_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            code = (row.get("mpn") or "").strip()
            raw = (row.get("number_raw") or "").strip()
            if not code or not raw:
                continue
            if (row.get("token_class") or "").strip() != SITE_OE_TOKEN_CLASS:
                not_an_oe += 1
                continue
            grouped.setdefault(code, []).append(raw)
            contexts.setdefault(code, (row.get("source_url") or "").strip())
    return (
        {
            code: SourceNumbers(
                extraction_method=SITE_SOURCE,
                numbers=tuple(numbers),
                raw_context=contexts.get(code, ""),
            )
            for code, numbers in grouped.items()
        },
        not_an_oe,
    )


def build_source_index(
    *,
    config: IdentityGraphConfig,
    kinds: ArticleBrandKinds,
    tokens: KempSiteTokensConfig,
    reference_paths: Sequence[str | Path] = (),
    site_path: str | Path | None = None,
) -> SourceIndex:
    """Merge every file source into one index keyed by internal code."""

    by_code: dict[str, list[SourceNumbers]] = {}
    articles_by_code: dict[str, list[str]] = {}
    loaded: list[str] = []
    mpn_only = 0
    without_code = 0
    supplier_number_claims = 0

    editions = [
        load_reference_edition(path, config=config) for path in reference_paths
    ]
    for name, _ in editions:
        if loaded.count(name):
            raise CatalogIdentityReparseError(
                f"{name} was supplied twice; two files cannot be one edition"
            )
        loaded.append(name)
    supplier_articles = supplier_articles_by_code(editions, kinds)

    for name, reference in editions:
        for row in reference.rows:
            code = row.mpn.strip()
            if not code:
                without_code += 1
                continue
            article_parts = article_numbers(
                row.article, own_code=code, tokens=tokens
            )
            articles_by_code.setdefault(code, []).extend(article_parts)
            context = f"{row.name} | {row.article} | {row.article_brand}".strip(" |")
            identity = resolve_identity(row, kinds=kinds, tokens=tokens)
            oe_raw = ""
            if identity.identity_status is IdentityStatus.OE_CONFIRMED:
                if identity.reason is IdentityReason.OE_COLUMN and (
                    identity.oe_norm in supplier_articles.get(code, ())
                ):
                    # The column called it an OE and another edition named its
                    # brand; the brand is a supplier, so the column is wrong.
                    supplier_number_claims += 1
                else:
                    oe_raw = identity.oe_raw
            elif identity.identity_status is IdentityStatus.MPN_ONLY:
                mpn_only += 1
            if oe_raw:
                by_code.setdefault(code, []).append(
                    SourceNumbers(
                        extraction_method=name,
                        numbers=(oe_raw,),
                        raw_context=context,
                    )
                )
            # The supplier article is a cross whatever happened above: it names
            # the same part under another maker's number, which is exactly what
            # widens an identity at the gate.  It goes in under the source that
            # claims no OE, so it can never contradict one.
            crosses = article_numbers(
                identity.mpn_raw, own_code=code, tokens=tokens
            )
            if crosses:
                by_code.setdefault(code, []).append(
                    SourceNumbers(
                        extraction_method=REFERENCE_ARTICLE_SOURCE,
                        numbers=crosses,
                        raw_context=context,
                    )
                )
                if REFERENCE_ARTICLE_SOURCE not in loaded:
                    loaded.append(REFERENCE_ARTICLE_SOURCE)

    if site_path is not None:
        loaded.append(SITE_SOURCE)
        site_numbers, site_not_an_oe = load_site_source(site_path)
        mpn_only += site_not_an_oe
        for code, entry in site_numbers.items():
            by_code.setdefault(code, []).append(entry)

    return SourceIndex(
        by_code={code: tuple(entries) for code, entries in by_code.items()},
        shared_articles=shared_article_numbers(articles_by_code),
        loaded_sources=tuple(loaded),
        mpn_only_rows=mpn_only,
        rows_without_code=without_code,
        supplier_number_claims=supplier_number_claims,
    )


# ------------------------------------------------------------------- planning


def _own_export_numbers(part_numbers_raw: Iterable[str]) -> SourceNumbers | None:
    numbers = tuple(value for value in part_numbers_raw if value and value.strip())
    if not numbers:
        return None
    return SourceNumbers(
        extraction_method=OWN_EXPORT_SOURCE,
        numbers=numbers,
        raw_context="; ".join(numbers),
    )


def plan_identity(
    *,
    own_code: str,
    part_numbers_raw: Sequence[str],
    current_oe_norm: str,
    index: SourceIndex,
    config: IdentityGraphConfig,
    tokens: KempSiteTokensConfig | None = None,
    code_raw: str = "",
) -> ItemPlan:
    """Decide this row's graph, its links and its identity status.

    ``own_code`` is the row's own code column, and what it holds decides how it
    is used. Measured on the live catalogue on 2026-07-31: 554 rows of 4647 hold
    an internal ``776*`` number there, and the other 4093 hold a real part number
    — the defect this whole arc started from, still sitting in the data.

    An internal code is a shelf number and is discarded as a self reference. A
    real number is contributed, and it has to be: it is what the candidate gate
    looks a position up by, so leaving it out of the graph would link the crosses
    to each other beside the one number anybody searches with.

    Pure: the same inputs give the same plan, which is what makes a dry run a
    truthful preview rather than a different code path.
    """

    code = own_code.strip()
    is_internal = bool(
        tokens is not None and code and tokens.internal_code_pattern.match(code)
    )
    sources: list[SourceNumbers] = list(index.by_code.get(code, ()))
    own_numbers = _own_export_numbers(part_numbers_raw)
    if own_numbers is not None:
        sources.append(own_numbers)
    if code and not is_internal:
        sources.append(
            SourceNumbers(
                extraction_method=OWN_EXPORT_CODE_SOURCE,
                numbers=((code_raw or code),),
                raw_context=code_raw or code,
            )
        )

    graph = build_identity_graph(
        # Only a shelf number is a self reference.  Passing a real part number
        # here would delete from the graph the very number the gate searches by.
        own_code=code if is_internal else "",
        sources=sources,
        config=config,
        shared_article_numbers=index.shared_articles,
    )

    links = tuple(
        PlannedLink(
            our_oem_norm=link.our_oem_norm,
            extracted_oem_norm=link.extracted_oem_norm,
            extracted_raw=link.extracted_raw,
            raw_context=link.raw_context,
            extraction_method=link.extraction_method,
            validation_status=link.validation_status.value,
            anomaly=link.anomaly,
            corroborating_sources=link.corroborating_sources,
            validation_details={
                "own_code": code,
                "canonical_source": graph.canonical_source,
                "graph_anomalies": list(graph.anomalies),
                "sources_consulted": list(index.loaded_sources),
            },
        )
        for link in graph.links
    )

    status, reason = _identity_status(graph, config)
    fill_raw, fill_norm = _oe_to_fill(graph, config, current_oe_norm, code)
    return ItemPlan(
        own_code=code,
        graph=graph,
        links=links,
        identity_status=status,
        identity_reason=reason,
        fill_oe_raw=fill_raw,
        fill_oe_norm=fill_norm,
    )


def _asserted_numbers(
    graph: IdentityGraph, config: IdentityGraphConfig
) -> list[tuple[str, str]]:
    """Anchor and edges that a source both claims are OEs and is trusted on.

    Two conditions, and dropping either one has been tried and is wrong.

    ``asserts_oe`` alone is not enough: kemp.ua asserts OEs and is declared
    ``REVIEW`` precisely because its field labels are unreliable, so a number
    only it supplies must not become the row's OE unaided — that is what the
    status is for, and a review status that still writes the column is not a
    review status.

    ``CONFIRMED`` alone is not enough either: the seller's own cross list is
    confirmed as a *statement* and never claimed any of its numbers was the OE.
    """

    found: list[tuple[str, str]] = []
    if graph.canonical and graph.canonical_source is not None:
        rule = config.sources[graph.canonical_source]
        if rule.asserts_oe and rule.status is LinkStatus.CONFIRMED:
            found.append((graph.canonical, graph.canonical))
    for link in graph.links:
        # ``is_confirmed`` already covers a kemp.ua edge promoted by a second
        # source agreeing with it, which is corroboration rather than trust.
        if config.sources[link.extraction_method].asserts_oe and link.is_confirmed:
            found.append((link.extracted_oem_norm, link.extracted_raw))
    return found


def _identity_status(
    graph: IdentityGraph, config: IdentityGraphConfig
) -> tuple[str, str | None]:
    if not graph.canonical:
        return IdentityStatus.UNRESOLVED.value, None
    if _asserted_numbers(graph, config):
        return IdentityStatus.OE_CONFIRMED.value, "OE_FROM_IDENTITY_GRAPH"
    # Numbers exist, but only from a cross list, which never claimed any of them
    # was the OE.  Calling that OE_CONFIRMED would invent a judgement WP-2 was
    # written to avoid making.
    return IdentityStatus.MPN_ONLY.value, "ONLY_CROSS_LIST_NUMBERS"


def _oe_to_fill(
    graph: IdentityGraph,
    config: IdentityGraphConfig,
    current_oe_norm: str,
    own_code: str,
) -> tuple[str, str]:
    """The OE to write onto a row that has none, or nothing.

    Two cases are filled and no others: the column is empty, or it holds our own
    internal code, which is the defect this whole arc started from — the OE
    living in the code column and the code column living in the OE column.

    A row whose OE column holds a different number is never overwritten. It may
    be wrong, but it came from the customer's own export, and replacing it is a
    decision with an owner who is not this script.
    """

    asserted = _asserted_numbers(graph, config)
    if not asserted:
        return "", ""
    current = (current_oe_norm or "").strip()
    own_norm = normalize_cross_oem(own_code)
    if current and current != own_norm:
        return "", ""
    normalized, raw = asserted[0]
    if normalized == own_norm:
        return "", ""
    return raw, normalized


# ------------------------------------------------------------ database writing


async def reparse_workspace_identity(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    index: SourceIndex,
    config: IdentityGraphConfig,
    tokens: KempSiteTokensConfig | None = None,
    dry_run: bool = False,
    batch_size: int = 500,
) -> ReparseReport:
    """Apply the plan for every catalogue row of one workspace."""

    report = ReparseReport(dry_run=dry_run)
    existing = await _existing_link_keys(session, workspace_id=workspace_id)
    produced: set[tuple[UUID, str, str, str]] = set()

    offset = 0
    while True:
        rows = (
            (
                await session.execute(
                    select(CatalogItem)
                    .where(CatalogItem.workspace_id == workspace_id)
                    .order_by(CatalogItem.source_row)
                    .offset(offset)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            break
        offset += len(rows)
        for item in rows:
            # The join key is the code column, not ``sku``: the importer puts
            # Prom's own product id in ``sku`` (1153724202), and none of the 4647
            # rows matches a reference code through it. Measured 2026-07-31:
            # ``oe_norm`` matches 550.
            plan = plan_identity(
                own_code=item.oe_norm or "",
                code_raw=item.oe_raw or "",
                part_numbers_raw=list(item.part_numbers_raw or ()),
                current_oe_norm=item.oe_norm or "",
                index=index,
                config=config,
                tokens=tokens,
            )
            _record_plan(report, plan, index, item.oe_norm or "")
            for link in plan.links:
                key = (
                    item.id,
                    link.our_oem_norm,
                    link.extracted_oem_norm,
                    link.extraction_method,
                )
                produced.add(key)
                _count(report.link_status_counts, link.validation_status)
                if key in existing:
                    report.links_updated += 1
                else:
                    report.links_created += 1
                if not dry_run:
                    await _upsert_link(
                        session,
                        workspace_id=workspace_id,
                        catalog_item_id=item.id,
                        link=link,
                        config=config,
                    )
            if not dry_run:
                _apply_item_fields(item, plan)
            if plan.fill_oe_norm:
                report.oe_filled += 1

    report.stale_links = len(existing - produced)
    if not dry_run:
        await session.commit()
    return report


def _record_plan(
    report: ReparseReport, plan: ItemPlan, index: SourceIndex, own_code: str
) -> None:
    report.items_seen += 1
    if own_code.strip() in index.by_code or plan.graph.canonical:
        report.items_with_sources += 1
    if plan.links:
        report.items_with_links += 1
    _count(report.identity_status_counts, plan.identity_status)
    for anomaly in plan.graph.anomalies:
        _count(report.anomaly_counts, anomaly)
    for reason in plan.graph.discarded.values():
        _count(report.discard_counts, reason)


def _apply_item_fields(item: CatalogItem, plan: ItemPlan) -> None:
    item.identity_status = plan.identity_status
    item.identity_reason = plan.identity_reason
    if plan.fill_oe_norm:
        item.oe_raw = plan.fill_oe_raw
        item.oe_norm = plan.fill_oe_norm


async def _existing_link_keys(
    session: AsyncSession, *, workspace_id: UUID
) -> set[tuple[UUID, str, str, str]]:
    rows = (
        await session.execute(
            select(
                CatalogIdentityLink.catalog_item_id,
                CatalogIdentityLink.our_oem_norm,
                CatalogIdentityLink.extracted_oem_norm,
                CatalogIdentityLink.extraction_method,
            ).where(CatalogIdentityLink.workspace_id == workspace_id)
        )
    ).all()
    return {
        (item_id, our_oem, extracted_oem, method)
        for item_id, our_oem, extracted_oem, method in rows
    }


async def _upsert_link(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    catalog_item_id: UUID,
    link: PlannedLink,
    config: IdentityGraphConfig,
) -> None:
    values = {
        "id": uuid4(),
        "workspace_id": workspace_id,
        "catalog_item_id": catalog_item_id,
        "our_oem_norm": link.our_oem_norm,
        "extracted_oem_norm": link.extracted_oem_norm,
        "extracted_raw": link.extracted_raw,
        "raw_context": link.raw_context,
        "extraction_method": link.extraction_method,
        "validation_status": link.validation_status,
        "anomaly": link.anomaly,
        "corroborating_sources": list(link.corroborating_sources),
        "validation_details": dict(link.validation_details),
        "method_version": config.method_version,
        "config_sha256": config.source_sha256,
    }
    statement = insert(CatalogIdentityLink).values(**values)
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_catalog_identity_link_pair_source",
            # The row's identity is the conflict target and is never rewritten.
            # What may legitimately move is what the current evidence says about
            # it: a newer file can corroborate a lone claim or supersede a
            # settled number, and a re-run must show that rather than hide it.
            set_={
                "validation_status": values["validation_status"],
                "anomaly": values["anomaly"],
                "corroborating_sources": values["corroborating_sources"],
                "validation_details": values["validation_details"],
                "extracted_raw": values["extracted_raw"],
                "raw_context": values["raw_context"],
                "method_version": values["method_version"],
                "config_sha256": values["config_sha256"],
            },
        )
    )


__all__ = [
    "OWN_EXPORT_CODE_SOURCE",
    "OWN_EXPORT_SOURCE",
    "SITE_SOURCE",
    "CatalogIdentityReparseError",
    "ItemPlan",
    "PlannedLink",
    "ReparseReport",
    "SourceIndex",
    "article_numbers",
    "build_source_index",
    "load_reference_edition",
    "load_site_source",
    "supplier_articles_by_code",
    "plan_identity",
    "reparse_workspace_identity",
]
