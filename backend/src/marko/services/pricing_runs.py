"""Persistence and orchestration services for pricing runs."""

from __future__ import annotations

import hashlib
import json
import math
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping
from uuid import UUID, uuid4

from celery import Celery
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import Settings, backend_config_path, get_settings
from marko.core.cost_encryption import CostCiphertextError
from marko.infrastructure.db.models import (
    CatalogIdentityLink,
    CatalogImportBatch,
    CatalogItem,
    CatalogItemCostRecord,
    CatalogItemOverride,
    CrossLink,
    FitmentCrossReference,
    MarketObservation,
    ObservationTierClassification,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    PricingRunPreviewContract,
    RecommendationDecision,
    ScrapeTarget,
    TierCalibrationPairRecord,
    TierCoefficientRecord,
)
from marko.services.catalog_costs import (
    add_cost_clear_record,
    add_encrypted_cost_record,
    get_decrypted_catalog_cost,
)
from marko.services.public_search_keys import (
    PublicSearchKey,
    build_public_search_keys,
)
from marko.services.catalog_identity_safety import (
    active_identity_graph_config,
    active_identity_runtime_sha256,
    catalog_identity_pair_has_safe_shape,
    confirmed_catalog_identity_conditions,
    is_internal_catalog_code,
)
from marko.services.cost_privacy import (
    CostPrivacyBlocked,
    privacy_safe_mapping,
)
from marko.services.cross_links import (
    CATALOG_IDENTITY_RUN_SNAPSHOT_EXTRACTION,
    CATALOG_IDENTITY_RUN_SNAPSHOT_METHOD,
)
from marko.services.fitment_cross_bridge import (
    FITMENT_CROSS_IDENTITY_KIND,
    FitmentCrossBridgeError,
    fitment_cross_snapshots_by_candidate,
    load_fitment_cross_authorities,
    validate_fitment_cross_snapshot,
)
from marko.services.scraper_architecture import (
    ADMISSION_POLICY_VERSION,
    SCRAPE_REQUEST_CONTRACT_VERSION,
    AcquisitionMode,
    ActorType,
    InputKind,
    ScrapeRequest,
    ScrapeRequestItem,
    SourceType,
    admit_prom_public_item,
    parser_contract_defaults,
)
from marko.services.scraper_contract import (
    PROM_ADAPTER_VERSION,
    QueryInput,
    ScrapeInput,
    ScraperBoundaryError,
    ScraperErrorCode,
    fallback_input_hash,
)
from marko.services.scraper_outbox import enqueue_dispatch, publish_dispatch
from marko.services.source_access import require_live_prom_marketplace_collection
from metis.pricing import (
    CalibrationPair,
    CoefficientModel,
    PricingPolicy,
    ProductPricingContext,
    ProductTier,
    StockStatus,
    TierCoefficient,
    calibration_dataset_hash,
    fit_shrinkage_coefficients,
    fit_simple_coefficients,
)
from metis.pricing.observability import pricing_event
from metis.pricing.raise_policy import (
    RaisePolicy,
    RaisePolicyConfigError,
    default_raise_policy,
    load_raise_policy,
)
from metis.pricing.tiering import TIER_METHOD_VERSION

PARSER_ADAPTER_VERSION = PROM_ADAPTER_VERSION
ACTIVE_RUN_STATUSES = (
    "queued",
    "running",
    "collecting",
    "classifying",
    "calibrating",
    "calculating",
)
TERMINAL_RUN_ITEM_STATUSES = ("calculated", "manual_review", "failed", "cancelled")
# These actions carry a price decision, even when the UI treats them as
# advisory.  A historical recommendation for a row whose identity is only a
# supplier/MPN code must never be exposed as an actionable market price: the
# query may have been performed against the wrong namespace.  Manual and
# insufficient-data outcomes remain visible so the operator can repair the
# catalog identity and rerun it.
PRICE_BEARING_RECOMMENDATION_ACTIONS = frozenset({"RAISE", "HOLD", "LOWER"})
IDENTITY_BLOCKED_RECOMMENDATION_ACTION = "CUSTOMER_OE_REQUIRED_FOR_PRICE_RECOMMENDATION"
CATALOG_OVERRIDE_SNAPSHOT_FIELDS = (
    "stock_status",
    "stock_qty",
    "stock_age_days",
    "expected_units_sold",
    "units_sold_30d",
    "units_sold_60d",
    "units_sold_90d",
    "days_since_last_sale",
    "historical_monthly_units",
    "views_30d",
    "conversion_rate_proxy",
    "manual_priority",
    "liquidity_target",
    "urgency",
    "allow_below_cost",
    "below_cost_warning_confirmed",
)


# Версия контракта области = версия канонических байт манифеста. Хеш области
# считается ровно по разделу ``execution`` манифеста, поэтому любое изменение
# состава этого раздела обязано менять и версию: иначе два несовместимых набора
# байт назывались бы одним контрактом.  v1 (без раздела ``execution``) остаётся
# читаемым, но байт-в-байт не воспроизводим и потому не повторяем.
PRICING_RUN_SCOPE_CONTRACT_VERSION = "pricing-run-scope-v3"
LEGACY_SCOPE_CONTRACT_VERSIONS = ("pricing-run-scope-v1",)
# Версия канонического документа политики исполнения. Меняется вместе с
# составом сохраняемых байт: иначе два несовместимых набора носили бы один
# отпечаток.
EXECUTION_POLICY_SNAPSHOT_VERSION = "pricing-run-policy-snapshot-v1"
# Версия контракта предпросмотра, выдаваемого сервером оператору.
PREVIEW_CONTRACT_VERSION = "pricing-run-preview-contract-v1"
# Сколько живёт выданный контракт. Предпросмотр — это утверждение о состоянии
# каталога на конкретный момент; бессрочный контракт таким утверждением не
# является.
PREVIEW_CONTRACT_TTL_SECONDS = 900
# Право, которым оператор запускает прогон. Контракт запоминает его вместе с
# ролью: старт после отзыва права — это не повтор, а другой запрос.
PRICING_RUN_START_PERMISSION = "pricing_run:start"
ACTOR_TYPE_USER = "user"
FULL_CATALOG_SCOPE = "FULL_CATALOG"
EXPLICIT_ITEMS_SCOPE = "EXPLICIT_ITEMS"
PRICING_RUN_SCOPE_MODES = (FULL_CATALOG_SCOPE, EXPLICIT_ITEMS_SCOPE)
MAX_EXPLICIT_SCOPE_ITEMS = 10_000
SCOPE_EXCLUSION_SAMPLE_LIMIT = 200
# Разделы манифеста — ключи контракта, они читаются из БД и из отчётов.
# ``execution``  — семантика исполнения; ровно эти байты и хешируются.
# ``advisory``   — оценки для оператора; они НЕ обязаны совпадать между
#                  предпросмотром и стартом и потому в хеш не входят.
# ``provenance`` — кто и на каком основании стартовал прогон.
SCOPE_MANIFEST_EXECUTION_SECTION = "execution"
SCOPE_MANIFEST_ADVISORY_SECTION = "advisory"
SCOPE_MANIFEST_PROVENANCE_SECTION = "provenance"
# Коды исключения — контракт с бейджами Flutter и с отчётами, менять нельзя.
SCOPE_EXCLUSION_ITEM_UNAVAILABLE = "ITEM_UNAVAILABLE"
CONFIRMATION_SOURCE_OPERATOR = "OPERATOR"
CONFIRMATION_SOURCE_SYSTEM_REPLAY = "SYSTEM_REPLAY"
CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY = "E2E_FIXTURE_REPLAY"
# Источник подтверждения и версия контракта, которыми отмечены строки, созданные
# ДО контракта ограниченной области. Только они вправе досчитываться по текущему
# файлу развёртывания: замораживать им было нечего.
CONFIRMATION_SOURCE_LEGACY_UNBOUNDED = "LEGACY_UNBOUNDED"
LEGACY_UNBOUNDED_SCOPE_CONTRACT = "LEGACY_UNBOUNDED"
# Полоса власти, по которой прогон был начат. Источник подтверждения уточняет
# основание внутри полосы (системный повтор или подстановка фикстур), полоса же
# отвечает на более грубый вопрос: человек это был или служба.
RUN_START_LANE_OPERATOR = "OPERATOR"
RUN_START_LANE_TRUSTED = "TRUSTED"
ACTOR_TYPE_SERVICE = "service"
# Только эти два источника вправе стартовать прогон без контракта предпросмотра,
# и каждый обязан назвать себя явно — «поля не передали» источником не является.
TRUSTED_CONFIRMATION_SOURCES = (
    CONFIRMATION_SOURCE_SYSTEM_REPLAY,
    CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
)
FULL_CATALOG_SELECTION_PREDICATE = (
    "catalog_items.import_batch_id = :import_batch_id "
    "AND catalog_items.workspace_id = :workspace_id "
    "AND catalog_items.is_available IS NOT FALSE"
)


class PricingRunError(RuntimeError):
    pass


class PricingRunScopeConflictError(PricingRunError):
    """Каталог сдвинулся между предпросмотром и запуском."""


class PricingRunIdempotencyConflictError(PricingRunError):
    """Тот же ключ идемпотентности пришёл с другой областью прогона."""


class PricingRunActiveScopeConflictError(PricingRunError):
    """По этому импорту уже идёт прогон с другой областью.

    Возвращать его как «свой» нельзя: оператор увидел бы чужой прогон вместо
    отказа и решил бы, что запущена именно его область.
    """


class PricingRunStartContractError(PricingRunError):
    """Старт без выданного сервером контракта предпросмотра."""


class PricingRunReplayError(PricingRunError):
    """Область исходного прогона невосстановима — системный повтор запрещён."""


class PricingRunExecutionPolicyError(PricingRunError):
    """Политика исполнения прогона не восстановима из его собственного снимка.

    Отдельный тип, а не общий ``PricingRunError``: «политику подменили», «снимок
    испорчен» и «заморозка потеряна» — это отказ считать историческую строку, а
    не ошибка заполнения запроса, и вызывающий обязан уметь отличить его от
    прочих отказов, не разбирая текст сообщения.
    """


class PricingRunNotFoundError(LookupError):
    pass


class RecommendationNotFoundError(LookupError):
    pass


class CatalogItemNotFoundError(LookupError):
    pass


class PricingTaskDispatchError(PricingRunError):
    pass


def _validate_decision_price(
    *,
    new_price: Decimal | None,
    cost: Decimal | None,
    approved_floor: Decimal | None,
    allow_below_cost: bool,
    warning_confirmed: bool,
) -> bool:
    """Validate the API-side below-cost boundary and return whether it applies."""
    is_below_cost = new_price is not None and cost is not None and new_price < cost
    if allow_below_cost and not warning_confirmed:
        raise PricingRunError("Below-cost warning must be explicitly confirmed")
    if is_below_cost and not allow_below_cost:
        raise PricingRunError("Below-cost price requires explicit allow_below_cost")
    if (
        is_below_cost
        and approved_floor is not None
        and new_price is not None
        and new_price < approved_floor
    ):
        raise PricingRunError("Decision price is below the approved below-cost floor")
    # With LOCAL_DEVICE_ONLY, the server receives only the operator's derived
    # acknowledgement and cannot independently reconstruct the comparison.
    return is_below_cost or (allow_below_cost and warning_confirmed)


def policy_to_dict(policy: PricingPolicy) -> dict[str, Any]:
    """Полный канонический снимок политики исполнения прогона.

    Раньше здесь оставался только «отпечаток личности» политики повышения, а
    сама она перечитывалась из файла развёртывания на каждом расчёте.  Это два
    разных утверждения: файл — источник для НОВОГО предпросмотра, а прогон —
    исторический вход уже принятого расчёта.  Пока в снимок не входило,
    например, ``target_quantile``, правка файла меняла результат прогона, не
    меняя ни одного сохранённого байта, и расхождение было невидимым.

    Поэтому здесь лежат ВСЕ поля ``PricingPolicy`` и ВСЕ поля ``RaisePolicy``,
    а полнота проверяется явно: выпавшее поле — это ошибка, а не умолчание.
    """

    payload = _json_safe(asdict(policy))
    raise_policy = payload.get("raise_policy")
    if not isinstance(raise_policy, Mapping):
        raise PricingRunError(
            "EXECUTION_POLICY_INCOMPLETE: the execution policy snapshot carries "
            "no raise policy; a run cannot be frozen against a policy it does "
            "not name"
        )
    _require_complete_dataclass_payload(RaisePolicy, raise_policy, "raise_policy")
    _require_complete_dataclass_payload(PricingPolicy, payload, "policy")
    return payload


def _require_complete_dataclass_payload(
    declared: type, payload: Mapping[str, Any], label: str
) -> None:
    """Каждое поле датакласса обязано быть в снимке — молча пропущенных нет."""

    missing = sorted({item.name for item in fields(declared)} - set(payload))
    if missing:
        raise PricingRunError(
            f"EXECUTION_POLICY_INCOMPLETE: {label} snapshot omits " + ", ".join(missing)
        )


def execution_policy_document(config: Mapping[str, Any]) -> dict[str, Any]:
    """Канонический документ вокруг сохранённого снимка политики.

    Ровно эти байты хешируются и предпросмотром, и стартом, и расчётом, и
    повтором — один документ, а не три независимо собранных отпечатка.
    """

    version = config.get("version")
    if not isinstance(version, str) or not version.strip():
        raise PricingRunError(
            "EXECUTION_POLICY_CORRUPT: the stored policy snapshot names no version"
        )
    return {
        "snapshot_version": EXECUTION_POLICY_SNAPSHOT_VERSION,
        "contract_version": PRICING_RUN_SCOPE_CONTRACT_VERSION,
        "policy_version": version,
        "policy": _json_safe(dict(config)),
    }


def execution_policy_hash(config: Mapping[str, Any]) -> str:
    """SHA-256 по каноническим байтам снимка политики исполнения."""

    return hashlib.sha256(
        _canonical_json(execution_policy_document(config)).encode("utf-8")
    ).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _coerce_dataclass_value(name: str, raw: Any, default: Any) -> Any:
    """Привести сохранённое значение к типу поля датакласса, не угадывая."""

    try:
        if isinstance(default, Decimal):
            value = Decimal(str(raw))
            if not value.is_finite():
                raise ValueError
            return value
        if isinstance(default, Enum):
            return type(default)(str(raw))
        if isinstance(default, Mapping):
            if not isinstance(raw, Mapping):
                raise ValueError
            return {
                **default,
                **{str(key): Decimal(str(item)) for key, item in raw.items()},
            }
        if isinstance(default, bool):
            if not isinstance(raw, bool):
                raise ValueError
            return raw
        if isinstance(default, int):
            if isinstance(raw, bool):
                raise ValueError
            return int(raw)
        if isinstance(default, str):
            return str(raw)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PricingRunError(f"Invalid policy value for {name}") from exc
    return raw


def _raise_policy_from_snapshot(payload: Mapping[str, Any]) -> RaisePolicy:
    """Собрать политику повышения ИЗ СНИМКА, не заглядывая в файл развёртывания."""

    _require_complete_dataclass_payload(RaisePolicy, payload, "raise_policy")
    reference = default_raise_policy()
    converted: dict[str, Any] = {}
    for item in fields(RaisePolicy):
        raw = payload[item.name]
        default = getattr(reference, item.name)
        if raw is None:
            converted[item.name] = None
            continue
        if default is None:
            # Поле, у которого в эталоне ``None``: тип берём из объявления, а
            # не из значения по умолчанию, иначе строка приехала бы как есть.
            annotation = str(item.type)
            if "Decimal" in annotation:
                converted[item.name] = _coerce_dataclass_value(
                    item.name, raw, Decimal("0")
                )
            elif "int" in annotation and "bool" not in annotation:
                converted[item.name] = _coerce_dataclass_value(item.name, raw, 0)
            else:
                converted[item.name] = str(raw)
            continue
        converted[item.name] = _coerce_dataclass_value(item.name, raw, default)
    try:
        return RaisePolicy(**converted)
    except (TypeError, ValueError) as exc:
        raise PricingRunExecutionPolicyError(
            f"EXECUTION_POLICY_CORRUPT: {exc}"
        ) from exc


def policy_from_snapshot(
    config: Mapping[str, Any] | None, *, expected_hash: str | None
) -> PricingPolicy:
    """Восстановить политику ТОЛЬКО из сохранённого снимка прогона.

    Файл развёртывания здесь не читается ни при каких условиях: он источник для
    НОВОГО предпросмотра, а не для уже принятого расчёта.  Отпечаток
    пересчитывается по тем же каноническим байтам и обязан совпасть: снимок,
    который никто не проверяет, — это просто ещё одна изменяемая копия.
    """

    if not isinstance(config, Mapping) or not config:
        raise PricingRunExecutionPolicyError(
            "EXECUTION_POLICY_MISSING: the run carries no execution policy "
            "snapshot; refusing to substitute the current deployment policy"
        )
    if not _is_sha256_hex(expected_hash):
        raise PricingRunExecutionPolicyError(
            "EXECUTION_POLICY_MISSING: the run carries no execution policy hash"
        )
    actual = execution_policy_hash(config)
    if actual != expected_hash:
        raise PricingRunExecutionPolicyError(
            "EXECUTION_POLICY_TAMPERED: the stored execution policy hashes to "
            f"{actual}, the run claims {expected_hash}"
        )
    raise_payload = config.get("raise_policy")
    if not isinstance(raise_payload, Mapping):
        raise PricingRunExecutionPolicyError(
            "EXECUTION_POLICY_CORRUPT: the stored snapshot carries no raise policy"
        )
    raise_policy = _raise_policy_from_snapshot(raise_payload)
    return _policy_from_mapping(
        {key: value for key, value in config.items() if key != "raise_policy"},
        raise_policy=raise_policy,
    )


def is_legacy_unbounded_run(run: Any) -> bool:
    """Настоящая доконтрактная строка — и только она вправе читать живую политику.

    «Легаси» — это не отсутствие отпечатка политики, а отсутствие ВСЕГО
    контракта: такой прогон не объявлял ни версии контракта области, ни
    подтверждения, ни отпечатков области и каталога, и заморозить ему было
    нечего.  Проверяются все эти признаки сразу, а не один: прогон, у которого
    область заморожена, а версия контракта обнулена, — это повреждённая или
    подделанная строка, а не история, и открывать ей путь к текущему файлу
    развёртывания нельзя.  Полулегаси не бывает: сомнение решается в пользу
    отказа.
    """

    version = (getattr(run, "scope_contract_version", None) or "").strip()
    if version and version != LEGACY_UNBOUNDED_SCOPE_CONTRACT:
        return False
    source = (getattr(run, "scope_confirmation_source", None) or "").strip()
    if source and source != CONFIRMATION_SOURCE_LEGACY_UNBOUNDED:
        return False
    for name in ("scope_hash", "catalog_snapshot_hash", "scope_frozen_at"):
        if getattr(run, name, None) is not None:
            return False
    return True


def load_run_execution_policy(run: PricingRun) -> PricingPolicy:
    """Политика прогона: только его собственный снимок, если прогон ограничен.

    Возврат к файлу развёртывания оставлен ровно для доконтрактных строк
    (``is_legacy_unbounded_run``): у них снимка никогда не было, и без этого
    пути их нельзя досчитать, не переписав историю.

    Для ограниченного прогона такого пути нет.  Прежде ветка выбиралась по
    одному признаку — «отпечаток похож на sha256 или нет», — поэтому строка,
    завершённая до миграции 0035, и строка с испорченным отпечатком обе тихо
    получали ТЕКУЩУЮ политику развёртывания и выдавали её за исторический вход
    расчёта.  Это ровно то, чего замораживание политики и должно было не
    допустить: пересчёт, повторное обогащение и воспроизведение обязаны
    отказаться, а не подставить чужую личность прогону, который её никогда не
    объявлял.
    """

    expected = getattr(run, "policy_snapshot_hash", None)
    if _is_sha256_hex(expected):
        return policy_from_snapshot(run.policy_config, expected_hash=expected)
    if not is_legacy_unbounded_run(run):
        detail = (
            "carries no execution policy hash"
            if expected is None
            else ("carries a malformed execution policy hash")
        )
        raise PricingRunExecutionPolicyError(
            f"EXECUTION_POLICY_NOT_FROZEN: run {getattr(run, 'id', '<unsaved>')} "
            f"declares scope contract "
            f"{getattr(run, 'scope_contract_version', None)!r} and {detail}; "
            "refusing to substitute the current deployment policy for a bounded "
            "run — recover the snapshot from a backup instead"
        )
    return policy_from_dict(run.policy_config)


def policy_from_dict(config: Mapping[str, Any] | None) -> PricingPolicy:
    """Политика для НОВОГО предпросмотра: файл развёртывания — её источник."""

    return _policy_from_mapping(config, raise_policy=_configured_raise_policy())


def _policy_from_mapping(
    config: Mapping[str, Any] | None, *, raise_policy: RaisePolicy
) -> PricingPolicy:
    defaults = replace(PricingPolicy(), raise_policy=raise_policy)
    if not config:
        return defaults
    # The raise target and its guards are owned by the deployment's policy file,
    # not by a per-run override, so a stray key is an error rather than a silent
    # second source of truth.
    allowed = {field.name for field in fields(PricingPolicy)} - {"raise_policy"}
    config = {
        key: value
        for key, value in config.items()
        if key not in {"raise_policy_identity", "raise_policy"}
    }
    unknown = set(config) - allowed
    if unknown:
        raise PricingRunError(
            "Unknown pricing policy fields: " + ", ".join(sorted(unknown))
        )
    converted: dict[str, Any] = {
        name: _coerce_dataclass_value(name, raw, getattr(defaults, name))
        for name, raw in config.items()
    }
    converted["raise_policy"] = raise_policy
    try:
        policy = PricingPolicy(**converted)
        _validate_policy(policy)
    except ValueError as exc:
        raise PricingRunError(str(exc)) from exc
    return policy


def _configured_raise_policy() -> RaisePolicy:
    """Materialize the raise policy from the deployment's config file."""

    configured = get_settings().pricing_raise_policy_path.strip()
    if not configured:
        return default_raise_policy()
    try:
        return load_raise_policy(backend_config_path(configured))
    except RaisePolicyConfigError as exc:
        raise PricingRunError(f"Invalid raise policy: {exc}") from exc


def _validate_policy(policy: PricingPolicy) -> None:
    # PricingPolicy.__post_init__ is the canonical validation boundary.
    if not policy.version.strip():
        raise PricingRunError("pricing policy version is required")


def require_activated_run_policy(
    policy: PricingPolicy,
    *,
    robust_v3_enabled: bool,
    activation_artifact_verified: bool = False,
) -> None:
    if policy.version in {
        "pricing-v3-robust-dispersion",
        "pricing-v3.1-heterogeneity-gated",
    } and not (robust_v3_enabled and activation_artifact_verified):
        raise PricingRunError(
            "robust pricing activation is NO_GO: the policy is implemented for "
            "preview/replay, but persisted activation requires both the explicit "
            "feature flag and a verified versioned activation artifact"
        )


def activation_artifact_verified(path_value: str, expected_sha256: str) -> bool:
    if not path_value.strip() or len(expected_sha256.strip()) != 64:
        return False
    try:
        payload = Path(path_value).expanduser().read_bytes()
    except OSError:
        return False
    return hashlib.sha256(payload).hexdigest() == expected_sha256.strip().casefold()


@dataclass(frozen=True, slots=True)
class ScopeCandidate:
    """Позиция каталога в том виде, в каком её видит предпросмотр и старт прогона.

    Здесь обязан лежать КАЖДЫЙ вход исполнения, который потом действительно
    читается: сбор, отождествление, подбор коэффициентов и расчёт.  Поле, не
    попавшее сюда, не попадает ни в снимок, ни в его отпечаток, а значит
    читается из живого каталога — и правка после старта молча меняет результат.
    """

    catalog_item_id: UUID
    source_row: int
    sku: str
    oe_norm: str
    mpn_norm: str
    name: str
    brand: str | None
    category: str
    current_price: Decimal
    currency: str
    stock_status: str
    product_url: str | None
    is_available: bool | None
    stock_qty: Decimal | None
    stock_age_days: Decimal | None
    expected_units_sold: Decimal | None
    units_sold_30d: Decimal | None
    units_sold_60d: Decimal | None
    units_sold_90d: Decimal | None
    days_since_last_sale: Decimal | None
    historical_monthly_units: Decimal | None
    views_30d: Decimal | None
    conversion_rate_proxy: Decimal | None
    manual_priority: Decimal | None
    identity_status: str
    override_id: UUID | None
    # Содержимое действующей правки, а не только её идентификатор: расчёт читает
    # именно значения, поэтому в снимке обязаны лежать значения.
    override_values: Mapping[str, Any] | None
    cost_record_id: UUID | None
    cost_record_sequence_no: int | None
    part_numbers_norm: tuple[str, ...] = ()
    identity_reason: str | None = None
    # Confirmed one-hop identity edges are execution inputs.  Keeping their
    # full provenance here makes preview/start hashing detect a graph change and
    # lets the run persist exactly the links the operator previewed.
    confirmed_identity_links: tuple[Mapping[str, Any], ...] = ()
    # Semantic identity inputs used by the comparability/Luna layer. Keeping
    # them outside the frozen scope let a catalog edit change a running review
    # without changing its run membership or pricing inputs.
    oe_raw: str = ""
    mpn_raw: str = ""
    description: str | None = None
    applicability_brands: tuple[str, ...] = ()
    applicability_models: tuple[str, ...] = ()
    characteristics_raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScopeExclusion:
    catalog_item_id: UUID
    sku: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class PricingRunScopeEstimate:
    requested_items: int
    eligible_items: int
    excluded_items: int
    unique_scrape_inputs: int
    duplicate_items: int
    worst_case_duration_seconds: int
    network_eligible_items: int = 0
    identity_blocked_items: int = 0


@dataclass(frozen=True, slots=True)
class PricingRunScope:
    """Замороженная область прогона: то, что предпросмотр обещает исполнителю."""

    contract_version: str
    workspace_id: UUID
    import_batch_id: UUID
    scope_mode: str
    policy_version: str
    policy_hash: str
    catalog_snapshot_hash: str
    scope_hash: str
    items: tuple[ScopeCandidate, ...]
    exclusions: tuple[ScopeExclusion, ...]
    exclusions_truncated: bool
    estimate: PricingRunScopeEstimate
    requires_full_catalog_confirmation: bool
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def execution(self) -> Mapping[str, Any]:
        """Исполняемая часть манифеста — ровно то, по чему считается хеш."""

        return self.manifest[SCOPE_MANIFEST_EXECUTION_SECTION]


MIN_PUBLIC_QUERY_NUMBER_LENGTH = 4


def customer_identity_query_from_fields(
    *,
    identity_status: str | None,
    oe_norm: str | None,
    mpn_norm: str | None,
    part_numbers_norm: Iterable[str] = (),
) -> str:
    """Resolve one safe retrieval number from a catalog identity snapshot.

    This field-level form is shared by pricing-run scope and the catalog
    discovery API.  Keeping the rule in one pure function prevents the UI
    discovery path from reintroducing the old ``oe_norm``-first behavior for
    rows whose ``oe_norm`` is actually a private KEMP shelf code.
    """
    def public(value: str | None) -> str:
        normalized = str(value or "").strip()
        return (
            normalized
            if normalized and not is_internal_catalog_code(normalized)
            else ""
        )

    def usable_fallback(value: str | None) -> str:
        """Return a non-authoritative public number safe for retrieval fallback.

        A short alphanumeric manufacturer code can be meaningful (for example
        ``A1``), while a bare three-digit value is commonly a truncated export
        prefix and produces a large, unrelated Prom result set.  Exact
        ``OE_CONFIRMED`` values are handled separately and are not subject to
        this heuristic: their graph status is the authority.
        """

        normalized = public(value)
        if not normalized:
            return ""
        if normalized.isdigit() and len(normalized) < MIN_PUBLIC_QUERY_NUMBER_LENGTH:
            return ""
        return normalized

    # ``identity_status`` is persisted by import/reparse, but legacy rows and
    # external adapters may differ only by case.  Namespace selection must be
    # stable across those representations: an OE-confirmed row must always
    # search its original vehicle OE, never fall through to the supplier MPN.
    status = str(identity_status or "").strip().upper()
    oe = public(oe_norm)
    mpn = public(mpn_norm)
    part_numbers = tuple(
        number
        for value in part_numbers_norm
        if (number := public(value))
    )
    if status == "OE_CONFIRMED":
        # An explicit OE namespace is a contract, not a preference order.  If
        # its value is absent/private, refuse the row instead of silently
        # searching the supplier MPN and making that unrelated number look like
        # the vehicle identity.
        return oe
    if status == "MPN_ONLY":
        # ``oe_norm`` is not an OE in this namespace.  For the canonical KEMP
        # export it can still contain a private 776... shelf code, while the
        # actual public article is present in the characteristics list.  Never
        # let the shelf code become a Prom query.  A complete MPN wins; when
        # the spreadsheet truncated it to a short numeric prefix (for example
        # ``115`` instead of ``115070``), use the public characteristic token
        # instead.  If no such token exists, retain the explicit MPN.
        # Do not fall back to ``oe_norm`` here.  In this namespace that field is
        # explicitly *not* an asserted original OE: the canonical customer
        # export stores ``Код_товару`` there, and it may be a private KEMP shelf
        # code or an unresolved supplier number.  Treating it as a public
        # market query would silently promote an unverified value to identity
        # evidence.  A row without a public MPN/part number must remain
        # identity-blocked until the import/reparse assigns an explicit
        # ``OE_CONFIRMED`` status.
        usable_mpn = usable_fallback(mpn)
        if usable_mpn and len(usable_mpn) >= MIN_PUBLIC_QUERY_NUMBER_LENGTH:
            return usable_mpn
        for number in part_numbers:
            usable_number = usable_fallback(number)
            if usable_number and len(usable_number) >= MIN_PUBLIC_QUERY_NUMBER_LENGTH:
                return usable_number
        # Keep a non-numeric short MPN available as a retrieval fallback; a
        # short numeric prefix is identity-blocked rather than sent to Prom.
        return usable_mpn
    usable_mpn = usable_fallback(mpn)
    if usable_mpn:
        return usable_mpn
    for number in part_numbers:
        if usable_number := usable_fallback(number):
            return usable_number
    return ""


def customer_identity_query(candidate: ScopeCandidate) -> str:
    """Choose a query only from identity evidence, never from an unknown code."""

    return customer_identity_query_from_fields(
        identity_status=candidate.identity_status,
        oe_norm=candidate.oe_norm,
        mpn_norm=candidate.mpn_norm,
        part_numbers_norm=candidate.part_numbers_norm,
    )


def customer_public_search_keys(
    candidate: ScopeCandidate,
) -> tuple[PublicSearchKey, ...]:
    """Ordered public Prom query keys for multi-key discovery expansion.

    The first pricing-primary key (when present) matches
    ``customer_identity_query`` for OE_CONFIRMED rows.  Additional CROSS / MPN /
    characteristic numbers expand retrieval only; they do not relax
    ``customer_identity_available``.
    """

    primary = customer_identity_query(candidate)
    return build_public_search_keys(
        identity_status=candidate.identity_status,
        oe_norm=candidate.oe_norm,
        mpn_norm=candidate.mpn_norm,
        part_numbers_norm=candidate.part_numbers_norm,
        confirmed_identity_links=candidate.confirmed_identity_links,
        primary_query=primary or None,
    )


def declared_widenings(candidate: ScopeCandidate) -> tuple[str, ...]:
    """Confirmed cross numbers this row may widen retrieval with.

    The original vehicle OE stays the market identity; a cross is an allowed
    widening only when it comes from a confirmed graph edge with provenance,
    so ``retrieval_only`` keys — MPNs and characteristic part numbers — are
    excluded here even though they are safe to *search*. Freezing the list
    into the acquisition input is what lets the persisted boundary refuse a
    widening the run never declared.
    """

    return tuple(
        key.number
        for key in customer_public_search_keys(candidate)
        if key.role == "CROSS" and key.confidence == "confirmed"
    )


def retrieval_only_queries(candidate: ScopeCandidate) -> tuple[str, ...]:
    """Public keys this row may *search* with but never be identified by.

    The row's own supplier MPN and its characteristic part numbers. They are
    the complement of :func:`declared_widenings`: safe to send to Prom, and
    carrying no claim about what comes back. A row one of these retrieved is
    still verified against the original vehicle OE — it earns its evidence off
    the card or it stays discovery / manual review. Freezing them separately
    is what lets the persistence boundary tell the two tiers apart instead of
    seeing one anonymous pile of extra queries.
    """

    return tuple(
        key.number
        for key in customer_public_search_keys(candidate)
        if key.role in {"PUBLIC_MPN", "PART_NUMBER"}
    )


def customer_search_context(candidate: ScopeCandidate) -> str:
    """Frozen retrieval-only context; it is never candidate identity evidence."""

    return " ".join(
        value.strip()
        for value in (candidate.brand or "", candidate.name or "")
        if value and value.strip()
    )[:255]


def customer_identity_available(candidate: ScopeCandidate) -> bool:
    """Whether this row may create a *pricing* market-acquisition input.

    The discovery layer may still use an MPN or a customer part-number list to
    enrich a row for operator review. A pricing run is stricter: its primary
    market query must be an asserted vehicle OE. This prevents a KEMP/private
    manufacturer number from becoming a hidden Prom query and then looking like
    an original-part market identity downstream.
    """

    status = str(getattr(candidate, "identity_status", "") or "").strip().upper()
    if status != "OE_CONFIRMED":
        return False
    value = str(getattr(candidate, "oe_norm", "") or "").strip()
    return bool(value and not is_internal_catalog_code(value))


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_manifest_bytes(section: Mapping[str, Any]) -> bytes:
    """Канонические байты манифеста: единственный вход хеша области.

    Порядок ключей не значим (``sort_keys``), порядок списков значим — членство
    прогона упорядочено, и его перестановка обязана менять хеш.
    """

    return _canonical_json(section).encode("utf-8")


def scope_manifest_hash(manifest: Mapping[str, Any]) -> str:
    """SHA-256 по каноническим байтам исполняемого раздела манифеста.

    Предпросмотр и старт сравнивают именно это значение, то есть одни и те же
    байты, а не два независимо собранных отпечатка.
    """

    section = manifest.get(SCOPE_MANIFEST_EXECUTION_SECTION)
    if not isinstance(section, Mapping):
        raise PricingRunError(
            "SCOPE_MANIFEST_UNVERSIONED: manifest carries no "
            f"'{SCOPE_MANIFEST_EXECUTION_SECTION}' section"
        )
    return hashlib.sha256(canonical_manifest_bytes(section)).hexdigest()


def policy_fingerprint(policy: PricingPolicy) -> str:
    """Отпечаток действующей политики: содержимое, а не только ярлык версии.

    Версия — это подпись под содержимым, но она не является содержимым: две
    разные настройки под одним ярлыком дали бы одинаковый хеш области и
    молча исполнились бы как один и тот же прогон.

    Это ровно тот же вызов, которым считается ``policy_snapshot_hash``
    сохранённого прогона: хеш области и сохранённая политика связаны ОДНИМИ И
    ТЕМИ ЖЕ каноническими байтами, а не двумя похожими отпечатками.
    """

    return execution_policy_hash(policy_to_dict(policy))


def membership_digest(catalog_item_ids: Sequence[UUID]) -> str:
    """Отпечаток упорядоченного членства прогона.

    Хранить весь список в манифесте полного каталога нельзя (он вырастает до
    размеров каталога), но хеш обязан связывать и состав, и порядок.
    """

    return _sha256_payload(
        {
            "contract_version": PRICING_RUN_SCOPE_CONTRACT_VERSION,
            "ordered_catalog_item_ids": [str(value) for value in catalog_item_ids],
        }
    )


def _exclusion_digest(exclusions: Sequence[ScopeExclusion]) -> str:
    return _sha256_payload(
        {
            "contract_version": PRICING_RUN_SCOPE_CONTRACT_VERSION,
            "ordered_exclusions": [
                {
                    "catalog_item_id": str(exclusion.catalog_item_id),
                    "reason_code": exclusion.reason_code,
                }
                for exclusion in exclusions
            ],
        }
    )


def scope_input_key(candidate: ScopeCandidate) -> str:
    """Тот же ключ дедупликации, что и у сетевых входов прогона (оценка сверху)."""

    if not customer_identity_available(candidate):
        return f"identity-missing:{candidate.catalog_item_id}"
    url = (candidate.product_url or "").strip()
    if url:
        return f"url:{url}"
    return "query:" + " ".join(customer_identity_query(candidate).upper().split())


def _candidate_fingerprint(candidate: ScopeCandidate) -> dict[str, Any]:
    """Отпечаток позиции = ровно те поля, которые исполнение потом читает.

    Отпечаток строится из ТОГО ЖЕ документа, что и замороженный снимок позиции:
    поле, добавленное в снимок, автоматически попадает и в хеш каталога, и
    разойтись они не могут.
    """

    payload = _catalog_item_snapshot(candidate)
    # Правка оператора и запись себестоимости входят в отпечаток: иначе
    # изменение контекста между предпросмотром и стартом осталось бы невидимым.
    payload["cost_record_sequence_no"] = candidate.cost_record_sequence_no
    return payload


def catalog_snapshot_fingerprint(candidates: Iterable[ScopeCandidate]) -> str:
    """SHA-256 по всему импортированному каталогу, независимо от порядка выборки."""

    fingerprints = sorted(
        (_candidate_fingerprint(candidate) for candidate in candidates),
        key=lambda payload: payload["catalog_item_id"],
    )
    return _sha256_payload(
        {
            "contract_version": PRICING_RUN_SCOPE_CONTRACT_VERSION,
            "items": fingerprints,
        }
    )


def scope_execution_manifest(
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    scope_mode: str,
    policy_version: str,
    policy_hash: str,
    catalog_snapshot_hash: str,
    requested_item_ids: Sequence[UUID],
    catalog_item_ids: Sequence[UUID],
    exclusions: Sequence[ScopeExclusion],
) -> dict[str, Any]:
    """Исполняемый раздел манифеста: всё, что определяет, ЧТО будет исполнено.

    Оценки сюда не входят намеренно: они советуют оператору, а не задают
    исполнение, и их дрейф не должен отменять уже подтверждённый предпросмотр.
    """

    selection: dict[str, Any] = {
        "materialized_in": "pricing_run_items",
        "ordering": "catalog_items.source_row, catalog_items.sku",
        "eligibility": "catalog_items.is_available IS NOT FALSE",
    }
    membership: dict[str, Any] = {
        "count": len(catalog_item_ids),
        "digest": membership_digest(catalog_item_ids),
    }
    if scope_mode == FULL_CATALOG_SCOPE:
        selection["predicate"] = FULL_CATALOG_SELECTION_PREDICATE
    else:
        selection["requested_catalog_item_ids"] = [
            str(value) for value in requested_item_ids
        ]
        # Ограниченная область перечисляет членство целиком: именно её повтор
        # обязан воспроизвести позиция-в-позицию, а не «весь каталог».
        membership["catalog_item_ids"] = [str(value) for value in catalog_item_ids]
    return {
        "contract_version": PRICING_RUN_SCOPE_CONTRACT_VERSION,
        "scope_mode": scope_mode,
        "workspace_id": str(workspace_id),
        "import_batch_id": str(import_batch_id),
        "policy_version": policy_version,
        "policy_hash": policy_hash,
        "catalog_snapshot_hash": catalog_snapshot_hash,
        "selection": selection,
        "membership": membership,
        "exclusions": {
            "count": len(exclusions),
            "digest": _exclusion_digest(exclusions),
            "counts_by_reason_code": _exclusion_counts(exclusions),
        },
    }


def _exclusion_counts(exclusions: Sequence[ScopeExclusion]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for exclusion in exclusions:
        counts[exclusion.reason_code] = counts.get(exclusion.reason_code, 0) + 1
    return counts


def _worst_case_duration_seconds(unique_inputs: int, settings: Any) -> int:
    """Верхняя граница длительности: дедлайны на воркерах или глобальный троттлинг."""

    workers = max(1, int(settings.pricing_collection_worker_count))
    deadline = max(1, int(settings.pricing_collection_item_deadline_seconds))
    throttle = float(settings.pricing_collection_min_interval_seconds)
    by_deadline = math.ceil(unique_inputs / workers) * deadline
    by_throttle = math.ceil(unique_inputs * max(0.0, throttle))
    return int(max(by_deadline, by_throttle))


def build_pricing_run_scope(
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    scope_mode: str,
    requested_item_ids: Sequence[UUID],
    catalog_candidates: Sequence[ScopeCandidate],
    policy_version: str,
    policy_hash: str,
    settings: Any,
) -> PricingRunScope:
    """Детерминированно вывести область прогона из состояния каталога."""

    if scope_mode not in PRICING_RUN_SCOPE_MODES:
        raise PricingRunError(f"SCOPE_MODE_UNKNOWN: {scope_mode}")
    requested = list(dict.fromkeys(requested_item_ids))
    if scope_mode == EXPLICIT_ITEMS_SCOPE:
        if not requested:
            raise PricingRunError("SCOPE_EMPTY: EXPLICIT_ITEMS requires catalog items")
        if len(requested) > MAX_EXPLICIT_SCOPE_ITEMS:
            raise PricingRunError(
                f"SCOPE_TOO_LARGE: at most {MAX_EXPLICIT_SCOPE_ITEMS} items per run"
            )
    elif requested:
        raise PricingRunError("SCOPE_MODE_CONFLICT: FULL_CATALOG takes no item list")

    by_id = {candidate.catalog_item_id: candidate for candidate in catalog_candidates}
    if scope_mode == EXPLICIT_ITEMS_SCOPE:
        missing = [value for value in requested if value not in by_id]
        if missing:
            raise PricingRunError(
                "SCOPE_ITEM_NOT_FOUND: "
                + ", ".join(str(value) for value in sorted(missing, key=str))
            )
        selected = [by_id[value] for value in requested]
    else:
        selected = list(catalog_candidates)
    selected.sort(key=lambda candidate: (candidate.source_row, str(candidate.sku)))

    items: list[ScopeCandidate] = []
    exclusions: list[ScopeExclusion] = []
    for candidate in selected:
        if candidate.is_available is False:
            exclusions.append(
                ScopeExclusion(
                    catalog_item_id=candidate.catalog_item_id,
                    sku=candidate.sku,
                    reason_code=SCOPE_EXCLUSION_ITEM_UNAVAILABLE,
                )
            )
            continue
        items.append(candidate)
    if not items:
        raise PricingRunError("SCOPE_EMPTY: no eligible catalog rows in the scope")

    network_candidates = [
        candidate for candidate in items if customer_identity_available(candidate)
    ]
    unique_inputs = len(
        {scope_input_key(candidate) for candidate in network_candidates}
    )
    estimate = PricingRunScopeEstimate(
        requested_items=len(selected),
        eligible_items=len(items),
        excluded_items=len(exclusions),
        unique_scrape_inputs=unique_inputs,
        duplicate_items=len(network_candidates) - unique_inputs,
        worst_case_duration_seconds=_worst_case_duration_seconds(
            unique_inputs, settings
        ),
        network_eligible_items=len(network_candidates),
        identity_blocked_items=len(items) - len(network_candidates),
    )
    snapshot_hash = catalog_snapshot_fingerprint(catalog_candidates)
    truncated = len(exclusions) > SCOPE_EXCLUSION_SAMPLE_LIMIT
    # Манифест хранит предикат отбора, упорядоченное членство и отпечатки, а не
    # копию каталога: сам список позиций материализован в pricing_run_items и не
    # должен разъезжаться с ним второй копией.
    execution = scope_execution_manifest(
        workspace_id=workspace_id,
        import_batch_id=import_batch_id,
        scope_mode=scope_mode,
        policy_version=policy_version,
        policy_hash=policy_hash,
        catalog_snapshot_hash=snapshot_hash,
        requested_item_ids=requested,
        catalog_item_ids=[candidate.catalog_item_id for candidate in items],
        exclusions=exclusions,
    )
    manifest: dict[str, Any] = {
        "contract_version": PRICING_RUN_SCOPE_CONTRACT_VERSION,
        SCOPE_MANIFEST_EXECUTION_SECTION: execution,
        SCOPE_MANIFEST_ADVISORY_SECTION: {
            "catalog_items_in_batch": len(catalog_candidates),
            "estimate": asdict(estimate),
            "exclusion_counts": _exclusion_counts(exclusions),
            "exclusions": [
                {
                    "catalog_item_id": str(exclusion.catalog_item_id),
                    "sku": exclusion.sku,
                    "reason_code": exclusion.reason_code,
                }
                for exclusion in exclusions[:SCOPE_EXCLUSION_SAMPLE_LIMIT]
            ],
            "exclusions_truncated": truncated,
        },
    }
    # Хеш области = хеш сохраняемых байт манифеста, а не отдельно собранный
    # отпечаток: иначе манифест и хеш живут своей жизнью и расходятся молча.
    hash_value = scope_manifest_hash(manifest)
    manifest["scope_hash"] = hash_value
    return PricingRunScope(
        contract_version=PRICING_RUN_SCOPE_CONTRACT_VERSION,
        workspace_id=workspace_id,
        import_batch_id=import_batch_id,
        scope_mode=scope_mode,
        policy_version=policy_version,
        policy_hash=policy_hash,
        catalog_snapshot_hash=snapshot_hash,
        scope_hash=hash_value,
        items=tuple(items),
        exclusions=tuple(exclusions),
        exclusions_truncated=truncated,
        estimate=estimate,
        requires_full_catalog_confirmation=scope_mode == FULL_CATALOG_SCOPE,
        manifest=manifest,
    )


async def load_scope_candidates(
    session: AsyncSession, *, workspace_id: UUID, import_batch_id: UUID
) -> list[ScopeCandidate]:
    """Каталог импорта вместе с действующими на этот момент правками и ценами."""

    override_ranked = (
        select(
            CatalogItemOverride.catalog_item_id.label("catalog_item_id"),
            CatalogItemOverride.id.label("override_id"),
            func.row_number()
            .over(
                partition_by=CatalogItemOverride.catalog_item_id,
                order_by=(
                    CatalogItemOverride.created_at.desc(),
                    CatalogItemOverride.id.desc(),
                ),
            )
            .label("row_position"),
        )
        .join(CatalogItem, CatalogItem.id == CatalogItemOverride.catalog_item_id)
        .where(
            CatalogItem.workspace_id == workspace_id,
            CatalogItem.import_batch_id == import_batch_id,
        )
        .subquery()
    )
    latest_override = (
        select(override_ranked.c.catalog_item_id, override_ranked.c.override_id)
        .where(override_ranked.c.row_position == 1)
        .subquery()
    )
    cost_ranked = (
        select(
            CatalogItemCostRecord.catalog_item_id.label("catalog_item_id"),
            CatalogItemCostRecord.id.label("cost_record_id"),
            CatalogItemCostRecord.sequence_no.label("sequence_no"),
            func.row_number()
            .over(
                partition_by=CatalogItemCostRecord.catalog_item_id,
                order_by=CatalogItemCostRecord.sequence_no.desc(),
            )
            .label("row_position"),
        )
        .join(CatalogItem, CatalogItem.id == CatalogItemCostRecord.catalog_item_id)
        .where(
            CatalogItemCostRecord.workspace_id == workspace_id,
            CatalogItem.import_batch_id == import_batch_id,
        )
        .subquery()
    )
    latest_cost = (
        select(
            cost_ranked.c.catalog_item_id,
            cost_ranked.c.cost_record_id,
            cost_ranked.c.sequence_no,
        )
        .where(cost_ranked.c.row_position == 1)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                CatalogItem,
                CatalogItemOverride,
                latest_cost.c.cost_record_id,
                latest_cost.c.sequence_no,
            )
            .outerjoin(
                latest_override,
                latest_override.c.catalog_item_id == CatalogItem.id,
            )
            # Содержимое правки читается здесь же: снимок обязан нести значения,
            # а не ссылку, по которой расчёт снова пойдёт в живую строку.
            .outerjoin(
                CatalogItemOverride,
                CatalogItemOverride.id == latest_override.c.override_id,
            )
            .outerjoin(latest_cost, latest_cost.c.catalog_item_id == CatalogItem.id)
            .where(
                CatalogItem.workspace_id == workspace_id,
                CatalogItem.import_batch_id == import_batch_id,
            )
            .order_by(CatalogItem.source_row, CatalogItem.sku)
        )
    ).all()
    item_ids = [item.id for item, _, _, _ in rows]
    links_by_item: dict[UUID, list[dict[str, Any]]] = {}
    if item_ids:
        identity_links = list(
            (
                await session.scalars(
                    select(CatalogIdentityLink)
                    .where(
                        *confirmed_catalog_identity_conditions(workspace_id),
                        CatalogIdentityLink.catalog_item_id.in_(item_ids),
                    )
                    .order_by(
                        CatalogIdentityLink.catalog_item_id,
                        CatalogIdentityLink.our_oem_norm,
                        CatalogIdentityLink.extracted_oem_norm,
                        CatalogIdentityLink.extraction_method,
                        CatalogIdentityLink.sequence_no,
                    )
                )
            ).all()
        )
        for link in identity_links:
            if not catalog_identity_pair_has_safe_shape(
                link.our_oem_norm, link.extracted_oem_norm
            ):
                continue
            links_by_item.setdefault(link.catalog_item_id, []).append(
                _catalog_identity_link_snapshot(link)
            )

    candidates = [
        ScopeCandidate(
            catalog_item_id=item.id,
            source_row=item.source_row,
            sku=item.sku,
            oe_norm=item.oe_norm,
            oe_raw=item.oe_raw,
            mpn_norm=item.mpn_norm,
            mpn_raw=item.mpn_raw,
            name=item.name,
            brand=item.brand,
            category=item.category,
            current_price=item.current_price,
            currency=item.currency,
            stock_status=item.stock_status,
            product_url=item.product_url,
            is_available=item.is_available,
            stock_qty=item.stock_qty,
            stock_age_days=item.stock_age_days,
            expected_units_sold=item.expected_units_sold,
            units_sold_30d=item.units_sold_30d,
            units_sold_60d=item.units_sold_60d,
            units_sold_90d=item.units_sold_90d,
            days_since_last_sale=item.days_since_last_sale,
            historical_monthly_units=item.historical_monthly_units,
            views_30d=item.views_30d,
            conversion_rate_proxy=item.conversion_rate_proxy,
            manual_priority=item.manual_priority,
            identity_status=item.identity_status,
            part_numbers_norm=tuple(item.part_numbers_norm or ()),
            description=item.description,
            applicability_brands=tuple(item.applicability_brands or ()),
            applicability_models=tuple(item.applicability_models or ()),
            characteristics_raw=dict(item.characteristics_raw or {}),
            identity_reason=item.identity_reason,
            confirmed_identity_links=tuple(links_by_item.get(item.id, ())),
            override_id=override.id if override is not None else None,
            override_values=_override_values(override),
            cost_record_id=cost_record_id,
            cost_record_sequence_no=(
                int(sequence_no) if sequence_no is not None else None
            ),
        )
        for item, override, cost_record_id, sequence_no in rows
    ]
    if not candidates:
        return candidates

    # Fitment cross references are append-only knowledge records, separate from
    # the customer reference graph.  Load every revision so the bridge can
    # identify superseded leaves and live conflicts instead of accidentally
    # reviving an older confirmation.
    fitment_crosses = list(
        (
            await session.scalars(
                select(FitmentCrossReference)
                .where(FitmentCrossReference.workspace_id == workspace_id)
                .order_by(
                    FitmentCrossReference.valid_from,
                    FitmentCrossReference.id,
                )
            )
        ).all()
    )
    fitment_authorities = await load_fitment_cross_authorities(
        session,
        workspace_id=workspace_id,
        records=fitment_crosses,
    )
    fitment_by_item = fitment_cross_snapshots_by_candidate(
        candidate_queries={
            candidate.catalog_item_id: customer_identity_query(candidate)
            for candidate in candidates
        },
        records=fitment_crosses,
        authorities=fitment_authorities,
    )
    return [
        replace(
            candidate,
            confirmed_identity_links=(
                *candidate.confirmed_identity_links,
                *fitment_by_item.get(candidate.catalog_item_id, ()),
            ),
        )
        for candidate in candidates
    ]


def _catalog_identity_link_snapshot(link: CatalogIdentityLink) -> dict[str, Any]:
    """Canonical evidence document copied into a bounded pricing run."""

    return {
        "catalog_identity_link_id": str(link.id),
        "catalog_item_id": str(link.catalog_item_id),
        "our_oem_norm": link.our_oem_norm,
        "extracted_oem_norm": link.extracted_oem_norm,
        "extracted_raw": link.extracted_raw,
        "raw_context": link.raw_context,
        "extraction_method": link.extraction_method,
        "validation_status": link.validation_status,
        "anomaly": link.anomaly,
        "corroborating_sources": list(link.corroborating_sources or ()),
        "validation_details": _json_safe(dict(link.validation_details or {})),
        "method_version": link.method_version,
        "config_sha256": link.config_sha256,
    }


def _frozen_catalog_cross_rows(
    *, run: PricingRun, candidates: Sequence[ScopeCandidate]
) -> list[CrossLink]:
    """Materialize the previewed identity graph as run-owned evidence.

    ``catalog_identity_links`` outlive every pricing run and can be reparsed.
    A run must not read that mutable graph later, so each unique confirmed pair
    is copied at start from the already-hashed ``ScopeCandidate`` snapshot.
    Multiple source rows for the same pair remain visible inside
    ``source_evidence`` rather than violating the run-pair uniqueness key.
    """

    rows: list[CrossLink] = []
    grouped: dict[tuple[str, str], list[tuple[UUID, dict[str, Any]]]] = {}
    active_graph = active_identity_graph_config()
    active_runtime_sha256 = active_identity_runtime_sha256()
    for candidate in candidates:
        for raw in candidate.confirmed_identity_links:
            link = dict(raw)
            if link.get("validation_status") != "CONFIRMED" or link.get("anomaly"):
                # The loader already filters these.  Re-check because a
                # hand-built trusted scope must not smuggle REVIEW evidence in.
                raise PricingRunStartContractError(
                    "IDENTITY_GRAPH_NOT_CONFIRMED: a frozen identity edge is not "
                    "eligible for a pricing run"
                )
            evidence_kind = str(
                link.get("identity_evidence_kind") or "CATALOG_IDENTITY"
            )
            if evidence_kind == FITMENT_CROSS_IDENTITY_KIND:
                try:
                    link = validate_fitment_cross_snapshot(
                        link,
                        catalog_item_id=candidate.catalog_item_id,
                        customer_query=customer_identity_query(candidate),
                    )
                except FitmentCrossBridgeError as exc:
                    raise PricingRunStartContractError(
                        f"FITMENT_CROSS_INVALID: {exc}"
                    ) from exc
            elif evidence_kind == "CATALOG_IDENTITY":
                if (
                    link.get("method_version") != active_graph.method_version
                    or link.get("config_sha256") != active_runtime_sha256
                ):
                    raise PricingRunStartContractError(
                        "IDENTITY_GRAPH_STALE: a frozen identity edge was not "
                        "produced by the active identity algorithm and config"
                    )
            else:
                raise PricingRunStartContractError(
                    "IDENTITY_GRAPH_UNKNOWN_EVIDENCE: a frozen identity edge "
                    "names an unsupported evidence kind"
                )
            our_oem = str(link.get("our_oem_norm") or "").strip()
            extracted_oem = str(link.get("extracted_oem_norm") or "").strip()
            if not catalog_identity_pair_has_safe_shape(our_oem, extracted_oem):
                raise PricingRunStartContractError(
                    "IDENTITY_GRAPH_CORRUPT: a frozen identity edge has an "
                    "empty, self-referential, or private-code pair"
                )
            recorded_item_id = str(link.get("catalog_item_id") or "")
            if recorded_item_id and recorded_item_id != str(candidate.catalog_item_id):
                raise PricingRunStartContractError(
                    "IDENTITY_GRAPH_ITEM_MISMATCH: a frozen edge belongs to a "
                    "different catalog item"
                )
            grouped.setdefault((our_oem, extracted_oem), []).append(
                (candidate.catalog_item_id, link)
            )

    for (our_oem, extracted_oem), entries in sorted(grouped.items()):
        catalog_item_id = min((item_id for item_id, _ in entries), key=str)
        ordered = sorted(
            (link for _, link in entries),
            key=lambda value: (
                str(value.get("catalog_item_id") or ""),
                str(value.get("extraction_method") or ""),
                str(value.get("catalog_identity_link_id") or ""),
            ),
        )
        evidence_hash = _sha256_payload(
            {
                "method_version": CATALOG_IDENTITY_RUN_SNAPSHOT_METHOD,
                "catalog_item_id": str(catalog_item_id),
                "our_oem_norm": our_oem,
                "extracted_oem_norm": extracted_oem,
                "source_evidence": ordered,
            }
        )
        source_methods = sorted(
            {
                str(value.get("extraction_method") or "")
                for value in ordered
                if str(value.get("extraction_method") or "").strip()
            }
        )
        source_ids = [
            str(value.get("catalog_identity_link_id") or "")
            for value in ordered
            if str(value.get("catalog_identity_link_id") or "").strip()
        ]
        fitment_cross_ids = [
            str(value.get("fitment_cross_reference_id") or "")
            for value in ordered
            if str(value.get("fitment_cross_reference_id") or "").strip()
        ]
        contains_fitment_cross = bool(fitment_cross_ids)
        confidence_values: list[Decimal] = []
        for value in ordered:
            raw_confidence = (value.get("validation_details") or {}).get("confidence")
            try:
                parsed_confidence = Decimal(str(raw_confidence))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise PricingRunStartContractError(
                    "IDENTITY_GRAPH_CONFIDENCE_INVALID: confirmed identity "
                    "evidence must carry explicit numeric confidence"
                ) from exc
            if not parsed_confidence.is_finite() or not Decimal(
                "0"
            ) < parsed_confidence <= Decimal("1"):
                raise PricingRunStartContractError(
                    "IDENTITY_GRAPH_CONFIDENCE_INVALID: confirmed identity "
                    "confidence must be in (0, 1]"
                )
            confidence_values.append(parsed_confidence)
        confidence = min(confidence_values)
        rows.append(
            CrossLink(
                workspace_id=run.workspace_id,
                pricing_run_id=run.id,
                catalog_item_id=catalog_item_id,
                our_oem_norm=our_oem,
                extracted_oem_norm=extracted_oem,
                source_listing_url=(
                    f"urn:marko:catalog-identity-snapshot:{run.id}:{catalog_item_id}"
                ),
                source_seller=(
                    "VERIFIED_IDENTITY_GRAPH"
                    if contains_fitment_cross
                    else "CUSTOMER_REFERENCE_GRAPH"
                ),
                raw_context="\n".join(
                    dict.fromkeys(
                        str(value.get("raw_context") or "")
                        for value in ordered
                        if str(value.get("raw_context") or "").strip()
                    )
                ),
                extraction_method=CATALOG_IDENTITY_RUN_SNAPSHOT_EXTRACTION,
                validation_status="CONFIRMED",
                rejection_reason=None,
                reciprocal_evidence_url=None,
                source_evidence=ordered,
                validation_details={
                    "confidence": str(confidence),
                    "evidence_kind": (
                        "FROZEN_VERIFIED_IDENTITY"
                        if contains_fitment_cross
                        else "FROZEN_CATALOG_IDENTITY"
                    ),
                    "catalog_identity_link_ids": source_ids,
                    "fitment_cross_reference_ids": fitment_cross_ids,
                    "source_methods": source_methods,
                    "source_evidence_sha256": evidence_hash,
                },
                method_version=CATALOG_IDENTITY_RUN_SNAPSHOT_METHOD,
                config_sha256=evidence_hash,
            )
        )
    return rows


def _override_values(
    override: CatalogItemOverride | None,
) -> dict[str, Any] | None:
    """Разрешённые значения правки — ровно то, что читает расчёт."""

    if override is None:
        return None
    values = {
        name: getattr(override, name) for name in CATALOG_OVERRIDE_SNAPSHOT_FIELDS
    }
    values["below_cost_floor"] = override.below_cost_floor
    return _json_safe(values)


async def _require_import_batch(
    session: AsyncSession, *, workspace_id: UUID, import_batch_id: UUID
) -> CatalogImportBatch:
    batch = await session.scalar(
        select(CatalogImportBatch).where(
            CatalogImportBatch.id == import_batch_id,
            CatalogImportBatch.workspace_id == workspace_id,
        )
    )
    if batch is None:
        raise PricingRunError("Catalog import not found")
    if batch.status not in {"completed", "partial"} or batch.imported_rows < 1:
        raise PricingRunError("Catalog import has no valid rows")
    return batch


async def resolve_pricing_run_scope(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    scope_mode: str,
    catalog_item_ids: Sequence[UUID] | None,
    policy: PricingPolicy,
) -> PricingRunScope:
    candidates = await load_scope_candidates(
        session, workspace_id=workspace_id, import_batch_id=import_batch_id
    )
    if not candidates:
        raise PricingRunError("SCOPE_EMPTY: catalog import has no rows")
    return build_pricing_run_scope(
        workspace_id=workspace_id,
        import_batch_id=import_batch_id,
        scope_mode=scope_mode,
        requested_item_ids=tuple(catalog_item_ids or ()),
        catalog_candidates=tuple(candidates),
        policy_version=policy.version,
        policy_hash=policy_fingerprint(policy),
        settings=get_settings(),
    )


async def preview_pricing_run(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    scope_mode: str = FULL_CATALOG_SCOPE,
    catalog_item_ids: Sequence[UUID] | None = None,
    policy_config: Mapping[str, Any] | None = None,
) -> PricingRunScope:
    """Показать оператору область прогона до его запуска. Без побочных эффектов."""

    await _require_import_batch(
        session, workspace_id=workspace_id, import_batch_id=import_batch_id
    )
    policy = policy_from_dict(policy_config)
    return await resolve_pricing_run_scope(
        session,
        workspace_id=workspace_id,
        import_batch_id=import_batch_id,
        scope_mode=scope_mode,
        catalog_item_ids=catalog_item_ids,
        policy=policy,
    )


async def preview_pricing_run_for_operator(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    actor: PreviewActor,
    scope_mode: str = FULL_CATALOG_SCOPE,
    catalog_item_ids: Sequence[UUID] | None = None,
    policy_config: Mapping[str, Any] | None = None,
    confirm_full_catalog: bool = False,
) -> tuple[PricingRunScope, IssuedPreviewContract]:
    """Показать область И выдать контракт, которым её потом можно запустить.

    Побочный эффект здесь ровно один и он необходим: без сохранённой строки
    контракта «предпросмотр» остаётся числом, которое клиент присылает сам
    себе, и старт нечем закрыть.
    """

    scope = await preview_pricing_run(
        session,
        workspace_id=workspace_id,
        import_batch_id=import_batch_id,
        scope_mode=scope_mode,
        catalog_item_ids=catalog_item_ids,
        policy_config=policy_config,
    )
    contract = await issue_preview_contract(
        session,
        scope=scope,
        actor=actor,
        policy_config=policy_config,
        confirm_full_catalog=confirm_full_catalog,
    )
    return scope, contract


@dataclass(frozen=True, slots=True)
class PreviewActor:
    """Кто именно смотрел предпросмотр — с ролью и правами на тот момент."""

    actor_id: str
    actor_type: str
    workspace_role: str
    permissions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, str) or not self.actor_id.strip():
            raise PricingRunStartContractError(
                "START_CONTRACT_REQUIRED: a preview contract must name its actor"
            )
        if not isinstance(self.workspace_role, str) or not self.workspace_role.strip():
            raise PricingRunStartContractError(
                "START_CONTRACT_REQUIRED: a preview contract must name the "
                "actor's workspace role"
            )

    @property
    def canonical_permissions(self) -> tuple[str, ...]:
        return tuple(sorted({str(value) for value in self.permissions}))

    def as_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "workspace_role": self.workspace_role,
            "permissions": list(self.canonical_permissions),
        }


@dataclass(frozen=True, slots=True)
class IssuedPreviewContract:
    """Выданный контракт. ``token`` возвращается один раз и не сохраняется."""

    token: str
    contract_id: UUID
    contract_version: str
    issued_at: datetime
    expires_at: datetime
    request_hash: str
    scope_hash: str
    catalog_snapshot_hash: str
    policy_snapshot_hash: str


def canonical_start_request_hash(
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    scope_mode: str,
    catalog_item_ids: Sequence[UUID] | None,
    policy_config: Mapping[str, Any] | None,
    confirm_full_catalog: bool,
) -> str:
    """Отпечаток самого запроса: что именно оператор просил исполнить.

    Порядок ``catalog_item_ids`` значим — он определяет порядок членства, а
    значит и результат.  Дубликаты снимаются ровно так же, как их снимает
    построение области, иначе тело старта и область считали бы по-разному.
    """

    requested = list(dict.fromkeys(catalog_item_ids or ()))
    return _sha256_payload(
        {
            "contract_version": PREVIEW_CONTRACT_VERSION,
            "workspace_id": str(workspace_id),
            "import_batch_id": str(import_batch_id),
            "scope_mode": scope_mode,
            "catalog_item_ids": [str(value) for value in requested],
            "policy_config": dict(policy_config or {}),
            "confirm_full_catalog": bool(confirm_full_catalog),
        }
    )


def _new_preview_token() -> tuple[str, str]:
    """Непрозрачный токен и его sha256. Сам токен в базу не попадает."""

    raw = secrets.token_urlsafe(32)
    token = f"mrp1_{raw}"
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_preview_contract(
    session: AsyncSession,
    *,
    scope: PricingRunScope,
    actor: PreviewActor,
    policy_config: Mapping[str, Any] | None,
    confirm_full_catalog: bool,
    now: datetime | None = None,
    ttl_seconds: int = PREVIEW_CONTRACT_TTL_SECONDS,
) -> IssuedPreviewContract:
    """Выдать контракт предпросмотра — единственное основание старта оператора."""

    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=max(1, int(ttl_seconds)))
    token, token_sha256 = _new_preview_token()
    request_hash = canonical_start_request_hash(
        workspace_id=scope.workspace_id,
        import_batch_id=scope.import_batch_id,
        scope_mode=scope.scope_mode,
        catalog_item_ids=_requested_item_ids(scope),
        policy_config=policy_config,
        confirm_full_catalog=confirm_full_catalog,
    )
    contract = PricingRunPreviewContract(
        contract_version=PREVIEW_CONTRACT_VERSION,
        token_sha256=token_sha256,
        workspace_id=scope.workspace_id,
        import_batch_id=scope.import_batch_id,
        actor_id=actor.actor_id,
        actor_type=actor.actor_type,
        workspace_role=actor.workspace_role,
        permissions=list(actor.canonical_permissions),
        scope_mode=scope.scope_mode,
        request_hash=request_hash,
        scope_hash=scope.scope_hash,
        catalog_snapshot_hash=scope.catalog_snapshot_hash,
        policy_version=scope.policy_version,
        policy_snapshot_hash=scope.policy_hash,
        requires_full_catalog_confirmation=scope.requires_full_catalog_confirmation,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    session.add(contract)
    await session.flush()
    return IssuedPreviewContract(
        token=token,
        contract_id=contract.id,
        contract_version=PREVIEW_CONTRACT_VERSION,
        issued_at=issued_at,
        expires_at=expires_at,
        request_hash=request_hash,
        scope_hash=scope.scope_hash,
        catalog_snapshot_hash=scope.catalog_snapshot_hash,
        policy_snapshot_hash=scope.policy_hash,
    )


def _requested_item_ids(scope: PricingRunScope) -> tuple[UUID, ...]:
    """Список позиций, названный оператором, — из исполняемого раздела манифеста."""

    if scope.scope_mode != EXPLICIT_ITEMS_SCOPE:
        return ()
    selection = scope.execution.get("selection")
    if not isinstance(selection, Mapping):
        return ()
    raw = selection.get("requested_catalog_item_ids")
    if not isinstance(raw, list):
        return ()
    return tuple(UUID(str(value)) for value in raw)


async def _claim_preview_contract(
    session: AsyncSession,
    *,
    token: str,
    workspace_id: UUID,
    idempotency_key: str,
    now: datetime,
) -> PricingRunPreviewContract:
    """Погасить контракт атомарно: один контракт — одна попытка старта.

    Гашение и проверка «не погашен ли уже» — один ``UPDATE ... RETURNING``, а
    не «прочитать, решить, записать»: последнее в гонке пропускает два старта
    по одному контракту.  Повтор той же попытки (тот же ключ идемпотентности)
    гасит контракт повторно и потому проходит.
    """

    token_sha256 = hashlib.sha256(token.encode("utf-8")).hexdigest()
    claimed = (
        await session.execute(
            update(PricingRunPreviewContract)
            .where(
                PricingRunPreviewContract.token_sha256 == token_sha256,
                PricingRunPreviewContract.workspace_id == workspace_id,
                PricingRunPreviewContract.expires_at > now,
                or_(
                    PricingRunPreviewContract.consumed_at.is_(None),
                    PricingRunPreviewContract.consumed_idempotency_key
                    == idempotency_key,
                ),
            )
            .values(consumed_at=now, consumed_idempotency_key=idempotency_key)
            .returning(PricingRunPreviewContract)
        )
    ).scalar_one_or_none()
    if claimed is not None:
        return claimed
    # Отказ обязан различать «нет такого контракта» и «есть, но не годится»:
    # иначе оператор не может понять, истёк ли предпросмотр или он смотрит не
    # в то рабочее пространство.
    existing = await session.scalar(
        select(PricingRunPreviewContract).where(
            PricingRunPreviewContract.token_sha256 == token_sha256
        )
    )
    if existing is None or existing.workspace_id != workspace_id:
        raise PricingRunStartContractError(
            "PREVIEW_CONTRACT_UNKNOWN: the start presents no preview contract "
            "this workspace ever issued"
        )
    if existing.expires_at <= now:
        raise PricingRunStartContractError(
            f"PREVIEW_CONTRACT_EXPIRED: contract {existing.id} expired at "
            f"{existing.expires_at.isoformat()}; take a new preview"
        )
    raise PricingRunIdempotencyConflictError(
        f"PREVIEW_CONTRACT_ALREADY_CONSUMED: contract {existing.id} already "
        f"started run {existing.consumed_run_id} under idempotency key "
        f"{existing.consumed_idempotency_key!r}, not {idempotency_key!r}"
    )


def _verify_preview_contract(
    contract: PricingRunPreviewContract,
    *,
    actor: PreviewActor,
    import_batch_id: UUID,
    request_hash: str,
    scope: PricingRunScope,
    confirm_full_catalog: bool,
) -> None:
    """Контракт обязан совпасть с телом старта И с текущими правами и областью.

    Каждое расхождение — отдельный отказ, а не общее «не сошлось»: оператор
    должен видеть, что именно сдвинулось между «посмотреть» и «запустить».
    """

    if contract.contract_version != PREVIEW_CONTRACT_VERSION:
        raise PricingRunStartContractError(
            f"PREVIEW_CONTRACT_UNSUPPORTED: contract {contract.id} speaks "
            f"{contract.contract_version!r}"
        )
    if contract.import_batch_id != import_batch_id:
        raise PricingRunStartContractError(
            f"PREVIEW_CONTRACT_SCOPE_MISMATCH: contract {contract.id} was issued "
            f"for import {contract.import_batch_id}, the start names "
            f"{import_batch_id}"
        )
    if contract.actor_id != actor.actor_id or contract.actor_type != actor.actor_type:
        raise PricingRunStartContractError(
            f"PREVIEW_CONTRACT_ACTOR_MISMATCH: contract {contract.id} was issued "
            f"to {contract.actor_type}:{contract.actor_id}, the start is made by "
            f"{actor.actor_type}:{actor.actor_id}"
        )
    if contract.workspace_role != actor.workspace_role:
        raise PricingRunStartContractError(
            f"PREVIEW_CONTRACT_ROLE_CHANGED: contract {contract.id} was issued to "
            f"role {contract.workspace_role!r}, the actor now holds "
            f"{actor.workspace_role!r}"
        )
    recorded = tuple(sorted(str(value) for value in (contract.permissions or ())))
    if recorded != actor.canonical_permissions:
        raise PricingRunStartContractError(
            f"PREVIEW_CONTRACT_PERMISSIONS_CHANGED: contract {contract.id} was "
            f"issued with {list(recorded)}, the actor now holds "
            f"{list(actor.canonical_permissions)}"
        )
    if PRICING_RUN_START_PERMISSION not in actor.canonical_permissions:
        raise PricingRunStartContractError(
            "PREVIEW_CONTRACT_PERMISSIONS_CHANGED: the actor no longer holds "
            f"{PRICING_RUN_START_PERMISSION}"
        )
    if contract.request_hash != request_hash:
        raise PricingRunStartContractError(
            f"PREVIEW_CONTRACT_REQUEST_MISMATCH: contract {contract.id} was issued "
            f"for request {contract.request_hash}, the start body hashes to "
            f"{request_hash}"
        )
    if contract.scope_mode != scope.scope_mode:
        raise PricingRunStartContractError(
            f"PREVIEW_CONTRACT_SCOPE_MISMATCH: contract {contract.id} was issued "
            f"for {contract.scope_mode}, the start asks for {scope.scope_mode}"
        )
    if bool(contract.requires_full_catalog_confirmation) and not confirm_full_catalog:
        raise PricingRunError(
            "FULL_CATALOG_CONFIRMATION_REQUIRED: the preview named the whole "
            "catalog and the start carries no confirmation"
        )
    if contract.policy_snapshot_hash != scope.policy_hash:
        raise PricingRunScopeConflictError(
            f"POLICY_CHANGED: preview saw policy {contract.policy_snapshot_hash}, "
            f"start-time policy is {scope.policy_hash}"
        )
    if contract.catalog_snapshot_hash != scope.catalog_snapshot_hash:
        raise PricingRunScopeConflictError(
            "CATALOG_SNAPSHOT_CHANGED: preview saw "
            f"{contract.catalog_snapshot_hash}, start-time catalog is "
            f"{scope.catalog_snapshot_hash}"
        )
    if contract.scope_hash != scope.scope_hash:
        raise PricingRunScopeConflictError(
            f"SCOPE_CHANGED: preview saw {contract.scope_hash}, start-time scope "
            f"is {scope.scope_hash}"
        )


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value.casefold()) <= set("0123456789abcdef")
    )


@dataclass(frozen=True, slots=True)
class OperatorRunStart:
    """Старт оператора: сервер обязан узнать выданный ИМ ЖЕ контракт предпросмотра.

    Раньше «контрактом» служили два хеша, которые сервер сам же и публиковал:
    их можно было переслать, воспроизвести или подобрать по чужому
    предпросмотру, и ни срока годности, ни актора у них не было.  Теперь
    предъявляется непрозрачный токен, выданный сервером один раз; всё
    остальное (область, каталог, политика, права) берётся из сохранённой
    строки контракта, а не со слов клиента.
    """

    idempotency_key: str
    preview_token: str
    actor: PreviewActor
    confirm_full_catalog: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.idempotency_key, str)
            or not self.idempotency_key.strip()
        ):
            raise PricingRunStartContractError(
                "START_CONTRACT_REQUIRED: a non-empty idempotency_key is mandatory "
                "for an operator start"
            )
        if (
            not isinstance(self.preview_token, str)
            or not self.preview_token.strip()
            or not self.preview_token.startswith("mrp1_")
        ):
            raise PricingRunStartContractError(
                "START_CONTRACT_REQUIRED: an operator start must present the "
                "opaque preview token issued by POST /runs/preview"
            )
        if not isinstance(self.actor, PreviewActor):
            raise PricingRunStartContractError(
                "START_CONTRACT_REQUIRED: an operator start must name its actor"
            )


@dataclass(frozen=True, slots=True)
class TrustedRunStart:
    """Доверенный внутренний путь: область унаследована, а не выбрана заново.

    Отдельный тип, а не «поля не передали»: и системный повтор, и e2e-подстановка
    обязаны назвать источник и основание, и оба попадают в манифест прогона.
    """

    confirmation_source: str
    reason: str
    source_run_id: UUID | None = None
    idempotency_key: str | None = None
    expected_scope_hash: str | None = None
    expected_catalog_snapshot_hash: str | None = None
    full_catalog_confirmed: bool = False

    def __post_init__(self) -> None:
        if self.confirmation_source not in TRUSTED_CONFIRMATION_SOURCES:
            raise PricingRunStartContractError(
                "START_CONTRACT_REQUIRED: unknown trusted confirmation source "
                f"{self.confirmation_source!r}"
            )
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise PricingRunStartContractError(
                "START_CONTRACT_REQUIRED: a trusted start must state its reason"
            )
        for name in ("expected_scope_hash", "expected_catalog_snapshot_hash"):
            value = getattr(self, name)
            if value is not None and not _is_sha256_hex(value):
                raise PricingRunStartContractError(
                    f"START_CONTRACT_REQUIRED: {name} must be a sha256 digest"
                )


PricingRunStart = OperatorRunStart | TrustedRunStart


def _resolve_confirmation(
    *,
    scope: PricingRunScope,
    start: PricingRunStart,
) -> tuple[str, bool]:
    """Развести подтверждение оператора и доверенный повтор, не смешивая их."""

    if isinstance(start, TrustedRunStart):
        return start.confirmation_source, bool(start.full_catalog_confirmed)
    if scope.requires_full_catalog_confirmation and not start.confirm_full_catalog:
        raise PricingRunError(
            "FULL_CATALOG_CONFIRMATION_REQUIRED: executing the whole catalog "
            f"({scope.estimate.eligible_items} item(s)) needs an explicit confirmation"
        )
    if start.confirm_full_catalog and not scope.requires_full_catalog_confirmation:
        raise PricingRunError(
            "FULL_CATALOG_CONFIRMATION_UNEXPECTED: confirm_full_catalog applies "
            f"only to {FULL_CATALOG_SCOPE} scope"
        )
    return CONFIRMATION_SOURCE_OPERATOR, bool(start.confirm_full_catalog)


def _start_provenance(
    start: PricingRunStart,
    *,
    preview_contract: PricingRunPreviewContract | None = None,
    identity: RunStartIdentity | None = None,
) -> dict[str, Any]:
    """Кто и на каком основании стартовал прогон — в сам манифест прогона.

    Раздел не участвует в хеше области: он описывает основание старта, а не то,
    что будет исполнено.  Личность старта дублируется здесь наравне с колонками
    прогона: колонки сравнивает код, манифест читает человек, разбирающий уже
    случившееся, и оба неизменяемы на уровне БД.
    """

    lane_section: dict[str, Any] = (
        {}
        if identity is None
        else {
            "start_lane": identity.lane,
            "start_actor_id": identity.actor_id,
            "start_actor_type": identity.actor_type,
            "canonical_start_request_hash": identity.canonical_start_request_hash,
        }
    )
    if isinstance(start, TrustedRunStart):
        return {
            **lane_section,
            "confirmation_source": start.confirmation_source,
            "reason": start.reason,
            "source_run_id": (
                str(start.source_run_id) if start.source_run_id is not None else None
            ),
            "preview_contract_verified": start.expected_scope_hash is not None,
        }
    if preview_contract is None:
        # Сюда можно попасть только если проверку контракта обошли: старт
        # оператора без погашенного контракта основанием не является.
        raise PricingRunStartContractError(
            "START_CONTRACT_REQUIRED: an operator start carries no consumed "
            "preview contract"
        )
    return {
        **lane_section,
        "confirmation_source": CONFIRMATION_SOURCE_OPERATOR,
        "reason": "operator start confirmed against a server-issued preview",
        "source_run_id": None,
        "preview_contract_verified": True,
        "preview_contract": {
            "id": str(preview_contract.id),
            "contract_version": preview_contract.contract_version,
            "issued_at": preview_contract.issued_at.isoformat(),
            "expires_at": preview_contract.expires_at.isoformat(),
            "request_hash": preview_contract.request_hash,
            "policy_snapshot_hash": preview_contract.policy_snapshot_hash,
            "actor_id": preview_contract.actor_id,
            "actor_type": preview_contract.actor_type,
            "workspace_role": preview_contract.workspace_role,
            "permissions": list(preview_contract.permissions or ()),
        },
    }


async def _find_run_by_idempotency_key(
    session: AsyncSession, *, workspace_id: UUID, idempotency_key: str
) -> PricingRun | None:
    return await session.scalar(
        select(PricingRun).where(
            PricingRun.workspace_id == workspace_id,
            PricingRun.idempotency_key == idempotency_key,
        )
    )


async def _find_active_run(
    session: AsyncSession, *, workspace_id: UUID, import_batch_id: UUID
) -> PricingRun | None:
    return await session.scalar(
        select(PricingRun)
        .where(
            PricingRun.workspace_id == workspace_id,
            PricingRun.import_batch_id == import_batch_id,
            PricingRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .order_by(PricingRun.created_at.desc())
        .limit(1)
    )


@dataclass(frozen=True, slots=True)
class RunStartIdentity:
    """Личность старта: КТО, по какой полосе власти и ЧТО именно просил исполнить.

    Ключ идемпотентности личностью не является — это лишь имя попытки, которое
    второй актор может назвать своим.  Прогон опознаётся как «тот же» только
    когда сошлось всё сразу: рабочее пространство, полоса, актор, отпечаток
    канонического тела старта и отпечатки области, манифеста и политики.
    Сравнивать один хеш области было недостаточно: два канонически разных
    запроса (например, ``policy: null`` и ``policy: {"version": "pricing-v2"}``)
    нормализуются в одну и ту же политику и одну и ту же область, но это два
    разных утверждения оператора, и повторять первое в ответ на второе нельзя.
    """

    workspace_id: UUID
    lane: str
    actor_id: str
    actor_type: str
    confirmation_source: str
    canonical_start_request_hash: str
    scope_hash: str
    policy_snapshot_hash: str
    catalog_snapshot_hash: str
    idempotency_key: str | None


# Поля, расхождение по которым означает ЧУЖОЙ старт.  Отказ по ним обязан быть
# непрозрачным: назвать идентификатор, область или актора чужого прогона значит
# превратить сам отказ в канал утечки.
_FOREIGN_AUTHORITY_FIELDS = frozenset(
    {"workspace_id", "lane", "actor_id", "actor_type"}
)


def run_start_identity(
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    scope_mode: str,
    catalog_item_ids: Sequence[UUID] | None,
    policy_config: Mapping[str, Any] | None,
    start: PricingRunStart,
    scope_hash: str,
    policy_snapshot_hash: str,
    catalog_snapshot_hash: str,
    confirmation_source: str,
) -> RunStartIdentity:
    """Собрать личность старта из тела запроса и предъявленного основания."""

    if isinstance(start, TrustedRunStart):
        lane = RUN_START_LANE_TRUSTED
        # У доверенной полосы нет человека-актора, но безымянной она быть не
        # может: носителем власти выступает сама служба, названная источником
        # подтверждения.  Иначе два разных внутренних основания под одним ключом
        # выглядели бы как один и тот же старт.
        actor_id = f"system:{start.confirmation_source}"
        actor_type = ACTOR_TYPE_SERVICE
        confirm_full_catalog = bool(start.full_catalog_confirmed)
    else:
        lane = RUN_START_LANE_OPERATOR
        actor_id = start.actor.actor_id
        actor_type = start.actor.actor_type
        confirm_full_catalog = bool(start.confirm_full_catalog)
    return RunStartIdentity(
        workspace_id=workspace_id,
        lane=lane,
        actor_id=actor_id,
        actor_type=actor_type,
        confirmation_source=confirmation_source,
        canonical_start_request_hash=canonical_start_request_hash(
            workspace_id=workspace_id,
            import_batch_id=import_batch_id,
            scope_mode=scope_mode,
            catalog_item_ids=catalog_item_ids,
            policy_config=policy_config,
            confirm_full_catalog=confirm_full_catalog,
        ),
        scope_hash=scope_hash,
        policy_snapshot_hash=policy_snapshot_hash,
        catalog_snapshot_hash=catalog_snapshot_hash,
        idempotency_key=start.idempotency_key or None,
    )


def _stored_manifest_hash(existing: PricingRun) -> str | None:
    """Хеш сохранённого манифеста — пересчитанный, а не переписанный из колонки.

    Колонка ``scope_hash`` и сам манифест неизменяемы в БД по отдельности;
    сравнивать нужно оба, иначе «совпал хеш» перестаёт означать «совпал
    документ», как только одна из двух защит снята.
    """

    manifest = getattr(existing, "scope_manifest", None)
    if not isinstance(manifest, Mapping) or not manifest:
        return None
    try:
        return scope_manifest_hash(manifest)
    except PricingRunError:
        return None


def _run_identity_mismatches(
    existing: PricingRun, identity: RunStartIdentity
) -> tuple[str, ...]:
    """Перечислить ВСЕ расхождения, а не остановиться на первом.

    Оператор должен видеть, что именно разошлось; безопасность при этом не
    страдает, потому что решение о том, насколько подробным будет сообщение,
    принимается отдельно — по тому, чужой это старт или свой.
    """

    seen: tuple[tuple[str, Any, Any], ...] = (
        ("workspace_id", existing.workspace_id, identity.workspace_id),
        ("lane", existing.start_lane, identity.lane),
        ("actor_id", existing.start_actor_id, identity.actor_id),
        ("actor_type", existing.start_actor_type, identity.actor_type),
        (
            "confirmation_source",
            (existing.scope_confirmation_source or None),
            identity.confirmation_source,
        ),
        (
            "canonical_start_request_hash",
            existing.canonical_start_request_hash,
            identity.canonical_start_request_hash,
        ),
        ("scope_hash", existing.scope_hash, identity.scope_hash),
        ("scope_manifest_hash", _stored_manifest_hash(existing), identity.scope_hash),
        (
            "policy_snapshot_hash",
            existing.policy_snapshot_hash,
            identity.policy_snapshot_hash,
        ),
        (
            "catalog_snapshot_hash",
            existing.catalog_snapshot_hash,
            identity.catalog_snapshot_hash,
        ),
        (
            "idempotency_key",
            (existing.idempotency_key or None),
            identity.idempotency_key,
        ),
    )
    return tuple(name for name, stored, wanted in seen if stored != wanted)


def _same_run_identity(existing: PricingRun, identity: RunStartIdentity) -> bool:
    """Тот же самый запрос или другой?

    Совпадение импорта — это не совпадение запроса, и совпадение области — тоже
    не совпадение запроса.  Прогон возвращается как «тот же» только когда сошлось
    ВСЁ: рабочее пространство, полоса власти, актор, отпечаток канонического тела
    старта, отпечатки области, манифеста, политики и каталога, источник
    подтверждения и ключ идемпотентности (в обе стороны, а не только когда новый
    запрос его назвал).
    """

    return not _run_identity_mismatches(existing, identity)


def _reused_active_run_or_conflict(
    existing: PricingRun, *, identity: RunStartIdentity
) -> PricingRun:
    """Переиспользовать активный прогон только при совпадении личности запроса."""

    mismatches = _run_identity_mismatches(existing, identity)
    if not mismatches:
        return existing
    if _FOREIGN_AUTHORITY_FIELDS & set(mismatches):
        raise PricingRunActiveScopeConflictError(
            "ACTIVE_RUN_SCOPE_CONFLICT: import batch "
            f"{existing.import_batch_id} is already running a pricing run "
            "started by another authority in this workspace; it cannot be "
            "adopted and is not disclosed here"
        )
    raise PricingRunActiveScopeConflictError(
        f"ACTIVE_RUN_SCOPE_CONFLICT: import batch {existing.import_batch_id} is "
        f"already running run {existing.id} with scope {existing.scope_hash} "
        f"(key {existing.idempotency_key!r}, source "
        f"{existing.scope_confirmation_source!r}); the request asks for scope "
        f"{identity.scope_hash} (key {identity.idempotency_key!r}, source "
        f"{identity.confirmation_source!r}); differs in " + ", ".join(mismatches)
    )


async def _resolve_create_conflict(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    identity: RunStartIdentity,
) -> PricingRun | None:
    """Кто выиграл гонку: владелец ключа идемпотентности или активный прогон."""

    idempotency_key = identity.idempotency_key
    if idempotency_key is not None:
        replayed = await _find_run_by_idempotency_key(
            session, workspace_id=workspace_id, idempotency_key=idempotency_key
        )
        if replayed is not None:
            return _replayed_run_or_conflict(replayed, identity=identity)
    active = await _find_active_run(
        session, workspace_id=workspace_id, import_batch_id=import_batch_id
    )
    if active is None:
        return None
    return _reused_active_run_or_conflict(active, identity=identity)


def _replayed_run_or_conflict(
    existing: PricingRun, *, identity: RunStartIdentity
) -> PricingRun:
    """Вернуть победителя по ключу идемпотентности ТОЛЬКО той же самой попытке.

    Прежняя проверка сравнивала лишь хеш области и источник подтверждения.
    Этого хватало ровно до двух случаев, и оба воспроизводимы:

    * два канонически разных тела старта, нормализующихся в одну область
      (``policy: null`` и ``policy: {"version": "pricing-v2"}``), считались одним
      запросом — второй молча получал прогон, запущенный по первому;
    * второй актор со своим законным контрактом предпросмотра называл чужой
      ключ идемпотентности и получал прогон первого — то есть межпользовательскую
      утечку, а не идемпотентность.

    Теперь сравнивается вся личность старта. Расхождение по носителю власти
    закрывается непрозрачным отказом: чужой прогон не называется ни
    идентификатором, ни областью.
    """

    mismatches = _run_identity_mismatches(existing, identity)
    if not mismatches:
        return existing
    if _FOREIGN_AUTHORITY_FIELDS & set(mismatches):
        raise PricingRunIdempotencyConflictError(
            "IDEMPOTENCY_KEY_REUSED: this idempotency key is already bound to a "
            "pricing run started by another authority in this workspace; choose "
            "a key of your own"
        )
    raise PricingRunIdempotencyConflictError(
        f"IDEMPOTENCY_KEY_REUSED: {identity.idempotency_key} already names run "
        f"{existing.id}; the new request differs in " + ", ".join(mismatches)
    )


async def load_run_item_start_override(
    session: AsyncSession, run_item: PricingRunItem
) -> CatalogItemOverride | None:
    """Правка каталога, действовавшая на момент старта прогона.

    Расчёт обязан читать её вместо ``get_latest_override``: правка, поданная
    оператором уже после старта, не должна попадать в идущий прогон.
    """

    if run_item.catalog_item_override_id is None:
        return None
    return await session.get(CatalogItemOverride, run_item.catalog_item_override_id)


async def load_run_item_start_cost_record(
    session: AsyncSession, run_item: PricingRunItem
) -> CatalogItemCostRecord | None:
    """Запись себестоимости, действовавшая на момент старта прогона."""

    if run_item.cost_record_id is None:
        return None
    return await session.get(CatalogItemCostRecord, run_item.cost_record_id)


def _catalog_item_snapshot(candidate: ScopeCandidate) -> dict[str, Any]:
    """Замороженный вид позиции: все входы исполнения, включая правку оператора.

    Хранить только ``override_id`` было недостаточно: расчёт всё равно шёл в
    строку правки за значениями, то есть за живыми данными.  Здесь лежит
    разрешённый оператор_ский контекст целиком — читать из него можно, не
    возвращаясь в каталог.
    """

    return {
        "catalog_item_id": str(candidate.catalog_item_id),
        "source_row": candidate.source_row,
        "sku": candidate.sku,
        "oe_norm": candidate.oe_norm,
        "oe_raw": candidate.oe_raw,
        "mpn_norm": candidate.mpn_norm,
        "mpn_raw": candidate.mpn_raw,
        "name": candidate.name,
        "brand": candidate.brand,
        "category": candidate.category,
        "current_price": str(candidate.current_price),
        "currency": candidate.currency,
        "stock_status": candidate.stock_status,
        "product_url": candidate.product_url,
        "is_available": candidate.is_available,
        "identity_status": candidate.identity_status,
        "identity_reason": candidate.identity_reason,
        "part_numbers_norm": list(candidate.part_numbers_norm),
        "description": candidate.description,
        "applicability_brands": list(candidate.applicability_brands),
        "applicability_models": list(candidate.applicability_models),
        "characteristics_raw": _json_safe(dict(candidate.characteristics_raw)),
        "confirmed_identity_links": [
            _json_safe(dict(link)) for link in candidate.confirmed_identity_links
        ],
        "customer_identity_available": customer_identity_available(candidate),
        "stock_qty": _decimal_or_none(candidate.stock_qty),
        "stock_age_days": _decimal_or_none(candidate.stock_age_days),
        "expected_units_sold": _decimal_or_none(candidate.expected_units_sold),
        "units_sold_30d": _decimal_or_none(candidate.units_sold_30d),
        "units_sold_60d": _decimal_or_none(candidate.units_sold_60d),
        "units_sold_90d": _decimal_or_none(candidate.units_sold_90d),
        "days_since_last_sale": _decimal_or_none(candidate.days_since_last_sale),
        "historical_monthly_units": _decimal_or_none(
            candidate.historical_monthly_units
        ),
        "views_30d": _decimal_or_none(candidate.views_30d),
        "conversion_rate_proxy": _decimal_or_none(candidate.conversion_rate_proxy),
        "manual_priority": _decimal_or_none(candidate.manual_priority),
        "catalog_item_override_id": (
            str(candidate.override_id) if candidate.override_id else None
        ),
        "override_values": (
            _json_safe(dict(candidate.override_values))
            if candidate.override_values is not None
            else None
        ),
        "cost_record_id": (
            str(candidate.cost_record_id) if candidate.cost_record_id else None
        ),
    }


def _decimal_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def start_snapshot_fingerprint(snapshot: Mapping[str, Any]) -> str:
    """SHA-256 по каноническим байтам замороженного снимка позиции."""

    payload = {
        key: value for key, value in snapshot.items() if key != "start_snapshot_hash"
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _start_snapshot(
    candidate: ScopeCandidate, *, frozen_at: datetime, membership_position: int
) -> dict[str, Any]:
    snapshot = {
        "contract_version": PRICING_RUN_SCOPE_CONTRACT_VERSION,
        "frozen_at": frozen_at.isoformat(),
        "membership_position": membership_position,
        **_catalog_item_snapshot(candidate),
        "cost_record_sequence_no": candidate.cost_record_sequence_no,
    }
    return snapshot


@dataclass(frozen=True, slots=True)
class FrozenCatalogItem:
    """Позиция каталога, какой её заморозил старт прогона.

    Подставляется вместо ORM-строки ``CatalogItem`` везде, где ограниченный
    прогон читает каталог: имена полей те же, поэтому сбор, отождествление и
    расчёт получают замороженный вид, не зная о подмене, а живые правки после
    старта в идущий прогон не попадают.
    """

    id: UUID
    source_row: int
    sku: str
    oe_norm: str
    mpn_norm: str
    name: str
    brand: str | None
    category: str
    current_price: Decimal
    currency: str
    stock_status: str
    product_url: str | None
    is_available: bool | None
    identity_status: str
    stock_qty: Decimal | None
    stock_age_days: Decimal | None
    expected_units_sold: Decimal | None
    units_sold_30d: Decimal | None
    units_sold_60d: Decimal | None
    units_sold_90d: Decimal | None
    days_since_last_sale: Decimal | None
    historical_monthly_units: Decimal | None
    views_30d: Decimal | None
    conversion_rate_proxy: Decimal | None
    manual_priority: Decimal | None
    override_values: Mapping[str, Any] | None
    catalog_item_override_id: UUID | None
    cost_record_id: UUID | None
    part_numbers_norm: tuple[str, ...] = ()
    identity_reason: str | None = None
    confirmed_identity_links: tuple[Mapping[str, Any], ...] = ()
    customer_identity_available: bool = False
    oe_raw: str = ""
    mpn_raw: str = ""
    description: str | None = None
    applicability_brands: tuple[str, ...] = ()
    applicability_models: tuple[str, ...] = ()
    characteristics_raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FrozenCatalogOverride:
    """Разрешённый операторский контекст из снимка, а не строка из каталога."""

    id: UUID | None
    stock_status: str | None = None
    stock_qty: Decimal | None = None
    stock_age_days: Decimal | None = None
    expected_units_sold: Decimal | None = None
    units_sold_30d: Decimal | None = None
    units_sold_60d: Decimal | None = None
    units_sold_90d: Decimal | None = None
    days_since_last_sale: Decimal | None = None
    historical_monthly_units: Decimal | None = None
    views_30d: Decimal | None = None
    conversion_rate_proxy: Decimal | None = None
    manual_priority: Decimal | None = None
    liquidity_target: Decimal | None = None
    urgency: Decimal | None = None
    allow_below_cost: bool = False
    below_cost_warning_confirmed: bool = False
    below_cost_floor: Decimal | None = None


class PricingRunSnapshotError(PricingRunError):
    """Замороженный снимок отсутствует, испорчен или не сходится с отпечатком."""


def _snapshot_decimal(snapshot: Mapping[str, Any], name: str) -> Decimal | None:
    raw = snapshot.get(name)
    if raw is None:
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PricingRunSnapshotError(
            f"START_SNAPSHOT_CORRUPT: {name} is not a number"
        ) from exc
    if not value.is_finite():
        raise PricingRunSnapshotError(f"START_SNAPSHOT_CORRUPT: {name} is not finite")
    return value


def _snapshot_required_decimal(snapshot: Mapping[str, Any], name: str) -> Decimal:
    value = _snapshot_decimal(snapshot, name)
    if value is None:
        raise PricingRunSnapshotError(f"START_SNAPSHOT_INCOMPLETE: {name} is missing")
    return value


def _snapshot_required_str(snapshot: Mapping[str, Any], name: str) -> str:
    raw = snapshot.get(name)
    if not isinstance(raw, str):
        raise PricingRunSnapshotError(f"START_SNAPSHOT_INCOMPLETE: {name} is missing")
    return raw


def frozen_override_from_snapshot(
    snapshot: Mapping[str, Any],
) -> FrozenCatalogOverride | None:
    """Собрать операторский контекст из снимка. ``None`` — правки не было."""

    raw = snapshot.get("override_values")
    override_id = snapshot.get("catalog_item_override_id")
    if raw is None:
        if override_id is not None:
            raise PricingRunSnapshotError(
                "START_SNAPSHOT_INCOMPLETE: the snapshot names an override but "
                "carries none of its values"
            )
        return None
    if not isinstance(raw, Mapping):
        raise PricingRunSnapshotError(
            "START_SNAPSHOT_CORRUPT: override values are not a mapping"
        )
    decimals = {
        name: _snapshot_decimal(raw, name)
        for name in (
            "stock_qty",
            "stock_age_days",
            "expected_units_sold",
            "units_sold_30d",
            "units_sold_60d",
            "units_sold_90d",
            "days_since_last_sale",
            "historical_monthly_units",
            "views_30d",
            "conversion_rate_proxy",
            "manual_priority",
            "liquidity_target",
            "urgency",
            "below_cost_floor",
        )
    }
    status = raw.get("stock_status")
    return FrozenCatalogOverride(
        id=UUID(str(override_id)) if override_id else None,
        stock_status=str(status) if status is not None else None,
        allow_below_cost=bool(raw.get("allow_below_cost", False)),
        below_cost_warning_confirmed=bool(
            raw.get("below_cost_warning_confirmed", False)
        ),
        **decimals,
    )


def frozen_catalog_item_from_snapshot(
    snapshot: Mapping[str, Any],
) -> FrozenCatalogItem:
    """Восстановить замороженную позицию из снимка, ничего не дочитывая."""

    override_id = snapshot.get("catalog_item_override_id")
    cost_record_id = snapshot.get("cost_record_id")
    raw_values = snapshot.get("override_values")
    raw_identity_links = snapshot.get("confirmed_identity_links") or ()
    if not isinstance(raw_identity_links, (list, tuple)) or any(
        not isinstance(value, Mapping) for value in raw_identity_links
    ):
        raise PricingRunSnapshotError(
            "START_SNAPSHOT_CORRUPT: confirmed identity links are not mappings"
        )
    return FrozenCatalogItem(
        id=UUID(_snapshot_required_str(snapshot, "catalog_item_id")),
        source_row=int(snapshot.get("source_row") or 0),
        sku=_snapshot_required_str(snapshot, "sku"),
        oe_norm=_snapshot_required_str(snapshot, "oe_norm"),
        oe_raw=str(snapshot.get("oe_raw") or ""),
        mpn_norm=str(snapshot.get("mpn_norm") or ""),
        mpn_raw=str(snapshot.get("mpn_raw") or ""),
        name=str(snapshot.get("name") or ""),
        brand=snapshot.get("brand"),
        category=_snapshot_required_str(snapshot, "category"),
        current_price=_snapshot_required_decimal(snapshot, "current_price"),
        currency=_snapshot_required_str(snapshot, "currency"),
        stock_status=_snapshot_required_str(snapshot, "stock_status"),
        product_url=snapshot.get("product_url"),
        is_available=snapshot.get("is_available"),
        identity_status=str(snapshot.get("identity_status") or "UNRESOLVED"),
        stock_qty=_snapshot_decimal(snapshot, "stock_qty"),
        stock_age_days=_snapshot_decimal(snapshot, "stock_age_days"),
        expected_units_sold=_snapshot_decimal(snapshot, "expected_units_sold"),
        units_sold_30d=_snapshot_decimal(snapshot, "units_sold_30d"),
        units_sold_60d=_snapshot_decimal(snapshot, "units_sold_60d"),
        units_sold_90d=_snapshot_decimal(snapshot, "units_sold_90d"),
        days_since_last_sale=_snapshot_decimal(snapshot, "days_since_last_sale"),
        historical_monthly_units=_snapshot_decimal(
            snapshot, "historical_monthly_units"
        ),
        views_30d=_snapshot_decimal(snapshot, "views_30d"),
        conversion_rate_proxy=_snapshot_decimal(snapshot, "conversion_rate_proxy"),
        manual_priority=_snapshot_decimal(snapshot, "manual_priority"),
        override_values=dict(raw_values) if isinstance(raw_values, Mapping) else None,
        catalog_item_override_id=UUID(str(override_id)) if override_id else None,
        cost_record_id=UUID(str(cost_record_id)) if cost_record_id else None,
        part_numbers_norm=tuple(
            str(value)
            for value in (snapshot.get("part_numbers_norm") or ())
            if str(value).strip()
        ),
        identity_reason=(
            str(snapshot.get("identity_reason"))
            if snapshot.get("identity_reason") is not None
            else None
        ),
        confirmed_identity_links=tuple(dict(value) for value in raw_identity_links),
        customer_identity_available=bool(
            snapshot.get("customer_identity_available", False)
        ),
        description=(
            str(snapshot.get("description"))
            if snapshot.get("description") is not None
            else None
        ),
        applicability_brands=tuple(
            str(value)
            for value in (snapshot.get("applicability_brands") or ())
            if str(value).strip()
        ),
        applicability_models=tuple(
            str(value)
            for value in (snapshot.get("applicability_models") or ())
            if str(value).strip()
        ),
        characteristics_raw=(
            dict(snapshot.get("characteristics_raw") or {})
            if isinstance(snapshot.get("characteristics_raw"), Mapping)
            else {}
        ),
    )


def verified_start_snapshot(run_item: PricingRunItem) -> Mapping[str, Any]:
    """Снимок позиции с пересчитанным отпечатком. Отказ вместо догадки."""

    snapshot = run_item.start_snapshot
    if not isinstance(snapshot, Mapping) or not snapshot:
        raise PricingRunSnapshotError(
            f"START_SNAPSHOT_MISSING: run item {run_item.id} carries no frozen "
            "execution inputs"
        )
    expected = run_item.start_snapshot_hash
    if not _is_sha256_hex(expected):
        raise PricingRunSnapshotError(
            f"START_SNAPSHOT_MISSING: run item {run_item.id} carries no snapshot "
            "hash, so its frozen inputs cannot be trusted"
        )
    actual = start_snapshot_fingerprint(snapshot)
    if actual != expected:
        raise PricingRunSnapshotError(
            f"START_SNAPSHOT_TAMPERED: run item {run_item.id} snapshot hashes to "
            f"{actual}, the row claims {expected}"
        )
    return snapshot


def frozen_execution_inputs(
    run_item: PricingRunItem,
) -> tuple[FrozenCatalogItem, FrozenCatalogOverride | None]:
    """Замороженные входы позиции: позиция каталога и операторский контекст."""

    snapshot = verified_start_snapshot(run_item)
    return (
        frozen_catalog_item_from_snapshot(snapshot),
        frozen_override_from_snapshot(snapshot),
    )


def run_is_bounded(run: PricingRun) -> bool:
    """Несёт ли прогон контракт замороженной области."""

    version = (getattr(run, "scope_contract_version", None) or "").strip()
    return bool(version) and version != LEGACY_UNBOUNDED_SCOPE_CONTRACT


def resolve_execution_catalog_item(
    run: PricingRun,
    run_item: PricingRunItem,
    live_item: CatalogItem,
) -> CatalogItem | FrozenCatalogItem:
    """Что именно исполнение читает как «позицию каталога».

    Для прогона с контрактом это ВСЕГДА замороженный снимок: сбор,
    отождествление, подбор коэффициентов и расчёт получают один и тот же вид,
    и правка каталога после старта в него не попадает.  Снимок без отпечатка
    или с разошедшимся отпечатком — отказ, а не молчаливый возврат к живым
    данным: иначе достаточно испортить снимок, чтобы прогон снова поехал по
    текущему каталогу.
    """

    if not run_is_bounded(run):
        return live_item
    return frozen_catalog_item_from_snapshot(verified_start_snapshot(run_item))


def resolve_execution_override(
    run: PricingRun, run_item: PricingRunItem
) -> FrozenCatalogOverride | None:
    """Операторский контекст ограниченного прогона — из снимка, а не из базы."""

    return frozen_override_from_snapshot(verified_start_snapshot(run_item))


async def create_pricing_run(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    celery_app: Celery,
    start: PricingRunStart,
    policy_config: Mapping[str, Any] | None = None,
    source_mode: Literal["live", "e2e_fixture_replay"] = "live",
    correlation_id: str | None = None,
    scope_mode: str = FULL_CATALOG_SCOPE,
    catalog_item_ids: Sequence[UUID] | None = None,
) -> PricingRun:
    """Создать прогон. ``start`` — обязательное основание старта, а не опция.

    Оператор обязан предъявить контракт предпросмотра (``OperatorRunStart``);
    доверенные внутренние пути предъявляют ``TrustedRunStart`` и называют себя.
    """

    settings = get_settings()
    if not isinstance(start, (OperatorRunStart, TrustedRunStart)):
        raise PricingRunStartContractError(
            "START_CONTRACT_REQUIRED: a pricing run needs a typed start contract"
        )
    idempotency_key = start.idempotency_key
    if isinstance(start, TrustedRunStart):
        expected_scope_hash = start.expected_scope_hash
        expected_catalog_snapshot_hash = start.expected_catalog_snapshot_hash
    else:
        # Оператор ничего не «ожидает»: сравнивать будет сохранённый контракт,
        # а не значения, присланные вместе с запросом.
        expected_scope_hash = None
        expected_catalog_snapshot_hash = None
    # Полоса e2e-подстановки и источник подтверждения обязаны совпадать: иначе
    # обычный старт мог бы проехать по полосе воспроизведения фикстур.
    if (source_mode == "e2e_fixture_replay") != (
        isinstance(start, TrustedRunStart)
        and start.confirmation_source == CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY
    ):
        raise PricingRunStartContractError(
            "START_CONTRACT_REQUIRED: the fixture replay lane and the "
            f"{CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY} confirmation source only "
            "exist together"
        )
    if source_mode == "live":
        require_live_prom_marketplace_collection(settings)
    elif not (
        source_mode == "e2e_fixture_replay"
        and settings.environment.strip().casefold() == "e2e"
        and settings.e2e_auth_bypass
    ):
        raise PricingRunError("Fixture replay is isolated to authenticated E2E mode")
    await _require_import_batch(
        session, workspace_id=workspace_id, import_batch_id=import_batch_id
    )
    policy = policy_from_dict(policy_config)
    require_activated_run_policy(
        policy,
        robust_v3_enabled=settings.pricing_v3_robust_dispersion_enabled,
        activation_artifact_verified=activation_artifact_verified(
            settings.pricing_v3_activation_artifact,
            settings.pricing_v3_activation_sha256,
        ),
    )
    scope = await resolve_pricing_run_scope(
        session,
        workspace_id=workspace_id,
        import_batch_id=import_batch_id,
        scope_mode=scope_mode,
        catalog_item_ids=catalog_item_ids,
        policy=policy,
    )
    # Сравнивается хеш ровно тех байт манифеста, которые и будут сохранены:
    # предпросмотр и старт обязаны говорить об одном и том же документе.
    persisted_scope_hash = scope_manifest_hash(scope.manifest)
    if persisted_scope_hash != scope.scope_hash:
        raise PricingRunError(
            "SCOPE_MANIFEST_MISMATCH: the manifest to be persisted hashes to "
            f"{persisted_scope_hash}, the scope claims {scope.scope_hash}"
        )
    # Отпечатки из предпросмотра — единственная защита от того, что каталог
    # или правки оператора сдвинулись между «посмотреть» и «запустить».
    if (
        expected_catalog_snapshot_hash is not None
        and expected_catalog_snapshot_hash != scope.catalog_snapshot_hash
    ):
        raise PricingRunScopeConflictError(
            "CATALOG_SNAPSHOT_CHANGED: preview saw "
            f"{expected_catalog_snapshot_hash}, start-time catalog is "
            f"{scope.catalog_snapshot_hash}"
        )
    if expected_scope_hash is not None and expected_scope_hash != persisted_scope_hash:
        raise PricingRunScopeConflictError(
            f"SCOPE_CHANGED: preview saw {expected_scope_hash}, start-time scope is "
            f"{persisted_scope_hash}"
        )
    confirmation_source, full_catalog_confirmed = _resolve_confirmation(
        scope=scope, start=start
    )
    # Личность старта считается ОДИН раз и ровно по тому телу запроса, которое
    # пришло: тот же отпечаток предъявляется контракту предпросмотра, тот же
    # сравнивается с уже существующим прогоном и тот же сохраняется в строке.
    identity = run_start_identity(
        workspace_id=workspace_id,
        import_batch_id=import_batch_id,
        scope_mode=scope_mode,
        catalog_item_ids=catalog_item_ids,
        policy_config=policy_config,
        start=start,
        scope_hash=persisted_scope_hash,
        policy_snapshot_hash=scope.policy_hash,
        catalog_snapshot_hash=scope.catalog_snapshot_hash,
        confirmation_source=confirmation_source,
    )
    # Старт оператора закрывается не «похожестью хешей», а погашением выданного
    # сервером контракта: без него, с истёкшим, чужим или не тем — отказ.
    preview_contract: PricingRunPreviewContract | None = None
    if isinstance(start, OperatorRunStart):
        now = datetime.now(UTC)
        preview_contract = await _claim_preview_contract(
            session,
            token=start.preview_token,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            now=now,
        )
        _verify_preview_contract(
            preview_contract,
            actor=start.actor,
            import_batch_id=import_batch_id,
            request_hash=identity.canonical_start_request_hash,
            scope=scope,
            confirm_full_catalog=start.confirm_full_catalog,
        )
        if preview_contract.scope_hash != persisted_scope_hash:
            raise PricingRunScopeConflictError(
                f"SCOPE_CHANGED: preview saw {preview_contract.scope_hash}, "
                f"start-time scope is {persisted_scope_hash}"
            )
        if preview_contract.consumed_run_id is not None:
            # Та же попытка уже создала прогон: возвращается он, а не второй.
            settled = await session.get(PricingRun, preview_contract.consumed_run_id)
            if settled is not None:
                return settled

    if idempotency_key is not None:
        replayed = await _find_run_by_idempotency_key(
            session, workspace_id=workspace_id, idempotency_key=idempotency_key
        )
        if replayed is not None:
            return _replayed_run_or_conflict(replayed, identity=identity)
    active = await _find_active_run(
        session, workspace_id=workspace_id, import_batch_id=import_batch_id
    )
    if active is not None:
        return _reused_active_run_or_conflict(active, identity=identity)

    catalog_items = list(scope.items)
    frozen_at = datetime.now(UTC)
    manifest = dict(scope.manifest)
    manifest[SCOPE_MANIFEST_PROVENANCE_SECTION] = _start_provenance(
        start, preview_contract=preview_contract, identity=identity
    )
    # Снимок политики и его отпечаток считаются по ТЕМ ЖЕ байтам, которыми
    # посчитан ``policy_hash`` области: один документ, а не два похожих.
    policy_snapshot = policy_to_dict(policy)
    policy_snapshot_hash = execution_policy_hash(policy_snapshot)
    if policy_snapshot_hash != scope.policy_hash:
        raise PricingRunError(
            "SCOPE_POLICY_MISMATCH: the policy to be persisted hashes to "
            f"{policy_snapshot_hash}, the scope claims {scope.policy_hash}"
        )
    run = PricingRun(
        workspace_id=workspace_id,
        import_batch_id=import_batch_id,
        status="queued",
        policy_version=policy.version,
        policy_config=policy_snapshot,
        policy_snapshot_hash=policy_snapshot_hash,
        parser_version=PARSER_ADAPTER_VERSION,
        classifier_version=TIER_METHOD_VERSION,
        coefficient_model=policy.coefficient_model.value,
        calibration_accounting=(
            {"correlation_id": correlation_id} if correlation_id else {}
        ),
        total_items=len(catalog_items),
        scope_contract_version=PRICING_RUN_SCOPE_CONTRACT_VERSION,
        scope_mode=scope.scope_mode,
        scope_confirmation_source=confirmation_source,
        full_catalog_confirmed=full_catalog_confirmed,
        catalog_snapshot_hash=scope.catalog_snapshot_hash,
        scope_hash=persisted_scope_hash,
        scope_manifest=manifest,
        idempotency_key=idempotency_key,
        scope_frozen_at=frozen_at,
        # Личность старта записывается ТЕМ ЖЕ INSERT, что и область: отдельного
        # окна, в котором прогон уже есть, а его происхождение ещё нет, не
        # существует.
        canonical_start_request_hash=identity.canonical_start_request_hash,
        start_lane=identity.lane,
        start_actor_id=identity.actor_id,
        start_actor_type=identity.actor_type,
    )
    # Вставка внутри savepoint: обе уникальные гарантии (активный прогон и ключ
    # идемпотентности) живут в БД, поэтому проигравший в гонке узнаёт об этом
    # здесь, а не после того, как уже создал второй прогон.
    try:
        async with session.begin_nested():
            session.add(run)
            await session.flush()
    except IntegrityError as exc:
        winner = await _resolve_create_conflict(
            session,
            workspace_id=workspace_id,
            import_batch_id=import_batch_id,
            identity=identity,
        )
        if winner is None:
            raise PricingRunError(f"PRICING_RUN_CONFLICT: {exc.orig}") from exc
        return winner
    frozen_cross_rows = _frozen_catalog_cross_rows(run=run, candidates=catalog_items)
    if frozen_cross_rows:
        session.add_all(frozen_cross_rows)
        await session.flush()
    if preview_contract is not None:
        # Контракт назвал прогон, который им открыт: повтор той же попытки
        # вернёт этот прогон, а не создаст второй.
        preview_contract.consumed_run_id = run.id

    submitted_at = frozen_at
    parser_contract = parser_contract_defaults()
    targets_by_hash: dict[str, ScrapeTarget] = {}
    target_hash_by_item: dict[UUID, str] = {}
    for catalog_item in catalog_items:
        raw_url = (catalog_item.product_url or "").strip() or None
        raw_query = customer_identity_query(catalog_item)
        search_context = customer_search_context(catalog_item)
        input_kind = InputKind.PRODUCT_SEED if raw_url else InputKind.QUERY
        request = ScrapeRequest(
            contract_version=SCRAPE_REQUEST_CONTRACT_VERSION,
            request_id=str(run.id),
            client_idempotency_token=f"pricing-run:{run.id}:{catalog_item.catalog_item_id}",
            workspace_id=str(workspace_id),
            source_type=SourceType.PROM_PUBLIC,
            acquisition_mode=AcquisitionMode.COMPARISON_JOB,
            submitted_by_actor_id="marko.pricing_runs",
            submitted_by_actor_type=ActorType.SERVICE,
            submitted_at=submitted_at,
            deadline_at=submitted_at
            + timedelta(
                seconds=max(
                    1,
                    settings.pricing_collection_item_deadline_seconds,
                )
            ),
            items=[
                ScrapeRequestItem(
                    item_id=str(catalog_item.catalog_item_id),
                    input_kind=input_kind,
                    # Missing identity is rejected below before admission.  A
                    # stable SKU keeps this audit request structurally valid;
                    # it is never dispatched or used as a market query.
                    input_value=raw_url or raw_query or catalog_item.sku,
                    priority=0,
                    client_item_reference=catalog_item.sku,
                    metadata=(
                        {"query": raw_query}
                        if raw_url
                        else {
                            "language": "ua",
                            "search_context": search_context,
                            "fallback_queries": list(
                                declared_widenings(catalog_item)
                            ),
                            "discovery_queries": list(
                                retrieval_only_queries(catalog_item)
                            ),
                        }
                    ),
                )
            ],
        )
        rejected_reason: str | None = None
        metadata_payload: dict[str, Any]
        admitted_input: ScrapeInput | QueryInput | None = None
        persisted_input_kind = input_kind.value
        try:
            if not customer_identity_available(catalog_item):
                raise ScraperBoundaryError(
                    code=ScraperErrorCode.CUSTOMER_IDENTITY_MISSING,
                    message=(
                        "Customer data contains no confirmed vehicle OE for this "
                        "catalog row"
                    ),
                    retryable=False,
                )
            if source_mode == "e2e_fixture_replay":
                admission = None
                admitted_input = (
                    ScrapeInput.build(
                        raw_url,
                        raw_query,
                        adapter_version=PARSER_ADAPTER_VERSION,
                    )
                    if raw_url
                    else QueryInput.build(
                        raw_query,
                        language="ua",
                        search_context=search_context,
                        adapter_version=PARSER_ADAPTER_VERSION,
                    )
                )
            else:
                admission, admitted_input = admit_prom_public_item(
                    request,
                    request.items[0],
                    settings=settings,
                    now=submitted_at,
                )
                if admitted_input is None:
                    raise ScraperBoundaryError(
                        code=ScraperErrorCode.SOURCE_ACCESS_BLOCKED,
                        message="Trusted admission rejected the public source",
                        retryable=False,
                    )
            if admitted_input is None:
                raise ScraperBoundaryError(
                    code=ScraperErrorCode.SERIALIZATION,
                    message="Admission returned no scraper input",
                    retryable=False,
                )
            scrape_input = admitted_input
        except (ScraperBoundaryError, ValueError) as exc:
            identity_missing = (
                isinstance(exc, ScraperBoundaryError)
                and exc.code == ScraperErrorCode.CUSTOMER_IDENTITY_MISSING
            )
            # A missing-identity row needs its own terminal audit target.  It
            # must never deduplicate onto a valid row merely because both rows
            # happen to carry the same product URL: that would materialize the
            # other row's market evidence into a product the customer did not
            # identify.
            hash_url = None if identity_missing else raw_url
            hash_query = (
                f"customer-identity-missing:{catalog_item.catalog_item_id}"
                if identity_missing
                else raw_query
            )
            if identity_missing:
                persisted_input_kind = InputKind.QUERY.value
            input_hash = fallback_input_hash(
                hash_url,
                hash_query,
                input_kind=persisted_input_kind,
                adapter_version=PARSER_ADAPTER_VERSION,
            )
            canonical_url = None
            product_key = None
            normalized_query = (
                "" if identity_missing else " ".join(raw_query.strip().upper().split())
            )
            metadata_payload = {
                "adapter_version": PARSER_ADAPTER_VERSION,
                "input_kind": persisted_input_kind,
                "product_url": raw_url,
                "query": normalized_query,
                "input_hash": input_hash,
                "customer_identity_available": not identity_missing,
            }
            policy_decision_id = f"rejected-{uuid4()}"
            source_policy_version = ADMISSION_POLICY_VERSION
            source_policy_state = (
                "NOT_PERMITTED"
                if isinstance(exc, ScraperBoundaryError)
                and exc.code == ScraperErrorCode.SOURCE_ACCESS_BLOCKED
                else "UNKNOWN"
            )
            submission_key = input_hash
            acquisition_key = input_hash
            rejected_reason = (
                exc.code.value
                if isinstance(exc, ScraperBoundaryError)
                else "invalid_input"
            )
        else:
            input_hash = scrape_input.input_hash
            canonical_url = getattr(scrape_input, "canonical_url", None)
            product_key = getattr(scrape_input, "product_key", None)
            normalized_query = scrape_input.query
            metadata_payload = scrape_input.as_dict()
            if admission is None:
                policy_decision_id = f"e2e-fixture-replay-{run.id}"
                source_policy_version = "e2e-fixture-replay-v1"
                source_policy_state = "NOT_PERMITTED"
                submission_key = input_hash
                acquisition_key = input_hash
            else:
                policy_decision_id = admission.policy_decision_id
                source_policy_version = admission.source_policy_version
                source_policy_state = admission.source_policy_state.value
                submission_key = admission.server_idempotency_keys.submission_key
                acquisition_key = admission.server_idempotency_keys.acquisition_key
        target = targets_by_hash.get(input_hash)
        if target is None:
            target = ScrapeTarget(
                pricing_run_id=run.id,
                source="prom",
                source_type=(
                    "persisted_replay"
                    if source_mode == "e2e_fixture_replay"
                    else "prom_public"
                ),
                source_lane=(
                    "REPLAY"
                    if source_mode == "e2e_fixture_replay"
                    else "PUBLIC_COMPETITOR"
                ),
                source_policy_decision_id=policy_decision_id,
                source_policy_version=source_policy_version,
                source_policy_state=source_policy_state,
                submission_key=submission_key,
                acquisition_key=acquisition_key,
                freshness_generation=0,
                original_url=raw_url,
                canonical_url=canonical_url,
                product_key=product_key,
                input_kind=persisted_input_kind,
                query=normalized_query,
                input_hash=input_hash,
                adapter_version=PARSER_ADAPTER_VERSION,
                status=("terminal_failure" if rejected_reason else "queued"),
                parser_name=parser_contract["parser_name"],
                parser_config_hash=parser_contract["parser_config_hash"],
                output_schema_version=parser_contract["output_schema_version"],
                execution_status=("TERMINAL_FAILED" if rejected_reason else "QUEUED"),
                acquisition_status=("BLOCKED" if rejected_reason else "NOT_STARTED"),
                parse_status="NOT_STARTED",
                evidence_status="NONE",
                downstream_eligibility=("INELIGIBLE" if rejected_reason else "UNKNOWN"),
                operator_action="NO_RECOMMENDATION",
                reason_codes=([rejected_reason] if rejected_reason else []),
                max_task_executions=max(
                    1,
                    settings.pricing_collection_max_task_executions,
                ),
                deadline_at=datetime.now(UTC)
                + timedelta(
                    seconds=max(
                        1,
                        settings.pricing_collection_item_deadline_seconds,
                    )
                ),
                metadata_size_bytes=len(
                    json.dumps(
                        metadata_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode()
                ),
                error_category=rejected_reason,
                error_detail=(
                    "Customer supplied no confirmed vehicle OE; matching was "
                    "skipped before network execution"
                    if rejected_reason
                    == ScraperErrorCode.CUSTOMER_IDENTITY_MISSING.value
                    else "Rejected by trusted admission before network execution"
                    if rejected_reason
                    else None
                ),
                finished_at=(submitted_at if rejected_reason else None),
            )
            targets_by_hash[input_hash] = target
        target_hash_by_item[catalog_item.catalog_item_id] = input_hash
    session.add_all(list(targets_by_hash.values()))
    await session.flush()

    run_items: list[PricingRunItem] = []
    for membership_position, catalog_item in enumerate(catalog_items):
        snapshot = _start_snapshot(
            catalog_item,
            frozen_at=frozen_at,
            membership_position=membership_position,
        )
        run_items.append(
            PricingRunItem(
                pricing_run_id=run.id,
                catalog_item_id=catalog_item.catalog_item_id,
                scrape_target_id=targets_by_hash[
                    target_hash_by_item[catalog_item.catalog_item_id]
                ].id,
                status="queued",
                idempotency_key=f"{run.id}:{catalog_item.catalog_item_id}",
                # Входы на момент старта: расчёт обязан читать именно их.
                catalog_item_override_id=catalog_item.override_id,
                cost_record_id=catalog_item.cost_record_id,
                start_snapshot=snapshot,
                start_snapshot_hash=start_snapshot_fingerprint(snapshot),
                membership_position=membership_position,
            )
        )
    session.add_all(run_items)
    dispatch = await enqueue_dispatch(
        session,
        event_key=f"pricing-run:{run.id}:start:v1",
        aggregate_type="pricing_run",
        aggregate_id=run.id,
        workspace_id=workspace_id,
        task_name="marko.worker.start_pricing_run",
        task_args=[str(run.id)],
        queue="celery",
    )
    await session.commit()
    await session.refresh(run)

    await publish_dispatch(
        session,
        event_id=dispatch.id,
        celery_app=celery_app,
    )
    pricing_event(
        "pricing_run_started",
        pricing_run_id=str(run.id),
        workspace_id=str(workspace_id),
        items=run.total_items,
        unique_inputs=len(targets_by_hash),
        unique_urls=len(
            {
                target.canonical_url
                for target in targets_by_hash.values()
                if target.canonical_url
            }
        ),
        duplicates=max(0, run.total_items - len(targets_by_hash)),
        policy_version=run.policy_version,
        correlation_id=correlation_id,
        scope_mode=run.scope_mode,
        scope_hash=run.scope_hash,
        catalog_snapshot_hash=run.catalog_snapshot_hash,
        scope_confirmation_source=run.scope_confirmation_source,
        estimated_unique_inputs=scope.estimate.unique_scrape_inputs,
    )
    target_counts = {
        kind: sum(1 for target in targets_by_hash.values() if target.input_kind == kind)
        for kind in (InputKind.QUERY.value, InputKind.PRODUCT_SEED.value)
    }
    pricing_event(
        "pricing_query_only_targets_total",
        pricing_run_id=str(run.id),
        value=target_counts[InputKind.QUERY.value],
    )
    pricing_event(
        "pricing_product_seed_targets_total",
        pricing_run_id=str(run.id),
        value=target_counts[InputKind.PRODUCT_SEED.value],
    )
    return run


@dataclass(frozen=True, slots=True)
class PricingRunReplayPlan:
    """Область исходного прогона, восстановленная для системного повтора."""

    source_run_id: UUID
    import_batch_id: UUID
    scope_mode: str
    catalog_item_ids: tuple[UUID, ...]
    policy_config: dict[str, Any]
    start: TrustedRunStart


def plan_pricing_run_replay(
    run: PricingRun, *, reason: str, idempotency_key: str
) -> PricingRunReplayPlan:
    """Восстановить область прогона для повтора — или отказаться повторять.

    Повтор наследует режим, упорядоченное членство, политику и отпечатки уже
    принятого прогона.  Область, которую невозможно восстановить дословно, не
    расширяется до полного каталога: одна упавшая позиция ограниченного прогона
    никогда не превращается в исполнение всего каталога.
    """

    manifest = run.scope_manifest or {}
    execution = manifest.get(SCOPE_MANIFEST_EXECUTION_SECTION)
    if (
        (run.scope_contract_version or "") != PRICING_RUN_SCOPE_CONTRACT_VERSION
        or not isinstance(execution, Mapping)
        or run.scope_hash is None
        or run.catalog_snapshot_hash is None
    ):
        raise PricingRunReplayError(
            f"REPLAY_SCOPE_UNRECOVERABLE: run {run.id} carries no "
            f"{PRICING_RUN_SCOPE_CONTRACT_VERSION} manifest; start a new bounded "
            "run through preview instead of replaying an unknown scope"
        )
    scope_mode = str(execution.get("scope_mode") or "")
    if scope_mode not in PRICING_RUN_SCOPE_MODES:
        raise PricingRunReplayError(
            f"REPLAY_SCOPE_UNRECOVERABLE: run {run.id} declares scope mode "
            f"{scope_mode!r}"
        )
    membership = execution.get("membership")
    if not isinstance(membership, Mapping):
        raise PricingRunReplayError(
            f"REPLAY_SCOPE_UNRECOVERABLE: run {run.id} declares no membership"
        )
    catalog_item_ids: tuple[UUID, ...] = ()
    if scope_mode == EXPLICIT_ITEMS_SCOPE:
        raw_ids = membership.get("catalog_item_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise PricingRunReplayError(
                f"REPLAY_SCOPE_UNRECOVERABLE: run {run.id} lists no bounded "
                "membership to replay"
            )
        try:
            catalog_item_ids = tuple(UUID(str(value)) for value in raw_ids)
        except (AttributeError, TypeError, ValueError) as exc:
            raise PricingRunReplayError(
                f"REPLAY_SCOPE_UNRECOVERABLE: run {run.id} lists an unreadable "
                "membership"
            ) from exc
        # Порядок членства — часть контракта: повтор обязан идти позиция в
        # позицию, а не «тем же множеством в другом порядке».
        if membership_digest(catalog_item_ids) != membership.get("digest"):
            raise PricingRunReplayError(
                f"REPLAY_SCOPE_UNRECOVERABLE: run {run.id} membership does not "
                "match its own digest"
            )
    return PricingRunReplayPlan(
        source_run_id=run.id,
        import_batch_id=run.import_batch_id,
        scope_mode=scope_mode,
        catalog_item_ids=catalog_item_ids,
        policy_config=dict(run.policy_config or {}),
        start=TrustedRunStart(
            confirmation_source=CONFIRMATION_SOURCE_SYSTEM_REPLAY,
            reason=reason,
            source_run_id=run.id,
            idempotency_key=idempotency_key,
            # Повтор обязан воспроизвести ту же область и тот же каталог: если
            # они сдвинулись, честнее отказать, чем исполнить другой прогон под
            # видом повтора.
            expected_scope_hash=run.scope_hash,
            expected_catalog_snapshot_hash=run.catalog_snapshot_hash,
            full_catalog_confirmed=bool(run.full_catalog_confirmed),
        ),
    )


async def get_pricing_run(
    session: AsyncSession, *, workspace_id: UUID, run_id: UUID
) -> PricingRun:
    run = await session.scalar(
        select(PricingRun).where(
            PricingRun.id == run_id,
            PricingRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise PricingRunNotFoundError(str(run_id))
    return run


async def list_pricing_runs(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    limit: int,
    offset: int,
) -> tuple[list[PricingRun], int]:
    where = PricingRun.workspace_id == workspace_id
    total = int(
        await session.scalar(select(func.count(PricingRun.id)).where(where)) or 0
    )
    runs = list(
        (
            await session.scalars(
                select(PricingRun)
                .where(where)
                .order_by(PricingRun.created_at.desc(), PricingRun.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return runs, total


async def cancel_pricing_run(
    session: AsyncSession, *, workspace_id: UUID, run_id: UUID
) -> PricingRun:
    run = await get_pricing_run(session, workspace_id=workspace_id, run_id=run_id)
    if run.status in {"completed", "partial", "failed", "cancelled"}:
        return run
    run.cancel_requested = True
    await session.commit()
    return run


async def get_latest_override(
    session: AsyncSession, catalog_item_id: UUID
) -> CatalogItemOverride | None:
    return await session.scalar(
        select(CatalogItemOverride)
        .where(CatalogItemOverride.catalog_item_id == catalog_item_id)
        .order_by(CatalogItemOverride.created_at.desc(), CatalogItemOverride.id.desc())
        .limit(1)
    )


def _merge_catalog_override_snapshot(
    values: Mapping[str, Any], previous: CatalogItemOverride | None
) -> dict[str, Any]:
    snapshot = {
        field: (
            values[field]
            if field in values
            else getattr(
                previous,
                field,
                False
                if field in {"allow_below_cost", "below_cost_warning_confirmed"}
                else None,
            )
        )
        for field in CATALOG_OVERRIDE_SNAPSHOT_FIELDS
    }
    if not snapshot["allow_below_cost"]:
        snapshot["below_cost_warning_confirmed"] = False
    return snapshot


async def add_catalog_item_override(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    catalog_item_id: UUID,
    values: Mapping[str, Any],
    settings: Settings | None = None,
) -> CatalogItemOverride:
    item = await session.scalar(
        select(CatalogItem).where(
            CatalogItem.id == catalog_item_id,
            CatalogItem.workspace_id == workspace_id,
        )
    )
    if item is None:
        raise CatalogItemNotFoundError(str(catalog_item_id))
    allowed = {
        "stock_status",
        "cost",
        "clear_cost",
        "stock_qty",
        "stock_age_days",
        "expected_units_sold",
        "units_sold_30d",
        "units_sold_60d",
        "units_sold_90d",
        "days_since_last_sale",
        "historical_monthly_units",
        "views_30d",
        "conversion_rate_proxy",
        "manual_priority",
        "liquidity_target",
        "urgency",
        "allow_below_cost",
        "below_cost_warning_confirmed",
        "reason",
    }
    if set(values) - allowed:
        raise PricingRunError("Unknown catalog override fields")
    if values.get("cost") is not None and values.get("clear_cost") is True:
        raise PricingRunError("cost and clear_cost cannot be submitted together")
    reason = str(values.get("reason", "")).strip()
    if not reason:
        raise PricingRunError("Override reason is required")
    previous = await get_latest_override(session, catalog_item_id)
    snapshot = _merge_catalog_override_snapshot(values, previous)
    allow_below_cost = bool(snapshot["allow_below_cost"])
    if allow_below_cost and not snapshot["below_cost_warning_confirmed"]:
        raise PricingRunError("below-cost warning confirmation is required")
    selected = settings or get_settings()
    try:
        if values.get("cost") is not None:
            add_encrypted_cost_record(
                session,
                workspace_id=workspace_id,
                catalog_item_id=catalog_item_id,
                user_id=user_id,
                cost=values["cost"],
                reason=reason,
                settings=selected,
            )
        elif values.get("clear_cost") is True:
            add_cost_clear_record(
                session,
                workspace_id=workspace_id,
                catalog_item_id=catalog_item_id,
                user_id=user_id,
                reason=reason,
                settings=selected,
            )
    except (CostCiphertextError, CostPrivacyBlocked) as exc:
        raise PricingRunError(str(exc)) from exc
    override = CatalogItemOverride(
        catalog_item_id=catalog_item_id,
        user_id=user_id,
        **snapshot,
        reason=reason,
    )
    session.add(override)
    await session.commit()
    await session.refresh(override)
    return override


def build_pricing_context(
    item: CatalogItem | FrozenCatalogItem,
    override: CatalogItemOverride | FrozenCatalogOverride | None,
) -> ProductPricingContext:
    """Контекст расчёта. Для ограниченного прогона сюда приходит ЗАМОРОЖЕННЫЙ вид.

    Функция намеренно не ходит в базу: её вход — либо живая строка каталога
    (унаследованные прогоны), либо ``FrozenCatalogItem`` из проверенного
    снимка.  Так один и тот же расчёт нельзя случайно накормить живыми данными
    в обход заморозки — решение принимается у вызывающего, а не здесь.
    """

    def latest(name: str, fallback: Any) -> Any:
        if override is None:
            return fallback
        value = getattr(override, name)
        return fallback if value is None else value

    status_raw = latest("stock_status", item.stock_status)
    try:
        stock_status = StockStatus(status_raw)
    except ValueError:
        stock_status = StockStatus.UNKNOWN
    return ProductPricingContext(
        sku=item.sku,
        category=item.category,
        current_price=item.current_price,
        currency=item.currency,
        stock_status=stock_status,
        # Legacy plaintext values may still exist, but are outside the active
        # V1 data flow until the cost privacy ADR is approved.
        cost=None,
        stock_qty=latest("stock_qty", item.stock_qty),
        stock_age_days=latest("stock_age_days", item.stock_age_days),
        expected_units_sold=latest("expected_units_sold", item.expected_units_sold),
        units_sold_30d=latest("units_sold_30d", item.units_sold_30d),
        units_sold_60d=latest("units_sold_60d", item.units_sold_60d),
        units_sold_90d=latest("units_sold_90d", item.units_sold_90d),
        days_since_last_sale=latest("days_since_last_sale", item.days_since_last_sale),
        historical_monthly_units=latest(
            "historical_monthly_units", item.historical_monthly_units
        ),
        views_30d=latest("views_30d", item.views_30d),
        conversion_rate_proxy=latest(
            "conversion_rate_proxy", item.conversion_rate_proxy
        ),
        liquidity_target=latest("liquidity_target", Decimal("0")),
        urgency=latest("urgency", Decimal("0")),
        manual_priority=latest("manual_priority", item.manual_priority),
        allow_below_cost=override.allow_below_cost if override else False,
        below_cost_warning_confirmed=(
            override.below_cost_warning_confirmed if override else False
        ),
    )


def _coefficient_to_domain(record: TierCoefficientRecord) -> TierCoefficient:
    return TierCoefficient(
        category=record.category,
        tier=ProductTier(record.tier),
        multiplier=record.multiplier,
        model=CoefficientModel(record.model),
        method_version=record.method_version,
        coefficient_version=record.coefficient_version,
        sample_size=record.sample_size,
        effective_sample_size=record.effective_sample_size,
        confidence=record.confidence,
        validated=record.validated,
        log_effect=record.log_effect,
        global_log_effect=record.global_log_effect,
        shrinkage_weight=record.shrinkage_weight,
        interval_low=record.interval_low,
        interval_high=record.interval_high,
        dataset_hash=record.dataset_hash,
        validation_reasons=tuple(record.validation_reasons),
    )


async def load_tier_coefficients(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    category: str,
    pricing_run_id: UUID | None = None,
) -> dict[tuple[str, ProductTier], TierCoefficient]:
    conditions = [
        TierCoefficientRecord.workspace_id == workspace_id,
        TierCoefficientRecord.category == category,
    ]
    if pricing_run_id is None:
        conditions.extend(
            [
                TierCoefficientRecord.pricing_run_id.is_(None),
                TierCoefficientRecord.validated.is_(True),
            ]
        )
    else:
        conditions.extend(
            [
                TierCoefficientRecord.pricing_run_id == pricing_run_id,
                TierCoefficientRecord.is_selected.is_(True),
            ]
        )
    records = list(
        (
            await session.scalars(
                select(TierCoefficientRecord)
                .where(*conditions)
                .order_by(TierCoefficientRecord.computed_at.desc())
            )
        ).all()
    )
    result: dict[tuple[str, ProductTier], TierCoefficient] = {}
    for record in records:
        coefficient = _coefficient_to_domain(record)
        key = (record.category, coefficient.tier)
        if key in result:
            continue
        result[key] = coefficient
    return result


async def persist_run_calibration_pairs(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pricing_run_id: UUID,
    pairs: list[CalibrationPair],
) -> tuple[list[TierCalibrationPairRecord], str]:
    dataset_hash = calibration_dataset_hash(pairs)
    existing = list(
        (
            await session.scalars(
                select(TierCalibrationPairRecord).where(
                    TierCalibrationPairRecord.pricing_run_id == pricing_run_id
                )
            )
        ).all()
    )
    if existing:
        hashes = {record.dataset_hash for record in existing}
        if hashes != {dataset_hash}:
            raise PricingRunError("Run calibration dataset changed after freezing")
        return existing, dataset_hash
    records = [
        TierCalibrationPairRecord(
            workspace_id=workspace_id,
            pricing_run_id=pricing_run_id,
            oe_norm=pair.oe_norm.strip().upper(),
            category=pair.category.strip(),
            tier=pair.tier.value,
            tier_price=pair.tier_price,
            reference_price=pair.reference_price,
            quality_weight=pair.quality_weight,
            tier_observation_ids=list(pair.tier_observation_ids),
            reference_observation_ids=list(pair.reference_observation_ids),
            identity_evidence=[dict(item) for item in pair.identity_evidence],
            dataset_hash=dataset_hash,
        )
        for pair in pairs
    ]
    session.add_all(records)
    await session.flush()
    return records, dataset_hash


async def load_run_calibration_pairs(
    session: AsyncSession, *, pricing_run_id: UUID
) -> list[CalibrationPair]:
    records = list(
        (
            await session.scalars(
                select(TierCalibrationPairRecord)
                .where(TierCalibrationPairRecord.pricing_run_id == pricing_run_id)
                .order_by(
                    TierCalibrationPairRecord.category,
                    TierCalibrationPairRecord.tier,
                    TierCalibrationPairRecord.oe_norm,
                )
            )
        ).all()
    )
    return [
        CalibrationPair(
            oe_norm=record.oe_norm,
            category=record.category,
            tier=ProductTier(record.tier),
            tier_price=record.tier_price,
            reference_price=record.reference_price,
            quality_weight=record.quality_weight,
            tier_observation_ids=tuple(record.tier_observation_ids),
            reference_observation_ids=tuple(record.reference_observation_ids),
            identity_evidence=tuple(dict(item) for item in record.identity_evidence),
        )
        for record in records
    ]


async def calibrate_tier_coefficients(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pairs: list[CalibrationPair],
    model: CoefficientModel,
    shrinkage_k: Decimal = Decimal("10"),
    min_category_pairs: int = 8,
    min_global_pairs: int = 20,
    min_effective_pairs: Decimal | None = None,
    max_interval_ratio: Decimal = Decimal("3"),
    pricing_run_id: UUID | None = None,
    policy_version: str = "pricing-v2",
    selected: bool = False,
) -> list[TierCoefficientRecord]:
    dataset_hash = calibration_dataset_hash(pairs)
    scope = f":run-{pricing_run_id}" if pricing_run_id else ""
    method_version = f"tier-{model.value}-v2{scope}"
    if model == CoefficientModel.SIMPLE_MEDIAN:
        coefficients = fit_simple_coefficients(
            pairs,
            min_pairs=min_category_pairs,
            min_effective_pairs=min_effective_pairs,
            max_interval_ratio=max_interval_ratio,
            method_version=method_version,
        )
    else:
        coefficients = fit_shrinkage_coefficients(
            pairs,
            shrinkage_k=shrinkage_k,
            min_category_pairs=min_category_pairs,
            min_global_pairs=min_global_pairs,
            min_effective_pairs=min_effective_pairs,
            max_interval_ratio=max_interval_ratio,
            method_version=method_version,
        )
    coefficient_versions = {
        coefficient.coefficient_version for coefficient in coefficients.values()
    }
    existing = list(
        (
            await session.scalars(
                select(TierCoefficientRecord).where(
                    TierCoefficientRecord.workspace_id == workspace_id,
                    TierCoefficientRecord.pricing_run_id == pricing_run_id,
                    TierCoefficientRecord.method_version == method_version,
                    TierCoefficientRecord.coefficient_version.in_(coefficient_versions),
                )
            )
        ).all()
    )
    if existing:
        return existing
    records = [
        TierCoefficientRecord(
            workspace_id=workspace_id,
            pricing_run_id=pricing_run_id,
            category=coefficient.category,
            tier=coefficient.tier.value,
            model=coefficient.model.value,
            multiplier=coefficient.multiplier,
            log_effect=coefficient.log_effect,
            global_log_effect=coefficient.global_log_effect,
            shrinkage_weight=coefficient.shrinkage_weight,
            sample_size=coefficient.sample_size,
            effective_sample_size=coefficient.effective_sample_size,
            confidence=coefficient.confidence,
            interval_low=coefficient.interval_low,
            interval_high=coefficient.interval_high,
            validated=coefficient.validated,
            dataset_hash=dataset_hash,
            method_version=coefficient.method_version,
            coefficient_version=coefficient.coefficient_version,
            policy_version=policy_version,
            validation_reasons=list(coefficient.validation_reasons),
            is_selected=selected,
        )
        for coefficient in coefficients.values()
    ]
    session.add_all(records)
    await session.commit()
    return records


async def load_target_tier_coefficients(
    session: AsyncSession,
    *,
    run: PricingRun,
    category: str,
    oe_norm: str,
    policy: PricingPolicy,
    comparison_identity_keys: Iterable[str] = (),
) -> dict[tuple[str, ProductTier], TierCoefficient]:
    frozen = await load_tier_coefficients(
        session,
        workspace_id=run.workspace_id,
        category=category,
        pricing_run_id=run.id,
    )
    if not policy.require_target_leakage_protection:
        return frozen
    pairs = await load_run_calibration_pairs(session, pricing_run_id=run.id)
    excluded_identities = {
        value.strip().upper()
        for value in (oe_norm, *comparison_identity_keys)
        if value and value.strip()
    }
    if not any(pair.oe_norm.strip().upper() in excluded_identities for pair in pairs):
        return frozen
    leakage_safe_pairs = [
        pair
        for pair in pairs
        if pair.oe_norm.strip().upper() not in excluded_identities
    ]
    method_version = f"tier-{policy.coefficient_model.value}-v2:loo-run-{run.id}"
    if policy.coefficient_model == CoefficientModel.SIMPLE_MEDIAN:
        fitted = fit_simple_coefficients(
            leakage_safe_pairs,
            min_pairs=policy.min_category_pairs,
            min_effective_pairs=policy.min_effective_pairs,
            max_interval_ratio=policy.max_allowed_interval_width,
            method_version=method_version,
        )
    else:
        fitted = fit_shrinkage_coefficients(
            leakage_safe_pairs,
            shrinkage_k=policy.shrinkage_k,
            min_category_pairs=policy.min_category_pairs,
            min_global_pairs=policy.min_global_pairs,
            min_effective_pairs=policy.min_effective_pairs,
            max_interval_ratio=policy.max_allowed_interval_width,
            method_version=method_version,
        )
    return {key: value for key, value in fitted.items() if key[0] == category}


async def list_tier_coefficients(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pricing_run_id: UUID | None,
    category: str | None,
    model: CoefficientModel | None,
    validated: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[TierCoefficientRecord], int]:
    conditions = [TierCoefficientRecord.workspace_id == workspace_id]
    if pricing_run_id is not None:
        conditions.append(TierCoefficientRecord.pricing_run_id == pricing_run_id)
    if category:
        conditions.append(TierCoefficientRecord.category == category)
    if model is not None:
        conditions.append(TierCoefficientRecord.model == model.value)
    if validated is not None:
        conditions.append(TierCoefficientRecord.validated.is_(validated))
    total = int(
        await session.scalar(
            select(func.count(TierCoefficientRecord.id)).where(*conditions)
        )
        or 0
    )
    records = list(
        (
            await session.scalars(
                select(TierCoefficientRecord)
                .where(*conditions)
                .order_by(
                    TierCoefficientRecord.computed_at.desc(),
                    TierCoefficientRecord.category,
                    TierCoefficientRecord.tier,
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return records, total


async def list_recommendations(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    run_id: UUID | None,
    action: str | None,
    confidence_grade: str | None,
    category: str | None,
    queue: str,
    priority_score_type: str | None,
    confidence_min: Decimal | None,
    confidence_max: Decimal | None,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[
    list[tuple[PricingRecommendation, CatalogItem]],
    int,
    UUID | None,
    dict[str, int],
]:
    if run_id is None:
        run_id = await session.scalar(
            select(PricingRun.id)
            .where(PricingRun.workspace_id == workspace_id)
            .order_by(PricingRun.created_at.desc())
            .limit(1)
        )
        if run_id is None:
            return (
                [],
                0,
                None,
                {"raise": 0, "lower": 0, "review": 0, "hold": 0, "total": 0},
            )
    else:
        await get_pricing_run(session, workspace_id=workspace_id, run_id=run_id)
    # The counts feeding the summary tiles describe the whole run, not the tab the
    # operator is standing on. Narrowing them by `queue`/`action` made every tile
    # read 0 while finished recommendations sat one tab away, which reads as "the
    # system found nothing" instead of "look under another tab".
    # Price-bearing recommendation rows are admissible only for a catalog item
    # whose original vehicle/OE identity was explicitly confirmed.  MPN_ONLY
    # rows remain useful in the review queue, but an old RAISE/HOLD/LOWER row
    # must not leak through a later API/export query as if its supplier number
    # were the original part identity.
    identity_scope_condition = or_(
        CatalogItem.identity_status == "OE_CONFIRMED",
        PricingRecommendation.action.in_(
            ("MANUAL_REVIEW", "INSUFFICIENT_DATA")
        ),
    )
    scope_conditions = [
        PricingRecommendation.pricing_run_id == run_id,
        identity_scope_condition,
    ]
    if confidence_grade:
        scope_conditions.append(
            PricingRecommendation.confidence_grade == confidence_grade
        )
    if category:
        scope_conditions.append(CatalogItem.category == category)
    if priority_score_type:
        scope_conditions.append(
            PricingRecommendation.priority_score_type == priority_score_type
        )
    if confidence_min is not None:
        scope_conditions.append(PricingRecommendation.confidence >= confidence_min)
    if confidence_max is not None:
        scope_conditions.append(PricingRecommendation.confidence <= confidence_max)
    conditions = list(scope_conditions)
    narrowed = bool(action) or queue != "all"
    if action:
        conditions.append(PricingRecommendation.action == action)
    if queue == "raise":
        conditions.append(PricingRecommendation.action == "RAISE")
    elif queue == "clearance":
        conditions.extend(
            [
                PricingRecommendation.priority_score_type == "clearance_priority",
                PricingRecommendation.action.in_(("LOWER", "HOLD")),
            ]
        )
    elif queue == "review":
        conditions.append(
            PricingRecommendation.action.in_(("MANUAL_REVIEW", "INSUFFICIENT_DATA"))
        )
    elif queue == "hold":
        conditions.append(PricingRecommendation.action == "HOLD")
    aggregate_statement = (
        select(
            func.count(PricingRecommendation.id).label("total"),
            func.count(PricingRecommendation.id)
            .filter(PricingRecommendation.action == "RAISE")
            .label("raise_count"),
            func.count(PricingRecommendation.id)
            .filter(PricingRecommendation.action == "LOWER")
            .label("lower_count"),
            func.count(PricingRecommendation.id)
            .filter(
                PricingRecommendation.action.in_(("MANUAL_REVIEW", "INSUFFICIENT_DATA"))
            )
            .label("review_count"),
            func.count(PricingRecommendation.id)
            .filter(PricingRecommendation.action == "HOLD")
            .label("hold_count"),
        )
        .join(CatalogItem, CatalogItem.id == PricingRecommendation.catalog_item_id)
        .where(*scope_conditions)
    )
    aggregates = (await session.execute(aggregate_statement)).one()
    action_counts = {
        "raise": int(aggregates.raise_count or 0),
        "lower": int(aggregates.lower_count or 0),
        "review": int(aggregates.review_count or 0),
        "hold": int(aggregates.hold_count or 0),
        "total": int(aggregates.total or 0),
    }
    # `total` stays the count under the active tab: it drives paging and the
    # export size guard, both of which must match the rows actually returned. On
    # the unfiltered tab the two scopes coincide and the extra round trip is skipped.
    if not narrowed:
        total = action_counts["total"]
    else:
        total = int(
            await session.scalar(
                select(func.count(PricingRecommendation.id))
                .join(
                    CatalogItem,
                    CatalogItem.id == PricingRecommendation.catalog_item_id,
                )
                .where(*conditions)
            )
            or 0
        )
    order = _recommendation_sort_order(sort)
    rows = list(
        (
            await session.execute(
                select(PricingRecommendation, CatalogItem)
                .join(
                    CatalogItem, CatalogItem.id == PricingRecommendation.catalog_item_id
                )
                .where(*conditions)
                .order_by(*order, PricingRecommendation.id.asc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return [(row[0], row[1]) for row in rows], total, run_id, action_counts


def recommendation_price_identity_allowed(item: Any, action: str | None) -> bool:
    """Return whether a persisted recommendation may carry a price decision.

    ``CatalogItem.oe_norm`` was overloaded on pre-WP-2 rows: for ``MPN_ONLY``
    imports it can be a private KEMP code.  The database recommendation is
    immutable, so old rows cannot be rewritten in place.  Every read/export
    boundary therefore applies this last-mile guard as well as the creation
    and calculation gates.

    Small in-memory adapters used by pure tests may not expose
    ``identity_status``; those retain the historical explicit-OE fallback only
    when a non-empty ``oe_norm`` is present.  Real ORM rows always persist the
    status and consequently fail closed when it is ``UNRESOLVED``/``MPN_ONLY``.
    """

    normalized_action = str(action or "").strip().upper()
    if normalized_action not in PRICE_BEARING_RECOMMENDATION_ACTIONS:
        return True
    raw_status = getattr(item, "identity_status", None)
    if raw_status is None:
        return bool(getattr(item, "oe_norm", None))
    return str(raw_status or "").strip().upper() == "OE_CONFIRMED"


def _recommendation_sort_order(sort: str) -> list[Any]:
    """Return literal, unit-homogeneous ordering independent of queue filters."""
    if sort == "ABSOLUTE_RECOMMENDED_CHANGE":
        return [
            PricingRecommendation.absolute_recommended_change.desc().nullslast(),
            PricingRecommendation.confidence.desc(),
            PricingRecommendation.computed_at.desc(),
        ]
    elif sort == "PERCENT_RECOMMENDED_CHANGE":
        return [
            PricingRecommendation.percentage_recommended_change.desc().nullslast(),
            PricingRecommendation.confidence.desc(),
            PricingRecommendation.computed_at.desc(),
        ]
    elif sort == "EXPECTED_GROSS_UPLIFT":
        return [
            PricingRecommendation.priority_score.desc(),
            PricingRecommendation.confidence.desc(),
            PricingRecommendation.computed_at.desc(),
        ]
    elif sort == "CLEARANCE_CAPITAL_LOCK":
        return [
            PricingRecommendation.priority_score.desc(),
            PricingRecommendation.computed_at.desc(),
        ]
    elif sort == "REVIEW_PRIORITY":
        return [
            PricingRecommendation.review_priority.desc(),
            PricingRecommendation.computed_at.desc(),
        ]
    elif sort == "NEWEST":
        return [PricingRecommendation.computed_at.desc()]
    raise PricingRunError(f"Unknown recommendation sort: {sort}")


async def get_recommendation(
    session: AsyncSession, *, workspace_id: UUID, recommendation_id: UUID
) -> tuple[PricingRecommendation, CatalogItem]:
    row = (
        await session.execute(
            select(PricingRecommendation, CatalogItem)
            .join(CatalogItem, CatalogItem.id == PricingRecommendation.catalog_item_id)
            .join(PricingRun, PricingRun.id == PricingRecommendation.pricing_run_id)
            .where(
                PricingRecommendation.id == recommendation_id,
                PricingRun.workspace_id == workspace_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise RecommendationNotFoundError(str(recommendation_id))
    return row[0], row[1]


async def get_recommendation_evidence(
    session: AsyncSession, *, workspace_id: UUID, recommendation_id: UUID
) -> list[tuple[MarketObservation, ObservationTierClassification]]:
    recommendation, _ = await get_recommendation(
        session, workspace_id=workspace_id, recommendation_id=recommendation_id
    )
    rows = list(
        (
            await session.execute(
                select(MarketObservation, ObservationTierClassification)
                .join(
                    ObservationTierClassification,
                    ObservationTierClassification.market_observation_id
                    == MarketObservation.id,
                )
                .where(
                    MarketObservation.pricing_run_item_id
                    == recommendation.pricing_run_item_id,
                )
                .order_by(
                    MarketObservation.id,
                    ObservationTierClassification.classified_at.desc(),
                    ObservationTierClassification.id.desc(),
                )
            )
        ).all()
    )
    latest: dict[UUID, tuple[MarketObservation, ObservationTierClassification]] = {}
    for observation, classification in rows:
        latest.setdefault(observation.id, (observation, classification))
    return list(latest.values())


async def override_observation_tier(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    observation_id: UUID,
    tier: ProductTier,
    reason: str,
) -> ObservationTierClassification:
    observation = await session.scalar(
        select(MarketObservation)
        .join(
            PricingRunItem, PricingRunItem.id == MarketObservation.pricing_run_item_id
        )
        .join(PricingRun, PricingRun.id == PricingRunItem.pricing_run_id)
        .where(
            MarketObservation.id == observation_id,
            PricingRun.workspace_id == workspace_id,
        )
    )
    if observation is None:
        raise RecommendationNotFoundError(str(observation_id))
    current = await session.scalar(
        select(ObservationTierClassification)
        .where(ObservationTierClassification.market_observation_id == observation_id)
        .order_by(
            ObservationTierClassification.classified_at.desc(),
            ObservationTierClassification.id.desc(),
        )
        .limit(1)
    )
    if not reason.strip():
        raise PricingRunError("Tier override reason is required")
    record = ObservationTierClassification(
        market_observation_id=observation_id,
        tier=tier.value,
        tier_confidence=Decimal("1"),
        is_used=tier == ProductTier.USED,
        is_kemp=tier == ProductTier.KEMP,
        is_owned=current.is_owned if current else False,
        is_dumping=(current.is_dumping if current else False)
        if tier == ProductTier.KEMP
        else False,
        cohort_role=(
            "OWNED_STORE"
            if current and current.is_owned
            else "USED_REJECTED"
            if tier == ProductTier.USED
            else "KEMP_REFERENCE"
            if tier == ProductTier.KEMP
            else "TARGET_MARKET"
        ),
        exclusion_reason="USED_OR_REFURBISHED" if tier == ProductTier.USED else None,
        reason_codes=["MANUAL_OVERRIDE", reason.strip()],
        method_version="manual-tier-override-v1",
        override_user_id=user_id,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def add_recommendation_decision(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    recommendation_id: UUID,
    user_id: UUID,
    decision: str,
    new_price: Decimal | None,
    allow_below_cost: bool,
    warning_confirmed: bool,
    reason: str,
) -> RecommendationDecision:
    recommendation, _ = await get_recommendation(
        session, workspace_id=workspace_id, recommendation_id=recommendation_id
    )
    if decision not in {"accepted", "rejected", "overridden"}:
        raise PricingRunError("Unknown recommendation decision")
    if decision == "accepted" and not recommendation.automatic_eligible:
        raise PricingRunError(
            "Ineligible recommendation cannot be accepted; reject it or record "
            "a manual override"
        )
    if decision == "overridden" and (new_price is None or new_price <= 0):
        raise PricingRunError("Override requires a positive new_price")
    if decision == "accepted":
        new_price = recommendation.recommended_price
    elif decision == "rejected":
        new_price = None
        allow_below_cost = False
        warning_confirmed = False
    if not reason.strip():
        raise PricingRunError("Decision reason is required")
    settings = get_settings()
    try:
        cost = await get_decrypted_catalog_cost(
            session,
            workspace_id=workspace_id,
            catalog_item_id=recommendation.catalog_item_id,
            settings=settings,
        )
    except (CostCiphertextError, CostPrivacyBlocked) as exc:
        raise PricingRunError(str(exc)) from exc
    approved_floor = None
    is_below_cost = _validate_decision_price(
        new_price=new_price,
        cost=cost,
        approved_floor=approved_floor,
        allow_below_cost=allow_below_cost,
        warning_confirmed=warning_confirmed,
    )
    decided_at = datetime.now(UTC)
    record = RecommendationDecision(
        recommendation_id=recommendation_id,
        user_id=user_id,
        decision=decision,
        old_price=recommendation.current_price,
        new_price=new_price,
        cost_snapshot=None,
        recommended_price_snapshot=recommendation.recommended_price,
        approved_floor=None,
        allow_below_cost=allow_below_cost,
        reason=reason.strip(),
        warning_confirmed=is_below_cost and warning_confirmed,
        warning_confirmed_at=decided_at
        if is_below_cost and warning_confirmed
        else None,
        context_snapshot=privacy_safe_mapping(recommendation.context_snapshot),
        policy_version=recommendation.policy_version,
        decided_at=decided_at,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    if is_below_cost:
        pricing_event(
            "below_cost_decision",
            recommendation_id=str(recommendation_id),
            user_id=str(user_id),
            decision=decision,
            new_price=str(new_price),
            cost_privacy_mode=settings.cost_privacy_mode,
        )
    if decision == "overridden":
        pricing_event(
            "manual_recommendation_override",
            recommendation_id=str(recommendation_id),
            user_id=str(user_id),
            original_automatic_eligible=recommendation.automatic_eligible,
            policy_version=recommendation.policy_version,
        )
    return record


__all__ = [
    "ACTIVE_RUN_STATUSES",
    "ACTOR_TYPE_USER",
    "CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY",
    "CONFIRMATION_SOURCE_LEGACY_UNBOUNDED",
    "CONFIRMATION_SOURCE_OPERATOR",
    "CONFIRMATION_SOURCE_SYSTEM_REPLAY",
    "CatalogItemNotFoundError",
    "EXECUTION_POLICY_SNAPSHOT_VERSION",
    "EXPLICIT_ITEMS_SCOPE",
    "LEGACY_UNBOUNDED_SCOPE_CONTRACT",
    "FULL_CATALOG_SCOPE",
    "FrozenCatalogItem",
    "FrozenCatalogOverride",
    "IssuedPreviewContract",
    "MAX_EXPLICIT_SCOPE_ITEMS",
    "PARSER_ADAPTER_VERSION",
    "PREVIEW_CONTRACT_TTL_SECONDS",
    "PREVIEW_CONTRACT_VERSION",
    "PRICING_RUN_SCOPE_CONTRACT_VERSION",
    "PRICING_RUN_SCOPE_MODES",
    "PRICING_RUN_START_PERMISSION",
    "RUN_START_LANE_OPERATOR",
    "RUN_START_LANE_TRUSTED",
    "ACTOR_TYPE_SERVICE",
    "SCOPE_MANIFEST_ADVISORY_SECTION",
    "SCOPE_MANIFEST_EXECUTION_SECTION",
    "SCOPE_MANIFEST_PROVENANCE_SECTION",
    "OperatorRunStart",
    "PreviewActor",
    "PricingRunActiveScopeConflictError",
    "PricingRunError",
    "PricingRunExecutionPolicyError",
    "PricingRunIdempotencyConflictError",
    "PricingRunMembershipError",
    "PricingRunNotFoundError",
    "PricingRunReplayError",
    "PricingRunReplayPlan",
    "PricingRunScope",
    "RunStartIdentity",
    "PricingRunScopeConflictError",
    "PricingRunScopeEstimate",
    "PricingRunSnapshotError",
    "PricingRunStart",
    "PricingRunStartContractError",
    "PricingTaskDispatchError",
    "TrustedRunStart",
    "RecommendationNotFoundError",
    "ScopeCandidate",
    "ScopeExclusion",
    "add_catalog_item_override",
    "add_recommendation_decision",
    "build_pricing_context",
    "build_pricing_run_scope",
    "calibrate_tier_coefficients",
    "cancel_pricing_run",
    "canonical_manifest_bytes",
    "canonical_start_request_hash",
    "catalog_snapshot_fingerprint",
    "create_pricing_run",
    "customer_identity_available",
    "customer_identity_query",
    "customer_public_search_keys",
    "retrieval_only_queries",
    "execution_policy_document",
    "execution_policy_hash",
    "frozen_catalog_item_from_snapshot",
    "frozen_execution_inputs",
    "frozen_override_from_snapshot",
    "get_latest_override",
    "issue_preview_contract",
    "is_legacy_unbounded_run",
    "load_run_execution_policy",
    "load_run_item_start_cost_record",
    "load_run_item_start_override",
    "load_scope_candidates",
    "manifest_membership",
    "membership_digest",
    "plan_pricing_run_replay",
    "policy_fingerprint",
    "policy_from_snapshot",
    "preview_pricing_run",
    "preview_pricing_run_for_operator",
    "resolve_execution_catalog_item",
    "resolve_execution_override",
    "resolve_pricing_run_scope",
    "run_is_bounded",
    "run_start_identity",
    "scope_execution_manifest",
    "scope_input_key",
    "scope_manifest_hash",
    "start_snapshot_fingerprint",
    "get_pricing_run",
    "get_recommendation",
    "get_recommendation_evidence",
    "list_tier_coefficients",
    "list_pricing_runs",
    "list_recommendations",
    "load_run_calibration_pairs",
    "load_target_tier_coefficients",
    "load_tier_coefficients",
    "persist_run_calibration_pairs",
    "policy_from_dict",
    "policy_to_dict",
    "require_activated_run_policy",
    "verified_start_snapshot",
    "verify_run_membership",
    "override_observation_tier",
]


class PricingRunMembershipError(PricingRunError):
    """Материализованный состав прогона разошёлся с замороженным манифестом."""


def manifest_membership(run: PricingRun) -> Mapping[str, Any] | None:
    """Замороженное членство из манифеста. ``None`` — прогон без контракта."""

    version = (run.scope_contract_version or "").strip()
    if not version or version == "LEGACY_UNBOUNDED":
        return None
    manifest = run.scope_manifest or {}
    execution = manifest.get(SCOPE_MANIFEST_EXECUTION_SECTION)
    if not isinstance(execution, Mapping):
        raise PricingRunMembershipError(
            f"RUN_MEMBERSHIP_UNVERIFIABLE: run {run.id} declares contract "
            f"{version!r} but carries no execution manifest"
        )
    membership = execution.get("membership")
    if not isinstance(membership, Mapping):
        raise PricingRunMembershipError(
            f"RUN_MEMBERSHIP_UNVERIFIABLE: run {run.id} declares no membership"
        )
    return membership


async def verify_run_membership(session: AsyncSession, run: PricingRun) -> None:
    """Сверить материализованный состав с неизменяемым манифестом. Отказ, а не догадка.

    Считать по ``total_items`` нельзя: это счётчик строки прогона, и именно на
    него опирался прежний барьер.  Здесь читается манифест — он неизменяем на
    уровне БД, — и проверяются ОБА утверждения: сколько позиций и в каком
    порядке.  Дозапись, не меняющая числа (например, подмена одной позиции
    другой), ловится отпечатком.
    """

    membership = manifest_membership(run)
    if membership is None:
        return
    expected_count = membership.get("count")
    if not isinstance(expected_count, int):
        raise PricingRunMembershipError(
            f"RUN_MEMBERSHIP_UNVERIFIABLE: run {run.id} declares no membership count"
        )
    rows = list(
        (
            await session.execute(
                select(
                    PricingRunItem.catalog_item_id,
                    PricingRunItem.membership_position,
                )
                .where(PricingRunItem.pricing_run_id == run.id)
                .order_by(
                    PricingRunItem.membership_position,
                    PricingRunItem.catalog_item_id,
                )
            )
        ).all()
    )
    if len(rows) != expected_count:
        raise PricingRunMembershipError(
            f"RUN_MEMBERSHIP_CHANGED: run {run.id} froze {expected_count} item(s), "
            f"the database holds {len(rows)}"
        )
    positions = [position for _, position in rows]
    if any(position is None for position in positions):
        # Прогон, созданный до появления позиции членства, порядок не несёт:
        # его нельзя сверить с отпечатком, и делать вид, что можно, нельзя.
        raise PricingRunMembershipError(
            f"RUN_MEMBERSHIP_UNVERIFIABLE: run {run.id} carries items without a "
            "frozen membership position"
        )
    if positions != list(range(expected_count)):
        raise PricingRunMembershipError(
            f"RUN_MEMBERSHIP_CHANGED: run {run.id} membership positions are "
            f"{positions}, expected 0..{expected_count - 1}"
        )
    # Ограниченная область перечисляет членство целиком, поэтому сверяется не
    # «множество совпало», а КАЖДОЕ место: позиция N обязана нести ровно ту
    # позицию каталога, которую заморозил манифест.  Одного отпечатка мало не
    # по существу, а по диагностике — перестановка двух позиций и подмена одной
    # из них ломают отпечаток одинаково, а это разные события; и любой
    # будущий вызывающий, который решит сверить только состав, увидит здесь
    # явную проверку порядка, а не догадается о ней по хешу.
    frozen_ids = membership.get("catalog_item_ids")
    if isinstance(frozen_ids, list):
        if len(frozen_ids) != expected_count:
            raise PricingRunMembershipError(
                f"RUN_MEMBERSHIP_UNVERIFIABLE: run {run.id} lists "
                f"{len(frozen_ids)} frozen item(s) but claims {expected_count}"
            )
        for position, (item_id, _) in enumerate(rows):
            if str(item_id) != str(frozen_ids[position]):
                raise PricingRunMembershipError(
                    f"RUN_MEMBERSHIP_CHANGED: run {run.id} holds catalog item "
                    f"{item_id} at membership position {position}, the frozen "
                    f"manifest names {frozen_ids[position]}"
                )
    actual_digest = membership_digest([item_id for item_id, _ in rows])
    expected_digest = membership.get("digest")
    if actual_digest != expected_digest:
        raise PricingRunMembershipError(
            f"RUN_MEMBERSHIP_CHANGED: run {run.id} materialized membership hashes "
            f"to {actual_digest}, the frozen manifest claims {expected_digest}"
        )


def uses_frozen_start_inputs(run: PricingRun, run_item: PricingRunItem) -> bool:
    """Считать ли позицию по входам, замороженным на старте прогона.

    Прогон обязан быть воспроизводимым: правка каталога или себестоимости,
    поданная оператором уже во время расчёта, не должна попадать в идущий
    прогон, иначе часть позиций посчитана по старым данным, часть по новым, и
    в отчёте об этом нет ни следа.

    Прогоны, начатые до появления замороженной области, таких ссылок не имеют.
    Для них возвращается ``False`` и сохраняется прежнее поведение — это
    единственный способ досчитать их, не переписывая историю.
    """

    if run_item.catalog_item_override_id is not None:
        return True
    if run_item.cost_record_id is not None:
        return True
    version = (run.scope_contract_version or "").strip()
    return bool(version) and version != "LEGACY_UNBOUNDED"
