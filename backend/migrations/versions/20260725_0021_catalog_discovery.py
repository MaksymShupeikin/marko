"""Add persisted owned-catalog competitor discovery snapshots.

Revision ID: 20260725_0021
Revises: 20260721_0020
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0021"
down_revision: str | None = "20260721_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_discovery_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("product_key", sa.String(length=64), nullable=False),
        sa.Column("query", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("oe_norm", sa.String(length=255), nullable=True),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="running",
            nullable=False,
        ),
        sa.Column("parser_outcome", sa.String(length=40), nullable=True),
        sa.Column("prom_reported_total", sa.Integer(), nullable=True),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retrieved_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("persisted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rejected_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "owned_excluded_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_catalog_discovery_run_status",
        ),
        sa.CheckConstraint(
            "request_count >= 0 AND retrieved_count >= 0 "
            "AND persisted_count >= 0 AND rejected_count >= 0 "
            "AND owned_excluded_count >= 0",
            name="ck_catalog_discovery_run_counts",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_discovery_runs_workspace_id",
        "catalog_discovery_runs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_catalog_discovery_runs_product_key",
        "catalog_discovery_runs",
        ["product_key"],
    )
    op.create_index(
        "ix_catalog_discovery_runs_oe_norm",
        "catalog_discovery_runs",
        ["oe_norm"],
    )
    op.create_index(
        "ix_catalog_discovery_runs_status",
        "catalog_discovery_runs",
        ["status"],
    )
    op.create_index(
        "ix_catalog_discovery_workspace_product_time",
        "catalog_discovery_runs",
        ["workspace_id", "product_key", "created_at"],
    )

    op.create_table(
        "catalog_discovery_captures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("discovery_run_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_blob_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("request_kind", sa.String(length=40), nullable=False),
        sa.Column("prepared_url", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("attempts_total", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.BigInteger(), nullable=False),
        sa.Column("raw_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence_no > 0 AND attempts_total > 0 AND latency_ms >= 0 "
            "AND raw_size_bytes >= 0",
            name="ck_catalog_discovery_capture_measurements",
        ),
        sa.ForeignKeyConstraint(
            ["discovery_run_id"],
            ["catalog_discovery_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_blob_id"],
            ["scrape_evidence_blobs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "discovery_run_id",
            "sequence_no",
            name="uq_catalog_discovery_capture_sequence",
        ),
    )
    op.create_index(
        "ix_catalog_discovery_captures_discovery_run_id",
        "catalog_discovery_captures",
        ["discovery_run_id"],
    )
    op.create_index(
        "ix_catalog_discovery_captures_evidence_blob_id",
        "catalog_discovery_captures",
        ["evidence_blob_id"],
    )
    op.create_index(
        "ix_catalog_discovery_captures_content_sha256",
        "catalog_discovery_captures",
        ["content_sha256"],
    )

    op.create_table(
        "catalog_discovery_offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("discovery_run_id", sa.Uuid(), nullable=False),
        sa.Column("raw_offer_index", sa.Integer(), nullable=False),
        sa.Column("source_listing_id", sa.String(length=255), nullable=False),
        sa.Column("seller_id", sa.String(length=255), nullable=False),
        sa.Column("seller_name", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("sale_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("reference_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("measure_unit", sa.String(length=80), nullable=True),
        sa.Column("is_available", sa.Boolean(), nullable=True),
        sa.Column("is_owned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "title_contains_query",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("identity_status", sa.String(length=40), nullable=False),
        sa.Column("source_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("reason_codes", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("raw_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "raw_offer_index >= 0 AND sale_price > 0 "
            "AND (reference_price IS NULL OR reference_price > 0) "
            "AND source_confidence >= 0 AND source_confidence <= 1",
            name="ck_catalog_discovery_offer_values",
        ),
        sa.CheckConstraint(
            "identity_status IN ('QUERY_TOKEN_PRESENT', 'SEARCH_RESULT_UNVERIFIED')",
            name="ck_catalog_discovery_offer_identity_status",
        ),
        sa.ForeignKeyConstraint(
            ["discovery_run_id"],
            ["catalog_discovery_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "discovery_run_id",
            "source_listing_id",
            name="uq_catalog_discovery_offer_listing",
        ),
    )
    op.create_index(
        "ix_catalog_discovery_offers_discovery_run_id",
        "catalog_discovery_offers",
        ["discovery_run_id"],
    )
    op.create_index(
        "ix_catalog_discovery_offers_is_owned",
        "catalog_discovery_offers",
        ["is_owned"],
    )
    op.create_index(
        "ix_catalog_discovery_offer_run_owned",
        "catalog_discovery_offers",
        ["discovery_run_id", "is_owned"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_discovery_offer_run_owned",
        table_name="catalog_discovery_offers",
    )
    op.drop_index(
        "ix_catalog_discovery_offers_is_owned",
        table_name="catalog_discovery_offers",
    )
    op.drop_index(
        "ix_catalog_discovery_offers_discovery_run_id",
        table_name="catalog_discovery_offers",
    )
    op.drop_table("catalog_discovery_offers")
    op.drop_index(
        "ix_catalog_discovery_captures_content_sha256",
        table_name="catalog_discovery_captures",
    )
    op.drop_index(
        "ix_catalog_discovery_captures_evidence_blob_id",
        table_name="catalog_discovery_captures",
    )
    op.drop_index(
        "ix_catalog_discovery_captures_discovery_run_id",
        table_name="catalog_discovery_captures",
    )
    op.drop_table("catalog_discovery_captures")
    op.drop_index(
        "ix_catalog_discovery_workspace_product_time",
        table_name="catalog_discovery_runs",
    )
    op.drop_index(
        "ix_catalog_discovery_runs_status",
        table_name="catalog_discovery_runs",
    )
    op.drop_index(
        "ix_catalog_discovery_runs_oe_norm",
        table_name="catalog_discovery_runs",
    )
    op.drop_index(
        "ix_catalog_discovery_runs_product_key",
        table_name="catalog_discovery_runs",
    )
    op.drop_index(
        "ix_catalog_discovery_runs_workspace_id",
        table_name="catalog_discovery_runs",
    )
    op.drop_table("catalog_discovery_runs")
