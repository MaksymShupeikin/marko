"""Deterministic early-exit gates for Prom discovery candidates.

The chain answers two independent questions and keeps them apart.

*Is this the same part?*  Identity gates run first and end in ``REJECTED``.
A rejected candidate is wrong, not merely unusable, so it is never shown.

*Is this the same level of quality?*  Comparability gates run second and end in
``REFERENCE_ONLY``.  Such a candidate is the same part at an unknown or
unconvertible level: its price cannot enter the calculation, but the customer
still sees it and can check it by eye.  Only a candidate that clears both
phases becomes ``PRICING_EVIDENCE``.

Merging the two questions is what produced runs with nothing to show: an
unapproved brand dictionary made every tier ``UNKNOWN``, and a fail-closed
policy then suppressed the entire result set.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any
import unicodedata

import yaml

from metis.identifiers import normalize_oem_identifier

from .tiering import classify_tier
from .types import ProductTier


CANDIDATE_SELECTION_SCHEMA_VERSION = "metis-deterministic-candidate-selection-v1"

#: Identity gates.  Ordered cheapest-first; every one of them can only end in
#: ``REJECTED``, because each proves the candidate is a different product.
CANDIDATE_IDENTITY_GATES = (
    "own_seller",
    "dismantler_seller",
    # Cheap integer comparison with high selectivity against text collisions,
    # so it runs before any regex or OEM work.
    "category_domain",
    "condition",
    "remanufactured",
    "oem_identity",
    "oem_stuffing",
    "variant",
    "package",
    "applicability",
)

#: Comparability gates.  They decide how a candidate is *used*, never whether
#: it is shown, so their terminal outcome is ``REFERENCE_ONLY``.  The single
#: exception is ``tier_classification``, which rejects a listing the tier model
#: proves to be second-hand — that is an identity fact reached late because it
#: needs the classifier.
CANDIDATE_COMPARABILITY_GATES = (
    "tier_classification",
    "own_brand",
    "tier_known",
    "premium_calibration",
    "price_anomaly",
)

CANDIDATE_GATE_ORDER = CANDIDATE_IDENTITY_GATES + CANDIDATE_COMPARABILITY_GATES


class CandidateSelectionConfigError(ValueError):
    """Raised when candidate-selection rules are incomplete or unsafe."""


class CandidateStatus(StrEnum):
    """What a candidate may be used for, not how confident the chain feels."""

    #: Same part, level known, level convertible: enters the fair-price basis.
    PRICING_EVIDENCE = "PRICING_EVIDENCE"
    #: Same part, level unknown or unconvertible: shown to the customer with a
    #: link, deliberately excluded from the calculation.
    REFERENCE_ONLY = "REFERENCE_ONLY"
    #: Proven to be a different product, second-hand, or our own listing.
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class TextMarkers:
    words: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    substrings: tuple[str, ...] = ()
    regex: tuple[str, ...] = ()


# These defaults are intentionally conservative.  They are not a product
# taxonomy and must not be used as positive identity proof.  Their only job is
# to keep an unrecognised Prom category from entering the price cohort when the
# title is an unmistakably unrelated marketplace item.  The shipped YAML
# repeats the lists so the active policy is auditable and hash-pinned; the
# Python defaults preserve backwards compatibility for older/private policy
# files that predate the semantic domain section.
_DEFAULT_CATEGORY_DOMAIN_AUTOMOTIVE_MARKERS: Mapping[str, list[str]] = {
    "words": [
        "vw",
        "bmw",
        "audi",
        "ford",
        "kia",
        "opel",
        "seat",
        "fiat",
        "honda",
        "mazda",
        "volvo",
        "iveco",
        "isuzu",
        "toyota",
        "nissan",
        "renault",
        "peugeot",
        "citroen",
        "subaru",
        "suzuki",
        "hyundai",
        "mitsubishi",
        "volkswagen",
        "мерседес",
        "фольксваген",
        "тойота",
        "авто",
    ],
    "prefixes": [
        "автозапчаст",
        "запчаст",
        "автомоб",
        "радиатор",
        "амортиз",
        "термостат",
        "стартер",
        "генератор",
        "насос",
        "ступиц",
        "подшип",
        "колод",
        "датчик",
        "фильтр",
        "ремн",
        "ролик",
        "ремкомплект",
        "замок",
        "зажиган",
        "подвес",
        "рычаг",
        "тяга",
        "сайлент",
        "втул",
        "проклад",
        "клапан",
        "катуш",
        "форсун",
        "дроссел",
        "турбин",
        "картер",
        "масл",
        "сцеплен",
        "короб",
        "тормоз",
        "кузов",
        "капот",
        "багажник",
        "бампер",
        "фара",
        "крыл",
        "двер",
        "зеркал",
        "стеклооч",
        "шкив",
        "маховик",
        "шрус",
        "глуш",
        "выхлоп",
        "рул",
        "гидроусил",
        "бачок",
        "сальник",
        "привод",
        "полуос",
        "свеч",
        "провод",
        "аккум",
        "кардан",
        "патруб",
        "шланг",
        "опор",
    ],
    "phrases": [
        "для автомобиля",
        "для авто",
        "для двигателя",
        "для акпп",
        "для кпп",
        "для volkswagen",
        "для toyota",
    ],
}

_DEFAULT_CATEGORY_DOMAIN_NON_AUTOMOTIVE_MARKERS: Mapping[str, list[str]] = {
    "words": [
        "vitamin",
        "supplement",
        "lenovo",
        "gap",
    ],
    "regex": [
        # Ukrainian "ніж" normalizes to "ниж" (``norm_text`` folds і into и),
        # and after that the knife is indistinguishable from the conjunction
        # "ніж" ("than").  As a prefix the marker swallowed "нижнього важеля"
        # and every other lower control arm; as a whole word it still killed an
        # Audi 100 tie rod end carrying the exact OE 4A0419812A, because the
        # reseller boilerplate says "Перш ніж купити, варто порівняти номер".
        # One deny marker rejects the listing outright, so both forms were
        # broad words -- exactly what this set is documented not to hold.
        # The discriminator is position: a knife being sold is the first word
        # of the title, and the conjunction never is.  ``semantic_text`` is
        # built title-first and ``norm_text`` pads with a leading space.
        r"^ ниж\b",
    ],
    "prefixes": [
        "витамин",
        "добавк",
        "коллаген",
        "нож",
        "лезви",
        "фотофон",
        "фотозон",
        "винилов",
        "ноутбук",
        "компьютер",
        "смартфон",
        # No bare "телефон" here, deliberately -- see comparability.yaml.  The
        # markers match on substring, and on Prom the word is the seller's
        # contact line ("телефон для замовлення"), not the product.  It rejected
        # a VW Crafter viscous-coupling bearing carrying an exact OE match while
        # "vw" was firing as an automotive marker in the same listing.  A real
        # phone or phone accessory is still caught by "смартфон" and by
        # "для телефона" below, and by the category blocklist.
        "планшет",
        "клавиатур",
        "монитор",
        "наушник",
        "мебел",
        "стол",
        "стул",
        "шкаф",
        "диван",
        "кресл",
        "одеж",
        "куртк",
        "жилет",
        "футболк",
        "брюк",
        "плать",
        "юбк",
        "кепк",
        "балетк",
        "обув",
        "шапк",
        "сумк",
        "аквариум",
        "самокат",
        "велосипед",
        "беговел",
        "игруш",
        "тетрад",
        "зошит",
        "пенал",
        "обои",
        "маникюр",
        "медицин",
        "посуд",
        "бутыл",
        "полотен",
        "краск",
        "эмал",
        "мультимед",
        "адаптер",
        "переходник",
        "погруж",
        "глубин",
        "глибин",
        "скважин",
        "свердлов",
        "колод",
    ],
    "phrases": [
        "для ноутбука",
        "для телефона",
        "для компьютера",
        "для скважины",
        "для колодца",
        "для воды",
        "насос для воды",
        "насос для скважины",
        "насос для колодца",
        "квадратный виниловый фотофон",
    ],
}


@dataclass(frozen=True, slots=True)
class ApplicabilityDictionary:
    year_regex: str
    brands: Mapping[str, tuple[str, ...]]
    models: Mapping[str, tuple[str, ...]]
    generations: Mapping[str, tuple[str, ...]]
    platform_families: Mapping[str, frozenset[str]]


@dataclass(frozen=True, slots=True)
class CategoryDomainConfig:
    """Policy for rejecting candidates that sit in an unrelated product domain.

    Prom search matches plain text, so a generic numeric article such as
    ``2141006`` also returns pool ladders and school notebooks. Category
    ancestry separates those from real parts without any text heuristics.

    Two independent mechanisms are supported:

    ``blocked_ancestors``
        Deny semantics and the default. Only domains proven to be
        non-automotive are rejected, so a category never observed before
        still passes. Fail-open: unknown data cannot cause a false SKIP.

    ``allowed_ancestors`` with ``allowlist_enforced``
        Allow semantics. Everything outside the list is rejected. This is
        only safe once the list provably covers the whole automotive
        taxonomy, so it stays disabled until an owner approves it.
    """

    enabled: bool
    blocked_ancestors: tuple[tuple[int, ...], ...]
    allowed_ancestors: tuple[tuple[int, ...], ...]
    allowlist_enforced: bool
    majority_vote_enabled: bool
    majority_prefix_depth: int
    majority_min_candidates: int
    majority_min_share: Decimal
    # Semantic markers are a precision guard for category paths that are not
    # known to be automotive.  They never prove identity; they only reject
    # explicit non-automotive wording or hold an unconfirmed domain out of the
    # price cohort.
    trusted_automotive_ancestors: tuple[tuple[int, ...], ...]
    automotive_markers: TextMarkers
    non_automotive_markers: TextMarkers
    require_semantic_for_unknown: bool


@dataclass(frozen=True, slots=True)
class CategoryDomainContext:
    """Cross-candidate category statistics for exactly one discovery run.

    ``check_candidate`` stays a pure per-candidate function, so the majority
    vote is computed once upstream and passed in, mirroring how owned seller
    ids and confirmed cross OEMs are already supplied.
    """

    candidate_count: int
    mode_prefix: tuple[int, ...] | None
    majority_share: Decimal

    @property
    def is_conclusive(self) -> bool:
        return self.mode_prefix is not None


@dataclass(frozen=True, slots=True)
class PriceAnomalyConfig:
    minimum_ratio: Decimal
    maximum_ratio: Decimal
    default_tier_premiums: Mapping[ProductTier, Decimal]
    category_tier_premiums: Mapping[str, Mapping[ProductTier, Decimal]]


@dataclass(frozen=True, slots=True)
class CandidateSelectionConfig:
    method_version: str
    source_path: str
    source_sha256: str
    own_seller_ids: frozenset[str]
    kemp_network_seller_ids: frozenset[str]
    dismantler_markers: TextMarkers
    used_markers: TextMarkers
    new_markers: TextMarkers
    remanufactured_markers: TextMarkers
    pack_markers: TextMarkers
    max_oem_in_title: int
    oem_like_token_regex: str
    variant_axes: Mapping[str, Mapping[str, TextMarkers]]
    applicability: ApplicabilityDictionary
    category_domain: CategoryDomainConfig
    price_anomaly: PriceAnomalyConfig


@dataclass(frozen=True, slots=True)
class ReferenceItem:
    oem: str
    title: str
    price: Decimal | None
    brand: str | None = None
    category: str | None = None
    tier: ProductTier | None = None


@dataclass(frozen=True, slots=True)
class CandidateItem:
    seller_id: str
    seller_name: str
    title: str
    description: str | None
    article_field: str | None
    brand: str | None
    price: Decimal
    condition: str | None = None
    category_id: int | None = None
    # Root-to-leaf Prom category ancestry. Compared element-wise as integers;
    # never as text, because ancestor 20 must not match category 208.
    category_path: tuple[int, ...] = ()
    # Additional candidate-native identifiers, kept separate from the single
    # legacy ``article_field`` slot.  Prom commonly exposes both a seller SKU
    # and a manufacturer part number; choosing one with ``sku or mpn`` loses a
    # valid exact MPN whenever the seller SKU is present but different.
    # Values are labelled so the verdict explains which namespace matched.
    article_fields: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateVerdict:
    status: CandidateStatus
    reason: str
    passed_gates: tuple[str, ...]
    flags: tuple[str, ...]
    details: Mapping[str, Any]
    predicted_tier: ProductTier
    tier_confidence: Decimal

    @property
    def histogram_key(self) -> str:
        """Group verdicts by outcome and cause in one human-readable key.

        The status is always part of the key, including for
        ``PRICING_EVIDENCE``: a histogram that hides the successful bucket
        behind a bare reason code is unreadable next to the other two.
        """

        return f"{self.status.value}:{self.reason}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "passed_gates": list(self.passed_gates),
            "flags": list(self.flags),
            "details": dict(self.details),
            "predicted_tier": self.predicted_tier.value,
            "tier_confidence": str(self.tier_confidence),
        }


@dataclass(frozen=True, slots=True)
class _GateResult:
    action: CandidateStatus | None = None
    reason: str | None = None
    flag: str | None = None
    flags: tuple[str, ...] = ()
    details: Mapping[str, Any] | None = None
    predicted_tier: ProductTier | None = None
    tier_confidence: Decimal | None = None


@dataclass(frozen=True, slots=True)
class _Applicability:
    brands: frozenset[str]
    models: frozenset[str]
    generations: frozenset[str]
    years: tuple[int, int] | None


def norm_text(value: str | None) -> str:
    """Normalize multilingual listing text and preserve word boundaries."""

    normalized = unicodedata.normalize("NFKC", value or "").lower()
    normalized = (
        normalized.replace("ё", "е")
        .replace("і", "и")
        .replace("ї", "и")
        .replace("є", "е")
    )
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return f" {normalized} " if normalized else " "


def norm_oem(value: str | None) -> str:
    """Normalize OE/article identifiers through the shared OEM contract."""

    return normalize_oem_identifier(value)


def load_candidate_selection_config(
    path: str | Path,
) -> CandidateSelectionConfig:
    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise CandidateSelectionConfigError(
            f"Candidate selection config does not exist: {source_path}"
        )
    raw = source_path.read_bytes()
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise CandidateSelectionConfigError(
            "Candidate selection config is not valid YAML"
        ) from exc
    root = _mapping(payload, "root")
    if root.get("schema_version") != CANDIDATE_SELECTION_SCHEMA_VERSION:
        raise CandidateSelectionConfigError(
            "Unsupported candidate selection schema_version"
        )
    method_version = _text(root.get("method_version"), "method_version")
    text_markers = _mapping(root.get("text_markers"), "text_markers")
    variant_payload = _mapping(root.get("variant_axes"), "variant_axes")
    variant_axes: dict[str, Mapping[str, TextMarkers]] = {}
    for axis, raw_values in variant_payload.items():
        values = _mapping(raw_values, f"variant_axes.{axis}")
        if len(values) < 2:
            raise CandidateSelectionConfigError(
                f"variant_axes.{axis} must define at least two values"
            )
        variant_axes[str(axis)] = MappingProxyType(
            {
                str(value): _markers(
                    marker_payload,
                    f"variant_axes.{axis}.{value}",
                )
                for value, marker_payload in values.items()
            }
        )

    applicability_payload = _mapping(root.get("applicability"), "applicability")
    applicability = ApplicabilityDictionary(
        year_regex=_valid_regex(
            applicability_payload.get("year_regex"),
            "applicability.year_regex",
        ),
        brands=_alias_dictionary(
            applicability_payload.get("brands"), "applicability.brands"
        ),
        models=_alias_dictionary(
            applicability_payload.get("models"), "applicability.models"
        ),
        generations=_alias_dictionary(
            applicability_payload.get("generations"),
            "applicability.generations",
        ),
        platform_families=_platform_families(
            applicability_payload.get("platform_families")
        ),
    )
    price_payload = _mapping(root.get("price_anomaly"), "price_anomaly")
    minimum_ratio = _positive_decimal(
        price_payload.get("minimum_ratio"), "price_anomaly.minimum_ratio"
    )
    maximum_ratio = _positive_decimal(
        price_payload.get("maximum_ratio"), "price_anomaly.maximum_ratio"
    )
    if minimum_ratio >= maximum_ratio:
        raise CandidateSelectionConfigError(
            "price_anomaly.minimum_ratio must be below maximum_ratio"
        )
    default_premiums = _tier_premiums(
        price_payload.get("default_tier_premiums"),
        "price_anomaly.default_tier_premiums",
    )
    category_payload = _mapping(
        price_payload.get("category_tier_premiums", {}),
        "price_anomaly.category_tier_premiums",
    )
    category_premiums = MappingProxyType(
        {
            str(category).strip().casefold(): _tier_premiums(
                premiums,
                f"price_anomaly.category_tier_premiums.{category}",
            )
            for category, premiums in category_payload.items()
        }
    )
    max_oem = root.get("max_oem_in_title")
    if isinstance(max_oem, bool) or not isinstance(max_oem, int) or max_oem < 1:
        raise CandidateSelectionConfigError(
            "max_oem_in_title must be a positive integer"
        )

    return CandidateSelectionConfig(
        method_version=method_version,
        source_path=str(source_path.resolve()),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        own_seller_ids=_text_set(root.get("own_seller_ids"), "own_seller_ids"),
        kemp_network_seller_ids=_text_set(
            root.get("kemp_network_seller_ids"),
            "kemp_network_seller_ids",
        ),
        dismantler_markers=_markers(
            text_markers.get("dismantler_seller"),
            "text_markers.dismantler_seller",
        ),
        used_markers=_markers(text_markers.get("used"), "text_markers.used"),
        new_markers=_markers(text_markers.get("new"), "text_markers.new"),
        remanufactured_markers=_markers(
            text_markers.get("remanufactured"),
            "text_markers.remanufactured",
        ),
        pack_markers=_markers(text_markers.get("pack"), "text_markers.pack"),
        max_oem_in_title=max_oem,
        oem_like_token_regex=_valid_regex(
            root.get("oem_like_token_regex"), "oem_like_token_regex"
        ),
        variant_axes=MappingProxyType(variant_axes),
        applicability=applicability,
        category_domain=_category_domain(root.get("category_domain")),
        price_anomaly=PriceAnomalyConfig(
            minimum_ratio=minimum_ratio,
            maximum_ratio=maximum_ratio,
            default_tier_premiums=default_premiums,
            category_tier_premiums=category_premiums,
        ),
    )


def check_candidate(
    our_item: ReferenceItem,
    candidate: CandidateItem,
    config: CandidateSelectionConfig,
    *,
    owned_seller_ids: frozenset[str] | set[str] = frozenset(),
    confirmed_cross_oems: frozenset[str] | set[str] = frozenset(),
    brand_tiers: Mapping[str, ProductTier] | None = None,
    category_context: CategoryDomainContext | None = None,
    calibrated_premiums: Mapping[tuple[str, ProductTier], Decimal] | None = None,
    tier_agnostic: bool = False,
    identity_source: str | None = None,
) -> CandidateVerdict:
    """Run cheap-to-expensive gates and stop at the first terminal result.

    ``calibrated_premiums`` carries the validated ``(category, tier)``
    coefficients produced by calibration.  It defaults to empty, which is the
    honest state of a workspace that has not calibrated yet: every candidate at
    a level other than ours becomes ``REFERENCE_ONLY`` instead of silently
    entering the price basis at an unconverted price.

    ``tier_agnostic`` reflects a workspace whose owner prices against the
    cheapest comparable offer regardless of level, and it relaxes exactly two
    gates: ``tier_known`` and ``premium_calibration``.  It is deliberately not a
    property of the shared comparability config — the decision belongs to the
    pricing strategy (``raise_policy.yaml``), and duplicating it here would let
    the two disagree.  Nothing that establishes whether this is the same part is
    affected; under a minimum-based target those gates matter more, not less,
    because a wrong match is no longer diluted by a median but becomes the
    recommendation outright.
    """

    effective_owned = frozenset(owned_seller_ids) | config.own_seller_ids
    cross_oems = frozenset(norm_oem(value) for value in confirmed_cross_oems)
    search_field = norm_text(
        f"{candidate.title} {candidate.description or ''} {candidate.seller_name}"
    )
    predicted_tier = ProductTier.UNKNOWN
    tier_confidence = Decimal("0")
    passed: list[str] = []
    flags: list[str] = []
    gate_details: dict[str, Any] = {}

    gates = (
        (
            "own_seller",
            lambda: _gate_own_seller(candidate, effective_owned),
        ),
        (
            "dismantler_seller",
            lambda: _gate_dismantler(candidate, config),
        ),
        (
            "category_domain",
            lambda: _gate_category_domain(candidate, config, category_context),
        ),
        (
            "condition",
            lambda: _gate_condition(search_field, config),
        ),
        (
            "remanufactured",
            lambda: _gate_remanufactured(search_field, config),
        ),
        (
            "oem_identity",
            lambda: _gate_oem_identity(
                our_item, candidate, cross_oems, identity_source
            ),
        ),
        (
            "oem_stuffing",
            lambda: _gate_oem_stuffing(
                candidate,
                config,
                gate_details.get("oem_identity", {}),
            ),
        ),
        (
            "variant",
            lambda: _gate_variant(our_item, candidate, config),
        ),
        (
            "package",
            lambda: _gate_package(our_item, candidate, config),
        ),
        (
            "applicability",
            lambda: _gate_applicability(our_item, candidate, config),
        ),
        (
            "tier_classification",
            lambda: _gate_tier_classification(
                our_item,
                candidate,
                brand_tiers=brand_tiers,
            ),
        ),
        (
            "own_brand",
            lambda: _gate_own_brand(candidate, config, tier=predicted_tier),
        ),
        (
            "tier_known",
            lambda: _gate_tier_known(predicted_tier, tier_agnostic=tier_agnostic),
        ),
        (
            "premium_calibration",
            lambda: _gate_premium_calibration(
                our_item,
                tier=predicted_tier,
                calibrated_premiums=calibrated_premiums,
                tier_agnostic=tier_agnostic,
            ),
        ),
        (
            "price_anomaly",
            lambda: _gate_price_anomaly(
                our_item,
                candidate,
                config,
                tier=predicted_tier,
                tier_agnostic=tier_agnostic,
            ),
        ),
    )

    for gate_name, gate in gates:
        result = gate()
        details = dict(result.details or {})
        gate_details[gate_name] = details
        if result.predicted_tier is not None:
            predicted_tier = result.predicted_tier
        if result.tier_confidence is not None:
            tier_confidence = result.tier_confidence
        if result.flag and result.flag not in flags:
            flags.append(result.flag)
        for flag in result.flags:
            if flag not in flags:
                flags.append(flag)
        if result.action is not None:
            reason = result.reason or "UNSPECIFIED"
            return CandidateVerdict(
                status=result.action,
                reason=reason,
                passed_gates=tuple(passed),
                flags=tuple(flags),
                details=MappingProxyType(
                    {
                        "method_version": config.method_version,
                        "config_sha256": config.source_sha256,
                        "stopped_gate": gate_name,
                        "gates": gate_details,
                    }
                ),
                predicted_tier=predicted_tier,
                tier_confidence=tier_confidence,
            )
        passed.append(gate_name)

    return CandidateVerdict(
        status=CandidateStatus.PRICING_EVIDENCE,
        reason="OK",
        passed_gates=tuple(passed),
        flags=tuple(flags),
        details=MappingProxyType(
            {
                "method_version": config.method_version,
                "config_sha256": config.source_sha256,
                "stopped_gate": None,
                "gates": gate_details,
            }
        ),
        predicted_tier=predicted_tier,
        tier_confidence=tier_confidence,
    )


def verdict_histogram(
    verdicts: list[CandidateVerdict] | tuple[CandidateVerdict, ...],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for verdict in verdicts:
        counts[verdict.histogram_key] = counts.get(verdict.histogram_key, 0) + 1
    return dict(sorted(counts.items()))


def _gate_own_seller(
    candidate: CandidateItem,
    owned_seller_ids: frozenset[str],
) -> _GateResult:
    owned = candidate.seller_id.strip() in owned_seller_ids
    return _GateResult(
        action=CandidateStatus.REJECTED if owned else None,
        reason="OWN_SELLER" if owned else None,
        details={"seller_id": candidate.seller_id, "owned": owned},
    )


def _gate_dismantler(
    candidate: CandidateItem,
    config: CandidateSelectionConfig,
) -> _GateResult:
    seller = norm_text(candidate.seller_name)
    matched = _matched_markers(seller, config.dismantler_markers)
    return _GateResult(
        action=CandidateStatus.REJECTED if matched else None,
        reason="DISMANTLER_SELLER" if matched else None,
        details={"matched_markers": matched},
    )


def _is_descendant(path: tuple[int, ...], ancestor: tuple[int, ...]) -> bool:
    """Return whether ``ancestor`` is an element-wise prefix of ``path``.

    Integer comparison is mandatory: textual prefixes would make ancestor
    ``20`` swallow the unrelated category ``208``.
    """

    return len(ancestor) <= len(path) and path[: len(ancestor)] == ancestor


def _first_matching_ancestor(
    path: tuple[int, ...],
    ancestors: tuple[tuple[int, ...], ...],
) -> tuple[int, ...] | None:
    for ancestor in ancestors:
        if _is_descendant(path, ancestor):
            return ancestor
    return None


def build_category_domain_context(
    category_paths: list[tuple[int, ...]] | tuple[tuple[int, ...], ...],
    config: CategoryDomainConfig,
) -> CategoryDomainContext:
    """Summarise one result set for the majority-vote mode.

    ``mode_prefix`` stays ``None`` whenever the sample is too small or too
    scattered to be conclusive, which makes the gate a no-op instead of
    guessing a domain from a handful of unrelated rows.
    """

    known = [path for path in category_paths if path]
    total = len(known)
    if total < config.majority_min_candidates:
        return CategoryDomainContext(total, None, Decimal("0"))
    prefixes = [path[: config.majority_prefix_depth] for path in known]
    counts: dict[tuple[int, ...], int] = {}
    for prefix in prefixes:
        counts[prefix] = counts.get(prefix, 0) + 1
    # Ties resolve deterministically: highest count, then lowest prefix.
    mode_prefix, mode_count = sorted(
        counts.items(), key=lambda item: (-item[1], item[0])
    )[0]
    share = (Decimal(mode_count) / Decimal(total)).quantize(Decimal("0.000001"))
    if share < config.majority_min_share:
        return CategoryDomainContext(total, None, share)
    return CategoryDomainContext(total, mode_prefix, share)


def _gate_category_domain(
    candidate: CandidateItem,
    config: CandidateSelectionConfig,
    context: CategoryDomainContext | None,
) -> _GateResult:
    policy = config.category_domain
    path = tuple(candidate.category_path)
    semantic_text = " ".join(
        value.strip()
        for value in (
            candidate.title,
            candidate.description or "",
            candidate.brand or "",
        )
        if value and value.strip()
    )
    automotive_markers = _matched_markers(
        semantic_text,
        policy.automotive_markers,
    )
    non_automotive_markers = _matched_markers(
        semantic_text,
        policy.non_automotive_markers,
    )
    details: dict[str, Any] = {
        "category_id": candidate.category_id,
        "category_path": list(path),
        "semantic_text_markers": {
            "automotive": automotive_markers,
            "non_automotive": non_automotive_markers,
        },
    }
    if not policy.enabled:
        details["mode"] = "DISABLED"
        return _GateResult(details=details)

    blocked = _first_matching_ancestor(path, policy.blocked_ancestors)
    if blocked is not None:
        details["mode"] = "BLOCKLIST"
        details["matched_ancestor"] = list(blocked)
        return _GateResult(
            action=CandidateStatus.REJECTED,
            reason="CATEGORY_NOT_AUTOPARTS",
            details=details,
        )

    # A strong lexical contradiction wins even when Prom misclassified the
    # category under the automotive root.  This is intentionally a closed,
    # auditable deny set; broad words such as ``насос`` or ``лампа`` are not in
    # it because they occur in real vehicle parts as well.
    if non_automotive_markers:
        details["mode"] = "SEMANTIC_NON_AUTOMOTIVE"
        return _GateResult(
            action=CandidateStatus.REJECTED,
            reason="CATEGORY_NOT_AUTOPARTS",
            details=details,
        )

    if not path:
        details["mode"] = "CATEGORY_UNKNOWN"
        # Keep the gate non-terminal when Prom supplied no category.  This
        # preserves the later OEM gate's diagnostic/identity precedence.  The
        # acquisition adapters call the semantic pricing gate after the full
        # chain and turn an unconfirmed domain into REFERENCE_ONLY there.
        return _GateResult(flag="CATEGORY_UNKNOWN", details=details)

    if policy.allowlist_enforced and policy.allowed_ancestors:
        allowed = _first_matching_ancestor(path, policy.allowed_ancestors)
        details["mode"] = "ALLOWLIST"
        if allowed is None:
            return _GateResult(
                action=CandidateStatus.REJECTED,
                reason="CATEGORY_NOT_AUTOPARTS",
                details=details,
            )
        details["matched_ancestor"] = list(allowed)
        return _GateResult(details=details)

    trusted = _first_matching_ancestor(
        path,
        policy.trusted_automotive_ancestors,
    )
    if trusted is not None:
        details["mode"] = "TRUSTED_AUTOMOTIVE_BRANCH"
        details["matched_ancestor"] = list(trusted)
        return _GateResult(details=details)

    if policy.majority_vote_enabled and context is not None and context.is_conclusive:
        prefix = path[: policy.majority_prefix_depth]
        details["mode"] = "MAJORITY_VOTE"
        details["mode_prefix"] = list(context.mode_prefix or ())
        details["majority_share"] = str(context.majority_share)
        details["candidate_prefix"] = list(prefix)
        if prefix != context.mode_prefix:
            return _GateResult(
                action=CandidateStatus.REJECTED,
                reason="CATEGORY_OUTLIER_MAJORITY_VOTE",
                details=details,
            )
        return _GateResult(details=details)

    if automotive_markers:
        details["mode"] = "SEMANTIC_AUTOMOTIVE_TEXT"
        return _GateResult(details=details)

    # The path is known but belongs to a branch for which we have no approved
    # automotive interpretation.  Keep the gate non-terminal so identity
    # failures still report OEM_NOT_FOUND; the acquisition adapters demote a
    # completed pricing verdict to REFERENCE_ONLY after all identity gates.
    if policy.require_semantic_for_unknown:
        details["mode"] = "CATEGORY_DOMAIN_UNCONFIRMED"
        return _GateResult(
            flag="CATEGORY_DOMAIN_UNCONFIRMED",
            details=details,
        )

    details["mode"] = "NO_ACTIVE_POLICY"
    return _GateResult(details=details)


def _gate_condition(
    search_field: str,
    config: CandidateSelectionConfig,
) -> _GateResult:
    used = _matched_markers(search_field, config.used_markers)
    new = _matched_markers(search_field, config.new_markers)
    if used and new:
        return _GateResult(
            action=CandidateStatus.REFERENCE_ONLY,
            reason="CONDITION_CONFLICT",
            details={"used_markers": used, "new_markers": new},
        )
    if used:
        return _GateResult(
            action=CandidateStatus.REJECTED,
            reason="USED",
            details={"used_markers": used, "new_markers": new},
        )
    return _GateResult(details={"used_markers": [], "new_markers": new})


def _gate_remanufactured(
    search_field: str,
    config: CandidateSelectionConfig,
) -> _GateResult:
    matched = _matched_markers(search_field, config.remanufactured_markers)
    return _GateResult(
        action=CandidateStatus.REJECTED if matched else None,
        reason="REMANUFACTURED" if matched else None,
        details={"matched_markers": matched},
    )


#: Number of digits below which an all-numeric OE stops identifying a part on a
#: free-text marketplace search.  Measured on the 2026-07-29 reference map: 938
#: of 7687 positions (12.2%) carry an all-numeric OE of six digits or fewer, and
#: 682 of those are exactly six.  Six digits is a space of one million, and part
#: numbering is reused across trades — KEMP 863130 (a cylinder-head gasket, Elring
#: 863.130) and Zelmer 86.3130 (a meat-grinder auger) normalize to the same
#: string, which is how 115 auger listings reached the observation set.
#:
#: Unlabelled hits are kept visible but reference-only.  Structured article
#: fields and explicitly labelled ``art./OE/код`` title evidence remain eligible
#: for the downstream gates.
WEAK_NUMERIC_IDENTITY_MAX_DIGITS = 6

#: Evidence kinds that are a substring hit in free text rather than an exact
#: match of a structured field.  A collision can only enter through these.
_SUBSTRING_IDENTITY_EVIDENCE = frozenset({"TITLE", "DESCRIPTION"})
_IDENTIFIER_LABEL_RE = re.compile(
    r"(?:\b(?:oe|oem|art|article|артикул|арт)\b|"
    r"\bpart\s+(?:no|number)\b|"
    r"\bкод\s+(?:запчасти|запчастини|виробника|производителя)\b|[#№])",
    re.IGNORECASE,
)


def _identifier_pattern(expected: str) -> re.Pattern[str] | None:
    if not expected:
        return None
    pieces = r"[\s./_-]*".join(re.escape(character) for character in expected)
    return re.compile(
        rf"(?<![A-Za-zА-Яа-яЇїІіЄєҐґ0-9]){pieces}"
        rf"(?![A-Za-zА-Яа-яЇїІіЄєҐґ0-9])",
        re.IGNORECASE,
    )


def _identifier_matches_as_token(
    text: str | None, expected: str
) -> tuple[re.Match[str], ...]:
    pattern = _identifier_pattern(expected)
    if pattern is None or not text:
        return ()
    return tuple(pattern.finditer(text))


def _numeric_title_identifier_is_labelled(title: str | None, expected: str) -> bool:
    """Return whether a short numeric title hit is explicitly labelled.

    ``norm_oem`` intentionally removes punctuation, so a plain substring
    search cannot distinguish ``940194`` from the same digits embedded in a
    random SKU. Keep the original title for this one safety decision and
    accept grouped forms such as ``940 194`` only when a nearby ``арт./OE/код``
    marker identifies the number as a part identifier.
    """

    if not title or not expected.isdigit():
        return False
    for match in _identifier_matches_as_token(title, expected):
        before = title[max(0, match.start() - 48) : match.start()]
        if _IDENTIFIER_LABEL_RE.search(before):
            return True
    return False


def _gate_oem_identity(
    our_item: ReferenceItem,
    candidate: CandidateItem,
    confirmed_cross_oems: frozenset[str],
    identity_source: str | None = None,
) -> _GateResult:
    """Establish that the candidate is the same part, or reject it.

    ``identity_source`` names a source that already grouped this offer with our
    part — prom.ua's own ``/auto/oen/`` listing for our normalized part code, for
    instance.  Then the number is not looked for again in the seller's wording.

    That is not a relaxation, it is a correction.  Measured on 2026-07-31: of
    2181 offers taken from the page prom.ua files under our own part code, 1887
    were rejected as ``OEM_NOT_FOUND`` because the sellers do not repeat the
    number in their titles.  Re-deriving an identity the source asserted throws
    away exactly the evidence the source was consulted for.
    """

    if identity_source:
        expected = norm_oem(our_item.oem)
        # A Prom part-code page is strong acquisition evidence, but it is not
        # permission to ignore an explicit native OE reported by the card
        # itself.  A different MPN is normal for an aftermarket offer; a
        # different native OE is a contradiction that must be held for review.
        source_native_oes = tuple(
            normalized
            for label, raw_value in candidate.article_fields
            if label.strip().upper() in {"OE", "OE_RAW"}
            and (normalized := norm_oem(raw_value))
        )
        conflicting_source_oes = tuple(
            value
            for value in source_native_oes
            if expected and value != expected and value not in confirmed_cross_oems
        )
        if conflicting_source_oes:
            return _GateResult(
                action=CandidateStatus.REFERENCE_ONLY,
                reason="SOURCE_ASSERTION_OE_CONFLICT",
                details={
                    "expected_oem": expected,
                    "candidate_native_oes": list(source_native_oes),
                    "conflicting_native_oes": list(conflicting_source_oes),
                    "evidence": "SOURCE_ASSERTED_CONFLICT",
                    "identity_asserted_by": identity_source,
                },
            )
        return _GateResult(
            details={
                "expected_oem": expected,
                "article_oem": norm_oem(candidate.article_field) or None,
                "evidence": "SOURCE_ASSERTED",
                "identity_asserted_by": identity_source,
            }
        )
    expected = norm_oem(our_item.oem)
    article = norm_oem(candidate.article_field)
    structured_articles: list[tuple[str, str]] = []
    if article:
        structured_articles.append(("ARTICLE_FIELD", article))
    for label, raw_value in candidate.article_fields:
        normalized_value = norm_oem(raw_value)
        if normalized_value:
            structured_articles.append((str(label).strip() or "STRUCTURED", normalized_value))
    title = candidate.title
    description = candidate.description
    evidence: str | None = None
    # Native manufacturer namespaces outrank a seller SKU/article field in
    # both directions.  A common false-positive shape is:
    #
    #   query/our code = 7E5827505A
    #   candidate SKU  = 7E5827505A
    #   candidate MPN  = 7E5827505B
    #
    # Treating the first equality as proof would price an unrelated listing
    # whose private SKU happens to copy our code.  Conversely, an exact native
    # MPN/OE is valid evidence even when the seller's private SKU is different.
    native_articles = tuple(
        (label, value)
        for label, value in structured_articles
        if label.strip().upper() in {"MPN", "OE", "OE_RAW"}
    )
    matching_native = next(
        ((label, value) for label, value in native_articles if value == expected),
        None,
    )
    matching_structured = matching_native
    if matching_native is None:
        conflicting_native = tuple(
            (label, value)
            for label, value in native_articles
            if value != expected and value not in confirmed_cross_oems
        )
        if conflicting_native:
            return _GateResult(
                action=CandidateStatus.REJECTED,
                reason="OEM_CONFLICT",
                details={
                    "expected_oem": expected,
                    "article_oem": article or None,
                    "structured_articles": [
                        {"namespace": label, "normalized": value}
                        for label, value in structured_articles
                    ],
                    "conflicting_native": [
                        {"namespace": label, "normalized": value}
                        for label, value in conflicting_native
                    ],
                    "evidence": None,
                },
            )
        matching_structured = next(
            (
                (label, value)
                for label, value in structured_articles
                if value == expected
            ),
            None,
        )
    if matching_structured is not None:
        evidence = matching_structured[0]
    else:
        # A marketplace title may list a family of numbers (for example both
        # sides of a supersession), while the candidate-native MPN/OE field
        # identifies the actual card as another part.  Structured manufacturer
        # namespaces outrank copied marketing text; only an explicitly
        # confirmed cross is allowed to override that conflict.
        if expected and _identifier_matches_as_token(title, expected):
            evidence = "TITLE"
        elif expected and _identifier_matches_as_token(description, expected):
            evidence = "DESCRIPTION"
        elif any(
            value in confirmed_cross_oems for _label, value in structured_articles
        ):
            evidence = "CROSS_TABLE"
    if evidence is None:
        return _GateResult(
            action=CandidateStatus.REJECTED,
            reason="OEM_NOT_FOUND",
            details={
                "expected_oem": expected,
                "article_oem": article or None,
                "structured_articles": [
                    {"namespace": label, "normalized": value}
                    for label, value in structured_articles
                ],
                "evidence": None,
            },
        )
    weak = (
        evidence in _SUBSTRING_IDENTITY_EVIDENCE
        and expected.isdigit()
        and len(expected) <= WEAK_NUMERIC_IDENTITY_MAX_DIGITS
    )
    labelled = weak and _numeric_title_identifier_is_labelled(
        f"{candidate.title}\n{candidate.description or ''}",
        expected,
    )
    weak = weak and not labelled
    if weak:
        return _GateResult(
            action=CandidateStatus.REFERENCE_ONLY,
            reason="WEAK_NUMERIC_IDENTITY",
            flag="WEAK_NUMERIC_IDENTITY",
            details={
                "expected_oem": expected,
                "article_oem": article or None,
                "structured_articles": [
                    {"namespace": label, "normalized": value}
                    for label, value in structured_articles
                ],
                "evidence": evidence,
                "weak_numeric_identity": True,
                "identifier_context": "UNLABELLED_TITLE_SUBSTRING",
            },
        )
    return _GateResult(
        details={
            "expected_oem": expected,
            "article_oem": article or None,
            "structured_articles": [
                {"namespace": label, "normalized": value}
                for label, value in structured_articles
            ],
            "evidence": evidence,
            "weak_numeric_identity": False,
            "identifier_context": "LABELLED_TITLE" if labelled else None,
        },
    )


def _gate_oem_stuffing(
    candidate: CandidateItem,
    config: CandidateSelectionConfig,
    identity_details: Mapping[str, Any],
) -> _GateResult:
    tokens = tuple(
        dict.fromkeys(re.findall(config.oem_like_token_regex, candidate.title.upper()))
    )
    stuffed = (
        identity_details.get("evidence") == "TITLE"
        and len(tokens) > config.max_oem_in_title
    )
    return _GateResult(
        flag="OEM_STUFFED" if stuffed else None,
        details={
            "oem_like_tokens": list(tokens),
            "token_count": len(tokens),
            "threshold": config.max_oem_in_title,
        },
    )


def _gate_variant(
    our_item: ReferenceItem,
    candidate: CandidateItem,
    config: CandidateSelectionConfig,
) -> _GateResult:
    details: dict[str, Any] = {}
    flags: list[str] = []
    for axis, values in config.variant_axes.items():
        our_values = _axis_values(our_item.title, values)
        candidate_values = _axis_values(candidate.title, values)
        details[axis] = {
            "reference": sorted(our_values),
            "candidate": sorted(candidate_values),
        }
        if len(our_values) == 1 and len(candidate_values) == 1:
            if our_values != candidate_values:
                return _GateResult(
                    action=CandidateStatus.REJECTED,
                    reason=f"VARIANT_MISMATCH:{axis}",
                    details=details,
                )
        elif len(our_values) > 1 or len(candidate_values) > 1:
            flags.append(f"VARIANT_AMBIGUOUS:{axis}")
    return _GateResult(
        flags=tuple(flags),
        details=details,
    )


def _gate_package(
    our_item: ReferenceItem,
    candidate: CandidateItem,
    config: CandidateSelectionConfig,
) -> _GateResult:
    our_markers = _matched_markers(norm_text(our_item.title), config.pack_markers)
    candidate_markers = _matched_markers(
        norm_text(candidate.title), config.pack_markers
    )
    mismatch = bool(our_markers) != bool(candidate_markers)
    return _GateResult(
        action=CandidateStatus.REJECTED if mismatch else None,
        reason="PACK_MISMATCH" if mismatch else None,
        details={
            "reference_is_pack": bool(our_markers),
            "candidate_is_pack": bool(candidate_markers),
            "reference_markers": our_markers,
            "candidate_markers": candidate_markers,
        },
    )


def _gate_applicability(
    our_item: ReferenceItem,
    candidate: CandidateItem,
    config: CandidateSelectionConfig,
) -> _GateResult:
    reference = _extract_applicability(our_item.title, config.applicability)
    current = _extract_applicability(candidate.title, config.applicability)
    details = {
        "reference": _applicability_dict(reference),
        "candidate": _applicability_dict(current),
    }
    if (
        reference.brands
        and current.brands
        and reference.brands.isdisjoint(current.brands)
    ):
        return _GateResult(
            action=CandidateStatus.REJECTED,
            reason="BRAND_MISMATCH",
            details=details,
        )
    if not reference.models or not current.models:
        return _GateResult(
            flag="APPLICABILITY_UNKNOWN",
            details=details,
        )
    common_models = reference.models & current.models
    if common_models:
        if (
            reference.generations
            and current.generations
            and reference.generations.isdisjoint(current.generations)
        ):
            if _years_overlap(reference.years, current.years):
                return _GateResult(flag="YEARS_PARTIAL", details=details)
            return _GateResult(
                action=CandidateStatus.REJECTED,
                reason="APPLICABILITY_MISMATCH",
                details=details,
            )
        if not reference.generations or not current.generations:
            return _GateResult(
                flag="APPLICABILITY_UNKNOWN",
                details=details,
            )
        return _GateResult(details=details)

    platform = _shared_platform(
        reference.models,
        current.models,
        config.applicability.platform_families,
    )
    if platform is not None:
        details["shared_platform"] = platform
        return _GateResult(flag="SAME_PLATFORM", details=details)
    return _GateResult(
        action=CandidateStatus.REJECTED,
        reason="APPLICABILITY_MISMATCH",
        details=details,
    )


def _gate_tier_classification(
    our_item: ReferenceItem,
    candidate: CandidateItem,
    *,
    brand_tiers: Mapping[str, ProductTier] | None,
) -> _GateResult:
    """Classify the candidate's level and reject only proven second-hand goods.

    This gate never stops a listing for an *unknown* level.  Not knowing the
    level is a limit of our brand dictionary, not a property of the listing,
    and the customer is entitled to see it either way.
    """

    classification = classify_tier(
        brand=candidate.brand,
        title=candidate.title,
        description=candidate.description,
        condition=candidate.condition,
        brand_tiers=brand_tiers,
    )
    reference_tier = our_item.tier
    if reference_tier is None:
        reference_tier = classify_tier(
            brand=our_item.brand,
            title=our_item.title,
            brand_tiers=brand_tiers,
        ).tier
    details = {
        "tier": classification.tier.value,
        "confidence": str(classification.confidence),
        "reasons": list(classification.reasons),
        "reference_tier": reference_tier.value,
    }
    if classification.tier is ProductTier.USED:
        return _GateResult(
            action=CandidateStatus.REJECTED,
            reason="USED_BY_TIER",
            details=details,
            predicted_tier=classification.tier,
            tier_confidence=classification.confidence,
        )
    return _GateResult(
        details=details,
        predicted_tier=classification.tier,
        tier_confidence=classification.confidence,
    )


def _gate_own_brand(
    candidate: CandidateItem,
    config: CandidateSelectionConfig,
    *,
    tier: ProductTier,
) -> _GateResult:
    """Hold back our own brand from the target basis, but keep it visible.

    Another shop reselling our own brand prices our product, not the market we
    price against, so its price must not move ours.  It is still shown, and it
    remains available to premium calibration as the KEMP anchor — those are two
    different sets and the calibration path reads its own.
    """

    by_tier = tier is ProductTier.KEMP
    by_seller = candidate.seller_id in config.kemp_network_seller_ids
    if not (by_tier or by_seller):
        return _GateResult(details={"is_own_brand": False})
    return _GateResult(
        action=CandidateStatus.REFERENCE_ONLY,
        reason="OWN_BRAND",
        details={
            "is_own_brand": True,
            "matched_by": "TIER" if by_tier else "SELLER_NETWORK",
            "tier": tier.value,
        },
    )


def _gate_tier_known(tier: ProductTier, *, tier_agnostic: bool) -> _GateResult:
    if tier is ProductTier.UNKNOWN:
        if tier_agnostic:
            # The owner prices against the cheapest comparable offer whatever
            # its level, so an unclassified brand is no longer a reason to hold
            # the offer back.  The flag keeps the admission attributable: it
            # marks every candidate that entered the basis only because of that
            # decision, so its effect stays measurable afterwards.
            return _GateResult(
                flag="TIER_UNKNOWN_ACCEPTED",
                details={"tier": tier.value, "admitted_by": "TIER_AGNOSTIC_POLICY"},
            )
        return _GateResult(
            action=CandidateStatus.REFERENCE_ONLY,
            reason="TIER_UNKNOWN",
            details={"tier": tier.value},
        )
    return _GateResult(details={"tier": tier.value})


def _gate_premium_calibration(
    our_item: ReferenceItem,
    *,
    tier: ProductTier,
    calibrated_premiums: Mapping[tuple[str, ProductTier], Decimal] | None,
    tier_agnostic: bool,
) -> _GateResult:
    """Require a validated coefficient before a price may be converted.

    Without one there is no defensible way to express a competitor's price at
    our own level, and comparing raw prices across levels is exactly the error
    that would recommend raising a budget part to the price of an original.
    A candidate at our own level needs no coefficient: the ratio is one by
    construction.

    ``tier_agnostic`` retires that requirement, and only a minimum-based target
    earns the right to retire it.  Converting levels matters for a central
    statistic, where dear originals drag the estimate upwards; the minimum of a
    mixture is almost never taken by the dearest level, so it selects the lowest
    one present without any coefficient.  The error the gate was built to
    prevent cannot occur in the direction the owner asked for — and where only
    originals are on the market he has explicitly chosen the cheapest of them
    as the target.
    """

    category = (our_item.category or "").strip().casefold()
    reference_tier = our_item.tier
    if reference_tier is not None and reference_tier is tier:
        return _GateResult(
            details={
                "premium": "1",
                "source": "SAME_TIER_IDENTITY",
                "category": category,
                "tier": tier.value,
            }
        )
    if tier_agnostic:
        return _GateResult(
            flag="TIER_AGNOSTIC_PRICING",
            details={
                "premium": "1",
                "source": "TIER_AGNOSTIC_OWNER_POLICY",
                "category": category,
                "tier": tier.value,
            },
        )
    premium = (calibrated_premiums or {}).get((category, tier))
    if premium is None or premium <= 0 or not premium.is_finite():
        return _GateResult(
            action=CandidateStatus.REFERENCE_ONLY,
            reason="PREMIUM_NOT_CALIBRATED",
            details={
                "premium": None if premium is None else str(premium),
                "source": "VALIDATED_COEFFICIENT_MISSING",
                "category": category,
                "tier": tier.value,
            },
        )
    return _GateResult(
        details={
            "premium": str(premium),
            "source": "VALIDATED_COEFFICIENT",
            "category": category,
            "tier": tier.value,
        }
    )


def _gate_price_anomaly(
    our_item: ReferenceItem,
    candidate: CandidateItem,
    config: CandidateSelectionConfig,
    *,
    tier: ProductTier,
    tier_agnostic: bool,
) -> _GateResult:
    if our_item.price is None or our_item.price <= 0:
        return _GateResult(
            details={"checked": False, "reason": "REFERENCE_PRICE_MISSING"}
        )
    category = (our_item.category or "").strip().casefold()
    if tier_agnostic:
        # No level is converted, so the premium is one by policy rather than by
        # lookup.  This is not a formality: ``unknown`` carries no configured
        # premium, so keeping the lookup here would report ``checked: False``
        # and switch the only remaining price guard off for precisely the
        # unclassified offers that the tier-agnostic decision lets in.
        premium = Decimal("1")
    else:
        premiums = config.price_anomaly.category_tier_premiums.get(
            category,
            config.price_anomaly.default_tier_premiums,
        )
        looked_up = premiums.get(tier)
        if looked_up is None or looked_up <= 0:
            return _GateResult(
                details={
                    "checked": False,
                    "reason": "TIER_PREMIUM_MISSING",
                    "tier": tier.value,
                }
            )
        premium = looked_up
    normalized_price = candidate.price / premium
    ratio = normalized_price / our_item.price
    anomaly = (
        ratio < config.price_anomaly.minimum_ratio
        or ratio > config.price_anomaly.maximum_ratio
    )
    return _GateResult(
        flag="PRICE_ANOMALY" if anomaly else None,
        details={
            "checked": True,
            "tier": tier.value,
            "tier_premium": str(premium),
            "normalized_price": str(normalized_price),
            "reference_price": str(our_item.price),
            "ratio": str(ratio),
            "minimum_ratio": str(config.price_anomaly.minimum_ratio),
            "maximum_ratio": str(config.price_anomaly.maximum_ratio),
        },
    )


def _matched_markers(text: str, markers: TextMarkers) -> list[str]:
    normalized = norm_text(text)
    result: list[str] = []
    for value in markers.words:
        token = norm_text(value).strip()
        if token and f" {token} " in normalized:
            result.append(value)
    for value in markers.phrases:
        phrase = norm_text(value).strip()
        if phrase and f" {phrase} " in normalized:
            result.append(value)
    words = normalized.strip().split()
    for value in markers.prefixes:
        prefix = norm_text(value).strip()
        if prefix and any(word.startswith(prefix) for word in words):
            result.append(value)
    compact = normalized.strip()
    for value in markers.substrings:
        substring = norm_text(value).strip()
        if substring and substring in compact:
            result.append(value)
    for pattern in markers.regex:
        if re.search(pattern, normalized, flags=re.IGNORECASE | re.UNICODE):
            result.append(pattern)
    return list(dict.fromkeys(result))


def _axis_values(
    title: str,
    values: Mapping[str, TextMarkers],
) -> frozenset[str]:
    normalized = norm_text(title)
    return frozenset(
        value
        for value, markers in values.items()
        if _matched_markers(normalized, markers)
    )


def _extract_applicability(
    title: str,
    config: ApplicabilityDictionary,
) -> _Applicability:
    normalized = norm_text(title)
    years = [int(value) for value in re.findall(config.year_regex, title)]
    interval = (min(years), max(years)) if years else None
    return _Applicability(
        brands=_dictionary_matches(normalized, config.brands),
        models=_dictionary_matches(normalized, config.models),
        generations=_dictionary_matches(normalized, config.generations),
        years=interval,
    )


def _dictionary_matches(
    normalized_text: str,
    dictionary: Mapping[str, tuple[str, ...]],
) -> frozenset[str]:
    return frozenset(
        canonical
        for canonical, aliases in dictionary.items()
        if any(
            f" {norm_text(alias).strip()} " in normalized_text
            for alias in aliases
            if norm_text(alias).strip()
        )
    )


def _applicability_dict(value: _Applicability) -> dict[str, Any]:
    return {
        "brands": sorted(value.brands),
        "models": sorted(value.models),
        "generations": sorted(value.generations),
        "years": list(value.years) if value.years is not None else None,
    }


def _shared_platform(
    left: frozenset[str],
    right: frozenset[str],
    families: Mapping[str, frozenset[str]],
) -> str | None:
    for family, models in families.items():
        if left & models and right & models:
            return family
    return None


def _years_overlap(
    left: tuple[int, int] | None,
    right: tuple[int, int] | None,
) -> bool:
    if left is None or right is None:
        return False
    return max(left[0], right[0]) <= min(left[1], right[1])


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CandidateSelectionConfigError(f"{field} must be a mapping")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateSelectionConfigError(f"{field} must be non-empty text")
    return value.strip()


def _text_set(value: Any, field: str) -> frozenset[str]:
    if not isinstance(value, list):
        raise CandidateSelectionConfigError(f"{field} must be a list")
    result = frozenset(_text(item, f"{field}[]") for item in value)
    return result


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CandidateSelectionConfigError(f"{field} must be a list")
    return tuple(_text(item, f"{field}[]") for item in value)


def _markers(value: Any, field: str) -> TextMarkers:
    payload = _mapping(value, field)
    markers = TextMarkers(
        words=_string_tuple(payload.get("words"), f"{field}.words"),
        phrases=_string_tuple(payload.get("phrases"), f"{field}.phrases"),
        prefixes=_string_tuple(payload.get("prefixes"), f"{field}.prefixes"),
        substrings=_string_tuple(payload.get("substrings"), f"{field}.substrings"),
        regex=tuple(
            _valid_regex(pattern, f"{field}.regex[]")
            for pattern in _string_tuple(payload.get("regex"), f"{field}.regex")
        ),
    )
    if not any(
        (
            markers.words,
            markers.phrases,
            markers.prefixes,
            markers.substrings,
            markers.regex,
        )
    ):
        raise CandidateSelectionConfigError(f"{field} must define at least one marker")
    return markers


def _valid_regex(value: Any, field: str) -> str:
    pattern = _text(value, field)
    try:
        re.compile(pattern)
    except re.error as exc:
        raise CandidateSelectionConfigError(
            f"{field} is not a valid regular expression"
        ) from exc
    return pattern


def _alias_dictionary(
    value: Any,
    field: str,
) -> Mapping[str, tuple[str, ...]]:
    payload = _mapping(value, field)
    result: dict[str, tuple[str, ...]] = {}
    for canonical, raw_record in payload.items():
        record = _mapping(raw_record, f"{field}.{canonical}")
        aliases = _string_tuple(record.get("aliases"), f"{field}.{canonical}.aliases")
        if not aliases:
            raise CandidateSelectionConfigError(
                f"{field}.{canonical}.aliases cannot be empty"
            )
        result[str(canonical)] = aliases
    return MappingProxyType(result)


def _platform_families(value: Any) -> Mapping[str, frozenset[str]]:
    payload = _mapping(value, "applicability.platform_families")
    result: dict[str, frozenset[str]] = {}
    for family, raw_record in payload.items():
        record = _mapping(raw_record, f"applicability.platform_families.{family}")
        models = _text_set(
            record.get("models"),
            f"applicability.platform_families.{family}.models",
        )
        if len(models) < 2:
            raise CandidateSelectionConfigError(
                f"platform family {family} must contain at least two models"
            )
        result[str(family)] = models
    return MappingProxyType(result)


def _ancestor_paths(value: Any, field: str) -> tuple[tuple[int, ...], ...]:
    """Parse a list of category ancestries into element-wise integer tuples."""

    if value is None:
        return ()
    if not isinstance(value, list):
        raise CandidateSelectionConfigError(f"{field} must be a list")
    result: list[tuple[int, ...]] = []
    for index, entry in enumerate(value):
        record = _mapping(entry, f"{field}[{index}]")
        raw_path = record.get("path")
        if not isinstance(raw_path, list) or not raw_path:
            raise CandidateSelectionConfigError(
                f"{field}[{index}].path must be a non-empty list"
            )
        path: list[int] = []
        for element in raw_path:
            if isinstance(element, bool) or not isinstance(element, int):
                raise CandidateSelectionConfigError(
                    f"{field}[{index}].path must contain integers only"
                )
            path.append(element)
        # A human-readable label is mandatory so the policy stays auditable.
        _text(record.get("label"), f"{field}[{index}].label")
        result.append(tuple(path))
    duplicates = len(result) - len({*result})
    if duplicates:
        raise CandidateSelectionConfigError(f"{field} contains duplicate paths")
    return tuple(result)


def _category_domain(value: Any) -> CategoryDomainConfig:
    payload = _mapping(value, "category_domain")
    blocked = _ancestor_paths(
        payload.get("blocked_ancestors"), "category_domain.blocked_ancestors"
    )
    allowed = _ancestor_paths(
        payload.get("allowed_ancestors"), "category_domain.allowed_ancestors"
    )
    overlap = sorted(set(blocked) & set(allowed))
    if overlap:
        raise CandidateSelectionConfigError(
            f"category_domain lists the same ancestor as blocked and allowed: {overlap}"
        )
    majority = _mapping(
        payload.get("majority_vote", {}), "category_domain.majority_vote"
    )
    depth = majority.get("prefix_depth", 3)
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
        raise CandidateSelectionConfigError(
            "category_domain.majority_vote.prefix_depth must be a positive integer"
        )
    min_candidates = majority.get("min_candidates", 5)
    if (
        isinstance(min_candidates, bool)
        or not isinstance(min_candidates, int)
        or min_candidates < 1
    ):
        raise CandidateSelectionConfigError(
            "category_domain.majority_vote.min_candidates must be a positive integer"
        )
    min_share = _positive_decimal(
        majority.get("min_share", "0.6"),
        "category_domain.majority_vote.min_share",
    )
    if min_share > 1:
        raise CandidateSelectionConfigError(
            "category_domain.majority_vote.min_share must not exceed 1"
        )
    allowlist_enforced = bool(payload.get("allowlist_enforced", False))
    if allowlist_enforced and not allowed:
        raise CandidateSelectionConfigError(
            "category_domain.allowlist_enforced requires allowed_ancestors"
        )
    trusted_default = [
        {
            "path": [0, 55],
            "label": "Автозапчастини та аксесуари",
        }
    ]
    trusted = _ancestor_paths(
        payload.get("trusted_automotive_ancestors", trusted_default),
        "category_domain.trusted_automotive_ancestors",
    )
    semantic = _mapping(
        payload.get("semantic_markers", {}),
        "category_domain.semantic_markers",
    )
    automotive_markers = _markers(
        semantic.get(
            "automotive",
            _DEFAULT_CATEGORY_DOMAIN_AUTOMOTIVE_MARKERS,
        ),
        "category_domain.semantic_markers.automotive",
    )
    non_automotive_markers = _markers(
        semantic.get(
            "non_automotive",
            _DEFAULT_CATEGORY_DOMAIN_NON_AUTOMOTIVE_MARKERS,
        ),
        "category_domain.semantic_markers.non_automotive",
    )
    return CategoryDomainConfig(
        enabled=bool(payload.get("enabled", False)),
        blocked_ancestors=blocked,
        allowed_ancestors=allowed,
        allowlist_enforced=allowlist_enforced,
        majority_vote_enabled=bool(majority.get("enabled", False)),
        majority_prefix_depth=depth,
        majority_min_candidates=min_candidates,
        majority_min_share=min_share,
        trusted_automotive_ancestors=trusted,
        automotive_markers=automotive_markers,
        non_automotive_markers=non_automotive_markers,
        require_semantic_for_unknown=bool(
            payload.get("require_semantic_for_unknown", True)
        ),
    )


def _positive_decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CandidateSelectionConfigError(f"{field} must be numeric") from exc
    if not result.is_finite() or result <= 0:
        raise CandidateSelectionConfigError(f"{field} must be positive")
    return result


def _tier_premiums(
    value: Any,
    field: str,
) -> Mapping[ProductTier, Decimal]:
    payload = _mapping(value, field)
    result: dict[ProductTier, Decimal] = {}
    for raw_tier, raw_premium in payload.items():
        try:
            tier = ProductTier(str(raw_tier))
        except ValueError as exc:
            raise CandidateSelectionConfigError(
                f"{field} contains unsupported tier {raw_tier!r}"
            ) from exc
        result[tier] = _positive_decimal(raw_premium, f"{field}.{raw_tier}")
    return MappingProxyType(result)


__all__ = [
    "CANDIDATE_COMPARABILITY_GATES",
    "CANDIDATE_GATE_ORDER",
    "CANDIDATE_IDENTITY_GATES",
    "CANDIDATE_SELECTION_SCHEMA_VERSION",
    "CandidateItem",
    "CandidateSelectionConfig",
    "CandidateSelectionConfigError",
    "CandidateStatus",
    "CandidateVerdict",
    "CategoryDomainConfig",
    "CategoryDomainContext",
    "ReferenceItem",
    "build_category_domain_context",
    "check_candidate",
    "load_candidate_selection_config",
    "norm_oem",
    "norm_text",
    "verdict_histogram",
]
