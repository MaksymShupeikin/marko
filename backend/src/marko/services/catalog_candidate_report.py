"""Operational report for one persisted catalog candidate-selection run."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    CatalogDiscoveryOffer,
    CatalogDiscoveryRun,
    CrossLink,
)
from metis.pricing import CANDIDATE_GATE_ORDER


class CandidateReportError(RuntimeError):
    """Raised when a requested deterministic run cannot be reported."""


@dataclass(frozen=True, slots=True)
class CandidateSelectionReport:
    run_id: UUID
    query: str
    histogram: dict[str, int]
    pricing_evidence_count: int
    reference_only_count: int
    rejected_candidate_count: int
    prom_reported_total: int | None
    retrieved_count: int
    persisted_count: int
    rejected_count: int
    owned_excluded_count: int
    search_pages_fetched: int
    search_page_limit: int
    unfetched_count: int
    coverage_ratio: Decimal | None
    coverage_reason: str | None
    method_version: str | None
    config_sha256: str | None
    brand_rules_dataset_id: str | None
    applicability_unknown_count: int = 0
    applicability_unknown_rate: Decimal | None = None
    gate_metrics: dict[str, dict[str, int | str | None]] = field(default_factory=dict)
    cross_link_status_counts: dict[str, int] = field(default_factory=dict)
    cross_link_confirmed_share: Decimal | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": str(self.run_id),
            "query": self.query,
            "histogram": self.histogram,
            "status_counts": {
                "PRICING_EVIDENCE": self.pricing_evidence_count,
                "REFERENCE_ONLY": self.reference_only_count,
                "REJECTED": self.rejected_candidate_count,
            },
            "coverage": {
                "prom_reported_total": self.prom_reported_total,
                "retrieved_count": self.retrieved_count,
                "persisted_count": self.persisted_count,
                "rejected_count": self.rejected_count,
                "owned_excluded_count": self.owned_excluded_count,
                "search_pages_fetched": self.search_pages_fetched,
                "search_page_limit": self.search_page_limit,
                "unfetched_count": self.unfetched_count,
                "coverage_ratio": (
                    str(self.coverage_ratio)
                    if self.coverage_ratio is not None
                    else None
                ),
                "coverage_reason": self.coverage_reason,
            },
            "method": {
                "version": self.method_version,
                "config_sha256": self.config_sha256,
                "brand_rules_dataset_id": self.brand_rules_dataset_id,
            },
            "applicability": {
                "unknown_count": self.applicability_unknown_count,
                "unknown_rate": (
                    str(self.applicability_unknown_rate)
                    if self.applicability_unknown_rate is not None
                    else None
                ),
            },
            "gate_metrics": self.gate_metrics,
            "cross_links": {
                "status_counts": self.cross_link_status_counts,
                "confirmed_share": (
                    str(self.cross_link_confirmed_share)
                    if self.cross_link_confirmed_share is not None
                    else None
                ),
            },
        }


async def load_candidate_selection_report(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    run_id: UUID | None = None,
    query: str | None = None,
) -> CandidateSelectionReport:
    if run_id is None and not (query or "").strip():
        raise CandidateReportError("run_id or query is required")
    statement = select(CatalogDiscoveryRun).where(
        CatalogDiscoveryRun.workspace_id == workspace_id,
        CatalogDiscoveryRun.status == "completed",
    )
    if run_id is not None:
        statement = statement.where(CatalogDiscoveryRun.id == run_id)
    else:
        statement = statement.where(
            CatalogDiscoveryRun.query == (query or "").strip().upper()
        )
    run = await session.scalar(
        statement.order_by(
            CatalogDiscoveryRun.completed_at.desc(),
            CatalogDiscoveryRun.id.desc(),
        ).limit(1)
    )
    if run is None:
        raise CandidateReportError("completed catalog discovery run not found")
    offers = list(
        (
            await session.scalars(
                select(CatalogDiscoveryOffer)
                .where(CatalogDiscoveryOffer.discovery_run_id == run.id)
                .order_by(CatalogDiscoveryOffer.raw_offer_index)
            )
        ).all()
    )
    applicability_unknown_count = sum(
        "APPLICABILITY_UNKNOWN" in (offer.selection_flags or []) for offer in offers
    )
    applicability_unknown_rate = (
        (Decimal(applicability_unknown_count) / Decimal(len(offers))).quantize(
            Decimal("0.000001")
        )
        if offers
        else None
    )
    cross_link_status_counts = {
        status: 0 for status in ("CONFIRMED", "REVIEW", "REJECTED", "UNKNOWN")
    }
    cross_rows = (
        await session.execute(
            select(CrossLink.validation_status, func.count(CrossLink.id))
            .where(CrossLink.workspace_id == run.workspace_id)
            .group_by(CrossLink.validation_status)
        )
    ).all()
    for status, count in cross_rows:
        cross_link_status_counts[str(status)] = int(count)
    cross_link_total = sum(cross_link_status_counts.values())
    cross_link_confirmed_share = (
        (
            Decimal(cross_link_status_counts["CONFIRMED"]) / Decimal(cross_link_total)
        ).quantize(Decimal("0.000001"))
        if cross_link_total
        else None
    )
    return CandidateSelectionReport(
        run_id=run.id,
        query=run.query,
        histogram=dict(run.selection_histogram or {}),
        pricing_evidence_count=run.pricing_evidence_count,
        reference_only_count=run.reference_only_count,
        rejected_candidate_count=run.rejected_candidate_count,
        prom_reported_total=run.prom_reported_total,
        retrieved_count=run.retrieved_count,
        persisted_count=run.persisted_count,
        rejected_count=run.rejected_count,
        owned_excluded_count=run.owned_excluded_count,
        search_pages_fetched=run.request_count,
        search_page_limit=run.search_page_limit,
        unfetched_count=run.unfetched_count,
        coverage_ratio=run.coverage_ratio,
        coverage_reason=run.coverage_reason,
        method_version=run.selection_method_version,
        config_sha256=run.selection_config_sha256,
        brand_rules_dataset_id=run.brand_rules_dataset_id,
        applicability_unknown_count=applicability_unknown_count,
        applicability_unknown_rate=applicability_unknown_rate,
        gate_metrics=_candidate_gate_metrics(offers),
        cross_link_status_counts=cross_link_status_counts,
        cross_link_confirmed_share=cross_link_confirmed_share,
    )


def format_candidate_selection_report(report: CandidateSelectionReport) -> str:
    rows = ["ПРИЧИНА".ljust(40) + "КОЛ-ВО"]
    rows.append("-" * 48)
    for reason, count in report.histogram.items():
        rows.append(reason.ljust(40) + str(count))
    rows.extend(
        (
            "",
            f"Run: {report.run_id}",
            f"Query: {report.query}",
            (
                "Статусы: "
                f"PRICING_EVIDENCE={report.pricing_evidence_count}, "
                f"REFERENCE_ONLY={report.reference_only_count}, "
                f"REJECTED={report.rejected_candidate_count}"
            ),
            (
                "Покрытие: "
                f"{report.retrieved_count}/{report.prom_reported_total or 'UNKNOWN'} "
                f"(не загружено {report.unfetched_count}); "
                f"страниц {report.search_pages_fetched}/"
                f"{report.search_page_limit}; "
                f"причина={report.coverage_reason or 'UNKNOWN'}"
            ),
            (
                "Applicability UNKNOWN: "
                f"{report.applicability_unknown_count}/"
                f"{report.persisted_count} "
                f"({report.applicability_unknown_rate or Decimal('0')})"
            ),
            (
                "CrossLink: "
                + ", ".join(
                    f"{status}={count}"
                    for status, count in report.cross_link_status_counts.items()
                )
                + "; confirmed_share="
                + (
                    str(report.cross_link_confirmed_share)
                    if report.cross_link_confirmed_share is not None
                    else "UNDEFINED"
                )
            ),
            "",
            "УСЛОВНАЯ СЕЛЕКТИВНОСТЬ ГЕЙТОВ",
        )
    )
    for gate, metrics in report.gate_metrics.items():
        rows.append(
            f"{gate}: reached={metrics['reached']}, "
            f"terminal={metrics['terminal']}, "
            f"s={metrics['conditional_selectivity']}"
        )
    return "\n".join(rows)


def _candidate_gate_metrics(
    offers: Iterable[CatalogDiscoveryOffer | Any],
) -> dict[str, dict[str, int | str | None]]:
    counts = {gate: {"reached": 0, "terminal": 0} for gate in CANDIDATE_GATE_ORDER}
    for offer in offers:
        passed = set(offer.passed_gates or [])
        details = (
            offer.selection_details if isinstance(offer.selection_details, dict) else {}
        )
        stopped = details.get("stopped_gate")
        for gate in CANDIDATE_GATE_ORDER:
            if gate in passed or stopped == gate:
                counts[gate]["reached"] += 1
            if stopped == gate:
                counts[gate]["terminal"] += 1

    metrics: dict[str, dict[str, int | str | None]] = {}
    for gate in CANDIDATE_GATE_ORDER:
        reached = counts[gate]["reached"]
        terminal = counts[gate]["terminal"]
        selectivity = (
            (Decimal(terminal) / Decimal(reached)).quantize(Decimal("0.000001"))
            if reached
            else None
        )
        metrics[gate] = {
            "reached": reached,
            "terminal": terminal,
            "conditional_selectivity": (
                str(selectivity) if selectivity is not None else None
            ),
        }
    return metrics


__all__ = [
    "CandidateReportError",
    "CandidateSelectionReport",
    "_candidate_gate_metrics",
    "format_candidate_selection_report",
    "load_candidate_selection_report",
]
