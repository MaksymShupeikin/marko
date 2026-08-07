"""Guard the backend reason-code surface against untranslated UI enums."""

from __future__ import annotations

from pathlib import Path
import re


_UPPER_CODE = re.compile(r"""["']([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)["']""")
_DART_TRANSLATION_KEY = re.compile(
    r"^\s*'([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)'\s*:",
    re.MULTILINE,
)

# Uppercase protocol identifiers and enum values in the same source modules
# which are not customer-facing reason codes.
_NON_REASON_PROTOCOL_LITERALS = {
    "ACCEPTABLE_ANALOGUE",
    "COMPARABILITY_CONTRACT_VERSION",
    "COMPARABILITY_DIMENSIONS",
    "COMPARABILITY_POLICY_HASH",
    "COMPARABILITY_POLICY_ID",
    "CATEGORICAL_NORMALIZATION_VERSION",
    "DIMENSIONLESS_GAP_CONFIDENCE_PROXY",
    "FLAG_BELOW_COST_FLOOR",
    "FLAG_FLOOR_CORROBORATION_UNAVAILABLE",
    "FLAG_FLOOR_RESTS_ON_ONE_SELLER",
    "FLAG_IMPLAUSIBLE_EXCLUDED_FROM_TARGET",
    "FLAG_ROUNDED_BELOW_SIGNIFICANCE",
    "FLAG_STALE_CAPPED_AT_CHEAPEST",
    "FLAG_STEP_CAPPED",
    "MANUAL_REVIEW",
    "NO_DATA",
    "NO_RECOMMENDATION_ALREADY_COMPETITIVE",
    "NO_RECOMMENDATION_INSIGNIFICANT",
    "NO_RECOMMENDATION_STALE_NOT_CHEAPEST",
    "NOT_COMPARABLE",
    "RAISE_POLICY_SCHEMA_VERSION",
    "SHOW_BUT_FLAG",
    "STOCK_EXPOSURE_PROXY",
    "UAH_LOCKED_INVENTORY_CONFIDENCE_ADJUSTED",
    "UAH_PER_MONTH_CONFIDENCE_ADJUSTED",
}


def test_all_backend_pricing_reason_literals_have_ru_and_uk_ui_copy() -> None:
    root = Path(__file__).resolve().parents[2]
    backend_sources = (
        root / "backend/src/metis/pricing/engine.py",
        root / "backend/src/metis/pricing/raise_policy.py",
        root / "backend/src/metis/pricing/comparability.py",
    )
    emitted_or_guarded = {
        match
        for path in backend_sources
        for match in _UPPER_CODE.findall(path.read_text(encoding="utf-8"))
    } - _NON_REASON_PROTOCOL_LITERALS

    dart_contract = (
        root / "frontend/lib/features/pricing/pricing_reason_labels.dart"
    ).read_text(encoding="utf-8")
    translated = set(_DART_TRANSLATION_KEY.findall(dart_contract))

    assert emitted_or_guarded <= translated, (
        "Backend pricing reason codes lack explicit RU/UK UI translations: "
        f"{sorted(emitted_or_guarded - translated)}"
    )


def test_pricing_reason_codes_are_static_not_value_interpolated() -> None:
    root = Path(__file__).resolve().parents[2]
    engine = (root / "backend/src/metis/pricing/engine.py").read_text(encoding="utf-8")
    assert 'f"AGE_POLICY_' not in engine
