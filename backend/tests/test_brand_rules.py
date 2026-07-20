from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from metis.pricing import (
    BrandRuleContractError,
    ProductTier,
    load_approved_brand_rules,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_rules(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "brands.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _payload(*, domain_approved: bool, records: list[dict]) -> dict:
    return {
        "schema_version": "metis-brand-tiers-v1",
        "dataset_id": "test-prom-ua-rules-v1",
        "market": "prom.ua/UA",
        "domain_policy_approved": domain_approved,
        "approved_by": "domain-reviewer" if domain_approved else None,
        "approved_at": "2026-07-19T00:00:00Z" if domain_approved else None,
        "brands": records,
    }


def test_live_draft_loads_only_contractual_kemp_baseline() -> None:
    rules = load_approved_brand_rules(ROOT / "config" / "brands.yaml")

    assert rules.domain_policy_approved is False
    assert dict(rules.tiers) == {"KEMP": ProductTier.KEMP}
    assert dict(rules.confidence) == {"KEMP": Decimal("1.0000")}
    assert rules.source_sha256 is not None


def test_synthetic_e2e_rule_is_explicitly_isolated_and_loadable() -> None:
    rules = load_approved_brand_rules(
        ROOT / "src" / "marko" / "e2e" / "fixtures" / "brands.yaml"
    )

    assert rules.dataset_id == "prompt-15.015-synthetic-e2e-brands-v1"
    assert rules.approved_by == "E2E_FIXTURE_ONLY"
    assert rules.tiers["BOSCH"] is ProductTier.OES


def test_approved_policy_activates_only_individually_approved_rules(
    tmp_path: Path,
) -> None:
    path = _write_rules(
        tmp_path,
        _payload(
            domain_approved=True,
            records=[
                {
                    "brand": "Bosch",
                    "normalized": "BOSCH",
                    "tier": "oes",
                    "confidence": "0.9200",
                    "approved": True,
                    "evidence": ["https://prom.ua/p123-bosch.html"],
                    "approved_by": "domain-reviewer",
                    "approved_at": "2026-07-19T00:00:00Z",
                },
                {
                    "brand": "Vika",
                    "normalized": "VIKA",
                    "tier": "unknown",
                    "confidence": "0.0000",
                    "approved": False,
                },
            ],
        ),
    )

    rules = load_approved_brand_rules(path)

    assert dict(rules.tiers) == {
        "KEMP": ProductTier.KEMP,
        "BOSCH": ProductTier.OES,
    }
    assert rules.confidence["BOSCH"] == Decimal("0.9200")
    assert "VIKA" not in rules.tiers


def test_record_cannot_be_approved_under_unapproved_domain_policy(
    tmp_path: Path,
) -> None:
    path = _write_rules(
        tmp_path,
        _payload(
            domain_approved=False,
            records=[
                {
                    "brand": "Bosch",
                    "normalized": "BOSCH",
                    "tier": "oes",
                    "confidence": "0.9000",
                    "approved": True,
                }
            ],
        ),
    )

    with pytest.raises(BrandRuleContractError, match="domain policy is unapproved"):
        load_approved_brand_rules(path)


def test_normalized_brand_must_match_classifier_normalization(tmp_path: Path) -> None:
    path = _write_rules(
        tmp_path,
        _payload(
            domain_approved=False,
            records=[
                {
                    "brand": "Mercedes-Benz",
                    "normalized": "MERCEDES-BENZ",
                    "tier": "unknown",
                    "confidence": "0",
                    "approved": False,
                }
            ],
        ),
    )

    with pytest.raises(BrandRuleContractError, match="MERCEDESBENZ"):
        load_approved_brand_rules(path)


def test_approved_policy_requires_reviewer_and_timestamp(tmp_path: Path) -> None:
    payload = _payload(domain_approved=True, records=[])
    payload["approved_by"] = None
    path = _write_rules(tmp_path, payload)

    with pytest.raises(BrandRuleContractError, match="approved_by and approved_at"):
        load_approved_brand_rules(path)


@pytest.mark.parametrize("missing_field", ["evidence", "approved_by", "approved_at"])
def test_active_rule_requires_row_level_audit_metadata(
    tmp_path: Path, missing_field: str
) -> None:
    record = {
        "brand": "Bosch",
        "normalized": "BOSCH",
        "tier": "oes",
        "confidence": "0.9200",
        "approved": True,
        "evidence": ["https://prom.ua/p123-bosch.html"],
        "approved_by": "domain-reviewer",
        "approved_at": "2026-07-19",
    }
    record.pop(missing_field)
    path = _write_rules(
        tmp_path,
        _payload(domain_approved=True, records=[record]),
    )

    with pytest.raises(BrandRuleContractError, match=missing_field):
        load_approved_brand_rules(path)


@pytest.mark.parametrize(
    "evidence_url",
    [
        "http://prom.ua/p123-bosch.html",
        "https://prom.ua.evil.example/p123-bosch.html",
        "https://user:secret@prom.ua/p123-bosch.html",
        "not-a-url",
    ],
)
def test_active_prom_rule_requires_safe_prom_evidence_url(
    tmp_path: Path, evidence_url: str
) -> None:
    record = {
        "brand": "Bosch",
        "normalized": "BOSCH",
        "tier": "oes",
        "confidence": "0.9200",
        "approved": True,
        "evidence": [evidence_url],
        "approved_by": "domain-reviewer",
        "approved_at": "2026-07-19",
    }
    path = _write_rules(
        tmp_path,
        _payload(domain_approved=True, records=[record]),
    )

    with pytest.raises(BrandRuleContractError, match="HTTPS Prom URL"):
        load_approved_brand_rules(path)


def test_active_rule_requires_iso_approval_timestamp(tmp_path: Path) -> None:
    record = {
        "brand": "Bosch",
        "normalized": "BOSCH",
        "tier": "oes",
        "confidence": "0.9200",
        "approved": True,
        "evidence": ["https://prom.ua/p123-bosch.html"],
        "approved_by": "domain-reviewer",
        "approved_at": "sometime last week",
    }
    path = _write_rules(
        tmp_path,
        _payload(domain_approved=True, records=[record]),
    )

    with pytest.raises(BrandRuleContractError, match="ISO-8601"):
        load_approved_brand_rules(path)
