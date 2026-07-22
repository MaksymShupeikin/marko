"""Deterministic fitment scoring and advisory market aggregation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP
import math
import re
import unicodedata

from metis.pricing.types import ProductTier

from .types import (
    Availability,
    CommercialContext,
    ComparableOffer,
    CompatibilityAssessment,
    CompatibilityStatus,
    Condition,
    EvidenceClaim,
    FitmentFeature,
    FeatureConsensus,
    MarketEnvelope,
    PartIdentity,
    PriceAdvice,
    PriceComparabilityAssessment,
    PriceComparabilityStatus,
    SellerRelation,
    SourceTier,
    StatementStatus,
)


FITMENT_CONTRACT_VERSION = "metis-distributed-fitment-v2"
FITMENT_SCORING_VERSION = "fitment-logit-v2"

ZERO = Decimal("0")
ONE = Decimal("1")
HALF = Decimal("0.5")

FEATURE_WEIGHTS: Mapping[FitmentFeature, Decimal] = {
    FitmentFeature.ARTICLE_IDENTITY: Decimal("0.18"),
    # OE_EXACT is the storage key for the shared
    # ``exact_oe_or_supersession`` scoring dimension.  Supersession is an
    # alternative proof of that same 0.24 mass, not an intrinsically weaker
    # feature and not an additional 0.24 bonus.
    FitmentFeature.OE_EXACT: Decimal("0.24"),
    FitmentFeature.OE_SUPERSESSION: ZERO,
    FitmentFeature.CROSS_CONFIRMED: Decimal("0.16"),
    FitmentFeature.PART_CATEGORY: Decimal("0.08"),
    FitmentFeature.AXLE: Decimal("0.08"),
    FitmentFeature.SIDE: Decimal("0.08"),
    FitmentFeature.VEHICLE_MAKE_MODEL: Decimal("0.07"),
    FitmentFeature.GENERATION: Decimal("0.05"),
    FitmentFeature.YEAR_OVERLAP: Decimal("0.02"),
    FitmentFeature.ENGINE: Decimal("0.01"),
    FitmentFeature.BODY: Decimal("0.01"),
    # Market is a hard-scope evidence feature.  Its scoring mass is already
    # contained in the make/model scope, so it must not add a second bonus.
    FitmentFeature.VEHICLE_MARKET: ZERO,
    FitmentFeature.TECHNICAL_SPECS: Decimal("0.02"),
}

if sum(FEATURE_WEIGHTS.values(), ZERO) != ONE:  # pragma: no cover - import invariant
    raise RuntimeError("fitment feature weights must sum to one")

_PART_NUMBER_RE = re.compile(r"[^0-9A-Z]+")
_SPACE_RE = re.compile(r"\s+")

_AXLE_ALIASES = {
    "rear": "rear",
    "back": "rear",
    "задний": "rear",
    "задній": "rear",
    "front": "front",
    "передний": "front",
    "передній": "front",
}
_SIDE_ALIASES = {
    "right": "right",
    "rh": "right",
    "r/h": "right",
    "правый": "right",
    "правий": "right",
    "left": "left",
    "lh": "left",
    "l/h": "left",
    "левый": "left",
    "лівий": "left",
}
_CATEGORY_ALIASES = {
    "shock absorber": "shock_absorber",
    "damper": "shock_absorber",
    "амортизатор": "shock_absorber",
    "амортизатори": "shock_absorber",
    "brake pad": "brake_pad",
    "brake pads": "brake_pad",
    "тормозные колодки": "brake_pad",
    "гальмівні колодки": "brake_pad",
}


def normalize_part_number(value: str | None) -> str | None:
    """Normalize an OE/article without ever parsing it as an integer."""

    normalized = _PART_NUMBER_RE.sub(
        "", unicodedata.normalize("NFKC", value or "").upper().strip()
    )
    return normalized or None


def normalize_term(value: str | None) -> str | None:
    normalized = _SPACE_RE.sub(
        " ", unicodedata.normalize("NFKC", value or "").casefold().strip()
    )
    return normalized or None


def canonical_axle(value: str | None) -> str | None:
    normalized = normalize_term(value)
    return _AXLE_ALIASES.get(normalized or "", normalized)


def canonical_side(value: str | None) -> str | None:
    normalized = normalize_term(value)
    return _SIDE_ALIASES.get(normalized or "", normalized)


def canonical_category(value: str | None) -> str | None:
    normalized = normalize_term(value)
    return _CATEGORY_ALIASES.get(normalized or "", normalized)


def _canonical_vehicle(value: str | None) -> str | None:
    normalized = normalize_term(value)
    return normalized.replace(" ", "") if normalized else None


def _feature_consensus(claims: Sequence[EvidenceClaim]) -> FeatureConsensus:
    if not claims:
        raise ValueError("feature consensus requires at least one claim")

    groups: dict[str, list[EvidenceClaim]] = defaultdict(list)
    for claim in claims:
        groups[claim.correlation_group].append(claim)

    group_support: list[tuple[Decimal, Decimal]] = []
    evidence_ids: list[str] = []
    positive = False
    negative = False
    for group_claims in groups.values():
        evidence_ids.extend(claim.evidence_id for claim in group_claims)
        signed_claims = [
            claim
            for claim in group_claims
            if claim.value != ZERO and claim.effective_weight > ZERO
        ]
        if not signed_claims:
            continue
        # A correlation group represents one upstream source. Maxima make
        # repeated mirrors idempotent while retaining a conservative net vote
        # when that upstream group contains conflicting claims.
        positive_signal = max(
            (
                claim.effective_weight * claim.value
                for claim in signed_claims
                if claim.value > ZERO
            ),
            default=ZERO,
        )
        negative_signal = max(
            (
                claim.effective_weight * -claim.value
                for claim in signed_claims
                if claim.value < ZERO
            ),
            default=ZERO,
        )
        group_support.append((positive_signal, negative_signal))
        positive = positive or positive_signal > ZERO
        negative = negative or negative_signal > ZERO

    positive_product = ONE
    negative_product = ONE
    for positive_signal, negative_signal in group_support:
        positive_product *= ONE - positive_signal
        negative_product *= ONE - negative_signal
    positive_support = ONE - positive_product if group_support else ZERO
    negative_support = ONE - negative_product if group_support else ZERO
    conflict_mass = min(positive_support, negative_support)
    consensus = positive_support - negative_support
    coverage = max(positive_support, negative_support) > Decimal("0.10")
    return FeatureConsensus(
        feature=claims[0].feature,
        consensus=_clamp(consensus, Decimal("-1"), ONE).quantize(Decimal("0.0001")),
        positive_support=positive_support.quantize(Decimal("0.0001")),
        negative_support=negative_support.quantize(Decimal("0.0001")),
        conflict_mass=conflict_mass.quantize(Decimal("0.0001")),
        coverage=coverage,
        evidence_present=bool(group_support),
        contradiction=positive and negative,
        independent_group_count=len(group_support),
        evidence_ids=tuple(sorted(set(evidence_ids))),
    )


def _structured_identity_conflicts(
    target: PartIdentity,
    candidate: PartIdentity,
) -> tuple[tuple[str, FitmentFeature], ...]:
    conflicts: list[tuple[str, FitmentFeature]] = []
    comparisons = (
        (
            "SIDE_MISMATCH",
            FitmentFeature.SIDE,
            canonical_side(target.side),
            canonical_side(candidate.side),
            target.side_specific,
        ),
        (
            "AXLE_MISMATCH",
            FitmentFeature.AXLE,
            canonical_axle(target.axle),
            canonical_axle(candidate.axle),
            True,
        ),
        (
            "PART_CATEGORY_MISMATCH",
            FitmentFeature.PART_CATEGORY,
            canonical_category(target.category),
            canonical_category(candidate.category),
            True,
        ),
        (
            "VEHICLE_MAKE_MISMATCH",
            FitmentFeature.VEHICLE_MAKE_MODEL,
            _canonical_vehicle(target.vehicle_make),
            _canonical_vehicle(candidate.vehicle_make),
            True,
        ),
        (
            "VEHICLE_MODEL_MISMATCH",
            FitmentFeature.VEHICLE_MAKE_MODEL,
            _canonical_vehicle(target.vehicle_model),
            _canonical_vehicle(candidate.vehicle_model),
            True,
        ),
        (
            "GENERATION_MISMATCH",
            FitmentFeature.GENERATION,
            _canonical_vehicle(target.generation),
            _canonical_vehicle(candidate.generation),
            True,
        ),
        (
            "VEHICLE_MARKET_MISMATCH",
            FitmentFeature.VEHICLE_MARKET,
            normalize_term(target.vehicle_market),
            normalize_term(candidate.vehicle_market),
            True,
        ),
    )
    for reason, feature, expected, actual, applicable in comparisons:
        if (
            applicable
            and expected is not None
            and actual is not None
            and expected != actual
        ):
            conflicts.append((reason, feature))
    if (
        target.year_from is not None
        and target.year_to is not None
        and candidate.year_from is not None
        and candidate.year_to is not None
        and max(target.year_from, candidate.year_from)
        > min(target.year_to, candidate.year_to)
    ):
        conflicts.append(("YEAR_RANGE_DISJOINT", FitmentFeature.YEAR_OVERLAP))
    shared_specs = set(target.technical_specs) & set(candidate.technical_specs)
    if any(
        normalize_term(target.technical_specs[key])
        != normalize_term(candidate.technical_specs[key])
        for key in shared_specs
    ):
        conflicts.append(
            ("CRITICAL_TECHNICAL_MISMATCH", FitmentFeature.TECHNICAL_SPECS)
        )
    return tuple(conflicts)


def _authoritative_negative_feature(
    feature: FitmentFeature,
    claims: Sequence[EvidenceClaim],
) -> bool:
    """Require one strong catalog or two independent negative sources.

    A raw marketplace field or one copied description may lower the heuristic
    score, but it cannot trigger a non-overridable automotive hard rejection.
    """

    relevant = tuple(
        claim
        for claim in claims
        if claim.feature == feature
        and claim.value < ZERO
        and claim.statement_status == StatementStatus.FACT
        and claim.effective_weight >= Decimal("0.50")
    )
    if any(
        claim.source_tier in {SourceTier.A, SourceTier.B}
        and claim.effective_weight >= Decimal("0.60")
        for claim in relevant
    ):
        return True
    return len({claim.correlation_group for claim in relevant}) >= 2


def _hard_rejections(
    target: PartIdentity,
    candidate: PartIdentity,
    claims: Sequence[EvidenceClaim],
) -> tuple[str, ...]:
    return tuple(
        reason
        for reason, feature in _structured_identity_conflicts(target, candidate)
        if _authoritative_negative_feature(feature, claims)
    )


def _missing_critical(
    target: PartIdentity,
    consensus: Mapping[FitmentFeature, FeatureConsensus],
) -> tuple[str, ...]:
    required = [
        ("part_category", (FitmentFeature.PART_CATEGORY,)),
        ("axle", (FitmentFeature.AXLE,)),
        ("vehicle_make_model", (FitmentFeature.VEHICLE_MAKE_MODEL,)),
        (
            "verified_identifier",
            (
                FitmentFeature.ARTICLE_IDENTITY,
                FitmentFeature.OE_EXACT,
                FitmentFeature.OE_SUPERSESSION,
                FitmentFeature.CROSS_CONFIRMED,
            ),
        ),
    ]
    if target.side_specific:
        required.append(("side", (FitmentFeature.SIDE,)))
    return tuple(
        name
        for name, features in required
        if not any(
            consensus.get(feature)
            and consensus[feature].evidence_present
            and consensus[feature].consensus > ZERO
            for feature in features
        )
    )


def _identity_conflict_rejections(
    consensus: Mapping[FitmentFeature, FeatureConsensus],
    claims: Sequence[EvidenceClaim],
) -> tuple[str, ...]:
    """Reject a disproved OE unless a verified replacement/cross resolves it.

    A negative exact-OE claim is not by itself proof that two parts are
    incompatible: supersessions and confirmed cross references legitimately
    connect different numbers.  It becomes a terminal identity conflict only
    when neither of those positive bridges exists.
    """

    exact = consensus.get(FitmentFeature.OE_EXACT)
    if exact is None or exact.consensus > Decimal("-0.5"):
        return ()
    bridged = any(
        consensus.get(feature)
        and consensus[feature].consensus >= Decimal("0.5")
        for feature in (
            FitmentFeature.OE_SUPERSESSION,
            FitmentFeature.CROSS_CONFIRMED,
        )
    )
    return (
        ()
        if bridged
        or not _authoritative_negative_feature(FitmentFeature.OE_EXACT, claims)
        else ("OE_IDENTITY_CONFLICT",)
    )


def _critical_evidence_rejections(
    target: PartIdentity,
    consensus: Mapping[FitmentFeature, FeatureConsensus],
    claims: Sequence[EvidenceClaim],
) -> tuple[str, ...]:
    checks = (
        (FitmentFeature.PART_CATEGORY, "PART_CATEGORY_EVIDENCE_CONFLICT", True),
        (FitmentFeature.AXLE, "AXLE_EVIDENCE_CONFLICT", True),
        (FitmentFeature.SIDE, "SIDE_EVIDENCE_CONFLICT", target.side_specific),
        (FitmentFeature.GENERATION, "GENERATION_EVIDENCE_CONFLICT", True),
        (
            FitmentFeature.TECHNICAL_SPECS,
            "CRITICAL_TECHNICAL_MISMATCH",
            True,
        ),
    )
    return tuple(
        reason
        for feature, reason, applicable in checks
        if applicable
        and feature in consensus
        and consensus[feature].consensus <= Decimal("-0.5")
        and _authoritative_negative_feature(feature, claims)
    )


def _authoritative_confirmation(claims: Sequence[EvidenceClaim]) -> bool:
    identity_features = {
        FitmentFeature.ARTICLE_IDENTITY,
        FitmentFeature.OE_EXACT,
        FitmentFeature.OE_SUPERSESSION,
        FitmentFeature.CROSS_CONFIRMED,
    }
    tier_a_groups = {
        claim.correlation_group
        for claim in claims
        if claim.feature in identity_features
        and claim.value > ZERO
        and claim.source_tier == SourceTier.A
        and claim.statement_status == StatementStatus.FACT
        and claim.effective_weight >= Decimal("0.60")
    }
    tier_b_groups = {
        claim.correlation_group
        for claim in claims
        if claim.feature in identity_features
        and claim.value > ZERO
        and claim.source_tier == SourceTier.B
        and claim.statement_status == StatementStatus.FACT
        and claim.effective_weight >= Decimal("0.55")
    }
    return bool(tier_a_groups) or len(tier_b_groups) >= 2


def _scoring_components(
    consensus: Mapping[FitmentFeature, FeatureConsensus],
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Collapse alternative OE proofs into the prompt's ten dimensions."""

    dimension_groups: tuple[tuple[Decimal, tuple[FitmentFeature, ...]], ...] = (
        (Decimal("0.18"), (FitmentFeature.ARTICLE_IDENTITY,)),
        (
            Decimal("0.24"),
            (FitmentFeature.OE_EXACT, FitmentFeature.OE_SUPERSESSION),
        ),
        (Decimal("0.16"), (FitmentFeature.CROSS_CONFIRMED,)),
        (Decimal("0.08"), (FitmentFeature.PART_CATEGORY,)),
        (Decimal("0.08"), (FitmentFeature.AXLE,)),
        (Decimal("0.08"), (FitmentFeature.SIDE,)),
        (Decimal("0.07"), (FitmentFeature.VEHICLE_MAKE_MODEL,)),
        (Decimal("0.05"), (FitmentFeature.GENERATION,)),
        (Decimal("0.02"), (FitmentFeature.YEAR_OVERLAP,)),
        (Decimal("0.01"), (FitmentFeature.ENGINE,)),
        (Decimal("0.01"), (FitmentFeature.BODY,)),
        (Decimal("0.02"), (FitmentFeature.TECHNICAL_SPECS,)),
    )
    positive = ZERO
    negative = ZERO
    coverage = ZERO
    conflict = ZERO
    exact = consensus.get(FitmentFeature.OE_EXACT)
    supersession = consensus.get(FitmentFeature.OE_SUPERSESSION)
    cross = consensus.get(FitmentFeature.CROSS_CONFIRMED)
    bridge_support = max(
        supersession.positive_support if supersession else ZERO,
        cross.positive_support if cross else ZERO,
    )
    for weight, features in dimension_groups:
        values = [consensus[item] for item in features if item in consensus]
        if not values:
            continue
        dimension_positive = max((item.positive_support for item in values), default=ZERO)
        dimension_negative = max((item.negative_support for item in values), default=ZERO)
        dimension_conflict = max((item.conflict_mass for item in values), default=ZERO)
        # A verified supersession/cross explicitly explains why raw OE values
        # differ.  The mismatch must not be counted again as negative fitment
        # evidence, while a within-source exact-OE contradiction still is.
        if (
            FitmentFeature.OE_EXACT in features
            and bridge_support >= Decimal("0.5")
            and exact is not None
            and exact.positive_support == ZERO
        ):
            dimension_negative = max(
                supersession.negative_support if supersession else ZERO,
                dimension_conflict,
            )
        dimension_coverage = max(
            dimension_positive,
            dimension_negative,
        ) > Decimal("0.10")
        positive += weight * dimension_positive
        negative += weight * dimension_negative
        if dimension_coverage:
            coverage += weight
        conflict += weight * dimension_conflict
    return positive, negative, coverage, conflict


def assess_compatibility(
    target: PartIdentity,
    candidate: PartIdentity,
    claims: Iterable[EvidenceClaim],
) -> CompatibilityAssessment:
    """Apply hard rules and the versioned logistic scoring model."""

    collected = tuple(claims)
    by_feature: dict[FitmentFeature, list[EvidenceClaim]] = defaultdict(list)
    for claim in collected:
        by_feature[claim.feature].append(claim)
    consensus = {
        feature: _feature_consensus(by_feature[feature])
        for feature in FitmentFeature
        if by_feature.get(feature)
    }

    positive, negative, coverage, contradiction = _scoring_components(consensus)
    missing = _missing_critical(target, consensus)
    critical_weights = {
        "part_category": FEATURE_WEIGHTS[FitmentFeature.PART_CATEGORY],
        "axle": FEATURE_WEIGHTS[FitmentFeature.AXLE],
        "vehicle_make_model": FEATURE_WEIGHTS[FitmentFeature.VEHICLE_MAKE_MODEL],
        "verified_identifier": Decimal("0.24"),
    }
    if target.side_specific:
        critical_weights["side"] = FEATURE_WEIGHTS[FitmentFeature.SIDE]
    critical_total = sum(critical_weights.values(), ZERO)
    missing_ratio = (
        sum((critical_weights[name] for name in missing), ZERO) / critical_total
        if critical_total > ZERO
        else ONE
    )
    z = (
        Decimal("-1.8")
        + Decimal("5.2") * positive
        - Decimal("6.5") * negative
        + Decimal("1.0") * coverage
        - Decimal("2.8") * contradiction
        - Decimal("2.2") * missing_ratio
    )
    probability = Decimal(str(1 / (1 + math.exp(-float(z))))).quantize(
        Decimal("0.0001")
    )
    structured_conflicts = _structured_identity_conflicts(target, candidate)
    hard_rejections = tuple(
        dict.fromkeys(
            (
                *_hard_rejections(target, candidate, collected),
                *_identity_conflict_rejections(consensus, collected),
                *_critical_evidence_rejections(target, consensus, collected),
            )
        )
    )
    unverified_structured_conflicts = tuple(
        f"UNVERIFIED_{reason}"
        for reason, feature in structured_conflicts
        if not _authoritative_negative_feature(feature, collected)
    )
    if hard_rejections:
        probability = min(probability, Decimal("0.0500"))

    authoritative = _authoritative_confirmation(collected)
    critical_features = {
        FitmentFeature.ARTICLE_IDENTITY,
        FitmentFeature.OE_EXACT,
        FitmentFeature.OE_SUPERSESSION,
        FitmentFeature.CROSS_CONFIRMED,
        FitmentFeature.PART_CATEGORY,
        FitmentFeature.AXLE,
        FitmentFeature.VEHICLE_MAKE_MODEL,
    }
    if target.side_specific:
        critical_features.add(FitmentFeature.SIDE)
    critical_contradiction = any(
        item.contradiction
        for feature, item in consensus.items()
        if feature in critical_features
    )
    reason_codes: list[str] = list(hard_rejections)
    reason_codes.extend(unverified_structured_conflicts)
    if missing:
        reason_codes.append("MISSING_CRITICAL_EVIDENCE")
    if contradiction > ZERO:
        reason_codes.append("CONFLICTING_EVIDENCE")
    if negative > ZERO:
        reason_codes.append("NEGATIVE_EVIDENCE_PRESENT")
    if critical_contradiction:
        reason_codes.append("CRITICAL_EVIDENCE_CONFLICT")
    if not authoritative:
        reason_codes.append("AUTHORITATIVE_CONFIRMATION_MISSING")

    if hard_rejections:
        status = CompatibilityStatus.NOT_COMPATIBLE
    elif "verified_identifier" in missing:
        # Vehicle/title similarity is discovery evidence, never an identity
        # proof.  Without exact OE, supersession or a confirmed cross the
        # candidate cannot rise above the explicit uncertainty bucket.
        status = CompatibilityStatus.UNCERTAIN
    elif probability < Decimal("0.40"):
        status = CompatibilityStatus.NOT_COMPATIBLE
    elif probability < Decimal("0.70"):
        status = CompatibilityStatus.UNCERTAIN
    elif missing or unverified_structured_conflicts:
        status = CompatibilityStatus.LIKELY_COMPATIBLE
    elif (
        probability < Decimal("0.90")
        or not authoritative
        or contradiction > ZERO
        or negative > ZERO
    ):
        status = CompatibilityStatus.LIKELY_COMPATIBLE
    else:
        status = CompatibilityStatus.CONFIRMED_COMPATIBLE
    if status == CompatibilityStatus.CONFIRMED_COMPATIBLE and not reason_codes:
        reason_codes.append("FITMENT_CONFIRMED")
    elif status == CompatibilityStatus.LIKELY_COMPATIBLE:
        if probability < Decimal("0.90"):
            reason_codes.append("FITMENT_SCORE_BELOW_CONFIRMED_THRESHOLD")
        reason_codes.append("MANUAL_REVIEW_REQUIRED")

    return CompatibilityAssessment(
        contract_version=FITMENT_CONTRACT_VERSION,
        scoring_version=FITMENT_SCORING_VERSION,
        status=status,
        probability=probability,
        positive_evidence=positive.quantize(Decimal("0.0001")),
        negative_evidence=negative.quantize(Decimal("0.0001")),
        coverage=coverage.quantize(Decimal("0.0001")),
        contradiction_rate=contradiction.quantize(Decimal("0.0001")),
        missing_critical_ratio=missing_ratio.quantize(Decimal("0.0001")),
        hard_rejections=hard_rejections,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        missing_critical_fields=missing,
        feature_consensus=dict(
            sorted(consensus.items(), key=lambda item: item[0].value)
        ),
        authoritative_confirmation=authoritative,
        requires_manual_review=status != CompatibilityStatus.CONFIRMED_COMPATIBLE,
        evidence_ids=tuple(sorted({claim.evidence_id for claim in collected})),
    )


_AVAILABILITY_FACTORS = {
    Availability.IN_STOCK: ONE,
    Availability.PREORDER: Decimal("0.65"),
    Availability.UNKNOWN: Decimal("0.50"),
    Availability.OUT_OF_STOCK: Decimal("0.10"),
}


def _condition_factor(target: Condition, candidate: Condition) -> Decimal:
    if target == Condition.NEW and candidate == Condition.NEW:
        return ONE
    if target == Condition.NEW and candidate == Condition.REMANUFACTURED:
        return Decimal("0.45")
    if target == Condition.NEW and candidate == Condition.USED:
        return ZERO
    if Condition.UNKNOWN in {target, candidate}:
        return Decimal("0.30")
    return ONE if target == candidate else ZERO


_TIER_RANK = {
    ProductTier.OEM: 0,
    ProductTier.OES: 1,
    ProductTier.AFTERMARKET_A: 2,
    ProductTier.AFTERMARKET_B: 3,
    ProductTier.BUDGET: 4,
    ProductTier.KEMP: 4,
}


def _tier_factor(target: ProductTier, candidate: ProductTier) -> Decimal:
    if ProductTier.UNKNOWN in {target, candidate} or ProductTier.USED in {
        target,
        candidate,
    }:
        return ZERO
    distance = abs(_TIER_RANK[target] - _TIER_RANK[candidate])
    return (
        ONE if distance == 0 else Decimal("0.65") if distance == 1 else Decimal("0.25")
    )


def assess_price_comparability(
    fitment: CompatibilityAssessment,
    target: CommercialContext,
    candidate: CommercialContext,
    *,
    source_quality: Decimal,
    freshness_factor: Decimal,
) -> PriceComparabilityAssessment:
    """Keep commercial comparability separate from physical fitment."""

    for name, value in (
        ("source_quality", source_quality),
        ("freshness_factor", freshness_factor),
    ):
        if value < ZERO or value > ONE:
            raise ValueError(f"{name} must be in [0, 1]")

    reasons: list[str] = []
    hard_block = False
    manual_block = False
    if fitment.status not in {
        CompatibilityStatus.CONFIRMED_COMPATIBLE,
        CompatibilityStatus.LIKELY_COMPATIBLE,
    }:
        hard_block = True
        reasons.append("FITMENT_NOT_PRICE_ELIGIBLE")
    elif fitment.requires_manual_review:
        manual_block = True
        reasons.append("FITMENT_REVIEW_REQUIRED")
    if candidate.seller_relation in {SellerRelation.OWN, SellerRelation.RELATED}:
        hard_block = True
        reasons.append("OWN_OR_RELATED_SELLER")
    elif candidate.seller_relation != SellerRelation.INDEPENDENT:
        manual_block = True
        reasons.append("SELLER_INDEPENDENCE_UNVERIFIED")
    if not candidate.stable_seller_id_verified:
        manual_block = True
        reasons.append("STABLE_SELLER_ID_UNVERIFIED")

    condition_factor = _condition_factor(target.condition, candidate.condition)
    tier_factor = _tier_factor(target.tier, candidate.tier)
    availability_factor = _AVAILABILITY_FACTORS[candidate.availability]
    seller_factor = (
        ONE if candidate.seller_relation == SellerRelation.INDEPENDENT else ZERO
    )

    if condition_factor == ZERO:
        hard_block = True
        reasons.append("CONDITION_NOT_COMPARABLE")
    elif Condition.UNKNOWN in {target.condition, candidate.condition}:
        manual_block = True
        reasons.append("CONDITION_UNKNOWN")
    if target.package_quantity is None or candidate.package_quantity is None:
        manual_block = True
        reasons.append("PACKAGE_QUANTITY_UNKNOWN")
    elif target.package_quantity != candidate.package_quantity:
        hard_block = True
        reasons.append("PACKAGE_QUANTITY_MISMATCH")
    if not target.unit_basis or not candidate.unit_basis:
        manual_block = True
        reasons.append("UNIT_BASIS_UNKNOWN")
    elif normalize_term(target.unit_basis) != normalize_term(candidate.unit_basis):
        hard_block = True
        reasons.append("UNIT_BASIS_MISMATCH")
    if not target.currency or not candidate.currency:
        manual_block = True
        reasons.append("CURRENCY_UNKNOWN")
    elif target.currency.strip().upper() != candidate.currency.strip().upper():
        hard_block = True
        reasons.append("CURRENCY_MISMATCH")
    if target.vat_included is not None or candidate.vat_included is not None:
        if target.vat_included is None or candidate.vat_included is None:
            manual_block = True
            reasons.append("VAT_STATUS_UNKNOWN")
        elif target.vat_included != candidate.vat_included:
            manual_block = True
            reasons.append("VAT_BASIS_MISMATCH")
    if tier_factor == ZERO:
        manual_block = True
        reasons.append("TIER_NOT_COMPARABLE")
    if candidate.availability == Availability.OUT_OF_STOCK:
        hard_block = True
        reasons.append("OUT_OF_STOCK")

    eligible = not hard_block and not manual_block
    weight = (
        fitment.probability**2
        * source_quality
        * seller_factor
        * availability_factor
        * freshness_factor
        * tier_factor
        * condition_factor
        if eligible
        else ZERO
    ).quantize(Decimal("0.000001"))
    status = (
        PriceComparabilityStatus.NOT_COMPARABLE
        if hard_block
        else PriceComparabilityStatus.MANUAL_REVIEW
        if manual_block
        else PriceComparabilityStatus.COMPARABLE
    )
    if eligible:
        reasons.append("PRICE_COMPARABILITY_PASS")
    return PriceComparabilityAssessment(
        status=status,
        eligible_for_pricing=eligible,
        competitor_weight=weight,
        compatibility_factor=fitment.probability,
        source_quality_factor=source_quality,
        seller_independence_factor=seller_factor,
        availability_factor=availability_factor,
        freshness_factor=freshness_factor,
        tier_factor=tier_factor,
        condition_factor=condition_factor,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _weighted_quantile(
    values: Sequence[tuple[Decimal, Decimal]], quantile: Decimal
) -> Decimal | None:
    if not values:
        return None
    if quantile < ZERO or quantile > ONE:
        raise ValueError("quantile must be in [0, 1]")
    ordered = sorted(values, key=lambda item: (item[0], item[1]))
    total = sum((weight for _, weight in ordered), ZERO)
    if total <= ZERO:
        return None
    threshold = total * quantile
    cumulative = ZERO
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def build_market_envelope(
    offers: Iterable[ComparableOffer],
    *,
    article_weight_cap: Decimal = Decimal("1.5"),
    seller_group_cap: Decimal = ONE,
    min_independent_sellers: int = 3,
) -> MarketEnvelope:
    """Deduplicate commercial influence before computing weighted quantiles."""

    if article_weight_cap <= ZERO or seller_group_cap <= ZERO:
        raise ValueError("weight caps must be positive")
    eligible = [
        offer
        for offer in offers
        if offer.assessment.eligible_for_pricing
        and offer.assessment.competitor_weight > ZERO
    ]
    weights = {offer.offer_id: offer.assessment.competitor_weight for offer in eligible}
    by_article: dict[str, list[ComparableOffer]] = defaultdict(list)
    for offer in eligible:
        by_article[offer.brand_article_key].append(offer)
    for group in by_article.values():
        total = sum((weights[item.offer_id] for item in group), ZERO)
        if total > article_weight_cap:
            scale = article_weight_cap / total
            for item in group:
                weights[item.offer_id] *= scale

    by_seller: dict[str, list[ComparableOffer]] = defaultdict(list)
    for offer in eligible:
        by_seller[offer.seller_group_id].append(offer)
    for group in by_seller.values():
        total = sum((weights[item.offer_id] for item in group), ZERO)
        if total > seller_group_cap:
            scale = seller_group_cap / total
            for item in group:
                weights[item.offer_id] *= scale

    weighted = [(offer.price, weights[offer.offer_id]) for offer in eligible]
    seller_count = len({offer.seller_group_id for offer in eligible})
    sufficient = seller_count >= min_independent_sellers
    reasons = (
        ("MARKET_EVIDENCE_SUFFICIENT",)
        if sufficient
        else ("INSUFFICIENT_INDEPENDENT_SELLERS",)
    )
    quantiles = {
        quantile: _weighted_quantile(weighted, quantile)
        for quantile in (
            Decimal("0.20"),
            Decimal("0.25"),
            Decimal("0.35"),
            Decimal("0.50"),
            Decimal("0.75"),
            Decimal("0.80"),
        )
    }
    return MarketEnvelope(
        eligible_offer_count=len(eligible),
        independent_seller_count=seller_count,
        effective_weight=sum(weights.values(), ZERO).quantize(Decimal("0.000001")),
        weighted_q20=quantiles[Decimal("0.20")],
        weighted_q25=quantiles[Decimal("0.25")],
        weighted_q35=quantiles[Decimal("0.35")],
        weighted_median=quantiles[Decimal("0.50")],
        weighted_q75=quantiles[Decimal("0.75")],
        weighted_q80=quantiles[Decimal("0.80")],
        evidence_sufficient=sufficient,
        reason_codes=reasons,
    )


def advise_price(
    *,
    current_price: Decimal,
    market: MarketEnvelope,
    strategy: str = "balanced",
    undercut_fraction: Decimal = Decimal("0.02"),
    tolerance: Decimal = Decimal("0.05"),
    cost_price: Decimal | None = None,
    minimum_margin: Decimal | None = None,
    max_decrease: Decimal = Decimal("0.15"),
    max_increase: Decimal = Decimal("0.20"),
    price_tick: Decimal = Decimal("1"),
) -> PriceAdvice:
    """Produce advisory output only; this function has no publication side effect."""

    if current_price <= ZERO or price_tick <= ZERO:
        raise ValueError("current_price and price_tick must be positive")
    if not market.evidence_sufficient:
        return PriceAdvice(
            action="insufficient_data",
            current_price=current_price,
            recommended_price=None,
            recommended_range_min=market.weighted_q20,
            recommended_range_max=market.weighted_q80,
            absolute_change=None,
            relative_change=None,
            market=market,
        )
    anchors = {
        "competitive": market.weighted_q25,
        "balanced": market.weighted_q35,
        "margin_first": market.weighted_median,
    }
    if strategy not in anchors:
        raise ValueError("unknown pricing strategy")
    anchor = anchors[strategy]
    if anchor is None or market.weighted_q25 is None or market.weighted_q75 is None:
        raise ValueError("sufficient market envelope is missing required quantiles")
    target = anchor * (ONE - undercut_fraction)
    if cost_price is not None or minimum_margin is not None:
        if cost_price is None or minimum_margin is None:
            raise ValueError("cost_price and minimum_margin must be supplied together")
        if cost_price <= ZERO or minimum_margin < ZERO:
            raise ValueError("invalid margin floor")
        target = max(target, cost_price * (ONE + minimum_margin))
    target = _clamp(
        target,
        current_price * (ONE - max_decrease),
        current_price * (ONE + max_increase),
    )
    recommended = (target / price_tick).quantize(
        ZERO, rounding=ROUND_HALF_UP
    ) * price_tick
    if current_price < market.weighted_q25 * (ONE - tolerance):
        action = "consider_raise"
    elif current_price > market.weighted_q75 * (ONE + tolerance):
        action = "consider_reduce"
    else:
        action = "hold_or_minor_adjustment"
    change = recommended - current_price
    return PriceAdvice(
        action=action,
        current_price=current_price,
        recommended_price=recommended,
        recommended_range_min=market.weighted_q20,
        recommended_range_max=market.weighted_q80,
        absolute_change=change,
        relative_change=(change / current_price).quantize(Decimal("0.0001")),
        market=market,
    )


def _clamp(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    return max(minimum, min(value, maximum))
