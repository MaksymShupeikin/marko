"""CLI for the deterministic catalog candidate histogram and coverage report."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from marko.infrastructure.db.session import async_session_factory
from marko.services.catalog_candidate_report import (
    CandidateReportError,
    format_candidate_selection_report,
    load_candidate_selection_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catalog-candidate-report",
        description="Print deterministic candidate verdicts for one discovery run",
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--run-id", type=UUID)
    selector.add_argument("--query")
    parser.add_argument("--workspace-id", type=UUID, required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


async def _run(args: argparse.Namespace) -> int:
    async with async_session_factory() as session:
        report = await load_candidate_selection_report(
            session,
            workspace_id=args.workspace_id,
            run_id=args.run_id,
            query=args.query,
        )
    if args.as_json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_candidate_selection_report(report))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except CandidateReportError as exc:
        print(f"Ошибка: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
