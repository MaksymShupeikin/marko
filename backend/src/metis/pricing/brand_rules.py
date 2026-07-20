"""Fail-closed loader for human-approved Ukrainian Prom brand tiers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

import yaml

from .tiering import normalize_brand
from .types import ProductTier


BRAND_RULES_SCHEMA_VERSION = "metis-brand-tiers-v1"
_NON_ACTIVATABLE_TIERS = frozenset(
    {ProductTier.UNKNOWN, ProductTier.USED, ProductTier.KEMP}
)


class BrandRuleContractError(ValueError):
    """Raised when a brand dictionary could enable an unauditable rule."""


@dataclass(frozen=True, slots=True)
class ApprovedBrandRules:
    """Only rules that are safe to pass into ``classify_tier``."""

    tiers: Mapping[str, ProductTier]
    confidence: Mapping[str, Decimal]
    dataset_id: str
    domain_policy_approved: bool
    approved_by: str | None
    approved_at: str | None
    source_path: str | None
    source_sha256: str | None


def _safe_base_rules() -> tuple[dict[str, ProductTier], dict[str, Decimal]]:
    # KEMP is not inferred from market reputation. Yuri explicitly requires it
    # to be a separate customer tier, so it is a contractual system invariant.
    return {"KEMP": ProductTier.KEMP}, {"KEMP": Decimal("1.0000")}


def empty_approved_brand_rules() -> ApprovedBrandRules:
    """Return the safe runtime baseline when no dictionary is configured."""

    tiers, confidence = _safe_base_rules()
    return ApprovedBrandRules(
        tiers=MappingProxyType(tiers),
        confidence=MappingProxyType(confidence),
        dataset_id="NO_BRAND_DICTIONARY_CONFIGURED",
        domain_policy_approved=False,
        approved_by=None,
        approved_at=None,
        source_path=None,
        source_sha256=None,
    )


def load_approved_brand_rules(path: str | Path | None) -> ApprovedBrandRules:
    """Load only approved rules and reject contradictory approval metadata.

    A draft file is a useful review artifact, but it must not silently affect
    pricing.  Therefore non-KEMP records become active only when both the
    document and each record are approved.  Every active non-KEMP record must
    also carry its own reviewer, approval time, and source evidence so a later
    operator can reconstruct why that market-specific tier was activated.
    """

    if path is None or not str(path).strip():
        return empty_approved_brand_rules()

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise BrandRuleContractError(
            f"Configured brand dictionary does not exist: {source_path}"
        )
    raw = source_path.read_bytes()
    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise BrandRuleContractError("Brand dictionary is not valid YAML") from exc
    if not isinstance(payload, Mapping):
        raise BrandRuleContractError("Brand dictionary root must be a mapping")
    if payload.get("schema_version") != BRAND_RULES_SCHEMA_VERSION:
        raise BrandRuleContractError(
            f"Unsupported brand dictionary schema: {payload.get('schema_version')!r}"
        )

    domain_policy_approved = payload.get("domain_policy_approved")
    if not isinstance(domain_policy_approved, bool):
        raise BrandRuleContractError("domain_policy_approved must be a boolean")
    approved_by = _optional_text(payload.get("approved_by"))
    approved_at = _optional_text(payload.get("approved_at"))
    if domain_policy_approved and not (approved_by and approved_at):
        raise BrandRuleContractError(
            "Approved brand policy requires approved_by and approved_at"
        )
    dataset_id = _required_text(payload.get("dataset_id"), field="dataset_id")
    market = _required_text(payload.get("market"), field="market")
    data_class = _optional_text(payload.get("data_class"))
    records = payload.get("brands")
    if not isinstance(records, list):
        raise BrandRuleContractError("brands must be a list")

    tiers, confidence = _safe_base_rules()
    seen: set[str] = set()
    for index, raw_record in enumerate(records):
        field_prefix = f"brands[{index}]"
        if not isinstance(raw_record, Mapping):
            raise BrandRuleContractError(f"{field_prefix} must be a mapping")
        brand_raw = _required_text(
            raw_record.get("brand"), field=f"{field_prefix}.brand"
        )
        brand_normalized = normalize_brand(brand_raw)
        if not brand_normalized:
            raise BrandRuleContractError(
                f"{field_prefix}.brand cannot be normalized by the classifier"
            )
        declared_normalized = _required_text(
            raw_record.get("normalized"), field=f"{field_prefix}.normalized"
        )
        if declared_normalized != brand_normalized:
            raise BrandRuleContractError(
                f"{field_prefix}.normalized must equal {brand_normalized!r}"
            )
        if brand_normalized in seen:
            raise BrandRuleContractError(
                f"Duplicate normalized brand rule: {brand_normalized}"
            )
        seen.add(brand_normalized)

        try:
            tier = ProductTier(
                _required_text(raw_record.get("tier"), field=f"{field_prefix}.tier")
            )
        except ValueError as exc:
            raise BrandRuleContractError(
                f"{field_prefix}.tier is not a supported product tier"
            ) from exc
        rule_approved = raw_record.get("approved")
        if not isinstance(rule_approved, bool):
            raise BrandRuleContractError(f"{field_prefix}.approved must be a boolean")
        rule_confidence = _confidence(
            raw_record.get("confidence"), field=f"{field_prefix}.confidence"
        )

        if brand_normalized == "KEMP":
            if tier is not ProductTier.KEMP or not rule_approved:
                raise BrandRuleContractError(
                    "KEMP must remain an approved separate KEMP tier"
                )
            tiers["KEMP"] = ProductTier.KEMP
            confidence["KEMP"] = Decimal("1.0000")
            continue
        if rule_approved and not domain_policy_approved:
            raise BrandRuleContractError(
                f"{field_prefix} is approved while domain policy is unapproved"
            )
        if not rule_approved:
            continue
        if tier in _NON_ACTIVATABLE_TIERS:
            raise BrandRuleContractError(
                f"{field_prefix}.tier cannot activate {tier.value!r} for a non-KEMP brand"
            )
        if rule_confidence <= 0:
            raise BrandRuleContractError(
                f"{field_prefix}.confidence must be positive for an approved rule"
            )
        _active_rule_audit_metadata(
            raw_record,
            field_prefix=field_prefix,
            market=market,
            data_class=data_class,
        )
        tiers[brand_normalized] = tier
        confidence[brand_normalized] = rule_confidence

    return ApprovedBrandRules(
        tiers=MappingProxyType(tiers),
        confidence=MappingProxyType(confidence),
        dataset_id=dataset_id,
        domain_policy_approved=domain_policy_approved,
        approved_by=approved_by,
        approved_at=approved_at,
        source_path=str(source_path.resolve()),
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _required_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BrandRuleContractError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise BrandRuleContractError("Approval metadata must be strings or null")
    normalized = value.strip()
    return normalized or None


def _confidence(value: Any, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BrandRuleContractError(f"{field} must be numeric") from exc
    if not result.is_finite() or not Decimal("0") <= result <= Decimal("1"):
        raise BrandRuleContractError(f"{field} must be between 0 and 1")
    return result.quantize(Decimal("0.0001"))


def _active_rule_audit_metadata(
    record: Mapping[str, Any],
    *,
    field_prefix: str,
    market: str,
    data_class: str | None,
) -> None:
    _required_text(record.get("approved_by"), field=f"{field_prefix}.approved_by")
    approved_at = _required_text(
        record.get("approved_at"), field=f"{field_prefix}.approved_at"
    )
    _validate_approval_timestamp(approved_at, field=f"{field_prefix}.approved_at")

    evidence = record.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise BrandRuleContractError(
            f"{field_prefix}.evidence must be a non-empty list"
        )
    evidence_items = [
        _required_text(value, field=f"{field_prefix}.evidence[{index}]")
        for index, value in enumerate(evidence)
    ]

    if market.casefold() == "prom.ua/ua":
        for index, evidence_url in enumerate(evidence_items):
            _validate_prom_evidence_url(
                evidence_url, field=f"{field_prefix}.evidence[{index}]"
            )
        return

    # Synthetic fixtures exercise deterministic plumbing, not market policy.
    # Give them an explicit, non-web evidence namespace so they cannot be
    # mistaken for real Prom review evidence.
    if data_class == "synthetic_e2e_fixture":
        for index, evidence_ref in enumerate(evidence_items):
            if not evidence_ref.startswith("fixture://"):
                raise BrandRuleContractError(
                    f"{field_prefix}.evidence[{index}] must use fixture:// for "
                    "synthetic_e2e_fixture data"
                )
        return

    raise BrandRuleContractError(
        f"{field_prefix} cannot activate a non-KEMP rule for unsupported market "
        f"{market!r}"
    )


def _validate_approval_timestamp(value: str, *, field: str) -> None:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise BrandRuleContractError(
            f"{field} must be an ISO-8601 date or timestamp"
        ) from exc


def _validate_prom_evidence_url(value: str, *, field: str) -> None:
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not (hostname == "prom.ua" or hostname.endswith(".prom.ua"))
        or not parsed.path
    ):
        raise BrandRuleContractError(
            f"{field} must be a credential-free HTTPS Prom URL"
        )


__all__ = [
    "ApprovedBrandRules",
    "BRAND_RULES_SCHEMA_VERSION",
    "BrandRuleContractError",
    "empty_approved_brand_rules",
    "load_approved_brand_rules",
]
