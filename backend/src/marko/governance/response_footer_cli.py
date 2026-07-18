"""CLI for validating and rendering Section 15 response footers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from pydantic import ValidationError
import yaml

from .response_footer import (
    EndOfResponse,
    build_self_check,
    render_footer,
    validate_contract,
    validate_rendered_footer,
)


def _load_manifest(path: Path) -> EndOfResponse:
    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "end_of_response" not in payload:
        raise ValueError("manifest root must contain end_of_response")
    return EndOfResponse.model_validate(payload["end_of_response"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate or render the Marko+Metis Section 15 response footer."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--footer",
        type=Path,
        help="Full response or rendered footer to validate against the manifest.",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--render",
        action="store_true",
        help="Render the canonical human-readable footer to stdout.",
    )
    output_group.add_argument(
        "--self-check",
        action="store_true",
        help="Emit the executable Section 15.53 self-check as JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        contract = _load_manifest(args.manifest)
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        print(f"MANIFEST_INVALID: {exc}", file=sys.stderr)
        return 2

    issues = []
    if args.footer is not None:
        try:
            response = args.footer.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"FOOTER_READ_FAILED: {exc}", file=sys.stderr)
            return 2
        issues.extend(validate_rendered_footer(response, expected_contract=contract))
    else:
        issues.extend(validate_contract(contract))

    if issues:
        for issue in issues:
            print(f"{issue.code} [{issue.path}]: {issue.message}", file=sys.stderr)
        return 1

    if args.render:
        print(render_footer(contract))
    elif args.self_check:
        print(
            json.dumps(
                {"end_of_response_self_check": build_self_check(contract)},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print("END_OF_RESPONSE_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
