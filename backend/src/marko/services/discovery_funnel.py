"""Workspace-scoped discovery funnel and gate-ceiling aggregation.

The persisted discovery rows are the source of truth.  This module deliberately
does not rerun the frozen Prom parser and does not infer any missing owner
policy: it only explains how already collected candidates moved through the
configured gates.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    CatalogDiscoveryOffer,
    CatalogDiscoveryRun,
)
from metis.pricing import CANDIDATE_GATE_ORDER


def _ratio(numerator: int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    return str(
        (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.000001"))
    )


@dataclass(frozen=True, slots=True)
class DiscoveryFunnelSnapshot:
    generated_at: datetime
    sampled_runs: int
    run_status_counts: dict[str, int]
    total_candidates: int
    status_counts: dict[str, int]
    selection_reasons: dict[str, int]
    coverage: dict[str, int | str | None]
    gates: dict[str, dict[str, int | str | None]]
    categories: tuple[dict[str, Any], ...]

    def as_dict(self, *, correlation_id: str | None = None) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "correlation_id": correlation_id,
            "sampled_runs": self.sampled_runs,
            "run_status_counts": self.run_status_counts,
            "total_candidates": self.total_candidates,
            "status_counts": self.status_counts,
            "selection_reasons": self.selection_reasons,
            "coverage": self.coverage,
            "gates": self.gates,
            "categories": list(self.categories),
        }


def _gate_metrics(
    offers: Iterable[CatalogDiscoveryOffer | Any],
) -> dict[str, dict[str, int | str | None]]:
    materialized = list(offers)
    total = len(materialized)
    current_evidence = sum(
        str(getattr(offer, "selection_status", "")) == "PRICING_EVIDENCE"
        for offer in materialized
    )
    counts = {gate: {"reached": 0, "terminal": 0} for gate in CANDIDATE_GATE_ORDER}
    for offer in materialized:
        passed = set(getattr(offer, "passed_gates", None) or ())
        details = getattr(offer, "selection_details", None)
        stopped = details.get("stopped_gate") if isinstance(details, Mapping) else None
        for gate in CANDIDATE_GATE_ORDER:
            if gate in passed or stopped == gate:
                counts[gate]["reached"] += 1
            if stopped == gate:
                counts[gate]["terminal"] += 1

    result: dict[str, dict[str, int | str | None]] = {}
    for gate in CANDIDATE_GATE_ORDER:
        reached = counts[gate]["reached"]
        terminal = counts[gate]["terminal"]
        survived = max(0, reached - terminal)
        unlock_upper_bound = current_evidence + terminal
        result[gate] = {
            "reached": reached,
            "terminal": terminal,
            "survived": survived,
            "conditional_pass_rate": _ratio(survived, reached),
            "conditional_terminal_rate": _ratio(terminal, reached),
            # If every later gate passed, no more than this share of the
            # original candidates could remain pricing evidence.
            "survival_ceiling_ratio": _ratio(survived, total),
            # The evaluator short-circuits, so candidates stopped here have
            # no persisted later-gate results. Evidence + terminal is the
            # honest single-gate counterfactual upper bound.
            "single_gate_unlock_upper_bound": unlock_upper_bound,
            "single_gate_unlock_upper_bound_ratio": _ratio(
                unlock_upper_bound, total
            ),
            "counterfactual_ceiling_method": "SHORT_CIRCUIT_UPPER_BOUND",
        }
    return result


def aggregate_discovery_funnel(
    runs: Sequence[CatalogDiscoveryRun | Any],
    offers_by_run: Mapping[UUID, Sequence[CatalogDiscoveryOffer | Any]],
    *,
    generated_at: datetime | None = None,
    category_limit: int = 50,
) -> DiscoveryFunnelSnapshot:
    """Build a deterministic snapshot from persisted runs and offers."""

    run_status_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    selection_reasons: Counter[str] = Counter()
    category_offers: defaultdict[str, list[Any]] = defaultdict(list)
    category_runs: Counter[str] = Counter()
    all_offers: list[Any] = []
    reported_total = 0
    reported_known_runs = 0
    retrieved_count = 0
    persisted_count = 0
    rejected_count = 0
    owned_excluded_count = 0
    unfetched_count = 0

    for run in runs:
        run_status_counts[str(run.status)] += 1
        category = (getattr(run, "reference_category", None) or "UNKNOWN").strip()
        category_runs[category] += 1
        reported = getattr(run, "prom_reported_total", None)
        if reported is not None:
            reported_total += int(reported)
            reported_known_runs += 1
        retrieved_count += int(getattr(run, "retrieved_count", 0) or 0)
        persisted_count += int(getattr(run, "persisted_count", 0) or 0)
        rejected_count += int(getattr(run, "rejected_count", 0) or 0)
        owned_excluded_count += int(getattr(run, "owned_excluded_count", 0) or 0)
        unfetched_count += int(getattr(run, "unfetched_count", 0) or 0)
        run_offers = list(offers_by_run.get(run.id, ()))
        all_offers.extend(run_offers)
        category_offers[category].extend(run_offers)

    for offer in all_offers:
        status_counts[str(offer.selection_status)] += 1
        selection_reasons[str(offer.selection_reason)] += 1

    ranked_categories = sorted(
        category_offers,
        key=lambda value: (
            -len(category_offers[value]),
            value.casefold(),
        ),
    )[: max(1, category_limit)]
    categories = tuple(
        {
            "category": category,
            "runs": category_runs[category],
            "total_candidates": len(category_offers[category]),
            "status_counts": dict(
                sorted(
                    Counter(
                        str(offer.selection_status)
                        for offer in category_offers[category]
                    ).items()
                )
            ),
            "gates": _gate_metrics(category_offers[category]),
        }
        for category in ranked_categories
    )
    return DiscoveryFunnelSnapshot(
        generated_at=generated_at or datetime.now(UTC),
        sampled_runs=len(runs),
        run_status_counts=dict(sorted(run_status_counts.items())),
        total_candidates=len(all_offers),
        status_counts=dict(sorted(status_counts.items())),
        selection_reasons=dict(
            sorted(selection_reasons.items(), key=lambda item: (-item[1], item[0]))
        ),
        coverage={
            "reported_total": reported_total if reported_known_runs else None,
            "reported_known_runs": reported_known_runs,
            "retrieved_count": retrieved_count,
            "persisted_count": persisted_count,
            "rejected_count": rejected_count,
            "owned_excluded_count": owned_excluded_count,
            "unfetched_count": unfetched_count,
            "retrieval_coverage_ratio": (
                _ratio(retrieved_count, reported_total)
                if reported_known_runs
                else None
            ),
        },
        gates=_gate_metrics(all_offers),
        categories=categories,
    )


async def load_discovery_funnel(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    run_limit: int = 400,
    category_limit: int = 50,
) -> DiscoveryFunnelSnapshot:
    """Load and aggregate the latest terminal discovery runs in a workspace."""

    runs = list(
        (
            await session.scalars(
                select(CatalogDiscoveryRun)
                .where(
                    CatalogDiscoveryRun.workspace_id == workspace_id,
                    CatalogDiscoveryRun.status.in_(("completed", "failed")),
                )
                .order_by(
                    CatalogDiscoveryRun.created_at.desc(),
                    CatalogDiscoveryRun.id.desc(),
                )
                .limit(run_limit)
            )
        ).all()
    )
    offers_by_run: defaultdict[UUID, list[CatalogDiscoveryOffer]] = defaultdict(list)
    if runs:
        offers = list(
            (
                await session.scalars(
                    select(CatalogDiscoveryOffer)
                    .where(
                        CatalogDiscoveryOffer.discovery_run_id.in_(
                            tuple(run.id for run in runs)
                        )
                    )
                    .order_by(
                        CatalogDiscoveryOffer.discovery_run_id,
                        CatalogDiscoveryOffer.raw_offer_index,
                    )
                )
            ).all()
        )
        for offer in offers:
            offers_by_run[offer.discovery_run_id].append(offer)
    return aggregate_discovery_funnel(
        runs,
        offers_by_run,
        category_limit=category_limit,
    )


def render_discovery_funnel_prometheus(
    snapshot: DiscoveryFunnelSnapshot,
) -> str:
    """Render low-cardinality, deployment-safe funnel gauges."""

    lines = [
        "# HELP marko_discovery_funnel_snapshot_available Whether a discovery funnel snapshot exists.",
        "# TYPE marko_discovery_funnel_snapshot_available gauge",
        f"marko_discovery_funnel_snapshot_available {int(snapshot.sampled_runs > 0)}",
        "# HELP marko_discovery_sampled_runs Number of terminal discovery runs in the snapshot.",
        "# TYPE marko_discovery_sampled_runs gauge",
        f"marko_discovery_sampled_runs {snapshot.sampled_runs}",
        "# HELP marko_discovery_candidates_count Candidate count by terminal selection status.",
        "# TYPE marko_discovery_candidates_count gauge",
    ]
    for status, count in sorted(snapshot.status_counts.items()):
        lines.append(f'marko_discovery_candidates_count{{status="{status}"}} {count}')
    coverage = snapshot.coverage
    lines.extend(
        (
            "# HELP marko_discovery_candidates_reported_count Source-reported candidates for runs with a known total.",
            "# TYPE marko_discovery_candidates_reported_count gauge",
            f"marko_discovery_candidates_reported_count {coverage['reported_total'] or 0}",
            "# HELP marko_discovery_candidates_retrieved_count Retrieved candidates in the snapshot.",
            "# TYPE marko_discovery_candidates_retrieved_count gauge",
            f"marko_discovery_candidates_retrieved_count {coverage['retrieved_count']}",
            "# HELP marko_discovery_retrieval_coverage_ratio Retrieved divided by source-reported candidates.",
            "# TYPE marko_discovery_retrieval_coverage_ratio gauge",
            "marko_discovery_retrieval_coverage_ratio "
            f"{coverage['retrieval_coverage_ratio'] or 0}",
            "# HELP marko_discovery_gate_reached_count Candidates evaluated at a gate.",
            "# TYPE marko_discovery_gate_reached_count gauge",
            "# HELP marko_discovery_gate_terminal_count Candidates stopped at a gate.",
            "# TYPE marko_discovery_gate_terminal_count gauge",
            "# HELP marko_discovery_gate_conditional_pass_ratio Gate survivors divided by candidates reaching the gate.",
            "# TYPE marko_discovery_gate_conditional_pass_ratio gauge",
            "# HELP marko_discovery_gate_survival_ceiling_ratio Maximum final share after observed stops at this and earlier gates.",
            "# TYPE marko_discovery_gate_survival_ceiling_ratio gauge",
            "# HELP marko_discovery_gate_unlock_upper_bound_ratio Current evidence plus candidates stopped at one gate, divided by all candidates.",
            "# TYPE marko_discovery_gate_unlock_upper_bound_ratio gauge",
        )
    )
    for gate, metrics in snapshot.gates.items():
        lines.extend(
            (
                f'marko_discovery_gate_reached_count{{gate="{gate}"}} {metrics["reached"]}',
                f'marko_discovery_gate_terminal_count{{gate="{gate}"}} {metrics["terminal"]}',
                f'marko_discovery_gate_conditional_pass_ratio{{gate="{gate}"}} '
                f'{metrics["conditional_pass_rate"] or 0}',
                f'marko_discovery_gate_survival_ceiling_ratio{{gate="{gate}"}} '
                f'{metrics["survival_ceiling_ratio"] or 0}',
                f'marko_discovery_gate_unlock_upper_bound_ratio{{gate="{gate}"}} '
                f'{metrics["single_gate_unlock_upper_bound_ratio"] or 0}',
            )
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "DiscoveryFunnelSnapshot",
    "aggregate_discovery_funnel",
    "load_discovery_funnel",
    "render_discovery_funnel_prometheus",
]
