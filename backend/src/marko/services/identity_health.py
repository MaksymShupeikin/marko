"""Versioned operational alert policy for the verified-identity spine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any


IDENTITY_HEALTH_POLICY_VERSION = "identity-health-v1"


@dataclass(frozen=True, slots=True)
class IdentityHealthSnapshot:
    parsed_pages: int
    parser_schema_changed: int
    offer_internal_failures: int
    evidence_accounting_errors: int
    observations: int
    verified_observations: int
    source_confidence_p50: Decimal | None

    @property
    def schema_changed_rate(self) -> Decimal:
        if self.parsed_pages <= 0:
            return Decimal("0")
        return Decimal(self.parser_schema_changed) / Decimal(self.parsed_pages)

    @property
    def verified_oe_rate(self) -> Decimal | None:
        if self.observations <= 0:
            return None
        return Decimal(self.verified_observations) / Decimal(self.observations)

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "schema_changed_rate": format(self.schema_changed_rate, "f"),
            "verified_oe_rate": (
                format(self.verified_oe_rate, "f")
                if self.verified_oe_rate is not None
                else None
            ),
            "source_confidence_p50": (
                format(self.source_confidence_p50, "f")
                if self.source_confidence_p50 is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class IdentityHealthThresholds:
    parser_schema_changed_alert_count: int
    parser_schema_changed_critical_rate: Decimal
    offer_internal_failure_alert_count: int
    evidence_accounting_error_critical_count: int
    verified_oe_drop_warning_delta: Decimal
    source_confidence_p50_drop_warning_delta: Decimal
    policy_version: str = IDENTITY_HEALTH_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class IdentityHealthAlert:
    code: str
    severity: str
    current: str
    threshold: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def evaluate_identity_health(
    current: IdentityHealthSnapshot,
    thresholds: IdentityHealthThresholds,
    *,
    baseline: IdentityHealthSnapshot | None = None,
) -> tuple[IdentityHealthAlert, ...]:
    """Evaluate only bounded, non-sensitive aggregate signals."""

    alerts: list[IdentityHealthAlert] = []
    if current.parser_schema_changed > thresholds.parser_schema_changed_alert_count:
        alerts.append(
            IdentityHealthAlert(
                code="PARSER_SCHEMA_CHANGED_PRESENT",
                severity="ALERT",
                current=str(current.parser_schema_changed),
                threshold=str(thresholds.parser_schema_changed_alert_count),
            )
        )
    if current.schema_changed_rate > thresholds.parser_schema_changed_critical_rate:
        alerts.append(
            IdentityHealthAlert(
                code="PARSER_SCHEMA_CHANGED_RATE_HIGH",
                severity="CRITICAL",
                current=format(current.schema_changed_rate, "f"),
                threshold=format(
                    thresholds.parser_schema_changed_critical_rate,
                    "f",
                ),
            )
        )
    if current.offer_internal_failures > thresholds.offer_internal_failure_alert_count:
        alerts.append(
            IdentityHealthAlert(
                code="OFFER_INTERNAL_FAILURE_PRESENT",
                severity="ALERT",
                current=str(current.offer_internal_failures),
                threshold=str(thresholds.offer_internal_failure_alert_count),
            )
        )
    if (
        current.evidence_accounting_errors
        > thresholds.evidence_accounting_error_critical_count
    ):
        alerts.append(
            IdentityHealthAlert(
                code="EVIDENCE_ACCOUNTING_ERROR_PRESENT",
                severity="CRITICAL",
                current=str(current.evidence_accounting_errors),
                threshold=str(thresholds.evidence_accounting_error_critical_count),
            )
        )
    if baseline is not None:
        current_verified = current.verified_oe_rate
        baseline_verified = baseline.verified_oe_rate
        if (
            current_verified is not None
            and baseline_verified is not None
            and baseline_verified - current_verified
            > thresholds.verified_oe_drop_warning_delta
        ):
            alerts.append(
                IdentityHealthAlert(
                    code="VERIFIED_OE_RATE_DROP",
                    severity="WARNING",
                    current=format(current_verified, "f"),
                    threshold=format(
                        baseline_verified - thresholds.verified_oe_drop_warning_delta,
                        "f",
                    ),
                )
            )
        if (
            current.source_confidence_p50 is not None
            and baseline.source_confidence_p50 is not None
            and baseline.source_confidence_p50 - current.source_confidence_p50
            > thresholds.source_confidence_p50_drop_warning_delta
        ):
            alerts.append(
                IdentityHealthAlert(
                    code="SOURCE_CONFIDENCE_P50_DROP",
                    severity="WARNING",
                    current=format(current.source_confidence_p50, "f"),
                    threshold=format(
                        baseline.source_confidence_p50
                        - thresholds.source_confidence_p50_drop_warning_delta,
                        "f",
                    ),
                )
            )
    return tuple(alerts)


__all__ = [
    "IDENTITY_HEALTH_POLICY_VERSION",
    "IdentityHealthAlert",
    "IdentityHealthSnapshot",
    "IdentityHealthThresholds",
    "evaluate_identity_health",
]
