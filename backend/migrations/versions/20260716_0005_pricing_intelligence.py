"""Add catalog snapshots, market evidence, pricing runs, and recommendations.

Revision ID: 20260716_0005
Revises: 20260713_0004
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260716_0005"
down_revision: str | None = "20260713_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "catalog_import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), server_default="queued", nullable=False),
        sa.Column("column_mapping", sa.JSON(), nullable=False),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("imported_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rejected_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_log", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', 'failed')",
            name="ck_catalog_import_batch_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_import_batches_workspace_id",
        "catalog_import_batches",
        ["workspace_id"],
    )
    op.create_index(
        "ix_catalog_import_batches_content_sha256",
        "catalog_import_batches",
        ["content_sha256"],
    )
    op.create_index(
        "ix_catalog_import_batch_workspace_created",
        "catalog_import_batches",
        ["workspace_id", "created_at"],
    )

    op.create_table(
        "pricing_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "version", name="uq_pricing_policy_version"
        ),
    )
    op.create_index(
        "ix_pricing_policies_workspace_id", "pricing_policies", ["workspace_id"]
    )

    op.create_table(
        "catalog_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid()),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(255), nullable=False),
        sa.Column("oe_raw", sa.Text(), nullable=False),
        sa.Column("oe_norm", sa.String(255), nullable=False),
        sa.Column("mpn_raw", sa.Text(), server_default="", nullable=False),
        sa.Column("mpn_norm", sa.String(255), server_default="", nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.String(255), nullable=False),
        sa.Column("brand", sa.String(255)),
        sa.Column("description", sa.Text()),
        sa.Column("product_url", sa.Text()),
        sa.Column("current_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="UAH", nullable=False),
        sa.Column("is_available", sa.Boolean()),
        sa.Column(
            "stock_status", sa.String(16), server_default="unknown", nullable=False
        ),
        sa.Column("stock_qty", sa.Numeric(14, 3)),
        sa.Column("stock_age_days", sa.Numeric(14, 2)),
        sa.Column("expected_units_sold", sa.Numeric(14, 3)),
        sa.Column("cost", sa.Numeric(14, 2)),
        sa.Column(
            "manual_priority", sa.Numeric(8, 4), server_default="1", nullable=False
        ),
        sa.Column("raw_row", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("current_price > 0", name="ck_catalog_item_price_positive"),
        sa.CheckConstraint(
            "stock_status IN ('fresh', 'stale', 'dead_stock', 'unknown')",
            name="ck_catalog_item_stock_status",
        ),
        sa.CheckConstraint(
            "cost IS NULL OR cost > 0", name="ck_catalog_item_cost_positive"
        ),
        sa.CheckConstraint(
            "stock_qty IS NULL OR stock_qty >= 0",
            name="ck_catalog_item_stock_qty_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"], ["catalog_import_batches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["store_id"], ["marketplace_stores.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_batch_id", "sku", name="uq_catalog_item_batch_sku"),
    )
    for name, columns in (
        ("ix_catalog_items_workspace_id", ["workspace_id"]),
        ("ix_catalog_items_import_batch_id", ["import_batch_id"]),
        ("ix_catalog_items_store_id", ["store_id"]),
        ("ix_catalog_items_oe_norm", ["oe_norm"]),
        ("ix_catalog_items_category", ["category"]),
        ("ix_catalog_item_workspace_oe", ["workspace_id", "oe_norm"]),
        ("ix_catalog_item_workspace_category", ["workspace_id", "category"]),
    ):
        op.create_index(name, "catalog_items", columns)

    op.create_table(
        "catalog_item_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid()),
        sa.Column("stock_status", sa.String(16)),
        sa.Column("cost", sa.Numeric(14, 2)),
        sa.Column("stock_qty", sa.Numeric(14, 3)),
        sa.Column("stock_age_days", sa.Numeric(14, 2)),
        sa.Column("expected_units_sold", sa.Numeric(14, 3)),
        sa.Column("manual_priority", sa.Numeric(8, 4)),
        sa.Column("liquidity_target", sa.Numeric(5, 4)),
        sa.Column("urgency", sa.Numeric(5, 4)),
        sa.Column(
            "allow_below_cost", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("below_cost_floor", sa.Numeric(14, 2)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stock_status IS NULL OR stock_status IN ('fresh', 'stale', 'dead_stock', 'unknown')",
            name="ck_catalog_item_override_stock_status",
        ),
        sa.CheckConstraint(
            "cost IS NULL OR cost > 0", name="ck_catalog_item_override_cost"
        ),
        sa.CheckConstraint(
            "stock_qty IS NULL OR stock_qty >= 0",
            name="ck_catalog_item_override_stock_qty",
        ),
        sa.CheckConstraint(
            "below_cost_floor IS NULL OR below_cost_floor >= 0",
            name="ck_catalog_item_override_below_cost_floor",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_item_overrides_catalog_item_id",
        "catalog_item_overrides",
        ["catalog_item_id"],
    )
    op.create_index(
        "ix_catalog_item_overrides_user_id", "catalog_item_overrides", ["user_id"]
    )
    op.create_index(
        "ix_catalog_item_override_current",
        "catalog_item_overrides",
        ["catalog_item_id", "created_at", "id"],
    )

    op.create_table(
        "pricing_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("policy_config", sa.JSON(), nullable=False),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("total_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "manual_review_items", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("finalizer_task_id", sa.String(255)),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'collecting', 'classifying', "
            "'calculating', 'completed', 'partial', 'failed', 'cancelled')",
            name="ck_pricing_run_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"], ["catalog_import_batches.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pricing_runs_workspace_id", "pricing_runs", ["workspace_id"])
    op.create_index(
        "ix_pricing_runs_import_batch_id", "pricing_runs", ["import_batch_id"]
    )
    op.create_index(
        "ix_pricing_run_workspace_status", "pricing_runs", ["workspace_id", "status"]
    )

    op.create_table(
        "pricing_run_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("task_id", sa.String(255)),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("checkpoint", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('queued', 'collecting', 'collected', 'classified', "
            "'calculating', 'calculated', 'manual_review', 'failed', 'cancelled')",
            name="ck_pricing_run_item_status",
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_id"], ["pricing_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pricing_run_id", "catalog_item_id", name="uq_pricing_run_item"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_pricing_run_item_idempotency"),
    )
    op.create_index(
        "ix_pricing_run_items_pricing_run_id", "pricing_run_items", ["pricing_run_id"]
    )
    op.create_index(
        "ix_pricing_run_items_catalog_item_id", "pricing_run_items", ["catalog_item_id"]
    )
    op.create_index("ix_pricing_run_items_task_id", "pricing_run_items", ["task_id"])
    op.create_index(
        "ix_pricing_run_item_run_status",
        "pricing_run_items",
        ["pricing_run_id", "status"],
    )

    op.create_table(
        "raw_market_captures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_item_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column(
            "capture_kind",
            sa.String(50),
            server_default="parser_output",
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_item_id"], ["pricing_run_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pricing_run_item_id",
            "content_sha256",
            name="uq_raw_market_capture_item_sha256",
        ),
    )
    op.create_index(
        "ix_raw_market_captures_pricing_run_item_id",
        "raw_market_captures",
        ["pricing_run_item_id"],
    )
    op.create_index(
        "ix_raw_market_captures_content_sha256",
        "raw_market_captures",
        ["content_sha256"],
    )
    op.create_index(
        "ix_raw_market_capture_run_item_time",
        "raw_market_captures",
        ["pricing_run_item_id", "captured_at"],
    )

    op.create_table(
        "market_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_item_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("raw_capture_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_listing_id", sa.String(255), nullable=False),
        sa.Column("seller_id", sa.String(255), nullable=False),
        sa.Column("seller_name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("brand_raw", sa.String(255)),
        sa.Column("matched_oe_norm", sa.String(255), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("is_available", sa.Boolean()),
        sa.Column("match_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("price > 0", name="ck_market_observation_price_positive"),
        sa.CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_market_observation_match_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_item_id"], ["pricing_run_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["raw_capture_id"], ["raw_market_captures.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pricing_run_item_id",
            "source",
            "source_listing_id",
            name="uq_market_observation_run_listing",
        ),
    )
    for name, columns in (
        ("ix_market_observations_pricing_run_item_id", ["pricing_run_item_id"]),
        ("ix_market_observations_catalog_item_id", ["catalog_item_id"]),
        ("ix_market_observations_raw_capture_id", ["raw_capture_id"]),
        ("ix_market_observations_matched_oe_norm", ["matched_oe_norm"]),
        ("ix_market_observation_catalog_time", ["catalog_item_id", "observed_at"]),
    ):
        op.create_index(name, "market_observations", columns)

    op.create_table(
        "observation_tier_classifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("market_observation_id", sa.Uuid(), nullable=False),
        sa.Column("tier", sa.String(24), nullable=False),
        sa.Column("tier_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("is_used", sa.Boolean(), nullable=False),
        sa.Column("is_kemp", sa.Boolean(), nullable=False),
        sa.Column("is_owned", sa.Boolean(), nullable=False),
        sa.Column("is_dumping", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("exclusion_reason", sa.String(100)),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("method_version", sa.String(80), nullable=False),
        sa.Column("override_user_id", sa.Uuid()),
        sa.Column(
            "classified_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "tier IN ('oem', 'oes', 'aftermarket_a', 'aftermarket_b', "
            "'budget', 'kemp', 'used', 'unknown')",
            name="ck_observation_tier",
        ),
        sa.CheckConstraint(
            "tier_confidence >= 0 AND tier_confidence <= 1",
            name="ck_observation_tier_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["market_observation_id"], ["market_observations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["override_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_observation_tier_classifications_market_observation_id",
        "observation_tier_classifications",
        ["market_observation_id"],
    )
    op.create_index(
        "ix_observation_tier_current",
        "observation_tier_classifications",
        ["market_observation_id", "classified_at", "id"],
    )

    op.create_table(
        "brand_tier_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid()),
        sa.Column("brand_normalized", sa.String(255), nullable=False),
        sa.Column("tier", sa.String(24), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "tier IN ('oem', 'oes', 'aftermarket_a', 'aftermarket_b', "
            "'budget', 'kemp', 'used', 'unknown')",
            name="ck_brand_tier_rule_tier",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "brand_normalized",
            "version",
            name="uq_brand_tier_rule_version",
        ),
    )
    op.create_index(
        "ix_brand_tier_rules_workspace_id", "brand_tier_rules", ["workspace_id"]
    )
    op.create_index(
        "ix_brand_tier_rules_brand_normalized", "brand_tier_rules", ["brand_normalized"]
    )

    op.create_table(
        "tier_coefficients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(255), nullable=False),
        sa.Column("tier", sa.String(24), nullable=False),
        sa.Column("model", sa.String(32), nullable=False),
        sa.Column("multiplier", sa.Numeric(18, 10), nullable=False),
        sa.Column("log_effect", sa.Numeric(18, 10), nullable=False),
        sa.Column("global_log_effect", sa.Numeric(18, 10)),
        sa.Column("shrinkage_weight", sa.Numeric(8, 6)),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("effective_sample_size", sa.Numeric(12, 4), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("interval_low", sa.Numeric(18, 10)),
        sa.Column("interval_high", sa.Numeric(18, 10)),
        sa.Column("validated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("method_version", sa.String(80), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("multiplier > 0", name="ck_tier_coefficient_positive"),
        sa.CheckConstraint(
            "sample_size >= 0", name="ck_tier_coefficient_sample_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "category",
            "tier",
            "method_version",
            name="uq_tier_coefficient_version",
        ),
    )
    op.create_index(
        "ix_tier_coefficients_workspace_id", "tier_coefficients", ["workspace_id"]
    )
    op.create_index(
        "ix_tier_coefficient_lookup",
        "tier_coefficients",
        ["workspace_id", "category", "tier", "validated"],
    )

    op.create_table(
        "pricing_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_item_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("calculation_trace", sa.JSON(), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("current_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("fair_price", sa.Numeric(14, 2)),
        sa.Column("recommended_price", sa.Numeric(14, 2)),
        sa.Column("lower_bound", sa.Numeric(14, 2)),
        sa.Column("upper_bound", sa.Numeric(14, 2)),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("confidence_grade", sa.String(16), nullable=False),
        sa.Column("weakest_factor", sa.String(50)),
        sa.Column("factor_scores", sa.JSON(), nullable=False),
        sa.Column("competitor_count", sa.Integer(), nullable=False),
        sa.Column("effective_competitor_count", sa.Numeric(12, 4), nullable=False),
        sa.Column("dispersion", sa.Numeric(12, 8)),
        sa.Column("priority_score", sa.Numeric(20, 6), nullable=False),
        sa.Column("priority_score_type", sa.String(40), nullable=False),
        sa.Column("review_priority", sa.Numeric(20, 6), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("evidence_observation_ids", sa.JSON(), nullable=False),
        sa.Column("excluded_observations", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('RAISE', 'HOLD', 'LOWER', 'MANUAL_REVIEW', 'INSUFFICIENT_DATA')",
            name="ck_pricing_recommendation_action",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_pricing_recommendation_confidence",
        ),
        sa.CheckConstraint(
            "current_price > 0", name="ck_pricing_recommendation_current_price"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_id"], ["pricing_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_item_id"], ["pricing_run_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pricing_run_item_id", name="uq_pricing_recommendation_run_item"
        ),
    )
    op.create_index(
        "ix_pricing_recommendations_pricing_run_id",
        "pricing_recommendations",
        ["pricing_run_id"],
    )
    op.create_index(
        "ix_pricing_recommendations_pricing_run_item_id",
        "pricing_recommendations",
        ["pricing_run_item_id"],
    )
    op.create_index(
        "ix_pricing_recommendations_catalog_item_id",
        "pricing_recommendations",
        ["catalog_item_id"],
    )
    op.create_index(
        "ix_pricing_recommendation_run_action",
        "pricing_recommendations",
        ["pricing_run_id", "action"],
    )
    op.create_index(
        "ix_pricing_recommendation_run_priority",
        "pricing_recommendations",
        ["pricing_run_id", "priority_score"],
    )

    op.create_table(
        "recommendation_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid()),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("old_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("new_price", sa.Numeric(14, 2)),
        sa.Column("cost_snapshot", sa.Numeric(14, 2)),
        sa.Column(
            "allow_below_cost", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected', 'overridden')",
            name="ck_recommendation_decision",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["pricing_recommendations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recommendation_decisions_recommendation_id",
        "recommendation_decisions",
        ["recommendation_id"],
    )
    op.create_index(
        "ix_recommendation_decisions_user_id", "recommendation_decisions", ["user_id"]
    )
    op.create_index(
        "ix_recommendation_decision_recommendation_time",
        "recommendation_decisions",
        ["recommendation_id", "decided_at"],
    )

    op.execute(
        """
        CREATE FUNCTION marko_reject_append_only_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "raw_market_captures",
        "market_observations",
        "observation_tier_classifications",
        "pricing_recommendations",
        "recommendation_decisions",
        "catalog_item_overrides",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION marko_reject_append_only_mutation()"
        )


def downgrade() -> None:
    for table in (
        "recommendation_decisions",
        "pricing_recommendations",
        "observation_tier_classifications",
        "market_observations",
        "raw_market_captures",
        "catalog_item_overrides",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS marko_reject_append_only_mutation()")

    for table in (
        "recommendation_decisions",
        "pricing_recommendations",
        "tier_coefficients",
        "brand_tier_rules",
        "observation_tier_classifications",
        "market_observations",
        "raw_market_captures",
        "pricing_run_items",
        "pricing_runs",
        "catalog_item_overrides",
        "catalog_items",
        "pricing_policies",
        "catalog_import_batches",
    ):
        op.drop_table(table)
