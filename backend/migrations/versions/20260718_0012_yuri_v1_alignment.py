"""Add Yuri V1 evidence lanes, condition provenance, and literal deltas.

Revision ID: 20260718_0012
Revises: 20260718_0011
Create Date: 2026-07-18

Raw cost columns are deliberately unchanged: cost privacy is an unresolved
business decision and this migration must not pretend to implement encryption
or irreversibly move sensitive values.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0012"
down_revision: str | None = "20260718_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in (
        sa.Column("url_absence_reason", sa.String(100)),
        sa.Column(
            "description_available",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("condition_raw", sa.Text()),
        sa.Column(
            "condition_state",
            sa.String(32),
            server_default="UNKNOWN",
            nullable=False,
        ),
        sa.Column(
            "condition_reason_codes",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "cross_candidates",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    ):
        op.add_column("market_observations", column)
    op.execute(
        "UPDATE market_observations "
        "SET description_available = (description IS NOT NULL), "
        "url_absence_reason = CASE WHEN url = '' "
        "THEN 'LEGACY_SOURCE_URL_NOT_AVAILABLE' ELSE NULL END"
    )
    op.create_check_constraint(
        "ck_market_observation_condition_state",
        "market_observations",
        "condition_state IN ('NEW', 'USED_OR_REFURBISHED', 'CONFLICT', 'UNKNOWN')",
    )
    op.create_check_constraint(
        "ck_market_observation_description_availability",
        "market_observations",
        "(description_available AND description IS NOT NULL) OR "
        "(NOT description_available AND description IS NULL)",
    )
    op.create_check_constraint(
        "ck_market_observation_url_or_reason",
        "market_observations",
        "(url <> '' AND url_absence_reason IS NULL) OR "
        "(url = '' AND url_absence_reason IS NOT NULL)",
    )

    op.add_column(
        "observation_tier_classifications",
        sa.Column(
            "cohort_role",
            sa.String(32),
            server_default="MANUAL_REVIEW",
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE observation_tier_classifications SET cohort_role = CASE "
        "WHEN is_owned THEN 'OWNED_STORE' "
        "WHEN is_used OR tier = 'used' THEN 'USED_REJECTED' "
        "WHEN (is_kemp OR tier = 'kemp') AND is_dumping "
        "THEN 'DUMPING_DIAGNOSTIC' "
        "WHEN is_kemp OR tier = 'kemp' THEN 'KEMP_REFERENCE' "
        "WHEN tier = 'unknown' THEN 'MANUAL_REVIEW' "
        "ELSE 'TARGET_MARKET' END"
    )
    op.create_check_constraint(
        "ck_observation_cohort_role",
        "observation_tier_classifications",
        "cohort_role IN ('TARGET_MARKET', 'KEMP_REFERENCE', 'OWNED_STORE', "
        "'USED_REJECTED', 'DUMPING_DIAGNOSTIC', 'MANUAL_REVIEW', "
        "'HARD_REJECTED')",
    )

    for column in (
        sa.Column(
            "target_market_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "kemp_reference_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "owned_store_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("rejected_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("absolute_recommended_change", sa.Numeric(20, 6)),
        sa.Column("percentage_recommended_change", sa.Numeric(20, 10)),
        sa.Column(
            "kemp_reference_observation_ids",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    ):
        op.add_column("pricing_recommendations", column)
    op.execute(
        "UPDATE pricing_recommendations SET "
        "absolute_recommended_change = CASE WHEN recommended_price IS NULL "
        "THEN NULL ELSE abs(recommended_price - current_price) END, "
        "percentage_recommended_change = CASE WHEN recommended_price IS NULL "
        "THEN NULL ELSE abs(recommended_price - current_price) / current_price END"
    )
    op.create_check_constraint(
        "ck_pricing_recommendation_cohort_counts_nonnegative",
        "pricing_recommendations",
        "target_market_count >= 0 AND kemp_reference_count >= 0 AND "
        "owned_store_count >= 0 AND rejected_count >= 0",
    )
    op.create_check_constraint(
        "ck_pricing_recommendation_change_metrics",
        "pricing_recommendations",
        "(recommended_price IS NULL AND absolute_recommended_change IS NULL "
        "AND percentage_recommended_change IS NULL) OR "
        "(recommended_price IS NOT NULL AND absolute_recommended_change >= 0 "
        "AND percentage_recommended_change >= 0)",
    )
    op.create_index(
        "ix_pricing_recommendation_run_absolute_change",
        "pricing_recommendations",
        ["pricing_run_id", "absolute_recommended_change"],
    )

    op.drop_constraint(
        "ck_catalog_item_override_below_cost_authorization",
        "catalog_item_overrides",
        type_="check",
    )
    op.create_check_constraint(
        "ck_catalog_item_override_below_cost_authorization",
        "catalog_item_overrides",
        "NOT allow_below_cost OR below_cost_warning_confirmed",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_catalog_item_override_below_cost_authorization",
        "catalog_item_overrides",
        type_="check",
    )
    op.create_check_constraint(
        "ck_catalog_item_override_below_cost_authorization",
        "catalog_item_overrides",
        "NOT allow_below_cost OR (stock_status = 'dead_stock' AND "
        "below_cost_floor IS NOT NULL AND below_cost_warning_confirmed)",
    )

    op.drop_index(
        "ix_pricing_recommendation_run_absolute_change",
        table_name="pricing_recommendations",
    )
    op.drop_constraint(
        "ck_pricing_recommendation_change_metrics",
        "pricing_recommendations",
        type_="check",
    )
    op.drop_constraint(
        "ck_pricing_recommendation_cohort_counts_nonnegative",
        "pricing_recommendations",
        type_="check",
    )
    for name in (
        "kemp_reference_observation_ids",
        "percentage_recommended_change",
        "absolute_recommended_change",
        "rejected_count",
        "owned_store_count",
        "kemp_reference_count",
        "target_market_count",
    ):
        op.drop_column("pricing_recommendations", name)

    op.drop_constraint(
        "ck_observation_cohort_role",
        "observation_tier_classifications",
        type_="check",
    )
    op.drop_column("observation_tier_classifications", "cohort_role")

    for name in (
        "ck_market_observation_url_or_reason",
        "ck_market_observation_description_availability",
        "ck_market_observation_condition_state",
    ):
        op.drop_constraint(name, "market_observations", type_="check")
    for name in (
        "cross_candidates",
        "condition_reason_codes",
        "condition_state",
        "condition_raw",
        "description_available",
        "url_absence_reason",
    ):
        op.drop_column("market_observations", name)
