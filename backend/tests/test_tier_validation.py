from metis.pricing import (
    ProductTier,
    TierValidationCase,
    evaluate_tier_validation,
)


def test_real_tier_validation_reports_accuracy_and_confusion_matrix() -> None:
    report = evaluate_tier_validation(
        [
            TierValidationCase("one", ProductTier.OES, ProductTier.OES),
            TierValidationCase("two", ProductTier.OEM, ProductTier.UNKNOWN),
        ],
        min_labeled=2,
        representative=True,
        approved_by="reviewer",
        domain_policy_approved=True,
    )

    assert report["validation_gate"] == "PASS"
    assert report["metrics"]["accuracy"] == "0.5"
    assert report["confusion_matrix"]["oes"]["oes"] == 1
    assert report["confusion_matrix"]["oem"]["unknown"] == 1
    assert report["production_activation"] == "BLOCKED_SEPARATE_DECISION"


def test_real_tier_validation_is_blocked_until_real_prerequisites_close() -> None:
    report = evaluate_tier_validation(
        [],
        representative=False,
        approved_by=None,
        domain_policy_approved=False,
    )

    assert report["validation_gate"] == "BLOCKED"
    assert report["metrics"]["accuracy"] is None
    assert report["activation_blockers"] == [
        "LABELED_CASES_BELOW_MINIMUM:0/200",
        "REPRESENTATIVE_REAL_SAMPLE_NOT_APPROVED",
        "GOLD_SET_REVIEWER_NOT_RECORDED",
        "BRAND_DOMAIN_POLICY_NOT_APPROVED",
    ]


def test_duplicate_source_listing_ids_fail_the_contract() -> None:
    report = evaluate_tier_validation(
        [
            TierValidationCase("same", ProductTier.OES, ProductTier.OES),
            TierValidationCase("same", ProductTier.OES, ProductTier.OES),
        ],
        min_labeled=2,
        representative=True,
        approved_by="reviewer",
        domain_policy_approved=True,
    )

    assert report["validation_gate"] == "FAIL"
    assert report["contract_errors"] == ["DUPLICATE_SOURCE_LISTING_IDS"]
    assert report["duplicate_source_listing_ids"] == ["same"]
