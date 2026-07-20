from sqlalchemy import CheckConstraint, UniqueConstraint

from marko.infrastructure.db.models import (
    MarketObservation,
    OfferProcessingOutcome,
    PricingRun,
    ScrapeTarget,
    TierCalibrationPairRecord,
)


def _check_sql(table) -> str:
    return "\n".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_verified_identity_columns_are_part_of_orm_contract() -> None:
    columns = MarketObservation.__table__.c

    for name in (
        "search_oe_norm",
        "extracted_oe_norms",
        "verified_matched_oe_norm",
        "comparison_identity_key",
        "oe_verification_status",
        "oe_evidence",
        "canonical_category_id",
        "comparability_hard_gate_result",
        "source_confidence_factors",
        "source_confidence_method_version",
        "calibration_exclusion_codes",
    ):
        assert name in columns
    assert columns.matched_oe_norm.nullable is True


def test_automatic_eligibility_constraint_is_fail_closed() -> None:
    sql = _check_sql(MarketObservation.__table__)

    assert "NOT automatic_eligible" in sql
    assert "VERIFIED_EXACT" in sql
    assert "comparability_hard_gate_result = 'PASS'" in sql
    assert "comparison_identity_key IS NOT NULL" in sql


def test_offer_outcome_has_one_terminal_partition_per_raw_element() -> None:
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in OfferProcessingOutcome.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert (
        "raw_market_capture_id",
        "pricing_run_item_id",
        "raw_offer_index",
    ) in unique_columns
    assert "market_observation_id IS NOT NULL" in _check_sql(
        OfferProcessingOutcome.__table__
    )


def test_query_and_calibration_lineage_columns_are_persisted() -> None:
    assert "input_kind" in ScrapeTarget.__table__.c
    assert "calibration_accounting" in PricingRun.__table__.c
    assert "identity_evidence" in TierCalibrationPairRecord.__table__.c
