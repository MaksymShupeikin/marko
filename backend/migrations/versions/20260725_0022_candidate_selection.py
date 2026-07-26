"""Persist deterministic verdicts for catalog discovery candidates.

Revision ID: 20260725_0022
Revises: 20260725_0021
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0022"
down_revision: str | None = "20260725_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "catalog_discovery_runs",
        sa.Column("reference_title", sa.Text(), nullable=True),
    )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column("reference_price", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column("reference_currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column("reference_category", sa.String(length=255), nullable=True),
    )
    for name in ("comparable_count", "review_count", "skipped_count"):
        op.add_column(
            "catalog_discovery_runs",
            sa.Column(name, sa.Integer(), server_default="0", nullable=False),
        )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column(
            "search_page_limit",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column(
            "unfetched_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column("coverage_ratio", sa.Numeric(7, 6), nullable=True),
    )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column("coverage_reason", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column("selection_method_version", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column("selection_config_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column("brand_rules_dataset_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column("brand_rules_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "catalog_discovery_runs",
        sa.Column(
            "selection_histogram",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_catalog_discovery_run_reference_price",
        "catalog_discovery_runs",
        "reference_price IS NULL OR reference_price > 0",
    )
    op.create_check_constraint(
        "ck_catalog_discovery_run_coverage_ratio",
        "catalog_discovery_runs",
        "coverage_ratio IS NULL OR "
        "(coverage_ratio >= 0 AND coverage_ratio <= 1)",
    )
    op.drop_constraint(
        "ck_catalog_discovery_run_counts",
        "catalog_discovery_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_catalog_discovery_run_counts",
        "catalog_discovery_runs",
        "request_count >= 0 AND retrieved_count >= 0 "
        "AND persisted_count >= 0 AND rejected_count >= 0 "
        "AND owned_excluded_count >= 0 AND comparable_count >= 0 "
        "AND review_count >= 0 AND skipped_count >= 0 "
        "AND unfetched_count >= 0 AND search_page_limit > 0",
    )
    op.execute(
        """
        UPDATE catalog_discovery_runs
        SET
          unfetched_count = GREATEST(
            COALESCE(prom_reported_total, retrieved_count) - retrieved_count,
            0
          ),
          coverage_ratio = CASE
            WHEN prom_reported_total IS NULL OR prom_reported_total <= 0
              THEN NULL
            ELSE LEAST(
              1,
              retrieved_count::numeric / prom_reported_total::numeric
            )
          END,
          coverage_reason = CASE
            WHEN prom_reported_total > retrieved_count
              THEN 'SEARCH_PAGE_LIMIT'
            ELSE 'FULL_REPORTED_RESULT_SET'
          END
        """
    )

    op.add_column(
        "catalog_discovery_offers",
        sa.Column(
            "selection_status",
            sa.String(length=16),
            server_default="REVIEW",
            nullable=False,
        ),
    )
    op.add_column(
        "catalog_discovery_offers",
        sa.Column(
            "selection_reason",
            sa.String(length=100),
            server_default="LEGACY_UNCLASSIFIED",
            nullable=False,
        ),
    )
    op.add_column(
        "catalog_discovery_offers",
        sa.Column("passed_gates", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "catalog_discovery_offers",
        sa.Column(
            "selection_flags",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
    )
    op.add_column(
        "catalog_discovery_offers",
        sa.Column(
            "selection_details",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        "catalog_discovery_offers",
        sa.Column(
            "predicted_tier",
            sa.String(length=32),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "catalog_discovery_offers",
        sa.Column(
            "tier_confidence",
            sa.Numeric(5, 4),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_catalog_discovery_offer_selection_status",
        "catalog_discovery_offers",
        "selection_status IN ('COMPARABLE', 'REVIEW', 'SKIP')",
    )
    op.create_check_constraint(
        "ck_catalog_discovery_offer_tier_confidence",
        "catalog_discovery_offers",
        "tier_confidence >= 0 AND tier_confidence <= 1",
    )
    op.create_index(
        "ix_catalog_discovery_offers_selection_status",
        "catalog_discovery_offers",
        ["selection_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_discovery_offers_selection_status",
        table_name="catalog_discovery_offers",
    )
    op.drop_constraint(
        "ck_catalog_discovery_offer_tier_confidence",
        "catalog_discovery_offers",
        type_="check",
    )
    op.drop_constraint(
        "ck_catalog_discovery_offer_selection_status",
        "catalog_discovery_offers",
        type_="check",
    )
    for name in (
        "tier_confidence",
        "predicted_tier",
        "selection_details",
        "selection_flags",
        "passed_gates",
        "selection_reason",
        "selection_status",
    ):
        op.drop_column("catalog_discovery_offers", name)

    op.drop_constraint(
        "ck_catalog_discovery_run_counts",
        "catalog_discovery_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_catalog_discovery_run_counts",
        "catalog_discovery_runs",
        "request_count >= 0 AND retrieved_count >= 0 "
        "AND persisted_count >= 0 AND rejected_count >= 0 "
        "AND owned_excluded_count >= 0",
    )
    op.drop_constraint(
        "ck_catalog_discovery_run_coverage_ratio",
        "catalog_discovery_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_catalog_discovery_run_reference_price",
        "catalog_discovery_runs",
        type_="check",
    )
    for name in (
        "selection_histogram",
        "brand_rules_sha256",
        "brand_rules_dataset_id",
        "selection_config_sha256",
        "selection_method_version",
        "coverage_reason",
        "coverage_ratio",
        "unfetched_count",
        "search_page_limit",
        "skipped_count",
        "review_count",
        "comparable_count",
        "reference_category",
        "reference_currency",
        "reference_price",
        "reference_title",
    ):
        op.drop_column("catalog_discovery_runs", name)
