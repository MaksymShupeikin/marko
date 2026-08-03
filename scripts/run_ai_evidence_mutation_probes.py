#!/usr/bin/env python3
"""Kill the safety-critical AI-evidence mutants in isolated source copies.

The production checkout is never edited.  Every probe imports its mutated
module in a fresh process, prints the resolved module path, proves the mutant
replacement is present in that file, and only then runs the named regression
test against the isolated package.
"""

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


@dataclass(frozen=True, slots=True)
class Mutation:
    mutation_id: str
    relative_file: str
    module: str
    original: str
    replacement: str
    test_node: str


MUTATIONS = (
    Mutation(
        "bypass_exact_excerpt_verification",
        "marko/services/ai_evidence_verification.py",
        "marko.services.ai_evidence_verification",
        "if candidate.source_excerpt not in source_text:",
        "if False and candidate.source_excerpt not in source_text:",
        "tests/test_ai_evidence_verification.py::test_fabricated_excerpt_is_rejected",
    ),
    Mutation(
        "trust_model_normalized_oe",
        "marko/services/ai_evidence_verification.py",
        "marko.services.ai_evidence_verification",
        "raw_value=candidate.raw_value,\n        excerpt=candidate.source_excerpt,",
        "raw_value=candidate.normalized_value or candidate.raw_value,\n"
        "        excerpt=candidate.source_excerpt,",
        "tests/test_ai_evidence_verification.py::test_oe_is_normalized_by_our_code_not_by_the_model",
    ),
    Mutation(
        "override_deterministic_conflict",
        "marko/services/ai_evidence_verification.py",
        "marko.services.ai_evidence_verification",
        "if current is not None and current.state is EvidenceState.CONFLICT:",
        "if False and current is not None and current.state is EvidenceState.CONFLICT:",
        "tests/test_ai_evidence_verification.py::test_deterministic_conflict_cannot_be_overridden",
    ),
    Mutation(
        "set_automatic_eligible_from_ai",
        "marko/services/ai_evidence_verification.py",
        "marko.services.ai_evidence_verification",
        "authority_changes: Mapping[str, Any] = field(default_factory=dict)",
        "authority_changes: Mapping[str, Any] = field(\n"
        '        default_factory=lambda: {"automatic_eligible": True}\n'
        "    )",
        "tests/test_ai_evidence_verification.py::test_shadow_fill_never_moves_eligibility_or_authority",
    ),
    Mutation(
        "missing_key_still_posts",
        "marko/services/ai_evidence_provider.py",
        "marko.services.ai_evidence_provider",
        "if not api_key:",
        "if False and not api_key:",
        "tests/test_ai_evidence_provider.py::test_missing_budget_or_key_makes_zero_requests",
    ),
    Mutation(
        "retry_skips_budget_reservation",
        "marko/services/llm_call_budget.py",
        "marko.services.llm_call_budget",
        "if not await self.budget.reserve():",
        "if self.made == 0 and not await self.budget.reserve():",
        "tests/test_ai_evidence_provider.py::test_every_post_and_retry_reserves_before_transmission",
    ),
    Mutation(
        "replay_reuses_first_physical_budget_slot",
        "marko/services/llm_call_budget.py",
        "marko.services.llm_call_budget",
        "    async def _reserve_next(self) -> bool:\n"
        "        if not await self.budget.reserve():\n",
        "    async def _reserve_next(self) -> bool:\n"
        "        if self.made == 0:\n"
        "            return True\n"
        "        if not await self.budget.reserve():\n",
        "tests/test_ai_evidence_provider.py::test_crash_replay_spends_a_new_slot_and_reuses_idempotency_key",
    ),
    Mutation(
        "omit_capture_hash_from_request_identity",
        "marko/services/ai_evidence_runtime.py",
        "marko.services.ai_evidence_runtime",
        '"capture_sha256": binding["capture_content_sha256"],',
        '"capture_sha256": "omitted",',
        "tests/test_ai_evidence_runtime.py::test_every_bound_runtime_input_fact_changes_request_identity[capture_content_sha256]",
    ),
    Mutation(
        "bypass_prepared_input_digest_verification",
        "marko/services/ai_evidence_verification.py",
        "marko.services.ai_evidence_verification",
        "if binding.input_sha256 != expected.input_sha256:",
        "if False and binding.input_sha256 != expected.input_sha256:",
        "tests/test_ai_evidence_verification.py::test_input_digest_is_recomputed_from_rows_and_target_fields",
    ),
    Mutation(
        "accept_oe_fragment_inside_longer_token",
        "marko/services/ai_evidence_verification.py",
        "marko.services.ai_evidence_verification",
        'rf"(?<![^\\W_]){token_pattern}(?![^\\W_])",',
        'rf"{token_pattern}",',
        "tests/test_ai_evidence_verification.py::test_oe_fragment_next_to_unicode_alphanumeric_is_refused",
    ),
    Mutation(
        "persist_provider_controlled_usage_details",
        "marko/services/ai_evidence_provider.py",
        "marko.services.ai_evidence_provider",
        "bounded: dict[str, Any] = {}",
        "bounded: dict[str, Any] = dict(value)",
        "tests/test_ai_evidence_provider.py::test_every_post_and_retry_reserves_before_transmission",
    ),
    Mutation(
        "invent_oe_target_from_empty_identity_column",
        "marko/services/ai_evidence_shadow.py",
        "marko.services.ai_evidence_shadow",
        "    return frozenset(fields)\n",
        "    if not tuple(observation.extracted_oe_norms or ()):\n"
        "        fields.add(EvidenceFieldName.OE_NUMBERS)\n"
        "    return frozenset(fields)\n",
        "tests/test_ai_evidence_shadow.py::test_known_oe_dimension_never_becomes_ai_target_from_empty_identity_column",
    ),
    Mutation(
        "trust_self_asserted_offer_hash",
        "marko/services/ai_evidence_verification.py",
        "marko.services.ai_evidence_verification",
        "        and recomputed_sha == offer_sha\n",
        "        and offer_sha == offer_sha\n",
        "tests/test_ai_evidence_verification.py::test_self_consistent_locator_cannot_disagree_with_retained_offer_bytes",
    ),
    Mutation(
        "cache_failed_terminal_as_success",
        "marko/services/ai_evidence_runtime.py",
        "marko.services.ai_evidence_runtime",
        "def _cache_row(\n"
        "    *, source: AiEvidenceExtraction, attempt_no: int\n"
        ") -> AiEvidenceExtraction:\n"
        '    if source.status != "COMPLETED" or source.raw_output is None:\n',
        "def _cache_row(\n"
        "    *, source: AiEvidenceExtraction, attempt_no: int\n"
        ") -> AiEvidenceExtraction:\n"
        '    if False and (source.status != "COMPLETED" or source.raw_output is None):\n',
        "tests/test_ai_evidence_runtime.py::test_failed_terminal_cannot_be_materialized_as_cache_success",
    ),
    Mutation(
        "accept_provider_model_revision_drift",
        "marko/services/ai_evidence_extraction.py",
        "marko.services.ai_evidence_extraction",
        "if provider_model != config.model:",
        "if False and provider_model != config.model:",
        "tests/test_ai_evidence_extraction.py::test_provider_model_must_equal_the_configured_immutable_snapshot",
    ),
    Mutation(
        "accept_oversized_provider_model_identifier",
        "marko/core/ai_model_identity.py",
        "marko.core.ai_model_identity",
        "if not value or len(value) > AI_MODEL_IDENTIFIER_MAX_LENGTH or not value.isascii():\n"
        "        return None\n"
        "    return value if _MODEL_IDENTIFIER.fullmatch(value) else None",
        "if not value or not value.isascii():\n"
        "        return None\n"
        "    return value if _MODEL_IDENTIFIER.fullmatch(value[:160]) else None",
        "tests/test_ai_evidence_extraction.py::test_invalid_provider_model_is_rejected_before_persistence",
    ),
    Mutation(
        "publish_provider_controlled_model_metadata",
        "marko/api/schemas/pricing.py",
        "marko.api.schemas.pricing",
        "    model_id: str | None = None\n    reasoning_effort: str | None = None",
        "    model_id: str | None = None\n"
        "    provider_model: str | None = None\n"
        "    reasoning_effort: str | None = None",
        "tests/test_ai_evidence_cost_and_api.py::test_openapi_publishes_evidence_fields_and_no_reasoning_content",
    ),
)


def _apply_mutation(path: Path, mutation: Mutation) -> None:
    content = path.read_text(encoding="utf-8")
    count = content.count(mutation.original)
    if count != 1:
        raise RuntimeError(
            f"{mutation.mutation_id}: anchor count is {count}, expected 1"
        )
    path.write_text(
        content.replace(mutation.original, mutation.replacement, 1),
        encoding="utf-8",
    )


def _proof_command(mutation: Mutation, temporary_src: Path) -> tuple[str, ...]:
    script = (
        "import importlib,pathlib;"
        f"m=importlib.import_module({mutation.module!r});"
        "p=pathlib.Path(m.__file__).resolve();"
        f"root=pathlib.Path({str(temporary_src)!r}).resolve();"
        "assert p.is_relative_to(root),(p,root);"
        "s=p.read_text(encoding='utf-8');"
        f"assert {mutation.replacement!r} in s;"
        "print('IMPORTED_MODULE_PATH='+str(p));"
        "print('MUTANT_TEXT_LOADED=1')"
    )
    return (str(PYTHON), "-c", script)


def _path_proof_command(mutation: Mutation, temporary_src: Path) -> tuple[str, ...]:
    script = (
        "import importlib,pathlib;"
        f"m=importlib.import_module({mutation.module!r});"
        "p=pathlib.Path(m.__file__).resolve();"
        f"root=pathlib.Path({str(temporary_src)!r}).resolve();"
        "assert p.is_relative_to(root),(p,root);"
        "print('IMPORTED_MODULE_PATH='+str(p));"
        "print('ISOLATED_BASELINE_LOADED=1')"
    )
    return (str(PYTHON), "-c", script)


def run_mutation_probes() -> dict[str, object]:
    results: list[dict[str, object]] = []
    for mutation in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix="marko-ai-evidence-mutant-") as temp:
            temporary_src = Path(temp) / "src"
            shutil.copytree(BACKEND / "src" / "marko", temporary_src / "marko")
            environment = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    (str(temporary_src), str(BACKEND / "src"))
                ),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            baseline_proof = subprocess.run(
                _path_proof_command(mutation, temporary_src),
                cwd=BACKEND,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            baseline = subprocess.run(
                (str(PYTHON), "-m", "pytest", "-q", mutation.test_node),
                cwd=BACKEND,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            baseline_passed = (
                baseline_proof.returncode == 0
                and "ISOLATED_BASELINE_LOADED=1" in baseline_proof.stdout
                and baseline.returncode == 0
            )
            target = temporary_src / mutation.relative_file
            _apply_mutation(target, mutation)
            proof = subprocess.run(
                _proof_command(mutation, temporary_src),
                cwd=BACKEND,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            module_path = ""
            for line in proof.stdout.splitlines():
                if line.startswith("IMPORTED_MODULE_PATH="):
                    module_path = line.removeprefix("IMPORTED_MODULE_PATH=")
            loaded = proof.returncode == 0 and "MUTANT_TEXT_LOADED=1" in proof.stdout
            if loaded and baseline_passed:
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
                elif completed.returncode == 1 and "failed" in combined:
                    status = "KILLED"
                else:
                    status = "INVALID"
            else:
                completed = baseline if not baseline_passed else proof
                status = "INVALID"
            results.append(
                {
                    "mutation_id": mutation.mutation_id,
                    "status": status,
                    "test_node": mutation.test_node,
                    "return_code": completed.returncode,
                    "imported_module_path": module_path,
                    "isolated_baseline_passed": baseline_passed,
                    "baseline_return_code": baseline.returncode,
                    "baseline_stdout": baseline.stdout.strip()[-1000:],
                    "baseline_stderr": baseline.stderr.strip()[-1000:],
                    "mutant_text_loaded": loaded,
                    "proof_stdout": proof.stdout.strip(),
                    "proof_stderr": proof.stderr.strip()[:1000],
                }
            )
    passed = all(item["status"] == "KILLED" for item in results)
    return {
        "schema_version": "ai-evidence-mutation-report-v2",
        "isolated_baselines_passed": sum(
            item["isolated_baseline_passed"] is True for item in results
        ),
        "mutation_probe_status": "PASS" if passed else "FAIL",
        "valid_mutants": sum(item["mutant_text_loaded"] is True for item in results),
        "killed": sum(item["status"] == "KILLED" for item in results),
        "survived": sum(item["status"] == "SURVIVED" for item in results),
        "invalid": sum(item["status"] == "INVALID" for item in results),
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
