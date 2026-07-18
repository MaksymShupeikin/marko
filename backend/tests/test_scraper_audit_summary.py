from pathlib import Path

import pytest

from marko.governance.scraper_audit_summary import (
    ScraperAuditSummaryError,
    parse_scraper_audit_yaml,
)


MANIFEST = (
    Path(__file__).parents[2]
    / "docs"
    / "SCRAPER_ARCHITECTURE_AUDIT_SUMMARY_2026-07-17.yaml"
)


def test_repository_scraper_audit_manifest_is_strict_and_round_trips() -> None:
    payload = parse_scraper_audit_yaml(MANIFEST.read_text(encoding="utf-8"))
    assert payload["gates"]["audit_artifact"]["status"] == "PASS"
    assert payload["gates"]["production_eligibility"]["eligible"] is False


def test_duplicate_yaml_key_is_rejected() -> None:
    text = MANIFEST.read_text(encoding="utf-8").replace(
        "schema_version: scraper-architecture-audit.v2",
        "schema_version: scraper-architecture-audit.v2\nschema_version: duplicate",
        1,
    )
    with pytest.raises(ScraperAuditSummaryError, match="duplicate YAML key"):
        parse_scraper_audit_yaml(text)


def test_readiness_cannot_exceed_evidence_ceiling() -> None:
    text = MANIFEST.read_text(encoding="utf-8").replace(
        "weighted_score: 59.75",
        "weighted_score: 99.0",
        1,
    )
    with pytest.raises(ScraperAuditSummaryError, match="evidence ceiling"):
        parse_scraper_audit_yaml(text)


def test_production_eligibility_must_match_gate_status() -> None:
    text = MANIFEST.read_text(encoding="utf-8").replace(
        "eligible: false",
        "eligible: true",
        1,
    )
    with pytest.raises(ScraperAuditSummaryError, match="production eligible"):
        parse_scraper_audit_yaml(text)
