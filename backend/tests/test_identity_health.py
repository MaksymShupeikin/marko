from decimal import Decimal

from marko.services.identity_health import (
    IdentityHealthSnapshot,
    IdentityHealthThresholds,
    evaluate_identity_health,
)


def _snapshot(**overrides) -> IdentityHealthSnapshot:
    values = {
        "parsed_pages": 100,
        "parser_schema_changed": 0,
        "offer_internal_failures": 0,
        "evidence_accounting_errors": 0,
        "observations": 100,
        "verified_observations": 90,
        "source_confidence_p50": Decimal("0.90"),
    }
    values.update(overrides)
    return IdentityHealthSnapshot(**values)


def _thresholds() -> IdentityHealthThresholds:
    return IdentityHealthThresholds(
        parser_schema_changed_alert_count=0,
        parser_schema_changed_critical_rate=Decimal("0.01"),
        offer_internal_failure_alert_count=0,
        evidence_accounting_error_critical_count=0,
        verified_oe_drop_warning_delta=Decimal("0.20"),
        source_confidence_p50_drop_warning_delta=Decimal("0.15"),
    )


def test_identity_health_emits_hard_failure_alerts() -> None:
    alerts = evaluate_identity_health(
        _snapshot(
            parser_schema_changed=2,
            offer_internal_failures=1,
            evidence_accounting_errors=1,
        ),
        _thresholds(),
    )

    assert {alert.code for alert in alerts} == {
        "PARSER_SCHEMA_CHANGED_PRESENT",
        "PARSER_SCHEMA_CHANGED_RATE_HIGH",
        "OFFER_INTERNAL_FAILURE_PRESENT",
        "EVIDENCE_ACCOUNTING_ERROR_PRESENT",
    }


def test_identity_health_compares_verified_and_confidence_baselines() -> None:
    alerts = evaluate_identity_health(
        _snapshot(
            verified_observations=60,
            source_confidence_p50=Decimal("0.70"),
        ),
        _thresholds(),
        baseline=_snapshot(),
    )

    assert {alert.code for alert in alerts} == {
        "VERIFIED_OE_RATE_DROP",
        "SOURCE_CONFIDENCE_P50_DROP",
    }


def test_identity_health_has_no_alert_for_unmeasurable_empty_cohort() -> None:
    alerts = evaluate_identity_health(
        _snapshot(
            parsed_pages=0,
            observations=0,
            verified_observations=0,
            source_confidence_p50=None,
        ),
        _thresholds(),
        baseline=_snapshot(),
    )

    assert alerts == ()
