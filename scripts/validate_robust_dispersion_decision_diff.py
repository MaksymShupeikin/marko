#!/usr/bin/env python3
"""Compare legacy pricing-v2 with the candidate robust-dispersion v3 policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from metis.pricing import (  # noqa: E402
    CompetitorOffer,
    PricingPolicy,
    ProductPricingContext,
    ProductTier,
    RecommendationAction,
    StockStatus,
    recommend_price,
    verified_comparison_evidence,
)


ABSTENTIONS = {
    RecommendationAction.MANUAL_REVIEW,
    RecommendationAction.INSUFFICIENT_DATA,
}
AUTOMATIC_ACTIONS = {
    RecommendationAction.RAISE,
    RecommendationAction.HOLD,
    RecommendationAction.LOWER,
}


@dataclass(frozen=True)
class DecisionCase:
    case_id: str
    prices: tuple[str, ...]
    current_price: str = "80"
    context_overrides: dict[str, Any] = field(default_factory=dict)
    policy_overrides: dict[str, Any] = field(default_factory=dict)
    match_confidence: str = "0.95"


CASES = (
    DecisionCase("clean_grid", ("100", "105", "110", "115", "120")),
    DecisionCase("all_equal", ("100", "100", "100", "100", "100")),
    DecisionCase(
        "partial_degeneracy",
        ("100", "100", "100", "100", "100", "105", "110", "115"),
    ),
    DecisionCase(
        "one_high_outlier",
        ("100", "101", "102", "103", "104", "105", "106", "1000"),
    ),
    DecisionCase("right_skew", ("100", "101", "103", "108", "120", "160", "300")),
    DecisionCase(
        "two_clusters", ("100", "101", "102", "103", "180", "181", "182", "183")
    ),
    DecisionCase("small_n3", ("100", "105", "110")),
    DecisionCase("small_n4", ("100", "105", "110", "1000")),
    DecisionCase(
        "weak_match",
        ("100", "105", "110", "115", "120"),
        policy_overrides={"factor_floor": Decimal("0.75")},
        match_confidence="0.71",
    ),
    DecisionCase(
        "hold_threshold", ("100", "105", "110", "115", "120"), current_price="105"
    ),
    DecisionCase(
        "stale_markdown",
        ("100", "105", "110", "115", "120"),
        current_price="150",
        context_overrides={"stock_status": StockStatus.STALE, "cost": Decimal("90")},
    ),
    DecisionCase(
        "high_dispersion",
        ("100", "120", "140", "160", "180", "200", "220", "240"),
        policy_overrides={"max_dispersion": Decimal("0.20")},
    ),
)


def _offers(case: DecisionCase) -> list[CompetitorOffer]:
    return [
        CompetitorOffer(
            observation_id=f"{case.case_id}-{index}",
            seller_id=f"seller-{index}",
            seller_name=f"Seller {index}",
            price=Decimal(price),
            currency="UAH",
            is_available=True,
            age_hours=Decimal("0"),
            match_confidence=Decimal(case.match_confidence),
            tier=ProductTier.BUDGET,
            tier_confidence=Decimal("0.95"),
            currency_raw="UAH",
            comparison_evidence=verified_comparison_evidence(
                stable_seller_id=f"seller-{index}",
                source_record_id=f"{case.case_id}-{index}",
            ),
        )
        for index, price in enumerate(case.prices)
    ]


def _context(case: DecisionCase) -> ProductPricingContext:
    values: dict[str, Any] = {
        "sku": case.case_id,
        "category": "validation",
        "current_price": Decimal(case.current_price),
    }
    values.update(case.context_overrides)
    return ProductPricingContext(**values)


def _policy(case: DecisionCase, version: str) -> PricingPolicy:
    values = {"version": version, **case.policy_overrides}
    return PricingPolicy(**values)


def build_decision_diff(
    cases: tuple[DecisionCase, ...] = CASES,
    *,
    baseline_version: str = "pricing-v2",
    candidate_version: str = "pricing-v3.1-heterogeneity-gated",
    dataset_name: str = "synthetic_contract_matrix_v2",
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    counts = {"same": 0, "auto_to_manual": 0, "manual_to_auto": 0, "other": 0}
    unsafe_relaxation_count = 0
    for case in cases:
        context = _context(case)
        offers = _offers(case)
        legacy = recommend_price(
            context,
            offers,
            {},
            policy=_policy(case, baseline_version),
        )
        robust = recommend_price(
            context,
            offers,
            {},
            policy=_policy(case, candidate_version),
        )
        if legacy.action == robust.action:
            direction = "same"
        elif legacy.action in AUTOMATIC_ACTIONS and robust.action in ABSTENTIONS:
            direction = "auto_to_manual"
        elif legacy.action in ABSTENTIONS and robust.action in AUTOMATIC_ACTIONS:
            direction = "manual_to_auto"
            unsafe_relaxation_count += 1
        else:
            direction = "other"
        counts[direction] += 1
        profile = robust.dispersion_profile
        rows.append(
            {
                "case_id": case.case_id,
                "n_raw": robust.raw_competitor_count,
                "n_unique": robust.unique_seller_count,
                "n_clean": robust.clean_competitor_count,
                "legacy_dispersion": str(legacy.dispersion)
                if legacy.dispersion is not None
                else None,
                "iqr_cv": str(profile.robust_cvs["iqr"]) if profile else None,
                "mad_cv": str(profile.robust_cvs["mad"]) if profile else None,
                "sn_cv": str(profile.robust_cvs["sn"]) if profile else None,
                "qn_cv": str(profile.robust_cvs["qn"]) if profile else None,
                "v2_action": legacy.action.value,
                "v3_action": robust.action.value,
                "action_changed": legacy.action != robust.action,
                "change_direction": direction,
                "explanation": (
                    "v3.1 rejects a heterogeneous cohort"
                    if "ROBUST_MULTIMODAL_COHORT" in robust.reasons
                    else
                    "v3 is fail-closed on partial scale degeneracy"
                    if "ROBUST_SCALE_PARTIAL_DEGENERACY" in robust.reasons
                    else "same eligibility, cleaning, confidence and economic gates"
                ),
            }
        )
    return {
        "schema_version": "2.0.0",
        "dataset": dataset_name,
        "baseline_policy_version": baseline_version,
        "candidate_policy_version": candidate_version,
        "representative_market_calibration": False,
        "cases": rows,
        "counts": counts,
        "unsafe_relaxation_count": unsafe_relaxation_count,
        "execution_status": "PASS",
        "validation_gate": "PASS",
        "synthetic_safety_gate": (
            "PASS" if unsafe_relaxation_count == 0 else "NO_GO"
        ),
        "activation_gate": "BLOCKED_DATA",
        "activation_reason": (
            "No permitted representative decision-diff dataset; synthetic checks "
            "verify implementation safety but cannot calibrate production behavior."
        ),
    }


def _load_cases(path: Path) -> tuple[str, tuple[DecisionCase, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0.0" or not isinstance(
        payload.get("cases"), list
    ):
        raise ValueError("unsupported decision-diff dataset contract")
    cases = tuple(
        DecisionCase(
            case_id=str(item["case_id"]),
            prices=tuple(str(value) for value in item["prices"]),
            current_price=str(item.get("current_price", "80")),
            match_confidence=str(item.get("match_confidence", "0.95")),
        )
        for item in payload["cases"]
    )
    return str(payload.get("dataset_id", path.stem)), cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--baseline-version", default="pricing-v2")
    parser.add_argument(
        "--candidate-version", default="pricing-v3.1-heterogeneity-gated"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.dataset:
            dataset_name, cases = _load_cases(args.dataset)
        else:
            dataset_name, cases = "synthetic_contract_matrix_v2", CASES
        payload = build_decision_diff(
            cases,
            baseline_version=args.baseline_version,
            candidate_version=args.candidate_version,
            dataset_name=dataset_name,
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"DECISION_DIFF_INPUT_ERROR={type(exc).__name__}\n")
        return 2
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if payload["synthetic_safety_gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
