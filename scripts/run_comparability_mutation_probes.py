#!/usr/bin/env python3
"""Run critical comparability mutations against an isolated Metis copy."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PYTHON = BACKEND / ".venv" / "bin" / "python"


@dataclass(frozen=True)
class Mutation:
    mutation_id: str
    relative_file: str
    replacements: tuple[tuple[str, str], ...]
    test_node: str


MUTATIONS = (
    Mutation(
        "unknown_dimension_treated_as_match",
        "metis/pricing/comparability.py",
        (
            (
                "passed = state == EvidenceState.MATCH or (",
                "passed = state in {EvidenceState.MATCH, EvidenceState.UNKNOWN} or (",
            ),
        ),
        "tests/test_comparability_contract.py::test_m021_removing_any_required_dimension_revokes_automatic",
    ),
    Mutation(
        "conflict_not_classified_as_conflict",
        "metis/pricing/comparability.py",
        (("if state == EvidenceState.CONFLICT:", "if False:"),),
        "tests/test_comparability_contract.py::test_m001_m013_hard_dimensions_never_auto",
    ),
    Mutation(
        "seller_identity_verification_bypassed",
        "metis/pricing/comparability.py",
        (
            ("evidence.seller_identity.verified", "True"),
            (
                "and stable_id\n        and evidence.seller_identity.identity_source",
                "and True\n        and evidence.seller_identity.identity_source",
            ),
            ("and stable_id == caller_id", "and True"),
        ),
        "tests/test_comparability_contract.py::test_blank_or_mismatched_seller_identity_fails_direct_gate",
    ),
    Mutation(
        "missing_raw_currency_inferred_from_normalized",
        "metis/pricing/comparability.py",
        (
            (
                "currency_present = bool(raw_currency)",
                "currency_present = bool(raw_currency or normalized_currency)",
            ),
        ),
        "tests/test_comparability_contract.py::test_m018_missing_raw_currency_does_not_default_to_uah",
    ),
    Mutation(
        "unknown_source_type_trusted",
        "metis/pricing/comparability.py",
        (
            (
                '(provenance.source_type or "").strip() in RECOGNIZED_SOURCE_TYPES',
                "True",
            ),
        ),
        "tests/test_comparability_contract.py::test_m014_unknown_source_cannot_be_faked_by_confidence",
    ),
    Mutation(
        "missing_provenance_hash_trusted",
        "metis/pricing/comparability.py",
        (("and _SHA256_RE.fullmatch(raw_hash)", "and True"),),
        "tests/test_comparability_contract.py::test_m015_missing_source_hash_abstains",
    ),
    Mutation(
        "engine_skips_comparability_gate",
        "metis/pricing/engine.py",
        (
            (
                "if not comparability.automatic_eligible:",
                "if False and not comparability.automatic_eligible:",
            ),
        ),
        "tests/test_comparability_contract.py::test_m025_original_raise_920_payload_is_killed",
    ),
)


def _apply_mutation(path: Path, replacements: tuple[tuple[str, str], ...]) -> None:
    content = path.read_text(encoding="utf-8")
    for original, replacement in replacements:
        count = content.count(original)
        if count != 1:
            raise RuntimeError(
                f"mutation anchor count for {path.name} is {count}, expected 1: {original}"
            )
        content = content.replace(original, replacement, 1)
    path.write_text(content, encoding="utf-8")


def run_mutation_probes() -> dict[str, object]:
    results: list[dict[str, object]] = []
    for mutation in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix="marko-comparability-mutation-") as temp:
            temporary_src = Path(temp) / "src"
            shutil.copytree(BACKEND / "src" / "metis", temporary_src / "metis")
            _apply_mutation(
                temporary_src / mutation.relative_file, mutation.replacements
            )
            environment = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    (str(temporary_src), str(BACKEND / "src"))
                ),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            completed = subprocess.run(
                (str(PYTHON), "-m", "pytest", "-q", mutation.test_node),
                cwd=BACKEND,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            combined = f"{completed.stdout}\n{completed.stderr}"
            if completed.returncode == 0:
                status = "SURVIVED"
            elif "failed" in combined and "ERROR" not in combined:
                status = "KILLED"
            else:
                status = "INVALID"
            results.append(
                {
                    "mutation_id": mutation.mutation_id,
                    "status": status,
                    "test_node": mutation.test_node,
                    "return_code": completed.returncode,
                }
            )
    passed = all(result["status"] == "KILLED" for result in results)
    return {
        "schema_version": "comparability-mutation-report-v1",
        "mutation_probe_status": "PASS" if passed else "FAIL",
        "critical_mutations_survived": sum(
            result["status"] == "SURVIVED" for result in results
        ),
        "mutations": results,
        "production_files_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_mutation_probes()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if report["mutation_probe_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
