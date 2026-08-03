"""Bounded OpenAI Responses transport for AI evidence extraction.

The extractor schema and deterministic verifier deliberately contain no HTTP
client.  This module is the single paid transport boundary.  Every physical
POST, including a retry after a timeout/429/5xx, reserves a durable position
budget slot *before* transmission.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import hashlib
import json
from time import monotonic
from typing import Any
from uuid import UUID

import httpx

from marko.core.ai_model_identity import (
    is_immutable_model_snapshot,
    validated_model_identifier,
)
from marko.services.ai_evidence_extraction import (
    AiEvidenceExtractionOutput,
    AiEvidenceProviderError,
    AiEvidenceProviderResult,
    AiEvidenceRequest,
)
from marko.services.llm_call_budget import (
    AttemptBudgetExhausted,
    BudgetedAttempts,
    PositionCallBudget,
)


PROVIDER_CALL_BUDGET_EXHAUSTED = "LLM_PROVIDER_CALL_BUDGET_EXHAUSTED"


def safety_identifier_for_workspace(workspace_id: UUID | str) -> str:
    """Return a stable pseudonymous identifier without exposing the workspace id."""

    digest = hashlib.sha256(
        ("marko-ai-evidence:" + str(workspace_id)).encode("utf-8")
    ).hexdigest()
    return "marko-ai-evidence-" + digest[:32]


class OpenAIResponsesEvidenceProvider:
    """Strict text-only Responses API adapter for one pricing position.

    ``budget`` is mandatory by design.  A provider that cannot attribute a
    billable request to a durable position must make no request at all.
    """

    def __init__(
        self,
        settings: Any,
        *,
        budget: PositionCallBudget | None,
        safety_identifier: str,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 2,
    ) -> None:
        self._settings = settings
        self._budget = budget
        self._safety_identifier = safety_identifier.strip()
        self._client = client
        self._max_attempts = max(1, min(int(max_attempts), 2))

    async def extract(self, *, request: AiEvidenceRequest) -> AiEvidenceProviderResult:
        if self._budget is None:
            raise AiEvidenceProviderError(
                PROVIDER_CALL_BUDGET_EXHAUSTED,
                "AI evidence provider has no durable position budget; no request was made",
            )
        if not self._safety_identifier:
            raise AiEvidenceProviderError(
                "AI_EVIDENCE_SAFETY_IDENTIFIER_MISSING",
                "AI evidence provider has no pseudonymous safety identifier",
            )
        if request.tools_enabled or request.store or not request.strict_schema:
            raise AiEvidenceProviderError(
                "AI_EVIDENCE_UNSAFE_REQUEST",
                "AI evidence request must disable tools and storage and require a strict schema",
            )
        if not is_immutable_model_snapshot(request.model):
            raise AiEvidenceProviderError(
                "AI_EVIDENCE_MODEL_SNAPSHOT_REQUIRED",
                "AI evidence model must be a documented stable snapshot id",
            )
        if request.idempotency_key and (
            len(request.idempotency_key) != 64
            or any(char not in "0123456789abcdef" for char in request.idempotency_key)
        ):
            raise AiEvidenceProviderError(
                "AI_EVIDENCE_IDEMPOTENCY_KEY_INVALID",
                "provider idempotency key must be a lowercase SHA-256 digest",
            )

        api_key = _configured_api_key(self._settings)
        if not api_key:
            raise AiEvidenceProviderError(
                "AI_EVIDENCE_UNCONFIGURED",
                "OpenAI API key is not configured; no request was made",
            )

        payload = {
            "model": request.model,
            "instructions": request.system_prompt,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "UNTRUSTED_PRODUCT_EVIDENCE_JSON\n"
                            + json.dumps(
                                request.input_snapshot,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        }
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "marko_ai_evidence_extraction",
                    "description": "Cited product facts from one retained capture",
                    "strict": True,
                    "schema": request.json_schema,
                }
            },
            "reasoning": {"effort": request.reasoning_effort},
            "max_output_tokens": request.max_output_tokens,
            "store": False,
            "safety_identifier": self._safety_identifier,
        }
        endpoint = (
            str(
                getattr(
                    self._settings, "pricing_llm_base_url", "https://api.openai.com/v1"
                )
            ).rstrip("/")
            + "/responses"
        )
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=float(getattr(self._settings, "pricing_llm_timeout_seconds", 60.0))
        )
        attempts = BudgetedAttempts(
            self._budget,
            max_attempts=self._max_attempts,
        )
        response: httpx.Response | None = None
        transport_failure: Exception | None = None
        started = monotonic()
        try:
            async for attempt in attempts:
                if attempt:
                    await asyncio.sleep(0.5)
                try:
                    headers = {
                        "Authorization": "Bearer " + api_key,
                        "Content-Type": "application/json",
                    }
                    if request.idempotency_key:
                        headers["Idempotency-Key"] = request.idempotency_key
                    response = await client.post(
                        endpoint,
                        headers=headers,
                        json=payload,
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    response = None
                    transport_failure = exc
                    attempts.last_failure = type(exc).__name__
                    continue
                transport_failure = None
                if response.status_code == 429 or response.status_code >= 500:
                    attempts.last_failure = f"HTTP {response.status_code}"
                    continue
                break

            try:
                attempts.raise_if_refused()
            except AttemptBudgetExhausted as exc:
                raise AiEvidenceProviderError(
                    PROVIDER_CALL_BUDGET_EXHAUSTED,
                    exc.detail,
                    provider_attempts=attempts.made,
                ) from exc
            if response is None:
                raise AiEvidenceProviderError(
                    "AI_EVIDENCE_TRANSPORT_ERROR",
                    type(transport_failure).__name__,
                    provider_attempts=attempts.made,
                ) from transport_failure
            if not response.is_success:
                raise AiEvidenceProviderError(
                    "AI_EVIDENCE_HTTP_ERROR",
                    f"provider returned HTTP {response.status_code}",
                    provider_attempts=attempts.made,
                )
            try:
                raw = response.json()
            except ValueError as exc:
                raise AiEvidenceProviderError(
                    "AI_EVIDENCE_INVALID_RESPONSE_JSON",
                    "provider response was not JSON",
                    provider_attempts=attempts.made,
                ) from exc
            try:
                output = AiEvidenceExtractionOutput.model_validate_json(
                    _responses_output_text(raw)
                )
            except AiEvidenceProviderError as exc:
                raise AiEvidenceProviderError(
                    exc.code,
                    exc.safe_detail,
                    provider_attempts=attempts.made,
                ) from exc
            except ValueError as exc:
                raise AiEvidenceProviderError(
                    "AI_EVIDENCE_OUTPUT_SCHEMA_INVALID",
                    "provider output did not satisfy the strict evidence schema",
                    provider_attempts=attempts.made,
                ) from exc
            provider_model = validated_model_identifier(raw.get("model"))
            if provider_model is None:
                raise AiEvidenceProviderError(
                    "AI_EVIDENCE_PROVIDER_MODEL_INVALID",
                    "provider model identifier was missing or invalid",
                    provider_attempts=attempts.made,
                )
            if provider_model != request.model:
                raise AiEvidenceProviderError(
                    "AI_EVIDENCE_PROVIDER_MODEL_REVISION_MISMATCH",
                    "provider model revision did not match the configured snapshot",
                    provider_attempts=attempts.made,
                )
            usage = raw.get("usage")
            return AiEvidenceProviderResult(
                output=output,
                response_id=_optional_text(raw.get("id")),
                model=provider_model,
                usage=_bounded_usage(usage),
                latency_ms=max(0, round((monotonic() - started) * 1000)),
                provider_attempts=attempts.made,
            )
        finally:
            if own_client:
                await client.aclose()


def _responses_output_text(payload: Mapping[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "output_text":
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        return text
    raise AiEvidenceProviderError(
        "AI_EVIDENCE_OUTPUT_TEXT_MISSING",
        "provider response contained no output_text block",
    )


def _secret_text(value: Any) -> str:
    getter = getattr(value, "get_secret_value", None)
    return str(getter() if callable(getter) else value or "").strip()


def _configured_api_key(settings: Any) -> str:
    for name in ("pricing_ai_evidence_api_key", "pricing_llm_api_key"):
        value = _secret_text(getattr(settings, name, None))
        if value:
            return value
    return ""


def _optional_text(value: Any) -> str | None:
    return value.strip()[:255] if isinstance(value, str) and value.strip() else None


def _bounded_usage(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    # Reconstruct, do not copy.  Provider-controlled nested objects may grow
    # fields such as ``reasoning_content`` without notice; copying a details
    # mapping wholesale would persist hidden reasoning.  Only integer counters
    # needed for billing estimates cross this boundary.
    bounded: dict[str, Any] = {}

    def counter(container: Mapping[str, Any], key: str) -> int | None:
        raw = container.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            return None
        return raw

    for key in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
    ):
        amount = counter(value, key)
        if amount is not None:
            bounded[key] = amount

    input_details = value.get("input_tokens_details")
    if isinstance(input_details, Mapping):
        cached = counter(input_details, "cached_tokens")
        if cached is not None:
            bounded["input_tokens_details"] = {"cached_tokens": cached}

    output_details = value.get("output_tokens_details")
    if isinstance(output_details, Mapping):
        reasoning = counter(output_details, "reasoning_tokens")
        if reasoning is not None:
            bounded["output_tokens_details"] = {"reasoning_tokens": reasoning}
    return bounded


__all__ = [
    "OpenAIResponsesEvidenceProvider",
    "PROVIDER_CALL_BUDGET_EXHAUSTED",
    "safety_identifier_for_workspace",
]
