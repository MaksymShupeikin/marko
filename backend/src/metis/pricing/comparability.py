"""Fail-closed commercial-comparability policy and evidence adapters.

This module deliberately separates candidate retrieval confidence from the hard
facts required to place a price in an automatic cohort.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
import unicodedata
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from metis.identifiers import normalize_oem_identifier

from .types import (
    ComparisonEvidence,
    DimensionEvidence,
    EvidenceState,
    HardGateResult,
    SellerIdentityEvidence,
    SourceProvenance,
)


COMPARABILITY_CONTRACT_VERSION = "comparison-evidence-v3"
COMPARABILITY_POLICY_ID = "yuri-v1-comparability-v3"
CATEGORICAL_NORMALIZATION_VERSION = "comparability-categorical-v2-stem-phrases"
COMPARABILITY_DIMENSIONS = (
    "oe_reference",
    "part_type",
    "brand_manufacturer",
    "fitment",
    "vehicle_generation",
    "year_interval",
    "engine",
    "body_variant",
    "side",
    "position",
    "condition",
    "package_quantity",
    "currency_presence",
)
IDENTITY_DIMENSIONS = frozenset({"oe_reference"})
INFORMATIONAL_DIMENSIONS = frozenset({"brand_manufacturer"})
RECOGNIZED_SOURCE_TYPES = frozenset(
    {"prom", "prom_public", "persisted_replay", "official_feed", "test_fixture"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

#: Word stems for the closed side/position vocabularies, applied when the exact
#: alias table below cannot answer for a compound phrase.
#:
#: These deliberately mirror ``_SIDE_PATTERNS`` and ``_POSITION_PATTERNS`` in
#: ``marko.services.semantic_candidate_features``. They cannot import them:
#: ``metis`` does not depend on ``marko``, and inverting that is a far larger
#: change than one shared vocabulary is worth. ``tests`` sees both packages and
#: holds them in sync. The one intended difference is ``пер``: the extractor
#: matches ``пер.`` on raw text, while values reaching here have already had
#: their punctuation folded away.
_CATEGORICAL_STEMS: Mapping[str, tuple[tuple[re.Pattern[str], str], ...]] = (
    MappingProxyType(
        {
            "side": (
                (re.compile(r"\bлев\w*\b"), "left"),
                (re.compile(r"\bлів\w*\b"), "left"),
                (re.compile(r"\bleft\b"), "left"),
                (re.compile(r"\blh\b"), "left"),
                (re.compile(r"\bправ\w*\b"), "right"),
                (re.compile(r"\bright\b"), "right"),
                (re.compile(r"\brh\b"), "right"),
            ),
            "position": (
                (re.compile(r"\bпередн\w*\b"), "front"),
                (re.compile(r"\bпер\b"), "front"),
                (re.compile(r"\bfront\b"), "front"),
                (re.compile(r"\bзадн\w*\b"), "rear"),
                (re.compile(r"\brear\b"), "rear"),
            ),
        }
    )
)

_CATEGORICAL_ALIASES: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        "side": MappingProxyType(
            {
                "left": "left",
                "left hand": "left",
                "lh": "left",
                "лівий": "left",
                "ліва": "left",
                "ліве": "left",
                "левый": "left",
                "левая": "left",
                "левое": "left",
                "right": "right",
                "right hand": "right",
                "rh": "right",
                "правий": "right",
                "права": "right",
                "праве": "right",
                "правый": "right",
                "правая": "right",
                "правое": "right",
            }
        ),
        "position": MappingProxyType(
            {
                "front": "front",
                "front axle": "front",
                "передній": "front",
                "передня": "front",
                "переднє": "front",
                "передний": "front",
                "передняя": "front",
                "переднее": "front",
                "передня вісь": "front",
                "передняя ось": "front",
                "rear": "rear",
                "rear axle": "rear",
                "задній": "rear",
                "задня": "rear",
                "заднє": "rear",
                "задний": "rear",
                "задняя": "rear",
                "заднее": "rear",
                "задня вісь": "rear",
                "задняя ось": "rear",
            }
        ),
        "condition": MappingProxyType(
            {
                "new": "new",
                "новий": "new",
                "нова": "new",
                "нове": "new",
                "новый": "new",
                "новая": "new",
                "новое": "new",
                "used": "used",
                "б у": "used",
                "б/у": "used",
                "вживаний": "used",
                "вживана": "used",
                "вживане": "used",
                "refurbished": "refurbished",
                "відновлений": "refurbished",
                "восстановленный": "refurbished",
            }
        ),
        "body_variant": MappingProxyType(
            {
                "sedan": "sedan",
                "седан": "sedan",
                "hatchback": "hatchback",
                "хетчбек": "hatchback",
                "хэтчбек": "hatchback",
                "wagon": "wagon",
                "estate": "wagon",
                "station wagon": "wagon",
                "універсал": "wagon",
                "универсал": "wagon",
                "coupe": "coupe",
                "coupé": "coupe",
                "купе": "coupe",
                "cabriolet": "cabriolet",
                "convertible": "cabriolet",
                "кабріолет": "cabriolet",
                "кабриолет": "cabriolet",
                "van": "van",
                "фургон": "van",
                "minivan": "minivan",
                "мінівен": "minivan",
                "минивэн": "minivan",
                "pickup": "pickup",
                "pick up": "pickup",
                "пікап": "pickup",
                "пикап": "pickup",
                "bus": "bus",
                "автобус": "bus",
            }
        ),
    }
)
_CONSERVATIVE_TEXT_DIMENSIONS = frozenset({"fitment", "vehicle_generation", "engine"})


@dataclass(frozen=True, slots=True)
class CategoryComparabilityRule:
    policy_key: str
    hard_required: frozenset[str]
    conditional: frozenset[str]
    automatic_action_allowed: bool


_CATEGORY_RULES: Mapping[str, CategoryComparabilityRule] = MappingProxyType(
    {
        # Владельческое решение 2026-08-21: карточка продавца не обязана
        # повторять OE-номер, чтобы пройти жёсткие ворота сопоставимости —
        # идентичность по-прежнему доказывается verification/identity-evidence
        # и семантическим ревью, а КОНФЛИКТ OE-номера всё так же даёт REJECT
        # (oe_reference остаётся в IDENTITY_DIMENSIONS).
        "brake_pad": CategoryComparabilityRule(
            policy_key="brake_pad",
            hard_required=frozenset({"position", "condition", "package_quantity"}),
            conditional=frozenset(
                {
                    "oe_reference",
                    "part_type",
                    "fitment",
                    "vehicle_generation",
                    "year_interval",
                    "engine",
                    "side",
                }
            ),
            automatic_action_allowed=True,
        ),
        "shock_absorber": CategoryComparabilityRule(
            policy_key="shock_absorber",
            hard_required=frozenset({"position", "side", "condition"}),
            conditional=frozenset(
                {
                    "oe_reference",
                    "part_type",
                    "fitment",
                    "vehicle_generation",
                    "year_interval",
                    "engine",
                    "body_variant",
                }
            ),
            automatic_action_allowed=True,
        ),
        "generic_unknown": CategoryComparabilityRule(
            policy_key="generic_unknown",
            hard_required=frozenset({"condition"}),
            conditional=frozenset(
                set(COMPARABILITY_DIMENSIONS)
                - {
                    "condition",
                    "brand_manufacturer",
                }
            ),
            # "automatic" here means eligibility for the deterministic
            # recommendation calculation, never publishing a price to Prom.
            # In required mode the separate semantic-review gate still demands
            # an explicit part_type match before this policy is evaluated.
            automatic_action_allowed=True,
        ),
    }
)
_CATEGORY_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "brakes": "brake_pad",
        "brake": "brake_pad",
        "brakepad": "brake_pad",
        "brakepads": "brake_pad",
        "brake_pad": "brake_pad",
        "brake_pads": "brake_pad",
        "гальмівніколодки": "brake_pad",
        "тормозныеколодки": "brake_pad",
        "shockabsorber": "shock_absorber",
        "shockabsorbers": "shock_absorber",
        "shock_absorber": "shock_absorber",
        "амортизатор": "shock_absorber",
        "амортизатори": "shock_absorber",
    }
)


def category_comparability_rule(category: str | None) -> CategoryComparabilityRule:
    normalized = unicodedata.normalize("NFKC", category or "").casefold().strip()
    compact = "".join(character for character in normalized if character.isalnum())
    policy_key = _CATEGORY_ALIASES.get(normalized) or _CATEGORY_ALIASES.get(compact)
    return _CATEGORY_RULES.get(
        policy_key or "generic_unknown", _CATEGORY_RULES["generic_unknown"]
    )


def _policy_payload() -> dict[str, Any]:
    return {
        "policy_id": COMPARABILITY_POLICY_ID,
        "contract_version": COMPARABILITY_CONTRACT_VERSION,
        "required_dimensions": list(COMPARABILITY_DIMENSIONS),
        "approved_not_applicable": [],
        "identity_dimensions": sorted(IDENTITY_DIMENSIONS),
        "informational_dimensions": sorted(INFORMATIONAL_DIMENSIONS),
        "category_rules": {
            name: {
                "hard_required": sorted(rule.hard_required),
                "conditional": sorted(rule.conditional),
                "automatic_action_allowed": rule.automatic_action_allowed,
            }
            for name, rule in sorted(_CATEGORY_RULES.items())
        },
        "stable_seller_id_required": True,
        "raw_currency_required": True,
        "source_provenance_required": True,
        "unknown_semantics": "MANUAL_REVIEW",
        "conflict_semantics": "REJECT",
        "categorical_normalization_version": CATEGORICAL_NORMALIZATION_VERSION,
    }


COMPARABILITY_POLICY_HASH = hashlib.sha256(
    json.dumps(_policy_payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


@dataclass(frozen=True, slots=True)
class ComparabilityDecision:
    hard_gate_result: HardGateResult
    reason_codes: tuple[str, ...]
    failed_hard_gates: tuple[str, ...]
    unknown_hard_fields: tuple[str, ...]
    hard_gate_results: Mapping[str, int]

    @property
    def automatic_eligible(self) -> bool:
        return self.hard_gate_result == HardGateResult.PASS


_MISSING_REASON = {
    "oe_reference": "MANUAL_MISSING_OE_PROVENANCE",
    "part_type": "MANUAL_MISSING_PART_TYPE",
    "brand_manufacturer": "MANUAL_MISSING_BRAND",
    "fitment": "MANUAL_MISSING_FITMENT",
    "vehicle_generation": "MANUAL_MISSING_FITMENT",
    "year_interval": "MANUAL_MISSING_FITMENT",
    "engine": "MANUAL_MISSING_FITMENT",
    "body_variant": "MANUAL_MISSING_FITMENT",
    "side": "MANUAL_MISSING_SIDE_OR_POSITION",
    "position": "MANUAL_MISSING_SIDE_OR_POSITION",
    "condition": "MANUAL_MISSING_CONDITION",
    "package_quantity": "MANUAL_MISSING_PACKAGE_QUANTITY",
    "currency_presence": "MANUAL_MISSING_RAW_CURRENCY",
}


def evaluate_comparison_evidence(
    evidence: ComparisonEvidence | None,
    *,
    seller_id: str | None,
    currency_raw: str | None,
    currency_normalized: str | None,
    required_currency: str,
    category: str | None = None,
) -> ComparabilityDecision:
    """Evaluate every hard dimension; caller confidence is intentionally ignored."""

    gates: dict[str, int] = {}
    reasons: list[str] = []
    failed: list[str] = []
    unknown: list[str] = []
    conflict_dimensions: list[str] = []

    if evidence is None:
        return ComparabilityDecision(
            hard_gate_result=HardGateResult.MANUAL_REVIEW,
            reason_codes=("MANUAL_MISSING_COMPARABILITY_EVIDENCE",),
            failed_hard_gates=("comparison_evidence",),
            unknown_hard_fields=COMPARABILITY_DIMENSIONS,
            hard_gate_results=MappingProxyType({"comparison_evidence": 0}),
        )

    policy_valid = (
        evidence.policy_id == COMPARABILITY_POLICY_ID
        and evidence.policy_hash == COMPARABILITY_POLICY_HASH
    )
    gates["policy"] = int(policy_valid)
    if not policy_valid:
        failed.append("policy")
        reasons.append("MANUAL_POLICY_NOT_APPROVED")

    approved_na = set(evidence.approved_not_applicable)
    category_rule = category_comparability_rule(category)
    gates["category_policy_mapped"] = int(category_rule.automatic_action_allowed)
    if not category_rule.automatic_action_allowed:
        failed.append("category_policy")
        reasons.append("MANUAL_CATEGORY_POLICY_UNMAPPED")
    for name in COMPARABILITY_DIMENSIONS:
        dimension = evidence.dimensions.get(name)
        if dimension is None:
            state = EvidenceState.UNKNOWN
        else:
            try:
                state = EvidenceState(dimension.state)
            except ValueError:
                state = EvidenceState.UNKNOWN
        passed = state == EvidenceState.MATCH or (
            state == EvidenceState.NOT_APPLICABLE and name in approved_na
        )
        if name in INFORMATIONAL_DIMENSIONS:
            gates[f"dimension:{name}:informational"] = 1
            continue
        required = name in category_rule.hard_required
        gates[f"dimension:{name}"] = int(
            passed if required else state != EvidenceState.CONFLICT
        )
        if state == EvidenceState.CONFLICT:
            conflict_dimensions.append(name)
            failed.append(f"dimension:{name}")
        elif required and not passed:
            unknown.append(name)
            failed.append(f"dimension:{name}")
            reasons.append(_MISSING_REASON[name])

    stable_id = (evidence.seller_identity.stable_seller_id or "").strip()
    caller_id = (seller_id or "").strip()
    seller_verified = bool(
        evidence.seller_identity.verified
        and stable_id
        and evidence.seller_identity.identity_source
        and stable_id == caller_id
    )
    gates["stable_seller_identity"] = int(seller_verified)
    if not seller_verified:
        failed.append("stable_seller_identity")
        reasons.append("MANUAL_MISSING_STABLE_SELLER_ID")

    provenance = evidence.provenance
    raw_hash = (provenance.raw_evidence_sha256 or "").casefold().strip()
    provenance_verified = bool(
        provenance.verified
        and (provenance.source_type or "").strip() in RECOGNIZED_SOURCE_TYPES
        and (provenance.source_record_id or "").strip()
        and _SHA256_RE.fullmatch(raw_hash)
        and (provenance.parser_contract_version or "").strip()
        and provenance.schema_version == COMPARABILITY_CONTRACT_VERSION
    )
    gates["source_provenance"] = int(provenance_verified)
    if not provenance_verified:
        failed.append("source_provenance")
        reasons.append("MANUAL_MISSING_SOURCE_PROVENANCE")

    raw_currency = (currency_raw or "").strip()
    normalized_currency = (currency_normalized or "").strip().upper()
    currency_present = bool(raw_currency)
    currency_matches = bool(
        currency_present and normalized_currency == required_currency.strip().upper()
    )
    gates["raw_currency_present"] = int(currency_present)
    gates["currency_matches"] = int(currency_matches)
    if not currency_present:
        failed.append("raw_currency_present")
        reasons.append("MANUAL_MISSING_RAW_CURRENCY")
    elif not currency_matches:
        conflict_dimensions.append("currency_presence")
        failed.append("currency_matches")

    if conflict_dimensions:
        identity_conflict = any(
            item in IDENTITY_DIMENSIONS for item in conflict_dimensions
        )
        reasons.insert(
            0,
            "REJECTED_IDENTITY_CONFLICT"
            if identity_conflict
            else "REJECTED_COMPARABILITY_CONFLICT",
        )
        result = HardGateResult.REJECT
    elif failed:
        result = HardGateResult.MANUAL_REVIEW
    else:
        reasons.append("ELIGIBLE_VERIFIED")
        result = HardGateResult.PASS

    return ComparabilityDecision(
        hard_gate_result=result,
        reason_codes=tuple(dict.fromkeys(reasons)),
        failed_hard_gates=tuple(dict.fromkeys(failed)),
        unknown_hard_fields=tuple(dict.fromkeys(unknown)),
        hard_gate_results=MappingProxyType(dict(sorted(gates.items()))),
    )


def verified_comparison_evidence(
    *,
    stable_seller_id: str,
    source_record_id: str,
    raw_evidence_sha256: str | None = None,
    retrieval_kind: str = "fixture",
    source_type: str = "test_fixture",
    parser_contract_version: str = "fixture-parser-v1",
    dimension_overrides: Mapping[str, EvidenceState | DimensionEvidence] | None = None,
) -> ComparisonEvidence:
    """Build explicit verified evidence for deterministic fixtures and adapters."""

    dimensions: dict[str, DimensionEvidence] = {
        name: DimensionEvidence(
            state=EvidenceState.MATCH,
            normalized_value=f"verified:{name}",
            evidence_refs=(source_record_id,),
        )
        for name in COMPARABILITY_DIMENSIONS
    }
    for name, value in (dimension_overrides or {}).items():
        if name not in dimensions:
            raise ValueError(f"unknown comparability dimension: {name}")
        dimensions[name] = (
            value
            if isinstance(value, DimensionEvidence)
            else DimensionEvidence(state=EvidenceState(value))
        )
    evidence_hash = (
        raw_evidence_sha256
        or hashlib.sha256(source_record_id.encode("utf-8")).hexdigest()
    )
    return ComparisonEvidence(
        dimensions=MappingProxyType(dimensions),
        provenance=SourceProvenance(
            source_type=source_type,
            source_record_id=source_record_id,
            raw_evidence_sha256=evidence_hash,
            parser_contract_version=parser_contract_version,
            schema_version=COMPARABILITY_CONTRACT_VERSION,
            verified=True,
        ),
        seller_identity=SellerIdentityEvidence(
            stable_seller_id=stable_seller_id,
            identity_source=f"{source_type}:seller_id",
            verified=True,
        ),
        policy_id=COMPARABILITY_POLICY_ID,
        policy_hash=COMPARABILITY_POLICY_HASH,
        retrieval_kind=retrieval_kind,
        hard_gate_result=HardGateResult.PASS,
        reason_codes=("ELIGIBLE_VERIFIED",),
    )


def comparison_evidence_to_dict(
    evidence: ComparisonEvidence | None,
) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return {
        "dimensions": {
            name: {
                **asdict(value),
                "state": value.state.value,
                "evidence_refs": list(value.evidence_refs),
            }
            for name, value in sorted(evidence.dimensions.items())
        },
        "provenance": asdict(evidence.provenance),
        "seller_identity": asdict(evidence.seller_identity),
        "policy_id": evidence.policy_id,
        "policy_hash": evidence.policy_hash,
        "retrieval_kind": evidence.retrieval_kind,
        "seed_product_id": evidence.seed_product_id,
        "candidate_product_id": evidence.candidate_product_id,
        "approved_not_applicable": list(evidence.approved_not_applicable),
        "hard_gate_result": evidence.hard_gate_result.value,
        "reason_codes": list(evidence.reason_codes),
    }


def comparison_evidence_from_dict(
    payload: Mapping[str, Any] | None,
) -> ComparisonEvidence | None:
    if payload is None:
        return None
    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, Mapping):
        raise ValueError("comparison evidence dimensions must be an object")
    dimensions: dict[str, DimensionEvidence] = {}
    for name, raw in raw_dimensions.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"comparison evidence dimension {name} must be an object")
        dimensions[str(name)] = DimensionEvidence(
            state=EvidenceState(str(raw.get("state", "UNKNOWN"))),
            raw_value=_optional_string(raw.get("raw_value")),
            normalized_value=_optional_string(raw.get("normalized_value")),
            evidence_refs=tuple(str(item) for item in raw.get("evidence_refs", ())),
            reason_code=_optional_string(raw.get("reason_code")),
        )
    provenance_raw = payload.get("provenance")
    seller_raw = payload.get("seller_identity")
    if not isinstance(provenance_raw, Mapping) or not isinstance(seller_raw, Mapping):
        raise ValueError(
            "comparison evidence provenance and seller_identity are required"
        )
    return ComparisonEvidence(
        dimensions=MappingProxyType(dimensions),
        provenance=SourceProvenance(
            source_type=_optional_string(provenance_raw.get("source_type")),
            source_record_id=_optional_string(provenance_raw.get("source_record_id")),
            raw_evidence_sha256=_optional_string(
                provenance_raw.get("raw_evidence_sha256")
            ),
            parser_contract_version=_optional_string(
                provenance_raw.get("parser_contract_version")
            ),
            schema_version=str(
                provenance_raw.get("schema_version", COMPARABILITY_CONTRACT_VERSION)
            ),
            verified=bool(provenance_raw.get("verified", False)),
        ),
        seller_identity=SellerIdentityEvidence(
            stable_seller_id=_optional_string(seller_raw.get("stable_seller_id")),
            identity_source=_optional_string(seller_raw.get("identity_source")),
            verified=bool(seller_raw.get("verified", False)),
        ),
        policy_id=str(payload.get("policy_id", "")),
        policy_hash=str(payload.get("policy_hash", "")),
        retrieval_kind=str(payload.get("retrieval_kind", "unknown")),
        seed_product_id=_optional_string(payload.get("seed_product_id")),
        candidate_product_id=_optional_string(payload.get("candidate_product_id")),
        approved_not_applicable=tuple(
            str(item) for item in payload.get("approved_not_applicable", ())
        ),
        hard_gate_result=HardGateResult(
            str(payload.get("hard_gate_result", HardGateResult.MANUAL_REVIEW.value))
        ),
        reason_codes=tuple(str(item) for item in payload.get("reason_codes", ())),
    )


def bind_persisted_provenance(
    evidence: ComparisonEvidence | None,
    *,
    stable_seller_id: str | None,
    source_type: str,
    source_record_id: str,
    raw_evidence_sha256: str,
    parser_contract_version: str,
    currency_raw: str | None,
    currency_normalized: str | None,
    required_currency: str,
    category: str | None = None,
    condition_state: str | None = None,
) -> ComparisonEvidence:
    """Bind located immutable-record provenance without upgrading unknown facts."""

    if evidence is None:
        dimensions = {
            name: DimensionEvidence(state=EvidenceState.UNKNOWN)
            for name in COMPARABILITY_DIMENSIONS
        }
    else:
        dimensions = dict(evidence.dimensions)
    if currency_raw and currency_normalized:
        dimensions["currency_presence"] = DimensionEvidence(
            state=(
                EvidenceState.MATCH
                if currency_normalized.strip().upper()
                == required_currency.strip().upper()
                else EvidenceState.CONFLICT
            ),
            raw_value=currency_raw,
            normalized_value=currency_normalized,
            evidence_refs=(source_record_id,),
        )
    if condition_state is not None:
        normalized_condition = condition_state.strip().upper()
        dimensions["condition"] = DimensionEvidence(
            state=(
                EvidenceState.MATCH
                if normalized_condition == "NEW"
                else EvidenceState.CONFLICT
                if normalized_condition in {"USED_OR_REFURBISHED", "CONFLICT"}
                else EvidenceState.UNKNOWN
            ),
            raw_value=condition_state,
            normalized_value=normalized_condition,
            evidence_refs=(source_record_id,),
        )
    normalized_source_type = _optional_string(source_type)
    normalized_source_record_id = _optional_string(source_record_id)
    normalized_parser_version = _optional_string(parser_contract_version)
    normalized_raw_hash = _optional_string(raw_evidence_sha256)
    provenance_verified = bool(
        normalized_source_type
        and normalized_source_record_id
        and normalized_parser_version
        and normalized_raw_hash
        and re.fullmatch(r"[0-9a-fA-F]{64}", normalized_raw_hash)
    )
    initial = ComparisonEvidence(
        dimensions=MappingProxyType(dimensions),
        provenance=SourceProvenance(
            source_type=normalized_source_type,
            source_record_id=normalized_source_record_id,
            raw_evidence_sha256=(
                normalized_raw_hash.casefold() if normalized_raw_hash else None
            ),
            parser_contract_version=normalized_parser_version,
            schema_version=COMPARABILITY_CONTRACT_VERSION,
            verified=provenance_verified,
        ),
        seller_identity=SellerIdentityEvidence(
            stable_seller_id=stable_seller_id,
            identity_source=(f"{source_type}:seller_id" if stable_seller_id else None),
            verified=bool(stable_seller_id),
        ),
        policy_id=COMPARABILITY_POLICY_ID,
        policy_hash=COMPARABILITY_POLICY_HASH,
        retrieval_kind=evidence.retrieval_kind if evidence else "unknown",
        seed_product_id=evidence.seed_product_id if evidence else None,
        candidate_product_id=evidence.candidate_product_id if evidence else None,
        approved_not_applicable=(evidence.approved_not_applicable if evidence else ()),
    )
    decision = evaluate_comparison_evidence(
        initial,
        seller_id=stable_seller_id,
        currency_raw=currency_raw,
        currency_normalized=currency_normalized,
        required_currency=required_currency,
        category=category,
    )
    return replace(
        initial,
        hard_gate_result=decision.hard_gate_result,
        reason_codes=decision.reason_codes,
    )


def normalize_oe(value: str | None) -> str | None:
    """Versioned exact OE normalization using the shared identifier contract."""

    if value is None:
        return None
    normalized = normalize_oem_identifier(value)
    return normalized if len(normalized) >= 3 else None


def categorical_dimension(
    left: str | None,
    right: str | None,
    *,
    evidence_refs: Iterable[str] = (),
) -> DimensionEvidence:
    a = _optional_string(left)
    b = _optional_string(right)
    if a is None or b is None:
        state = EvidenceState.UNKNOWN
    elif a.casefold() == b.casefold():
        state = EvidenceState.MATCH
    else:
        state = EvidenceState.CONFLICT
    return DimensionEvidence(
        state=state,
        raw_value=b,
        normalized_value=b.casefold() if b is not None else None,
        evidence_refs=tuple(evidence_refs),
    )


def normalized_categorical_dimension(
    dimension: str,
    left: str | None,
    right: str | None,
    *,
    evidence_refs: Iterable[str] = (),
) -> DimensionEvidence:
    """Compare structured category values without converting wording drift to fact.

    Exact normalized text remains supporting evidence.  For mutually exclusive
    closed vocabularies (side, axle position, condition and body type), two
    recognized different canonical values are a real conflict.  Opaque
    fitment/generation/engine strings are not: differing wording is UNKNOWN
    unless a separate deterministic parser proves the contradiction.
    """

    raw_left = _optional_string(left)
    raw_right = _optional_string(right)
    if raw_left is None or raw_right is None:
        state = EvidenceState.UNKNOWN
        normalized_right = None if raw_right is None else _comparison_text(raw_right)
    else:
        folded_left = _comparison_text(raw_left)
        folded_right = _comparison_text(raw_right)
        normalized_right = folded_right
        if folded_left == folded_right:
            state = EvidenceState.MATCH
        else:
            aliases = _CATEGORICAL_ALIASES.get(dimension)
            canonical_left = _canonical_categorical_value(dimension, folded_left)
            canonical_right = _canonical_categorical_value(dimension, folded_right)
            if canonical_left is not None and canonical_right is not None:
                normalized_right = canonical_right
                state = (
                    EvidenceState.MATCH
                    if canonical_left == canonical_right
                    else EvidenceState.CONFLICT
                )
            elif dimension in _CONSERVATIVE_TEXT_DIMENSIONS or aliases is not None:
                state = EvidenceState.UNKNOWN
            else:
                state = EvidenceState.CONFLICT
    return DimensionEvidence(
        state=state,
        raw_value=raw_right,
        normalized_value=normalized_right,
        evidence_refs=tuple(evidence_refs),
        reason_code=f"{CATEGORICAL_NORMALIZATION_VERSION}:{dimension}",
    )


def _canonical_categorical_value(dimension: str, folded: str) -> str | None:
    """Read a closed-vocabulary value out of a phrase, or admit it cannot.

    Prom characteristics carry ``Передній лівий`` as one string. The exact
    alias table could only answer for a value that was already a single token,
    so a compound phrase came back as missing evidence and held the candidate
    for review. Word stems answer it, and a phrase naming two values of the
    same dimension stays unknown rather than becoming a guess about which was
    meant.
    """

    aliases = _CATEGORICAL_ALIASES.get(dimension)
    if aliases is not None:
        exact = aliases.get(folded)
        if exact is not None:
            return exact
    stems = _CATEGORICAL_STEMS.get(dimension)
    if stems is None:
        return None
    found = {
        canonical for pattern, canonical in stems if pattern.search(folded)
    }
    return found.pop() if len(found) == 1 else None


def _comparison_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[_-]+", " ", normalized)
    normalized = re.sub(r"[^\w\s/]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "COMPARABILITY_CONTRACT_VERSION",
    "COMPARABILITY_DIMENSIONS",
    "COMPARABILITY_POLICY_HASH",
    "COMPARABILITY_POLICY_ID",
    "ComparabilityDecision",
    "CategoryComparabilityRule",
    "CATEGORICAL_NORMALIZATION_VERSION",
    "categorical_dimension",
    "normalized_categorical_dimension",
    "bind_persisted_provenance",
    "comparison_evidence_from_dict",
    "comparison_evidence_to_dict",
    "evaluate_comparison_evidence",
    "category_comparability_rule",
    "normalize_oe",
    "verified_comparison_evidence",
]
