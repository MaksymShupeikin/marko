"""Fail-closed API and serialization boundary for Yuri's sensitive cost."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
import re
from typing import Any

from marko.core.config import Settings, get_settings


class CostPrivacyMode(StrEnum):
    UNDECIDED = "UNDECIDED"
    LOCAL_DEVICE_ONLY = "LOCAL_DEVICE_ONLY"
    SERVER_SIDE_ENCRYPTED = "SERVER_SIDE_ENCRYPTED"


class CostPrivacyBlocked(RuntimeError):
    """Raw cost crossed a boundary that has no approved protection model."""


_HEADER_NORMALIZER = re.compile(r"[^a-zа-яёіїґє0-9]+", re.IGNORECASE)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-zа-яёіїґє])(?=[A-ZА-ЯЁІЇҐЄ])")
_SENSITIVE_KEYS = frozenset(
    {
        "cost",
        "cost floor",
        "cost basis",
        "cost basis inventory value",
        "cost snapshot",
        "approved floor",
        "below cost floor",
        "себестоимость",
        "собівартість",
        "закупочная цена",
        "закупівельна ціна",
        "цена закупки",
        "ціна закупівлі",
    }
)
_SAFE_DERIVED_KEYS = frozenset(
    {
        "cost configured",
        "cost privacy mode",
        "allow below cost",
        "below cost warning confirmed",
        "is below cost",
        "recommended price below cost",
        "clear cost",
    }
)


def normalize_sensitive_label(value: str) -> str:
    separated = _CAMEL_BOUNDARY.sub(" ", value).replace("_", " ")
    return _HEADER_NORMALIZER.sub(" ", separated.casefold()).strip()


def is_raw_cost_label(value: str) -> bool:
    """Return whether a field/header can contain a raw or reconstructable cost."""
    normalized = normalize_sensitive_label(value)
    if normalized in _SAFE_DERIVED_KEYS:
        return False
    if normalized in _SENSITIVE_KEYS:
        return True
    tokens = set(normalized.split())
    if tokens & {"cost", "себестоимость", "собівартість"}:
        return True
    return (
        {"закупочная", "цена"} <= tokens
        or {"закупівельна", "ціна"} <= tokens
        or {"цена", "закупки"} <= tokens
        or {"ціна", "закупівлі"} <= tokens
    )


def require_server_cost_input_allowed(
    value: object | None,
    *,
    settings: Settings | None = None,
) -> None:
    """Allow raw input only when the validated encrypted-server mode is active."""
    if value is None:
        return
    selected = settings or get_settings()
    mode = CostPrivacyMode(selected.cost_privacy_mode)
    if mode == CostPrivacyMode.UNDECIDED:
        raise CostPrivacyBlocked(
            "Cost privacy mode is UNDECIDED; raw cost input is disabled"
        )
    if mode == CostPrivacyMode.LOCAL_DEVICE_ONLY:
        raise CostPrivacyBlocked(
            "LOCAL_DEVICE_ONLY forbids sending raw cost to the server"
        )
    if mode == CostPrivacyMode.SERVER_SIDE_ENCRYPTED:
        try:
            selected.cost_keyring
        except ValueError as exc:
            raise CostPrivacyBlocked(
                "SERVER_SIDE_ENCRYPTED requires a valid external keyring"
            ) from exc
        return
    raise CostPrivacyBlocked("Unsupported cost privacy mode")


def privacy_safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively remove legacy cost fields before an API/audit boundary."""
    result: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        if is_raw_cost_label(key_text):
            continue
        if isinstance(item, Mapping):
            result[key_text] = privacy_safe_mapping(item)
        elif isinstance(item, list):
            result[key_text] = [
                privacy_safe_mapping(entry) if isinstance(entry, Mapping) else entry
                for entry in item
            ]
        else:
            result[key_text] = item
    return result


def privacy_safe_validation_errors(
    errors: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return validation details without echoing any submitted request values.

    FastAPI's default 422 payload includes an ``input`` member.  That is useful
    for ordinary validation but would echo a mistyped raw cost (or an unrelated
    client row) back through an error boundary.  The public contract keeps the
    location and diagnostic while dropping all input and validator context.
    """
    safe_errors: list[dict[str, Any]] = []
    for error in errors:
        location = list(error.get("loc", ()))
        sensitive_location = any(
            is_raw_cost_label(str(part)) for part in location if isinstance(part, str)
        )
        if sensitive_location:
            safe_errors.append(
                {
                    "type": "value_error.sensitive_input_disabled",
                    "loc": location,
                    "msg": "Sensitive input is disabled by the current privacy policy",
                }
            )
            continue
        safe_errors.append(
            {
                key: value
                for key, value in error.items()
                if key in {"type", "loc", "msg", "url"}
            }
        )
    return safe_errors


__all__ = [
    "CostPrivacyBlocked",
    "CostPrivacyMode",
    "is_raw_cost_label",
    "privacy_safe_mapping",
    "privacy_safe_validation_errors",
    "require_server_cost_input_allowed",
]
