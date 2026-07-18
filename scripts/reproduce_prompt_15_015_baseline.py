#!/usr/bin/env python3
"""Executable before/after reproductions for PROMPT_15_015.

The script intentionally uses deficient legacy offers.  Before remediation they
produce an automatic price; after remediation the same payload must fail closed.
It never performs a network request and never prints configuration values.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import subprocess
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
    recommend_price,
    verified_comparison_evidence,
)


AUTOMATIC = {
    RecommendationAction.RAISE,
    RecommendationAction.HOLD,
    RecommendationAction.LOWER,
}
ABSTAIN = {
    RecommendationAction.MANUAL_REVIEW,
    RecommendationAction.INSUFFICIENT_DATA,
}


def _legacy_offers(prices: tuple[str, ...], prefix: str) -> list[CompetitorOffer]:
    """Return the exact semantically-deficient boundary used by the original code."""

    return [
        CompetitorOffer(
            observation_id=f"{prefix}-{index}",
            seller_id=f"seller-{index}",
            seller_name=f"Seller {index}",
            price=Decimal(price),
            currency="UAH",
            is_available=True,
            age_hours=Decimal("0"),
            match_confidence=Decimal("0.95"),
            tier=ProductTier.BUDGET,
            tier_confidence=Decimal("0.95"),
            source_confidence=Decimal("1"),
        )
        for index, price in enumerate(prices)
    ]


def _verified_offers(
    prices: tuple[str, ...], prefix: str
) -> list[CompetitorOffer]:
    return [
        CompetitorOffer(
            observation_id=f"{prefix}-{index}",
            seller_id=f"seller-{index}",
            seller_name=f"Seller {index}",
            price=Decimal(price),
            currency="UAH",
            currency_raw="UAH",
            is_available=True,
            age_hours=Decimal("0"),
            match_confidence=Decimal("0.95"),
            tier=ProductTier.BUDGET,
            tier_confidence=Decimal("0.95"),
            comparison_evidence=verified_comparison_evidence(
                stable_seller_id=f"seller-{index}",
                source_record_id=f"{prefix}-{index}",
            ),
        )
        for index, price in enumerate(prices)
    ]


def _preflight_example() -> dict[str, Any]:
    env_file = ROOT / "deploy" / ".env.production.example"
    env = os.environ.copy()
    env["ENVIRONMENT"] = "production"
    keys: list[str] = []
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        keys.append(key)
        env[key] = value
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_production_config.py"),
            "--env-file",
            str(env_file),
            "--mode",
            "static",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    return {
        "exit_code": completed.returncode,
        "input_keys": sorted(set(keys + ["ENVIRONMENT"])),
        "stdout_nonempty": bool(completed.stdout.strip()),
        "stderr_nonempty": bool(completed.stderr.strip()),
        "values_emitted": False,
    }


def build_reproductions() -> dict[str, Any]:
    context = ProductPricingContext(
        sku="PROMPT-15-015",
        category="validation",
        current_price=Decimal("800"),
    )
    missing = recommend_price(
        context,
        _legacy_offers(("1000", "1050", "1100", "1150", "1200"), "missing"),
        {},
    )

    cluster_context = ProductPricingContext(
        sku="PROMPT-15-015-CLUSTERS",
        category="validation",
        current_price=Decimal("80"),
    )
    cluster_offers = _verified_offers(
        ("100", "101", "102", "103", "180", "181", "182", "183"),
        "cluster",
    )
    baseline = recommend_price(
        cluster_context,
        cluster_offers,
        {},
        policy=PricingPolicy(version="pricing-v2"),
    )
    candidate = recommend_price(
        cluster_context,
        cluster_offers,
        {},
        policy=PricingPolicy(version="pricing-v3.1-heterogeneity-gated"),
    )

    docker = shutil.which("docker")
    return {
        "schema_version": "1.0.0",
        "prompt_id": "PROMPT_15_015",
        "network_requests": 0,
        "cases": {
            "E2E-BASELINE": {
                "docker_binary": docker or "NOT_AVAILABLE",
                "status": "NOT_VERIFIED" if docker else "BLOCKED_ENVIRONMENT",
            },
            "MATCH-MISSING-HARD-FIELDS": {
                "action": missing.action.value,
                "recommended_price": (
                    str(missing.recommended_price)
                    if missing.recommended_price is not None
                    else None
                ),
                "reason_codes": list(missing.reasons),
            },
            "DISP-TWO-CLUSTERS": {
                "baseline_action": baseline.action.value,
                "candidate_action": candidate.action.value,
                "candidate_price": (
                    str(candidate.recommended_price)
                    if candidate.recommended_price is not None
                    else None
                ),
                "candidate_reason_codes": list(candidate.reasons),
            },
            "PREFLIGHT-PLACEHOLDER": _preflight_example(),
        },
        "secrets_included": False,
    }


def _matches_expectation(payload: dict[str, Any], expectation: str) -> bool:
    cases = payload["cases"]
    missing = cases["MATCH-MISSING-HARD-FIELDS"]
    cluster = cases["DISP-TWO-CLUSTERS"]
    preflight = cases["PREFLIGHT-PLACEHOLDER"]
    if expectation == "before":
        return bool(
            missing["action"] in {item.value for item in AUTOMATIC}
            and missing["recommended_price"] is not None
            and cluster["baseline_action"] in {item.value for item in ABSTAIN}
            and cluster["candidate_action"] in {item.value for item in AUTOMATIC}
            and cluster["candidate_price"] is not None
            and preflight["exit_code"] == 0
        )
    return bool(
        missing["action"] in {item.value for item in ABSTAIN}
        and missing["recommended_price"] is None
        and cluster["candidate_action"] in {item.value for item in ABSTAIN}
        and cluster["candidate_price"] is None
        and preflight["exit_code"] != 0
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect", choices=("before", "after"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = build_reproductions()
    payload["expectation"] = args.expect
    payload["expectation_met"] = _matches_expectation(payload, args.expect)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if payload["expectation_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
