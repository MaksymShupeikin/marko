"""Resumable coverage re-measurement over a frozen list of catalog targets.

Gate 1 asks one question: how many comparable competitors the old search page
limit was hiding.  Answering it honestly requires re-running the *same* targets
as the 2026-07-19 baseline and counting the *same* cohort, so the cohort
predicates live here as explicit, testable functions instead of as an ad-hoc
query written once and forgotten.

Three cohorts are counted per target, because one number cannot answer both the
historical and the production question:

``baseline_exact_article``
    Reproduces the 2026-07-19 definition exactly: the candidate's own article
    field normalizes to the target OE, the seller is not ours, the offer is
    neither KEMP-branded nor detected as used, and one seller contributes at
    most one offer.  This is the only cohort that may be compared against the
    published ``mean 2.5333 / median 1.5``.

``identity_any_evidence``
    The production identity cohort: the OEM identity gate found the target OE
    in any lane (article, title, description, confirmed cross), and the offer
    survived the cheap gates ahead of it.  This is the realistic ceiling once
    brand tiers are approved.

``plan_s_set``
    The master plan §2.3 selection set.  It requires a ``COMPARABLE`` verdict,
    which stays unreachable while ``brands.yaml`` is unapproved.  It is counted
    anyway so the gap between "identity found" and "usable for pricing" stays a
    measured number rather than an assertion.

Resumption is fail-closed.  A checkpoint may only be continued by a batch whose
target list and result-affecting settings hash identically; otherwise the file
would silently mix observations produced under two different configurations.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any
from uuid import UUID
import zlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import Settings, get_settings
from marko.infrastructure.db.models import (
    CatalogDiscoveryCapture,
    CatalogDiscoveryOffer,
    CatalogDiscoveryRun,
    ScrapeEvidenceBlob,
)
from marko.parsers.prom.parser import parse_search
from marko.services.catalog_discovery import (
    CatalogDiscoveryError,
    collect_catalog_discovery,
)
from metis.pricing import classify_tier, normalize_candidate_oem


COVERAGE_TARGETS_SCHEMA_VERSION = "metis-coverage-targets-v1"
COVERAGE_CHECKPOINT_SCHEMA_VERSION = "metis-coverage-checkpoint-v1"
COVERAGE_REPORT_SCHEMA_VERSION = "metis-coverage-report-v1"

COHORT_BASELINE = "baseline_exact_article"
COHORT_IDENTITY = "identity_any_evidence"
COHORT_PLAN_S = "plan_s_set"
COHORT_ORDER: tuple[str, ...] = (COHORT_BASELINE, COHORT_IDENTITY, COHORT_PLAN_S)

# Diagnostics only: these never gate a candidate, they answer plan item 1.4
# ("зафиксировать HTTP-коды, капчи, задержки") on the persisted raw bodies.
BLOCKING_BODY_MARKERS: tuple[str, ...] = (
    "captcha",
    "recaptcha",
    "cf-challenge",
    "cf_chl_opt",
    "just a moment",
    "attention required",
    "access denied",
    "too many requests",
    "ви не робот",
    "вы не робот",
    "доступ обмежено",
    "доступ ограничен",
)

_QUANTUM = Decimal("0.0001")


class CoverageMeasurementError(RuntimeError):
    """Raised when a batch cannot be started or safely resumed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


# --------------------------------------------------------------------------
# Target list
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoverageTarget:
    sample_no: int
    category: str
    oe_raw: str
    oe_norm: str
    title: str
    baseline_after_filter: int | None = None


@dataclass(frozen=True, slots=True)
class CoverageTargetSet:
    source_path: str
    source_sha256: str
    content_sha256: str
    targets: tuple[CoverageTarget, ...]

    def __len__(self) -> int:
        return len(self.targets)


def load_coverage_targets(path: str | Path) -> CoverageTargetSet:
    """Load and validate the frozen target list, hashing the exact bytes read."""

    source = Path(path).expanduser()
    if not source.is_file():
        raise CoverageMeasurementError(
            "COVERAGE_TARGETS_MISSING",
            f"Файл целей не найден: {source}",
        )
    raw = source.read_bytes()
    content_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageMeasurementError(
            "COVERAGE_TARGETS_UNREADABLE",
            f"Файл целей не разобран как JSON: {exc}",
        ) from exc
    if not isinstance(document, Mapping):
        raise CoverageMeasurementError(
            "COVERAGE_TARGETS_UNREADABLE",
            "Файл целей должен быть JSON-объектом.",
        )
    schema_version = str(document.get("schema_version") or "")
    if schema_version != COVERAGE_TARGETS_SCHEMA_VERSION:
        raise CoverageMeasurementError(
            "COVERAGE_TARGETS_SCHEMA_MISMATCH",
            "Ожидалась схема "
            f"{COVERAGE_TARGETS_SCHEMA_VERSION}, получена {schema_version!r}.",
        )
    rows = document.get("targets")
    if not isinstance(rows, Sequence) or not rows:
        raise CoverageMeasurementError(
            "COVERAGE_TARGETS_EMPTY",
            "Список целей пуст.",
        )
    targets: list[CoverageTarget] = []
    seen_sample_numbers: set[int] = set()
    seen_oems: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise CoverageMeasurementError(
                "COVERAGE_TARGETS_UNREADABLE",
                f"Цель #{index} не является объектом.",
            )
        oe_raw = str(row.get("oe_raw") or "").strip()
        oe_norm = normalize_candidate_oem(row.get("oe_norm") or oe_raw)
        if not oe_norm:
            raise CoverageMeasurementError(
                "COVERAGE_TARGET_IDENTIFIER_REQUIRED",
                f"Цель #{index} не содержит пригодного OE.",
            )
        try:
            sample_no = int(row.get("sample_no", index + 1))
        except (TypeError, ValueError) as exc:
            raise CoverageMeasurementError(
                "COVERAGE_TARGETS_UNREADABLE",
                f"Цель #{index}: sample_no не целое число.",
            ) from exc
        if sample_no in seen_sample_numbers:
            raise CoverageMeasurementError(
                "COVERAGE_TARGET_DUPLICATE",
                f"sample_no {sample_no} встречается дважды.",
            )
        if oe_norm in seen_oems:
            raise CoverageMeasurementError(
                "COVERAGE_TARGET_DUPLICATE",
                f"OE {oe_norm} встречается дважды.",
            )
        seen_sample_numbers.add(sample_no)
        seen_oems.add(oe_norm)
        baseline = row.get("baseline_after_filter")
        targets.append(
            CoverageTarget(
                sample_no=sample_no,
                category=str(row.get("category") or "").strip() or "uncategorized",
                oe_raw=oe_raw or oe_norm,
                oe_norm=oe_norm,
                title=str(row.get("title") or "").strip(),
                baseline_after_filter=(
                    int(baseline) if isinstance(baseline, int) else None
                ),
            )
        )
    targets.sort(key=lambda target: target.sample_no)
    return CoverageTargetSet(
        source_path=str(source),
        source_sha256=str(document.get("source_sha256") or ""),
        content_sha256=content_sha256,
        targets=tuple(targets),
    )


# --------------------------------------------------------------------------
# Checkpoint
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BatchIdentity:
    """Everything that would invalidate a resume if it changed mid-batch."""

    targets_sha256: str
    workspace_id: str
    search_page_limit: int
    selection_config_sha256: str | None
    brand_rules_dataset_id: str | None
    request_delay_seconds: str
    request_jitter_seconds: str
    http_max_attempts: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "targets_sha256": self.targets_sha256,
            "workspace_id": self.workspace_id,
            "search_page_limit": self.search_page_limit,
            "selection_config_sha256": self.selection_config_sha256,
            "brand_rules_dataset_id": self.brand_rules_dataset_id,
            "request_delay_seconds": self.request_delay_seconds,
            "request_jitter_seconds": self.request_jitter_seconds,
            "http_max_attempts": self.http_max_attempts,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BatchIdentity:
        return cls(
            targets_sha256=str(payload.get("targets_sha256") or ""),
            workspace_id=str(payload.get("workspace_id") or ""),
            search_page_limit=int(payload.get("search_page_limit") or 0),
            selection_config_sha256=(
                str(payload["selection_config_sha256"])
                if payload.get("selection_config_sha256")
                else None
            ),
            brand_rules_dataset_id=(
                str(payload["brand_rules_dataset_id"])
                if payload.get("brand_rules_dataset_id")
                else None
            ),
            request_delay_seconds=str(payload.get("request_delay_seconds") or "0"),
            request_jitter_seconds=str(payload.get("request_jitter_seconds") or "0"),
            http_max_attempts=int(payload.get("http_max_attempts") or 0),
        )


@dataclass(frozen=True, slots=True)
class TargetOutcome:
    sample_no: int
    oe_norm: str
    status: str
    run_id: UUID | None
    error_code: str | None
    error_detail: str | None
    duration_ms: int
    recorded_at: str

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "record": "target",
            "sample_no": self.sample_no,
            "oe_norm": self.oe_norm,
            "status": self.status,
            "run_id": str(self.run_id) if self.run_id else None,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "duration_ms": self.duration_ms,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TargetOutcome:
        raw_run_id = payload.get("run_id")
        return cls(
            sample_no=int(payload["sample_no"]),
            oe_norm=str(payload.get("oe_norm") or ""),
            status=str(payload.get("status") or "failed"),
            run_id=UUID(str(raw_run_id)) if raw_run_id else None,
            error_code=(
                str(payload["error_code"]) if payload.get("error_code") else None
            ),
            error_detail=(
                str(payload["error_detail"]) if payload.get("error_detail") else None
            ),
            duration_ms=int(payload.get("duration_ms") or 0),
            recorded_at=str(payload.get("recorded_at") or ""),
        )


class MeasurementCheckpoint:
    """Append-only JSONL progress log that makes a batch restartable.

    The first line pins the batch identity.  Every later line records one
    attempt against one target; the last line for a ``sample_no`` wins, so a
    retried failure supersedes the earlier failure without rewriting history.
    """

    def __init__(self, path: Path, identity: BatchIdentity) -> None:
        self._path = path
        self._identity = identity
        self._outcomes: dict[int, TargetOutcome] = {}

    @property
    def path(self) -> Path:
        return self._path

    @property
    def identity(self) -> BatchIdentity:
        return self._identity

    @property
    def outcomes(self) -> Mapping[int, TargetOutcome]:
        return dict(self._outcomes)

    @classmethod
    def open(cls, path: str | Path, identity: BatchIdentity) -> MeasurementCheckpoint:
        resolved = Path(path).expanduser()
        checkpoint = cls(resolved, identity)
        if resolved.exists():
            checkpoint._load()
            return checkpoint
        resolved.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "record": "header",
            "schema_version": COVERAGE_CHECKPOINT_SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "identity": identity.as_dict(),
        }
        checkpoint._append(header)
        return checkpoint

    def _load(self) -> None:
        lines = [
            line
            for line in self._path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not lines:
            raise CoverageMeasurementError(
                "COVERAGE_CHECKPOINT_EMPTY",
                f"Чекпоинт {self._path} существует, но пуст. "
                "Удалите файл, чтобы начать заново.",
            )
        try:
            header = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            raise CoverageMeasurementError(
                "COVERAGE_CHECKPOINT_CORRUPT",
                f"Заголовок чекпоинта не разобран: {exc}",
            ) from exc
        if header.get("record") != "header":
            raise CoverageMeasurementError(
                "COVERAGE_CHECKPOINT_CORRUPT",
                "Первая строка чекпоинта не является заголовком.",
            )
        if header.get("schema_version") != COVERAGE_CHECKPOINT_SCHEMA_VERSION:
            raise CoverageMeasurementError(
                "COVERAGE_CHECKPOINT_SCHEMA_MISMATCH",
                "Схема чекпоинта "
                f"{header.get('schema_version')!r} не совпадает с "
                f"{COVERAGE_CHECKPOINT_SCHEMA_VERSION!r}.",
            )
        stored = BatchIdentity.from_dict(header.get("identity") or {})
        if stored != self._identity:
            raise CoverageMeasurementError(
                "COVERAGE_CHECKPOINT_IDENTITY_MISMATCH",
                "Чекпоинт создан при другой конфигурации, продолжение "
                "смешало бы несопоставимые наблюдения. Отличия: "
                + ", ".join(_identity_differences(stored, self._identity)),
            )
        for line_no, line in enumerate(lines[1:], start=2):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                # A kill during the final write can leave one truncated line.
                # Everything before it is intact, so the batch stays resumable.
                if line_no == len(lines):
                    break
                raise CoverageMeasurementError(
                    "COVERAGE_CHECKPOINT_CORRUPT",
                    f"Строка {line_no} чекпоинта не разобрана: {exc}",
                ) from exc
            if payload.get("record") != "target":
                continue
            outcome = TargetOutcome.from_dict(payload)
            self._outcomes[outcome.sample_no] = outcome

    def _append(self, payload: Mapping[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def record(self, outcome: TargetOutcome) -> None:
        self._append(outcome.as_dict())
        self._outcomes[outcome.sample_no] = outcome

    def pending(
        self,
        targets: Iterable[CoverageTarget],
        *,
        retry_failed: bool = True,
    ) -> tuple[CoverageTarget, ...]:
        targets_by_sample = {target.sample_no: target for target in targets}
        unexpected = sorted(set(self._outcomes) - set(targets_by_sample))
        if unexpected:
            raise CoverageMeasurementError(
                "COVERAGE_CHECKPOINT_TARGET_MISMATCH",
                "Чекпоинт содержит sample_no вне замороженного списка целей: "
                + ", ".join(map(str, unexpected)),
            )
        pending: list[CoverageTarget] = []
        for target in targets_by_sample.values():
            recorded = self._outcomes.get(target.sample_no)
            if recorded is None:
                pending.append(target)
                continue
            if recorded.oe_norm != target.oe_norm:
                raise CoverageMeasurementError(
                    "COVERAGE_CHECKPOINT_TARGET_MISMATCH",
                    f"sample_no {target.sample_no}: чекпоинт содержит OE "
                    f"{recorded.oe_norm!r}, ожидается {target.oe_norm!r}.",
                )
            if recorded.is_completed:
                continue
            if retry_failed:
                pending.append(target)
        return tuple(pending)

    def completed_run_ids(self) -> dict[int, UUID]:
        return {
            sample_no: outcome.run_id
            for sample_no, outcome in sorted(self._outcomes.items())
            if outcome.is_completed and outcome.run_id is not None
        }


def _identity_differences(stored: BatchIdentity, current: BatchIdentity) -> list[str]:
    stored_map = stored.as_dict()
    current_map = current.as_dict()
    return [
        f"{key}: {stored_map[key]!r} → {current_map[key]!r}"
        for key in stored_map
        if stored_map[key] != current_map[key]
    ] or ["неизвестное поле"]


def build_batch_identity(
    *,
    targets: CoverageTargetSet,
    workspace_id: UUID,
    settings: Settings,
    selection_config_sha256: str | None,
    brand_rules_dataset_id: str | None,
) -> BatchIdentity:
    return BatchIdentity(
        targets_sha256=targets.content_sha256,
        workspace_id=str(workspace_id),
        search_page_limit=settings.catalog_discovery_max_search_pages,
        selection_config_sha256=selection_config_sha256,
        brand_rules_dataset_id=brand_rules_dataset_id,
        request_delay_seconds=str(settings.pricing_scraper_request_delay_seconds),
        request_jitter_seconds=str(settings.pricing_scraper_request_jitter_seconds),
        http_max_attempts=int(settings.pricing_scraper_http_max_attempts),
    )


# --------------------------------------------------------------------------
# Collection driver
# --------------------------------------------------------------------------


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class BatchProgress:
    attempted: int
    completed: int
    failed: int
    skipped: int
    elapsed_seconds: Decimal


async def run_coverage_batch(
    session_factory: SessionFactory,
    *,
    targets: CoverageTargetSet,
    checkpoint: MeasurementCheckpoint,
    workspace_id: UUID,
    settings: Settings | None = None,
    retry_failed: bool = True,
    target_delay_seconds: float = 0.0,
    limit: int | None = None,
    sleep: Callable[[float], Any] | None = None,
    progress: Callable[[str], None] | None = None,
) -> BatchProgress:
    """Collect every pending target, recording each outcome before moving on.

    One target is one transaction and one checkpoint line, so a kill at any
    moment costs at most the target in flight.
    """

    resolved_settings = settings or get_settings()
    pending = checkpoint.pending(targets.targets, retry_failed=retry_failed)
    skipped = len(targets) - len(pending)
    if limit is not None:
        deferred = max(0, len(pending) - max(0, limit))
        pending = pending[: max(0, limit)]
        skipped += deferred
    completed = 0
    failed = 0
    started = time.monotonic()
    if progress is not None:
        progress(
            f"Целей всего {len(targets)}, к обработке {len(pending)}, "
            f"уже зафиксировано {skipped}."
        )
    for index, target in enumerate(pending, start=1):
        if index > 1 and target_delay_seconds > 0 and sleep is not None:
            await sleep(target_delay_seconds)
        attempt_started = time.monotonic()
        run_id: UUID | None = None
        error_code: str | None = None
        error_detail: str | None = None
        try:
            async with session_factory() as session:
                snapshot = await collect_catalog_discovery(
                    session,
                    workspace_id=workspace_id,
                    sku=None,
                    oe=target.oe_raw,
                    brand=None,
                    title=target.title or None,
                    category=target.category,
                    settings=resolved_settings,
                )
            run_id = snapshot.run_id
            status = "completed"
            completed += 1
        except Exception as exc:  # noqa: BLE001 - every failure must be recorded
            status = "failed"
            failed += 1
            error_code = str(getattr(exc, "code", type(exc).__name__))[:100]
            error_detail = str(exc)[:2000]
        duration_ms = int((time.monotonic() - attempt_started) * 1000)
        checkpoint.record(
            TargetOutcome(
                sample_no=target.sample_no,
                oe_norm=target.oe_norm,
                status=status,
                run_id=run_id,
                error_code=error_code,
                error_detail=error_detail,
                duration_ms=duration_ms,
                recorded_at=datetime.now(UTC).isoformat(),
            )
        )
        if progress is not None:
            suffix = f"run={run_id}" if run_id else f"error={error_code}"
            progress(
                f"[{index}/{len(pending)}] #{target.sample_no} "
                f"{target.oe_norm} → {status} ({duration_ms} мс) {suffix}"
            )
    return BatchProgress(
        attempted=len(pending),
        completed=completed,
        failed=failed,
        skipped=skipped,
        elapsed_seconds=Decimal(str(round(time.monotonic() - started, 3))),
    )


# --------------------------------------------------------------------------
# Cohorts
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OfferFacts:
    """The minimum an offer must expose for the cohort predicates."""

    source_listing_id: str
    seller_id: str
    sku: str | None
    brand: str | None
    title: str
    description: str | None
    condition: str | None
    is_owned: bool
    is_available: bool | None
    selection_status: str
    oem_evidence: str | None


def offer_facts(offer: CatalogDiscoveryOffer) -> OfferFacts:
    snapshot = offer.raw_snapshot if isinstance(offer.raw_snapshot, Mapping) else {}
    details = (
        offer.selection_details if isinstance(offer.selection_details, Mapping) else {}
    )
    gates = details.get("gates") if isinstance(details.get("gates"), Mapping) else {}
    identity = gates.get("oem_identity") if isinstance(gates, Mapping) else None
    evidence = (
        identity.get("evidence")
        if isinstance(identity, Mapping) and identity.get("evidence")
        else None
    )
    description = snapshot.get("description")
    condition = snapshot.get("condition")
    return OfferFacts(
        source_listing_id=offer.source_listing_id,
        seller_id=(offer.seller_id or "").strip(),
        sku=offer.sku,
        brand=offer.brand,
        title=offer.title or "",
        description=str(description) if description else None,
        condition=str(condition) if condition else None,
        is_owned=bool(offer.is_owned),
        is_available=offer.is_available,
        selection_status=offer.selection_status,
        oem_evidence=str(evidence) if evidence else None,
    )


def _dedupe_key(facts: OfferFacts) -> str:
    # The baseline deduplicated by stable seller id.  An offer without one must
    # not silently collapse every anonymous seller into a single observation.
    return facts.seller_id or f"listing:{facts.source_listing_id}"


def cohort_membership(target_oe: str, facts: OfferFacts) -> frozenset[str]:
    """Return every cohort this single offer belongs to.

    Cohort A is deliberately recomputed from the offer's own fields rather than
    read off the gate chain: gates stop at the first terminal result, so an
    offer skipped as ``DISMANTLER_SELLER`` never reaches OEM identity, and
    reading identity off the chain would silently shrink a cohort whose 2026
    baseline had no dismantler rule at all.
    """

    expected = normalize_candidate_oem(target_oe)
    tier = classify_tier(
        brand=facts.brand,
        title=facts.title,
        description=facts.description,
        condition=facts.condition,
    )
    excluded = facts.is_owned or tier.is_kemp or tier.is_used
    memberships: set[str] = set()

    article = normalize_candidate_oem(facts.sku)
    if expected and article == expected and not excluded:
        memberships.add(COHORT_BASELINE)

    if facts.oem_evidence is not None and not facts.is_owned and not tier.is_kemp:
        memberships.add(COHORT_IDENTITY)

    in_stock = facts.is_available is not False
    if facts.selection_status == "PRICING_EVIDENCE" and not excluded and in_stock:
        memberships.add(COHORT_PLAN_S)

    return frozenset(memberships)


def cohort_counts(
    target_oe: str,
    offers: Iterable[OfferFacts],
) -> dict[str, int]:
    """Count seller-deduplicated offers per cohort for one target."""

    seen: dict[str, set[str]] = {cohort: set() for cohort in COHORT_ORDER}
    for facts in offers:
        key = _dedupe_key(facts)
        for cohort in cohort_membership(target_oe, facts):
            seen[cohort].add(key)
    return {cohort: len(seen[cohort]) for cohort in COHORT_ORDER}


# --------------------------------------------------------------------------
# Metrics (§2.7)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoverageMetrics:
    target_count: int
    total: int
    mean: Decimal | None
    median: Decimal | None
    share_ge3: Decimal | None
    share_zero: Decimal | None
    distribution: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_count": self.target_count,
            "total": self.total,
            "mean": str(self.mean) if self.mean is not None else None,
            "median": str(self.median) if self.median is not None else None,
            "share_ge3": str(self.share_ge3) if self.share_ge3 is not None else None,
            "share_zero": (
                str(self.share_zero) if self.share_zero is not None else None
            ),
            "distribution": dict(self.distribution),
        }


def _median(sorted_counts: Sequence[int]) -> Decimal:
    size = len(sorted_counts)
    middle = size // 2
    if size % 2 == 1:
        return Decimal(sorted_counts[middle]).quantize(_QUANTUM)
    lower = Decimal(sorted_counts[middle - 1])
    upper = Decimal(sorted_counts[middle])
    return ((lower + upper) / Decimal(2)).quantize(_QUANTUM)


def coverage_metrics(counts: Sequence[int]) -> CoverageMetrics:
    """Compute the §2.7 coverage metrics without dividing by an empty sample.

    ``share_ge3`` is the headline number: three comparable competitors is the
    point at which the engine is allowed to recommend at all.
    """

    size = len(counts)
    distribution = {
        "0": sum(1 for value in counts if value == 0),
        "1-2": sum(1 for value in counts if 1 <= value <= 2),
        "3-4": sum(1 for value in counts if 3 <= value <= 4),
        "5+": sum(1 for value in counts if value >= 5),
    }
    if size == 0:
        return CoverageMetrics(
            target_count=0,
            total=0,
            mean=None,
            median=None,
            share_ge3=None,
            share_zero=None,
            distribution=distribution,
        )
    total = sum(counts)
    divisor = Decimal(size)
    return CoverageMetrics(
        target_count=size,
        total=total,
        mean=(Decimal(total) / divisor).quantize(_QUANTUM),
        median=_median(sorted(counts)),
        share_ge3=(
            Decimal(sum(1 for value in counts if value >= 3)) / divisor
        ).quantize(_QUANTUM),
        share_zero=(
            Decimal(sum(1 for value in counts if value == 0)) / divisor
        ).quantize(_QUANTUM),
        distribution=distribution,
    )


# --------------------------------------------------------------------------
# Anti-bot telemetry (§1.4)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequestTelemetry:
    request_count: int
    status_histogram: Mapping[str, int]
    retried_request_count: int
    attempts_total: int
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    latency_max_ms: int | None
    blocking_marker_hits: Mapping[str, int]
    suspected_block_count: int
    pages_without_products: int
    scanned_blob_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_count": self.request_count,
            "status_histogram": dict(self.status_histogram),
            "retried_request_count": self.retried_request_count,
            "attempts_total": self.attempts_total,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_max_ms": self.latency_max_ms,
            "blocking_marker_hits": dict(self.blocking_marker_hits),
            "suspected_block_count": self.suspected_block_count,
            "pages_without_products": self.pages_without_products,
            "scanned_blob_count": self.scanned_blob_count,
        }


def _quantile(sorted_values: Sequence[int], fraction: Decimal) -> int | None:
    """Nearest-rank quantile.

    Deliberately not an interpolating quantile: latency samples here are a
    handful of integers per run, and a rank always names a request that really
    happened.
    """

    if not sorted_values:
        return None
    size = len(sorted_values)
    rank = int((fraction * Decimal(size)).to_integral_value(rounding="ROUND_CEILING"))
    return sorted_values[max(0, min(size - 1, rank - 1))]


def summarize_request_telemetry(
    captures: Sequence[tuple[int, int, int]],
    *,
    blocking_marker_hits: Mapping[str, int] | None = None,
    suspected_block_count: int = 0,
    pages_without_products: int = 0,
    scanned_blob_count: int = 0,
) -> RequestTelemetry:
    """Summarize ``(status_code, attempts_total, latency_ms)`` triples."""

    statuses: dict[str, int] = {}
    for status_code, _attempts, _latency in captures:
        key = str(status_code)
        statuses[key] = statuses.get(key, 0) + 1
    latencies = sorted(latency for _status, _attempts, latency in captures)
    return RequestTelemetry(
        request_count=len(captures),
        status_histogram=dict(sorted(statuses.items())),
        retried_request_count=sum(
            1 for _status, attempts, _latency in captures if attempts > 1
        ),
        attempts_total=sum(attempts for _status, attempts, _latency in captures),
        latency_p50_ms=_quantile(latencies, Decimal("0.5")),
        latency_p95_ms=_quantile(latencies, Decimal("0.95")),
        latency_max_ms=latencies[-1] if latencies else None,
        blocking_marker_hits=dict(sorted((blocking_marker_hits or {}).items())),
        suspected_block_count=suspected_block_count,
        pages_without_products=pages_without_products,
        scanned_blob_count=scanned_blob_count,
    )


def scan_blocking_markers(body: str) -> tuple[str, ...]:
    """Return blocking keywords present in a response body.

    A hit alone proves nothing: a healthy Prom search page embeds
    ``CHAT_385_SHOW_BUYER_RECAPTCHA_*`` feature flags and a chat widget site
    key, so "recaptcha" appears in every 200 that also carries a full result
    set.  Callers must combine this with :func:`parsed_product_count`; see
    :func:`assess_capture_body`.
    """

    lowered = body.lower()
    return tuple(marker for marker in BLOCKING_BODY_MARKERS if marker in lowered)


def parsed_product_count(body: str, language: str = "ua") -> int:
    """Count products the production parser recovers from a captured body.

    A body that yields products cannot have been an anti-bot challenge, which
    is the only reliable way to tell a real block from Prom's ambient
    captcha configuration.
    """

    try:
        return len(parse_search(body, language).products)
    except Exception:  # noqa: BLE001 - an unparseable body is itself the signal
        return 0


@dataclass(frozen=True, slots=True)
class CaptureAssessment:
    product_count: int
    parser_outcome: str
    markers: tuple[str, ...]

    @property
    def is_suspected_block(self) -> bool:
        return (
            self.product_count == 0
            and self.parser_outcome != "EMPTY_SEARCH_RESULT"
            and bool(self.markers)
        )

    @property
    def yielded_no_products(self) -> bool:
        return self.product_count == 0


def assess_capture_body(body: str, language: str = "ua") -> CaptureAssessment:
    """Decide whether one captured response looks like an anti-bot response."""

    try:
        page = parse_search(body, language)
    except Exception as exc:  # noqa: BLE001 - the outcome is diagnostic evidence
        count = 0
        parser_outcome = f"UNPARSEABLE:{type(exc).__name__}"
    else:
        count = len(page.products)
        parser_outcome = page.outcome
    return CaptureAssessment(
        product_count=count,
        parser_outcome=parser_outcome,
        markers=(
            scan_blocking_markers(body)
            if count == 0 and parser_outcome != "EMPTY_SEARCH_RESULT"
            else ()
        ),
    )


# --------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetCoverage:
    sample_no: int
    category: str
    oe_norm: str
    run_id: UUID | None
    status: str
    prom_reported_total: int | None
    retrieved_count: int
    persisted_count: int
    request_count: int
    coverage_ratio: Decimal | None
    coverage_reason: str | None
    duration_ms: int
    baseline_after_filter: int | None
    counts: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_no": self.sample_no,
            "category": self.category,
            "oe_norm": self.oe_norm,
            "run_id": str(self.run_id) if self.run_id else None,
            "status": self.status,
            "prom_reported_total": self.prom_reported_total,
            "retrieved_count": self.retrieved_count,
            "persisted_count": self.persisted_count,
            "request_count": self.request_count,
            "coverage_ratio": (
                str(self.coverage_ratio) if self.coverage_ratio is not None else None
            ),
            "coverage_reason": self.coverage_reason,
            "duration_ms": self.duration_ms,
            "baseline_after_filter": self.baseline_after_filter,
            "counts": dict(self.counts),
        }


@dataclass(frozen=True, slots=True)
class CoverageReport:
    schema_version: str
    generated_at: datetime
    targets_path: str
    targets_sha256: str
    checkpoint_path: str
    identity: BatchIdentity
    target_rows: tuple[TargetCoverage, ...]
    failed_rows: tuple[TargetCoverage, ...]
    cohort_metrics: Mapping[str, CoverageMetrics]
    baseline_metrics: CoverageMetrics | None
    retrieval_coverage: Mapping[str, Any]
    telemetry: RequestTelemetry
    availability: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "targets_path": self.targets_path,
            "targets_sha256": self.targets_sha256,
            "checkpoint_path": self.checkpoint_path,
            "identity": self.identity.as_dict(),
            "targets": [row.as_dict() for row in self.target_rows],
            "failed": [row.as_dict() for row in self.failed_rows],
            "cohort_metrics": {
                cohort: metrics.as_dict()
                for cohort, metrics in self.cohort_metrics.items()
            },
            "baseline_metrics": (
                self.baseline_metrics.as_dict()
                if self.baseline_metrics is not None
                else None
            ),
            "retrieval_coverage": dict(self.retrieval_coverage),
            "telemetry": self.telemetry.as_dict(),
            "availability": dict(self.availability),
        }


async def build_coverage_report(
    session: AsyncSession,
    *,
    targets: CoverageTargetSet,
    checkpoint: MeasurementCheckpoint,
    scan_bodies: bool = True,
) -> CoverageReport:
    """Recompute every metric from persisted evidence, never from live state."""

    outcomes = checkpoint.outcomes
    rows: list[TargetCoverage] = []
    failed: list[TargetCoverage] = []
    capture_triples: list[tuple[int, int, int]] = []
    marker_hits: dict[str, int] = {}
    scanned_blobs = 0
    suspected_blocks = 0
    empty_pages = 0
    availability = {"available": 0, "unavailable": 0, "unknown": 0}

    for target in targets.targets:
        outcome = outcomes.get(target.sample_no)
        if outcome is None:
            failed.append(
                _empty_target_coverage(target, status="not_attempted", run_id=None)
            )
            continue
        if not outcome.is_completed or outcome.run_id is None:
            failed.append(
                _empty_target_coverage(
                    target,
                    status=outcome.error_code or "failed",
                    run_id=outcome.run_id,
                    duration_ms=outcome.duration_ms,
                )
            )
            continue
        run = await session.get(CatalogDiscoveryRun, outcome.run_id)
        if run is None:
            failed.append(
                _empty_target_coverage(
                    target,
                    status="RUN_ROW_MISSING",
                    run_id=outcome.run_id,
                    duration_ms=outcome.duration_ms,
                )
            )
            continue
        offers = list(
            (
                await session.scalars(
                    select(CatalogDiscoveryOffer).where(
                        CatalogDiscoveryOffer.discovery_run_id == run.id
                    )
                )
            ).all()
        )
        facts = [offer_facts(offer) for offer in offers]
        for item in facts:
            if item.is_available is True:
                availability["available"] += 1
            elif item.is_available is False:
                availability["unavailable"] += 1
            else:
                availability["unknown"] += 1
        rows.append(
            TargetCoverage(
                sample_no=target.sample_no,
                category=target.category,
                oe_norm=target.oe_norm,
                run_id=run.id,
                status=run.status,
                prom_reported_total=run.prom_reported_total,
                retrieved_count=run.retrieved_count,
                persisted_count=run.persisted_count,
                request_count=run.request_count,
                coverage_ratio=run.coverage_ratio,
                coverage_reason=run.coverage_reason,
                duration_ms=outcome.duration_ms,
                baseline_after_filter=target.baseline_after_filter,
                counts=cohort_counts(target.oe_norm, facts),
            )
        )
        captures = list(
            (
                await session.scalars(
                    select(CatalogDiscoveryCapture).where(
                        CatalogDiscoveryCapture.discovery_run_id == run.id
                    )
                )
            ).all()
        )
        for capture in captures:
            capture_triples.append(
                (capture.status_code, capture.attempts_total, capture.latency_ms)
            )
            if not scan_bodies:
                continue
            blob = await session.get(ScrapeEvidenceBlob, capture.evidence_blob_id)
            if blob is None:
                continue
            scanned_blobs += 1
            body = zlib.decompress(blob.content_zlib).decode(
                blob.encoding or "utf-8", errors="replace"
            )
            assessment = assess_capture_body(body)
            if assessment.yielded_no_products:
                empty_pages += 1
            if assessment.is_suspected_block:
                suspected_blocks += 1
            for marker in assessment.markers:
                marker_hits[marker] = marker_hits.get(marker, 0) + 1

    cohort_metrics = {
        cohort: coverage_metrics([row.counts[cohort] for row in rows])
        for cohort in COHORT_ORDER
    }
    baseline_counts = [
        row.baseline_after_filter
        for row in rows
        if row.baseline_after_filter is not None
    ]
    baseline_metrics = (
        coverage_metrics(baseline_counts) if len(baseline_counts) == len(rows) else None
    )
    retrieved = sum(row.retrieved_count for row in rows)
    reported = sum(
        row.prom_reported_total for row in rows if row.prom_reported_total is not None
    )
    return CoverageReport(
        schema_version=COVERAGE_REPORT_SCHEMA_VERSION,
        generated_at=datetime.now(UTC),
        targets_path=targets.source_path,
        targets_sha256=targets.content_sha256,
        checkpoint_path=str(checkpoint.path),
        identity=checkpoint.identity,
        target_rows=tuple(rows),
        failed_rows=tuple(failed),
        cohort_metrics=cohort_metrics,
        baseline_metrics=baseline_metrics,
        retrieval_coverage={
            "retrieved_total": retrieved,
            "prom_reported_total": reported,
            "ratio": (
                str(
                    (Decimal(retrieved) / Decimal(reported)).quantize(
                        Decimal("0.000001")
                    )
                )
                if reported > 0
                else None
            ),
            "reason_histogram": _histogram(
                row.coverage_reason or "UNKNOWN" for row in rows
            ),
            "runs_with_unknown_total": sum(
                1 for row in rows if row.prom_reported_total is None
            ),
        },
        telemetry=summarize_request_telemetry(
            capture_triples,
            blocking_marker_hits=marker_hits,
            suspected_block_count=suspected_blocks,
            pages_without_products=empty_pages,
            scanned_blob_count=scanned_blobs,
        ),
        availability=availability,
    )


def _empty_target_coverage(
    target: CoverageTarget,
    *,
    status: str,
    run_id: UUID | None,
    duration_ms: int = 0,
) -> TargetCoverage:
    return TargetCoverage(
        sample_no=target.sample_no,
        category=target.category,
        oe_norm=target.oe_norm,
        run_id=run_id,
        status=status,
        prom_reported_total=None,
        retrieved_count=0,
        persisted_count=0,
        request_count=0,
        coverage_ratio=None,
        coverage_reason=None,
        duration_ms=duration_ms,
        baseline_after_filter=target.baseline_after_filter,
        counts={cohort: 0 for cohort in COHORT_ORDER},
    )


def _histogram(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


__all__ = [
    "BLOCKING_BODY_MARKERS",
    "BatchIdentity",
    "BatchProgress",
    "CaptureAssessment",
    "COHORT_BASELINE",
    "COHORT_IDENTITY",
    "COHORT_ORDER",
    "COHORT_PLAN_S",
    "COVERAGE_CHECKPOINT_SCHEMA_VERSION",
    "COVERAGE_REPORT_SCHEMA_VERSION",
    "COVERAGE_TARGETS_SCHEMA_VERSION",
    "CatalogDiscoveryError",
    "CoverageMeasurementError",
    "CoverageMetrics",
    "CoverageReport",
    "CoverageTarget",
    "CoverageTargetSet",
    "MeasurementCheckpoint",
    "OfferFacts",
    "RequestTelemetry",
    "TargetCoverage",
    "TargetOutcome",
    "assess_capture_body",
    "build_batch_identity",
    "build_coverage_report",
    "cohort_counts",
    "cohort_membership",
    "coverage_metrics",
    "load_coverage_targets",
    "offer_facts",
    "parsed_product_count",
    "run_coverage_batch",
    "scan_blocking_markers",
    "summarize_request_telemetry",
]
