#!/usr/bin/env python3
"""Evaluate controlled scraper benchmark JSON without running external load."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

backend_src = Path(__file__).resolve().parent.parent / "backend" / "src"
if str(backend_src) not in sys.path:
    sys.path.insert(0, str(backend_src))

from marko.services.scraper_benchmark import (  # noqa: E402
    BenchmarkAcceptance,
    BenchmarkRun,
    evaluate_benchmark_series,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    decision = evaluate_benchmark_series(
        [BenchmarkRun(**value) for value in payload["runs"]],
        BenchmarkAcceptance(**payload["acceptance"]),
    )
    rendered = json.dumps(
        decision.as_dict(),
        indent=2,
        ensure_ascii=False,
    )
    if args.output is None:
        sys.stdout.write(rendered + "\n")
    else:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if decision.production_capacity_proven else 2


if __name__ == "__main__":
    raise SystemExit(main())
