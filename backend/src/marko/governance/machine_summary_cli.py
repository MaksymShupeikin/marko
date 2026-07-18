"""CLI for Section 16 machine-readable summary validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from pydantic import ValidationError
import yaml

from .machine_summary import (
    MachineSummaryParseError,
    build_machine_self_check,
    parse_machine_summary_yaml,
    render_machine_summary_block,
    validate_machine_response,
    validate_summary,
)
from .machine_summary_models import MachineReadableSummary
from .response_footer import EndOfResponse


def _load_summary(path: Path) -> MachineReadableSummary:
    return parse_machine_summary_yaml(path.read_text(encoding="utf-8"))


def _load_footer(path: Path) -> EndOfResponse:
    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "end_of_response" not in payload:
        raise ValueError("footer manifest root must contain end_of_response")
    return EndOfResponse.model_validate(payload["end_of_response"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate or render the Marko+Metis Section 16 summary."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--response",
        type=Path,
        help="Complete response containing Section 15 and the final YAML block.",
    )
    parser.add_argument(
        "--footer-manifest",
        type=Path,
        help="Optional Section 15 manifest for exact human-footer comparison.",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--render",
        action="store_true",
        help="Render MACHINE_READABLE_SUMMARY and its fenced YAML document.",
    )
    output_group.add_argument(
        "--self-check",
        action="store_true",
        help="Emit the executable Section 16 self-review as JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = _load_summary(args.manifest)
        footer = _load_footer(args.footer_manifest) if args.footer_manifest else None
    except (
        OSError,
        ValueError,
        ValidationError,
        yaml.YAMLError,
        MachineSummaryParseError,
    ) as exc:
        print(f"MANIFEST_INVALID: {exc}", file=sys.stderr)
        return 2

    issues = list(validate_summary(summary))
    response_text: str | None = None
    if args.response is not None:
        try:
            response_text = args.response.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"RESPONSE_READ_FAILED: {exc}", file=sys.stderr)
            return 2
        issues = list(
            validate_machine_response(
                response_text,
                expected_summary=summary,
                expected_footer=footer,
            )
        )

    if issues:
        for issue in issues:
            print(f"{issue.code} [{issue.path}]: {issue.message}", file=sys.stderr)
        return 1

    if args.render:
        print(render_machine_summary_block(summary))
    elif args.self_check:
        print(
            json.dumps(
                {
                    "machine_readable_summary_self_check": build_machine_self_check(
                        summary,
                        response=response_text,
                    )
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print("MACHINE_READABLE_SUMMARY_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
