from __future__ import annotations

from types import SimpleNamespace

import pytest

from marko.services.ai_evidence_runtime import (
    AiEvidenceRuntimeError,
    _cache_row,
    ai_evidence_runtime_input_hash,
)


_BINDING = {
    "input_sha256": "a" * 64,
    "capture_content_sha256": "b" * 64,
    "candidate_snapshot_sha256": "c" * 64,
    "source_offer_locator_sha256": "f" * 64,
    "document_sha256": "1" * 64,
    "prompt_version": "prompt-v1",
    "schema_version": "schema-v1",
    "model": "gpt-5.6-luna",
    "reasoning_effort": "medium",
    "model_settings_sha256": "d" * 64,
    "max_output_tokens": 1200,
    "max_input_chars": 20_000,
}


def test_runtime_input_hash_is_stable_for_the_exact_same_binding() -> None:
    assert ai_evidence_runtime_input_hash(
        dict(_BINDING)
    ) == ai_evidence_runtime_input_hash(dict(_BINDING))


@pytest.mark.parametrize("changed", sorted(_BINDING))
def test_every_bound_runtime_input_fact_changes_request_identity(changed: str) -> None:
    baseline = ai_evidence_runtime_input_hash(_BINDING)
    modified = dict(_BINDING)
    modified[changed] = (
        int(modified[changed]) + 1
        if isinstance(modified[changed], int)
        else (
            "e" * 64 if changed.endswith("sha256") else f"changed-{modified[changed]}"
        )
    )

    assert ai_evidence_runtime_input_hash(modified) != baseline


def test_different_returned_model_snapshots_cannot_share_cache_identity() -> None:
    first = dict(_BINDING, model="gpt-5.6-luna")
    second = dict(_BINDING, model="gpt-5.6-luna-2026-08-01")

    assert ai_evidence_runtime_input_hash(first) != ai_evidence_runtime_input_hash(
        second
    )


def test_failed_terminal_cannot_be_materialized_as_cache_success() -> None:
    with pytest.raises(
        AiEvidenceRuntimeError, match="only a completed strict extraction"
    ):
        _cache_row(
            source=SimpleNamespace(status="FAILED", raw_output=None),
            attempt_no=2,
        )


def test_cache_refuses_a_provider_revision_different_from_the_pinned_model() -> None:
    with pytest.raises(
        AiEvidenceRuntimeError,
        match="cache source model revision is missing or differs",
    ):
        _cache_row(
            source=SimpleNamespace(
                status="COMPLETED",
                raw_output={},
                provider_model="gpt-5.6-luna-2026-08-01",
                model_id="gpt-5.6-luna",
            ),
            attempt_no=2,
        )
