#!/usr/bin/env python3
"""Run required mutation probes against an isolated temporary Metis copy."""

from __future__ import annotations

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
        "qn_zero_based_rank",
        "metis/pricing/statistics.py",
        (
            (
                "raw = _order_statistic(distances, rank)",
                "raw = _order_statistic(distances, rank - 1)",
            ),
        ),
        "tests/test_robust_dispersion.py::test_qn_uses_only_pair_distances_and_one_based_k_rank",
    ),
    Mutation(
        "qn_includes_self_distances",
        "metis/pricing/statistics.py",
        (
            (
                "for right in range(left + 1, sample_size)",
                "for right in range(left, sample_size)",
            ),
        ),
        "tests/test_robust_dispersion.py::test_qn_uses_only_pair_distances_and_one_based_k_rank",
    ),
    Mutation(
        "sn_excludes_self_distance",
        "metis/pricing/statistics.py",
        (
            (
                "tuple(abs(value - peer) for peer in collected)",
                "tuple(abs(value - peer) for peer in collected if peer != value)",
            ),
        ),
        "tests/test_robust_dispersion.py::test_sn_includes_self_distance_and_uses_high_then_low_median",
    ),
    Mutation(
        "sn_averages_inner_median",
        "metis/pricing/statistics.py",
        (
            (
                "_high_median(tuple(abs(value - peer) for peer in collected))",
                "median(tuple(abs(value - peer) for peer in collected))",
            ),
        ),
        "tests/test_robust_dispersion.py::test_sn_includes_self_distance_and_uses_high_then_low_median",
    ),
    Mutation(
        "qn_historical_constant",
        "metis/pricing/statistics.py",
        (
            (
                'QN_NORMAL_CONSTANT = Decimal("2.219144465985076")',
                'QN_NORMAL_CONSTANT = Decimal("2.2219")',
            ),
        ),
        "tests/test_robust_dispersion.py::test_tight_oracle_detects_historical_qn_constant_substitution",
    ),
    Mutation(
        "qn_multiplies_finite_denominator",
        "metis/pricing/statistics.py",
        (
            (
                "return ONE / _qn_finite_denominator(sample_size)",
                "return _qn_finite_denominator(sample_size)",
            ),
        ),
        "tests/test_robust_dispersion.py::test_qn_n13_divides_by_finite_denominator_instead_of_multiplying",
    ),
    Mutation(
        "cv_uses_mean_center",
        "metis/pricing/statistics.py",
        (
            (
                "center = median(collected)\n    if center <= ZERO:",
                "center = sum(collected, ZERO) / Decimal(len(collected))\n"
                "    if center <= ZERO:",
            ),
        ),
        "tests/test_robust_dispersion_variations.py::test_cv_uses_median_center_not_mean_mutation",
    ),
    Mutation(
        "decision_profile_before_seller_dedup",
        "metis/pricing/engine.py",
        (
            (
                "pre_clean_profile = robust_price_dispersion(\n"
                "        [offer.normalized_price for offer in deduplicated],",
                "pre_clean_profile = robust_price_dispersion(\n"
                "        [offer.normalized_price for offer in eligible],",
            ),
            (
                "prices = [offer.normalized_price for offer in cleaned]",
                "prices = [offer.normalized_price for offer in eligible]",
            ),
        ),
        "tests/test_robust_dispersion_engine.py::test_profiles_are_built_after_seller_deduplication",
    ),
)


def _apply_mutation(path: Path, replacements: tuple[tuple[str, str], ...]) -> None:
    content = path.read_text()
    for original, replacement in replacements:
        count = content.count(original)
        if count != 1:
            raise RuntimeError(
                f"mutation anchor count for {path.name} is {count}, expected 1: {original}"
            )
        content = content.replace(original, replacement, 1)
    path.write_text(content)


def run_mutation_probes() -> dict[str, object]:
    results: list[dict[str, object]] = []
    for mutation in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix="marko-robust-mutation-") as temporary:
            temporary_root = Path(temporary)
            temporary_src = temporary_root / "src"
            shutil.copytree(BACKEND / "src" / "metis", temporary_src / "metis")
            target = temporary_src / mutation.relative_file
            _apply_mutation(target, mutation.replacements)
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
            elif "1 failed" in combined and "ERROR" not in combined:
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
        "mutation_probe_status": "PASS" if passed else "FAIL",
        "mutations": results,
        "production_files_modified": False,
    }


def main() -> None:
    report = run_mutation_probes()
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["mutation_probe_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
