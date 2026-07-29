"""Split candidate outcomes into identity rejection and comparability usage.

Revision ID: 20260728_0024
Revises: 20260728_0023
Create Date: 2026-07-28

``COMPARABLE``/``REVIEW``/``SKIP`` described how confident the gate chain felt.
The replacement describes what the candidate may be used for, which is the
question the customer and the pricing basis actually ask:

    COMPARABLE -> PRICING_EVIDENCE   same part, level known and convertible
    REVIEW     -> REFERENCE_ONLY     same part, shown but not priced against
    SKIP       -> REJECTED           different part, second-hand, or our own

The mapping is one-to-one, so historical rows keep their meaning.  The counter
columns are renamed with the same mapping; ``rejected_count`` on the run stays
untouched because it counts parser rejects, not candidates.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_0024"
down_revision: str | None = "20260728_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STATUS_MAP = (
    ("COMPARABLE", "PRICING_EVIDENCE"),
    ("REVIEW", "REFERENCE_ONLY"),
    ("SKIP", "REJECTED"),
)

_COUNTERS = (
    ("comparable_count", "pricing_evidence_count"),
    ("review_count", "reference_only_count"),
    ("skipped_count", "rejected_candidate_count"),
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_catalog_discovery_offer_selection_status",
        "catalog_discovery_offers",
        type_="check",
    )
    op.alter_column(
        "catalog_discovery_offers",
        "selection_status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=24),
        existing_nullable=False,
        server_default=None,
    )
    for old, new in _STATUS_MAP:
        op.execute(
            sa.text(
                "UPDATE catalog_discovery_offers SET selection_status = :new "
                "WHERE selection_status = :old"
            ).bindparams(new=new, old=old)
        )
    op.alter_column(
        "catalog_discovery_offers",
        "selection_status",
        existing_type=sa.String(length=24),
        server_default="REFERENCE_ONLY",
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_catalog_discovery_offer_selection_status",
        "catalog_discovery_offers",
        "selection_status IN ('PRICING_EVIDENCE', 'REFERENCE_ONLY', 'REJECTED')",
    )

    op.drop_constraint(
        "ck_catalog_discovery_run_counts",
        "catalog_discovery_runs",
        type_="check",
    )
    for old, new in _COUNTERS:
        op.alter_column("catalog_discovery_runs", old, new_column_name=new)
    op.create_check_constraint(
        "ck_catalog_discovery_run_counts",
        "catalog_discovery_runs",
        "request_count >= 0 AND retrieved_count >= 0 "
        "AND persisted_count >= 0 AND rejected_count >= 0 "
        "AND owned_excluded_count >= 0 AND pricing_evidence_count >= 0 "
        "AND reference_only_count >= 0 AND rejected_candidate_count >= 0 "
        "AND unfetched_count >= 0 AND search_page_limit > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_catalog_discovery_run_counts",
        "catalog_discovery_runs",
        type_="check",
    )
    for old, new in _COUNTERS:
        op.alter_column("catalog_discovery_runs", new, new_column_name=old)
    op.create_check_constraint(
        "ck_catalog_discovery_run_counts",
        "catalog_discovery_runs",
        "request_count >= 0 AND retrieved_count >= 0 "
        "AND persisted_count >= 0 AND rejected_count >= 0 "
        "AND owned_excluded_count >= 0 AND comparable_count >= 0 "
        "AND review_count >= 0 AND skipped_count >= 0 "
        "AND unfetched_count >= 0 AND search_page_limit > 0",
    )

    op.drop_constraint(
        "ck_catalog_discovery_offer_selection_status",
        "catalog_discovery_offers",
        type_="check",
    )
    op.alter_column(
        "catalog_discovery_offers",
        "selection_status",
        existing_type=sa.String(length=24),
        server_default=None,
        existing_nullable=False,
    )
    for old, new in _STATUS_MAP:
        op.execute(
            sa.text(
                "UPDATE catalog_discovery_offers SET selection_status = :old "
                "WHERE selection_status = :new"
            ).bindparams(new=new, old=old)
        )
    op.alter_column(
        "catalog_discovery_offers",
        "selection_status",
        existing_type=sa.String(length=24),
        type_=sa.String(length=16),
        server_default="REVIEW",
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_catalog_discovery_offer_selection_status",
        "catalog_discovery_offers",
        "selection_status IN ('COMPARABLE', 'REVIEW', 'SKIP')",
    )
