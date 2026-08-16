"""Deterministic semantic safety gate shared by Prom acquisition paths.

The candidate-selection gates establish a cheap OE/category boundary.  This
module adds the next fail-closed layer: if the closed semantic extractor finds
an explicit contradiction (for example ``gas_spring`` versus ``wiper_blade``),
the offer remains visible but is not allowed into a pricing cohort.  It never
turns positive similarity into identity proof and never mutates a price.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any

from marko.services.semantic_candidate_features import (
    SEMANTIC_FEATURE_EXTRACTOR_VERSION,
    ambiguous_taxonomy_conflicts,
    build_semantic_feature_matrix,
)
from marko.services.offer_identity import identity_admission_snapshot_is_current
from metis.pricing.candidate_selection import (
    CandidateStatus,
    CandidateVerdict,
    ReferenceItem,
)


SEMANTIC_PRICING_GATE_VERSION = (
    "semantic-pricing-gate-v13-blocking-dimension-set"
)


def semantic_gate_snapshot_is_current(
    snapshot: Any,
    *,
    expected_source_listing_id: str | None = None,
    expected_raw_capture_id: str | None = None,
    expected_identity_key: str | None = None,
    require_identity_namespace: bool = False,
) -> bool:
    """Return whether a persisted candidate carries the active gate proof.

    A scalar ``automatic_eligible`` flag is not enough to authorize an old
    observation: gate logic and feature extraction are versioned, and a later
    safety fix must invalidate the earlier snapshot until the offer is freshly
    materialized.  When supplied, ``expected_source_listing_id`` and
    ``expected_raw_capture_id`` bind the proof to the candidate's immutable
    source locator; a valid gate copied from another retained offer is then
    rejected.  Callers at the calculation/calibration boundary use this helper
    as a fail-closed check.
    """

    if not isinstance(snapshot, Mapping):
        return False
    gate = snapshot.get("semantic_gate")
    if not isinstance(gate, Mapping):
        return False
    identity_admission = snapshot.get("identity_admission")
    if not isinstance(identity_admission, Mapping):
        return False
    if identity_admission.get("automatic_evidence_sufficient") is not True:
        return False
    if require_identity_namespace and not identity_admission_snapshot_is_current(
        identity_admission,
        expected_identity_key=expected_identity_key,
    ):
        return False
    # The semantic decision is evidence about one retained candidate, not a
    # reusable boolean.  Persisted callers know the listing/capture that they
    # are materialising; bind the snapshot to both identifiers so a copied or
    # stale gate from another observation cannot authorize this row.
    locator = snapshot.get("source_locator")
    if expected_source_listing_id is not None:
        expected_listing = str(expected_source_listing_id).strip()
        actual_listing = (
            str(locator.get("source_listing_id") or "").strip()
            if isinstance(locator, Mapping)
            else ""
        )
        if not expected_listing or actual_listing != expected_listing:
            return False
    if expected_raw_capture_id is not None:
        expected_capture = str(expected_raw_capture_id).strip()
        actual_capture = (
            str(locator.get("raw_capture_id") or "").strip()
            if isinstance(locator, Mapping)
            else ""
        )
        if not expected_capture or actual_capture != expected_capture:
            return False
    return (
        str(gate.get("status") or "").strip() == "PRICING_EVIDENCE"
        and str(gate.get("reason") or "").strip() == "OK"
        and str(gate.get("gate_version") or "").strip()
        == SEMANTIC_PRICING_GATE_VERSION
        and str(gate.get("extractor_version") or "").strip()
        == SEMANTIC_FEATURE_EXTRACTOR_VERSION
    )

# These are commercial facts, not confidence scores.  A candidate may be the
# same physical OE part and still have a different price basis (one piece,
# pair, kit, or an unknown unit).  In that situation the offer remains useful
# evidence for an operator, but it must not enter a deterministic price cohort.
SEMANTIC_PRICING_BASE_REQUIRED_DIMENSIONS = frozenset(
    {"condition", "package_quantity", "unit_basis"}
)

# Owner decision of 2026-08-15.  A dimension blocks a price only when getting it
# wrong sells the customer the wrong thing: the part family, its condition, and
# the unit the price is quoted in.  Everything else the extractor reads --
# fuel_type, assembly_level, position, power_rating, the vehicle axes and the
# rest of ``SEMANTIC_PRICING_CONFLICT_DIMENSIONS`` -- is still extracted, still
# compared, still written into the review and still shown to the operator; it
# simply no longer withholds a price on its own.
#
# The distinction is between an *explicit contradiction* and *silence*.  A
# CONFLICT anywhere in ``SEMANTIC_PRICING_CONFLICT_DIMENSIONS`` remains a hard
# stop, because two stated values that disagree are evidence of a different
# part.  What changes here is the treatment of an asserted-but-unresolved
# dimension: previously any of the thirty could hold the offer out of the
# cohort by being merely unconfirmed, which on measured data was the single
# largest source of "no price" after the unit fields.
SEMANTIC_PRICING_BLOCKING_DIMENSIONS = frozenset(
    {"part_type"} | SEMANTIC_PRICING_BASE_REQUIRED_DIMENSIONS
)

# A text-search hit with an explicit vehicle conflict is not safe to price:
# the same token can be a seller SKU, an incomplete cross, or a broad SEO
# title.  An authoritative Prom part-code grouping / verified OE evidence may
# bypass only the vehicle application axes; engine and year contradictions stay
# review-only because they can change the physical part.
SEMANTIC_VEHICLE_FITMENT_REVIEW_DIMENSIONS = frozenset(
    {"vehicle_make", "vehicle_model", "vehicle_generation_hint"}
)
SEMANTIC_FITMENT_REVIEW_DIMENSIONS = frozenset(
    {"engine", "year_interval"} | SEMANTIC_VEHICLE_FITMENT_REVIEW_DIMENSIONS
)


# Make this set explicit rather than treating every semantic comparison as an
# identity rejection.  Vehicle axes are handled as a manual-review boundary
# below, not as a hard rejection, because a verified OE can legitimately span
# multiple applications.
SEMANTIC_PRICING_CONFLICT_DIMENSIONS = frozenset(
    {
        "domain",
        "part_type",
        "part_subtype",
        "assembly_level",
        "condition",
        "serviceability",
        "side",
        "position",
        "vertical_position",
        "cv_joint_variant",
        "fuel_type",
        "body_variant",
        "climate_variant",
        "transmission_variant",
        "core_construction",
        "engine_cylinder_count",
        "power_rating",
        "connectors_pins",
        "technical_specs",
        "opening_temperature",
        "operating_pressure",
        "housing",
        "inlet_outlet",
        "ports",
        "mounting",
        "included_components",
        "engine",
        "package_quantity",
        "unit_basis",
    }
)


def apply_semantic_pricing_gate(
    verdict: CandidateVerdict,
    *,
    reference: ReferenceItem,
    candidate: Mapping[str, Any],
    authoritative_identity: bool = False,
    verified_oe_identity: bool = False,
    reference_payload: Mapping[str, Any] | None = None,
    require_pricing_completeness: bool = False,
    require_analogue_dimensions: bool = False,
) -> CandidateVerdict:
    """Demote unsafe search evidence to ``REFERENCE_ONLY``.

    In addition to explicit semantic contradictions, ordinary search hits are
    held when the candidate has no typed part family, the OE appears only in a
    free-form description, or the title is stuffed with multiple OE-like
    numbers.  These are review boundaries, not claims that the item is wrong.

    The full feature matrix is intentionally not stored in the selection row;
    only the extractor version and the conflicts that caused the demotion are
    persisted.  This keeps the row bounded while retaining deterministic
    replay evidence.
    """

    if verdict.status is not CandidateStatus.PRICING_EVIDENCE:
        return verdict
    matrix = build_semantic_feature_matrix(
        dict(
            reference_payload
            or {
                "name": reference.title,
                "category": reference.category or "",
                "brand": reference.brand or "",
            }
        ),
        candidate,
    )
    our_family = _feature_values(matrix, "our_product", "part_family")
    candidate_family = _feature_values(matrix, "candidate", "part_family")
    our_subtypes = _feature_values(matrix, "our_product", "part_subtype")
    candidate_subtypes = _feature_values(matrix, "candidate", "part_subtype")
    category_details = _category_gate_details(verdict)
    category_mode = str(category_details.get("mode") or "")
    semantic_markers = category_details.get("semantic_text_markers")
    automotive_domain_unconfirmed = (
        category_mode in {"CATEGORY_UNKNOWN", "CATEGORY_DOMAIN_UNCONFIRMED"}
        and isinstance(semantic_markers, Mapping)
        and not semantic_markers.get("automotive")
    )
    conflicts = tuple(
        dict(conflict)
        for conflict in matrix.get("hard_stop_conflicts", ())
        if str(conflict.get("dimension")) in SEMANTIC_PRICING_CONFLICT_DIMENSIONS
    )
    # Some dimensions are deliberately soft in the generic feature matrix
    # because a free-form marketplace label can be noisy (notably ports and
    # mounting).  Once the extractor has typed the part family, however, an
    # explicit contradiction in a category-required dimension is no longer a
    # harmless ambiguity: it is unsafe price evidence.  Keep the matrix's
    # broad behaviour unchanged for discovery, but make the pricing admission
    # boundary fail closed for the applicable category.
    category_specific_conflicts = tuple(
        category_required_semantic_conflicts(matrix)
    )
    existing_conflict_dimensions = {
        str(conflict.get("dimension")) for conflict in conflicts
    }
    category_specific_conflicts = tuple(
        conflict
        for conflict in category_specific_conflicts
        if str(conflict.get("dimension")) not in existing_conflict_dimensions
    )
    all_conflicts = tuple((*conflicts, *category_specific_conflicts))
    ambiguous_conflicts = tuple(ambiguous_taxonomy_conflicts(matrix))
    all_fitment_conflicts = tuple(
        {
            "dimension": str(dimension),
            "our_value": ", ".join(str(value) for value in comparison.get("our_values", [])),
            "candidate_value": ", ".join(
                str(value) for value in comparison.get("candidate_values", [])
            ),
            "explanation": (
                "Explicit fitment values conflict; the OE may be shared across "
                "applications, so keep the offer visible for manual review."
            ),
        }
        for dimension, comparison in matrix.get("comparisons", {}).items()
        if dimension in SEMANTIC_FITMENT_REVIEW_DIMENSIONS
        and isinstance(comparison, Mapping)
        and comparison.get("state") == "CONFLICT"
    )
    # A verified candidate OE can legitimately be shared by several vehicle
    # applications, so it may bypass only vehicle make/model/generation
    # review.  It must *not* be treated as a marketplace identity assertion:
    # an ordinary search card whose title is stuffed with several OE-like
    # numbers, or whose OE appears only in free-form description, remains
    # review-only.  ``authoritative_identity`` is reserved for the retained
    # Prom part-code acquisition lineage; ``verified_oe_identity`` is a
    # separate, weaker fact used only for fitment-axis handling.
    fitment_identity = authoritative_identity or verified_oe_identity
    fitment_conflicts = tuple(
        conflict
        for conflict in all_fitment_conflicts
        if not (
            fitment_identity
            and conflict["dimension"] in SEMANTIC_VEHICLE_FITMENT_REVIEW_DIMENSIONS
        )
    )
    fitment_conflicts_bypassed = tuple(
        conflict
        for conflict in all_fitment_conflicts
        if fitment_identity
        and conflict["dimension"] in SEMANTIC_VEHICLE_FITMENT_REVIEW_DIMENSIONS
    )
    ambiguous_pricing_dimensions = tuple(
        sorted(
            str(dimension)
            for dimension, comparison in matrix.get("comparisons", {}).items()
            # Deliberately the wide set, not the blocking one.  An ambiguous
            # source value is the listing contradicting itself about what it
            # sells ("left right"), which is a conflict wearing different
            # clothes -- not the silence that the blocking set narrows.
            if str(dimension) in SEMANTIC_PRICING_CONFLICT_DIMENSIONS
            and isinstance(comparison, Mapping)
            and comparison.get("source_values_ambiguous") is True
        )
    )
    subtype_unconfirmed = bool(
        our_family
        & candidate_family
        and our_subtypes
        and not candidate_subtypes
    )
    # A search hit is not an identity assertion.  Even an exact alphanumeric
    # article can be a seller SKU copied into a generic/SEO title.  When the
    # seed has a typed part family but the candidate has no typed family, keep
    # the card visible while refusing to let it affect a price.  The motors
    # adapter may opt in to an authoritative marketplace grouping; ordinary
    # search/discovery callers must not.
    # A typed family on only one side is not enough for automatic pricing.  The
    # symmetric form also catches a bare numeric seed whose candidate happens
    # to contain a plausible family; both are visible, but neither is silently
    # treated as a confirmed part identity.
    # A source-authoritative OE is enough to keep an untyped card visible in
    # discovery, but it is not enough to put that card into a deterministic
    # price cohort.  The persisted path supplies ``require_pricing_completeness``
    # and therefore requires both sides to expose a typed part family as well.
    # This prevents a seller/article page containing only the OE token from
    # becoming price evidence merely because the marketplace grouping was
    # authoritative.
    unconfirmed_identity = (
        (not our_family or not candidate_family)
        and (not authoritative_identity or require_pricing_completeness)
    )
    identity_evidence = _oem_identity_details(verdict).get("evidence")
    description_only_identity = (
        identity_evidence == "DESCRIPTION" and not authoritative_identity
    )
    stuffed_identity = "OEM_STUFFED" in verdict.flags and not authoritative_identity

    # ``hard_stop_conflicts`` proves that an explicit fact is contradictory;
    # it does not prove that all commercial facts needed for a unit-normalized
    # price are present.  Keep this second boundary separate so an UNKNOWN
    # never becomes a silent match.  Analogue-specific dimensions are required
    # only for verified cross/analogue paths; exact OE still requires the base
    # commercial fields and any facts explicitly asserted by the owned seed.
    required_pricing_dimensions: set[str] = set()
    # A candidate-only sellable assertion (for example ``lock_cylinder`` or
    # ``left``) is not proof that the owned seed has the same configuration.
    # This boundary applies even to discovery callers that do not request the
    # full package/unit completeness contract; otherwise the UI could label a
    # richer but unresolved candidate as price evidence before persistence.
    # Which asserted dimensions may withhold a price.  The persisted pricing
    # caller applies the owner's blocking set (2026-08-15): an unresolved
    # ``fuel_type`` or ``assembly_level`` is recorded and shown, but no longer
    # holds the offer out of a cohort on its own.  Discovery keeps the wider
    # contract, because there the question is whether to *label* a card as
    # price evidence in the UI, and an unresolved sellable fact should stop that
    # label before anything is persisted.
    asserted_blocking = (
        SEMANTIC_PRICING_BLOCKING_DIMENSIONS
        if require_pricing_completeness
        else SEMANTIC_PRICING_CONFLICT_DIMENSIONS
    )
    candidate_asserted_missing: set[str] = set()
    for key in ("seed_asserted_dimensions", "candidate_asserted_dimensions"):
        raw_asserted = matrix.get(key)
        if not isinstance(raw_asserted, (list, tuple, set, frozenset)):
            continue
        for raw_dimension in raw_asserted:
            dimension = str(raw_dimension).strip()
            if not dimension or dimension not in asserted_blocking:
                continue
            if not _comparison_is_match(matrix, dimension):
                candidate_asserted_missing.add(dimension)
    required_pricing_dimensions.update(candidate_asserted_missing)
    if require_pricing_completeness:
        required_pricing_dimensions.update(SEMANTIC_PRICING_BASE_REQUIRED_DIMENSIONS)
        if require_analogue_dimensions:
            raw_required = matrix.get("analogue_required_dimensions")
            if isinstance(raw_required, (list, tuple, set, frozenset)):
                required_pricing_dimensions.update(
                    str(value)
                    for value in raw_required
                    if str(value).strip()
                )
        # An explicit component claim on either side changes the sellable
        # configuration.  If the other side does not resolve it, require a
        # manual decision even for exact OE.
        included = matrix.get("comparisons", {}).get("included_components")
        if isinstance(included, Mapping) and included.get("state") == "UNKNOWN":
            our_included = matrix.get("our_product", {}).get("included_components")
            candidate_included = matrix.get("candidate", {}).get(
                "included_components"
            )
            if (
                isinstance(our_included, Mapping)
                and our_included.get("values")
            ) or (
                isinstance(candidate_included, Mapping)
                and candidate_included.get("values")
            ):
                required_pricing_dimensions.add("included_components")

    missing_pricing_dimensions = tuple(
        sorted(
            dimension
            for dimension in required_pricing_dimensions
            if not _comparison_is_match(matrix, dimension)
        )
    )
    if (
        not all_conflicts
        and not ambiguous_conflicts
        and not fitment_conflicts
        and not subtype_unconfirmed
        and not unconfirmed_identity
        and not description_only_identity
        and not stuffed_identity
        and not automotive_domain_unconfirmed
        and not ambiguous_pricing_dimensions
        and not missing_pricing_dimensions
    ):
        details = dict(verdict.details)
        details["semantic_gate"] = {
            "status": "PRICING_EVIDENCE",
            "reason": "OK",
            "gate_version": SEMANTIC_PRICING_GATE_VERSION,
            "extractor_version": matrix.get("extractor_version"),
            "hard_stop_conflicts": [],
            "category_specific_conflicts": [],
            "ambiguous_taxonomy_conflicts": [],
            "fitment_conflicts": [],
            "fitment_conflicts_bypassed": list(fitment_conflicts_bypassed),
            "ambiguous_pricing_dimensions": [],
            "subtype_evidence": {
                "required": sorted(our_subtypes),
                "candidate": sorted(candidate_subtypes),
            },
            "our_part_families": sorted(our_family),
            "candidate_part_families": sorted(candidate_family),
            "identity_authoritative": authoritative_identity,
            "identity_verified_by_oe": verified_oe_identity,
            "identity_evidence": identity_evidence,
            "required_pricing_dimensions": sorted(required_pricing_dimensions),
            "missing_pricing_dimensions": [],
        }
        return replace(
            verdict,
            details=MappingProxyType(details),
        )
    if conflicts:
        reason = "SEMANTIC_CONFLICT"
    elif ambiguous_conflicts:
        reason = "SEMANTIC_AMBIGUOUS_REVIEW"
    elif category_specific_conflicts:
        reason = "SEMANTIC_CATEGORY_CONFLICT"
    elif fitment_conflicts:
        reason = "SEMANTIC_FITMENT_CONFLICT_REVIEW"
    elif subtype_unconfirmed:
        reason = "SEMANTIC_SUBTYPE_UNCONFIRMED"
    elif automotive_domain_unconfirmed:
        reason = "CATEGORY_DOMAIN_UNCONFIRMED"
    elif unconfirmed_identity:
        reason = "SEMANTIC_UNCONFIRMED"
    elif ambiguous_pricing_dimensions:
        reason = "SEMANTIC_AMBIGUOUS_VALUES_REVIEW"
    elif missing_pricing_dimensions:
        reason = "SEMANTIC_PRICING_EVIDENCE_INCOMPLETE"
    elif description_only_identity:
        reason = "OE_DESCRIPTION_UNVERIFIED"
    else:
        reason = "OEM_STUFFED_REVIEW"
    details = dict(verdict.details)
    details["semantic_gate"] = {
        "status": "REFERENCE_ONLY",
        "reason": reason,
        "gate_version": SEMANTIC_PRICING_GATE_VERSION,
        "extractor_version": matrix.get("extractor_version"),
        "hard_stop_conflicts": list(all_conflicts),
        "category_specific_conflicts": list(category_specific_conflicts),
        "ambiguous_taxonomy_conflicts": list(ambiguous_conflicts),
        "fitment_conflicts": list(fitment_conflicts),
        "fitment_conflicts_bypassed": list(fitment_conflicts_bypassed),
        "ambiguous_pricing_dimensions": list(ambiguous_pricing_dimensions),
        "subtype_evidence": {
            "required": sorted(our_subtypes),
            "candidate": sorted(candidate_subtypes),
        },
        "our_part_families": sorted(our_family),
        "candidate_part_families": sorted(candidate_family),
        "identity_authoritative": authoritative_identity,
        "identity_verified_by_oe": verified_oe_identity,
        "identity_evidence": identity_evidence,
        "required_pricing_dimensions": sorted(required_pricing_dimensions),
        "missing_pricing_dimensions": list(missing_pricing_dimensions),
    }
    flag = (
        "SEMANTIC_HARD_STOP"
        if conflicts
        else "SEMANTIC_AMBIGUOUS_REVIEW"
        if ambiguous_conflicts
        else "SEMANTIC_CATEGORY_CONFLICT"
        if category_specific_conflicts
        else "SEMANTIC_FITMENT_CONFLICT_REVIEW"
        if fitment_conflicts
        else "SEMANTIC_SUBTYPE_UNCONFIRMED"
        if subtype_unconfirmed
        else "CATEGORY_DOMAIN_UNCONFIRMED"
        if automotive_domain_unconfirmed
        else "SEMANTIC_IDENTITY_UNCONFIRMED"
        if unconfirmed_identity
        else "SEMANTIC_AMBIGUOUS_VALUES_REVIEW"
        if ambiguous_pricing_dimensions
        else "SEMANTIC_PRICING_EVIDENCE_INCOMPLETE"
        if missing_pricing_dimensions
        else "OE_DESCRIPTION_UNVERIFIED"
        if description_only_identity
        else "OEM_STUFFED_REVIEW"
    )
    flags = tuple(dict.fromkeys((*verdict.flags, flag)))
    return replace(
        verdict,
        status=CandidateStatus.REFERENCE_ONLY,
        reason=reason,
        flags=flags,
        details=MappingProxyType(details),
    )


def _feature_values(
    matrix: Mapping[str, Any],
    side: str,
    feature: str,
) -> frozenset[str]:
    payload = matrix.get(side)
    if not isinstance(payload, Mapping):
        return frozenset()
    record = payload.get(feature)
    if not isinstance(record, Mapping):
        return frozenset()
    values = record.get("values")
    if not isinstance(values, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(str(value) for value in values if str(value).strip())


def _comparison_is_match(matrix: Mapping[str, Any], dimension: str) -> bool:
    comparisons = matrix.get("comparisons")
    if not isinstance(comparisons, Mapping):
        return False
    comparison = comparisons.get(dimension)
    return isinstance(comparison, Mapping) and comparison.get("state") == "MATCH"


def category_required_semantic_conflicts(
    matrix: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Return explicit conflicts in dimensions required by the part family.

    The low-level extractor intentionally leaves a few noisy dimensions out of
    its global hard-stop list.  This helper applies the category contract only
    when ``analogue_required_dimensions`` says the dimension is material for
    this family.  It never turns UNKNOWN into a conflict and never invents a
    value; missing evidence remains the separate manual-review path.
    """

    raw_required = matrix.get("analogue_required_dimensions")
    if not isinstance(raw_required, (list, tuple, set, frozenset)):
        return []
    comparisons = matrix.get("comparisons")
    if not isinstance(comparisons, Mapping):
        return []
    result: list[dict[str, str]] = []
    for raw_dimension in raw_required:
        dimension = str(raw_dimension).strip()
        if dimension not in SEMANTIC_PRICING_CONFLICT_DIMENSIONS:
            continue
        comparison = comparisons.get(dimension)
        if not isinstance(comparison, Mapping) or comparison.get("state") != "CONFLICT":
            continue
        our_values = comparison.get("our_values")
        candidate_values = comparison.get("candidate_values")
        result.append(
            {
                "dimension": dimension,
                "our_value": ", ".join(
                    str(value) for value in (our_values or ())
                ),
                "candidate_value": ", ".join(
                    str(value) for value in (candidate_values or ())
                ),
                "explanation": (
                    f"Explicit {dimension} conflict is material for this "
                    "category and blocks pricing admission."
                ),
            }
        )
    return result


def _category_gate_details(verdict: CandidateVerdict) -> Mapping[str, Any]:
    details = verdict.details
    if not isinstance(details, Mapping):
        return {}
    gates = details.get("gates")
    if not isinstance(gates, Mapping):
        return {}
    category = gates.get("category_domain")
    return category if isinstance(category, Mapping) else {}


def _oem_identity_details(verdict: CandidateVerdict) -> Mapping[str, Any]:
    details = verdict.details
    if not isinstance(details, Mapping):
        return {}
    gates = details.get("gates")
    if not isinstance(gates, Mapping):
        return {}
    identity = gates.get("oem_identity")
    return identity if isinstance(identity, Mapping) else {}


__all__ = [
    "SEMANTIC_PRICING_CONFLICT_DIMENSIONS",
    "SEMANTIC_VEHICLE_FITMENT_REVIEW_DIMENSIONS",
    "SEMANTIC_FITMENT_REVIEW_DIMENSIONS",
    "SEMANTIC_PRICING_GATE_VERSION",
    "SEMANTIC_PRICING_BASE_REQUIRED_DIMENSIONS",
    "SEMANTIC_PRICING_BLOCKING_DIMENSIONS",
    "semantic_gate_snapshot_is_current",
    "apply_semantic_pricing_gate",
    "category_required_semantic_conflicts",
]
