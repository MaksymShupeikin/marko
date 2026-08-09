from __future__ import annotations

import pytest

from marko.services.market_funnel import (
    FunnelItemInput,
    MarketObservationInput,
    MarketFunnelError,
    RecommendationInput,
    build_blinded_review_batch,
    build_market_funnel_report,
    market_review_source_rows,
    public_keys_from_start_snapshot,
    score_reviewed_market_pairs,
    verify_canary_labels,
)


def _snapshot(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "identity_status": "OE_CONFIRMED",
        "oe_norm": "1086282",
        "mpn_norm": "TH652688J",
        "part_numbers_norm": ["776416", "TH6526.88J"],
        "confirmed_identity_links": [],
    }
    value.update(overrides)
    return value


def test_frozen_public_keys_never_emit_internal_code_and_preserve_key_roles() -> None:
    keys = public_keys_from_start_snapshot(_snapshot())

    assert [key.number for key in keys] == ["1086282", "TH652688J"]
    assert [key.role for key in keys] == ["OE", "PUBLIC_MPN"]
    assert [key.pricing_primary for key in keys] == [True, False]
    assert all(not key.number.startswith("776") for key in keys)


def test_five_stage_funnel_is_monotonic_and_excludes_owned_echoes() -> None:
    complete = FunnelItemInput(
        catalog_item_id="complete",
        source_row=2,
        start_snapshot=_snapshot(),
        scrape_target_status="succeeded",
        scrape_target_reason_codes=(),
        run_item_status="calculated",
        run_item_error=None,
        observations=(
            MarketObservationInput(
                observation_id="owned",
                via_oe_number="1086282",
                is_owned=True,
                cohort_role="OWNED_STORE",
                oe_verification_status="VERIFIED_EXACT",
                comparability_hard_gate_result="PASS",
                automatic_eligible=False,
                reason_codes=(),
            ),
            MarketObservationInput(
                observation_id="market",
                via_oe_number="1086282",
                is_owned=False,
                cohort_role="TARGET_MARKET",
                oe_verification_status="VERIFIED_EXACT",
                comparability_hard_gate_result="PASS",
                automatic_eligible=True,
                reason_codes=(),
            ),
        ),
        recommendations=(
            RecommendationInput(
                action="HOLD",
                action_gates_passed=True,
                recommended_price="100.00",
                reason_codes=(),
                evidence_observation_ids=("market",),
            ),
        ),
    )
    no_candidates = FunnelItemInput(
        catalog_item_id="no-candidates",
        source_row=3,
        start_snapshot=_snapshot(oe_norm="93818439"),
        scrape_target_status="succeeded",
        scrape_target_reason_codes=("EMPTY_SEARCH_RESULT",),
        run_item_status="classified",
        run_item_error=None,
        observations=(),
        recommendations=(),
    )
    no_key = FunnelItemInput(
        catalog_item_id="no-key",
        source_row=4,
        start_snapshot=_snapshot(
            oe_norm="776416", mpn_norm="", part_numbers_norm=["776416"]
        ),
        scrape_target_status="terminal_failure",
        scrape_target_reason_codes=("customer_identity_missing",),
        run_item_status="failed",
        run_item_error="Customer supplied no confirmed vehicle OE",
        observations=(),
        recommendations=(),
    )

    report = build_market_funnel_report((complete, no_candidates, no_key))

    assert report.population == 3
    assert report.positions_with_public_key == 2
    assert report.positions_with_external_candidate == 1
    assert report.positions_with_candidate_surviving_comparison == 1
    assert report.positions_with_price_recommendation == 1
    assert report.owned_echo_observations == 1
    assert report.stage_counts_are_monotonic is True
    assert report.rows[0].external_candidate_count == 1
    assert report.rows[1].drop_stage == "MARKET_CANDIDATE"
    assert "EMPTY_SEARCH_RESULT" in report.rows[1].reason_codes
    assert report.rows[2].drop_stage == "PUBLIC_KEY"
    assert report.as_dict()["price_showing_ready"] is False


def test_retrieval_only_hit_is_reported_but_cannot_bypass_identity_comparison() -> None:
    item = FunnelItemInput(
        catalog_item_id="retrieval-only",
        source_row=5,
        start_snapshot=_snapshot(),
        scrape_target_status="succeeded",
        scrape_target_reason_codes=(),
        run_item_status="manual_review",
        run_item_error=None,
        observations=(
            MarketObservationInput(
                observation_id="candidate",
                via_oe_number="TH652688J",
                is_owned=False,
                cohort_role="MANUAL_REVIEW",
                oe_verification_status="UNKNOWN",
                comparability_hard_gate_result="MANUAL_REVIEW",
                automatic_eligible=False,
                reason_codes=("OE_AUTOMATIC_IDENTITY_EVIDENCE_INSUFFICIENT",),
            ),
        ),
        recommendations=(
            RecommendationInput(
                action="INSUFFICIENT_DATA",
                action_gates_passed=False,
                recommended_price=None,
                reason_codes=("NO_VERIFIED_COMPETITORS",),
            ),
        ),
    )

    row = build_market_funnel_report((item,)).rows[0]

    assert row.external_candidate_count == 1
    assert row.retrieval_only_candidate_count == 1
    assert row.surviving_candidate_count == 0
    assert row.has_price_recommendation is False
    assert row.drop_stage == "COMPARISON"


def test_price_recommendation_cannot_use_retrieval_only_unverified_evidence() -> None:
    item = FunnelItemInput(
        catalog_item_id="unsafe-recommendation",
        source_row=7,
        start_snapshot=_snapshot(),
        scrape_target_status="succeeded",
        scrape_target_reason_codes=(),
        run_item_status="calculated",
        run_item_error=None,
        observations=(
            MarketObservationInput(
                observation_id="retrieval-only-observation",
                via_oe_number="TH652688J",
                is_owned=False,
                cohort_role="TARGET_MARKET",
                oe_verification_status="UNKNOWN",
                comparability_hard_gate_result="MANUAL_REVIEW",
                automatic_eligible=False,
                reason_codes=(),
            ),
        ),
        recommendations=(
            RecommendationInput(
                action="HOLD",
                action_gates_passed=True,
                recommended_price="100.00",
                reason_codes=(),
                evidence_observation_ids=("retrieval-only-observation",),
            ),
        ),
    )

    report = build_market_funnel_report((item,))

    assert report.positions_with_price_recommendation == 0
    assert report.unsafe_price_recommendations == 1
    assert report.rows[0].has_price_recommendation is False
    assert report.rows[0].unsafe_price_recommendation_count == 1


def test_retrieval_only_key_cannot_price_even_if_persisted_flags_are_wrong() -> None:
    item = FunnelItemInput(
        catalog_item_id="retrieval-only-fail-closed",
        source_row=8,
        start_snapshot=_snapshot(),
        scrape_target_status="succeeded",
        scrape_target_reason_codes=(),
        run_item_status="calculated",
        run_item_error=None,
        observations=(
            MarketObservationInput(
                observation_id="badly-admitted-retrieval-hit",
                via_oe_number="TH652688J",
                is_owned=False,
                cohort_role="TARGET_MARKET",
                oe_verification_status="VERIFIED_EXACT",
                comparability_hard_gate_result="PASS",
                automatic_eligible=True,
                reason_codes=(),
            ),
        ),
        recommendations=(
            RecommendationInput(
                action="HOLD",
                action_gates_passed=True,
                recommended_price="100.00",
                reason_codes=(),
                evidence_observation_ids=("badly-admitted-retrieval-hit",),
            ),
        ),
    )

    report = build_market_funnel_report((item,))

    assert report.rows[0].surviving_candidate_count == 1
    assert report.rows[0].automatic_candidate_count == 0
    assert report.positions_with_price_recommendation == 0
    assert report.unsafe_price_recommendations == 1


def test_observation_without_persisted_ownership_classification_fails_closed() -> None:
    item = FunnelItemInput(
        catalog_item_id="ownership-unclassified",
        source_row=6,
        start_snapshot=_snapshot(),
        scrape_target_status="succeeded",
        scrape_target_reason_codes=(),
        run_item_status="classified",
        run_item_error=None,
        observations=(
            MarketObservationInput(
                observation_id="unknown-owner",
                via_oe_number="1086282",
                is_owned=None,
                cohort_role="MANUAL_REVIEW",
                oe_verification_status="VERIFIED_EXACT",
                comparability_hard_gate_result="PASS",
                automatic_eligible=False,
                reason_codes=(),
            ),
        ),
        recommendations=(),
    )

    report = build_market_funnel_report((item,))

    assert report.positions_with_external_candidate == 0
    assert report.ownership_unclassified_observations == 1
    assert report.rows[0].external_candidate_count == 0
    assert report.rows[0].ownership_unclassified_count == 1
    assert "OWNERSHIP_UNCLASSIFIED" in report.rows[0].reason_codes


def test_canaries_are_blinded_and_the_answer_key_stays_separate() -> None:
    market_rows = tuple(
        {
            "our_oe": f"OE-{index}",
            "our_title": f"Seed {index}",
            "offer_title": f"Candidate {index}",
            "offer_url": f"https://example.test/p{index}",
        }
        for index in range(5)
    )
    canaries = (
        {
            "canary_id": "known-negative",
            "expected_identity_truth": "NOT_MATCH",
            "expected_pricing_admission_truth": "EXCLUDED",
            "our_oe": "CANARY-OE",
            "our_title": "Known seed",
            "offer_title": "Known wrong candidate",
            "offer_description": "Known price 750 грн",
            "offer_characteristics": '[{"name":"Ціна","value":"750"}]',
            "offer_url": "https://example.test/canary",
        },
    )

    first = build_blinded_review_batch(
        market_rows,
        canaries,
        batch_size=3,
        selection_seed="review-v1",
    )
    second = build_blinded_review_batch(
        market_rows,
        canaries,
        batch_size=3,
        selection_seed="review-v1",
    )

    assert first == second
    assert len(first.rows) == 3
    assert first.canary_count == 1
    assert all("expected_identity_truth" not in row for row in first.rows)
    assert all("canary_id" not in row for row in first.rows)
    assert all("750" not in row["offer_description"] for row in first.rows)
    assert all("750" not in row["offer_characteristics"] for row in first.rows)
    assert len(first.canary_key["canaries"]) == 1
    token = first.canary_key["canaries"][0]["opaque_source_rank"]
    assert any(row["pair_id"] == token for row in first.rows)


def test_review_batch_without_canaries_is_rejected() -> None:
    with pytest.raises(MarketFunnelError, match="at least one known-answer canary"):
        build_blinded_review_batch(
            ({"pair_id": "market-pair"},),
            (),
            batch_size=1,
            selection_seed="review-v1",
        )


def test_human_review_projection_removes_price_fields_and_currency_amounts() -> None:
    item = FunnelItemInput(
        catalog_item_id="price-blind-review",
        source_row=8,
        start_snapshot=_snapshot(
            description="Original description: 999 грн",
            characteristics_raw={"price": 999, "side": "left"},
        ),
        scrape_target_status="succeeded",
        scrape_target_reason_codes=(),
        run_item_status="classified",
        run_item_error=None,
        observations=(
            MarketObservationInput(
                observation_id="candidate-price",
                via_oe_number="1086282",
                is_owned=False,
                cohort_role="TARGET_MARKET",
                oe_verification_status="VERIFIED_EXACT",
                comparability_hard_gate_result="PASS",
                automatic_eligible=True,
                reason_codes=(),
                title="Candidate for 1 250 UAH",
                description="Sale price: 45",
                candidate_snapshot={
                    "characteristics": [
                        {"label": "Ціна", "value": "1250"},
                        {"name": "Сторона", "value": "ліва"},
                    ],
                    "fitment": {
                        "caption": "Ціна",
                        "value": "777",
                    },
                },
            ),
        ),
        recommendations=(),
    )

    row = market_review_source_rows((item,))[0]

    assert "999" not in row["our_characteristics"]
    assert "<PRICE_REDACTED>" in row["our_description"]
    assert "<PRICE_REDACTED>" in row["offer_title"]
    assert "<PRICE_REDACTED>" in row["offer_description"]
    assert "45" not in row["offer_description"]
    assert "1250" not in row["offer_characteristics"]
    assert "Сторона" in row["offer_characteristics"]
    assert "777" not in row["offer_fitment"]


def test_canary_verification_fails_a_plausible_but_wrong_batch() -> None:
    key = {
        "canaries": [
            {
                "opaque_source_rank": "opaque-token",
                "expected_identity_truth": "NOT_MATCH",
                "expected_pricing_admission_truth": "EXCLUDED",
            }
        ]
    }
    reviewed = {
        "tasks": [
            {
                "review_id": "LR-1",
                "source_refs": [{"source_rank": "opaque-token"}],
                "labels": {
                    "identity_truth": "MATCH",
                    "pricing_admission_truth": "ADMITTED",
                },
            }
        ]
    }

    result = verify_canary_labels(reviewed, key)

    assert result["status"] == "FAIL"
    assert result["canaries_expected"] == 1
    assert result["canaries_correct"] == 0
    assert result["mismatches"][0]["review_id"] == "LR-1"


def test_human_truth_scores_the_model_without_becoming_model_truth() -> None:
    reviewed = {
        "tasks": [
            {
                "review_id": "LR-positive",
                "source_refs": [{"source_rank": "observation-1"}],
                "labels": {
                    "identity_truth": "MATCH",
                    "pricing_admission_truth": "ADMITTED",
                },
            },
            {
                "review_id": "LR-negative",
                "source_refs": [{"source_rank": "observation-2"}],
                "labels": {
                    "identity_truth": "NOT_MATCH",
                    "pricing_admission_truth": "EXCLUDED",
                },
            },
        ]
    }
    predictions = {
        "pairs": [
            {
                "pair_id": "observation-1",
                "identity_verdict": "MATCH",
                "pricing_admission": "ADMITTED",
            },
            {
                "pair_id": "observation-2",
                "identity_verdict": "MATCH",
                "pricing_admission": "ADMITTED",
            },
        ]
    }

    result = score_reviewed_market_pairs(reviewed, predictions)

    assert result["labelled_pairs"] == 2
    assert result["human_matches"] == 1
    assert result["human_not_matches"] == 1
    assert result["human_class_coverage_complete"] is True
    assert result["model_false_accept_count"] == 1
    assert result["unsafe_pricing_admission_count"] == 1
    assert result["model_is_ground_truth"] is False
    assert result["price_showing_ready"] is False


def test_canaries_are_verified_separately_and_excluded_from_model_score() -> None:
    reviewed = {
        "tasks": [
            {
                "review_id": "LR-market",
                "source_refs": [{"source_rank": "observation-1"}],
                "labels": {
                    "identity_truth": "MATCH",
                    "pricing_admission_truth": "ADMITTED",
                },
            },
            {
                "review_id": "LR-canary",
                "source_refs": [{"source_rank": "opaque-canary"}],
                "labels": {
                    "identity_truth": "NOT_MATCH",
                    "pricing_admission_truth": "EXCLUDED",
                },
            },
        ]
    }
    predictions = {
        "pairs": [
            {
                "pair_id": "observation-1",
                "identity_verdict": "MATCH",
                "pricing_admission": "ADMITTED",
            }
        ]
    }
    canary_key = {
        "canaries": [
            {
                "opaque_source_rank": "opaque-canary",
                "expected_identity_truth": "NOT_MATCH",
                "expected_pricing_admission_truth": "EXCLUDED",
            }
        ]
    }

    result = score_reviewed_market_pairs(
        reviewed,
        predictions,
        canary_key=canary_key,
    )

    assert result["review_tasks_total"] == 2
    assert result["canary_pairs_excluded_from_model_score"] == 1
    assert result["model_pairs_expected"] == 1
    assert result["labelled_pairs"] == 1
    assert result["complete_pair_accounting"] is True
    assert result["human_class_coverage_complete"] is False


def test_unexecuted_model_review_is_not_counted_as_an_abstention() -> None:
    reviewed = {
        "tasks": [
            {
                "review_id": "LR-unreviewed",
                "source_refs": [{"source_rank": "observation-1"}],
                "labels": {
                    "identity_truth": "NOT_MATCH",
                    "pricing_admission_truth": "EXCLUDED",
                },
            }
        ]
    }
    predictions = {
        "pairs": [
            {
                "pair_id": "observation-1",
                "identity_verdict": "MANUAL_REVIEW",
                "pricing_admission": "MANUAL_REVIEW",
                "review_status": "NOT_REVIEWED",
            }
        ]
    }

    result = score_reviewed_market_pairs(reviewed, predictions)

    assert result["labelled_pairs"] == 0
    assert result["model_abstention_count"] == 0
    assert result["complete_pair_accounting"] is False
    assert result["missing"][0]["reason"] == "MODEL_REVIEW_NOT_TERMINAL"
