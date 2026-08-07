"""Hash-pinned comparability acceptance and full-catalog manifest checks."""

from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from marko.services.llm_comparability import (
    LLM_COMPARABILITY_CONTRACT_VERSION,
    LLM_COMPARABILITY_PROMPT_VERSION,
    LLM_COMPARABILITY_SCHEMA_VERSION,
)
from marko.services.comparability_activation import (
    build_comparability_activation_payload,
)
from marko.services import semantic_candidate_features as semantic_features
from marko.services.semantic_candidate_features import (
    SEMANTIC_FEATURE_EXTRACTOR_VERSION,
    build_semantic_feature_matrix,
)


_IDENTITY_VALUES = frozenset({"MATCH", "NOT_MATCH", "MANUAL_REVIEW"})
_ADMISSION_VALUES = frozenset({"ADMITTED", "EXCLUDED", "MANUAL_REVIEW"})
_TERMINAL_CATALOG_RESULTS = frozenset(
    {"IMPORTED", "REJECTED_NOT_IMPORTABLE", "FAILED", "CANCELLED"}
)
_REVIEW_IDENTITY_VALUES = frozenset({"MATCH", "NOT_MATCH", "MANUAL_REVIEW", ""})
_REVIEW_PRICING_VALUES = frozenset({"ADMITTED", "EXCLUDED", "MANUAL_REVIEW", ""})
_INDEPENDENCE_ATTESTATION = (
    "Labels were assigned from source evidence by an independent domain "
    "reviewer without access to model or semantic-gate predictions."
)
_LOCKED_REVIEW_SCHEMA_VERSION = "comparability-locked-review-set-v2"
_LOCKED_TRUTH_SCHEMA_VERSION = "comparability-locked-truth-v2"
_REVIEW_IDENTITY_FINGERPRINT_VERSION = "comparability-review-identity-v2"
_PROM_PRODUCT_PATH_RE = re.compile(r"(?:^|/)p(\d+)(?:[-./]|$)", re.IGNORECASE)


class AcceptanceInputError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceInputError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AcceptanceInputError(f"{path} must contain a JSON object")
    return value


def _write_or_print(payload: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def _git_sha(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "NOT_AVAILABLE"


def _git_worktree_clean(root: Path) -> bool | None:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return not completed.stdout.strip() if completed.returncode == 0 else None


def build_freeze_manifest(
    root: Path,
    *,
    git_root: Path | None,
    output: Path | None,
    expected_baseline_sha: str | None,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        raise AcceptanceInputError(f"freeze root is not a directory: {resolved_root}")
    output_path = output.resolve() if output is not None else None
    files: list[dict[str, Any]] = []
    excluded_parts = frozenset(
        {".git", ".venv", ".dart_tool", "build", "__pycache__", ".pytest_cache"}
    )
    for path in sorted(
        item
        for item in resolved_root.rglob("*")
        if item.is_file()
        and not any(
            part in excluded_parts for part in item.relative_to(resolved_root).parts
        )
    ):
        if output_path is not None and path.resolve() == output_path:
            continue
        files.append(
            {
                "path": path.relative_to(resolved_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    resolved_git_root = (git_root or resolved_root).resolve()
    current_sha = _git_sha(resolved_git_root)
    payload: dict[str, Any] = {
        "manifest_version": "comparability-freeze-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "root": str(resolved_root),
        "git_root": str(resolved_git_root),
        "git_sha": current_sha,
        "git_worktree_clean": _git_worktree_clean(resolved_git_root),
        "expected_baseline_sha": expected_baseline_sha,
        "baseline_matches": (
            current_sha == expected_baseline_sha
            if expected_baseline_sha is not None
            else None
        ),
        "contract_version": LLM_COMPARABILITY_CONTRACT_VERSION,
        "prompt_version": LLM_COMPARABILITY_PROMPT_VERSION,
        "schema_version": LLM_COMPARABILITY_SCHEMA_VERSION,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "files": files,
    }
    payload["content_manifest_sha256"] = _canonical_sha256(files)
    return payload


def _rows(value: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise AcceptanceInputError(f"JSON field {key!r} must be an array")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise AcceptanceInputError(f"{key}[{index}] must be an object")
        rows.append(item)
    return rows


def _admission(value: object) -> str:
    normalized = str(value or "").strip().upper()
    return {
        "COMPARABLE": "ADMITTED",
        "NOT_COMPARABLE": "EXCLUDED",
    }.get(normalized, normalized)


def _identity(value: object) -> str:
    return str(value or "").strip().upper()


def _pair_map(
    rows: Iterable[Mapping[str, Any]], *, source: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        pair_id = str(row.get("pair_id") or "").strip()
        if not pair_id:
            raise AcceptanceInputError(f"{source} row has no pair_id")
        if pair_id in result:
            raise AcceptanceInputError(f"duplicate {source} pair_id {pair_id}")
        result[pair_id] = dict(row)
    return result


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.000001"))


def _zero_event_upper_95(denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return Decimal(str(1 - 0.05 ** (1 / denominator))).quantize(Decimal("0.000001"))


def _wilson_95(successes: int, denominator: int) -> dict[str, str] | None:
    """Return a two-sided Wilson score interval for a binomial proportion."""

    if denominator <= 0 or successes < 0 or successes > denominator:
        return None
    z = 1.959963984540054
    observed = successes / denominator
    denominator_adjustment = 1 + (z * z / denominator)
    centre = (observed + z * z / (2 * denominator)) / denominator_adjustment
    half_width = (
        z
        * math.sqrt(
            (observed * (1 - observed) + z * z / (4 * denominator)) / denominator
        )
        / denominator_adjustment
    )
    return {
        "lower": f"{max(0.0, centre - half_width):.6f}",
        "upper": f"{min(1.0, centre + half_width):.6f}",
    }


def evaluate_semantic_gate(
    benchmark_payload: Mapping[str, Any],
    truth_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Measure only deterministic contradiction detection on a pinned set.

    An unblocked candidate is deliberately reported as ``NEEDS_REVIEW`` rather
    than ``MATCH``.  The semantic layer is allowed to disprove identity from an
    explicit contradiction; it is never allowed to manufacture positive
    identity from title similarity.
    """

    benchmark = _pair_map(_rows(benchmark_payload, "pairs"), source="benchmark")
    truth = _pair_map(_rows(truth_payload, "labels"), source="truth")
    if set(benchmark) != set(truth):
        raise AcceptanceInputError(
            "truth/benchmark pair IDs differ: "
            f"missing={sorted(set(truth) - set(benchmark))}, "
            f"extra={sorted(set(benchmark) - set(truth))}"
        )

    positive = 0
    negative = 0
    false_hard_stops = 0
    hard_negatives_blocked = 0
    rows: list[dict[str, Any]] = []
    for pair_id in sorted(benchmark):
        pair = benchmark[pair_id]
        truth_row = truth[pair_id]
        identity_truth = _identity(truth_row.get("identity_truth"))
        if identity_truth not in {"MATCH", "NOT_MATCH"}:
            raise AcceptanceInputError(
                f"truth {pair_id} has unsupported identity_truth {identity_truth!r}"
            )
        seed = pair.get("seed")
        candidate = pair.get("candidate")
        if not isinstance(seed, Mapping) or not isinstance(candidate, Mapping):
            raise AcceptanceInputError(
                f"benchmark {pair_id} must contain seed and candidate objects"
            )
        matrix = build_semantic_feature_matrix(seed, candidate)
        conflicts = list(matrix["hard_stop_conflicts"])
        blocked = bool(conflicts)
        if identity_truth == "MATCH":
            positive += 1
            false_hard_stops += int(blocked)
        else:
            negative += 1
            hard_negatives_blocked += int(blocked)
        rows.append(
            {
                "pair_id": pair_id,
                "identity_truth": identity_truth,
                "semantic_gate": "HARD_STOP" if blocked else "NEEDS_REVIEW",
                "conflict_dimensions": [
                    str(conflict["dimension"]) for conflict in conflicts
                ],
                "hard_stop_conflicts": conflicts,
            }
        )

    missed_hard_negatives = negative - hard_negatives_blocked
    positive_survival = positive - false_hard_stops
    passed = false_hard_stops == 0 and missed_hard_negatives == 0
    return {
        "evaluation_version": "semantic-gate-benchmark-v1",
        "extractor_version": SEMANTIC_FEATURE_EXTRACTOR_VERSION,
        "extractor_implementation_sha256": _sha256(
            Path(str(semantic_features.__file__))
        ),
        "status": (
            "SEMANTIC_GATE_SMOKE_PASS" if passed else "SEMANTIC_GATE_SMOKE_FAIL"
        ),
        "promotion_eligible": False,
        "dataset": {
            "hash_kind": "canonical-json-sha256",
            "pairs": len(benchmark),
            "true_matches": positive,
            "hard_negatives": negative,
            "benchmark_sha256": _canonical_sha256(benchmark_payload),
            "truth_sha256": _canonical_sha256(truth_payload),
        },
        "metrics": {
            "false_hard_stop_count": false_hard_stops,
            "false_hard_stop_rate": (
                str(_ratio(false_hard_stops, positive)) if positive else "NOT_EVALUATED"
            ),
            "positive_survival_count": positive_survival,
            "positive_survival_rate": (
                str(_ratio(positive_survival, positive))
                if positive
                else "NOT_EVALUATED"
            ),
            "positive_survival_wilson_95": _wilson_95(positive_survival, positive),
            "zero_event_false_hard_stop_upper_95": (
                str(_zero_event_upper_95(positive))
                if positive and false_hard_stops == 0
                else "NOT_PROVEN"
            ),
            "hard_negative_block_count": hard_negatives_blocked,
            "hard_negative_block_rate": (
                str(_ratio(hard_negatives_blocked, negative))
                if negative
                else "NOT_EVALUATED"
            ),
            "hard_negative_block_wilson_95": _wilson_95(
                hard_negatives_blocked, negative
            ),
            "missed_hard_negative_count": missed_hard_negatives,
            "zero_event_missed_hard_negative_upper_95": (
                str(_zero_event_upper_95(negative))
                if negative and missed_hard_negatives == 0
                else "NOT_PROVEN"
            ),
        },
        "rows": rows,
        "boundary": {
            "unblocked_means_match": False,
            "positive_identity_authorized": False,
            "pricing_admission_authorized": False,
            "promotion_authorized": False,
            "note": (
                "Development smoke only. Independent domain labels and the "
                "locked acceptance denominator remain mandatory."
            ),
        },
    }


def _review_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(normalized.replace("\u00a0", " ").split())


def _review_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return _review_text(raw)
    host = (parsed.hostname or "").casefold()
    try:
        parsed_port = parsed.port
    except ValueError:
        return _review_text(raw)
    port = f":{parsed_port}" if parsed_port else ""
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), f"{host}{port}", path, "", ""))


def _first_value(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _identity_token(value: object) -> str:
    """Normalize a part identifier for grouping, not identity adjudication."""

    return "".join(character for character in _review_text(value) if character.isalnum())


def _prom_listing_identity(url: str) -> str:
    """Collapse canonical and shop-host Prom URLs to the immutable product id."""

    normalized = _review_url(url)
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    host = (parsed.hostname or "").casefold()
    match = _PROM_PRODUCT_PATH_RE.search(parsed.path)
    if match is not None and (host == "prom.ua" or host.endswith(".prom.ua")):
        return f"prom:p{match.group(1)}"
    return normalized


def _review_seed_identity_descriptor(row: Mapping[str, Any]) -> dict[str, str]:
    for kind, keys in (
        ("oe", ("our_oe", "oe", "oe_norm")),
        ("mpn", ("our_mpn", "mpn", "mpn_norm")),
        ("catalog_code", ("code", "our_sku", "seed_sku", "sku")),
    ):
        token = _identity_token(_first_value(row, *keys))
        if token:
            return {"kind": kind, "value": token}
    return {
        "kind": "title_fallback",
        "value": _review_text(_first_value(row, "our_title", "title", "name")),
    }


def _review_seed_identity(row: Mapping[str, Any]) -> str:
    return _canonical_sha256(_review_seed_identity_descriptor(row))


def _review_candidate_listing_descriptor(
    row: Mapping[str, Any],
) -> dict[str, str]:
    listing_url = _prom_listing_identity(_first_value(row, "offer_url", "url"))
    if listing_url:
        return {"kind": "listing_url", "value": listing_url}
    source_id = _identity_token(
        _first_value(row, "offer_id", "candidate_source_id", "source_id")
    )
    if source_id:
        return {"kind": "source_id", "value": source_id}
    sku = _identity_token(
        _first_value(row, "offer_sku", "candidate_code", "code", "sku")
    )
    if sku:
        return {
            "kind": "brand_sku_fallback",
            "value": f"{_review_text(_first_value(row, 'offer_brand', 'brand'))}\0{sku}",
        }
    return {
        "kind": "brand_title_fallback",
        "value": (
            f"{_review_text(_first_value(row, 'offer_brand', 'brand'))}\0"
            f"{_review_text(_first_value(row, 'offer_title', 'title', 'name'))}"
        ),
    }


def _review_candidate_identity(row: Mapping[str, Any]) -> str:
    return _canonical_sha256(_review_candidate_listing_descriptor(row))


def _review_candidate_family_descriptor(
    row: Mapping[str, Any],
) -> dict[str, str]:
    oe = _identity_token(
        _first_value(row, "offer_oe_raw", "candidate_oe_raw", "oe", "oe_norm")
    )
    if oe:
        return {"kind": "oe_family", "value": oe}
    sku = _identity_token(
        _first_value(row, "offer_sku", "candidate_code", "code", "sku")
    )
    brand = _review_text(_first_value(row, "offer_brand", "brand"))
    if sku:
        return {"kind": "brand_sku_family", "value": f"{brand}\0{sku}"}
    title = _review_text(_first_value(row, "offer_title", "title", "name"))
    if title:
        return {"kind": "brand_title_family", "value": f"{brand}\0{title}"}
    return _review_candidate_listing_descriptor(row)


def _review_candidate_family_identity(row: Mapping[str, Any]) -> str:
    return _canonical_sha256(_review_candidate_family_descriptor(row))


def _review_pair_identity(row: Mapping[str, Any]) -> str:
    return _canonical_sha256(
        {
            "seed": _review_seed_identity(row),
            "candidate": _review_candidate_identity(row),
        }
    )


def _task_identity_row(task: Mapping[str, Any]) -> dict[str, Any]:
    seed = task.get("seed")
    candidate = task.get("candidate")
    if not isinstance(seed, Mapping) or not isinstance(candidate, Mapping):
        return {}
    return {
        "our_oe": seed.get("oe"),
        "our_mpn": seed.get("mpn"),
        "our_sku": seed.get("sku"),
        "our_title": seed.get("title"),
        "offer_id": candidate.get("source_id"),
        "offer_sku": candidate.get("sku"),
        "offer_brand": candidate.get("brand"),
        "offer_title": candidate.get("title"),
        "offer_url": candidate.get("url"),
        "offer_oe_raw": candidate.get("oe_raw"),
    }


def _benchmark_exclusions(
    payloads: Sequence[Mapping[str, Any]],
) -> tuple[set[str], set[str], set[str], set[str]]:
    pair_ids: set[str] = set()
    seed_ids: set[str] = set()
    candidate_listing_ids: set[str] = set()
    candidate_family_ids: set[str] = set()
    for payload in payloads:
        for pair in _rows(payload, "pairs"):
            seed = pair.get("seed")
            candidate = pair.get("candidate")
            if not isinstance(seed, Mapping) or not isinstance(candidate, Mapping):
                raise AcceptanceInputError(
                    "development benchmark pair must contain seed/candidate objects"
                )
            flattened = {
                "our_oe": _first_value(seed, "oe", "oe_norm", "code", "sku"),
                "our_title": _first_value(seed, "title", "name"),
                "offer_id": _first_value(candidate, "id", "code", "sku"),
                "offer_sku": _first_value(candidate, "sku", "code"),
                "offer_title": _first_value(candidate, "title", "name"),
                "offer_brand": _first_value(candidate, "brand"),
                "offer_url": _first_value(candidate, "url"),
            }
            pair_ids.add(_review_pair_identity(flattened))
            seed_ids.add(_review_seed_identity(flattened))
            candidate_listing_ids.add(_review_candidate_identity(flattened))
            candidate_family_ids.add(_review_candidate_family_identity(flattened))
    return pair_ids, seed_ids, candidate_listing_ids, candidate_family_ids


def _read_review_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise AcceptanceInputError(f"review source has no header: {path}")
            required = {"our_title", "offer_title"}
            missing = sorted(required - set(reader.fieldnames))
            if missing:
                raise AcceptanceInputError(
                    f"review source {path} is missing columns {missing}"
                )
            return [dict(row) for row in reader]
    except OSError as exc:
        raise AcceptanceInputError(f"cannot read review CSV {path}: {exc}") from exc


def _review_evidence_payload(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "review_id": task.get("review_id"),
        "pair_fingerprint": task.get("pair_fingerprint"),
        "seed_group_fingerprint": task.get("seed_group_fingerprint"),
        "candidate_fingerprint": task.get("candidate_fingerprint"),
        "candidate_family_fingerprint": task.get("candidate_family_fingerprint"),
        "seed": task.get("seed"),
        "candidate": task.get("candidate"),
        "source_refs": task.get("source_refs"),
    }


def _maximum_independent_pair_capacity(tasks: Sequence[Mapping[str, Any]]) -> int:
    """Return the exact one-seed/one-candidate bipartite matching capacity.

    ``min(unique seeds, unique candidates)`` is only an upper bound. It is not
    attainable when several seed products depend on the same candidate edges.
    Treating that upper bound as an independent sample size would understate
    statistical uncertainty. A deterministic augmenting-path matching is exact
    for this unweighted bipartite graph and cheap for the review pools we build.
    """

    adjacency: dict[str, set[str]] = {}
    for task in tasks:
        seed = str(task.get("seed_group_fingerprint") or "")
        candidate = str(task.get("candidate_family_fingerprint") or "")
        if not seed or not candidate:
            continue
        adjacency.setdefault(seed, set()).add(candidate)

    candidate_to_seed: dict[str, str] = {}

    def augment(seed: str, visited_candidates: set[str]) -> bool:
        for candidate in sorted(adjacency.get(seed, ())):
            if candidate in visited_candidates:
                continue
            visited_candidates.add(candidate)
            owner = candidate_to_seed.get(candidate)
            if owner is None or augment(owner, visited_candidates):
                candidate_to_seed[candidate] = seed
                return True
        return False

    matched = 0
    for seed in sorted(adjacency):
        if augment(seed, set()):
            matched += 1
    return matched


def prepare_locked_review_set(
    source_paths: Sequence[Path],
    *,
    development_payloads: Sequence[Mapping[str, Any]] = (),
    selection_seed: str,
    max_pairs: int = 0,
) -> dict[str, Any]:
    """Build a prediction-blind, hash-bound pool for independent review."""

    if not source_paths:
        raise AcceptanceInputError("at least one review source CSV is required")
    if not selection_seed.strip():
        raise AcceptanceInputError("selection seed must be non-empty")
    if max_pairs < 0:
        raise AcceptanceInputError("max pairs cannot be negative")
    (
        excluded_pairs,
        excluded_seeds,
        excluded_candidate_listings,
        excluded_candidate_families,
    ) = _benchmark_exclusions(development_payloads)
    source_manifest: list[dict[str, Any]] = []
    unique: dict[str, dict[str, Any]] = {}
    duplicate_rows = excluded_overlap = 0
    for path in source_paths:
        resolved = path.resolve()
        rows = _read_review_csv(resolved)
        source_sha = _sha256(resolved)
        source_manifest.append(
            {
                "path": str(resolved),
                "sha256": source_sha,
                "data_rows": len(rows),
            }
        )
        for row_number, row in enumerate(rows, start=2):
            pair_fingerprint = _review_pair_identity(row)
            seed_fingerprint = _review_seed_identity(row)
            candidate_fingerprint = _review_candidate_identity(row)
            candidate_family_fingerprint = _review_candidate_family_identity(row)
            if (
                pair_fingerprint in excluded_pairs
                or seed_fingerprint in excluded_seeds
                or candidate_fingerprint in excluded_candidate_listings
                or candidate_family_fingerprint in excluded_candidate_families
            ):
                excluded_overlap += 1
                continue
            source_ref = {
                "source_sha256": source_sha,
                "source_row": row_number,
                "source_rank": _first_value(row, "rank", "pair_id"),
            }
            existing = unique.get(pair_fingerprint)
            if existing is not None:
                duplicate_rows += 1
                existing["source_refs"].append(source_ref)
                continue
            review_id = f"LR-{pair_fingerprint[:16]}"
            task: dict[str, Any] = {
                "review_id": review_id,
                "pair_fingerprint": pair_fingerprint,
                "seed_group_fingerprint": seed_fingerprint,
                "candidate_fingerprint": candidate_fingerprint,
                "candidate_family_fingerprint": candidate_family_fingerprint,
                "seed": {
                    "title": _first_value(row, "our_title"),
                    "oe": _first_value(row, "our_oe"),
                    "sku": _first_value(row, "our_sku", "seed_sku"),
                    "brand": _first_value(row, "our_brand", "seed_brand"),
                    "category": _first_value(row, "our_category", "seed_category"),
                    "mpn": _first_value(row, "our_mpn", "seed_mpn"),
                    "part_numbers": _first_value(
                        row, "our_part_numbers", "seed_part_numbers"
                    ),
                    "applicability": _first_value(
                        row, "our_applicability", "seed_applicability"
                    ),
                    "characteristics": _first_value(
                        row, "our_characteristics", "seed_characteristics"
                    ),
                    "product_url": _review_url(
                        _first_value(row, "our_product_url", "seed_product_url")
                    ),
                    "image_urls": _first_value(
                        row, "our_image_urls", "seed_image_urls"
                    ),
                    "description": _first_value(
                        row, "our_description", "seed_description"
                    ),
                },
                "candidate": {
                    "source_id": _first_value(
                        row, "offer_id", "candidate_source_id", "source_id"
                    ),
                    "title": _first_value(row, "offer_title"),
                    "sku": _first_value(row, "offer_sku"),
                    "brand": _first_value(row, "offer_brand"),
                    "url": _review_url(_first_value(row, "offer_url")),
                    "seller_name": _first_value(
                        row, "offer_seller_name", "candidate_seller_name"
                    ),
                    "image_url": _review_url(
                        _first_value(row, "offer_image_url", "candidate_image_url")
                    ),
                    "category": _first_value(
                        row, "offer_category", "candidate_category"
                    ),
                    "category_path": _first_value(
                        row, "offer_category_path", "candidate_category_path"
                    ),
                    "measure_unit": _first_value(
                        row, "offer_measure_unit", "candidate_measure_unit"
                    ),
                    "availability": _first_value(
                        row, "offer_availability", "candidate_availability"
                    ),
                    "condition": _first_value(
                        row, "offer_condition", "candidate_condition"
                    ),
                    "package_quantity": _first_value(
                        row,
                        "offer_package_quantity",
                        "candidate_package_quantity",
                    ),
                    "oe_raw": _first_value(row, "offer_oe_raw", "candidate_oe_raw"),
                    "fitment": _first_value(row, "offer_fitment", "candidate_fitment"),
                    "engine": _first_value(row, "offer_engine", "candidate_engine"),
                    "year_from": _first_value(
                        row, "offer_year_from", "candidate_year_from"
                    ),
                    "year_to": _first_value(row, "offer_year_to", "candidate_year_to"),
                    "body_variant": _first_value(
                        row, "offer_body_variant", "candidate_body_variant"
                    ),
                    "side": _first_value(row, "offer_side", "candidate_side"),
                    "position": _first_value(
                        row, "offer_position", "candidate_position"
                    ),
                    "description": _first_value(
                        row, "offer_description", "candidate_description"
                    ),
                    "characteristics": _first_value(
                        row,
                        "offer_characteristics",
                        "candidate_characteristics",
                    ),
                },
                "source_refs": [source_ref],
                "labels": {
                    "identity_truth": "",
                    "pricing_admission_truth": "",
                    "reason_codes": [],
                    "evidence_notes": "",
                },
            }
            task["evidence_sha256"] = _canonical_sha256(_review_evidence_payload(task))
            unique[pair_fingerprint] = task

    ordered = sorted(
        unique.values(),
        key=lambda task: hashlib.sha256(
            f"{selection_seed}\0{task['pair_fingerprint']}".encode("utf-8")
        ).hexdigest(),
    )
    if max_pairs:
        ordered = ordered[:max_pairs]
    # Duplicate rows are merged into provenance after first construction;
    # bind the final source-ref list rather than only the first occurrence.
    for task in ordered:
        task["evidence_sha256"] = _canonical_sha256(_review_evidence_payload(task))
    selected_seed_groups = {str(task["seed_group_fingerprint"]) for task in ordered}
    selected_candidate_groups = {
        str(task["candidate_fingerprint"]) for task in ordered
    }
    selected_candidate_families = {
        str(task["candidate_family_fingerprint"]) for task in ordered
    }
    independent_pair_capacity = _maximum_independent_pair_capacity(ordered)
    payload: dict[str, Any] = {
        "schema_version": _LOCKED_REVIEW_SCHEMA_VERSION,
        "identity_fingerprint_version": _REVIEW_IDENTITY_FINGERPRINT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "blinded": True,
        "contains_model_predictions": False,
        "contains_prices": False,
        "selection": {
            "algorithm": "sha256-seeded-stable-order-v1",
            "selection_seed_sha256": hashlib.sha256(
                selection_seed.encode("utf-8")
            ).hexdigest(),
            "requested_max_pairs": max_pairs or "ALL",
            "eligible_unique_pairs": len(unique),
            "selected_pairs": len(ordered),
            "selected_seed_groups": len(selected_seed_groups),
            "selected_candidate_groups": len(selected_candidate_groups),
            "selected_candidate_families": len(selected_candidate_families),
            "max_one_per_seed_and_candidate_capacity": independent_pair_capacity,
            "capacity_algorithm": "exact-bipartite-maximum-matching-v1",
            "minimum_additional_unique_groups_for_400": max(
                0, 400 - independent_pair_capacity
            ),
            "locked_100_plus_300_structurally_reachable": (
                independent_pair_capacity >= 400
            ),
            "excluded_development_overlap_rows": excluded_overlap,
            "deduplicated_source_rows": duplicate_rows,
        },
        "development_exclusions": {
            "benchmark_count": len(development_payloads),
            "pair_fingerprints": len(excluded_pairs),
            "seed_group_fingerprints": len(excluded_seeds),
            "candidate_listing_fingerprints": len(excluded_candidate_listings),
            "candidate_family_fingerprints": len(excluded_candidate_families),
        },
        "source_manifest": source_manifest,
        "review_attestation": {
            "reviewer_id": "",
            "reviewer_role": "",
            "reviewed_at": "",
            "independence_attested": False,
            "required_statement": _INDEPENDENCE_ATTESTATION,
        },
        "tasks": ordered,
        "boundary": {
            "system_predictions_are_ground_truth": False,
            "unlabelled_tasks_are_matches": False,
            "promotion_authorized": False,
        },
    }
    payload["source_manifest_sha256"] = _canonical_sha256(source_manifest)
    payload["task_manifest_sha256"] = _canonical_sha256(
        [
            {
                "review_id": task["review_id"],
                "evidence_sha256": task["evidence_sha256"],
            }
            for task in ordered
        ]
    )
    return payload


def write_locked_review_csv(payload: Mapping[str, Any], output: Path) -> dict[str, Any]:
    """Export only evidence plus blank/operator labels, never model output."""

    tasks = _rows(payload, "tasks")
    resolved = output.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "review_id",
        "evidence_sha256",
        "seed_oe",
        "seed_title",
        "candidate_sku",
        "candidate_brand",
        "candidate_title",
        "candidate_url",
        "seed_sku",
        "seed_brand",
        "seed_category",
        "seed_mpn",
        "seed_part_numbers",
        "seed_applicability",
        "seed_characteristics",
        "seed_product_url",
        "seed_image_urls",
        "seed_description",
        "candidate_seller_name",
        "candidate_image_url",
        "candidate_category",
        "candidate_category_path",
        "candidate_measure_unit",
        "candidate_availability",
        "candidate_condition",
        "candidate_package_quantity",
        "candidate_oe_raw",
        "candidate_fitment",
        "candidate_engine",
        "candidate_year_from",
        "candidate_year_to",
        "candidate_body_variant",
        "candidate_side",
        "candidate_position",
        "candidate_description",
        "candidate_characteristics",
        "identity_truth",
        "pricing_admission_truth",
        "reason_codes",
        "evidence_notes",
    ]
    try:
        with resolved.open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fieldnames)
            writer.writeheader()
            for task in tasks:
                seed = task.get("seed")
                candidate = task.get("candidate")
                labels = task.get("labels")
                writer.writerow(
                    {
                        "review_id": task.get("review_id"),
                        "evidence_sha256": task.get("evidence_sha256"),
                        "seed_oe": seed.get("oe", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "seed_title": seed.get("title", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "candidate_sku": candidate.get("sku", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_brand": candidate.get("brand", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_title": candidate.get("title", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_url": candidate.get("url", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "seed_sku": seed.get("sku", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "seed_brand": seed.get("brand", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "seed_category": seed.get("category", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "seed_mpn": seed.get("mpn", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "seed_part_numbers": seed.get("part_numbers", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "seed_applicability": seed.get("applicability", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "seed_characteristics": seed.get("characteristics", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "seed_product_url": seed.get("product_url", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "seed_image_urls": seed.get("image_urls", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "seed_description": seed.get("description", "")
                        if isinstance(seed, Mapping)
                        else "",
                        "candidate_seller_name": candidate.get("seller_name", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_image_url": candidate.get("image_url", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_category": candidate.get("category", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_category_path": candidate.get("category_path", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_measure_unit": candidate.get("measure_unit", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_availability": candidate.get("availability", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_condition": candidate.get("condition", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_package_quantity": candidate.get(
                            "package_quantity", ""
                        )
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_oe_raw": candidate.get("oe_raw", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_fitment": candidate.get("fitment", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_engine": candidate.get("engine", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_year_from": candidate.get("year_from", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_year_to": candidate.get("year_to", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_body_variant": candidate.get("body_variant", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_side": candidate.get("side", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_position": candidate.get("position", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_description": candidate.get("description", "")
                        if isinstance(candidate, Mapping)
                        else "",
                        "candidate_characteristics": candidate.get(
                            "characteristics", ""
                        )
                        if isinstance(candidate, Mapping)
                        else "",
                        "identity_truth": labels.get("identity_truth", "")
                        if isinstance(labels, Mapping)
                        else "",
                        "pricing_admission_truth": labels.get(
                            "pricing_admission_truth", ""
                        )
                        if isinstance(labels, Mapping)
                        else "",
                        "reason_codes": ";".join(labels.get("reason_codes") or [])
                        if isinstance(labels, Mapping)
                        else "",
                        "evidence_notes": labels.get("evidence_notes", "")
                        if isinstance(labels, Mapping)
                        else "",
                    }
                )
    except OSError as exc:
        raise AcceptanceInputError(
            f"cannot write review CSV {resolved}: {exc}"
        ) from exc
    return {
        "path": str(resolved),
        "rows": len(tasks),
        "sha256": _sha256(resolved),
        "encoding": "utf-8-sig",
        "contains_model_predictions": False,
        "contains_prices": False,
    }


def write_locked_review_html(
    payload: Mapping[str, Any], output: Path
) -> dict[str, Any]:
    """Write a standalone, prediction-blind visual review workstation.

    The page renders only frozen source evidence and stores draft labels in the
    browser's local storage. Its CSV export contains exactly the identifiers,
    evidence hashes and operator labels accepted by ``import_locked_review_csv``.
    No model verdict or monetary field is embedded in the document.
    """

    tasks = _rows(payload, "tasks")
    manifest = str(payload.get("task_manifest_sha256") or "")
    browser_tasks = [
        {
            "review_id": task.get("review_id"),
            "evidence_sha256": task.get("evidence_sha256"),
            "seed": task.get("seed"),
            "candidate": task.get("candidate"),
        }
        for task in tasks
    ]
    task_json = json.dumps(
        browser_tasks,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    # JSON inside a script element must not be able to terminate that element.
    task_json = (
        task_json.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    template = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Metis — независимая проверка сопоставимости</title>
  <style>
    :root { color-scheme: light; font-family: Inter, system-ui, sans-serif; }
    body { margin: 0; background: #f4f6f8; color: #17202a; }
    header { position: sticky; top: 0; z-index: 4; background: #101b2d; color: white;
      padding: 14px 20px; box-shadow: 0 2px 12px #0003; }
    header h1 { font-size: 19px; margin: 0 0 6px; }
    header p { margin: 0; color: #cdd8ea; font-size: 13px; }
    .toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
      margin-top: 12px; }
    button, select, input, textarea { font: inherit; }
    button { border: 0; border-radius: 8px; padding: 9px 13px; cursor: pointer;
      background: #3264e8; color: white; font-weight: 650; }
    button.secondary { background: #334155; }
    .progress { margin-left: auto; font-weight: 650; }
    main { max-width: 1440px; margin: 18px auto; padding: 0 14px 80px; }
    .card { background: white; border: 1px solid #d8dee8; border-radius: 12px;
      margin: 0 0 16px; overflow: hidden; box-shadow: 0 2px 8px #1020400a; }
    .card-head { display: flex; justify-content: space-between; gap: 12px;
      padding: 10px 14px; background: #eef2f7; font-size: 12px; color: #526071; }
    .comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
    .side { min-width: 0; padding: 14px; }
    .side + .side { border-left: 1px solid #d8dee8; }
    .side h2 { font-size: 16px; margin: 0 0 10px; }
    .photo { width: 100%; height: 220px; object-fit: contain; background: #f8fafc;
      border: 1px solid #e2e8f0; border-radius: 8px; }
    .photo.empty { display: grid; place-items: center; color: #7b8794; }
    dl { display: grid; grid-template-columns: 132px minmax(0, 1fr); gap: 5px 10px;
      font-size: 13px; }
    dt { color: #667387; }
    dd { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
    a { color: #2857c5; }
    details { margin-top: 10px; font-size: 13px; }
    details pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f7f9fb;
      padding: 10px; border-radius: 8px; max-height: 320px; overflow: auto; }
    .decision { border-top: 1px solid #d8dee8; padding: 14px;
      display: grid; grid-template-columns: 190px 220px 1fr 1.5fr; gap: 12px; }
    label { display: grid; gap: 5px; font-size: 12px; color: #526071; }
    select, input, textarea { border: 1px solid #b8c2cf; border-radius: 7px;
      padding: 8px; background: white; color: #17202a; }
    textarea { min-height: 54px; resize: vertical; }
    .complete { border-color: #47a36b; box-shadow: 0 0 0 2px #47a36b22; }
    .warning { color: #ffddb0; font-size: 12px; }
    @media (max-width: 860px) {
      .comparison { grid-template-columns: 1fr; }
      .side + .side { border-left: 0; border-top: 1px solid #d8dee8; }
      .decision { grid-template-columns: 1fr; }
      .progress { margin-left: 0; }
    }
  </style>
</head>
<body>
<header>
  <h1>Metis — независимая проверка сопоставимости</h1>
  <p>Цены и ответы модели скрыты. UNKNOWN не додумывать: при недостатке доказательств используйте MANUAL_REVIEW.</p>
  <div class="toolbar">
    <button id="export">Экспортировать labels CSV</button>
    <button id="clear" class="secondary">Очистить локальный черновик</button>
    <select id="filter" aria-label="Фильтр">
      <option value="all">Все карточки</option>
      <option value="pending">Только незавершённые</option>
      <option value="complete">Только завершённые</option>
    </select>
    <span class="progress" id="progress"></span>
  </div>
  <div class="warning">Не открывайте DevTools или другие системные результаты во время независимой разметки.</div>
</header>
<main id="cards"></main>
<script>
"use strict";
const tasks = __TASKS_JSON__;
const manifest = "__TASK_MANIFEST__";
const storageKey = `metis-locked-review:${manifest}`;
const labels = JSON.parse(localStorage.getItem(storageKey) || "{}");
const cards = document.getElementById("cards");

function text(value) { return value == null ? "" : String(value); }
function safeUrl(value) {
  try { const u = new URL(text(value)); return u.protocol === "https:" ? u.href : ""; }
  catch (_) { return ""; }
}
function firstImage(value) {
  for (const candidate of text(value).split(/[,;\\n]/)) {
    const url = safeUrl(candidate.trim()); if (url) return url;
  }
  return "";
}
function addText(parent, tag, value, className) {
  const node = document.createElement(tag); node.textContent = text(value);
  if (className) node.className = className; parent.appendChild(node); return node;
}
function addField(dl, name, value) {
  if (!text(value).trim()) return;
  addText(dl, "dt", name); addText(dl, "dd", value);
}
function addLink(dl, name, value) {
  const url = safeUrl(value); if (!url) return;
  addText(dl, "dt", name); const dd = document.createElement("dd");
  const link = document.createElement("a"); link.href = url; link.target = "_blank";
  link.rel = "noopener noreferrer"; link.textContent = "Открыть источник";
  dd.appendChild(link); dl.appendChild(dd);
}
function addDetails(parent, label, value) {
  if (!text(value).trim()) return;
  const details = document.createElement("details"); addText(details, "summary", label);
  addText(details, "pre", value); parent.appendChild(details);
}
function photo(parent, url, alt) {
  const safe = firstImage(url);
  if (!safe) { const empty = addText(parent, "div", "Изображение не сохранено", "photo empty"); return empty; }
  const image = document.createElement("img"); image.className = "photo"; image.src = safe;
  image.alt = alt; image.loading = "lazy"; image.referrerPolicy = "no-referrer";
  parent.appendChild(image); return image;
}
function isComplete(value) {
  return ["MATCH", "NOT_MATCH"].includes(value.identity_truth) &&
    ["ADMITTED", "EXCLUDED"].includes(value.pricing_admission_truth) &&
    text(value.evidence_notes).trim().length > 0;
}
function persist() { localStorage.setItem(storageKey, JSON.stringify(labels)); updateProgress(); }
function control(tag, values, current, onChange) {
  const node = document.createElement(tag);
  if (tag === "select") for (const [value, label] of values) {
    const option = document.createElement("option"); option.value = value;
    option.textContent = label; node.appendChild(option);
  }
  node.value = current || ""; node.addEventListener("input", () => onChange(node.value));
  return node;
}
function render() {
  cards.replaceChildren();
  for (const task of tasks) {
    const seed = task.seed || {}; const candidate = task.candidate || {};
    const value = labels[task.review_id] || { identity_truth: "", pricing_admission_truth: "", reason_codes: "", evidence_notes: "" };
    labels[task.review_id] = value;
    const card = document.createElement("article"); card.className = "card";
    card.dataset.complete = isComplete(value) ? "true" : "false";
    const head = document.createElement("div"); head.className = "card-head";
    addText(head, "span", task.review_id); addText(head, "span", `evidence ${text(task.evidence_sha256).slice(0, 16)}…`);
    card.appendChild(head);
    const comparison = document.createElement("div"); comparison.className = "comparison";
    const left = document.createElement("section"); left.className = "side"; addText(left, "h2", "Наш товар");
    photo(left, seed.image_urls, text(seed.title));
    const seedDl = document.createElement("dl");
    addField(seedDl, "Название", seed.title); addField(seedDl, "OE", seed.oe);
    addField(seedDl, "SKU", seed.sku); addField(seedDl, "Бренд", seed.brand);
    addField(seedDl, "Категория", seed.category); addField(seedDl, "MPN", seed.mpn);
    addField(seedDl, "Артикулы", seed.part_numbers); addField(seedDl, "Применимость", seed.applicability);
    addLink(seedDl, "Карточка", seed.product_url); left.appendChild(seedDl);
    addDetails(left, "Характеристики нашего товара", seed.characteristics);
    addDetails(left, "Описание нашего товара", seed.description);
    const right = document.createElement("section"); right.className = "side"; addText(right, "h2", "Кандидат");
    photo(right, candidate.image_url, text(candidate.title));
    const candidateDl = document.createElement("dl");
    addField(candidateDl, "Название", candidate.title); addField(candidateDl, "SKU", candidate.sku);
    addField(candidateDl, "Бренд", candidate.brand); addField(candidateDl, "Продавец", candidate.seller_name);
    addField(candidateDl, "Категория", candidate.category); addField(candidateDl, "Путь категории", candidate.category_path);
    addField(candidateDl, "Единица", candidate.measure_unit); addField(candidateDl, "Наличие", candidate.availability);
    addField(candidateDl, "Состояние", candidate.condition); addField(candidateDl, "Количество", candidate.package_quantity);
    addField(candidateDl, "OE из карточки", candidate.oe_raw); addField(candidateDl, "Применимость", candidate.fitment);
    addField(candidateDl, "Двигатель", candidate.engine); addField(candidateDl, "Годы", [candidate.year_from, candidate.year_to].filter(Boolean).join("–"));
    addField(candidateDl, "Кузов", candidate.body_variant); addField(candidateDl, "Сторона", candidate.side);
    addField(candidateDl, "Позиция", candidate.position); addLink(candidateDl, "Карточка", candidate.url);
    right.appendChild(candidateDl); addDetails(right, "Характеристики кандидата", candidate.characteristics);
    addDetails(right, "Описание кандидата", candidate.description);
    comparison.append(left, right); card.appendChild(comparison);
    const decision = document.createElement("div"); decision.className = "decision";
    const specs = [
      ["Identity truth", "select", [["", "— выберите —"], ["MATCH", "MATCH"], ["NOT_MATCH", "NOT_MATCH"], ["MANUAL_REVIEW", "MANUAL_REVIEW"]], "identity_truth"],
      ["Pricing admission", "select", [["", "— выберите —"], ["ADMITTED", "ADMITTED"], ["EXCLUDED", "EXCLUDED"], ["MANUAL_REVIEW", "MANUAL_REVIEW"]], "pricing_admission_truth"],
      ["Reason codes через ;", "input", [], "reason_codes"],
      ["Обоснование по доказательствам", "textarea", [], "evidence_notes"]
    ];
    for (const [labelText, tag, options, key] of specs) {
      const label = document.createElement("label"); addText(label, "span", labelText);
      const node = control(tag, options, value[key], next => { value[key] = next; card.dataset.complete = isComplete(value) ? "true" : "false"; card.classList.toggle("complete", isComplete(value)); persist(); applyFilter(); });
      label.appendChild(node); decision.appendChild(label);
    }
    card.classList.toggle("complete", isComplete(value)); card.appendChild(decision); cards.appendChild(card);
  }
  persist(); applyFilter();
}
function updateProgress() {
  const complete = tasks.filter(task => isComplete(labels[task.review_id] || {})).length;
  document.getElementById("progress").textContent = `${complete} / ${tasks.length} завершено`;
}
function applyFilter() {
  const filter = document.getElementById("filter").value;
  for (const card of cards.children) {
    const complete = card.dataset.complete === "true";
    card.hidden = filter === "pending" ? complete : filter === "complete" ? !complete : false;
  }
}
function csvCell(value) { return `"${text(value).replaceAll('"', '""')}"`; }
function exportCsv() {
  const headers = ["review_id", "evidence_sha256", "identity_truth", "pricing_admission_truth", "reason_codes", "evidence_notes"];
  const rows = [headers.map(csvCell).join(",")];
  for (const task of tasks) {
    const value = labels[task.review_id] || {};
    rows.push([task.review_id, task.evidence_sha256, value.identity_truth, value.pricing_admission_truth, value.reason_codes, value.evidence_notes].map(csvCell).join(","));
  }
  const blob = new Blob(["\\ufeff" + rows.join("\\r\\n") + "\\r\\n"], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob);
  link.download = `metis_locked_labels_${manifest.slice(0, 12)}.csv`; link.click(); URL.revokeObjectURL(link.href);
}
document.getElementById("filter").addEventListener("change", applyFilter);
document.getElementById("export").addEventListener("click", exportCsv);
document.getElementById("clear").addEventListener("click", () => { if (confirm("Удалить локальный черновик разметки?")) { localStorage.removeItem(storageKey); location.reload(); } });
render();
</script>
</body>
</html>
"""
    rendered = template.replace("__TASKS_JSON__", task_json).replace(
        "__TASK_MANIFEST__", manifest
    )
    resolved = output.resolve()
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        raise AcceptanceInputError(
            f"cannot write review HTML {resolved}: {exc}"
        ) from exc
    return {
        "path": str(resolved),
        "rows": len(tasks),
        "sha256": _sha256(resolved),
        "contains_model_predictions": False,
        "contains_prices": False,
        "supports_local_draft": True,
        "exports_importable_labels_csv": True,
    }


def import_locked_review_csv(
    payload: Mapping[str, Any],
    labels_path: Path,
    *,
    reviewer_id: str,
    reviewer_role: str,
    reviewed_at: str,
    independence_attested: bool,
) -> dict[str, Any]:
    """Bind reviewed CSV labels back to the immutable JSON evidence tasks."""

    updated = deepcopy(dict(payload))
    tasks = _rows(updated, "tasks")
    task_map = {str(task.get("review_id") or ""): task for task in tasks}
    if "" in task_map or len(task_map) != len(tasks):
        raise AcceptanceInputError(
            "review set contains missing or duplicate review IDs"
        )
    try:
        with labels_path.resolve().open(
            "r", encoding="utf-8-sig", newline=""
        ) as source:
            reader = csv.DictReader(source)
            required = {
                "review_id",
                "evidence_sha256",
                "identity_truth",
                "pricing_admission_truth",
                "reason_codes",
                "evidence_notes",
            }
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise AcceptanceInputError(
                    f"review label CSV must contain columns {sorted(required)}"
                )
            label_rows = [dict(row) for row in reader]
    except OSError as exc:
        raise AcceptanceInputError(
            f"cannot read review label CSV {labels_path}: {exc}"
        ) from exc
    label_map: dict[str, dict[str, str]] = {}
    for row in label_rows:
        review_id = str(row.get("review_id") or "").strip()
        if not review_id or review_id in label_map:
            raise AcceptanceInputError(
                f"review label CSV has missing/duplicate review_id {review_id!r}"
            )
        label_map[review_id] = row
    if set(label_map) != set(task_map):
        raise AcceptanceInputError(
            "review label CSV task IDs differ from frozen review set: "
            f"missing={sorted(set(task_map) - set(label_map))}, "
            f"extra={sorted(set(label_map) - set(task_map))}"
        )
    for review_id, task in task_map.items():
        row = label_map[review_id]
        if row.get("evidence_sha256") != task.get("evidence_sha256"):
            raise AcceptanceInputError(
                f"review label CSV evidence hash mismatch for {review_id}"
            )
        task["labels"] = {
            "identity_truth": _identity(row.get("identity_truth")),
            "pricing_admission_truth": _admission(row.get("pricing_admission_truth")),
            "reason_codes": [
                value.strip()
                for value in str(row.get("reason_codes") or "").split(";")
                if value.strip()
            ],
            "evidence_notes": str(row.get("evidence_notes") or "").strip(),
        }
    updated["review_attestation"] = {
        "reviewer_id": reviewer_id.strip(),
        "reviewer_role": reviewer_role.strip(),
        "reviewed_at": reviewed_at.strip(),
        "independence_attested": independence_attested,
        "required_statement": _INDEPENDENCE_ATTESTATION,
    }
    updated["label_import"] = {
        "source_csv_path": str(labels_path.resolve()),
        "source_csv_sha256": _sha256(labels_path.resolve()),
        "rows": len(label_rows),
    }
    return updated


def _review_contains_forbidden_key(value: object) -> bool:
    forbidden = {
        "price",
        "our_price",
        "offer_price",
        "current_price",
        "sale_price",
        "reference_price",
        "cost",
        "model_prediction",
        "identity_verdict",
        "semantic_gate",
        "hard_stop_conflicts",
        "decision_confidence",
    }
    if isinstance(value, Mapping):
        return any(
            str(key) in forbidden or _review_contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_review_contains_forbidden_key(item) for item in value)
    return False


def validate_locked_review_set(
    payload: Mapping[str, Any],
    *,
    require_complete: bool = False,
) -> dict[str, Any]:
    tasks = _rows(payload, "tasks")
    invalid: list[dict[str, Any]] = []
    review_ids: set[str] = set()
    pair_ids: set[str] = set()
    label_counts = {"MATCH": 0, "NOT_MATCH": 0, "MANUAL_REVIEW": 0, "": 0}
    pricing_counts = {"ADMITTED": 0, "EXCLUDED": 0, "MANUAL_REVIEW": 0, "": 0}
    if payload.get("schema_version") != _LOCKED_REVIEW_SCHEMA_VERSION:
        invalid.append({"review_id": None, "reason": "STALE_REVIEW_SCHEMA"})
    if (
        payload.get("identity_fingerprint_version")
        != _REVIEW_IDENTITY_FINGERPRINT_VERSION
    ):
        invalid.append(
            {"review_id": None, "reason": "STALE_IDENTITY_FINGERPRINT_CONTRACT"}
        )
    if payload.get("blinded") is not True:
        invalid.append({"review_id": None, "reason": "REVIEW_SET_NOT_BLINDED"})
    if payload.get("contains_model_predictions") is not False:
        invalid.append({"review_id": None, "reason": "MODEL_PREDICTIONS_PRESENT"})
    if payload.get("contains_prices") is not False:
        invalid.append({"review_id": None, "reason": "PRICES_PRESENT"})
    source_manifest = payload.get("source_manifest")
    if not isinstance(source_manifest, list) or payload.get(
        "source_manifest_sha256"
    ) != _canonical_sha256(source_manifest):
        invalid.append({"review_id": None, "reason": "SOURCE_MANIFEST_HASH_MISMATCH"})
    for task in tasks:
        review_id = str(task.get("review_id") or "")
        pair_id = str(task.get("pair_fingerprint") or "")
        if not review_id or review_id in review_ids:
            invalid.append({"review_id": review_id, "reason": "DUPLICATE_REVIEW_ID"})
        if not pair_id or pair_id in pair_ids:
            invalid.append({"review_id": review_id, "reason": "DUPLICATE_PAIR"})
        review_ids.add(review_id)
        pair_ids.add(pair_id)
        identity_row = _task_identity_row(task)
        expected_seed = _review_seed_identity(identity_row)
        expected_candidate = _review_candidate_identity(identity_row)
        expected_candidate_family = _review_candidate_family_identity(identity_row)
        expected_pair = _canonical_sha256(
            {"seed": expected_seed, "candidate": expected_candidate}
        )
        if task.get("seed_group_fingerprint") != expected_seed:
            invalid.append(
                {"review_id": review_id, "reason": "SEED_FINGERPRINT_MISMATCH"}
            )
        if task.get("candidate_fingerprint") != expected_candidate:
            invalid.append(
                {"review_id": review_id, "reason": "CANDIDATE_FINGERPRINT_MISMATCH"}
            )
        if task.get("candidate_family_fingerprint") != expected_candidate_family:
            invalid.append(
                {
                    "review_id": review_id,
                    "reason": "CANDIDATE_FAMILY_FINGERPRINT_MISMATCH",
                }
            )
        if pair_id != expected_pair:
            invalid.append(
                {"review_id": review_id, "reason": "PAIR_FINGERPRINT_MISMATCH"}
            )
        expected = _canonical_sha256(_review_evidence_payload(task))
        if task.get("evidence_sha256") != expected:
            invalid.append({"review_id": review_id, "reason": "EVIDENCE_HASH_MISMATCH"})
        labels = task.get("labels")
        if not isinstance(labels, Mapping):
            invalid.append({"review_id": review_id, "reason": "LABELS_MISSING"})
            continue
        identity = _identity(labels.get("identity_truth"))
        pricing = _admission(labels.get("pricing_admission_truth"))
        if identity not in _REVIEW_IDENTITY_VALUES:
            invalid.append({"review_id": review_id, "reason": "INVALID_IDENTITY_LABEL"})
        else:
            label_counts[identity] += 1
        if pricing not in _REVIEW_PRICING_VALUES:
            invalid.append({"review_id": review_id, "reason": "INVALID_PRICING_LABEL"})
        else:
            pricing_counts[pricing] += 1
        if identity == "NOT_MATCH" and pricing not in {"EXCLUDED", ""}:
            invalid.append(
                {"review_id": review_id, "reason": "NOT_MATCH_MUST_BE_EXCLUDED"}
            )
        if _review_contains_forbidden_key(task):
            invalid.append(
                {"review_id": review_id, "reason": "BLINDING_BOUNDARY_VIOLATION"}
            )
        if require_complete:
            if identity in {"", "MANUAL_REVIEW"}:
                invalid.append({"review_id": review_id, "reason": "IDENTITY_NOT_FINAL"})
            if pricing in {"", "MANUAL_REVIEW"}:
                invalid.append({"review_id": review_id, "reason": "PRICING_NOT_FINAL"})
            if not str(labels.get("evidence_notes") or "").strip():
                invalid.append(
                    {"review_id": review_id, "reason": "EVIDENCE_NOTES_MISSING"}
                )
    attestation = payload.get("review_attestation")
    attested = (
        isinstance(attestation, Mapping)
        and bool(str(attestation.get("reviewer_id") or "").strip())
        and bool(str(attestation.get("reviewer_role") or "").strip())
        and bool(str(attestation.get("reviewed_at") or "").strip())
        and attestation.get("independence_attested") is True
        and attestation.get("required_statement") == _INDEPENDENCE_ATTESTATION
    )
    if require_complete and not attested:
        invalid.append({"review_id": None, "reason": "INDEPENDENT_REVIEW_NOT_ATTESTED"})
    expected_task_manifest = _canonical_sha256(
        [
            {
                "review_id": task.get("review_id"),
                "evidence_sha256": task.get("evidence_sha256"),
            }
            for task in tasks
        ]
    )
    if payload.get("task_manifest_sha256") != expected_task_manifest:
        invalid.append({"review_id": None, "reason": "TASK_MANIFEST_HASH_MISMATCH"})
    passed = not invalid
    return {
        "validation_version": "comparability-locked-review-validation-v1",
        "status": "PASS" if passed else "FAIL",
        "require_complete": require_complete,
        "tasks": len(tasks),
        "unique_seed_groups": len(
            {str(task.get("seed_group_fingerprint") or "") for task in tasks}
        ),
        "unique_candidate_listings": len(
            {str(task.get("candidate_fingerprint") or "") for task in tasks}
        ),
        "unique_candidate_families": len(
            {str(task.get("candidate_family_fingerprint") or "") for task in tasks}
        ),
        "identity_counts": label_counts,
        "pricing_counts": pricing_counts,
        "independent_review_attested": attested,
        "invalid": invalid,
        "promotion_authorized": False,
    }


def _independent_reviewer_id(payload: Mapping[str, Any], *, role: str) -> str:
    attestation = payload.get("review_attestation")
    if not isinstance(attestation, Mapping):
        raise AcceptanceInputError(f"{role} review set has no reviewer attestation")
    reviewer_id = str(attestation.get("reviewer_id") or "").strip()
    if (
        not reviewer_id
        or not str(attestation.get("reviewer_role") or "").strip()
        or not str(attestation.get("reviewed_at") or "").strip()
        or attestation.get("independence_attested") is not True
        or attestation.get("required_statement") != _INDEPENDENCE_ATTESTATION
    ):
        raise AcceptanceInputError(
            f"{role} review set lacks a complete independent-review attestation"
        )
    return reviewer_id


def _agreement_dimension(
    comparisons: Sequence[Mapping[str, str]],
    *,
    primary_key: str,
    secondary_key: str,
    classes: Sequence[str],
    raw_threshold: float,
    kappa_threshold: float,
) -> dict[str, Any]:
    total = len(comparisons)
    matrix = {
        primary: {secondary: 0 for secondary in classes} for primary in classes
    }
    primary_counts = {value: 0 for value in classes}
    secondary_counts = {value: 0 for value in classes}
    agreements = 0
    for row in comparisons:
        primary = row[primary_key]
        secondary = row[secondary_key]
        matrix[primary][secondary] += 1
        primary_counts[primary] += 1
        secondary_counts[secondary] += 1
        agreements += int(primary == secondary)

    observed = agreements / total
    expected = sum(
        (primary_counts[value] / total) * (secondary_counts[value] / total)
        for value in classes
    )
    denominator = 1.0 - expected
    kappa = None if math.isclose(denominator, 0.0) else (observed - expected) / denominator
    passed = observed >= raw_threshold and kappa is not None and kappa >= kappa_threshold
    return {
        "rows": total,
        "agreements": agreements,
        "disagreements": total - agreements,
        "raw_agreement": round(observed, 6),
        "raw_agreement_threshold": raw_threshold,
        "expected_agreement": round(expected, 6),
        "cohen_kappa": None if kappa is None else round(kappa, 6),
        "cohen_kappa_threshold": kappa_threshold,
        "kappa_defined": kappa is not None,
        "class_counts": {
            "primary": primary_counts,
            "secondary": secondary_counts,
        },
        "confusion_matrix_primary_by_secondary": matrix,
        "status": "PASS" if passed else "FAIL",
    }


def evaluate_reviewer_agreement(
    primary: Mapping[str, Any],
    secondary: Mapping[str, Any],
    *,
    min_overlap: int = 41,
    identity_raw_threshold: float = 0.95,
    identity_kappa_threshold: float = 0.85,
    pricing_raw_threshold: float = 0.90,
    pricing_kappa_threshold: float = 0.80,
) -> dict[str, Any]:
    """Fail closed unless two independent reviewers agree on identical evidence."""

    thresholds = (
        identity_raw_threshold,
        identity_kappa_threshold,
        pricing_raw_threshold,
        pricing_kappa_threshold,
    )
    if min_overlap <= 0:
        raise AcceptanceInputError("minimum reviewer overlap must be positive")
    if any(value < 0.0 or value > 1.0 for value in thresholds):
        raise AcceptanceInputError("reviewer agreement thresholds must be within [0, 1]")

    for role, payload in (("primary", primary), ("secondary", secondary)):
        validation = validate_locked_review_set(payload)
        if validation["status"] != "PASS":
            reasons = sorted({str(row["reason"]) for row in validation["invalid"]})
            raise AcceptanceInputError(
                f"{role} review set is invalid: {', '.join(reasons)}"
            )

    primary_reviewer = _independent_reviewer_id(primary, role="primary")
    secondary_reviewer = _independent_reviewer_id(secondary, role="secondary")
    if primary_reviewer == secondary_reviewer:
        raise AcceptanceInputError(
            "primary and secondary review sets must have different reviewer IDs"
        )

    primary_tasks = {
        str(task.get("review_id") or ""): task for task in _rows(primary, "tasks")
    }
    secondary_tasks = {
        str(task.get("review_id") or ""): task for task in _rows(secondary, "tasks")
    }
    shared_ids = sorted(set(primary_tasks) & set(secondary_tasks))
    comparisons: list[dict[str, str]] = []
    for review_id in shared_ids:
        first = primary_tasks[review_id]
        second = secondary_tasks[review_id]
        if first.get("evidence_sha256") != second.get("evidence_sha256"):
            raise AcceptanceInputError(
                f"review evidence hash mismatch between reviewers for {review_id}"
            )
        first_labels = first.get("labels")
        second_labels = second.get("labels")
        if not isinstance(first_labels, Mapping) or not isinstance(
            second_labels, Mapping
        ):
            continue
        row = {
            "review_id": review_id,
            "evidence_sha256": str(first.get("evidence_sha256") or ""),
            "primary_identity": _identity(first_labels.get("identity_truth")),
            "secondary_identity": _identity(second_labels.get("identity_truth")),
            "primary_pricing": _admission(
                first_labels.get("pricing_admission_truth")
            ),
            "secondary_pricing": _admission(
                second_labels.get("pricing_admission_truth")
            ),
        }
        if all(
            row[key]
            for key in (
                "primary_identity",
                "secondary_identity",
                "primary_pricing",
                "secondary_pricing",
            )
        ):
            comparisons.append(row)

    identity = _agreement_dimension(
        comparisons,
        primary_key="primary_identity",
        secondary_key="secondary_identity",
        classes=("MATCH", "NOT_MATCH", "MANUAL_REVIEW"),
        raw_threshold=identity_raw_threshold,
        kappa_threshold=identity_kappa_threshold,
    ) if comparisons else None
    pricing = _agreement_dimension(
        comparisons,
        primary_key="primary_pricing",
        secondary_key="secondary_pricing",
        classes=("ADMITTED", "EXCLUDED", "MANUAL_REVIEW"),
        raw_threshold=pricing_raw_threshold,
        kappa_threshold=pricing_kappa_threshold,
    ) if comparisons else None
    enough_overlap = len(comparisons) >= min_overlap
    passed = bool(
        enough_overlap
        and identity is not None
        and pricing is not None
        and identity["status"] == "PASS"
        and pricing["status"] == "PASS"
    )
    disagreements = [
        row
        for row in comparisons
        if row["primary_identity"] != row["secondary_identity"]
        or row["primary_pricing"] != row["secondary_pricing"]
    ]
    return {
        "agreement_version": "comparability-independent-review-agreement-v1",
        "status": "PASS" if passed else "FAIL",
        "primary_reviewer_id": primary_reviewer,
        "secondary_reviewer_id": secondary_reviewer,
        "shared_review_ids": len(shared_ids),
        "fully_labeled_overlap": len(comparisons),
        "minimum_required_overlap": min_overlap,
        "minimum_overlap_met": enough_overlap,
        "identity": identity,
        "pricing_admission": pricing,
        "disagreements": disagreements,
        "disagreement_count": len(disagreements),
        "adjudication_required": bool(disagreements),
        "review_instruction_accepted": passed,
        "promotion_authorized": False,
    }


def prepare_reviewer_overlap(
    payload: Mapping[str, Any],
    *,
    selection_seed: str,
    sample_size: int = 41,
) -> dict[str, Any]:
    """Create a blinded deterministic subset for an independent second reviewer."""

    validation = validate_locked_review_set(payload)
    if validation["status"] != "PASS":
        reasons = sorted({str(row["reason"]) for row in validation["invalid"]})
        raise AcceptanceInputError(
            f"source review set is invalid: {', '.join(reasons)}"
        )
    if not selection_seed.strip():
        raise AcceptanceInputError("reviewer-overlap selection seed must be non-empty")
    tasks = _rows(payload, "tasks")
    if sample_size <= 0 or sample_size > len(tasks):
        raise AcceptanceInputError(
            f"reviewer-overlap sample size must be within 1..{len(tasks)}"
        )
    ordered = sorted(
        tasks,
        key=lambda task: hashlib.sha256(
            (
                f"{selection_seed}\0{task.get('review_id')}\0"
                f"{task.get('evidence_sha256')}"
            ).encode("utf-8")
        ).hexdigest(),
    )
    selected = deepcopy(ordered[:sample_size])
    for task in selected:
        task["labels"] = {
            "identity_truth": "",
            "pricing_admission_truth": "",
            "reason_codes": [],
            "evidence_notes": "",
        }
    result = deepcopy(dict(payload))
    result["tasks"] = selected
    result["parent_task_manifest_sha256"] = payload.get("task_manifest_sha256")
    result["task_manifest_sha256"] = _canonical_sha256(
        [
            {
                "review_id": task.get("review_id"),
                "evidence_sha256": task.get("evidence_sha256"),
            }
            for task in selected
        ]
    )
    result["selection"] = {
        "purpose": "independent-second-reviewer-overlap",
        "selection_seed_sha256": hashlib.sha256(
            selection_seed.encode("utf-8")
        ).hexdigest(),
        "source_tasks": len(tasks),
        "selected_tasks": sample_size,
        "sampling_fraction": round(sample_size / len(tasks), 6),
        "algorithm": "sha256-deterministic-sample-v1",
    }
    result["review_attestation"] = {
        "reviewer_id": "",
        "reviewer_role": "",
        "reviewed_at": "",
        "independence_attested": False,
        "required_statement": _INDEPENDENCE_ATTESTATION,
    }
    for key in ("label_import", "review_csv", "review_html"):
        result.pop(key, None)
    return result


def finalize_locked_truth(
    payload: Mapping[str, Any],
    *,
    selection_seed: str,
) -> dict[str, Any]:
    validation = validate_locked_review_set(payload, require_complete=True)
    if validation["status"] != "PASS":
        raise AcceptanceInputError("review set is not complete and valid")
    if not selection_seed.strip():
        raise AcceptanceInputError("finalization seed must be non-empty")
    tasks = _rows(payload, "tasks")
    matches: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    seen_seed_groups: set[str] = set()
    seen_candidates: set[str] = set()
    ordered = sorted(
        tasks,
        key=lambda task: hashlib.sha256(
            f"{selection_seed}\0{task['pair_fingerprint']}".encode("utf-8")
        ).hexdigest(),
    )
    for task in ordered:
        seed_group = str(task["seed_group_fingerprint"])
        candidate = str(task["candidate_family_fingerprint"])
        if seed_group in seen_seed_groups or candidate in seen_candidates:
            continue
        labels = task["labels"]
        identity = _identity(labels["identity_truth"])
        if identity == "MATCH":
            matches.append(task)
        elif identity == "NOT_MATCH":
            negatives.append(task)
        seen_seed_groups.add(seed_group)
        seen_candidates.add(candidate)

    eligible_matches = [
        task
        for task in matches
        if _admission(task["labels"]["pricing_admission_truth"]) == "ADMITTED"
    ]
    ineligible_matches = [
        task
        for task in matches
        if _admission(task["labels"]["pricing_admission_truth"]) == "EXCLUDED"
    ]
    if len(eligible_matches) < 50 or len(ineligible_matches) < 50:
        raise AcceptanceInputError(
            "locked set needs >=50 pricing-eligible and >=50 pricing-ineligible "
            "unique MATCH seed groups"
        )
    if len(negatives) < 300:
        raise AcceptanceInputError(
            "locked set needs >=300 unique NOT_MATCH seed groups and candidates"
        )
    selected = [*eligible_matches[:50], *ineligible_matches[:50], *negatives[:300]]
    labels = [
        {
            "pair_id": task["review_id"],
            "identity_truth": _identity(task["labels"]["identity_truth"]),
            "pricing_admission_truth": _admission(
                task["labels"]["pricing_admission_truth"]
            ),
            "evidence_sha256": task["evidence_sha256"],
            "reason_codes": list(task["labels"].get("reason_codes") or []),
        }
        for task in selected
    ]
    result: dict[str, Any] = {
        "schema_version": _LOCKED_TRUTH_SCHEMA_VERSION,
        "identity_fingerprint_version": _REVIEW_IDENTITY_FINGERPRINT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "source_review_set_sha256": _canonical_sha256(payload),
        "selection_seed_sha256": hashlib.sha256(
            selection_seed.encode("utf-8")
        ).hexdigest(),
        "selection_contract": {
            "true_matches": 100,
            "hard_negatives": 300,
            "pricing_eligible_matches": 50,
            "pricing_ineligible_matches": 50,
            "max_pairs_per_seed_group": 1,
            "max_pairs_per_candidate": 1,
            "max_pairs_per_candidate_family": 1,
        },
        "review_attestation": dict(payload["review_attestation"]),
        "labels": labels,
        "promotion_authorized": False,
    }
    result["truth_sha256"] = _canonical_sha256(labels)
    return result


def _gate(name: str, passed: bool, actual: object, required: object) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "actual": actual,
        "required": required,
    }


def _operational_metrics(predictions: Mapping[str, Any]) -> dict[str, Any]:
    value = predictions.get("operational_metrics")
    return dict(value) if isinstance(value, dict) else {}


def evaluate_acceptance(
    truth_payload: Mapping[str, Any],
    prediction_payload: Mapping[str, Any],
    *,
    profile: str,
) -> dict[str, Any]:
    truth = _pair_map(_rows(truth_payload, "labels"), source="truth")
    predictions = _pair_map(
        _rows(prediction_payload, "pairs"),
        source="prediction",
    )
    if set(truth) != set(predictions):
        raise AcceptanceInputError(
            "truth/prediction pair IDs differ: "
            f"missing={sorted(set(truth) - set(predictions))}, "
            f"extra={sorted(set(predictions) - set(truth))}"
        )

    positive = negative = 0
    false_matches = false_not_matches = automatic_matches = automatic = 0
    abstentions = 0
    pricing_eligible = pricing_ineligible = admitted_eligible = unsafe_admitted = 0
    normalized_rows: list[dict[str, Any]] = []
    for pair_id in sorted(truth):
        truth_row = truth[pair_id]
        predicted_row = predictions[pair_id]
        identity_truth = _identity(truth_row.get("identity_truth"))
        identity_prediction = _identity(predicted_row.get("identity_verdict"))
        pricing_truth = _admission(
            truth_row.get("pricing_admission_truth")
            or truth_row.get("pricing_comparability_truth")
        )
        pricing_prediction = _admission(
            predicted_row.get("pricing_admission")
            or predicted_row.get("pricing_comparability")
        )
        if identity_truth not in {"MATCH", "NOT_MATCH"}:
            raise AcceptanceInputError(
                f"truth {pair_id} has unsupported identity_truth {identity_truth!r}"
            )
        if identity_prediction not in _IDENTITY_VALUES:
            raise AcceptanceInputError(
                f"prediction {pair_id} has invalid identity_verdict "
                f"{identity_prediction!r}"
            )
        if pricing_truth not in _ADMISSION_VALUES:
            raise AcceptanceInputError(
                f"truth {pair_id} has invalid pricing truth {pricing_truth!r}"
            )
        if pricing_prediction not in _ADMISSION_VALUES:
            raise AcceptanceInputError(
                f"prediction {pair_id} has invalid pricing admission "
                f"{pricing_prediction!r}"
            )

        if identity_truth == "MATCH":
            positive += 1
            if identity_prediction == "MATCH":
                automatic_matches += 1
            elif identity_prediction == "NOT_MATCH":
                false_not_matches += 1
        else:
            negative += 1
            if identity_prediction == "MATCH":
                false_matches += 1
        if identity_prediction == "MANUAL_REVIEW":
            abstentions += 1
        else:
            automatic += 1
        if identity_truth == "MATCH" and pricing_truth == "ADMITTED":
            pricing_eligible += 1
            if pricing_prediction == "ADMITTED":
                admitted_eligible += 1
        if identity_truth == "MATCH" and pricing_truth == "EXCLUDED":
            pricing_ineligible += 1
            if pricing_prediction == "ADMITTED":
                unsafe_admitted += 1
        normalized_rows.append(
            {
                "pair_id": pair_id,
                "identity_truth": identity_truth,
                "identity_prediction": identity_prediction,
                "pricing_truth": pricing_truth,
                "pricing_prediction": pricing_prediction,
            }
        )

    false_match_rate = _ratio(false_matches, negative)
    upper_95 = _zero_event_upper_95(negative) if false_matches == 0 else None
    recall = _ratio(automatic_matches, positive)
    coverage = _ratio(automatic, len(truth))
    abstention_rate = _ratio(abstentions, len(truth))
    pricing_recall = _ratio(admitted_eligible, pricing_eligible)
    operational = _operational_metrics(prediction_payload)

    gates: list[dict[str, Any]] = []
    if profile == "smoke":
        gates.extend(
            [
                _gate("automatic_false_matches", false_matches == 0, false_matches, 0),
                _gate(
                    "automatic_false_not_matches",
                    false_not_matches == 0,
                    false_not_matches,
                    0,
                ),
                _gate(
                    "complete_pair_accounting",
                    len(normalized_rows) == len(truth),
                    len(normalized_rows),
                    len(truth),
                ),
            ]
        )
        passed = all(item["passed"] for item in gates)
        status = "SMOKE_REGRESSION_PASS" if passed else "SMOKE_REGRESSION_FAIL"
        promotion_eligible = False
    elif profile == "locked":
        provider_requests = int(operational.get("provider_requests") or 0)
        valid_terminal = int(operational.get("valid_terminal_results") or 0)
        owned = int(operational.get("owned_store_candidates") or 0)
        owned_excluded = int(operational.get("owned_store_excluded") or 0)
        duplicates = int(operational.get("duplicate_seller_candidates") or 0)
        duplicates_excluded = int(operational.get("duplicate_seller_excluded") or 0)
        gates.extend(
            [
                _gate("locked_true_matches", positive == 100, positive, 100),
                _gate("locked_hard_negatives", negative == 300, negative, 300),
                _gate("false_matches", false_matches == 0, false_matches, 0),
                _gate(
                    "false_match_upper_95",
                    upper_95 is not None and upper_95 < Decimal("0.01"),
                    str(upper_95) if upper_95 is not None else "NOT_PROVEN",
                    "<0.01",
                ),
                _gate(
                    "false_not_matches",
                    false_not_matches == 0,
                    false_not_matches,
                    0,
                ),
                _gate(
                    "automatic_match_recall",
                    recall is not None and recall >= Decimal("0.70"),
                    str(recall) if recall is not None else "NOT_EVALUATED",
                    ">=0.70",
                ),
                _gate(
                    "automatic_decision_coverage",
                    coverage is not None and coverage >= Decimal("0.75"),
                    str(coverage) if coverage is not None else "NOT_EVALUATED",
                    ">=0.75",
                ),
                _gate(
                    "pricing_eligible_sample",
                    pricing_eligible >= 50,
                    pricing_eligible,
                    ">=50",
                ),
                _gate(
                    "pricing_ineligible_sample",
                    pricing_ineligible >= 50,
                    pricing_ineligible,
                    ">=50",
                ),
                _gate("unsafe_admitted", unsafe_admitted == 0, unsafe_admitted, 0),
                _gate(
                    "pricing_eligible_admission_rate",
                    pricing_recall is not None and pricing_recall >= Decimal("0.70"),
                    (
                        str(pricing_recall)
                        if pricing_recall is not None
                        else "NOT_EVALUATED"
                    ),
                    ">=0.70",
                ),
                _gate(
                    "owned_store_exclusion",
                    owned > 0 and owned_excluded == owned,
                    f"{owned_excluded}/{owned}",
                    "100% and denominator > 0",
                ),
                _gate(
                    "seller_deduplication",
                    duplicates > 0 and duplicates_excluded == duplicates,
                    f"{duplicates_excluded}/{duplicates}",
                    "100% and denominator > 0",
                ),
                _gate(
                    "provider_terminal_rate",
                    provider_requests > 0
                    and Decimal(valid_terminal) / Decimal(provider_requests)
                    >= Decimal("0.98"),
                    f"{valid_terminal}/{provider_requests}",
                    ">=0.98",
                ),
                _gate(
                    "provider_budget_exhausted",
                    int(operational.get("provider_budget_exhausted") or 0) == 0,
                    int(operational.get("provider_budget_exhausted") or 0),
                    0,
                ),
                _gate(
                    "candidate_terminal_accounting",
                    int(operational.get("candidate_terminal_results") or 0)
                    == len(truth),
                    int(operational.get("candidate_terminal_results") or 0),
                    len(truth),
                ),
            ]
        )
        passed = all(item["passed"] for item in gates)
        status = "LOCKED_ACCEPT" if passed else "LOCKED_REJECT"
        promotion_eligible = passed
    elif profile == "shadow":
        provider_requests = int(operational.get("provider_requests") or 0)
        valid_terminal = int(operational.get("valid_terminal_results") or 0)
        gates.extend(
            [
                _gate(
                    "shadow_product_count",
                    int(operational.get("product_count") or 0) == 200,
                    int(operational.get("product_count") or 0),
                    200,
                ),
                _gate(
                    "all_candidates_labelled",
                    int(operational.get("labelled_candidates") or 0) == len(truth),
                    int(operational.get("labelled_candidates") or 0),
                    len(truth),
                ),
                _gate(
                    "shadow_parity_mismatches",
                    int(operational.get("shadow_parity_mismatches") or 0) == 0,
                    int(operational.get("shadow_parity_mismatches") or 0),
                    0,
                ),
                _gate(
                    "provider_terminal_rate",
                    provider_requests > 0
                    and Decimal(valid_terminal) / Decimal(provider_requests)
                    >= Decimal("0.98"),
                    f"{valid_terminal}/{provider_requests}",
                    ">=0.98",
                ),
                _gate(
                    "provider_budget_exhausted",
                    int(operational.get("provider_budget_exhausted") or 0) == 0,
                    int(operational.get("provider_budget_exhausted") or 0),
                    0,
                ),
            ]
        )
        passed = all(item["passed"] for item in gates)
        status = "SHADOW_ACCEPT" if passed else "SHADOW_REJECT"
        promotion_eligible = passed
    else:
        raise AcceptanceInputError(f"unknown profile {profile!r}")

    return {
        "evaluation_version": "comparability-acceptance-v1",
        "profile": profile,
        "status": status,
        "promotion_eligible": promotion_eligible,
        "dataset": {
            "pairs": len(truth),
            "true_matches": positive,
            "hard_negatives": negative,
            "truth_sha256": _canonical_sha256(truth_payload),
            "predictions_sha256": _canonical_sha256(prediction_payload),
        },
        "metrics": {
            "false_match_count": false_matches,
            "false_match_rate": (
                str(false_match_rate)
                if false_match_rate is not None
                else "NOT_EVALUATED"
            ),
            "zero_event_false_match_upper_95": (
                str(upper_95) if upper_95 is not None else "NOT_PROVEN"
            ),
            "false_not_match_count": false_not_matches,
            "automatic_match_recall": (
                str(recall) if recall is not None else "NOT_EVALUATED"
            ),
            "automatic_decision_coverage": (
                str(coverage) if coverage is not None else "NOT_EVALUATED"
            ),
            "abstention_rate": (
                str(abstention_rate) if abstention_rate is not None else "NOT_EVALUATED"
            ),
            "pricing_eligible_count": pricing_eligible,
            "pricing_ineligible_count": pricing_ineligible,
            "unsafe_admitted_count": unsafe_admitted,
            "pricing_eligible_admission_rate": (
                str(pricing_recall) if pricing_recall is not None else "NOT_EVALUATED"
            ),
        },
        "gates": gates,
        "rows": normalized_rows,
        "note": (
            "Smoke data is regression-only and is never a promotion denominator."
            if profile == "smoke"
            else None
        ),
    }


def verify_catalog_manifest(
    payload: Mapping[str, Any],
    expected_rows: int,
    *,
    require_pricing_replay: bool = False,
) -> dict[str, Any]:
    rows = _rows(payload, "rows")
    ordinals: set[int] = set()
    source_rows: set[int] = set()
    invalid: list[dict[str, Any]] = []
    for row in rows:
        try:
            source_row = int(row.get("source_row"))
        except (TypeError, ValueError):
            invalid.append(
                {"source_row": row.get("source_row"), "reason": "INVALID_ROW"}
            )
            continue
        try:
            ordinal = int(row.get("source_ordinal", source_row))
        except (TypeError, ValueError):
            invalid.append(
                {"source_row": source_row, "reason": "INVALID_SOURCE_ORDINAL"}
            )
            continue
        status = str(row.get("terminal_status") or "")
        if source_row in source_rows:
            invalid.append({"source_row": source_row, "reason": "DUPLICATE_ROW"})
        if ordinal in ordinals:
            invalid.append(
                {"source_row": source_row, "reason": "DUPLICATE_SOURCE_ORDINAL"}
            )
        source_rows.add(source_row)
        ordinals.add(ordinal)
        if status not in _TERMINAL_CATALOG_RESULTS:
            invalid.append({"source_row": source_row, "reason": "NON_TERMINAL_STATUS"})
        if status == "REJECTED_NOT_IMPORTABLE" and not row.get("reason_codes"):
            invalid.append(
                {"source_row": source_row, "reason": "REJECTION_UNEXPLAINED"}
            )
        if require_pricing_replay:
            if row.get("pricing_terminal") is not True:
                invalid.append(
                    {"source_row": source_row, "reason": "PRICING_NOT_TERMINAL"}
                )
            if status == "IMPORTED" and not row.get("pricing_run_item_id"):
                invalid.append(
                    {"source_row": source_row, "reason": "PRICING_RUN_ITEM_MISSING"}
                )
    if require_pricing_replay and not payload.get("pricing_run_id"):
        invalid.append({"source_row": None, "reason": "PRICING_RUN_ID_MISSING"})
    if require_pricing_replay and payload.get("pricing_replay_complete") is not True:
        invalid.append({"source_row": None, "reason": "PRICING_REPLAY_NOT_COMPLETE"})
    missing = sorted(set(range(1, expected_rows + 1)) - ordinals)
    passed = len(rows) == expected_rows and not missing and not invalid
    return {
        "verification_version": "catalog-terminal-manifest-v1",
        "status": "PASS" if passed else "FAIL",
        "expected_rows": expected_rows,
        "pricing_replay_required": require_pricing_replay,
        "manifest_rows": len(rows),
        "missing_source_ordinals": missing,
        "missing_source_rows": missing,
        "invalid_rows": invalid,
        "silent_loss_count": len(missing),
    }


def verify_shadow_parity(
    off_payload: Mapping[str, Any],
    shadow_payload: Mapping[str, Any],
) -> dict[str, Any]:
    off = _pair_map(_rows(off_payload, "rows"), source="off")
    shadow = _pair_map(_rows(shadow_payload, "rows"), source="shadow")
    fields = ("recommendation_hash", "cohort_hash", "p_min_hash")
    mismatches: list[dict[str, Any]] = []
    for pair_id in sorted(set(off) | set(shadow)):
        left = off.get(pair_id)
        right = shadow.get(pair_id)
        if left is None or right is None:
            mismatches.append({"pair_id": pair_id, "field": "ROW_PRESENCE"})
            continue
        for field in fields:
            if left.get(field) != right.get(field):
                mismatches.append(
                    {
                        "pair_id": pair_id,
                        "field": field,
                        "off": left.get(field),
                        "shadow": right.get(field),
                    }
                )
    return {
        "verification_version": "comparability-shadow-parity-v1",
        "status": "PASS" if not mismatches else "FAIL",
        "rows": len(off),
        "mismatches": mismatches,
    }


def _budget(products: int, pilot_p95: str) -> dict[str, Any]:
    try:
        p95 = Decimal(pilot_p95)
    except InvalidOperation as exc:
        raise AcceptanceInputError("pilot p95 cost must be a decimal") from exc
    if products <= 0 or p95 < 0:
        raise AcceptanceInputError(
            "products must be positive and p95 cost non-negative"
        )
    budget = Decimal("1.25") * Decimal(products) * p95
    return {
        "budget_version": "post-pilot-budget-v1",
        "products": products,
        "pilot_p95_cost_per_product_usd": str(p95),
        "multiplier": "1.25",
        "stage_budget_usd": str(budget),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comparability-acceptance")
    commands = parser.add_subparsers(dest="command", required=True)

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--root", required=True, type=Path)
    freeze.add_argument("--git-root", type=Path)
    freeze.add_argument("--output", type=Path)
    freeze.add_argument("--expected-baseline-sha")
    freeze.add_argument("--model", default="gpt-5.6-luna")
    freeze.add_argument("--reasoning-effort", default="xhigh")

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--truth", required=True, type=Path)
    evaluate.add_argument("--predictions", required=True, type=Path)
    evaluate.add_argument(
        "--profile", choices=("smoke", "locked", "shadow"), required=True
    )
    evaluate.add_argument("--output", type=Path)

    semantic = commands.add_parser("evaluate-semantic-gate")
    semantic.add_argument("--benchmark", required=True, type=Path)
    semantic.add_argument("--truth", required=True, type=Path)
    semantic.add_argument("--output", type=Path)

    prepare_review = commands.add_parser("prepare-locked-review-set")
    prepare_review.add_argument(
        "--source-csv", required=True, action="append", type=Path
    )
    prepare_review.add_argument(
        "--exclude-development-benchmark", action="append", type=Path, default=[]
    )
    prepare_review.add_argument("--selection-seed", required=True)
    prepare_review.add_argument("--max-pairs", type=int, default=0)
    prepare_review.add_argument("--csv-output", type=Path)
    prepare_review.add_argument("--html-output", type=Path)
    prepare_review.add_argument("--output", type=Path)

    import_review = commands.add_parser("import-locked-review-csv")
    import_review.add_argument("--review-set", required=True, type=Path)
    import_review.add_argument("--labels-csv", required=True, type=Path)
    import_review.add_argument("--reviewer-id", required=True)
    import_review.add_argument("--reviewer-role", required=True)
    import_review.add_argument("--reviewed-at", required=True)
    import_review.add_argument("--attest-independent", action="store_true")
    import_review.add_argument("--output", type=Path)

    validate_review = commands.add_parser("validate-locked-review-set")
    validate_review.add_argument("--review-set", required=True, type=Path)
    validate_review.add_argument("--require-complete", action="store_true")
    validate_review.add_argument("--output", type=Path)

    finalize_review = commands.add_parser("finalize-locked-truth")
    finalize_review.add_argument("--review-set", required=True, type=Path)
    finalize_review.add_argument("--selection-seed", required=True)
    finalize_review.add_argument("--output", type=Path)

    agreement = commands.add_parser("evaluate-reviewer-agreement")
    agreement.add_argument("--primary-review-set", required=True, type=Path)
    agreement.add_argument("--secondary-review-set", required=True, type=Path)
    agreement.add_argument("--min-overlap", type=int, default=41)
    agreement.add_argument("--identity-raw-threshold", type=float, default=0.95)
    agreement.add_argument("--identity-kappa-threshold", type=float, default=0.85)
    agreement.add_argument("--pricing-raw-threshold", type=float, default=0.90)
    agreement.add_argument("--pricing-kappa-threshold", type=float, default=0.80)
    agreement.add_argument("--output", type=Path)

    overlap = commands.add_parser("prepare-reviewer-overlap")
    overlap.add_argument("--review-set", required=True, type=Path)
    overlap.add_argument("--selection-seed", required=True)
    overlap.add_argument("--sample-size", type=int, default=41)
    overlap.add_argument("--csv-output", type=Path)
    overlap.add_argument("--html-output", type=Path)
    overlap.add_argument("--output", type=Path)

    catalog = commands.add_parser("verify-catalog-manifest")
    catalog.add_argument("--manifest", required=True, type=Path)
    catalog.add_argument("--expected-rows", required=True, type=int)
    catalog.add_argument("--require-pricing-replay", action="store_true")
    catalog.add_argument("--output", type=Path)

    parity = commands.add_parser("verify-shadow-parity")
    parity.add_argument("--off", required=True, type=Path)
    parity.add_argument("--shadow", required=True, type=Path)
    parity.add_argument("--output", type=Path)

    budget = commands.add_parser("budget")
    budget.add_argument("--products", required=True, type=int)
    budget.add_argument("--pilot-p95-cost-usd", required=True)
    budget.add_argument("--output", type=Path)

    activation = commands.add_parser("build-activation-artifact")
    activation.add_argument("--locked-result", required=True, type=Path)
    activation.add_argument("--shadow-result", required=True, type=Path)
    activation.add_argument("--runtime-identity", required=True, type=Path)
    activation.add_argument("--product-owner-id", required=True)
    activation.add_argument("--risk-owner-id", required=True)
    activation.add_argument("--approved-at", required=True)
    activation.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "freeze":
            payload = build_freeze_manifest(
                args.root,
                git_root=args.git_root,
                output=args.output,
                expected_baseline_sha=args.expected_baseline_sha,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
            )
        elif args.command == "evaluate":
            payload = evaluate_acceptance(
                _load_object(args.truth),
                _load_object(args.predictions),
                profile=args.profile,
            )
        elif args.command == "evaluate-semantic-gate":
            payload = evaluate_semantic_gate(
                _load_object(args.benchmark),
                _load_object(args.truth),
            )
        elif args.command == "prepare-locked-review-set":
            payload = prepare_locked_review_set(
                args.source_csv,
                development_payloads=[
                    _load_object(path) for path in args.exclude_development_benchmark
                ],
                selection_seed=args.selection_seed,
                max_pairs=args.max_pairs,
            )
            if args.csv_output is not None:
                payload["review_csv"] = write_locked_review_csv(
                    payload, args.csv_output
                )
            if args.html_output is not None:
                payload["review_html"] = write_locked_review_html(
                    payload, args.html_output
                )
        elif args.command == "import-locked-review-csv":
            payload = import_locked_review_csv(
                _load_object(args.review_set),
                args.labels_csv,
                reviewer_id=args.reviewer_id,
                reviewer_role=args.reviewer_role,
                reviewed_at=args.reviewed_at,
                independence_attested=args.attest_independent,
            )
        elif args.command == "validate-locked-review-set":
            payload = validate_locked_review_set(
                _load_object(args.review_set),
                require_complete=args.require_complete,
            )
        elif args.command == "finalize-locked-truth":
            payload = finalize_locked_truth(
                _load_object(args.review_set),
                selection_seed=args.selection_seed,
            )
        elif args.command == "evaluate-reviewer-agreement":
            payload = evaluate_reviewer_agreement(
                _load_object(args.primary_review_set),
                _load_object(args.secondary_review_set),
                min_overlap=args.min_overlap,
                identity_raw_threshold=args.identity_raw_threshold,
                identity_kappa_threshold=args.identity_kappa_threshold,
                pricing_raw_threshold=args.pricing_raw_threshold,
                pricing_kappa_threshold=args.pricing_kappa_threshold,
            )
        elif args.command == "prepare-reviewer-overlap":
            payload = prepare_reviewer_overlap(
                _load_object(args.review_set),
                selection_seed=args.selection_seed,
                sample_size=args.sample_size,
            )
            if args.csv_output is not None:
                payload["review_csv"] = write_locked_review_csv(
                    payload, args.csv_output
                )
            if args.html_output is not None:
                payload["review_html"] = write_locked_review_html(
                    payload, args.html_output
                )
        elif args.command == "verify-catalog-manifest":
            payload = verify_catalog_manifest(
                _load_object(args.manifest),
                args.expected_rows,
                require_pricing_replay=args.require_pricing_replay,
            )
        elif args.command == "verify-shadow-parity":
            payload = verify_shadow_parity(
                _load_object(args.off),
                _load_object(args.shadow),
            )
        elif args.command == "build-activation-artifact":
            try:
                payload = build_comparability_activation_payload(
                    locked_acceptance_result=_load_object(args.locked_result),
                    shadow_acceptance_result=_load_object(args.shadow_result),
                    runtime_identity={
                        str(key): str(value)
                        for key, value in _load_object(
                            args.runtime_identity
                        ).items()
                    },
                    product_owner_id=args.product_owner_id,
                    risk_owner_id=args.risk_owner_id,
                    approved_at=args.approved_at,
                )
            except ValueError as exc:
                raise AcceptanceInputError(str(exc)) from exc
        else:
            payload = _budget(args.products, args.pilot_p95_cost_usd)
    except AcceptanceInputError as exc:
        sys.stderr.write(f"comparability acceptance input error: {exc}\n")
        return 2
    _write_or_print(payload, args.output)
    status = str(payload.get("status") or "PASS")
    return (
        0
        if status
        in {
            "PASS",
            "SMOKE_REGRESSION_PASS",
            "SEMANTIC_GATE_SMOKE_PASS",
            "LOCKED_ACCEPT",
            "SHADOW_ACCEPT",
        }
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
