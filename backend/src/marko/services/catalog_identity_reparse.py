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
inputs no longer produce is preserved but quarantined as stale.  Historical
evidence remains inspectable, while no obsolete edge can keep widening current
pricing merely because an earlier run once stamped it CONFIRMED.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import csv
from dataclasses import dataclass, field
import hashlib
import io
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from metis.pricing.crosses import normalize_cross_oem
from metis.pricing.identity_graph import (
    Anomaly,
    IdentityGraph,
    IdentityGraphConfig,
    LinkStatus,
    SourceNumbers,
    build_identity_graph,
    is_safe_public_number_shape,
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
    split_tokens,
)

from marko.infrastructure.db.models import CatalogIdentityLink, CatalogItem
from marko.services.catalog_identity_safety import identity_runtime_config_sha256
from marko.services.semantic_candidate_features import (
    SEMANTIC_FEATURE_EXTRACTOR_VERSION,
    build_semantic_feature_matrix,
)
from marko.services.parser_models import (
    extract_labelled_original_oe_evidence,
)

SITE_SOURCE = "KEMP_SITE"
# The site harvest is a customer-owned, medium-trust source.  Bind every row
# to the exact HTTPS host and to the search code that produced the card.  A
# copied CSV row pointing at another domain (or at a different KEMP search)
# must not silently acquire KEMP's source standing.
KEMP_SITE_HOSTS = frozenset({"kemp.ua", "www.kemp.ua"})
KEMP_SITE_INTERNAL_CODE_RE = re.compile(r"^776[0-9A-Z]{1,9}$")
#: The aggregator card harvest.  Two sources from one file: the site labels one
#: block the vehicle maker's numbers and one block analogs, and only the first
#: is an assertion about this part's OE.  Both are a second publisher, so both
#: are bound to the host and to the card that carries our code.
SPARETO_SOURCE = "SPARETO_OE_PAGE"
AVTOPRO_OE_SOURCE = "AVTOPRO_CARD_OE"
AVTOPRO_CROSS_SOURCE = "AVTOPRO_CARD_CROSS"
AVTOPRO_HOSTS = frozenset({"avto.pro", "www.avto.pro"})
#: ``/part-<article>-<BRAND>-<id>/``.  The article may contain hyphens, so it is
#: the two trailing segments that are anchored, not the leading one.
AVTOPRO_CARD_PATH_RE = re.compile(
    r"/part-(?P<article>.+)-(?P<brand>[A-Za-z0-9_]+)-(?P<id>\d+)"
)
#: Only the customer's own brand page states anything about the customer's part.
AVTOPRO_CARD_BRAND = "KEMP"
#: ``ExtractedNumber.source_field`` decides what a number may become.  The two
#: entries here are the two card sections; everything else is refused rather
#: than defaulted, because both possible defaults are wrong — one loses real
#: OEs, the other writes a supplier article into the catalogue's OE column.
AVTOPRO_FIELD_ROLES = MappingProxyType({"oe": "OE", "analog": "CROSS"})
#: Fields that are genuine output and carry no relation: the card restating the
#: code we searched for under our own brand.
AVTOPRO_NON_RELATIONAL_FIELDS = frozenset({"article", "mpn", "brand", ""})
#: A page that never rendered cannot testify about absence.
AVTOPRO_BLOCKED_STATUSES = frozenset({"WAF", "PARSE_ERROR", "EMPTY"})
OWN_EXPORT_SOURCE = "OWN_EXPORT_CHARACTERISTIC"
#: The supplier article column of the reference book, which names the same part
#: under another maker's number without claiming it is the vehicle maker's.
REFERENCE_ARTICLE_SOURCE = "KEMP_REFERENCE_ARTICLE"
#: The row's own code column, which holds an internal shelf number for some
#: rows and a real part number for the rest.
OWN_EXPORT_CODE_SOURCE = "OWN_EXPORT_CODE"
#: An exact, owner-labelled OE field from a customer-owned Prom product card.
#: The loader below refuses page-wide text, non-card URLs and non-OE labels, so
#: this source can be trusted independently of a reference-book match.
OWN_STORE_LABELLED_OE_SOURCE = "OWN_STORE_LABELLED_OE"

DISCARD_INTERNAL_CATALOG_CODE = "INTERNAL_CATALOG_CODE"
DISCARD_AMBIGUOUS_INTERNAL_CODES = "AMBIGUOUS_INTERNAL_CATALOG_CODES"
ANOMALY_STALE_AFTER_REPARSE = Anomaly.STALE_AFTER_REPARSE.value
CONFIRMED_IDENTITY_LINK_CONFIDENCE = "0.90"


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
    #: Exact non-empty codes present in the reference editions.  Keeping this
    #: separate from ``by_code`` prevents optional Avto.pro evidence from
    #: changing the 7,193-code denominator.
    reference_codes: frozenset[str] = frozenset()
    #: Owner-card evidence keyed by every exact normalized spelling of the
    #: card's KEMP code (with a leading/trailing ``KEMP`` brand token removed).
    #: These are catalog-code aliases, not fuzzy joins: plan_identity only
    #: consults an exact key present in the row's code or explicit part-number
    #: block.
    owner_by_code: Mapping[str, tuple[SourceNumbers, ...]] = field(
        default_factory=dict
    )
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
    owner_rows_read: int = 0
    owner_rows_bound: int = 0
    owner_noise_rows: int = 0
    owner_cards_bound: int = 0
    owner_card_ambiguity_codes: int = 0
    #: Same private catalogue key, but source revisions explicitly disagree on
    #: a hard physical identity dimension.  The evidence is retained verbatim;
    #: every resulting graph edge stays REVIEW until a human resolves it.
    semantic_conflicts: Mapping[str, tuple[Mapping[str, Any], ...]] = field(
        default_factory=dict
    )
    #: Exact public number reused by different private catalog identities whose
    #: titles contradict on a high-certainty structural dimension.  This is
    #: narrower than ordinary fan-out: engine-only or dimension-only drift is
    #: not enough to defeat an exact number by itself.
    semantic_fanout_conflicts: Mapping[
        str, tuple[Mapping[str, Any], ...]
    ] = field(default_factory=dict)


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
    #: Private KEMP shelf codes recovered from the declared part-number block.
    #: Exactly one is a safe join key into the two customer reference books;
    #: none of them is ever a public cross identifier.
    internal_catalog_codes: tuple[str, ...] = ()
    reference_lookup_codes: tuple[str, ...] = ()
    #: The OE this row should carry, when the row does not already carry one and
    #: a source supplied it. Empty means leave the imported value alone.
    fill_oe_raw: str = ""
    fill_oe_norm: str = ""
    #: Bound provenance for canonical-only evidence.  A star graph has no edge
    #: row for its anchor, so callers that persist the plan need this map to
    #: avoid losing the card URL/label/hash when the owner OE itself wins the
    #: canonical choice.
    source_contexts: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    #: Exact customer-card assertions kept outside the identity graph.  They
    #: are review evidence, not an automatic identity link, so adding a new
    #: owner export cannot silently downgrade an existing confirmed map result
    #: or turn a review-only number into a pricing edge.
    owner_sources: tuple[SourceNumbers, ...] = ()


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

# Commercial quantity/unit conflicts stop pricing admission but do not disprove
# that two source rows describe the same physical part.  Only the dimensions
# below are strong enough to quarantine an identity join between XLS revisions.
_SOURCE_IDENTITY_CONFLICT_DIMENSIONS = frozenset(
    {
        "domain",
        "part_type",
        "part_subtype",
        "assembly_level",
        "serviceability",
        "side",
        "position",
        "climate_variant",
        "connectors_pins",
        "technical_specs",
        "opening_temperature",
        "housing",
        "engine",
    }
)

# For an exact public number, engine lists and measurements can legitimately
# differ across compatible applications or suppliers.  Structural component,
# assembly, side and connector disagreements are materially stronger: the same
# identifier cannot safely stand for a reservoir and an impeller, or a lock
# housing and a complete lock assembly.
_PUBLIC_NUMBER_FANOUT_CONFLICT_DIMENSIONS = frozenset(
    {
        "domain",
        "part_type",
        "part_subtype",
        "assembly_level",
        "serviceability",
        "side",
        "position",
        "climate_variant",
        "connectors_pins",
        "opening_temperature",
        "housing",
    }
)


def reference_semantic_conflicts(
    editions: Sequence[tuple[str, ReferenceMap]],
    *,
    config: IdentityGraphConfig,
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    """Find explicit identity contradictions hidden by a shared private key.

    A private KEMP code is a join key, not proof that every historical row under
    it is one part.  The customer files currently contain cases where the older
    revision says left and the newer says right, or rear and front.  Recency can
    choose which row is current; it cannot turn the two rows into cross numbers
    of one physical part.

    Multiple distinct rows inside one edition are compared as well: one
    truncated key can otherwise fuse unrelated parts before provenance has any
    chance to help.  Across editions, only revisions from the same publisher
    are compared. Distinct publishers are independent evidence sources and
    their number-level disagreements are handled by ``OE_SOURCE_CONFLICT``.
    """

    by_code: dict[str, list[tuple[str, str]]] = {}
    for source, reference in editions:
        for row in reference.rows:
            code = row.mpn.strip()
            title = row.name.strip()
            if code and title:
                entry = (source, title)
                if entry not in by_code.setdefault(code, []):
                    by_code[code].append(entry)

    result: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for code in sorted(by_code):
        evidence: list[Mapping[str, Any]] = []
        entries = sorted(
            by_code[code],
            key=lambda item: (config.sources[item[0]].vintage, item[0], item[1]),
        )
        for left_index, (left_source, left_title) in enumerate(entries):
            left_rule = config.sources[left_source]
            for right_source, right_title in entries[left_index + 1 :]:
                right_rule = config.sources[right_source]
                if (
                    left_source != right_source
                    and left_rule.publisher != right_rule.publisher
                ):
                    continue
                matrix = build_semantic_feature_matrix(
                    {"name": left_title}, {"title": right_title}
                )
                conflicts = tuple(
                    conflict
                    for conflict in matrix["hard_stop_conflicts"]
                    if conflict["dimension"] in _SOURCE_IDENTITY_CONFLICT_DIMENSIONS
                )
                if not conflicts:
                    continue
                evidence.append(
                    {
                        "left_source": left_source,
                        "left_vintage": left_rule.vintage,
                        "left_title": left_title,
                        "right_source": right_source,
                        "right_vintage": right_rule.vintage,
                        "right_title": right_title,
                        "conflicts": list(conflicts),
                        "extractor_version": SEMANTIC_FEATURE_EXTRACTOR_VERSION,
                    }
                )
        if evidence:
            result[code] = tuple(evidence)
    return result


def site_semantic_conflicts(
    editions: Sequence[tuple[str, ReferenceMap]],
    site_sources: Mapping[str, SourceNumbers],
    *,
    config: IdentityGraphConfig,
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    """Compare each retained KEMP card title with the newest book title.

    The site card is medium-trust evidence: it can corroborate a number, but
    it must not silently repair a stale or mis-bound private-code join.  Only
    the newest title for each code is compared; an older book revision is
    already handled by ``reference_semantic_conflicts`` and must not create a
    second disagreement merely because it is historical.  An explicit
    structural conflict (part family, component/assembly, side, position,
    etc.) quarantines the key for human review.  Missing or merely different
    wording remains UNKNOWN rather than becoming a false conflict.
    """

    latest: dict[str, list[tuple[str, str]]] = {}
    for source, reference in editions:
        vintage = config.sources[source].vintage
        for row in reference.rows:
            code = row.mpn.strip()
            title = row.name.strip()
            if not code or not title:
                continue
            current = latest.get(code)
            if current is None:
                latest[code] = [(source, title)]
                continue
            current_vintage = config.sources[current[0][0]].vintage
            if vintage > current_vintage:
                latest[code] = [(source, title)]
            elif vintage == current_vintage and (source, title) not in current:
                current.append((source, title))

    result: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for code, site_source in site_sources.items():
        site_title = _semantic_title_from_context(site_source.raw_context)
        if not site_title:
            continue
        evidence: list[Mapping[str, Any]] = []
        for reference_source, reference_title in latest.get(code, ()):
            matrix = build_semantic_feature_matrix(
                {"name": reference_title}, {"title": site_title}
            )
            conflicts = tuple(
                conflict
                for conflict in matrix["hard_stop_conflicts"]
                if conflict["dimension"] in _SOURCE_IDENTITY_CONFLICT_DIMENSIONS
            )
            if conflicts:
                evidence.append(
                    {
                        "left_source": reference_source,
                        "left_vintage": config.sources[reference_source].vintage,
                        "left_title": reference_title,
                        "right_source": SITE_SOURCE,
                        "right_vintage": config.sources[SITE_SOURCE].vintage,
                        "right_title": site_title,
                        "conflicts": list(conflicts),
                        "extractor_version": SEMANTIC_FEATURE_EXTRACTOR_VERSION,
                    }
                )
        if evidence:
            result[code] = tuple(evidence)
    return result


def public_number_semantic_conflicts(
    by_code: Mapping[str, Sequence[SourceNumbers]],
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    """Find exact public numbers joining structurally incompatible identities.

    Ordinary fan-out may be two duplicate catalog rows for the same physical
    part.  It remains fail-closed at the persistence reader, but this function
    makes the stronger subset explicit: the same normalized number appears
    under different private keys and the associated titles disagree on a
    structural identity dimension.  Those conflicts must also quarantine a
    canonical-only graph, where no link row exists for the SQL fan-out guard.
    """

    claims: dict[str, list[tuple[str, str, str]]] = {}
    for code, entries in by_code.items():
        for entry in entries:
            title = _semantic_title_from_context(entry.raw_context)
            if not title:
                continue
            for raw in entry.numbers:
                normalized = normalize_cross_oem(raw)
                claim = (code, entry.extraction_method, title)
                if (
                    is_safe_public_number_shape(normalized)
                    and claim not in claims.setdefault(normalized, [])
                ):
                    claims[normalized].append(claim)

    result: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for number in sorted(claims):
        by_owner: dict[str, list[tuple[str, str]]] = {}
        for code, source, title in claims[number]:
            by_owner.setdefault(code, []).append((source, title))
        owners = sorted(by_owner)
        if len(owners) < 2:
            continue
        evidence: list[Mapping[str, Any]] = []
        for left_index, left_code in enumerate(owners):
            for right_code in owners[left_index + 1 :]:
                for left_source, left_title in by_owner[left_code]:
                    for right_source, right_title in by_owner[right_code]:
                        matrix = build_semantic_feature_matrix(
                            {"name": left_title}, {"title": right_title}
                        )
                        conflicts = tuple(
                            conflict
                            for conflict in matrix["hard_stop_conflicts"]
                            if conflict["dimension"]
                            in _PUBLIC_NUMBER_FANOUT_CONFLICT_DIMENSIONS
                        )
                        if not conflicts:
                            continue
                        evidence.append(
                            {
                                "left_code": left_code,
                                "left_source": left_source,
                                "left_title": left_title,
                                "right_code": right_code,
                                "right_source": right_source,
                                "right_title": right_title,
                                "conflicts": list(conflicts),
                                "extractor_version": (
                                    SEMANTIC_FEATURE_EXTRACTOR_VERSION
                                ),
                            }
                        )
        if evidence:
            result[number] = tuple(evidence)
    return result


def _semantic_title_from_context(raw_context: str) -> str:
    """Recover title-like evidence without reading URL punctuation as facts.

    KEMP_SITE stores the exact source URL as context.  Its slug is useful
    evidence, but a hyphen after ``ac`` is a word separator, not the product
    assertion ``AC-``.  Decode only the final path segment and replace slug
    separators before passing it to the semantic extractor.
    """

    text = raw_context.strip()
    if text.casefold().startswith(("http://", "https://")):
        slug = unquote(urlsplit(text).path.rsplit("/", 1)[-1])
        return slug.replace("-", " ").replace("_", " ").strip()
    return text.split(" | ", 1)[0].strip()


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

    if not article.strip() or _DIMENSION_ONLY_ARTICLE.fullmatch(article):
        return ()
    extraction = extract_numbers(
        [("sku", chunk) for chunk in _article_identity_chunks(article, tokens=tokens)],
        config=tokens,
        known=known_number_set([own_code], tokens),
    )
    raw_numbers = tuple(
        token.raw
        for token in extraction.tokens
        if token.token_class is not TokenClass.INTERNAL_CODE
    )
    return _expand_slash_shorthand(raw_numbers, raw_context=article)


def _article_identity_chunks(
    article: str, *, tokens: KempSiteTokensConfig
) -> tuple[str, ...]:
    """Remove editorial brand labels and split adjacent complete identifiers.

    Customer exports contain both formatted identifiers (``7E5 827 505 A``)
    and prose-prefixed values (``Audi 4F0260403E``).  Normalizing the latter as
    one token publishes the fictitious node ``AUDI4F0260403E``.  Some cells
    also place two complete identifiers next to each other with whitespace.

    Keep a formatted identifier whole unless every digit-bearing fragment is
    independently long enough to be a complete identifier.  The private KEMP
    namespace and explicitly configured aftermarket shapes are recognized
    before this rule, so ``7764 1257`` and ``VKBA 3901`` retain their intended
    classification.
    """

    chunks: list[str] = []
    for raw_chunk in split_tokens(article, tokens):
        chunk = raw_chunk.strip()
        normalized = normalize_cross_oem(chunk)
        upper = chunk.upper()
        if (
            tokens.internal_code_pattern.fullmatch(normalized)
            or any(rule.pattern.match(upper) for rule in tokens.aftermarket_patterns)
        ):
            chunks.append(chunk)
            continue

        fragments = chunk.split()
        while fragments and not any(character.isdigit() for character in fragments[0]):
            fragments.pop(0)
        while (
            fragments
            and not any(character.isdigit() for character in fragments[-1])
            and len(normalize_cross_oem(fragments[-1])) > 1
        ):
            fragments.pop()
        if not fragments:
            # A short alphabetic fragment after ``/`` or ``,`` is a catalogue
            # suffix (``...A/K`` or ``...B,L,R``), not an editorial brand.
            # Preserve it for ``_expand_slash_shorthand``; the expansion logic
            # decides whether the base makes that suffix unambiguous.
            if (
                len(normalize_cross_oem(chunk)) <= 3
                and ({"/", ","} & set(article))
            ):
                chunks.append(chunk)
            continue

        digit_fragments = [
            fragment for fragment in fragments if any(character.isdigit() for character in fragment)
        ]
        if (
            len(digit_fragments) >= 2
            and all(len(normalize_cross_oem(fragment)) >= tokens.min_length for fragment in digit_fragments)
        ):
            chunks.extend(digit_fragments)
        else:
            chunks.append(" ".join(fragments))
    return tuple(chunks)


_DIMENSION_ONLY_ARTICLE = re.compile(
    r"\s*\d{1,4}(?:[.,]\d+)?\s*[*xх×]\s*\d{1,4}(?:[.,]\d+)?"
    r"(?:\s*[*xх×]\s*\d{1,4}(?:[.,]\d+)?)?\s*(?:mm|мм)?\s*",
    re.IGNORECASE,
)
_TRAILING_LETTERS = re.compile(r"[A-Z]+$")


def _expand_slash_shorthand(
    numbers: Sequence[str], *, raw_context: str
) -> tuple[str, ...]:
    """Expand compact suffix lists without emitting suffixes as global IDs.

    Customer cells use catalog shorthand such as ``1J0959455A/K`` and
    ``8K0407151/152/695``.  The old tokenizer emitted ``K`` and ``152`` as
    standalone public numbers, so unrelated products sharing those fragments
    became cross-linked.  A suffix is expanded only when the first token gives
    an unambiguous base.  Bare alphabetic fragments after a numeric-only base
    are dropped rather than guessed.
    """

    if len(numbers) < 2 or not ({"/", ","} & set(raw_context)):
        return tuple(numbers)
    base_raw = numbers[0]
    base = normalize_cross_oem(base_raw)
    if len(base) < 4:
        # A short numeric prefix followed by one full token is a composite
        # catalogue identifier, not a list.  JCB uses values such as
        # ``331/28235L``; splitting that cell published the common prefix
        # ``331`` as a global cross and falsely joined the left and right
        # handles.  Preserve the exact cell so ordinary normalization produces
        # the single identifier ``33128235L``.
        if (
            "/" in raw_context
            and len(numbers) == 2
            and base.isdigit()
            and len(normalize_cross_oem(numbers[1])) >= 4
        ):
            return (raw_context.strip(),)
        return tuple(numbers)

    expanded: list[str] = [base_raw]
    for raw in numbers[1:]:
        suffix = normalize_cross_oem(raw)
        if not suffix or len(suffix) >= 4:
            if raw:
                expanded.append(raw)
            continue
        replacement: str | None = None
        if suffix.isalpha():
            trailing = _TRAILING_LETTERS.search(base)
            if trailing is not None:
                replacement = f"{base[: trailing.start()]}{suffix}"
            # With no letter suffix in the base, ``/MG`` may be a brand/editor
            # note.  It is not safe to manufacture a new identifier.
        elif suffix.isalnum() and len(base) >= len(suffix) + 3:
            replacement = f"{base[: -len(suffix)]}{suffix}"
        if replacement and replacement not in {
            normalize_cross_oem(value) for value in expanded
        }:
            expanded.append(replacement)
    return tuple(expanded)


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
            source_url = (row.get("source_url") or "").strip()
            if not _kemp_site_source_url_binds_code(source_url, code):
                raise CatalogIdentityReparseError(
                    "KEMP_SITE row has untrusted or unbound source_url: "
                    f"code={code!r}, url={source_url!r}"
                )
            if (row.get("token_class") or "").strip() != SITE_OE_TOKEN_CLASS:
                not_an_oe += 1
                continue
            # New harvests bind the card to the searched private code through
            # schema.org/Product.mpn.  A conflicting structured object is a
            # concrete card-binding failure, not an invitation to fall back to
            # a fuzzy slug.  Legacy CSVs without this column remain readable
            # as medium-trust review evidence until the next harvest.
            structured_status = (row.get("structured_status") or "").strip()
            structured_mpn = (row.get("structured_mpn") or "").strip()
            if structured_status == "MPN_MISMATCH":
                raise CatalogIdentityReparseError(
                    "KEMP_SITE structured Product.mpn does not bind to search code: "
                    f"code={code!r}, structured_mpn={structured_mpn!r}"
                )
            if structured_status == "PRODUCT_MATCH" and (
                not structured_mpn
                or normalize_cross_oem(structured_mpn) != normalize_cross_oem(code)
            ):
                raise CatalogIdentityReparseError(
                    "KEMP_SITE structured Product.mpn is missing or unbound: "
                    f"code={code!r}, structured_mpn={structured_mpn!r}"
                )
            grouped.setdefault(code, []).append(raw)
            # New harvests carry the retained card title.  Keep the URL in the
            # context as well: the title is semantic evidence, while the URL
            # is the provenance a reviewer can open and re-check.  Old v1 CSVs
            # remain readable and fall back to the URL/slug parser.
            source_title = (
                row.get("source_title") or row.get("title") or ""
            ).strip()
            structured_title = (row.get("structured_name") or "").strip()
            source_image_url = (row.get("source_image_url") or "").strip()
            structured_image_url = (row.get("structured_image_url") or "").strip()
            if source_image_url and not _kemp_site_media_url_is_safe(
                source_image_url
            ):
                raise CatalogIdentityReparseError(
                    "KEMP_SITE row has untrusted source_image_url: "
                    f"code={code!r}, url={source_image_url!r}"
                )
            if structured_image_url and not _kemp_site_media_url_is_safe(
                structured_image_url
            ):
                raise CatalogIdentityReparseError(
                    "KEMP_SITE structured image URL is untrusted: "
                    f"code={code!r}, url={structured_image_url!r}"
                )
            semantic_title = structured_title or source_title
            context = " | ".join(
                value
                for value in (
                    semantic_title,
                    (
                        f"visible_title={source_title}"
                        if structured_title
                        and source_title
                        and structured_title != source_title
                        else ""
                    ),
                    source_url,
                    f"image={source_image_url}" if source_image_url else "",
                    (
                        f"structured_image={structured_image_url}"
                        if structured_image_url
                        else ""
                    ),
                    (
                        f"structured_mpn_status={structured_status}"
                        if structured_status
                        else ""
                    ),
                )
                if value
            )
            contexts.setdefault(code, context)
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


#: Заголовок страницы spareto вида ``<номер> - <типы> OE number by<МАРКИ>``.
#: Без него страница ничего не утверждает: «Search results for …» — это ответ
#: «такого оригинального номера я не знаю», а не подтверждение.
_SPARETO_HEADLINE = re.compile(
    r"^\s*(?P<num>[0-9A-Za-z][0-9A-Za-z .\-/]*?)\s*-\s*.+?\s*OE number by",
    re.S,
)


def _spareto_source_url_binds_number(source_url: str, number: str) -> tuple[bool, bool]:
    """-> (хост наш, адрес про этот номер).

    Адрес страницы спрашивается по номеру, поэтому связь адреса с номером —
    единственное, что вообще можно проверить в этой строке, и проверять её
    обязательно: строка с чужой ссылкой доказывает чужую деталь.
    """

    parts = urlsplit(source_url.strip())
    if parts.scheme != "https" or parts.netloc.lower() not in {
        "spareto.com",
        "www.spareto.com",
    }:
        return False, False
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) != 2 or segments[0] != "oe":
        return False, False
    return True, normalize_cross_oem(segments[1]) == normalize_cross_oem(number)


def load_spareto_source(path: str | Path) -> tuple[dict[str, SourceNumbers], int]:
    """Прочитать подтверждения spareto, сгруппированные по внутреннему коду.

    Возвращает второе число — сколько строк отброшено как «не подтверждение».
    Страница без блока ``OE number by`` и наш собственный код 776… в роли OE
    сюда не попадают ни при каких условиях.
    """

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise CatalogIdentityReparseError(
            f"Spareto confirmations do not exist: {source_path}"
        )
    grouped: dict[str, list[str]] = {}
    contexts: dict[str, str] = {}
    not_a_confirmation = 0
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = (row.get("mpn") or "").strip()
            raw = (row.get("number_raw") or "").strip()
            if not code or not raw:
                continue
            source_url = (row.get("source_url") or "").strip()
            host_ok, bound = _spareto_source_url_binds_number(source_url, raw)
            if not host_ok:
                raise CatalogIdentityReparseError(
                    "SPARETO_OE_PAGE row has untrusted source_url: "
                    f"code={code!r}, url={source_url!r}"
                )
            if not bound:
                raise CatalogIdentityReparseError(
                    "SPARETO_OE_PAGE row has unbound source_url: the page is "
                    f"about another number: code={code!r}, number={raw!r}, "
                    f"url={source_url!r}"
                )
            headline = (row.get("page_headline") or "").strip()
            match = _SPARETO_HEADLINE.match(headline)
            if match is None or normalize_cross_oem(match.group("num")) != normalize_cross_oem(raw):
                not_a_confirmation += 1
                continue
            if KEMP_SITE_INTERNAL_CODE_RE.fullmatch(normalize_cross_oem(raw)):
                # Наш складской код никогда не является оригинальным номером,
                # что бы ни показала страница.
                not_a_confirmation += 1
                continue
            grouped.setdefault(code, []).append(raw)
            contexts.setdefault(code, headline)
    return (
        {
            code: SourceNumbers(
                extraction_method=SPARETO_SOURCE,
                numbers=tuple(numbers),
                raw_context=contexts.get(code, ""),
            )
            for code, numbers in grouped.items()
        },
        not_a_confirmation,
    )


def _kemp_site_source_url_binds_code(source_url: str, code: str) -> bool:
    """Validate the immutable provenance contract of one harvested card.

    ``kemp_site_harvest`` obtains links from a search result and records the
    query code.  Friendly product URLs and the legacy ``index.php`` route are
    both present in the retained capture.  Requiring HTTPS, the customer host,
    a product-card path and an exact ``search=<internal code>`` binding keeps a
    stale or manually edited CSV from turning an arbitrary page into identity
    evidence.
    """

    if not KEMP_SITE_INTERNAL_CODE_RE.fullmatch(
        normalize_cross_oem(code.upper())
    ):
        return False
    try:
        parsed = urlsplit(source_url)
    except ValueError:
        return False
    if parsed.scheme.casefold() != "https":
        return False
    if (parsed.hostname or "").casefold() not in KEMP_SITE_HOSTS:
        return False
    query = parse_qs(parsed.query, keep_blank_values=False)
    search_values = query.get("search") or ()
    if len(search_values) != 1:
        return False
    if normalize_cross_oem(search_values[0]) != normalize_cross_oem(code):
        return False
    path = parsed.path.rstrip("/")
    if path.casefold().startswith("/kemp-"):
        return True
    if path.casefold() == "/index.php":
        route = (query.get("route") or ("",))[0].casefold()
        return route == "product/product" and bool((query.get("product_id") or ("",))[0])
    return False


def _kemp_site_media_url_is_safe(source_url: str) -> bool:
    """Accept only an HTTPS media URL served by the customer site."""

    try:
        parsed = urlsplit(source_url)
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() == "https"
        and (parsed.hostname or "").casefold() in KEMP_SITE_HOSTS
        and bool(parsed.path)
    )


def load_avtopro_source(
    path: str | Path,
) -> tuple[dict[str, SourceNumbers], dict[str, SourceNumbers]]:
    """Read the harvested avto.pro cards as two sources, not one.

    ``metis.pricing.avto_pro.parse_part_page`` has already done the reading: it
    takes OE candidates from ``#original-manufacturers`` and analogues from
    ``#analog-parts`` and tags each number with ``source_field``.  This function
    only decides what the graph is allowed to do with them, and the answer
    differs by section.  Returning one merged mapping would hand a Konner
    article to a source declared to assert OEs — the shape of the ``+276``
    defect, and the reason ``KEMP_REFERENCE_ARTICLE`` is a separate source from
    ``KEMP_REFERENCE_MAP``.
    """

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise CatalogIdentityReparseError(f"avto.pro cards do not exist: {source_path}")
    # (role, code) -> numbers / title / url / brands, in the order the card
    # printed them.  ``dict`` keys stand in for an ordered set.
    numbers: dict[tuple[str, str], list[str]] = {}
    titles: dict[tuple[str, str], str] = {}
    urls: dict[tuple[str, str], str] = {}
    brands: dict[tuple[str, str], dict[str, None]] = {}
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            status = (row.get("extraction_status") or "").strip()
            if status in AVTOPRO_BLOCKED_STATUSES:
                # A challenge page yields no numbers, and that is a different
                # fact from a card that lists none.  Reading it as the latter
                # records an absence the site never stated.
                raise CatalogIdentityReparseError(
                    "AVTOPRO row was captured through a blocked page: "
                    f"extraction_status={status!r}"
                )
            code = (row.get("article_raw") or "").strip()
            raw = (row.get("number_raw") or "").strip()
            if not code or not raw:
                continue
            source_url = (row.get("product_url") or "").strip()
            if not avtopro_card_url_binds_code(source_url, code):
                raise CatalogIdentityReparseError(
                    "AVTOPRO row has untrusted or unbound source_url: "
                    f"code={code!r}, url={source_url!r}"
                )
            field = (row.get("source_field") or "").strip()
            if field in AVTOPRO_NON_RELATIONAL_FIELDS:
                # The card restating the code we searched for.  Real, and it
                # relates the part to nothing.
                continue
            role = AVTOPRO_FIELD_ROLES.get(field)
            if role is None:
                raise CatalogIdentityReparseError(
                    "AVTOPRO row carries an unknown source_field; the parser "
                    "grew a field this loader has no rule for: "
                    f"code={code!r}, source_field={field!r}"
                )
            normalized = normalize_cross_oem(raw)
            if not normalized:
                continue
            if KEMP_SITE_INTERNAL_CODE_RE.fullmatch(normalized.upper()):
                # Our own shelf code.  avto.pro prints it as the card's article,
                # so every card carries at least one.  It is not a public
                # identifier anywhere, and a graph holding it would send our
                # warehouse number to Prom as an OE.
                continue
            key = (role, code)
            numbers.setdefault(key, []).append(raw)
            title = (row.get("title") or "").strip()
            if title and key not in titles:
                titles[key] = title
            if key not in urls:
                urls[key] = source_url
            brand = (row.get("number_brand") or "").strip()
            if brand:
                brands.setdefault(key, {})[brand] = None

    def collect(role: str, extraction_method: str) -> dict[str, SourceNumbers]:
        collected: dict[str, SourceNumbers] = {}
        for (row_role, code), values in numbers.items():
            if row_role != role:
                continue
            key = (row_role, code)
            context = " | ".join(
                value
                for value in (
                    titles.get(key, ""),
                    urls.get(key, ""),
                    (
                        "brands=" + ", ".join(brands.get(key, {}))
                        if brands.get(key)
                        else ""
                    ),
                )
                if value
            )
            collected[code] = SourceNumbers(
                extraction_method=extraction_method,
                numbers=tuple(values),
                raw_context=context,
            )
        return collected

    return (
        collect("OE", AVTOPRO_OE_SOURCE),
        collect("CROSS", AVTOPRO_CROSS_SOURCE),
    )


def avtopro_card_url_binds_code(source_url: str, code: str) -> bool:
    """Validate the provenance contract of one harvested avto.pro card.

    The aggregator's card URL carries the article and the brand it belongs to
    (``/part-77642361-KEMP-606/``), so the binding a kemp.ua row gets from its
    ``search=`` query is available here from the path itself.  Three things are
    required and each has a way of going wrong on its own: the customer's own
    internal code shape, so a foreign article cannot enter as a join key; the
    card's brand, because a Febi card says nothing about our part even when it
    lists our number; and the host, so an edited CSV cannot lend avto.pro's
    standing to any page on the internet.
    """

    if not KEMP_SITE_INTERNAL_CODE_RE.fullmatch(normalize_cross_oem(code.upper())):
        return False
    try:
        parsed = urlsplit(source_url)
    except ValueError:
        return False
    if parsed.scheme.casefold() != "https":
        return False
    if (parsed.hostname or "").casefold() not in AVTOPRO_HOSTS:
        return False
    match = AVTOPRO_CARD_PATH_RE.fullmatch(parsed.path.rstrip("/"))
    if match is None:
        return False
    if match.group("brand").casefold() != AVTOPRO_CARD_BRAND.casefold():
        return False
    return normalize_cross_oem(match.group("article")) == normalize_cross_oem(code)


_OWNER_CARD_URL_RE = re.compile(
    r"^/" r"(?:[a-z]{2}/)?" r"p(?P<product_id>[0-9]+)-[^/?#]+\.html$",
    re.IGNORECASE,
)
def _owner_card_url_is_safe(source_url: str) -> bool:
    """Accept only an exact HTTPS Prom product-card URL.

    The owner source is deliberately narrower than a general web citation:
    listing/search URLs and arbitrary Prom pages do not bind a characteristic
    block to one product, so they cannot confirm an OE.
    """

    try:
        parsed = urlsplit(source_url)
    except ValueError:
        return False
    return bool(
        parsed.scheme.casefold() == "https"
        and (parsed.hostname or "").casefold() in {"prom.ua", "www.prom.ua"}
        and not parsed.query
        and not parsed.fragment
        and _OWNER_CARD_URL_RE.fullmatch(parsed.path.rstrip("/")) is not None
    )


def _owner_code_aliases(raw_code: str) -> tuple[str, ...]:
    """Return exact catalog-code aliases, stripping only a KEMP brand token."""

    normalized = normalize_cross_oem(raw_code)
    if not normalized:
        return ()
    aliases = [normalized]
    if normalized.startswith("KEMP") and len(normalized) > len("KEMP"):
        aliases.append(normalized[len("KEMP") :])
    if normalized.endswith("KEMP") and len(normalized) > len("KEMP"):
        aliases.append(normalized[: -len("KEMP")])
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


def _owner_row_value(row: Mapping[str, object], *names: str) -> str:
    folded = {
        str(key or "").strip().casefold(): value for key, value in row.items()
    }
    for name in names:
        value = folded.get(name.casefold())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _owner_rows(path: Path) -> tuple[bytes, list[dict[str, object]]]:
    raw = path.read_bytes()
    if path.suffix.casefold() in {".xlsx", ".xlsm"}:
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(
                io.BytesIO(raw), read_only=True, data_only=True
            )
            sheet = workbook[workbook.sheetnames[0]]
            values = list(sheet.iter_rows(values_only=True))
        except Exception as exc:  # pragma: no cover - openpyxl's concrete errors vary
            raise CatalogIdentityReparseError(
                f"Owner store workbook is not readable: {path}"
            ) from exc
        if not values:
            return raw, []
        headers = [str(value or "").strip() for value in values[0]]
        return raw, [
            {headers[index]: value for index, value in enumerate(row) if index < len(headers)}
            for row in values[1:]
        ]

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CatalogIdentityReparseError(
            f"Owner store CSV is not UTF-8: {path}"
        ) from exc
    return raw, [dict(row) for row in csv.DictReader(io.StringIO(text))]


@dataclass(frozen=True, slots=True)
class OwnerStoreSourceLoad:
    entries: Mapping[str, tuple[SourceNumbers, ...]]
    rows_read: int
    rows_bound: int
    noise_rows: int
    cards_bound: int
    ambiguous_codes: int
    source_sha256: str


def _owner_number_is_obvious_noise(raw: str, normalized: str) -> bool:
    """Reject page-token artefacts without imposing a brand-specific whitelist."""

    value = raw.strip()
    if re.search(r"\d\s*[.,]\s*\d", value):
        return True
    if re.search(r"\d{4}\s*[-/]\s*\d{2,4}", value):
        return True
    if re.search(r"\d\s*[*xх×]\s*\d", value, re.IGNORECASE):
        return True
    # The customer's own shelf/reference namespace is not an OE even when a
    # scraped card repeats it inside an explicitly labelled block.  Keep the
    # exact KEMP pattern in the same rejection bucket so it cannot leak into
    # owner review as a plausible vehicle number.
    if KEMP_SITE_INTERNAL_CODE_RE.fullmatch(normalized):
        return True
    # Purely numeric short fragments are overwhelmingly dates, dimensions,
    # menu counts or seller text in the scraped export.  Keep alphanumeric
    # short OEs (04E, A1, KL2) because the graph's general shape guard permits
    # those genuine identifiers.
    return normalized.isdigit() and len(normalized) < 5


def _load_owner_store_source_with_stats(path: str | Path) -> OwnerStoreSourceLoad:
    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise CatalogIdentityReparseError(
            f"Owner store cards do not exist: {source_path}"
        )
    raw_file, rows = _owner_rows(source_path)
    source_sha256 = hashlib.sha256(raw_file).hexdigest()
    grouped: dict[str, list[SourceNumbers]] = {}
    seen: set[tuple[str, str, str, str]] = set()
    rows_bound = 0
    noise_rows = 0
    cards: set[str] = set()
    card_urls_by_code: dict[str, set[str]] = {}
    for row in rows:
        code = _owner_row_value(row, "код_kemp", "код kemp", "kemp code")
        raw_number = _owner_row_value(row, "oem", "номер", "number")
        label = _owner_row_value(row, "блок", "block", "field", "label")
        source_url = _owner_row_value(row, "ссылка", "url", "source_url")
        title = _owner_row_value(row, "название", "title", "name")
        number_brand = _owner_row_value(
            row, "бренд_номера", "number_brand", "brand", "manufacturer"
        )
        captured_at = _owner_row_value(
            row, "дата", "date", "captured_at", "timestamp"
        )
        screenshot = _owner_row_value(row, "скриншот", "screenshot", "image")
        if not code or not raw_number:
            continue
        # Reuse the exact label parser rather than keeping a second, subtly
        # different spelling table in the file loader.
        evidence = extract_labelled_original_oe_evidence(
            [{"name": label, "value": raw_number}]
        )
        if not evidence:
            continue
        if not _owner_card_url_is_safe(source_url):
            raise CatalogIdentityReparseError(
                "Owner store row has untrusted or unbound product URL: "
                f"code={code!r}, url={source_url!r}"
            )
        rows_bound += 1
        cards.add(source_url)
        card_urls_by_code.setdefault(normalize_cross_oem(code), set()).add(source_url)
        card_match = _OWNER_CARD_URL_RE.fullmatch(urlsplit(source_url).path.rstrip("/"))
        product_id = card_match.group("product_id") if card_match else ""
        for item in evidence:
            normalized = normalize_cross_oem(item["raw"])
            if not normalized:
                continue
            if _owner_number_is_obvious_noise(item["raw"], normalized):
                noise_rows += 1
                continue
            context = " | ".join(
                value
                for value in (
                    f"label={item['label']}",
                    f"code={code}",
                    f"source_url={source_url}",
                    f"product_id={product_id}" if product_id else "",
                    f"title={title}" if title else "",
                    f"brand={number_brand}" if number_brand else "",
                    f"captured_at={captured_at}" if captured_at else "",
                    f"screenshot={screenshot}" if screenshot else "",
                    f"raw={item['raw']}",
                    f"normalized={normalized}",
                    "publisher=kemp_owned_store",
                    "source_version=owner-card-export-v1",
                    "parser_version=owner-card-export-v1",
                    f"source_file_sha256={source_sha256}",
                )
                if value
            )
            entry_key = (code, normalized, source_url, item["label"])
            if entry_key in seen:
                continue
            seen.add(entry_key)
            entry = SourceNumbers(
                extraction_method=OWN_STORE_LABELLED_OE_SOURCE,
                numbers=(item["raw"],),
                raw_context=context,
            )
            for alias in _owner_code_aliases(code):
                grouped.setdefault(alias, []).append(entry)
        # A bound card with only noise is retained in the counters but emits no
        # graph source, making the rejection visible in the coverage report.
    return OwnerStoreSourceLoad(
        entries={key: tuple(entries) for key, entries in grouped.items()},
        rows_read=len(rows),
        rows_bound=rows_bound,
        noise_rows=noise_rows,
        cards_bound=len(cards),
        ambiguous_codes=sum(
            1 for urls in card_urls_by_code.values() if len(urls) > 1
        ),
        source_sha256=source_sha256,
    )


def load_owner_store_source(
    path: str | Path,
) -> dict[str, tuple[SourceNumbers, ...]]:
    """Load exact OE fields from a customer's own Prom card export.

    Only rows whose block is an exact original/OE label are admitted.  The
    common ``Код запчастини`` block, page text, supplier articles and rows from
    another host are refused or ignored; a broad token scan would turn dates,
    dimensions and seller IDs into false OEs.  The returned mapping is keyed by
    exact code aliases and carries file hash, label, card URL and title in every
    context for audit/replay.
    """

    return dict(_load_owner_store_source_with_stats(path).entries)


def build_source_index(
    *,
    config: IdentityGraphConfig,
    kinds: ArticleBrandKinds,
    tokens: KempSiteTokensConfig,
    reference_paths: Sequence[str | Path] = (),
    site_path: str | Path | None = None,
    owner_store_paths: Sequence[str | Path] = (),
    avtopro_paths: Sequence[str | Path] = (),
    spareto_paths: Sequence[str | Path] = (),
) -> SourceIndex:
    """Merge every declared file source into one exact-code index.

    Reference/site inputs are keyed by the private reference code.  Owner card
    exports are keyed by the exact KEMP code printed on the card and are kept in
    a separate alias map so a public code can be joined without treating a
    fuzzy title or a transitive cross as identity evidence.
    """

    by_code: dict[str, list[SourceNumbers]] = {}
    articles_by_code: dict[str, list[str]] = {}
    loaded: list[str] = []
    mpn_only = 0
    without_code = 0
    supplier_number_claims = 0
    owner_by_code: dict[str, list[SourceNumbers]] = {}
    owner_rows_read = 0
    owner_rows_bound = 0
    owner_noise_rows = 0
    owner_cards_bound = 0
    owner_card_ambiguity_codes = 0

    editions = [load_reference_edition(path, config=config) for path in reference_paths]
    reference_codes: frozenset[str] = frozenset()
    for name, _ in editions:
        if loaded.count(name):
            raise CatalogIdentityReparseError(
                f"{name} was supplied twice; two files cannot be one edition"
            )
        loaded.append(name)
    supplier_articles = supplier_articles_by_code(editions, kinds)
    semantic_conflicts = reference_semantic_conflicts(editions, config=config)
    site_numbers: dict[str, SourceNumbers] = {}

    for name, reference in editions:
        for row in reference.rows:
            code = row.mpn.strip()
            if not code:
                without_code += 1
                continue
            article_parts = article_numbers(row.article, own_code=code, tokens=tokens)
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
            crosses = article_numbers(identity.mpn_raw, own_code=code, tokens=tokens)
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

    # This is the graph's reference universe: codes that produced at least one
    # declared identity/cross source.  Rows with an empty OE and empty article
    # remain counted in ``rows_without_code``/source diagnostics, but must not
    # inflate a denominator that can never yield a plan.
    reference_codes = frozenset(by_code)

    if site_path is not None:
        loaded.append(SITE_SOURCE)
        site_numbers, site_not_an_oe = load_site_source(site_path)
        mpn_only += site_not_an_oe
        for code, entry in site_numbers.items():
            by_code.setdefault(code, []).append(entry)

        for code, conflicts in site_semantic_conflicts(
            editions,
            site_numbers,
            config=config,
        ).items():
            semantic_conflicts[code] = tuple(
                (*semantic_conflicts.get(code, ()), *conflicts)
            )

    for owner_path in owner_store_paths:
        owner_load = _load_owner_store_source_with_stats(owner_path)
        declared_owner_hashes = {
            digest
            for digest, source_name in config.datasets.items()
            if source_name == OWN_STORE_LABELLED_OE_SOURCE
        }
        if declared_owner_hashes and owner_load.source_sha256 not in declared_owner_hashes:
            raise CatalogIdentityReparseError(
                "Owner store export has an undeclared sha256; refresh the "
                "identity graph dataset manifest before admitting it: "
                f"{owner_load.source_sha256}"
            )
        owner_entries = owner_load.entries
        if OWN_STORE_LABELLED_OE_SOURCE not in loaded:
            loaded.append(OWN_STORE_LABELLED_OE_SOURCE)
        owner_rows_read += owner_load.rows_read
        owner_rows_bound += owner_load.rows_bound
        owner_noise_rows += owner_load.noise_rows
        owner_cards_bound += owner_load.cards_bound
        owner_card_ambiguity_codes += owner_load.ambiguous_codes
        for alias, entries in owner_entries.items():
            owner_by_code.setdefault(alias, []).extend(entries)

    for avtopro_path in avtopro_paths:
        avtopro_oe, avtopro_cross = load_avtopro_source(avtopro_path)
        for source_name, entries_by_code in (
            (AVTOPRO_OE_SOURCE, avtopro_oe),
            (AVTOPRO_CROSS_SOURCE, avtopro_cross),
        ):
            if source_name not in loaded:
                loaded.append(source_name)
            for code, entry in entries_by_code.items():
                # Avto.pro's loader already validates the private KEMP card
                # binding.  Keep the source in the same private-code namespace
                # as the reference/site files; no fuzzy public-code join is
                # allowed here.
                by_code.setdefault(code, []).append(entry)

    for spareto_path in spareto_paths:
        spareto_numbers, spareto_skipped = load_spareto_source(spareto_path)
        if SPARETO_SOURCE not in loaded:
            loaded.append(SPARETO_SOURCE)
        mpn_only += spareto_skipped
        for code, entry in spareto_numbers.items():
            by_code.setdefault(code, []).append(entry)

    frozen_by_code = {code: tuple(entries) for code, entries in by_code.items()}
    frozen_owner_by_code = {
        code: tuple(entries) for code, entries in owner_by_code.items()
    }
    semantic_fanout_conflicts = public_number_semantic_conflicts(frozen_by_code)
    return SourceIndex(
        by_code=frozen_by_code,
        owner_by_code=frozen_owner_by_code,
        shared_articles=shared_article_numbers(articles_by_code),
        loaded_sources=tuple(loaded),
        reference_codes=reference_codes,
        mpn_only_rows=mpn_only,
        rows_without_code=without_code,
        supplier_number_claims=supplier_number_claims,
        owner_rows_read=owner_rows_read,
        owner_rows_bound=owner_rows_bound,
        owner_noise_rows=owner_noise_rows,
        owner_cards_bound=owner_cards_bound,
        owner_card_ambiguity_codes=owner_card_ambiguity_codes,
        semantic_conflicts=semantic_conflicts,
        semantic_fanout_conflicts=semantic_fanout_conflicts,
    )


# ------------------------------------------------------------------- planning


def _internal_catalog_codes(
    part_numbers_raw: Iterable[str], *, tokens: KempSiteTokensConfig
) -> tuple[str, ...]:
    codes = {
        normalized
        for value in part_numbers_raw
        if (normalized := normalize_cross_oem(value))
        and tokens.internal_code_pattern.fullmatch(normalized)
    }
    return tuple(sorted(codes))


def _own_export_numbers(
    part_numbers_raw: Iterable[str], *, tokens: KempSiteTokensConfig
) -> SourceNumbers | None:
    """Keep declared public numbers while removing private shelf join keys."""

    numbers = tuple(
        number
        for value in part_numbers_raw
        if value and value.strip()
        for number in article_numbers(value, own_code="", tokens=tokens)
        if not tokens.internal_code_pattern.fullmatch(normalize_cross_oem(number))
    )
    if not numbers:
        return None
    return SourceNumbers(
        extraction_method=OWN_EXPORT_SOURCE,
        numbers=numbers,
        raw_context="; ".join(numbers),
    )


def _owner_evidence_sources(
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[SourceNumbers, ...]:
    """Convert already-bound owner-card evidence into graph source entries."""

    entries: list[SourceNumbers] = []
    for item in evidence:
        raw = str(item.get("raw") or item.get("number") or "").strip()
        if not raw:
            continue
        source_url = str(item.get("source_url") or item.get("url") or "").strip()
        # Direct characteristics may become an owner REVIEW source only when
        # the caller proved the exact Prom card binding.  Loader-produced rows
        # carry a safe source_url; tests/other callers may state the same fact
        # explicitly with bound=true.  Unbound text is deliberately ignored.
        if source_url and not _owner_card_url_is_safe(source_url):
            continue
        if not source_url and item.get("bound") is not True:
            continue
        label = str(item.get("label") or "").strip()
        source_path = str(item.get("source_path") or "").strip()
        context = " | ".join(
            value
            for value in (
                f"label={label}" if label else "",
                f"source_url={source_url}" if source_url else "",
                f"source_path={source_path}" if source_path else "",
                f"publisher={item.get('publisher')}"
                if item.get("publisher")
                else "",
                f"source_version={item.get('source_version')}"
                if item.get("source_version")
                else "",
                f"content_sha256={item.get('content_sha256')}"
                if item.get("content_sha256")
                else "",
                f"source_file_sha256={item.get('source_file_sha256')}"
                if item.get("source_file_sha256")
                else "",
                f"parser_version={item.get('parser_version')}"
                if item.get("parser_version")
                else "",
                f"captured_at={item.get('captured_at')}"
                if item.get("captured_at")
                else "",
                f"card_title={item.get('card_title')}"
                if item.get("card_title")
                else "",
                f"card_brand={item.get('card_brand')}"
                if item.get("card_brand")
                else "",
            )
            if value
        )
        entries.append(
            SourceNumbers(
                extraction_method=OWN_STORE_LABELLED_OE_SOURCE,
                numbers=(raw,),
                raw_context=context,
            )
        )
    return tuple(entries)


def plan_identity(
    *,
    own_code: str,
    part_numbers_raw: Sequence[str],
    current_oe_norm: str,
    index: SourceIndex,
    config: IdentityGraphConfig,
    tokens: KempSiteTokensConfig,
    code_raw: str = "",
    owner_oe_evidence: Sequence[Mapping[str, Any]] = (),
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
    code_norm = normalize_cross_oem(code)
    is_internal = bool(code_norm and tokens.internal_code_pattern.fullmatch(code_norm))
    internal_codes = _internal_catalog_codes(part_numbers_raw, tokens=tokens)

    # The live export usually carries its stable 776... reference-book key in
    # ``Код запчастини``, while ``Код_товару`` already carries the public OE.
    # The old implementation looked only at the latter and therefore joined
    # merely 550 rows; worse, it emitted the former as a CONFIRMED cross.  One
    # recovered private code is unambiguous.  More than one must never be
    # guessed between.
    lookup_codes = [code_norm] if code_norm else []
    if len(internal_codes) == 1 and internal_codes[0] not in lookup_codes:
        lookup_codes.append(internal_codes[0])

    sources: list[SourceNumbers] = []
    owner_sources: list[SourceNumbers] = []
    source_semantic_conflicts = {
        lookup_code: index.semantic_conflicts[lookup_code]
        for lookup_code in lookup_codes
        if lookup_code in index.semantic_conflicts
    }
    for lookup_code in lookup_codes:
        sources.extend(index.by_code.get(lookup_code, ()))
    own_numbers = _own_export_numbers(part_numbers_raw, tokens=tokens)
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

    # Customer-owned detail cards are a separate, explicitly OE-labelled
    # source.  Join only exact code aliases already present in this row — never
    # by title, substring, shared article or a transitive graph path.
    owner_lookup_keys: list[str] = []
    for raw_key in (code, code_raw, *part_numbers_raw):
        for alias in _owner_code_aliases(str(raw_key)):
            if alias not in owner_lookup_keys:
                owner_lookup_keys.append(alias)
    owner_entries_seen: set[tuple[str, str, str]] = set()
    for owner_key in owner_lookup_keys:
        for owner_entry in index.owner_by_code.get(owner_key, ()):
            entry_key = (
                owner_entry.extraction_method,
                owner_entry.raw_context,
                owner_entry.numbers[0] if owner_entry.numbers else "",
            )
            if entry_key in owner_entries_seen:
                continue
            owner_entries_seen.add(entry_key)
            owner_sources.append(owner_entry)
    owner_sources.extend(_owner_evidence_sources(owner_oe_evidence))

    # Preserve every source's reviewer-openable context, not only the graph's
    # preferred context.  The canonical edge is usually the reference-map
    # article, while KEMP_SITE may carry the exact card URL/title/image that
    # corroborates it.  Keeping this as audit metadata avoids changing the
    # identity decision or importing any monetary field into pricing.
    source_contexts_by_number: dict[str, dict[str, str]] = {}
    for source in (*sources, *owner_sources):
        for raw_number in source.numbers:
            normalized = normalize_cross_oem(raw_number)
            if not normalized:
                continue
            source_contexts_by_number.setdefault(normalized, {}).setdefault(
                source.extraction_method, source.raw_context
            )

    graph = build_identity_graph(
        # Only a shelf number is a self reference.  Passing a real part number
        # here would delete from the graph the very number the gate searches by.
        own_code=(
            code_norm
            if is_internal
            else internal_codes[0]
            if len(internal_codes) == 1
            else ""
        ),
        sources=sources,
        config=config,
        shared_article_numbers=index.shared_articles,
        source_semantic_conflict=bool(source_semantic_conflicts),
        public_number_semantic_fanout=frozenset(
            index.semantic_fanout_conflicts
        ),
    )
    public_number_semantic_conflicts = {
        number: index.semantic_fanout_conflicts[number]
        for number in graph.all_numbers
        if number in index.semantic_fanout_conflicts
    }

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
                "confidence": (
                    CONFIRMED_IDENTITY_LINK_CONFIDENCE
                    if link.validation_status is LinkStatus.CONFIRMED
                    else "0"
                ),
                "automatic_eligible": (
                    link.validation_status is LinkStatus.CONFIRMED
                ),
                "own_code": code,
                "internal_catalog_codes": list(internal_codes),
                "reference_lookup_codes": lookup_codes,
                "owner_lookup_keys": owner_lookup_keys,
                "canonical_source": graph.canonical_source,
                "canonical_sources": list(graph.canonical_sources),
                "graph_anomalies": list(graph.anomalies),
                "sources_consulted": list(index.loaded_sources),
                "source_contexts": source_contexts_by_number.get(
                    link.extracted_oem_norm, {}
                ),
                "source_semantic_conflicts": source_semantic_conflicts,
                "public_number_semantic_conflicts": (
                    public_number_semantic_conflicts
                ),
                "semantic_feature_extractor_version": (
                    SEMANTIC_FEATURE_EXTRACTOR_VERSION
                ),
                "identity_graph_config_sha256": config.source_sha256,
                "token_config_sha256": tokens.source_sha256,
                "runtime_config_sha256": identity_runtime_config_sha256(config, tokens),
            },
        )
        for link in graph.links
    )

    status, reason = _identity_status(graph, config)
    fill_raw, fill_norm = _oe_to_fill(
        graph,
        config,
        current_oe_norm,
        tokens=tokens,
    )
    return ItemPlan(
        own_code=code,
        graph=graph,
        links=links,
        identity_status=status,
        identity_reason=reason,
        internal_catalog_codes=internal_codes,
        reference_lookup_codes=tuple(lookup_codes),
        fill_oe_raw=fill_raw,
        fill_oe_norm=fill_norm,
        source_contexts=source_contexts_by_number,
        owner_sources=tuple(owner_sources),
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

    def assertion_is_eligible(
        sources: Sequence[str], *, evidence_confirmed: bool
    ) -> bool:
        # A second source only corroborates an OE assertion when it also
        # asserts that the number is an OE.  A supplier article/cross list is
        # valid evidence that the number belongs to the same physical part,
        # but it cannot turn a medium-trust KEMP_SITE token into an OE merely
        # because both rows contain the same number.  The previous
        # ``len(sources) > 1`` rule did exactly that for KEMP_SITE +
        # KEMP_REFERENCE_ARTICLE and could fill the catalog OE from an
        # unlabelled site SKU.
        oe_sources = tuple(
            source for source in sources if config.sources[source].asserts_oe
        )
        return any(
            config.sources[source].asserts_oe
            and (
                config.sources[source].status is LinkStatus.CONFIRMED
                or (evidence_confirmed and len(oe_sources) > 1)
            )
            for source in oe_sources
        )

    found: list[tuple[str, str]] = []
    if (
        graph.canonical
        # Аномалия на ребре — сомнение в ребре, а не в якоре. Раньше здесь
        # стояло ``graph.anomalies``, собранное по всему графу, и позиция с
        # уверенно названным оригиналом оставалась закрытой из-за кросса,
        # висящего сбоку.  Ребро при этом всё равно не проходит: ниже стоит
        # ``link.is_confirmed``, а аномальное ребро понижено до REVIEW.
        and not graph.canonical_anomalies
        and assertion_is_eligible(
            graph.canonical_sources,
            evidence_confirmed=True,
        )
    ):
        found.append((graph.canonical, graph.canonical))
    for link in graph.links:
        # ``is_confirmed`` already covers a kemp.ua edge promoted by a second
        # source agreeing with it, which is corroboration rather than trust.
        if link.is_confirmed and assertion_is_eligible(
            link.corroborating_sources,
            evidence_confirmed=True,
        ):
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
    *,
    tokens: KempSiteTokensConfig,
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
    current = normalize_cross_oem(current_oe_norm)
    # Existing public identifiers belong to the customer's imported truth and
    # are never rewritten automatically.  The only non-empty value we are
    # authorised to repair is a proven private KEMP shelf code.
    if current and not tokens.internal_code_pattern.fullmatch(current):
        return "", ""
    normalized, raw = asserted[0]
    if normalized == current:
        return "", ""
    return raw, normalized


# ------------------------------------------------------------ database writing


async def reparse_workspace_identity(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    index: SourceIndex,
    config: IdentityGraphConfig,
    tokens: KempSiteTokensConfig,
    dry_run: bool = False,
    batch_size: int = 500,
) -> ReparseReport:
    """Apply the plan for every catalogue row of one workspace."""

    report = ReparseReport(dry_run=dry_run)
    existing = await _existing_link_keys(session, workspace_id=workspace_id)
    produced: set[tuple[UUID, str, str, str]] = set()

    if not dry_run:
        # Quarantine first, then restore every edge produced by the current
        # deterministic plan through the upsert below.  Both operations share
        # one transaction, so a failed partial reparse rolls back instead of
        # leaving a half-disabled graph.  This also handles catalog-row changes
        # where method/config hashes alone cannot distinguish an obsolete edge.
        await session.execute(
            update(CatalogIdentityLink)
            .where(CatalogIdentityLink.workspace_id == workspace_id)
            .values(
                validation_status=LinkStatus.REVIEW.value,
                anomaly=ANOMALY_STALE_AFTER_REPARSE,
            )
        )

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
            owner_evidence: tuple[Mapping[str, Any], ...] = ()
            if _owner_card_url_is_safe(item.product_url or ""):
                owner_evidence = tuple(
                    {
                        **evidence,
                        "source_url": item.product_url,
                        "bound": True,
                    }
                    for evidence in extract_labelled_original_oe_evidence(
                        item.characteristics_raw
                    )
                )
            plan = plan_identity(
                own_code=item.oe_norm or "",
                code_raw=item.oe_raw or "",
                part_numbers_raw=list(item.part_numbers_raw or ()),
                current_oe_norm=item.oe_norm or "",
                index=index,
                config=config,
                tokens=tokens,
                owner_oe_evidence=owner_evidence,
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
                        tokens=tokens,
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
    for _ in plan.internal_catalog_codes:
        _count(report.discard_counts, DISCARD_INTERNAL_CATALOG_CODE)
    if len(plan.internal_catalog_codes) > 1:
        _count(report.discard_counts, DISCARD_AMBIGUOUS_INTERNAL_CODES)


def _apply_item_fields(item: CatalogItem, plan: ItemPlan) -> None:
    item.identity_status = plan.identity_status
    item.identity_reason = plan.identity_reason
    if plan.fill_oe_norm:
        item.oe_raw = plan.fill_oe_raw
        item.oe_norm = plan.fill_oe_norm
    if plan.source_contexts:
        raw_row = dict(item.raw_row or {})
        raw_row["identity_provenance"] = {
            "canonical": plan.graph.canonical,
            "canonical_sources": list(plan.graph.canonical_sources),
            "source_contexts": {
                number: dict(contexts)
                for number, contexts in plan.source_contexts.items()
            },
            "canonical_source": plan.graph.canonical_source,
        }
        item.raw_row = raw_row


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
    tokens: KempSiteTokensConfig,
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
        "config_sha256": identity_runtime_config_sha256(config, tokens),
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
    "ANOMALY_STALE_AFTER_REPARSE",
    "OWN_EXPORT_CODE_SOURCE",
    "OWN_EXPORT_SOURCE",
    "OWN_STORE_LABELLED_OE_SOURCE",
    "DISCARD_AMBIGUOUS_INTERNAL_CODES",
    "DISCARD_INTERNAL_CATALOG_CODE",
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
    "load_owner_store_source",
    "supplier_articles_by_code",
    "site_semantic_conflicts",
    "plan_identity",
    "reparse_workspace_identity",
]
