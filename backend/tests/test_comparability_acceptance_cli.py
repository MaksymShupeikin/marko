from __future__ import annotations

from copy import deepcopy
import csv
from pathlib import Path

import pytest

from marko.comparability_acceptance_cli import (
    AcceptanceInputError,
    evaluate_acceptance,
    evaluate_reviewer_agreement,
    evaluate_semantic_gate,
    finalize_locked_truth,
    import_locked_review_csv,
    prepare_locked_review_set,
    prepare_reviewer_overlap,
    validate_locked_review_set,
    verify_catalog_manifest,
    verify_shadow_parity,
    write_locked_review_csv,
    write_locked_review_html,
)


def _locked_payloads() -> tuple[dict[str, object], dict[str, object]]:
    labels: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []
    for index in range(100):
        pair_id = f"P{index:03d}"
        pricing_truth = "ADMITTED" if index < 50 else "EXCLUDED"
        identity_prediction = "MATCH" if index < 70 else "MANUAL_REVIEW"
        pricing_prediction = (
            "ADMITTED"
            if index < 35
            else "EXCLUDED"
            if 50 <= index < 100
            else "MANUAL_REVIEW"
        )
        labels.append(
            {
                "pair_id": pair_id,
                "identity_truth": "MATCH",
                "pricing_admission_truth": pricing_truth,
            }
        )
        pairs.append(
            {
                "pair_id": pair_id,
                "identity_verdict": identity_prediction,
                "pricing_admission": pricing_prediction,
            }
        )
    for index in range(300):
        pair_id = f"N{index:03d}"
        labels.append(
            {
                "pair_id": pair_id,
                "identity_truth": "NOT_MATCH",
                "pricing_admission_truth": "EXCLUDED",
            }
        )
        pairs.append(
            {
                "pair_id": pair_id,
                "identity_verdict": "NOT_MATCH",
                "pricing_admission": "EXCLUDED",
            }
        )
    return (
        {"labels": labels},
        {
            "pairs": pairs,
            "operational_metrics": {
                "provider_requests": 400,
                "valid_terminal_results": 392,
                "provider_budget_exhausted": 0,
                "candidate_terminal_results": 400,
                "owned_store_candidates": 1,
                "owned_store_excluded": 1,
                "duplicate_seller_candidates": 1,
                "duplicate_seller_excluded": 1,
            },
        },
    )


def test_locked_acceptance_enforces_the_exact_statistical_denominator() -> None:
    truth, predictions = _locked_payloads()

    result = evaluate_acceptance(truth, predictions, profile="locked")

    assert result["status"] == "LOCKED_ACCEPT"
    assert result["promotion_eligible"] is True
    assert result["metrics"]["zero_event_false_match_upper_95"] == "0.009936"
    assert result["metrics"]["automatic_match_recall"] == "0.700000"
    assert result["metrics"]["pricing_eligible_admission_rate"] == "0.700000"


def test_one_false_match_rejects_the_locked_set() -> None:
    truth, predictions = _locked_payloads()
    broken = deepcopy(predictions)
    broken["pairs"][100]["identity_verdict"] = "MATCH"

    result = evaluate_acceptance(truth, broken, profile="locked")

    assert result["status"] == "LOCKED_REJECT"
    assert result["promotion_eligible"] is False
    assert result["metrics"]["false_match_count"] == 1
    upper_gate = next(
        gate for gate in result["gates"] if gate["name"] == "false_match_upper_95"
    )
    assert upper_gate["actual"] == "NOT_PROVEN"


def test_smoke_result_can_never_authorize_promotion() -> None:
    truth = {
        "labels": [
            {
                "pair_id": "P1",
                "identity_truth": "MATCH",
                "pricing_admission_truth": "MANUAL_REVIEW",
            },
            {
                "pair_id": "N1",
                "identity_truth": "NOT_MATCH",
                "pricing_admission_truth": "EXCLUDED",
            },
        ]
    }
    predictions = {
        "pairs": [
            {
                "pair_id": "P1",
                "identity_verdict": "MATCH",
                "pricing_admission": "MANUAL_REVIEW",
            },
            {
                "pair_id": "N1",
                "identity_verdict": "NOT_MATCH",
                "pricing_admission": "EXCLUDED",
            },
        ]
    }

    result = evaluate_acceptance(truth, predictions, profile="smoke")

    assert result["status"] == "SMOKE_REGRESSION_PASS"
    assert result["promotion_eligible"] is False


def test_semantic_gate_measures_only_explicit_contradictions() -> None:
    truth = {
        "labels": [
            {"pair_id": "P1", "identity_truth": "MATCH"},
            {"pair_id": "N1", "identity_truth": "NOT_MATCH"},
        ]
    }
    benchmark = {
        "pairs": [
            {
                "pair_id": "P1",
                "seed": {"title": "Амортизатор передний Mercedes W202"},
                "candidate": {"title": "Амортизатор передний Mercedes W202"},
            },
            {
                "pair_id": "N1",
                "seed": {"title": "Амортизатор передний Mercedes W202"},
                "candidate": {"title": "Амортизатор задний Mercedes W202"},
            },
        ]
    }

    result = evaluate_semantic_gate(benchmark, truth)

    assert result["status"] == "SEMANTIC_GATE_SMOKE_PASS"
    assert result["promotion_eligible"] is False
    assert result["metrics"] == {
        "false_hard_stop_count": 0,
        "false_hard_stop_rate": "0.000000",
        "positive_survival_count": 1,
        "positive_survival_rate": "1.000000",
        "positive_survival_wilson_95": {
            "lower": "0.206549",
            "upper": "1.000000",
        },
        "zero_event_false_hard_stop_upper_95": "0.950000",
        "hard_negative_block_count": 1,
        "hard_negative_block_rate": "1.000000",
        "hard_negative_block_wilson_95": {
            "lower": "0.206549",
            "upper": "1.000000",
        },
        "missed_hard_negative_count": 0,
        "zero_event_missed_hard_negative_upper_95": "0.950000",
    }
    assert result["rows"] == [
        {
            "pair_id": "N1",
            "identity_truth": "NOT_MATCH",
            "semantic_gate": "HARD_STOP",
            "conflict_dimensions": ["position"],
            "hard_stop_conflicts": [
                {
                    "dimension": "position",
                    "our_value": "front",
                    "candidate_value": "rear",
                    "explanation": (
                        "Deterministic semantic extraction found conflicting position."
                    ),
                }
            ],
        },
        {
            "pair_id": "P1",
            "identity_truth": "MATCH",
            "semantic_gate": "NEEDS_REVIEW",
            "conflict_dimensions": [],
            "hard_stop_conflicts": [],
        },
    ]


def _write_review_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "rank",
        "our_oe",
        "our_title",
        "our_price",
        "our_sku",
        "our_brand",
        "our_category",
        "our_mpn",
        "our_part_numbers",
        "our_applicability",
        "our_characteristics",
        "our_product_url",
        "our_image_urls",
        "our_description",
        "offer_id",
        "offer_title",
        "offer_sku",
        "offer_brand",
        "offer_price",
        "offer_url",
        "offer_seller_name",
        "offer_image_url",
        "offer_category",
        "offer_category_path",
        "offer_measure_unit",
        "offer_availability",
        "offer_condition",
        "offer_package_quantity",
        "offer_oe_raw",
        "offer_fitment",
        "offer_engine",
        "offer_year_from",
        "offer_year_to",
        "offer_body_variant",
        "offer_side",
        "offer_position",
        "offer_description",
        "offer_characteristics",
    ]
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_locked_review_preparation_is_blind_deduplicated_and_leakage_safe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pairs.csv"
    _write_review_csv(
        source,
        [
            {
                "rank": "1",
                "our_oe": "DEV-1",
                "our_title": "Development seed",
                "our_price": "100",
                "offer_id": "D1",
                "offer_title": "Development candidate",
                "offer_sku": "D1",
                "offer_brand": "Brand",
                "offer_price": "90",
                "offer_url": "https://prom.ua/p1.html?utm=x",
            },
            {
                "rank": "2",
                "our_oe": "LOCK-2",
                "our_title": "Locked seed two",
                "our_price": "200",
                "our_sku": "SEED-2",
                "our_brand": "KEMP",
                "our_category": "Замки",
                "our_mpn": "MPN-2",
                "our_part_numbers": '["LOCK-2", "CROSS-2"]',
                "our_applicability": "VW T5 2003-2015",
                "our_characteristics": '{"pins": 6}',
                "our_product_url": "https://kemp.prom.ua/p2.html?owned=1",
                "our_image_urls": (
                    "https://images.prom.ua/seed-2-a.jpg, "
                    "https://images.prom.ua/seed-2-b.jpg"
                ),
                "our_description": "Complete housing",
                "offer_id": "C2",
                "offer_title": "Candidate two",
                "offer_sku": "C2",
                "offer_brand": "Brand",
                "offer_price": "180",
                "offer_url": "https://prom.ua/p2.html?utm=x",
                "offer_seller_name": "External seller",
                "offer_image_url": "https://images.prom.ua/p2.jpg?size=640",
                "offer_category": "Автозапчастини",
                "offer_category_path": "Авто > Замки",
                "offer_measure_unit": "шт.",
                "offer_availability": "avail",
                "offer_condition": "new",
                "offer_package_quantity": "1",
                "offer_oe_raw": "LOCK-2",
                "offer_fitment": "VW T5",
                "offer_engine": "2.0 TDI",
                "offer_year_from": "2003",
                "offer_year_to": "2015",
                "offer_body_variant": "van",
                "offer_side": "rear",
                "offer_position": "tailgate",
                "offer_description": "Housing with six-pin contact group",
                "offer_characteristics": '{"pins": 6}',
            },
            {
                "rank": "3",
                "our_oe": "LOCK-2",
                "our_title": "Locked seed two",
                "our_price": "999",
                "offer_id": "C2",
                "offer_title": "Candidate two",
                "offer_sku": "C2",
                "offer_brand": "Brand",
                "offer_price": "1",
                "offer_url": "https://prom.ua/p2.html?different=query",
            },
            {
                "rank": "4",
                "our_oe": "LOCK-3",
                "our_title": "Locked seed three",
                "our_price": "300",
                "offer_id": "C3",
                "offer_title": "Candidate three",
                "offer_sku": "C3",
                "offer_brand": "Other",
                "offer_price": "250",
                "offer_url": "https://prom.ua/p3.html",
            },
        ],
    )
    development = {
        "pairs": [
            {
                "pair_id": "DEV",
                "seed": {"code": "DEV-1", "title": "Development seed"},
                "candidate": {
                    "code": "D1",
                    "title": "Development candidate",
                    "url": "https://prom.ua/p1.html",
                },
            }
        ]
    }

    first = prepare_locked_review_set(
        [source],
        development_payloads=[development],
        selection_seed="locked-seed",
    )
    second = prepare_locked_review_set(
        [source],
        development_payloads=[development],
        selection_seed="locked-seed",
    )

    assert first["tasks"] == second["tasks"]
    assert first["selection"]["selected_pairs"] == 2
    assert first["selection"]["max_one_per_seed_and_candidate_capacity"] == 2
    assert first["selection"]["minimum_additional_unique_groups_for_400"] == 398
    assert first["selection"]["locked_100_plus_300_structurally_reachable"] is False
    assert first["selection"]["excluded_development_overlap_rows"] == 1
    assert first["selection"]["deduplicated_source_rows"] == 1
    assert first["contains_model_predictions"] is False
    assert first["contains_prices"] is False
    rendered = str(first["tasks"])
    assert "our_price" not in rendered
    assert "offer_price" not in rendered
    assert "utm=" not in rendered
    enriched = next(task for task in first["tasks"] if task["seed"]["oe"] == "LOCK-2")
    assert enriched["seed"]["part_numbers"] == '["LOCK-2", "CROSS-2"]'
    assert enriched["seed"]["product_url"] == "https://kemp.prom.ua/p2.html"
    assert enriched["candidate"]["package_quantity"] == "1"
    assert enriched["candidate"]["image_url"] == "https://images.prom.ua/p2.jpg"
    assert validate_locked_review_set(first)["status"] == "PASS"
    assert validate_locked_review_set(first, require_complete=True)["status"] == "FAIL"

    tampered = deepcopy(first)
    tampered["tasks"][0]["candidate"]["title"] = "Changed after freeze"
    invalid = validate_locked_review_set(tampered)
    assert invalid["status"] == "FAIL"
    assert "EVIDENCE_HASH_MISMATCH" in {row["reason"] for row in invalid["invalid"]}

    leaked = deepcopy(first)
    leaked["tasks"][0]["model_prediction"] = "MATCH"
    leakage = validate_locked_review_set(leaked)
    assert "BLINDING_BOUNDARY_VIOLATION" in {
        row["reason"] for row in leakage["invalid"]
    }

    review_csv = tmp_path / "review.csv"
    export = write_locked_review_csv(first, review_csv)
    review_html = tmp_path / "review.html"
    html_export = write_locked_review_html(first, review_html)
    html_text = review_html.read_text(encoding="utf-8")
    assert "Locked seed two" in html_text
    assert "https://images.prom.ua/p2.jpg" in html_text
    assert "our_price" not in html_text
    assert "offer_price" not in html_text
    assert "model_prediction" not in html_text
    assert html_export["exports_importable_labels_csv"] is True
    assert html_export["contains_prices"] is False
    with review_csv.open("r", encoding="utf-8-sig", newline="") as source_file:
        csv_rows = list(csv.DictReader(source_file))
        csv_fields = list(csv_rows[0])
    for index, row in enumerate(csv_rows):
        row["identity_truth"] = "MATCH" if index == 0 else "NOT_MATCH"
        row["pricing_admission_truth"] = "ADMITTED" if index == 0 else "EXCLUDED"
        row["reason_codes"] = "EXPERT_REVIEW"
        row["evidence_notes"] = "Checked against source evidence"
    with review_csv.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(csv_rows)
    imported = import_locked_review_csv(
        first,
        review_csv,
        reviewer_id="reviewer-1",
        reviewer_role="independent-domain-expert",
        reviewed_at="2026-08-05T00:00:00Z",
        independence_attested=True,
    )

    assert export["contains_prices"] is False
    assert export["contains_model_predictions"] is False
    assert (
        validate_locked_review_set(imported, require_complete=True)["status"] == "PASS"
    )


def test_locked_review_v2_collapses_title_slug_and_listing_clone_leakage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "identity-families.csv"
    _write_review_csv(
        source,
        [
            {
                "rank": "1",
                "our_oe": "1K0 615 301",
                "our_title": "Brake disc title A",
                "offer_id": "seller-row-a",
                "offer_title": "Candidate title A",
                "offer_sku": "DISC-A",
                "offer_brand": "Brand A",
                "offer_url": "https://prom.ua/ua/p123-first-slug.html?utm=x",
            },
            {
                "rank": "2",
                "our_oe": "1K0615301",
                "our_title": "Completely rewritten seed title",
                "offer_id": "seller-row-b",
                "offer_title": "Completely rewritten candidate title",
                "offer_sku": "DISC-A",
                "offer_brand": "Brand A",
                "offer_url": "https://shop.prom.ua/p123-other-slug.html",
            },
            {
                "rank": "3",
                "our_oe": "OE-SECOND",
                "our_title": "Second seed",
                "offer_id": "clone-listing-one",
                "offer_title": "Clone product first wording",
                "offer_sku": "CLONE-42",
                "offer_brand": "Clone Brand",
                "offer_url": "https://prom.ua/ua/p200-first.html",
            },
            {
                "rank": "4",
                "our_oe": "OE-THIRD",
                "our_title": "Third seed",
                "offer_id": "clone-listing-two",
                "offer_title": "Clone product second wording",
                "offer_sku": "CLONE 42",
                "offer_brand": "Clone Brand",
                "offer_url": "https://prom.ua/ua/p201-second.html",
            },
        ],
    )

    review = prepare_locked_review_set(
        [source],
        selection_seed="identity-family-v2",
    )

    assert review["schema_version"] == "comparability-locked-review-set-v2"
    assert review["identity_fingerprint_version"] == (
        "comparability-review-identity-v2"
    )
    assert review["selection"]["eligible_unique_pairs"] == 3
    assert review["selection"]["deduplicated_source_rows"] == 1
    assert review["selection"]["selected_seed_groups"] == 3
    assert review["selection"]["selected_candidate_groups"] == 3
    assert review["selection"]["selected_candidate_families"] == 2
    assert review["selection"]["max_one_per_seed_and_candidate_capacity"] == 2
    assert validate_locked_review_set(review)["status"] == "PASS"

    stale = deepcopy(review)
    stale["schema_version"] = "comparability-locked-review-set-v1"
    stale_validation = validate_locked_review_set(stale)
    assert "STALE_REVIEW_SCHEMA" in {
        row["reason"] for row in stale_validation["invalid"]
    }

    forged_family = deepcopy(review)
    forged_family["tasks"][0]["candidate_family_fingerprint"] = "f" * 64
    forged_validation = validate_locked_review_set(forged_family)
    assert "CANDIDATE_FAMILY_FINGERPRINT_MISMATCH" in {
        row["reason"] for row in forged_validation["invalid"]
    }


def test_locked_review_capacity_uses_exact_bipartite_matching(tmp_path: Path) -> None:
    source = tmp_path / "hall-deficit.csv"
    rows: list[dict[str, str]] = []
    # Three seeds and three candidates exist, but Hall's condition fails:
    # S1 and S2 can both use only C1, while S3 can use C2 or C3. The maximum
    # independent set is therefore two pairs, not min(3, 3) == three.
    for rank, seed, candidate in (
        (1, "S1", "C1"),
        (2, "S2", "C1"),
        (3, "S3", "C2"),
        (4, "S3", "C3"),
    ):
        rows.append(
            {
                "rank": str(rank),
                "our_oe": seed,
                "our_title": f"Seed {seed}",
                "our_price": "999",
                "offer_id": candidate,
                "offer_title": f"Candidate {candidate}",
                "offer_sku": candidate,
                "offer_brand": "Brand",
                "offer_price": "1",
                "offer_url": f"https://prom.ua/{candidate.lower()}.html",
            }
        )
    _write_review_csv(source, rows)

    review = prepare_locked_review_set([source], selection_seed="hall-deficit")

    assert review["selection"]["selected_seed_groups"] == 3
    assert review["selection"]["selected_candidate_groups"] == 3
    assert review["selection"]["max_one_per_seed_and_candidate_capacity"] == 2
    assert (
        review["selection"]["capacity_algorithm"]
        == "exact-bipartite-maximum-matching-v1"
    )
    assert review["selection"]["minimum_additional_unique_groups_for_400"] == 398


def _independently_labeled_review_set(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    source = tmp_path / "agreement.csv"
    rows = [
        {
            "rank": str(index + 1),
            "our_oe": f"OE-{index:03d}",
            "our_title": f"Agreement seed {index}",
            "our_price": "999",
            "offer_id": f"C-{index:03d}",
            "offer_title": f"Agreement candidate {index}",
            "offer_sku": f"SKU-{index:03d}",
            "offer_brand": "Brand",
            "offer_price": "1",
            "offer_url": f"https://prom.ua/p{index}.html",
        }
        for index in range(41)
    ]
    _write_review_csv(source, rows)
    primary = prepare_locked_review_set([source], selection_seed="agreement")
    secondary = deepcopy(primary)
    for reviewer, reviewer_id in (
        (primary, "reviewer-primary"),
        (secondary, "reviewer-secondary"),
    ):
        reviewer["review_attestation"].update(
            {
                "reviewer_id": reviewer_id,
                "reviewer_role": "independent_auto_parts_expert",
                "reviewed_at": "2026-08-05T00:00:00Z",
                "independence_attested": True,
            }
        )
        for index, task in enumerate(reviewer["tasks"]):
            identity = "MATCH" if index % 2 == 0 else "NOT_MATCH"
            task["labels"].update(
                {
                    "identity_truth": identity,
                    "pricing_admission_truth": (
                        "ADMITTED" if identity == "MATCH" else "EXCLUDED"
                    ),
                    "evidence_notes": "Independent agreement fixture",
                }
            )
    return primary, secondary


def test_reviewer_agreement_requires_independent_hash_pinned_overlap(
    tmp_path: Path,
) -> None:
    primary, secondary = _independently_labeled_review_set(tmp_path)

    result = evaluate_reviewer_agreement(primary, secondary)

    assert result["status"] == "PASS"
    assert result["fully_labeled_overlap"] == 41
    assert result["identity"]["raw_agreement"] == 1.0
    assert result["identity"]["cohen_kappa"] == 1.0
    assert result["pricing_admission"]["cohen_kappa"] == 1.0
    assert result["promotion_authorized"] is False

    secondary["tasks"][0]["candidate"]["title"] = "Tampered evidence"
    with pytest.raises(AcceptanceInputError, match="secondary review set is invalid"):
        evaluate_reviewer_agreement(primary, secondary)


def test_reviewer_agreement_fails_below_quality_thresholds(tmp_path: Path) -> None:
    primary, secondary = _independently_labeled_review_set(tmp_path)
    for task in secondary["tasks"][:10]:
        task["labels"].update(
            {
                "identity_truth": "NOT_MATCH",
                "pricing_admission_truth": "EXCLUDED",
            }
        )

    result = evaluate_reviewer_agreement(primary, secondary)

    assert result["status"] == "FAIL"
    assert result["identity"]["status"] == "FAIL"
    assert result["pricing_admission"]["status"] == "FAIL"
    assert result["disagreement_count"] > 0
    assert result["adjudication_required"] is True


def test_reviewer_agreement_rejects_same_reviewer(tmp_path: Path) -> None:
    primary, secondary = _independently_labeled_review_set(tmp_path)
    secondary["review_attestation"]["reviewer_id"] = "reviewer-primary"

    with pytest.raises(AcceptanceInputError, match="different reviewer IDs"):
        evaluate_reviewer_agreement(primary, secondary)


def test_prepare_reviewer_overlap_is_deterministic_and_scrubs_primary_labels(
    tmp_path: Path,
) -> None:
    primary, _ = _independently_labeled_review_set(tmp_path)

    first = prepare_reviewer_overlap(
        primary,
        selection_seed="second-reviewer-v1",
        sample_size=10,
    )
    second = prepare_reviewer_overlap(
        primary,
        selection_seed="second-reviewer-v1",
        sample_size=10,
    )

    assert first == second
    assert len(first["tasks"]) == 10
    assert first["task_manifest_sha256"] != primary["task_manifest_sha256"]
    assert first["parent_task_manifest_sha256"] == primary["task_manifest_sha256"]
    assert first["review_attestation"]["reviewer_id"] == ""
    assert all(
        task["labels"]
        == {
            "identity_truth": "",
            "pricing_admission_truth": "",
            "reason_codes": [],
            "evidence_notes": "",
        }
        for task in first["tasks"]
    )
    assert validate_locked_review_set(first)["status"] == "PASS"


def test_locked_truth_finalization_requires_independent_unique_100_plus_300(
    tmp_path: Path,
) -> None:
    source = tmp_path / "locked.csv"
    rows = []
    for index in range(400):
        rows.append(
            {
                "rank": str(index + 1),
                "our_oe": f"OE-{index:03d}",
                "our_title": f"Our product {index}",
                "our_price": "999",
                "offer_id": f"C-{index:03d}",
                "offer_title": f"Candidate product {index}",
                "offer_sku": f"SKU-{index:03d}",
                "offer_brand": "Brand",
                "offer_price": "1",
                "offer_url": f"https://prom.ua/p{index}.html",
            }
        )
    _write_review_csv(source, rows)
    review = prepare_locked_review_set(
        [source],
        selection_seed="review-order",
    )
    assert review["selection"]["locked_100_plus_300_structurally_reachable"] is True
    review["review_attestation"].update(
        {
            "reviewer_id": "domain-reviewer-1",
            "reviewer_role": "independent_auto_parts_expert",
            "reviewed_at": "2026-08-05T00:00:00Z",
            "independence_attested": True,
        }
    )
    for index, task in enumerate(review["tasks"]):
        if index < 50:
            identity, pricing = "MATCH", "ADMITTED"
        elif index < 100:
            identity, pricing = "MATCH", "EXCLUDED"
        else:
            identity, pricing = "NOT_MATCH", "EXCLUDED"
        task["labels"].update(
            {
                "identity_truth": identity,
                "pricing_admission_truth": pricing,
                "evidence_notes": f"Independent evidence review {index}",
            }
        )

    validation = validate_locked_review_set(review, require_complete=True)
    truth = finalize_locked_truth(review, selection_seed="final-order")

    assert validation["status"] == "PASS"
    assert truth["schema_version"] == "comparability-locked-truth-v2"
    assert truth["identity_fingerprint_version"] == (
        "comparability-review-identity-v2"
    )
    assert len(truth["labels"]) == 400
    assert sum(row["identity_truth"] == "MATCH" for row in truth["labels"]) == 100
    assert sum(row["identity_truth"] == "NOT_MATCH" for row in truth["labels"]) == 300
    assert truth["selection_contract"]["max_pairs_per_seed_group"] == 1
    assert truth["selection_contract"]["max_pairs_per_candidate_family"] == 1
    assert truth["promotion_authorized"] is False

    insufficient = deepcopy(review)
    insufficient["tasks"][100]["labels"].update(
        {
            "identity_truth": "MATCH",
            "pricing_admission_truth": "EXCLUDED",
        }
    )
    with pytest.raises(AcceptanceInputError, match="300 unique NOT_MATCH"):
        finalize_locked_truth(insufficient, selection_seed="final-order")


def test_catalog_manifest_rejects_silent_loss_and_unexplained_rejection() -> None:
    result = verify_catalog_manifest(
        {
            "rows": [
                {"source_row": 1, "terminal_status": "IMPORTED"},
                {
                    "source_row": 2,
                    "terminal_status": "REJECTED_NOT_IMPORTABLE",
                    "reason_codes": [],
                },
            ]
        },
        expected_rows=3,
    )

    assert result["status"] == "FAIL"
    assert result["missing_source_rows"] == [3]
    assert result["silent_loss_count"] == 1
    assert {row["reason"] for row in result["invalid_rows"]} == {
        "REJECTION_UNEXPLAINED"
    }


def test_full_catalog_gate_requires_pricing_terminal_result_for_imported_rows() -> None:
    import_only = {
        "rows": [
            {
                "source_ordinal": 1,
                "source_row": 2,
                "terminal_status": "IMPORTED",
                "reason_codes": [],
            }
        ]
    }

    rejected = verify_catalog_manifest(
        import_only,
        expected_rows=1,
        require_pricing_replay=True,
    )

    assert rejected["status"] == "FAIL"
    assert {row["reason"] for row in rejected["invalid_rows"]} == {
        "PRICING_NOT_TERMINAL",
        "PRICING_RUN_ITEM_MISSING",
        "PRICING_RUN_ID_MISSING",
        "PRICING_REPLAY_NOT_COMPLETE",
    }

    replay = deepcopy(import_only)
    replay.update(
        {
            "pricing_run_id": "run-1",
            "pricing_replay_complete": True,
        }
    )
    replay["rows"][0].update(
        {
            "pricing_run_item_id": "item-1",
            "pricing_terminal": True,
            "pricing_terminal_status": "CALCULATED",
        }
    )

    accepted = verify_catalog_manifest(
        replay,
        expected_rows=1,
        require_pricing_replay=True,
    )

    assert accepted["status"] == "PASS"
    assert accepted["silent_loss_count"] == 0


def test_shadow_parity_compares_recommendation_cohort_and_p_min_hashes() -> None:
    off = {
        "rows": [
            {
                "pair_id": "SKU-1",
                "recommendation_hash": "a",
                "cohort_hash": "b",
                "p_min_hash": "c",
            }
        ]
    }
    shadow = deepcopy(off)
    shadow["rows"][0]["p_min_hash"] = "changed"

    result = verify_shadow_parity(off, shadow)

    assert result["status"] == "FAIL"
    assert result["mismatches"] == [
        {
            "pair_id": "SKU-1",
            "field": "p_min_hash",
            "off": "c",
            "shadow": "changed",
        }
    ]
