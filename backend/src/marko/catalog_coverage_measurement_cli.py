"""CLI for the resumable Gate 1 coverage re-measurement.

``collect`` performs live work and may be interrupted at any point; ``report``
touches no network and recomputes every number from persisted evidence, so the
same checkpoint can be re-reported without re-scraping.
"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
import json
from pathlib import Path
import sys
from uuid import UUID

from marko.core.config import get_settings
from marko.infrastructure.db.session import async_session_factory
from marko.services.catalog_coverage_measurement import (
    COHORT_BASELINE,
    COHORT_IDENTITY,
    COHORT_ORDER,
    COHORT_PLAN_S,
    CoverageMeasurementError,
    CoverageReport,
    MeasurementCheckpoint,
    build_batch_identity,
    build_coverage_report,
    load_coverage_targets,
    run_coverage_batch,
)
from marko.services.catalog_discovery import (
    optional_backend_path,
    resolve_backend_path,
)
from metis.pricing import (
    load_approved_brand_rules,
    load_candidate_selection_config,
)


_COHORT_TITLES = {
    COHORT_BASELINE: "A. baseline_exact_article (сопоставимо с 2026-07-19)",
    COHORT_IDENTITY: "B. identity_any_evidence (discovery upper bound)",
    COHORT_PLAN_S: "C. plan_s_set (§2.3, требует COMPARABLE)",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catalog-coverage-measurement",
        description="Resumable coverage re-measurement over a frozen target list",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser(
        "collect",
        help="Run pending targets live, appending one checkpoint line each",
    )
    collect.add_argument("--targets", required=True, type=Path)
    collect.add_argument("--checkpoint", required=True, type=Path)
    collect.add_argument("--workspace-id", required=True, type=UUID)
    collect.add_argument(
        "--target-delay-seconds",
        type=float,
        default=None,
        help="Pause between targets; defaults to the scraper request delay",
    )
    collect.add_argument(
        "--no-retry-failed",
        action="store_true",
        help="Leave previously failed targets alone instead of retrying them",
    )
    collect.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after this many pending targets (for a bounded first probe)",
    )

    report = subparsers.add_parser(
        "report",
        help="Recompute cohorts, metrics and anti-bot telemetry from the database",
    )
    report.add_argument("--targets", required=True, type=Path)
    report.add_argument("--checkpoint", required=True, type=Path)
    report.add_argument("--workspace-id", required=True, type=UUID)
    report.add_argument("--json", action="store_true", dest="as_json")
    report.add_argument("--json-out", type=Path, default=None)
    report.add_argument(
        "--no-body-scan",
        action="store_true",
        help="Skip decompressing raw bodies for captcha/blocking markers",
    )
    return parser


def _identity_for(args: argparse.Namespace):
    settings = get_settings()
    targets = load_coverage_targets(args.targets)
    selection_config = load_candidate_selection_config(
        resolve_backend_path(settings.pricing_candidate_selection_path)
    )
    brand_rules = load_approved_brand_rules(
        optional_backend_path(settings.pricing_brand_tiers_path)
    )
    identity = build_batch_identity(
        targets=targets,
        workspace_id=args.workspace_id,
        settings=settings,
        selection_config_sha256=selection_config.source_sha256,
        brand_rules_dataset_id=brand_rules.dataset_id,
    )
    return settings, targets, identity


async def _collect(args: argparse.Namespace) -> int:
    settings, targets, identity = _identity_for(args)
    checkpoint = MeasurementCheckpoint.open(args.checkpoint, identity)
    delay = (
        args.target_delay_seconds
        if args.target_delay_seconds is not None
        else settings.pricing_scraper_request_delay_seconds
    )
    progress = await run_coverage_batch(
        async_session_factory,
        targets=targets,
        checkpoint=checkpoint,
        workspace_id=args.workspace_id,
        settings=settings,
        retry_failed=not args.no_retry_failed,
        target_delay_seconds=delay,
        limit=args.limit,
        sleep=asyncio.sleep,
        progress=lambda message: print(message, flush=True),
    )
    print(
        f"\nИтог: обработано {progress.attempted}, успешно {progress.completed}, "
        f"ошибок {progress.failed}, пропущено {progress.skipped}, "
        f"время {progress.elapsed_seconds} с."
    )
    return 0 if progress.failed == 0 else 1


async def _report(args: argparse.Namespace) -> int:
    _settings, targets, identity = _identity_for(args)
    checkpoint = MeasurementCheckpoint.open(args.checkpoint, identity)
    async with async_session_factory() as session:
        report = await build_coverage_report(
            session,
            targets=targets,
            checkpoint=checkpoint,
            scan_bodies=not args.no_body_scan,
        )
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.as_json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_coverage_report(report))
    return report_exit_code(report)


def report_exit_code(report: CoverageReport) -> int:
    """Make an incomplete checkpoint fail automation even after emitting output."""

    return 1 if report.failed_rows else 0


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def format_coverage_report(report: CoverageReport) -> str:
    lines: list[str] = []
    lines.append("ЗАМЕР ПОКРЫТИЯ — ГЕЙТ 1")
    lines.append(f"цели:      {report.targets_path}")
    lines.append(f"sha256:    {report.targets_sha256}")
    lines.append(f"чекпоинт:  {report.checkpoint_path}")
    lines.append(
        f"лимит страниц: {report.identity.search_page_limit}   "
        f"задержка: {report.identity.request_delay_seconds} с "
        f"(±{report.identity.request_jitter_seconds})   "
        f"попыток HTTP: {report.identity.http_max_attempts}"
    )
    lines.append(
        f"позиций измерено: {len(report.target_rows)}   "
        f"не измерено: {len(report.failed_rows)}"
    )

    lines.append("")
    lines.append("КОГОРТЫ (n на позицию, продавцы дедуплицированы)")
    header = (
        f"{'когорта':<52}{'mean':>9}{'median':>9}"
        f"{'share_ge3':>11}{'share_zero':>12}{'сумма':>8}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    if report.baseline_metrics is not None:
        base = report.baseline_metrics
        lines.append(
            f"{'было 2026-07-19 (та же когорта A)':<52}"
            f"{_fmt(base.mean):>9}{_fmt(base.median):>9}"
            f"{_fmt(base.share_ge3):>11}{_fmt(base.share_zero):>12}"
            f"{base.total:>8}"
        )
    for cohort in COHORT_ORDER:
        metrics = report.cohort_metrics[cohort]
        lines.append(
            f"{_COHORT_TITLES[cohort]:<52}"
            f"{_fmt(metrics.mean):>9}{_fmt(metrics.median):>9}"
            f"{_fmt(metrics.share_ge3):>11}{_fmt(metrics.share_zero):>12}"
            f"{metrics.total:>8}"
        )

    lines.append("")
    lines.append("РАСПРЕДЕЛЕНИЕ n ПО ПОЗИЦИЯМ")
    dist_header = f"{'когорта':<52}{'0':>6}{'1-2':>7}{'3-4':>7}{'5+':>7}"
    lines.append(dist_header)
    lines.append("-" * len(dist_header))
    if report.baseline_metrics is not None:
        dist = report.baseline_metrics.distribution
        lines.append(
            f"{'было 2026-07-19 (та же когорта A)':<52}"
            f"{dist['0']:>6}{dist['1-2']:>7}{dist['3-4']:>7}{dist['5+']:>7}"
        )
    for cohort in COHORT_ORDER:
        dist = report.cohort_metrics[cohort].distribution
        lines.append(
            f"{_COHORT_TITLES[cohort]:<52}"
            f"{dist['0']:>6}{dist['1-2']:>7}{dist['3-4']:>7}{dist['5+']:>7}"
        )

    coverage = report.retrieval_coverage
    lines.append("")
    lines.append("ПОКРЫТИЕ ВЫДАЧИ PROM")
    lines.append(
        f"извлечено {coverage['retrieved_total']} из "
        f"{coverage['prom_reported_total']} заявленных  →  "
        f"{_fmt(coverage['ratio'])}"
    )
    lines.append(
        f"позиций без заявленного total: {coverage['runs_with_unknown_total']}"
    )
    for reason, count in coverage["reason_histogram"].items():
        lines.append(f"  {reason}: {count}")

    telemetry = report.telemetry
    lines.append("")
    lines.append("АНТИБОТ / ЗАПРОСЫ")
    lines.append(f"HTTP-запросов: {telemetry.request_count}")
    lines.append(
        "коды: "
        + (
            ", ".join(
                f"{code}×{count}" for code, count in telemetry.status_histogram.items()
            )
            or "—"
        )
    )
    lines.append(
        f"с повторными попытками: {telemetry.retried_request_count}   "
        f"попыток всего: {telemetry.attempts_total}"
    )
    lines.append(
        f"латентность мс: p50 {_fmt(telemetry.latency_p50_ms)}   "
        f"p95 {_fmt(telemetry.latency_p95_ms)}   "
        f"max {_fmt(telemetry.latency_max_ms)}"
    )
    lines.append(
        f"тел разобрано парсером: {telemetry.scanned_blob_count}   "
        f"страниц без товаров: {telemetry.pages_without_products}   "
        f"подозрений на блокировку: {telemetry.suspected_block_count}"
    )
    lines.append(
        "маркеры блокировки (только на страницах без товаров): "
        + (
            ", ".join(
                f"{marker}×{count}"
                for marker, count in telemetry.blocking_marker_hits.items()
            )
            if telemetry.blocking_marker_hits
            else "нет"
        )
    )

    availability = report.availability
    lines.append("")
    lines.append(
        f"наличие: в наличии {availability['available']}, "
        f"нет {availability['unavailable']}, неизвестно {availability['unknown']}"
    )

    if report.failed_rows:
        lines.append("")
        lines.append("НЕ ИЗМЕРЕНО")
        for row in report.failed_rows:
            lines.append(f"  #{row.sample_no} {row.oe_norm}: {row.status}")

    lines.append("")
    lines.append("ПО ПОЗИЦИЯМ")
    per_header = (
        f"{'#':>3} {'категория':<16}{'OE':<16}"
        f"{'было':>6}{'A':>4}{'B':>4}{'C':>4}"
        f"{'извл.':>7}{'total':>7}{'стр.':>6}{'покрытие':>11}  причина"
    )
    lines.append(per_header)
    lines.append("-" * len(per_header))
    for row in report.target_rows:
        lines.append(
            f"{row.sample_no:>3} {row.category:<16}{row.oe_norm:<16}"
            f"{_fmt(row.baseline_after_filter):>6}"
            f"{row.counts[COHORT_BASELINE]:>4}"
            f"{row.counts[COHORT_IDENTITY]:>4}"
            f"{row.counts[COHORT_PLAN_S]:>4}"
            f"{row.retrieved_count:>7}"
            f"{_fmt(row.prom_reported_total):>7}"
            f"{row.request_count:>6}"
            f"{_fmt(row.coverage_ratio):>11}  {row.coverage_reason or '—'}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handler = _collect if args.command == "collect" else _report
    try:
        return asyncio.run(handler(args))
    except CoverageMeasurementError as exc:
        print(f"Ошибка [{exc.code}]: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
