"""Versioned USD estimation policy for AI-assisted evidence extraction.

Every amount produced by this module is an **estimate**, never billing truth.
The provider's invoice is the only authority on money actually owed; these
numbers exist so an operator can see the order of magnitude of a shadow run
before it becomes a surprise.  That is why each result carries
:data:`ESTIMATE_DISCLAIMER` and the identifier of the rate snapshot it was
computed from.

Three rules hold this module together:

* **No floats.**  Money is :class:`~decimal.Decimal` end to end.  A ``float``
  rate or a ``float`` amount is rejected at construction, not silently
  absorbed, because binary fractions cannot represent USD 0.02 exactly.
* **Rates are data, not code.**  They live in a versioned
  :class:`AiRateCard` with an effective date and a model id, are resolvable by
  version, and are configurable from JSON.  Extraction logic must never inline
  a number from here.
* **Price is downstream of everything.**  A rate change may move an estimate
  and nothing else: not request identity, not cached evidence, not eligibility,
  not verification.  :func:`cost_independent_digest` exists to make that
  property assertable rather than merely intended.

The default snapshot is the OpenAI standard-API rate announced for GPT-5.6
Luna on 2026-07-30: USD 0.20 / 1M uncached input tokens, USD 0.02 / 1M cached
input tokens, USD 1.20 / 1M output tokens with reasoning tokens billed as
output.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import hashlib
import json
from typing import Any, Final


ESTIMATE_DISCLAIMER: Final[str] = "ESTIMATE_NOT_BILLING_TRUTH"

#: Provider rates are quoted per million tokens.
RATE_UNIT_TOKENS: Final[int] = 1_000_000

#: ``Decimal.scaleb`` shifts the exponent instead of dividing, so converting a
#: per-million rate to a per-token amount stays exact for every input.
_RATE_UNIT_EXPONENT: Final[int] = -6

_DISPLAY_QUANTUM: Final[Decimal] = Decimal("0.000001")


class AiCostPolicyError(ValueError):
    """A rate card, a usage report, or a rate lookup was not usable."""


def _require_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise AiCostPolicyError(
            f"{name} must be a Decimal, got {type(value).__name__}: "
            "binary floats cannot represent USD rates exactly"
        )
    if not value.is_finite():
        raise AiCostPolicyError(f"{name} must be a finite Decimal")
    if value < 0:
        raise AiCostPolicyError(f"{name} must not be negative")
    return value


def _require_token_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AiCostPolicyError(
            f"{name} must be an int token count, got {type(value).__name__}"
        )
    if value < 0:
        raise AiCostPolicyError(f"{name} must not be negative")
    return value


def _money_from_config(value: object, name: str) -> Decimal:
    """Parse a configured rate, refusing the JSON ``float`` representation."""

    if isinstance(value, Decimal):
        return _require_decimal(value, name)
    if isinstance(value, bool) or isinstance(value, float):
        raise AiCostPolicyError(
            f"{name} must be configured as a decimal string, not a float"
        )
    if isinstance(value, int):
        return _require_decimal(Decimal(value), name)
    if isinstance(value, str):
        try:
            return _require_decimal(Decimal(value.strip()), name)
        except AiCostPolicyError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalized below
            raise AiCostPolicyError(f"{name} is not a valid decimal string") from exc
    raise AiCostPolicyError(f"{name} must be a decimal string")


@dataclass(frozen=True, slots=True)
class AiRateCard:
    """One immutable, dated snapshot of provider rates for one model."""

    rate_version: str
    model_id: str
    effective_date: date
    uncached_input_usd_per_million: Decimal
    cached_input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    source: str = "provider_announced_standard_api_rates"
    currency: str = "USD"
    #: Reasoning tokens are billed at the output rate and are already counted
    #: inside ``output_tokens`` in the provider's usage report.
    reasoning_billed_as_output: bool = True

    def __post_init__(self) -> None:
        if not self.rate_version.strip():
            raise AiCostPolicyError("rate_version must not be empty")
        if not self.model_id.strip():
            raise AiCostPolicyError("model_id must not be empty")
        if not isinstance(self.effective_date, date):
            raise AiCostPolicyError("effective_date must be a date")
        if self.currency != "USD":
            raise AiCostPolicyError("only USD rate cards are supported")
        _require_decimal(self.uncached_input_usd_per_million, "uncached_input rate")
        _require_decimal(self.cached_input_usd_per_million, "cached_input rate")
        _require_decimal(self.output_usd_per_million, "output rate")
        if self.cached_input_usd_per_million > self.uncached_input_usd_per_million:
            raise AiCostPolicyError(
                "cached input must not be priced above uncached input"
            )
        if not self.reasoning_billed_as_output:
            raise AiCostPolicyError(
                "this policy only models providers that bill reasoning as output"
            )

    def rates_per_million(self) -> dict[str, str]:
        return {
            "uncached_input": str(self.uncached_input_usd_per_million),
            "cached_input": str(self.cached_input_usd_per_million),
            "output": str(self.output_usd_per_million),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "rate_version": self.rate_version,
            "model_id": self.model_id,
            "effective_date": self.effective_date.isoformat(),
            "currency": self.currency,
            "source": self.source,
            "reasoning_billed_as_output": self.reasoning_billed_as_output,
            "rates_per_million": self.rates_per_million(),
            "disclaimer": ESTIMATE_DISCLAIMER,
        }


#: Announced OpenAI standard-API rates for GPT-5.6 Luna, 2026-07-30.
LUNA_STANDARD_2026_07_30_VERSION: Final[str] = "openai-gpt-5.6-luna-standard-2026-07-30"
LUNA_MODEL_ID: Final[str] = "gpt-5.6-luna"

LUNA_STANDARD_2026_07_30: Final[AiRateCard] = AiRateCard(
    rate_version=LUNA_STANDARD_2026_07_30_VERSION,
    model_id=LUNA_MODEL_ID,
    effective_date=date(2026, 7, 30),
    uncached_input_usd_per_million=Decimal("0.20"),
    cached_input_usd_per_million=Decimal("0.02"),
    output_usd_per_million=Decimal("1.20"),
    source="openai_standard_api_announced_2026_07_30",
)

DEFAULT_RATE_VERSION: Final[str] = LUNA_STANDARD_2026_07_30_VERSION


@dataclass(frozen=True, slots=True)
class RateCardRegistry:
    """An ordered set of rate cards addressable by version or by model."""

    cards: tuple[AiRateCard, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for card in self.cards:
            if not isinstance(card, AiRateCard):
                raise AiCostPolicyError("registry entries must be AiRateCard")
            if card.rate_version in seen:
                raise AiCostPolicyError(
                    f"duplicate rate_version {card.rate_version!r} in registry"
                )
            seen.add(card.rate_version)

    def versions(self) -> tuple[str, ...]:
        return tuple(card.rate_version for card in self.cards)

    def get(self, rate_version: str) -> AiRateCard:
        for card in self.cards:
            if card.rate_version == rate_version:
                return card
        raise AiCostPolicyError(
            f"unknown rate_version {rate_version!r}; known: {list(self.versions())}"
        )

    def for_model(self, model_id: str, *, as_of: date | None = None) -> AiRateCard:
        """Return the newest card for ``model_id`` effective on ``as_of``."""

        candidates = [
            card
            for card in self.cards
            if card.model_id == model_id
            and (as_of is None or card.effective_date <= as_of)
        ]
        if not candidates:
            raise AiCostPolicyError(
                f"no rate card for model {model_id!r}"
                + (f" effective on {as_of.isoformat()}" if as_of else "")
            )
        return max(
            candidates, key=lambda card: (card.effective_date, card.rate_version)
        )

    def extended(self, cards: Iterable[AiRateCard]) -> RateCardRegistry:
        return RateCardRegistry(tuple(self.cards) + tuple(cards))


DEFAULT_RATE_REGISTRY: Final[RateCardRegistry] = RateCardRegistry(
    (LUNA_STANDARD_2026_07_30,)
)


def rate_card_from_mapping(payload: Mapping[str, Any]) -> AiRateCard:
    """Build a rate card from configuration (JSON, env, or a fixture)."""

    missing = {
        "rate_version",
        "model_id",
        "effective_date",
        "uncached_input_usd_per_million",
        "cached_input_usd_per_million",
        "output_usd_per_million",
    } - set(payload)
    if missing:
        raise AiCostPolicyError(f"rate card is missing {sorted(missing)}")
    raw_date = payload["effective_date"]
    effective = raw_date if isinstance(raw_date, date) else None
    if effective is None:
        try:
            effective = date.fromisoformat(str(raw_date))
        except ValueError as exc:
            raise AiCostPolicyError("effective_date must be an ISO date") from exc
    return AiRateCard(
        rate_version=str(payload["rate_version"]),
        model_id=str(payload["model_id"]),
        effective_date=effective,
        uncached_input_usd_per_million=_money_from_config(
            payload["uncached_input_usd_per_million"], "uncached_input rate"
        ),
        cached_input_usd_per_million=_money_from_config(
            payload["cached_input_usd_per_million"], "cached_input rate"
        ),
        output_usd_per_million=_money_from_config(
            payload["output_usd_per_million"], "output rate"
        ),
        source=str(payload.get("source", "operator_configured")),
    )


def registry_from_config(
    raw: str | Iterable[Mapping[str, Any]] | None,
    *,
    include_builtin: bool = True,
) -> RateCardRegistry:
    """Load extra rate cards from a JSON document or an iterable of mappings."""

    base = DEFAULT_RATE_REGISTRY.cards if include_builtin else ()
    if raw is None:
        return RateCardRegistry(base)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return RateCardRegistry(base)
        try:
            decoded = json.loads(text, parse_float=str)
        except json.JSONDecodeError as exc:
            raise AiCostPolicyError(
                "rate card configuration is not valid JSON"
            ) from exc
    else:
        decoded = list(raw)
    if isinstance(decoded, Mapping):
        decoded = [decoded]
    if not isinstance(decoded, list):
        raise AiCostPolicyError("rate card configuration must be a list of objects")
    extra = [rate_card_from_mapping(entry) for entry in decoded]
    return RateCardRegistry(tuple(base) + tuple(extra))


def resolve_rate_card(
    *,
    rate_version: str | None = None,
    model_id: str | None = None,
    registry: RateCardRegistry | None = None,
    as_of: date | None = None,
) -> AiRateCard:
    """Resolve the card to estimate with; fail closed rather than guessing."""

    selected = registry or DEFAULT_RATE_REGISTRY
    if rate_version:
        card = selected.get(rate_version)
        if model_id and card.model_id != model_id:
            raise AiCostPolicyError(
                f"rate_version {rate_version!r} prices {card.model_id!r}, "
                f"not {model_id!r}"
            )
        return card
    if model_id:
        return selected.for_model(model_id, as_of=as_of)
    return selected.get(DEFAULT_RATE_VERSION)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Provider-reported token usage, in the provider's own conventions.

    ``input_tokens`` includes ``cached_input_tokens`` and ``output_tokens``
    includes ``reasoning_tokens``; that is what the OpenAI Responses API
    reports, and mixing the two conventions is exactly how a bill doubles
    without anyone noticing.
    """

    input_tokens: int
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        _require_token_count(self.input_tokens, "input_tokens")
        _require_token_count(self.cached_input_tokens, "cached_input_tokens")
        _require_token_count(self.output_tokens, "output_tokens")
        _require_token_count(self.reasoning_tokens, "reasoning_tokens")
        if self.cached_input_tokens > self.input_tokens:
            raise AiCostPolicyError(
                "cached_input_tokens must be a subset of input_tokens"
            )
        if self.reasoning_tokens > self.output_tokens:
            raise AiCostPolicyError(
                "reasoning_tokens must be a subset of output_tokens; "
                "output usage is missing the reasoning tokens it is billed for"
            )

    @property
    def uncached_input_tokens(self) -> int:
        return self.input_tokens - self.cached_input_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "uncached_input_tokens": self.uncached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
        }


_INPUT_KEYS: Final[tuple[str, ...]] = ("input_tokens", "prompt_tokens")
_OUTPUT_KEYS: Final[tuple[str, ...]] = ("output_tokens", "completion_tokens")
_INPUT_DETAIL_KEYS: Final[tuple[str, ...]] = (
    "input_tokens_details",
    "prompt_tokens_details",
)
_OUTPUT_DETAIL_KEYS: Final[tuple[str, ...]] = (
    "output_tokens_details",
    "completion_tokens_details",
)


def _first_int(payload: Mapping[str, Any], keys: Iterable[str]) -> int | None:
    for key in keys:
        if key in payload and payload[key] is not None:
            return _require_token_count(payload[key], key)
    return None


def _detail_int(payload: Mapping[str, Any], group: Iterable[str], key: str) -> int:
    for name in group:
        details = payload.get(name)
        if isinstance(details, Mapping) and details.get(key) is not None:
            return _require_token_count(details[key], f"{name}.{key}")
    return 0


def usage_from_provider_payload(payload: Mapping[str, Any]) -> TokenUsage:
    """Parse a provider usage report, refusing to invent absent numbers.

    A missing output count is an error, not a zero: silently treating an
    unreported completion as free is how reasoning-heavy calls disappear from
    a cost estimate entirely.
    """

    if not isinstance(payload, Mapping):
        raise AiCostPolicyError("usage payload must be a mapping")
    input_tokens = _first_int(payload, _INPUT_KEYS)
    if input_tokens is None:
        raise AiCostPolicyError("usage payload is missing an input token count")
    output_tokens = _first_int(payload, _OUTPUT_KEYS)
    if output_tokens is None:
        raise AiCostPolicyError(
            "usage payload is missing an output token count; output and "
            "reasoning tokens are billable and must never be assumed zero"
        )
    cached = _detail_int(payload, _INPUT_DETAIL_KEYS, "cached_tokens")
    if payload.get("cached_input_tokens") is not None:
        cached = _require_token_count(payload["cached_input_tokens"], "cached_tokens")
    reasoning = _detail_int(payload, _OUTPUT_DETAIL_KEYS, "reasoning_tokens")
    if payload.get("reasoning_tokens") is not None:
        reasoning = _require_token_count(
            payload["reasoning_tokens"], "reasoning_tokens"
        )
    usage = TokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
    )
    reported_total = _first_int(payload, ("total_tokens",))
    if reported_total is not None and reported_total != usage.total_tokens:
        raise AiCostPolicyError(
            "usage payload is internally inconsistent: total_tokens "
            f"{reported_total} != input {usage.input_tokens} + output "
            f"{usage.output_tokens}; billable tokens are missing"
        )
    return usage


def _amount(tokens: int, rate_per_million: Decimal) -> Decimal:
    """Exact per-token money: shift the exponent, never divide into a float."""

    return (Decimal(tokens) * rate_per_million).scaleb(_RATE_UNIT_EXPONENT)


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """An estimate, labelled as such, bound to the rate version that made it."""

    rate_version: str
    model_id: str
    rates_effective_date: date
    currency: str
    usage: TokenUsage
    uncached_input_usd: Decimal
    cached_input_usd: Decimal
    output_usd: Decimal
    total_usd: Decimal
    rates_per_million: Mapping[str, str]
    disclaimer: str = ESTIMATE_DISCLAIMER

    @property
    def total_usd_display(self) -> Decimal:
        """Micro-USD rounding for humans; never use this for reconciliation."""

        return self.total_usd.quantize(_DISPLAY_QUANTUM)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rate_version": self.rate_version,
            "model_id": self.model_id,
            "rates_effective_date": self.rates_effective_date.isoformat(),
            "currency": self.currency,
            "uncached_input_usd": str(self.uncached_input_usd),
            "cached_input_usd": str(self.cached_input_usd),
            "output_usd": str(self.output_usd),
            "total_usd": str(self.total_usd),
            "rates_per_million": dict(self.rates_per_million),
            "disclaimer": self.disclaimer,
        }


def estimate_cost(usage: TokenUsage, card: AiRateCard | None = None) -> CostEstimate:
    """Price ``usage`` with ``card``.  Estimate only -- never billing truth."""

    if not isinstance(usage, TokenUsage):
        raise AiCostPolicyError("usage must be a TokenUsage")
    selected = card or LUNA_STANDARD_2026_07_30
    if not isinstance(selected, AiRateCard):
        raise AiCostPolicyError("card must be an AiRateCard")
    uncached_input_usd = _amount(
        usage.uncached_input_tokens, selected.uncached_input_usd_per_million
    )
    cached_input_usd = _amount(
        usage.cached_input_tokens, selected.cached_input_usd_per_million
    )
    output_usd = _amount(usage.output_tokens, selected.output_usd_per_million)
    return CostEstimate(
        rate_version=selected.rate_version,
        model_id=selected.model_id,
        rates_effective_date=selected.effective_date,
        currency=selected.currency,
        usage=usage,
        uncached_input_usd=uncached_input_usd,
        cached_input_usd=cached_input_usd,
        output_usd=output_usd,
        total_usd=uncached_input_usd + cached_input_usd + output_usd,
        rates_per_million=selected.rates_per_million(),
    )


def estimate_from_provider_payload(
    payload: Mapping[str, Any],
    *,
    card: AiRateCard | None = None,
    rate_version: str | None = None,
    model_id: str | None = None,
    registry: RateCardRegistry | None = None,
) -> CostEstimate:
    selected = card or resolve_rate_card(
        rate_version=rate_version, model_id=model_id, registry=registry
    )
    return estimate_cost(usage_from_provider_payload(payload), selected)


def usage_telemetry_payload(
    usage: TokenUsage,
    estimate: CostEstimate | None = None,
) -> dict[str, Any]:
    """The JSON-safe block persisted alongside an extraction row.

    The rate version travels with the estimate so a later rate change can be
    told apart from a change in what the provider actually did.
    """

    payload: dict[str, Any] = dict(usage.as_dict())
    if estimate is not None:
        if estimate.usage != usage:
            raise AiCostPolicyError("estimate does not describe this usage")
        payload["spend_estimate"] = estimate.as_dict()
    return payload


#: Keys whose value depends on the rate card.  Nothing outside this set may
#: move when rates change.
COST_ESTIMATE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "spend_estimate",
        "rate_version",
        "rates_effective_date",
        "rates_per_million",
        "uncached_input_usd",
        "cached_input_usd",
        "output_usd",
        "total_usd",
        "total_usd_display",
        "estimated_usd",
    }
)


def strip_cost_estimate_fields(value: Any) -> Any:
    """Recursively drop every rate-derived field from a payload."""

    if isinstance(value, Mapping):
        return {
            str(key): strip_cost_estimate_fields(item)
            for key, item in value.items()
            if str(key) not in COST_ESTIMATE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [strip_cost_estimate_fields(item) for item in value]
    return value


def cost_independent_digest(value: Any) -> str:
    """Fingerprint everything a rate change must not be able to move."""

    canonical = json.dumps(
        strip_cost_estimate_fields(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "AiCostPolicyError",
    "AiRateCard",
    "COST_ESTIMATE_KEYS",
    "CostEstimate",
    "DEFAULT_RATE_REGISTRY",
    "DEFAULT_RATE_VERSION",
    "ESTIMATE_DISCLAIMER",
    "LUNA_STANDARD_2026_07_30",
    "LUNA_STANDARD_2026_07_30_VERSION",
    "LUNA_MODEL_ID",
    "RATE_UNIT_TOKENS",
    "RateCardRegistry",
    "TokenUsage",
    "cost_independent_digest",
    "estimate_cost",
    "estimate_from_provider_payload",
    "rate_card_from_mapping",
    "registry_from_config",
    "resolve_rate_card",
    "strip_cost_estimate_fields",
    "usage_from_provider_payload",
    "usage_telemetry_payload",
]
