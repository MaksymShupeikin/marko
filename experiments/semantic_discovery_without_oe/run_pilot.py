#!/usr/bin/env python3
"""Run a bounded semantic-discovery pilot for KEMP rows without confirmed OE."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping

from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import RequestFailed
from marko.services.scrape_runtime import ScrapeExecutionTrace, scrape_execution
from marko.services.source_access import (
    SourceAccessBlocked,
    source_access_status,
)

from semantic_discovery import (
    CONTRACT_VERSION,
    DEFAULT_OWNED_SELLER_IDS,
    LUNA_PROMPT_VERSION,
    LUNA_SCHEMA_VERSION,
    MAX_DETAIL_CARDS_PER_QUERY,
    MAX_LUNA_PAIRS_PER_RUN,
    MAX_QUERIES_PER_SEED,
    MAX_SEEDS_PER_RUN,
    DeterministicDisposition,
    LunaSemanticOutput,
    assess_candidate,
    bound_luna_output_schema,
    build_luna_prompt,
    build_luna_snapshot,
    build_query_plan,
    build_seed_profile,
    candidate_image_urls,
    canonical_json,
    collect_prom_candidates,
    freeze_image,
    load_no_oe_catalog_seeds,
    map_luna_result_to_review_status,
    non_monetary_product,
    persist_http_trace,
    product_identity,
    sha256_file,
    strict_luna_output_schema,
    validate_luna_evidence_against_snapshot,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MASTER = REPO_ROOT.parent / "OE_каталог_2026-08-09.xlsx"
DEFAULT_SOURCE = REPO_ROOT / "backend/data/kemp_prom_catalog.xlsx"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-workbook", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--source-workbook", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--row-id", action="append", default=[])
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Perform bounded live Prom search/detail requests.",
    )
    parser.add_argument(
        "--run-luna",
        action="store_true",
        help="Run gpt-5.6-luna/xhigh through the local Codex CLI.",
    )
    parser.add_argument("--queries-per-seed", type=int, default=1)
    parser.add_argument("--max-search-pages", type=int, default=1)
    parser.add_argument("--max-detail-cards", type=int, default=3)
    parser.add_argument("--max-luna-pairs", type=int, default=1)
    parser.add_argument(
        "--luna-repair-attempts",
        type=int,
        default=1,
        help="At most one schema/evidence repair call after an invalid Luna JSON.",
    )
    parser.add_argument("--lang", default="ua")
    parser.add_argument("--delay", type=float, default=0.75)
    parser.add_argument("--delay-jitter", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--luna-timeout", type=int, default=900)
    return parser


def _validate_args(args: argparse.Namespace) -> int:
    limit = args.limit if args.limit is not None else (len(args.row_id) or 1)
    if not 1 <= limit <= MAX_SEEDS_PER_RUN:
        raise ValueError(f"--limit must be between 1 and {MAX_SEEDS_PER_RUN}")
    if not 1 <= args.queries_per_seed <= MAX_QUERIES_PER_SEED:
        raise ValueError(
            f"--queries-per-seed must be between 1 and {MAX_QUERIES_PER_SEED}"
        )
    if not 1 <= args.max_search_pages <= 2:
        raise ValueError("--max-search-pages must be 1 or 2")
    if not 1 <= args.max_detail_cards <= MAX_DETAIL_CARDS_PER_QUERY:
        raise ValueError(
            f"--max-detail-cards must be between 1 and {MAX_DETAIL_CARDS_PER_QUERY}"
        )
    if not 1 <= args.max_luna_pairs <= MAX_LUNA_PAIRS_PER_RUN:
        raise ValueError(
            f"--max-luna-pairs must be between 1 and {MAX_LUNA_PAIRS_PER_RUN}"
        )
    if args.luna_repair_attempts not in {0, 1}:
        raise ValueError("--luna-repair-attempts must be 0 or 1")
    if args.run_luna and not args.live:
        raise ValueError("--run-luna requires --live so candidate evidence can be frozen")
    if args.max_attempts not in {1, 2}:
        raise ValueError("--max-attempts must be 1 or 2 for this bounded experiment")
    if args.delay < 0.5:
        raise ValueError("--delay must be at least 0.5 seconds")
    if not args.master_workbook.is_file():
        raise FileNotFoundError(args.master_workbook)
    if not args.source_workbook.is_file():
        raise FileNotFoundError(args.source_workbook)
    return limit


def _output_dir(args: argparse.Namespace) -> Path:
    if args.output_dir is not None:
        target = args.output_dir.resolve()
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = REPO_ROOT / ".artifacts" / f"semantic_discovery_without_oe_{stamp}"
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty output directory: {target}")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(canonical_json(row) + "\n")


def _safe_fragment(value: object) -> str:
    rendered = "".join(character if character.isalnum() else "_" for character in str(value))
    return rendered.strip("_")[:80] or "unknown"


def _blocked_error(exc: BaseException) -> bool:
    if isinstance(exc, SourceAccessBlocked):
        return True
    if isinstance(exc, RequestFailed) and exc.status_code in {403, 429}:
        return True
    text = str(exc).casefold()
    return any(marker in text for marker in ("captcha", "challenge", "rate limit"))


def _run_luna(
    *,
    codex_bin: str,
    snapshot: Mapping[str, Any],
    image_paths: list[Path],
    pair_dir: Path,
    schema_path: Path,
    timeout: int,
    repair_feedback: str | None = None,
    previous_output: str | None = None,
) -> tuple[LunaSemanticOutput | None, dict[str, Any]]:
    pair_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = pair_dir / "input_snapshot.json"
    prompt_path = pair_dir / "prompt.txt"
    output_path = pair_dir / "model_output.json"
    stdout_path = pair_dir / "codex_stdout.txt"
    stderr_path = pair_dir / "codex_stderr.txt"
    _write_json(snapshot_path, snapshot)
    bound_schema_path = pair_dir / "bound_output_schema.json"
    _write_json(bound_schema_path, bound_luna_output_schema(snapshot))
    prompt = build_luna_prompt(snapshot)
    if repair_feedback is not None:
        prompt += (
            "\n\nVALIDATION_REPAIR\n"
            "A previous draft failed the server-side evidence validator. "
            "Return the complete corrected JSON, not a patch. Do not change "
            "a product fact merely to satisfy validation. Use only exact "
            "evidence_id values from PRODUCT_DATA.evidence_catalog. Do not "
            "invent or rewrite an evidence ID.\n"
            f"VALIDATION_ERROR\n{repair_feedback}\n"
            "PREVIOUS_DRAFT_UNTRUSTED\n"
            f"{previous_output or '<unavailable>'}"
        )
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    command = [
        codex_bin,
        "exec",
        "-m",
        "gpt-5.6-luna",
        "-c",
        'model_reasoning_effort="xhigh"',
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "--output-schema",
        str(bound_schema_path),
        "-o",
        str(output_path),
        "-C",
        str(REPO_ROOT),
    ]
    for path in image_paths:
        command.extend(("--image", str(path)))
    command.append("-")

    environment = dict(os.environ)
    environment.pop("OPENAI_API_KEY", None)
    started = datetime.now(UTC)
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout or "", encoding="utf-8")
        stderr_path.write_text(exc.stderr or "", encoding="utf-8")
        return None, {
            "status": "TIMEOUT",
            "command": command,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "timeout_seconds": timeout,
        }
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    metadata = {
        "status": "CLI_FINISHED" if completed.returncode == 0 else "CLI_FAILED",
        "returncode": completed.returncode,
        "command": command,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "model": "gpt-5.6-luna",
        "reasoning_effort": "xhigh",
        "sandbox": "read-only",
        "ephemeral": True,
        "openai_api_key_forwarded": False,
        "image_paths": [str(path) for path in image_paths],
        "repair_call": repair_feedback is not None,
        "output_path": str(output_path),
        "base_schema_path": str(schema_path),
        "bound_schema_path": str(bound_schema_path),
        "bound_schema_sha256": sha256_file(bound_schema_path),
    }
    if completed.returncode != 0 or not output_path.is_file():
        return None, metadata
    try:
        output = LunaSemanticOutput.model_validate_json(
            output_path.read_text(encoding="utf-8")
        )
        validate_luna_evidence_against_snapshot(output, snapshot)
    except Exception as exc:  # Pydantic supplies the detailed validation error.
        metadata["status"] = "INVALID_MODEL_OUTPUT"
        metadata["validation_error"] = str(exc)
        return None, metadata
    metadata["status"] = "VALID"
    metadata["output_sha256"] = sha256_file(output_path)
    return output, metadata


def _artifact_manifest(root: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "artifact_manifest.json":
            continue
        result.append(
            {
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return result


def _report(summary: Mapping[str, Any], *, output_dir: Path) -> str:
    luna_counts = summary.get("luna_verdicts", {})
    return f"""# Пилот semantic discovery без OE

Статус: `{summary['run_status']}`

Контракт: `{CONTRACT_VERSION}`

Артефакты: `{output_dir}`

## Что фактически выполнено

- Выбрано позиций без подтверждённого OE: {summary['selected_seeds']}.
- Спланировано/выполнено Prom-запросов: {summary['queries_planned']}/{summary['queries_executed']}.
- Уникальных карточек-кандидатов: {summary['unique_candidates']}.
- Исключено своих KEMP-продавцов: {summary['owned_seller_excluded']}.
- Отклонено по явному семантическому конфликту: {summary['deterministic_not_match']}.
- Передано/допущено к Luna: {summary['luna_attempted']}/{summary['semantic_needs_luna']}.
- Физических Luna CLI calls (включая repair): {summary['luna_cli_calls']}.
- Валидных ответов Luna: {summary['luna_valid']}.
- Вердикты Luna: `{json.dumps(luna_counts, ensure_ascii=False, sort_keys=True)}`.

## Граница интерпретации

`MATCH` от Luna здесь преобразуется только в
`SEMANTIC_MATCH_CANDIDATE_MANUAL_REVIEW`. Он не создаёт OE, не сливает
товары, не записывает цену и не даёт автоматический pricing admission.
Сырые Prom-страницы могут содержать цены как часть оригинального HTML,
но в структурированные кандидаты и вход Luna ценовые поля не передаются.

## Чего это не доказывает

Пилот не измеряет representative-market precision/recall на всех 1 617
неразрешённых позициях. Для этого нужна ручная разметка стратифицированной
выборки по категориям и отдельный stop-gate по false accepts.
"""


def main() -> int:
    args = _parser().parse_args()
    limit = _validate_args(args)
    output_dir = _output_dir(args)
    started = datetime.now(UTC)
    access = source_access_status().as_dict()
    if args.live and access["live_collection_allowed"] is not True:
        raise SourceAccessBlocked(source_access_status())

    seeds, catalog_counts = load_no_oe_catalog_seeds(
        args.master_workbook,
        args.source_workbook,
        row_ids=args.row_id,
        offset=args.offset,
        limit=limit,
    )
    profiles = [build_seed_profile(seed) for seed in seeds]
    plans = [build_query_plan(seed, profile) for seed, profile in zip(seeds, profiles)]
    _write_jsonl(output_dir / "seed_profiles.jsonl", profiles)
    _write_jsonl(output_dir / "query_plan.jsonl", plans)

    raw_manifest: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    verdict_rows: list[dict[str, Any]] = []
    collection_errors: list[dict[str, Any]] = []
    queries_executed = 0
    stop_live = False

    config = ScrapeConfig(
        delay=args.delay,
        delay_jitter=args.delay_jitter,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
        max_search_pages=args.max_search_pages,
        max_detail_cards=args.max_detail_cards,
        # The experimental collector never invokes the OE page, but keep the
        # general config bounded if that implementation boundary changes.
        max_oe_page_pages=1,
    )

    if args.live:
        execution_no = 0
        for seed, plan in zip(seeds, plans):
            found: dict[str, dict[str, Any]] = {}
            for query_no, query_item in enumerate(
                plan["queries"][: args.queries_per_seed], start=1
            ):
                if stop_live:
                    break
                execution_no += 1
                queries_executed += 1
                trace = ScrapeExecutionTrace(
                    item_kind="semantic_discovery_without_oe",
                    item_version=CONTRACT_VERSION,
                    execution_no=execution_no,
                )
                error: BaseException | None = None
                products = []
                try:
                    with scrape_execution(trace):
                        products = collect_prom_candidates(
                            seed,
                            query_item["query"],
                            config=config,
                            lang=args.lang,
                            owned_seller_ids=DEFAULT_OWNED_SELLER_IDS,
                        )
                except BaseException as exc:  # Persist the trace before deciding.
                    error = exc
                finally:
                    prefix = (
                        f"seed_{_safe_fragment(seed.row_id)}_q{query_no:02d}"
                    )
                    raw_manifest.extend(
                        {
                            "row_id": seed.row_id,
                            "query_no": query_no,
                            "query": query_item["query"],
                            **row,
                        }
                        for row in persist_http_trace(
                            trace.drain_completed_requests(),
                            raw_dir=output_dir / "raw_pages",
                            prefix=prefix,
                        )
                    )
                    trace.close()
                if error is not None:
                    collection_errors.append(
                        {
                            "row_id": seed.row_id,
                            "query_no": query_no,
                            "query": query_item["query"],
                            "error_type": type(error).__name__,
                            "error": str(error),
                            "stop_live": _blocked_error(error),
                        }
                    )
                    if _blocked_error(error):
                        stop_live = True
                    continue
                for product in products:
                    key = product_identity(product)
                    payload = non_monetary_product(product)
                    current = found.get(key)
                    row = {
                        "row_id": seed.row_id,
                        "candidate_key": key,
                        "found_by_queries": [query_item["query"]],
                        "candidate": payload,
                    }
                    if current is None:
                        found[key] = row
                    else:
                        current["found_by_queries"].append(query_item["query"])

            for item in found.values():
                assessment = assess_candidate(
                    seed,
                    item["candidate"],
                    owned_seller_ids=DEFAULT_OWNED_SELLER_IDS,
                )
                candidate_rows.append(item)
                verdict_rows.append(
                    {
                        "row_id": seed.row_id,
                        "candidate_key": item["candidate_key"],
                        "candidate_id": item["candidate"].get("id"),
                        "candidate_name": item["candidate"].get("name"),
                        "candidate_url": item["candidate"].get("url"),
                        "seller_id": item["candidate"].get("seller_id"),
                        "found_by_queries": item["found_by_queries"],
                        "assessment": assessment.as_dict(),
                    }
                )

    _write_jsonl(output_dir / "raw_http_manifest.jsonl", raw_manifest)
    _write_jsonl(output_dir / "candidates_non_monetary.jsonl", candidate_rows)
    _write_jsonl(output_dir / "deterministic_verdicts.jsonl", verdict_rows)
    _write_json(output_dir / "collection_errors.json", collection_errors)

    schema_path = output_dir / "luna/output_schema.json"
    _write_json(schema_path, strict_luna_output_schema())
    image_manifest: list[dict[str, Any]] = []
    luna_predictions: list[dict[str, Any]] = []
    luna_attempted = 0
    luna_cli_calls = 0

    if args.run_luna and not stop_live:
        seed_by_id = {seed.row_id: seed for seed in seeds}
        candidate_by_key = {
            (row["row_id"], row["candidate_key"]): row["candidate"]
            for row in candidate_rows
        }
        eligible = sorted(
            (
                row
                for row in verdict_rows
                if row["assessment"]["disposition"]
                == DeterministicDisposition.SEMANTIC_NEEDS_LUNA.value
            ),
            key=lambda row: (-row["assessment"]["retrieval_score"], row["candidate_key"]),
        )[: args.max_luna_pairs]
        for pair_no, row in enumerate(eligible, start=1):
            luna_attempted += 1
            seed = seed_by_id[row["row_id"]]
            candidate = candidate_by_key[(row["row_id"], row["candidate_key"])]
            assessment = assess_candidate(
                seed,
                candidate,
                owned_seller_ids=DEFAULT_OWNED_SELLER_IDS,
            )
            pair_images: list[dict[str, Any]] = []
            image_errors: list[dict[str, str]] = []
            for role, urls in (
                ("OUR_PRODUCT", seed.image_urls[:1]),
                ("CANDIDATE", candidate_image_urls(candidate)[:1]),
            ):
                for ordinal, url in enumerate(urls, start=1):
                    try:
                        frozen = freeze_image(
                            url,
                            role=role,
                            output_dir=output_dir / "images",
                            ordinal=pair_no * 10 + ordinal,
                            timeout=args.timeout,
                        )
                        pair_images.append(frozen)
                        image_manifest.append(
                            {
                                "row_id": seed.row_id,
                                "candidate_key": row["candidate_key"],
                                **frozen,
                            }
                        )
                    except Exception as exc:
                        image_errors.append(
                            {
                                "role": role,
                                "url": url,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )
            snapshot = build_luna_snapshot(
                seed,
                candidate,
                assessment,
                image_manifest=pair_images,
            )
            pair_dir = output_dir / "luna/pairs" / (
                f"{pair_no:02d}_{_safe_fragment(seed.row_id)}_"
                f"{_safe_fragment(row['candidate_key'])}"
            )
            output, first_metadata = _run_luna(
                codex_bin=args.codex_bin,
                snapshot=snapshot,
                image_paths=[Path(item["local_path"]) for item in pair_images],
                pair_dir=pair_dir / "attempt_01",
                schema_path=schema_path,
                timeout=args.luna_timeout,
            )
            luna_cli_calls += 1
            attempts = [first_metadata]
            metadata = first_metadata
            if (
                output is None
                and first_metadata.get("status") == "INVALID_MODEL_OUTPUT"
                and args.luna_repair_attempts == 1
            ):
                previous_path = Path(str(first_metadata.get("output_path") or ""))
                previous_output = (
                    previous_path.read_text(encoding="utf-8")
                    if previous_path.is_file()
                    else None
                )
                output, repair_metadata = _run_luna(
                    codex_bin=args.codex_bin,
                    snapshot=snapshot,
                    image_paths=[Path(item["local_path"]) for item in pair_images],
                    pair_dir=pair_dir / "attempt_02_repair",
                    schema_path=schema_path,
                    timeout=args.luna_timeout,
                    repair_feedback=str(first_metadata.get("validation_error") or ""),
                    previous_output=previous_output,
                )
                luna_cli_calls += 1
                attempts.append(repair_metadata)
                metadata = repair_metadata
            metadata = {
                **metadata,
                "attempt_count": len(attempts),
                "repair_used": len(attempts) > 1,
                "attempts": attempts,
            }
            prediction = {
                "row_id": seed.row_id,
                "candidate_key": row["candidate_key"],
                "candidate_id": candidate.get("id"),
                "candidate_name": candidate.get("name"),
                "image_errors": image_errors,
                "runner": metadata,
                "validated_output": output.model_dump(mode="json") if output else None,
                "review_status": (
                    map_luna_result_to_review_status(output) if output else "LUNA_FAILED"
                ),
                "oe_assertion_created": False,
                "automatic_eligible": False,
                "pricing_eligible_by_construction": False,
            }
            luna_predictions.append(prediction)

    _write_jsonl(output_dir / "images/image_manifest.jsonl", image_manifest)
    _write_jsonl(output_dir / "luna/predictions.jsonl", luna_predictions)

    disposition_counts = Counter(
        row["assessment"]["disposition"] for row in verdict_rows
    )
    luna_valid = [
        row for row in luna_predictions if row["runner"].get("status") == "VALID"
    ]
    luna_verdicts = Counter(
        row["validated_output"]["verdict"]
        for row in luna_valid
        if row.get("validated_output")
    )
    run_status = (
        "STOPPED_SOURCE_BLOCK"
        if stop_live
        else "COMPLETED_WITH_ERRORS"
        if collection_errors
        else "COMPLETED_WITH_LUNA_FAILURES"
        if args.run_luna and luna_attempted > len(luna_valid)
        else "COMPLETED"
    )
    summary = {
        "contract_version": CONTRACT_VERSION,
        "luna_prompt_version": LUNA_PROMPT_VERSION,
        "luna_schema_version": LUNA_SCHEMA_VERSION,
        "run_status": run_status,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "live": args.live,
        "run_luna": args.run_luna,
        "source_access": access,
        "catalog_counts": catalog_counts,
        "selected_seeds": len(seeds),
        "queries_planned": sum(len(plan["queries"]) for plan in plans),
        "queries_executed": queries_executed,
        "http_requests_frozen": len(raw_manifest),
        "collection_errors": len(collection_errors),
        "unique_candidates": len(candidate_rows),
        "owned_seller_excluded": disposition_counts[
            DeterministicDisposition.OWNED_SELLER_EXCLUDED.value
        ],
        "deterministic_not_match": disposition_counts[
            DeterministicDisposition.SEMANTIC_NOT_MATCH.value
        ],
        "semantic_seed_unsupported": disposition_counts[
            DeterministicDisposition.SEMANTIC_SEED_UNSUPPORTED.value
        ],
        "semantic_needs_luna": disposition_counts[
            DeterministicDisposition.SEMANTIC_NEEDS_LUNA.value
        ],
        "luna_attempted": luna_attempted,
        "luna_cli_calls": luna_cli_calls,
        "luna_valid": len(luna_valid),
        "luna_verdicts": dict(sorted(luna_verdicts.items())),
        "identity_records_written": 0,
        "oe_assertions_created": 0,
        "prices_written": 0,
        "database_writes": 0,
        "automatic_pricing_admissions": 0,
    }
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "REPORT.md").write_text(
        _report(summary, output_dir=output_dir), encoding="utf-8"
    )
    manifest = {
        "contract_version": CONTRACT_VERSION,
        "master_workbook": {
            "path": str(args.master_workbook.resolve()),
            "sha256": sha256_file(args.master_workbook),
        },
        "source_workbook": {
            "path": str(args.source_workbook.resolve()),
            "sha256": sha256_file(args.source_workbook),
        },
        "arguments": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "summary_sha256": sha256_file(output_dir / "summary.json"),
        "artifacts": _artifact_manifest(output_dir),
    }
    _write_json(output_dir / "artifact_manifest.json", manifest)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    print(f"Artifacts: {output_dir}")
    return 0 if run_status == "COMPLETED" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; no database or pricing state was changed.", file=sys.stderr)
        raise SystemExit(130)
