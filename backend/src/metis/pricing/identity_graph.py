"""Build the number graph of one catalog item (WP-3).

A product is not one number.  The same brake hose is our internal ``77641229``,
Boge's ``27C06F`` and VAG's ``1K0413031BK``, and a competitor may list it under
any of them.  WP-4 searches the marketplace by every number in the graph, and
the candidate gate accepts an offer whose OE differs from ours only when a
*confirmed* edge says the two numbers are the same part.

Three properties of this module are deliberate and each of them is a decision
that could have gone the other way:

**A star, not a clique.**  Edges run from the item's canonical number to each
other number, and never between two non-canonical numbers.  Transitivity
(A↔B, B↔C ⇒ A↔C) is not introduced here: it multiplies the chance of fusing two
different parts, and one wrong fusion means recommending a price based on
somebody else's component.

**Never ``REJECTED``.**  These sources can fail to know something; they cannot
disprove it.  The worst status a link gets is ``REVIEW``, and a ``REVIEW`` link
moves no price.

**Conflicts are kept, not resolved.**  When two sources give different OEs for
one item, both edges survive and both are flagged.  Silently keeping one would
throw away the case where the number was superseded and the *other* source is
the right one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from metis.pricing.crosses import normalize_cross_oem

IDENTITY_GRAPH_SCHEMA_VERSION = "metis-identity-graph-v1"


class IdentityGraphConfigError(ValueError):
    """The graph configuration is absent, malformed or of an unknown schema."""


class LinkStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    REVIEW = "REVIEW"


class Anomaly(str, Enum):
    #: Site and reference map disagree about this item's OE.
    OE_SOURCE_CONFLICT = "OE_SOURCE_CONFLICT"
    #: One normalized article belongs to several internal codes.
    SHARED_ARTICLE_FANOUT = "SHARED_ARTICLE_FANOUT"
    #: An older edition of the same reference book named a different OE, and the
    #: newer one is preferred.  Not a conflict: the customer told us which file is
    #: current, so this is a supersession with a known direction.
    OE_SUPERSEDED_BY_NEWER_REFERENCE = "OE_SUPERSEDED_BY_NEWER_REFERENCE"
    #: Two declared revisions joined by the same private catalogue key describe
    #: physically incompatible parts (for example left versus right).  The key
    #: can no longer prove that numbers from those rows belong to one identity.
    SOURCE_SEMANTIC_CONFLICT = "SOURCE_SEMANTIC_CONFLICT"
    #: One public number is assigned to structurally incompatible catalog
    #: identities, including canonical-only graphs with no edge to annotate.
    PUBLIC_NUMBER_SEMANTIC_FANOUT = "PUBLIC_NUMBER_SEMANTIC_FANOUT"
    #: Historical edge absent from the latest atomic workspace reparse.
    STALE_AFTER_REPARSE = "STALE_AFTER_REPARSE"


class CanonicalRule(str, Enum):
    SOURCE_PREFERENCE = "SOURCE_PREFERENCE"
    LEXICOGRAPHIC = "LEXICOGRAPHIC"


#: A rule that puts any two distinct numbers in a definite order.  The rule
#: chain must end in one of these, or two runs over the same data could pick
#: different canonical numbers and the graph would stop being reproducible.
_TOTAL_ORDER_RULES = frozenset({CanonicalRule.LEXICOGRAPHIC})


@dataclass(frozen=True)
class SourceRule:
    name: str
    status: LinkStatus
    #: Whether this source answers "what is *this part's* OE".  Only such
    #: sources can contradict each other; a list of crosses that happens not to
    #: mention a number is not an objection to it.
    asserts_oe: bool
    #: Who published it.  Two editions of one publisher's reference book are the
    #: same voice a year apart, not two voices disagreeing.
    publisher: str
    #: Delivery order within the publisher, higher being more recent.  An ordinal
    #: rather than a date: the customer said "one is a year old, the other is from
    #: yesterday", which fixes the order and nothing finer.
    vintage: int


@dataclass(frozen=True)
class IdentityGraphConfig:
    method_version: str
    #: Source name → its rule, in declaration order, which is the order of how
    #: reliable the *statement* is and therefore what status a link gets.
    sources: Mapping[str, SourceRule]
    #: Preference order for the graph's anchor — a different question, answered
    #: by which number best identifies the part rather than by who said it.
    canonical_source_preference: tuple[str, ...]
    canonical_rules: tuple[CanonicalRule, ...]
    anomalies_requiring_review: frozenset[str]
    source_sha256: str
    #: sha256 of a dataset's raw bytes → the source it counts as.  Keyed on the
    #: hash because a filename guarantees nothing about contents.
    datasets: Mapping[str, str] = MappingProxyType({})

    @property
    def trust_order(self) -> tuple[str, ...]:
        return tuple(self.sources)

    def source_for_dataset(self, sha256: str) -> str:
        """Which declared source a file is, or a refusal.

        Fail-closed on purpose: an unrecognised reference book must not inherit
        the standing of one that was checked against a control sample.
        """

        key = sha256.strip().lower()
        try:
            return self.datasets[key]
        except KeyError as exc:
            raise IdentityGraphConfigError(
                f"No declared dataset with sha256 {key!r}"
            ) from exc

    def trust_index(self, source: str) -> int:
        try:
            return self.trust_order.index(source)
        except ValueError as exc:  # pragma: no cover - guarded by callers
            raise IdentityGraphConfigError(f"Unknown source: {source}") from exc

    def canonical_index(self, source: str) -> int:
        try:
            return self.canonical_source_preference.index(source)
        except ValueError as exc:  # pragma: no cover - guarded by callers
            raise IdentityGraphConfigError(f"Unknown source: {source}") from exc


@dataclass(frozen=True)
class SourceNumbers:
    """Numbers one source offers for one item, in the form the source gave."""

    extraction_method: str
    numbers: tuple[str, ...]
    #: The original text the numbers were read out of — the audit evidence that
    #: lets a human re-judge the decision by eye.
    raw_context: str = ""


@dataclass(frozen=True)
class IdentityLink:
    """One edge, ready to be written as a ``catalog_identity_links`` row."""

    our_oem_norm: str
    extracted_oem_norm: str
    extraction_method: str
    validation_status: LinkStatus
    raw_context: str
    extracted_raw: str
    anomaly: str | None = None
    #: Every source that produced this same pair, sorted.  Two independent
    #: sources agreeing is the only automatic way a ``KEMP_SITE`` edge becomes
    #: ``CONFIRMED``.
    corroborating_sources: tuple[str, ...] = ()

    @property
    def is_confirmed(self) -> bool:
        return self.validation_status is LinkStatus.CONFIRMED


@dataclass(frozen=True)
class IdentityGraph:
    canonical: str
    canonical_source: str | None
    #: Every source that named the anchor, in trust order.  Keeping only the
    #: first source loses a trusted OE assertion whenever the same number also
    #: appears in the non-asserting own-export code column.
    canonical_sources: tuple[str, ...] = ()
    links: tuple[IdentityLink, ...] = ()
    anomalies: tuple[str, ...] = ()
    #: Подмножество ``anomalies``, ставящее под сомнение именно якорь.
    #: Аномалия на ребре — это сомнение в ребре: общий артикул поставщика,
    #: принадлежащий нескольким нашим кодам, не является возражением против
    #: оригинального номера, который справочник назвал для этой позиции.
    #: Ворота, пускающие номер в колонку OE, смотрят сюда; ручной разбор —
    #: по-прежнему в ``anomalies``, оттуда не исчезает ничего.
    canonical_anomalies: tuple[str, ...] = ()
    #: Numbers that were dropped and why — never silent.
    discarded: Mapping[str, str] = field(default_factory=dict)

    @property
    def confirmed_numbers(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {link.extracted_oem_norm for link in self.links if link.is_confirmed}
            )
        )

    @property
    def all_numbers(self) -> tuple[str, ...]:
        numbers = {link.extracted_oem_norm for link in self.links}
        if self.canonical:
            numbers.add(self.canonical)
        return tuple(sorted(numbers))


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IdentityGraphConfigError(f"{name} must be a non-empty string")
    return value.strip()


def _reject_duplicate_vintages(sources: Mapping[str, SourceRule]) -> None:
    """Two sources cannot share a publisher and a vintage.

    Supersession is decided by comparing vintages, so a tie inside one publisher
    would leave the direction undefined and the result dependent on input order.
    """

    seen: dict[tuple[str, int], str] = {}
    for rule in sources.values():
        key = (rule.publisher, rule.vintage)
        if key in seen:
            raise IdentityGraphConfigError(
                f"{rule.name} and {seen[key]} share publisher {rule.publisher!r} "
                f"and vintage {rule.vintage}"
            )
        seen[key] = rule.name


_SHA256_LENGTH = 64


def _parse_datasets(payload: Any, sources: Mapping[str, SourceRule]) -> dict[str, str]:
    entries = payload.get("datasets")
    if entries is None:
        return {}
    if not isinstance(entries, list) or not entries:
        raise IdentityGraphConfigError("datasets must be a non-empty list when present")
    datasets: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise IdentityGraphConfigError("each dataset must be a mapping")
        digest = _text(entry.get("sha256"), "dataset sha256").lower()
        if len(digest) != _SHA256_LENGTH or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise IdentityGraphConfigError(
                f"dataset sha256 must be 64 hex characters, got {digest!r}"
            )
        if digest in datasets:
            raise IdentityGraphConfigError(f"Duplicate dataset sha256: {digest}")
        source = _text(entry.get("source"), f"dataset {digest[:12]}.source")
        if source not in sources:
            raise IdentityGraphConfigError(
                f"dataset {digest[:12]} names undeclared source {source!r}"
            )
        datasets[digest] = source
    return datasets


def load_identity_graph_config(path: str | Path) -> IdentityGraphConfig:
    """Load and hash the graph configuration, refusing anything unexpected."""

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise IdentityGraphConfigError(f"Graph config does not exist: {source_path}")
    raw = source_path.read_bytes()
    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise IdentityGraphConfigError("Graph config is not valid YAML") from exc
    if not isinstance(payload, dict):
        raise IdentityGraphConfigError("Graph config root must be a mapping")
    if payload.get("schema_version") != IDENTITY_GRAPH_SCHEMA_VERSION:
        raise IdentityGraphConfigError(
            f"Unsupported graph config schema: {payload.get('schema_version')!r}"
        )

    entries = payload.get("sources")
    if not isinstance(entries, list) or not entries:
        raise IdentityGraphConfigError("sources must be a non-empty list")
    sources: dict[str, SourceRule] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise IdentityGraphConfigError("each source must be a mapping")
        name = _text(entry.get("name"), "source name")
        if name in sources:
            raise IdentityGraphConfigError(f"Duplicate source: {name}")
        status_text = _text(entry.get("status"), f"{name}.status")
        try:
            status = LinkStatus(status_text)
        except ValueError as exc:
            # REJECTED is not merely unsupported here, it is forbidden: absence
            # of data from these sources is not disproof of a link.
            raise IdentityGraphConfigError(
                f"{name}.status must be CONFIRMED or REVIEW, got {status_text!r}"
            ) from exc
        asserts_oe = entry.get("asserts_oe")
        if not isinstance(asserts_oe, bool):
            raise IdentityGraphConfigError(f"{name}.asserts_oe must be a boolean")
        publisher = _text(entry.get("publisher"), f"{name}.publisher")
        vintage = entry.get("vintage")
        if isinstance(vintage, bool) or not isinstance(vintage, int) or vintage < 1:
            raise IdentityGraphConfigError(f"{name}.vintage must be an integer >= 1")
        sources[name] = SourceRule(
            name=name,
            status=status,
            asserts_oe=asserts_oe,
            publisher=publisher,
            vintage=vintage,
        )
    _reject_duplicate_vintages(sources)

    rule_names = payload.get("canonical", {})
    if not isinstance(rule_names, dict):
        raise IdentityGraphConfigError("canonical must be a mapping")
    raw_preference = rule_names.get("source_preference")
    if not isinstance(raw_preference, list):
        raise IdentityGraphConfigError("canonical.source_preference must be a list")
    preference = tuple(_text(name, "canonical source") for name in raw_preference)
    if sorted(preference) != sorted(sources):
        # A source missing from the preference list could never anchor a graph,
        # and one that is not a declared source would silently never match.
        raise IdentityGraphConfigError(
            "canonical.source_preference must list every source exactly once: "
            f"{sorted(sources)}"
        )

    raw_rules = rule_names.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise IdentityGraphConfigError("canonical.rules must be a non-empty list")
    rules: list[CanonicalRule] = []
    for name in raw_rules:
        try:
            rule = CanonicalRule(_text(name, "canonical rule"))
        except ValueError as exc:
            raise IdentityGraphConfigError(f"Unknown canonical rule: {name!r}") from exc
        if rule in rules:
            raise IdentityGraphConfigError(f"Duplicate canonical rule: {rule.value}")
        rules.append(rule)
    if rules[-1] not in _TOTAL_ORDER_RULES:
        # Without a total order at the end, two numbers the earlier rules cannot
        # separate would be ordered by whatever the input happened to look like,
        # and the same catalogue would produce different graphs on two runs.
        raise IdentityGraphConfigError(
            "canonical.rules must end in a rule that fully orders any two "
            f"numbers, one of: {sorted(rule.value for rule in _TOTAL_ORDER_RULES)}"
        )

    anomaly_entries = payload.get("anomalies")
    if not isinstance(anomaly_entries, list) or not anomaly_entries:
        raise IdentityGraphConfigError("anomalies must be a non-empty list")
    review_required: set[str] = set()
    for entry in anomaly_entries:
        if not isinstance(entry, dict):
            raise IdentityGraphConfigError("each anomaly must be a mapping")
        name = _text(entry.get("name"), "anomaly name")
        try:
            Anomaly(name)
        except ValueError as exc:
            raise IdentityGraphConfigError(f"Unknown anomaly: {name!r}") from exc
        if entry.get("review_required") is not True:
            # An anomaly that does not require review is a note nobody reads.
            raise IdentityGraphConfigError(f"{name}.review_required must be true")
        review_required.add(name)

    return IdentityGraphConfig(
        method_version=_text(payload.get("method_version"), "method_version"),
        sources=MappingProxyType(sources),
        canonical_source_preference=preference,
        canonical_rules=tuple(rules),
        anomalies_requiring_review=frozenset(review_required),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        datasets=MappingProxyType(_parse_datasets(payload, sources)),
    )


#: Reasons a number never made it into the graph.  Every one of them is
#: reported rather than dropped, because a number silently missing from the
#: graph looks exactly like a part nobody sells.
DISCARD_SELF_REFERENCE = "SELF_REFERENCE"
DISCARD_EMPTY_AFTER_NORMALIZATION = "EMPTY_AFTER_NORMALIZATION"
DISCARD_UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
DISCARD_UNSAFE_PUBLIC_NUMBER_SHAPE = "UNSAFE_PUBLIC_NUMBER_SHAPE"


def is_safe_public_number_shape(normalized: str) -> bool:
    """Whether a normalized value can be a public automotive identifier.

    This is intentionally only a shape guard, not a brand-specific catalogue
    guess. Genuine identifiers may be short, but a one-character token, an
    all-zero placeholder or text with no digit is not safe as a global graph
    node.
    """

    return bool(
        len(normalized) >= 2
        and any(character.isdigit() for character in normalized)
        and set(normalized) != {"0"}
    )


def _candidates(
    sources: Sequence[SourceNumbers], config: IdentityGraphConfig
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Normalize every offered number, keeping its sources and raw forms."""

    seen: dict[str, dict[str, Any]] = {}
    discarded: dict[str, str] = {}
    for source in sources:
        if source.extraction_method not in config.sources:
            for number in source.numbers:
                discarded[number] = DISCARD_UNKNOWN_SOURCE
            continue
        for number in source.numbers:
            normalized = normalize_cross_oem(number)
            if not normalized:
                discarded[number] = DISCARD_EMPTY_AFTER_NORMALIZATION
                continue
            # A public identifier must carry at least one digit.  Bare editor
            # notes and suffix fragments such as ``MG``, ``L`` or
            # ``Fiat/Alfa/Lancia`` used to become global graph nodes and could
            # join unrelated catalogue rows.  Keep short genuine identifiers
            # such as ``KL2``, ``S5G`` and ``04``: length alone is not evidence
            # that an automotive part number is invalid.
            if not is_safe_public_number_shape(normalized):
                discarded[number] = DISCARD_UNSAFE_PUBLIC_NUMBER_SHAPE
                continue
            entry = seen.setdefault(
                normalized,
                {"raw": number, "sources": set(), "contexts": {}},
            )
            entry["sources"].add(source.extraction_method)
            entry["contexts"].setdefault(source.extraction_method, source.raw_context)
    return seen, discarded


def _best_source(sources: Iterable[str], config: IdentityGraphConfig) -> str:
    return min(sources, key=config.trust_index)


def _sources_disagree(
    candidates: Mapping[str, Mapping[str, Any]],
    config: IdentityGraphConfig,
    *,
    superseded: frozenset[str] = frozenset(),
) -> bool:
    """Do two OE-asserting sources name numbers with nothing in common?

    Overlap is agreement plus extra knowledge, and extra knowledge is welcome:
    the reference map routinely supplies an OE the seller never wrote down.
    Disjoint claims are the disagreement — ``77647977``, where the map says
    ``7701059269`` and the card says ``7701050685``.  Both may be real; one may
    supersede the other; nothing in our data can tell, so a human is told.
    """

    claims = _oe_claims(candidates, config)
    # A superseded edition argues with nobody.  Leaving it in would let a
    # year-old number contradict the site and reopen as a conflict the very case
    # the recency rule just settled.
    names = sorted(name for name in claims if name not in superseded)
    return any(
        claims[left].isdisjoint(claims[right])
        # Two editions of one publisher's book are one voice a year apart. Their
        # differences are supersessions with a known direction, reported as
        # ``OE_SUPERSEDED_BY_NEWER_REFERENCE``, and calling them a conflict would
        # keep 158 positions unresolvable for a reason the customer has resolved.
        and config.sources[left].publisher != config.sources[right].publisher
        for index, left in enumerate(names)
        for right in names[index + 1 :]
    )


def _oe_claims(
    candidates: Mapping[str, Mapping[str, Any]], config: IdentityGraphConfig
) -> dict[str, set[str]]:
    """Which numbers each OE-asserting source names for this item."""

    claims: dict[str, set[str]] = {}
    for number, entry in candidates.items():
        for source in entry["sources"]:
            if config.sources[source].asserts_oe:
                claims.setdefault(source, set()).add(number)
    return claims


def _superseded_sources(
    candidates: Mapping[str, Mapping[str, Any]], config: IdentityGraphConfig
) -> frozenset[str]:
    """Sources this item has a newer edition of, from the same publisher.

    Only sources that actually named something for *this* item count: a newer
    book that says nothing here supersedes nothing here, because absence of data
    is not disproof — the same principle that keeps ``REJECTED`` out of this
    module.
    """

    present = set(_oe_claims(candidates, config))
    newest: dict[str, int] = {}
    for name in present:
        rule = config.sources[name]
        newest[rule.publisher] = max(newest.get(rule.publisher, 0), rule.vintage)
    return frozenset(
        name
        for name in present
        if config.sources[name].vintage < newest[config.sources[name].publisher]
    )


def choose_canonical(
    candidates: Mapping[str, Mapping[str, Any]], config: IdentityGraphConfig
) -> tuple[str, str | None]:
    """Pick the anchor number, deterministically and without pretending.

    Between two genuine OEs of one part there is no substantive winner — the
    vehicle maker shipped the part under both numbers — so once the trust rule
    stops separating them the tie is broken by a stable arbitrary rule.  The
    choice does not narrow the search: WP-4 queries every number in the graph.
    """

    if not candidates:
        return "", None

    def key(number: str) -> tuple[Any, ...]:
        entry = candidates[number]
        parts: list[Any] = []
        for rule in config.canonical_rules:
            if rule is CanonicalRule.SOURCE_PREFERENCE:
                parts.append(
                    min(config.canonical_index(source) for source in entry["sources"])
                )
            elif rule is CanonicalRule.LEXICOGRAPHIC:
                parts.append(number)
        return tuple(parts)

    canonical = min(candidates, key=key)
    return canonical, _best_source(candidates[canonical]["sources"], config)


def build_identity_graph(
    *,
    own_code: str,
    sources: Sequence[SourceNumbers],
    config: IdentityGraphConfig,
    shared_article_numbers: frozenset[str] = frozenset(),
    source_semantic_conflict: bool = False,
    public_number_semantic_fanout: frozenset[str] = frozenset(),
) -> IdentityGraph:
    """Turn what every source says about one item into a set of edges.

    ``own_code`` is the item's own catalogue code.  A source repeating it is not
    contributing a cross — it is telling us our own number back — so it is
    discarded as a self reference and reported as such.

    ``shared_article_numbers`` are normalized numbers known to belong to more
    than one internal code.  Edges touching them are flagged rather than
    dropped: the number is real, it just cannot be trusted to identify a single
    part on its own.

    ``source_semantic_conflict`` means that two source revisions joined through
    the same private key explicitly disagree on a physical identity dimension.
    Every edge is then retained for audit but downgraded to ``REVIEW``: choosing
    which revision is right is a domain decision, not a recency tie-break.

    ``public_number_semantic_fanout`` contains exact public numbers assigned to
    structurally incompatible catalog rows. It also quarantines a graph that
    contains only that canonical number: no edge exists, but querying the
    canonical would still mix the incompatible products.
    """

    own_norm = normalize_cross_oem(own_code)
    candidates, discarded = _candidates(sources, config)

    if own_norm in candidates:
        discarded[candidates[own_norm]["raw"]] = DISCARD_SELF_REFERENCE
        del candidates[own_norm]

    canonical, canonical_source = choose_canonical(candidates, config)
    if not canonical:
        return IdentityGraph(
            canonical="",
            canonical_source=None,
            discarded=MappingProxyType(dict(discarded)),
        )

    superseded = _superseded_sources(candidates, config)
    has_conflict = _sources_disagree(candidates, config, superseded=superseded)

    graph_anomalies: set[str] = set()
    if source_semantic_conflict:
        graph_anomalies.add(Anomaly.SOURCE_SEMANTIC_CONFLICT.value)
    if set(candidates).intersection(public_number_semantic_fanout):
        graph_anomalies.add(Anomaly.PUBLIC_NUMBER_SEMANTIC_FANOUT.value)
    # Причина у якоря одна и выбирается тем же порядком старшинства, что и у
    # ребра ниже: читателю нужна главная причина, а не их перечень.
    canonical_sources = tuple(
        sorted(candidates[canonical]["sources"], key=config.trust_index)
    )
    canonical_anomaly: str | None = None
    if source_semantic_conflict:
        canonical_anomaly = Anomaly.SOURCE_SEMANTIC_CONFLICT.value
    elif canonical in public_number_semantic_fanout:
        canonical_anomaly = Anomaly.PUBLIC_NUMBER_SEMANTIC_FANOUT.value
    elif canonical in shared_article_numbers:
        canonical_anomaly = Anomaly.SHARED_ARTICLE_FANOUT.value
    elif has_conflict and config.sources[canonical_source].asserts_oe:
        canonical_anomaly = Anomaly.OE_SOURCE_CONFLICT.value
    elif all(source in superseded for source in canonical_sources):
        canonical_anomaly = Anomaly.OE_SUPERSEDED_BY_NEWER_REFERENCE.value

    links: list[IdentityLink] = []
    for number in sorted(candidates):
        if number == canonical:
            continue
        entry = candidates[number]
        # Trust order, not alphabetical: the first element is then the source
        # that decided the status, which is what a reader wants to see first.
        sources_for_number = sorted(entry["sources"], key=config.trust_index)
        best = sources_for_number[0]
        status = config.sources[best].status
        # Two independent sources naming the same pair is corroboration, and it
        # is the only automatic route out of REVIEW: one unverified source
        # agreeing with a verified one is evidence, one source alone is not.
        if status is LinkStatus.REVIEW and len(sources_for_number) > 1:
            status = LinkStatus.CONFIRMED

        anomaly: str | None = None
        if source_semantic_conflict:
            anomaly = Anomaly.SOURCE_SEMANTIC_CONFLICT.value
        elif (
            canonical in public_number_semantic_fanout
            or number in public_number_semantic_fanout
        ):
            anomaly = Anomaly.PUBLIC_NUMBER_SEMANTIC_FANOUT.value
        elif number in shared_article_numbers or canonical in shared_article_numbers:
            anomaly = Anomaly.SHARED_ARTICLE_FANOUT.value
        elif has_conflict and config.sources[best].asserts_oe:
            anomaly = Anomaly.OE_SOURCE_CONFLICT.value
        elif all(source in superseded for source in sources_for_number):
            # Only when *every* source behind this pair is an old edition.  A
            # number the current book also names is not superseded by anything,
            # even if an older edition happens to mention it too.
            anomaly = Anomaly.OE_SUPERSEDED_BY_NEWER_REFERENCE.value
        if anomaly:
            graph_anomalies.add(anomaly)
            # An edge under review is not a rejected edge: the pair may well be
            # right, and a human decides.  What it must not do is move a price.
            status = LinkStatus.REVIEW

        links.append(
            IdentityLink(
                our_oem_norm=canonical,
                extracted_oem_norm=number,
                extraction_method=best,
                validation_status=status,
                raw_context=entry["contexts"].get(best, ""),
                extracted_raw=entry["raw"],
                anomaly=anomaly,
                corroborating_sources=tuple(sources_for_number),
            )
        )

    return IdentityGraph(
        canonical=canonical,
        canonical_source=canonical_source,
        canonical_sources=canonical_sources,
        links=tuple(links),
        anomalies=tuple(sorted(graph_anomalies)),
        # Пересечение, а не просто причина якоря. Это поле сужает ворота и не
        # должно их нигде ужесточать: причина, о которой сам граф молчит, не
        # может закрыть позицию, которая сегодня открыта.
        #
        # Такие причины существуют. Граф без рёбер, у которого якорь и есть
        # общий артикул, аномалию не показывает вовсе: она добавляется только
        # в цикле по рёбрам, а цикл пуст. Это отдельная дыра
        # (``PUBLIC_NUMBER_SEMANTIC_FANOUT`` свою проверку для такого случая
        # имеет, ``SHARED_ARTICLE_FANOUT`` — нет), и закрывать её надо
        # отдельной правкой с отдельным замером: на живом каталоге она снимает
        # OE со 163 позиций.
        canonical_anomalies=tuple(
            sorted({canonical_anomaly} & graph_anomalies)
            if canonical_anomaly is not None
            else ()
        ),
        discarded=MappingProxyType(dict(discarded)),
    )


def shared_article_numbers(
    articles_by_code: Mapping[str, Iterable[str]], *, minimum_codes: int = 2
) -> frozenset[str]:
    """Normalized numbers claimed by ``minimum_codes`` or more internal codes.

    151 articles of the 2026-07-28 reference map are shared this way.  Merging
    them automatically is the straight road to comparing our price against a
    different part (M9), so they are surfaced instead.
    """

    owners: dict[str, set[str]] = {}
    for code, articles in articles_by_code.items():
        for article in articles:
            normalized = normalize_cross_oem(article)
            if is_safe_public_number_shape(normalized):
                owners.setdefault(normalized, set()).add(code)
    return frozenset(
        number for number, codes in owners.items() if len(codes) >= minimum_codes
    )
