"""Tell an OE apart from a supplier number in the KEMP reference map (WP-2).

The catalogue's original defect was substituting a supplier article for a
missing OE.  A number alone cannot say which it is — ``313856`` is a Sachs
article, ``443121251T`` is an Audi OE, and nothing in their shape separates
them.  The brand standing next to the article says it: a number branded by a
vehicle maker is an OE, a number branded by a component supplier is an MPN.

So the whole package rests on one dictionary, ``article_brand_kinds.yaml``, and
on refusing to guess when the dictionary has no answer.  An unknown brand does
not become an OE by default; the position closes as ``MPN_ONLY`` with an empty
``oe_norm``.  Losing an OE costs one unresolved position, inventing one puts a
wrong number into the price comparison (NO_5).
"""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from metis.pricing.crosses import normalize_cross_oem
from metis.pricing.kemp_site import (
    KempSiteTokensConfig,
    extract_numbers,
    known_number_set,
)

ARTICLE_BRAND_KINDS_SCHEMA_VERSION = "metis-article-brand-kinds-v1"

#: There is no single reference-map source any more.  The customer keeps sending
#: new editions of the same book — "the first file is a year old, the second is
#: from yesterday" (2026-07-30) — and each edition is its own source, because a
#: number that changed between them is a supersession and not a disagreement.
#:
#: Which edition a file is, is decided by the sha256 of its bytes through
#: ``identity_graph.yaml``: see ``IdentityGraphConfig.source_for_dataset``.  A
#: constant here would have to name one edition and be wrong about the others.
EXTRACTION_METHOD_PREFIX = "KEMP_REFERENCE_MAP"


class KempReferenceError(ValueError):
    """The brand dictionary or the reference map is unusable as given."""


class BrandKind(str, Enum):
    """What the value of the ``фирма по артикулу`` column turned out to be."""

    VEHICLE_MANUFACTURER = "VEHICLE_MANUFACTURER"
    AFTERMARKET = "AFTERMARKET"
    #: Stands in the brand column but names no manufacturer ("China").
    NOT_A_BRAND = "NOT_A_BRAND"
    #: Absent from the dictionary, or the column was empty.  Never a guess.
    UNKNOWN = "UNKNOWN"


class IdentityStatus(str, Enum):
    OE_CONFIRMED = "OE_CONFIRMED"
    MPN_ONLY = "MPN_ONLY"
    #: The row has not been through resolution yet — every catalog row imported
    #: before WP-2, until the WP-6 reparse reaches it.  Distinct from
    #: ``MPN_ONLY``, which records a decision that the article is not an OE;
    #: collapsing the two would report 4646 judgements that were never made.
    UNRESOLVED = "UNRESOLVED"


#: Why the row ended where it did — carried into ``validation_details`` so a
#: human can re-judge the decision without re-running anything.
class IdentityReason(str, Enum):
    BRAND_IS_VEHICLE_MANUFACTURER = "BRAND_IS_VEHICLE_MANUFACTURER"
    BRAND_IS_AFTERMARKET = "BRAND_IS_AFTERMARKET"
    BRAND_NOT_A_BRAND = "BRAND_NOT_A_BRAND"
    BRAND_UNKNOWN = "BRAND_UNKNOWN"
    ARTICLE_EMPTY = "ARTICLE_EMPTY"
    ARTICLE_IS_INTERNAL_CODE = "ARTICLE_IS_INTERNAL_CODE"
    #: The 2026-07-29 layout stated the OE in its own column and the value
    #: survived shape classification.
    OE_COLUMN = "OE_COLUMN"
    #: That column held only our internal code or a supplier number.
    OE_COLUMN_NOT_AN_OE = "OE_COLUMN_NOT_AN_OE"


@dataclass(frozen=True)
class ArticleBrandKinds:
    """The brand dictionary, hashed so every link can name its evidence."""

    method_version: str
    kinds: Mapping[str, BrandKind]
    source_path: str
    source_sha256: str

    def kind_of(self, brand: str | None) -> BrandKind:
        if not brand or not brand.strip():
            return BrandKind.UNKNOWN
        return self.kinds.get(normalize_brand_value(brand), BrandKind.UNKNOWN)


@dataclass(frozen=True)
class ReferenceRow:
    """One row of the reference map, as read.

    Two workbook revisions are in use and neither is a superset of the other.
    The 2026-07-28 export carries ``article_brand`` and no OE column; the
    2026-07-29 one carries ``oe`` and dropped the brand.  Both are kept and
    joined on ``mpn``, so a row from either reads through this one shape with
    the columns its source lacks left empty.
    """

    name: str
    mpn: str
    make: str = ""
    article: str = ""
    article_brand: str = ""
    #: Present only in the 2026-07-29 layout, and not to be trusted on its own:
    #: the measurement of that file found 810 internal codes and 344 supplier
    #: numbers sitting in this column.  It is classified, never copied.
    oe: str = ""


@dataclass(frozen=True)
class ReferenceMap:
    rows: tuple[ReferenceRow, ...]
    dataset_id: str
    source_path: str
    source_sha256: str


@dataclass(frozen=True)
class ResolvedIdentity:
    """What a reference row says about one internal code."""

    mpn: str
    identity_status: IdentityStatus
    reason: IdentityReason
    brand_kind: BrandKind
    article_brand: str
    oe_raw: str = ""
    oe_norm: str = ""
    mpn_raw: str = ""
    mpn_norm: str = ""

    @property
    def has_oe(self) -> bool:
        return bool(self.oe_norm)


def normalize_brand_value(value: str) -> str:
    """Fold a brand string to its lookup key.

    Case and inner spacing vary between exports (``GKN-Spidan`` /
    ``GKN - Spidan``); the marque does not.  Punctuation is kept, because
    ``K+F`` and ``K&K`` are different suppliers and stripping it merges them.
    """

    folded = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"\s+", " ", folded)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KempReferenceError(f"{name} must be a non-empty string")
    return value.strip()


_KIND_SECTIONS: tuple[tuple[str, BrandKind], ...] = (
    ("vehicle_manufacturer", BrandKind.VEHICLE_MANUFACTURER),
    ("aftermarket", BrandKind.AFTERMARKET),
    ("not_a_brand", BrandKind.NOT_A_BRAND),
)


def load_article_brand_kinds(path: str | Path) -> ArticleBrandKinds:
    """Load the brand dictionary, refusing anything it cannot vouch for."""

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise KempReferenceError(f"Brand kinds config does not exist: {source_path}")
    raw = source_path.read_bytes()
    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise KempReferenceError("Brand kinds config is not valid YAML") from exc
    if not isinstance(payload, dict):
        raise KempReferenceError("Brand kinds config root must be a mapping")
    if payload.get("schema_version") != ARTICLE_BRAND_KINDS_SCHEMA_VERSION:
        raise KempReferenceError(
            f"Unsupported brand kinds schema: {payload.get('schema_version')!r}"
        )

    kinds: dict[str, BrandKind] = {}
    seen_raw: dict[str, str] = {}
    for section, kind in _KIND_SECTIONS:
        entries = payload.get(section)
        if not isinstance(entries, list) or not entries:
            raise KempReferenceError(f"{section} must be a non-empty list")
        for entry in entries:
            if not isinstance(entry, dict):
                raise KempReferenceError(f"each {section} entry must be a mapping")
            name = _text(entry.get("name"), f"{section} entry name")
            key = normalize_brand_value(name)
            if key in seen_raw:
                # Two sections claiming the same brand is not a merge conflict
                # to resolve quietly: one of them is wrong about whether that
                # brand's numbers are OEs.
                raise KempReferenceError(
                    f"Brand {name!r} is classified twice "
                    f"(also as {seen_raw[key]!r})"
                )
            seen_raw[key] = name
            kinds[key] = kind

    return ArticleBrandKinds(
        method_version=_text(payload.get("method_version"), "method_version"),
        kinds=MappingProxyType(kinds),
        source_path=str(source_path),
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )


#: Without these the file identifies nothing and cannot be joined.
_REQUIRED_COLUMNS = ("name", "mpn")
#: Supplied by one workbook revision or the other, never by both.
_OPTIONAL_COLUMNS = ("make", "article", "article_brand", "oe")


def load_kemp_reference_map(path: str | Path) -> ReferenceMap:
    """Read a converted reference map of either layout and hash it as shipped."""

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise KempReferenceError(f"Reference map does not exist: {source_path}")
    raw = source_path.read_bytes()
    with source_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        present = reader.fieldnames or []
        missing = [column for column in _REQUIRED_COLUMNS if column not in present]
        if missing:
            raise KempReferenceError(
                f"Reference map is missing columns: {', '.join(missing)}"
            )
        if "article_brand" not in present and "oe" not in present:
            # A file with neither the brand of the article nor an OE column can
            # say nothing about identity at all; reading it would produce 7000
            # MPN_ONLY rows that look like decisions.
            raise KempReferenceError(
                "Reference map has neither article_brand nor oe; it carries no "
                "identity evidence"
            )
        columns = _REQUIRED_COLUMNS + tuple(
            column for column in _OPTIONAL_COLUMNS if column in present
        )
        rows = tuple(
            ReferenceRow(**{column: (row.get(column) or "").strip() for column in columns})
            for row in reader
        )

    digest = hashlib.sha256(raw).hexdigest()
    return ReferenceMap(
        rows=rows,
        dataset_id=f"kemp_reference_map:{digest[:16]}",
        source_path=str(source_path),
        source_sha256=digest,
    )


def resolve_identity(
    row: ReferenceRow,
    *,
    kinds: ArticleBrandKinds,
    tokens: KempSiteTokensConfig,
) -> ResolvedIdentity:
    """Decide whether this row carries an OE, an MPN, or neither.

    ``tokens`` is the shared number-shape config (``kemp_site_tokens.yaml``)
    rather than a private copy: the shape of a KEMP internal code and of a
    supplier number must mean the same thing here as on the site cards, or the
    two sources would disagree for no reason but drift.
    """

    article = row.article.strip()
    brand_kind = kinds.kind_of(row.article_brand)
    internal_code_pattern = tokens.internal_code_pattern

    def closed(reason: IdentityReason) -> ResolvedIdentity:
        return ResolvedIdentity(
            mpn=row.mpn,
            identity_status=IdentityStatus.MPN_ONLY,
            reason=reason,
            brand_kind=brand_kind,
            article_brand=row.article_brand,
            mpn_raw=article if article and not internal_code_pattern.match(article) else "",
            mpn_norm=(
                normalize_cross_oem(article)
                if article and not internal_code_pattern.match(article)
                else ""
            ),
        )

    # The 2026-07-29 layout states the OE outright, which is stronger evidence
    # than inferring it from the brand beside the article.  It is still only
    # evidence: that column also holds internal codes and supplier numbers, so
    # the value is classified by shape exactly as a number off a site card is.
    if row.oe.strip():
        candidates = extract_numbers(
            [("oe", row.oe)],
            config=tokens,
            known=known_number_set([row.mpn, article], tokens),
        ).oe_candidates
        if candidates:
            return ResolvedIdentity(
                mpn=row.mpn,
                identity_status=IdentityStatus.OE_CONFIRMED,
                reason=IdentityReason.OE_COLUMN,
                brand_kind=brand_kind,
                article_brand=row.article_brand,
                oe_raw=candidates[0].raw,
                oe_norm=candidates[0].normalized,
                mpn_raw=article,
                mpn_norm=normalize_cross_oem(article) if article else "",
            )
        if not row.article_brand.strip():
            # The column existed and held nothing usable — our own code or a
            # supplier number.  That is a different fact from "no brand told
            # us": on this layout there is no brand column to consult at all,
            # and reporting BRAND_UNKNOWN would send a reviewer looking for a
            # dictionary entry that could never have helped.
            return closed(IdentityReason.OE_COLUMN_NOT_AN_OE)

    # These two checks run before the brand is consulted. In 11 rows of the
    # 2026-07-28 map the brand column names a vehicle maker while the article
    # cell is empty or literally repeats the internal code: the brand describes
    # an article that is not there, and trusting it would mint an OE out of our
    # own warehouse code.
    if not article:
        return closed(IdentityReason.ARTICLE_EMPTY)
    if internal_code_pattern.match(article) or normalize_cross_oem(
        article
    ) == normalize_cross_oem(row.mpn):
        return closed(IdentityReason.ARTICLE_IS_INTERNAL_CODE)

    if brand_kind is BrandKind.VEHICLE_MANUFACTURER:
        return ResolvedIdentity(
            mpn=row.mpn,
            identity_status=IdentityStatus.OE_CONFIRMED,
            reason=IdentityReason.BRAND_IS_VEHICLE_MANUFACTURER,
            brand_kind=brand_kind,
            article_brand=row.article_brand,
            oe_raw=article,
            oe_norm=normalize_cross_oem(article),
        )

    reason = {
        BrandKind.AFTERMARKET: IdentityReason.BRAND_IS_AFTERMARKET,
        BrandKind.NOT_A_BRAND: IdentityReason.BRAND_NOT_A_BRAND,
        BrandKind.UNKNOWN: IdentityReason.BRAND_UNKNOWN,
    }[brand_kind]
    return ResolvedIdentity(
        mpn=row.mpn,
        identity_status=IdentityStatus.MPN_ONLY,
        reason=reason,
        brand_kind=brand_kind,
        article_brand=row.article_brand,
        mpn_raw=article,
        mpn_norm=normalize_cross_oem(article),
    )


def resolve_all(
    reference: ReferenceMap,
    *,
    kinds: ArticleBrandKinds,
    tokens: KempSiteTokensConfig,
) -> tuple[ResolvedIdentity, ...]:
    return tuple(
        resolve_identity(row, kinds=kinds, tokens=tokens) for row in reference.rows
    )


def unknown_brand_values(
    reference: ReferenceMap, kinds: ArticleBrandKinds
) -> tuple[str, ...]:
    """Brand values the dictionary does not classify, for the import report.

    An empty result is the contract for the shipped pair of files; a non-empty
    one after a reference-map update is the signal that a human must extend the
    dictionary, not that the import should improvise.
    """

    unknown = {
        row.article_brand.strip()
        for row in reference.rows
        if row.article_brand.strip()
        and kinds.kind_of(row.article_brand) is BrandKind.UNKNOWN
    }
    return tuple(sorted(unknown))


def validation_details(
    identity: ResolvedIdentity,
    *,
    reference: ReferenceMap,
    kinds: ArticleBrandKinds,
    extraction_method: str,
) -> dict[str, str]:
    """Evidence stamped on every link built from this source.

    Mirrors ``brand_rules_dataset_id`` / ``brand_rules_sha256`` in
    ``catalog_discovery.py`` so an auditor reads one shape everywhere.

    ``extraction_method`` is passed in rather than assumed: which edition of the
    reference book this row came from is a fact about the file, resolved from its
    hash by ``IdentityGraphConfig.source_for_dataset``, and a default here would
    quietly stamp the wrong edition on a link that outlives the run.
    """

    if not extraction_method.startswith(EXTRACTION_METHOD_PREFIX):
        raise KempReferenceError(
            f"{extraction_method!r} is not a reference-map source"
        )
    return {
        "extraction_method": extraction_method,
        "identity_status": identity.identity_status.value,
        "identity_reason": identity.reason.value,
        "article_brand": identity.article_brand,
        "article_brand_kind": identity.brand_kind.value,
        "reference_map_dataset_id": reference.dataset_id,
        "reference_map_sha256": reference.source_sha256,
        "article_brand_kinds_sha256": kinds.source_sha256,
        "article_brand_kinds_method_version": kinds.method_version,
    }
