#!/usr/bin/env python3
"""Read-only export of canary-run market offers for human yes/no/doubt labels.

One row is one offer. ``human_verdict`` and ``human_note`` are left empty for
the owner. This script never writes to the database.

    python3 scripts/export_canary_offer_labels.py
    python3 scripts/export_canary_offer_labels.py --to-gold-set labeled.json
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_ID = "e53bcba8-037b-429c-a88e-323ff6a8a037"
DEFAULT_JSON = ROOT / "docs" / "canary_offer_labels_e53bcba8.json"
DEFAULT_CSV = ROOT / "docs" / "canary_offer_labels_e53bcba8.csv"
THICK_MIN_OFFERS = 3
ALLOWED_VERDICTS = frozenset({"yes", "no", "doubt"})

_EXPORT_SQL = """
SELECT COALESCE(json_agg(row_to_json(t) ORDER BY t.sku, t.price, t.observation_id), '[]'::json)
FROM (
    SELECT
        mo.id::text AS observation_id,
        pri.id::text AS pricing_run_item_id,
        pr.id::text AS pricing_run_id,
        ci.sku,
        ci.name AS catalog_name,
        ci.oe_norm,
        ci.identity_status,
        ci.current_price::text AS our_price,
        mo.url AS listing_url,
        mo.seller_id,
        mo.seller_name,
        mo.price::text AS price,
        mo.currency,
        mo.title,
        mo.condition_state,
        mo.condition_raw,
        mo.comparability_hard_gate_result,
        mo.automatic_eligible,
        mo.oe_verification_status,
        cls.cohort_role,
        cls.exclusion_reason,
        cls.reason_codes AS classification_reason_codes,
        mo.calibration_exclusion_codes,
        mo.candidate_snapshot -> 'semantic_gate' ->> 'reason' AS semantic_gate_reason,
        mo.candidate_snapshot -> 'semantic_gate' -> 'missing_pricing_dimensions'
            AS missing_pricing_dimensions,
        mo.candidate_snapshot -> 'semantic_gate' ->> 'status' AS semantic_gate_status,
        pri.status AS run_item_status,
        pri.error AS run_item_error
    FROM market_observations mo
    JOIN pricing_run_items pri ON pri.id = mo.pricing_run_item_id
    JOIN pricing_runs pr ON pr.id = pri.pricing_run_id
    JOIN catalog_items ci ON ci.id = mo.catalog_item_id
    LEFT JOIN LATERAL (
        SELECT
            otc.cohort_role,
            otc.exclusion_reason,
            otc.reason_codes
        FROM observation_tier_classifications otc
        WHERE otc.market_observation_id = mo.id
        ORDER BY otc.classified_at DESC, otc.id DESC
        LIMIT 1
    ) cls ON TRUE
    WHERE pr.id = %(run_id)s::uuid
) t
"""


def _repo_root() -> Path:
    return ROOT


def _fetch_rows_via_docker(run_id: str) -> list[dict[str, Any]]:
    sql = _EXPORT_SQL.replace("%(run_id)s", f"'{run_id}'")
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "marko",
            "-d",
            "marko",
            "-t",
            "-A",
            "-c",
            sql,
        ],
        cwd=_repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Read-only export failed talking to docker compose db:\n"
            f"{completed.stderr or completed.stdout}"
        )
    raw = completed.stdout.strip()
    if not raw or raw == "null":
        return []
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise SystemExit("psql did not return a JSON array of offers")
    return [row for row in payload if isinstance(row, dict)]


def _normalize_missing(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    return [str(value)]


def _rejection_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for key in (
        "semantic_gate_reason",
        "exclusion_reason",
        "cohort_role",
        "comparability_hard_gate_result",
    ):
        value = row.get(key)
        if value:
            reasons.append(str(value))
    for bucket in (
        row.get("classification_reason_codes"),
        row.get("calibration_exclusion_codes"),
    ):
        if isinstance(bucket, list):
            reasons.extend(str(item) for item in bucket if item)
        elif isinstance(bucket, str) and bucket.strip():
            try:
                parsed = json.loads(bucket)
            except json.JSONDecodeError:
                reasons.append(bucket)
            else:
                if isinstance(parsed, list):
                    reasons.extend(str(item) for item in parsed if item)
    return list(dict.fromkeys(reasons))


def _decorate(rows: list[dict[str, Any]], *, run_id: str) -> list[dict[str, Any]]:
    counts = Counter(str(row.get("sku") or "") for row in rows)
    decorated: list[dict[str, Any]] = []
    for row in rows:
        sku = str(row.get("sku") or "")
        offer_count = counts.get(sku, 0)
        decorated.append(
            {
                "pricing_run_id": run_id,
                "pricing_run_item_id": row.get("pricing_run_item_id"),
                "observation_id": row.get("observation_id"),
                "sku": sku,
                "catalog_name": row.get("catalog_name"),
                "oe_norm": row.get("oe_norm"),
                "identity_status": row.get("identity_status"),
                "our_price": row.get("our_price"),
                "listing_url": row.get("listing_url"),
                "seller_id": row.get("seller_id"),
                "seller_name": row.get("seller_name"),
                "price": row.get("price"),
                "currency": row.get("currency"),
                "title": row.get("title"),
                "condition_state": row.get("condition_state"),
                "condition_raw": row.get("condition_raw"),
                "cohort_role": row.get("cohort_role"),
                "semantic_gate_reason": row.get("semantic_gate_reason"),
                "semantic_gate_status": row.get("semantic_gate_status"),
                "comparability_hard_gate_result": row.get(
                    "comparability_hard_gate_result"
                ),
                "automatic_eligible": row.get("automatic_eligible"),
                "oe_verification_status": row.get("oe_verification_status"),
                "exclusion_reason": row.get("exclusion_reason"),
                "rejection_reasons": _rejection_reasons(row),
                "missing_pricing_dimensions": _normalize_missing(
                    row.get("missing_pricing_dimensions")
                ),
                "sku_offer_count": offer_count,
                "thick_position": offer_count >= THICK_MIN_OFFERS,
                "run_item_status": row.get("run_item_status"),
                "run_item_error": row.get("run_item_error"),
                "human_verdict": "",
                "human_note": "",
            }
        )
    return decorated


def _write_exports(
    rows: list[dict[str, Any]],
    *,
    json_path: Path,
    csv_path: Path,
    run_id: str,
) -> None:
    payload = {
        "schema_version": "canary-offer-labels-v1",
        "pricing_run_id": run_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "instructions": (
            "Fill human_verdict with yes / no / doubt: would you take this "
            "price as the price of a new complete part? human_note is optional."
        ),
        "rows": rows,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fieldnames = list(rows[0].keys()) if rows else [
        "observation_id",
        "sku",
        "listing_url",
        "human_verdict",
        "human_note",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            serialized = dict(row)
            for key, value in serialized.items():
                if isinstance(value, (list, dict)):
                    serialized[key] = json.dumps(value, ensure_ascii=False)
            writer.writerow(serialized)


def _load_labeled(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return [row for row in payload["rows"] if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    raise SystemExit(f"{path} is not a labeled canary export")


def _verdict_to_gold(verdict: str) -> tuple[str, str]:
    if verdict == "yes":
        return "comparable", "PASS"
    if verdict == "no":
        return "conflict", "REJECT"
    return "insufficient", "MANUAL_REVIEW"


def _safe_family(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() else "-" for character in value
    ).strip("-")
    return cleaned or "unspecified"


def build_gold_set(rows: list[dict[str, Any]], *, run_id: str) -> dict[str, Any]:
    labeled = [row for row in rows if str(row.get("human_verdict") or "").strip()]
    if not labeled:
        raise SystemExit(
            "No human_verdict values yet. The owner fills yes/no/doubt; "
            "then re-run with --to-gold-set."
        )
    cases: list[dict[str, Any]] = []
    for index, row in enumerate(labeled, start=1):
        verdict = str(row.get("human_verdict") or "").strip().lower()
        if verdict not in ALLOWED_VERDICTS:
            raise SystemExit(
                f"Invalid human_verdict {verdict!r} on "
                f"{row.get('observation_id')}: use yes / no / doubt"
            )
        gold_label, expected = _verdict_to_gold(verdict)
        observation_id = str(row.get("observation_id") or f"row-{index}")
        sku = str(row.get("sku") or "unknown")
        host = urlparse(str(row.get("listing_url") or "")).netloc or "prom.ua"
        cases.append(
            {
                "case_id": f"CANARY-{index:03d}-{observation_id[:8]}",
                "split": "test",
                "product_family": _safe_family(f"canary-sku-{sku}"),
                "oe_family": _safe_family(str(row.get("oe_norm") or sku)),
                "seller_family": _safe_family(
                    str(row.get("seller_id") or row.get("seller_name") or host)
                ),
                "observed_period": f"canary-{run_id[:8]}",
                "retrieval_kind": "sku",
                "category": str(row.get("catalog_name") or "parts")[:80] or "parts",
                "gold_label": gold_label,
                "expected_result": expected,
                "mutation": {"kind": "none"},
                "human_verdict": verdict,
                "human_note": row.get("human_note") or "",
                "observation_id": observation_id,
                "sku": sku,
                "listing_url": row.get("listing_url"),
                "price": row.get("price"),
                "rejection_reasons": row.get("rejection_reasons") or [],
                "missing_pricing_dimensions": row.get("missing_pricing_dimensions")
                or [],
            }
        )
    # Unique leakage keys per case: observed_period is shared, so make it
    # case-specific to satisfy the split-leakage contract.
    for case in cases:
        case["observed_period"] = f"canary-{run_id[:8]}-{case['case_id']}"
    return {
        "schema_version": "comparability-gold-set-v2",
        "dataset_id": f"canary-human-labels-{run_id[:8]}",
        "dataset_version": "1.0.0",
        "created_at": datetime.now(UTC).date().isoformat(),
        "data_class": "human_canary_labels",
        "representative": False,
        "approval": {
            "domain_policy_approved": False,
            "representative_labels_approved": False,
            "approved_by": None,
            "approved_at": None,
        },
        "release_policy": {
            "alpha": None,
            "epsilon": None,
            "loss_weights": None,
            "engineering_unsafe_auto_count_max": 0,
        },
        "split_contract": {
            "splits": ["train", "calibration", "test"],
            "leakage_keys": [
                "product_family",
                "oe_family",
                "seller_family",
                "observed_period",
            ],
        },
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--csv-out", type=Path, default=DEFAULT_CSV)
    parser.add_argument(
        "--to-gold-set",
        type=Path,
        help="Labeled JSON/CSV from this export. Writes a gold-set document.",
    )
    parser.add_argument(
        "--gold-out",
        type=Path,
        default=ROOT / "docs" / "canary_comparability_gold_set.json",
    )
    args = parser.parse_args()
    if args.to_gold_set is not None:
        labeled = _load_labeled(args.to_gold_set)
        payload = build_gold_set(labeled, run_id=args.run_id)
        args.gold_out.parent.mkdir(parents=True, exist_ok=True)
        args.gold_out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {len(payload['cases'])} gold-set cases to {args.gold_out}")
        return
    rows = _decorate(_fetch_rows_via_docker(args.run_id), run_id=args.run_id)
    _write_exports(
        rows,
        json_path=args.json_out,
        csv_path=args.csv_out,
        run_id=args.run_id,
    )
    thick = sum(1 for row in rows if row["thick_position"])
    print(
        f"Exported {len(rows)} offers "
        f"({thick} on positions with >={THICK_MIN_OFFERS} offers) "
        f"to {args.json_out} and {args.csv_out}"
    )


if __name__ == "__main__":
    main()
