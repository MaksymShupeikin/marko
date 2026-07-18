#!/usr/bin/env python3
"""Strict production preflight CLI; diagnostics never contain config values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from marko.governance.production_preflight import (  # noqa: E402
    render_human,
    render_json,
    run_preflight,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument(
        "--mode", required=True, choices=("static", "connectivity", "full")
    )
    parser.add_argument(
        "--format", dest="output_format", choices=("human", "json"), default="human"
    )
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--e2e-evidence", type=Path)
    parser.add_argument("--connectivity-timeout", type=float, default=3.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.connectivity_timeout <= 0 or args.connectivity_timeout > 30:
        sys.stderr.write("PREFLIGHT_TOOL_ERROR=INVALID_CONNECTIVITY_TIMEOUT\n")
        return 3
    try:
        result = run_preflight(
            args.env_file,
            mode=args.mode,
            e2e_evidence=args.e2e_evidence,
            connectivity_timeout=args.connectivity_timeout,
        )
        json_output = render_json(result)
        if args.output_json:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(json_output, encoding="utf-8")
        sys.stdout.write(
            json_output if args.output_format == "json" else render_human(result)
        )
        return 0 if result.passed else 2
    except Exception as exc:
        # Only the exception type is safe. Exception text may contain a DSN.
        diagnostic = {
            "schema_version": "1.0.0",
            "passed": False,
            "tool_error": type(exc).__name__,
            "secrets_emitted": False,
        }
        sys.stderr.write(json.dumps(diagnostic, sort_keys=True) + "\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
