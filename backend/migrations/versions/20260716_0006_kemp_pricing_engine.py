"""Complete the reproducible KEMP-normalized pricing pipeline.

Revision ID: 20260716_0006
Revises: 20260716_0005
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0006"
down_revision: str | None = "20260716_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SALES_COLUMNS = (
    ("units_sold_30d", sa.Numeric(14, 3)),
    ("units_sold_60d", sa.Numeric(14, 3)),
    ("units_sold_90d", sa.Numeric(14, 3)),
    ("days_since_last_sale", sa.Numeric(14, 2)),
    ("historical_monthly_units", sa.Numeric(14, 3)),
    ("views_30d", sa.Numeric(14, 3)),
    ("conversion_rate_proxy", sa.Numeric(8, 6)),
)


def upgrade() -> None:
    for table in ("catalog_items", "catalog_item_overrides"):
        for name, column_type in _SALES_COLUMNS:
            op.add_column(table, sa.Column(name, column_type, nullable=True))
        op.create_check_constraint(
            f"ck_{table}_sales_nonnegative",
            table,
            "(units_sold_30d IS NULL OR units_sold_30d >= 0) AND "
            "(units_sold_60d IS NULL OR units_sold_60d >= 0) AND "
            "(units_sold_90d IS NULL OR units_sold_90d >= 0) AND "
            "(days_since_last_sale IS NULL OR days_since_last_sale >= 0) AND "
            "(historical_monthly_units IS NULL OR historical_monthly_units >= 0) AND "
            "(views_30d IS NULL OR views_30d >= 0) AND "
            "(conversion_rate_proxy IS NULL OR "
            "(conversion_rate_proxy >= 0 AND conversion_rate_proxy <= 1))",
        )

    op.add_column(
        "catalog_item_overrides",
        sa.Column(
            "below_cost_warning_confirmed",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE catalog_item_overrides SET below_cost_warning_confirmed = true "
        "WHERE allow_below_cost = true"
    )
    op.create_check_constraint(
        "ck_catalog_item_override_below_cost_authorization",
        "catalog_item_overrides",
        "NOT allow_below_cost OR (stock_status = 'dead_stock' AND "
        "below_cost_floor IS NOT NULL AND below_cost_warning_confirmed)",
    )

    op.drop_constraint("ck_pricing_run_status", "pricing_runs", type_="check")
    op.create_check_constraint(
        "ck_pricing_run_status",
        "pricing_runs",
        "status IN ('queued', 'running', 'collecting', 'classifying', "
        "'calibrating', 'calculating', 'completed', 'partial', 'failed', "
        "'cancelled')",
    )
    op.add_column(
        "pricing_runs",
        sa.Column(
            "classifier_version",
            sa.String(80),
            server_default="brand-tier-v1",
            nullable=False,
        ),
    )
    op.add_column(
        "pricing_runs",
        sa.Column(
            "coefficient_model",
            sa.String(32),
            server_default="shrinkage",
            nullable=False,
        ),
    )
    op.add_column("pricing_runs", sa.Column("coefficient_version", sa.String(160)))
    op.add_column("pricing_runs", sa.Column("calibration_dataset_hash", sa.String(64)))
    op.add_column(
        "pricing_runs", sa.Column("calibration_started_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "pricing_runs",
        sa.Column("calibration_completed_at", sa.DateTime(timezone=True)),
    )

    op.add_column(
        "market_observations",
        sa.Column(
            "source_confidence",
            sa.Numeric(5, 4),
            server_default="1",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_market_observation_source_confidence",
        "market_observations",
        "source_confidence >= 0 AND source_confidence <= 1",
    )

    op.create_table(
        "tier_calibration_pairs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_id", sa.Uuid(), nullable=False),
        sa.Column("oe_norm", sa.String(255), nullable=False),
        sa.Column("category", sa.String(255), nullable=False),
        sa.Column("tier", sa.String(24), nullable=False),
        sa.Column("tier_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("reference_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("quality_weight", sa.Numeric(8, 6), nullable=False),
        sa.Column("tier_observation_ids", sa.JSON(), nullable=False),
        sa.Column("reference_observation_ids", sa.JSON(), nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("tier_price > 0", name="ck_tier_calibration_tier_price"),
        sa.CheckConstraint(
            "reference_price > 0", name="ck_tier_calibration_reference_price"
        ),
        sa.CheckConstraint(
            "quality_weight > 0 AND quality_weight <= 1",
            name="ck_tier_calibration_quality_weight",
        ),
        sa.CheckConstraint(
            "tier IN ('oem', 'oes', 'aftermarket_a', 'aftermarket_b')",
            name="ck_tier_calibration_tier",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_id"], ["pricing_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pricing_run_id",
            "category",
            "tier",
            "oe_norm",
            name="uq_tier_calibration_pair_run_unit",
        ),
    )
    op.create_index(
        "ix_tier_calibration_pairs_workspace_id",
        "tier_calibration_pairs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_tier_calibration_pairs_pricing_run_id",
        "tier_calibration_pairs",
        ["pricing_run_id"],
    )
    op.create_index(
        "ix_tier_calibration_pairs_dataset_hash",
        "tier_calibration_pairs",
        ["dataset_hash"],
    )
    op.create_index(
        "ix_tier_calibration_run_category_tier",
        "tier_calibration_pairs",
        ["pricing_run_id", "category", "tier"],
    )

    op.drop_constraint(
        "uq_tier_coefficient_version", "tier_coefficients", type_="unique"
    )
    op.add_column(
        "tier_coefficients", sa.Column("pricing_run_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "tier_coefficients",
        sa.Column(
            "coefficient_version", sa.String(160), server_default="", nullable=False
        ),
    )
    op.add_column(
        "tier_coefficients",
        sa.Column(
            "policy_version",
            sa.String(80),
            server_default="pricing-v1",
            nullable=False,
        ),
    )
    op.add_column(
        "tier_coefficients",
        sa.Column(
            "validation_reasons",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "tier_coefficients",
        sa.Column("is_selected", sa.Boolean(), server_default="false", nullable=False),
    )
    op.execute(
        "UPDATE tier_coefficients SET coefficient_version = method_version "
        "WHERE coefficient_version = ''"
    )
    op.create_foreign_key(
        "fk_tier_coefficients_pricing_run_id",
        "tier_coefficients",
        "pricing_runs",
        ["pricing_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_tier_coefficients_pricing_run_id",
        "tier_coefficients",
        ["pricing_run_id"],
    )
    op.create_index(
        "uq_tier_coefficient_run_scope_version",
        "tier_coefficients",
        [
            "workspace_id",
            "pricing_run_id",
            "category",
            "tier",
            "model",
            "coefficient_version",
        ],
        unique=True,
        postgresql_where=sa.text("pricing_run_id IS NOT NULL"),
    )
    op.create_index(
        "uq_tier_coefficient_global_scope_version",
        "tier_coefficients",
        [
            "workspace_id",
            "category",
            "tier",
            "model",
            "coefficient_version",
        ],
        unique=True,
        postgresql_where=sa.text("pricing_run_id IS NULL"),
    )
    op.create_check_constraint(
        "ck_tier_coefficient_effective_sample_nonnegative",
        "tier_coefficients",
        "effective_sample_size >= 0",
    )
    op.create_check_constraint(
        "ck_tier_coefficient_confidence",
        "tier_coefficients",
        "confidence >= 0 AND confidence <= 1",
    )

    recommendation_columns = (
        sa.Column("catalog_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column(
            "raw_competitor_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "unique_seller_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "clean_competitor_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "outlier_method", sa.String(24), server_default="none", nullable=False
        ),
        sa.Column("outlier_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sensitivity", sa.Numeric(12, 8)),
        sa.Column(
            "action_gates_passed", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("cost_floor", sa.Numeric(14, 2)),
        sa.Column("cost_basis_inventory_value", sa.Numeric(20, 6)),
        sa.Column(
            "parser_version", sa.String(80), server_default="unknown", nullable=False
        ),
        sa.Column(
            "classifier_version",
            sa.String(80),
            server_default="brand-tier-v1",
            nullable=False,
        ),
        sa.Column("coefficient_version", sa.String(160)),
        sa.Column("calibration_dataset_hash", sa.String(64)),
        sa.Column("currency", sa.String(3), server_default="UAH", nullable=False),
        sa.Column("price_tick", sa.Numeric(14, 4), server_default="1", nullable=False),
        sa.Column(
            "price_tick_version",
            sa.String(80),
            server_default="uah-integer-v1",
            nullable=False,
        ),
    )
    for column in recommendation_columns:
        op.add_column("pricing_recommendations", column)
    op.execute(
        "UPDATE pricing_recommendations AS recommendation SET "
        "catalog_snapshot_id = run.import_batch_id, "
        "raw_competitor_count = recommendation.competitor_count, "
        "unique_seller_count = recommendation.competitor_count, "
        "clean_competitor_count = recommendation.competitor_count, "
        "action_gates_passed = recommendation.action IN ('RAISE', 'LOWER'), "
        "parser_version = run.parser_version "
        "FROM pricing_runs AS run WHERE run.id = recommendation.pricing_run_id"
    )
    op.alter_column("pricing_recommendations", "catalog_snapshot_id", nullable=False)
    op.create_foreign_key(
        "fk_pricing_recommendation_catalog_snapshot",
        "pricing_recommendations",
        "catalog_import_batches",
        ["catalog_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_pricing_recommendations_catalog_snapshot_id",
        "pricing_recommendations",
        ["catalog_snapshot_id"],
    )
    op.create_check_constraint(
        "ck_pricing_recommendation_counts_nonnegative",
        "pricing_recommendations",
        "raw_competitor_count >= 0 AND unique_seller_count >= 0 AND "
        "clean_competitor_count >= 0 AND outlier_count >= 0",
    )
    op.create_check_constraint(
        "ck_pricing_recommendation_action_gate",
        "pricing_recommendations",
        "action NOT IN ('RAISE', 'LOWER') OR "
        "(action_gates_passed AND recommended_price IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_pricing_recommendation_direction",
        "pricing_recommendations",
        "(action <> 'RAISE' OR recommended_price > current_price) AND "
        "(action <> 'LOWER' OR recommended_price < current_price)",
    )

    op.add_column(
        "recommendation_decisions",
        sa.Column("recommended_price_snapshot", sa.Numeric(14, 2)),
    )
    op.add_column(
        "recommendation_decisions", sa.Column("approved_floor", sa.Numeric(14, 2))
    )
    op.add_column(
        "recommendation_decisions",
        sa.Column(
            "warning_confirmed", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column(
        "recommendation_decisions",
        sa.Column("warning_confirmed_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "recommendation_decisions",
        sa.Column(
            "context_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE recommendation_decisions "
        "SET warning_confirmed = true, warning_confirmed_at = decided_at "
        "WHERE allow_below_cost = true"
    )
    op.create_check_constraint(
        "ck_recommendation_decision_below_cost_confirmation",
        "recommendation_decisions",
        "NOT allow_below_cost OR (warning_confirmed AND warning_confirmed_at IS NOT NULL)",
    )

    for table in ("tier_calibration_pairs", "tier_coefficients"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION marko_reject_append_only_mutation()"
        )


def downgrade() -> None:
    for table in ("tier_coefficients", "tier_calibration_pairs"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")

    op.drop_constraint(
        "ck_recommendation_decision_below_cost_confirmation",
        "recommendation_decisions",
        type_="check",
    )
    for column in (
        "context_snapshot",
        "warning_confirmed_at",
        "warning_confirmed",
        "approved_floor",
        "recommended_price_snapshot",
    ):
        op.drop_column("recommendation_decisions", column)

    op.drop_constraint(
        "ck_pricing_recommendation_direction",
        "pricing_recommendations",
        type_="check",
    )
    op.drop_constraint(
        "ck_pricing_recommendation_action_gate",
        "pricing_recommendations",
        type_="check",
    )
    op.drop_constraint(
        "ck_pricing_recommendation_counts_nonnegative",
        "pricing_recommendations",
        type_="check",
    )
    op.drop_index(
        "ix_pricing_recommendations_catalog_snapshot_id",
        table_name="pricing_recommendations",
    )
    op.drop_constraint(
        "fk_pricing_recommendation_catalog_snapshot",
        "pricing_recommendations",
        type_="foreignkey",
    )
    for column in (
        "price_tick_version",
        "price_tick",
        "currency",
        "calibration_dataset_hash",
        "coefficient_version",
        "classifier_version",
        "parser_version",
        "cost_basis_inventory_value",
        "cost_floor",
        "action_gates_passed",
        "sensitivity",
        "outlier_count",
        "outlier_method",
        "clean_competitor_count",
        "unique_seller_count",
        "raw_competitor_count",
        "catalog_snapshot_id",
    ):
        op.drop_column("pricing_recommendations", column)

    op.drop_index(
        "uq_tier_coefficient_global_scope_version", table_name="tier_coefficients"
    )
    op.drop_index(
        "uq_tier_coefficient_run_scope_version", table_name="tier_coefficients"
    )
    op.drop_constraint(
        "ck_tier_coefficient_confidence", "tier_coefficients", type_="check"
    )
    op.drop_constraint(
        "ck_tier_coefficient_effective_sample_nonnegative",
        "tier_coefficients",
        type_="check",
    )
    op.drop_index("ix_tier_coefficients_pricing_run_id", table_name="tier_coefficients")
    op.drop_constraint(
        "fk_tier_coefficients_pricing_run_id",
        "tier_coefficients",
        type_="foreignkey",
    )
    for column in (
        "is_selected",
        "validation_reasons",
        "policy_version",
        "coefficient_version",
        "pricing_run_id",
    ):
        op.drop_column("tier_coefficients", column)
    op.create_unique_constraint(
        "uq_tier_coefficient_version",
        "tier_coefficients",
        ["workspace_id", "category", "tier", "method_version"],
    )

    op.drop_table("tier_calibration_pairs")

    op.drop_constraint(
        "ck_market_observation_source_confidence",
        "market_observations",
        type_="check",
    )
    op.drop_column("market_observations", "source_confidence")

    for column in (
        "calibration_completed_at",
        "calibration_started_at",
        "calibration_dataset_hash",
        "coefficient_version",
        "coefficient_model",
        "classifier_version",
    ):
        op.drop_column("pricing_runs", column)
    op.drop_constraint("ck_pricing_run_status", "pricing_runs", type_="check")
    op.create_check_constraint(
        "ck_pricing_run_status",
        "pricing_runs",
        "status IN ('queued', 'running', 'collecting', 'classifying', "
        "'calculating', 'completed', 'partial', 'failed', 'cancelled')",
    )

    op.drop_constraint(
        "ck_catalog_item_override_below_cost_authorization",
        "catalog_item_overrides",
        type_="check",
    )
    op.drop_column("catalog_item_overrides", "below_cost_warning_confirmed")
    for table in ("catalog_item_overrides", "catalog_items"):
        op.drop_constraint(f"ck_{table}_sales_nonnegative", table, type_="check")
        for name, _ in reversed(_SALES_COLUMNS):
            op.drop_column(table, name)
