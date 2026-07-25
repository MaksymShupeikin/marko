from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from marko.services.catalog_number_nature import (
    CatalogNumberNature,
    CatalogNumberNatureContractError,
    CatalogNumberRecord,
    classify_catalog_number,
    load_catalog_number_nature_policy,
    load_live_independent_exact_counts,
)
from marko.services.xlsx_catalog import normalize_identifier


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/catalog_number_nature.yaml"
FIXTURE_PATH = ROOT / "tests/fixtures/catalog_number_nature_real_rows_v1.json"
LIVE_FIXTURE_PATH = (
    ROOT / "tests/fixtures/catalog_number_nature_real_offers_v1.csv"
)


def test_real_catalog_fixture_is_classified_fail_closed() -> None:
    policy = load_catalog_number_nature_policy(POLICY_PATH)
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert payload["source_catalog_sha256"] == policy.source_catalog_sha256
    for raw_record in payload["records"]:
        expected_nature = CatalogNumberNature(raw_record.pop("expected_nature"))
        expected_reason = raw_record.pop("expected_reason")
        live_count = int(raw_record.pop("live_independent_exact_count", 0))
        record = CatalogNumberRecord(**raw_record)

        result = classify_catalog_number(
            record,
            policy=policy,
            live_independent_exact_counts=(
                {normalize_identifier(record.oe_raw): live_count}
                if live_count
                else {}
            ),
        )

        assert result.nature is expected_nature, record.oe_raw
        assert result.reason_code == expected_reason, record.oe_raw


def test_live_cross_check_excludes_owned_kemp_used_and_non_exact_rows() -> None:
    policy = load_catalog_number_nature_policy(POLICY_PATH)

    counts = load_live_independent_exact_counts(
        LIVE_FIXTURE_PATH,
        owned_seller_ids=policy.owned_seller_ids,
    )

    assert dict(counts) == {"96943762": 2, "314216": 1}
    assert "77641041" not in counts
    assert "863130" not in counts


def test_direct_independent_market_evidence_outranks_internal_pattern() -> None:
    policy = load_catalog_number_nature_policy(POLICY_PATH)
    record = CatalogNumberRecord(
        source_row=1,
        sku="real-fixture-probe",
        oe_raw="77641041",
        title="Амортизатор Ford Mondeo",
        search_queries="77641041",
    )

    result = classify_catalog_number(
        record,
        policy=policy,
        live_independent_exact_counts={"77641041": 1},
    )

    assert result.nature is CatalogNumberNature.MANUFACTURER_OE
    assert result.reason_code == "LIVE_INDEPENDENT_EXACT"


def test_pattern_without_required_manufacturer_context_stays_unknown() -> None:
    policy = load_catalog_number_nature_policy(POLICY_PATH)
    record = CatalogNumberRecord(
        source_row=1,
        sku="real-fixture-probe",
        oe_raw="4A0941699",
        title="Фара без подтверждённой марки",
    )

    result = classify_catalog_number(record, policy=policy)

    assert result.nature is CatalogNumberNature.UNKNOWN
    assert result.reason_code == "NO_SUFFICIENT_EVIDENCE"


def test_policy_rejects_unanchored_identifier_regex(tmp_path: Path) -> None:
    payload = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    payload["internal_number_patterns"][0]["regex"] = "776[0-9]+"
    path = tmp_path / "catalog_number_nature.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(
        CatalogNumberNatureContractError,
        match="explicitly anchored",
    ):
        load_catalog_number_nature_policy(path)


def test_policy_rejects_invalid_source_digest(tmp_path: Path) -> None:
    payload = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    payload["source_catalog_sha256"] = "not-a-digest"
    path = tmp_path / "catalog_number_nature.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(CatalogNumberNatureContractError, match="SHA-256"):
        load_catalog_number_nature_policy(path)
