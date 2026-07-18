#!/usr/bin/env python3
"""Validate the versioned comparability engineering gold set and release gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from metis.pricing.gold_set import evaluate_gold_set, load_gold_set  # noqa: E402


DEFAULT_DATASET = ROOT / "backend/tests/fixtures/comparability_gold_set_v1.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate_gold_set(load_gold_set(args.dataset))
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if report["engineering_gate"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
