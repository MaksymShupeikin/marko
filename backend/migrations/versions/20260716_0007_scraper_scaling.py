"""Add deduplicated scraper targets, attempts, and evidence measurements.

Revision ID: 20260716_0007
Revises: 20260716_0006
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0007"
down_revision: str | None = "20260716_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scrape_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(50), server_default="prom", nullable=False),
        sa.Column("original_url", sa.Text()),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("product_key", sa.String(100)),
        sa.Column("query", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("adapter_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), server_default="queued", nullable=False),
        sa.Column("owner_task_id", sa.String(255)),
        sa.Column("delivery_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("network_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "max_task_executions",
            sa.Integer(),
            server_default="4",
            nullable=False,
        ),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("payload", sa.JSON()),
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("raw_size_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "structured_size_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "metadata_size_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("structured_completeness", sa.Numeric(7, 6)),
        sa.Column("error_category", sa.String(50)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("first_started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint(
            "status IN ('queued', 'collecting', 'retryable_failure', "
            "'succeeded', 'terminal_failure', 'cancelled')",
            name="ck_scrape_target_status",
        ),
        sa.CheckConstraint(
            "delivery_count >= 0 AND network_attempts >= 0 "
            "AND max_task_executions > 0",
            name="ck_scrape_target_attempt_counts",
        ),
        sa.CheckConstraint(
            "raw_size_bytes >= 0 AND structured_size_bytes >= 0 "
            "AND metadata_size_bytes >= 0",
            name="ck_scrape_target_storage_sizes",
        ),
        sa.CheckConstraint(
            "structured_completeness IS NULL OR "
            "(structured_completeness >= 0 AND structured_completeness <= 1)",
            name="ck_scrape_target_completeness",
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_id"], ["pricing_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pricing_run_id",
            "input_hash",
            name="uq_scrape_target_run_input_hash",
        ),
    )
    for index_name, columns in (
        ("ix_scrape_targets_pricing_run_id", ["pricing_run_id"]),
        ("ix_scrape_targets_input_hash", ["input_hash"]),
        ("ix_scrape_targets_owner_task_id", ["owner_task_id"]),
        ("ix_scrape_targets_content_sha256", ["content_sha256"]),
        ("ix_scrape_target_run_status", ["pricing_run_id", "status"]),
    ):
        op.create_index(index_name, "scrape_targets", columns)

    op.add_column(
        "pricing_run_items",
        sa.Column("scrape_target_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_pricing_run_items_scrape_target",
        "pricing_run_items",
        "scrape_targets",
        ["scrape_target_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_pricing_run_items_scrape_target_id",
        "pricing_run_items",
        ["scrape_target_id"],
    )

    op.create_table(
        "scrape_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scrape_target_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_item_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.String(255)),
        sa.Column("delivery_no", sa.Integer(), nullable=False),
        sa.Column(
            "network_attempted", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("status", sa.String(24), server_default="running", nullable=False),
        sa.Column("error_category", sa.String(50)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("wall_time_ms", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("cpu_time_ms", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "memory_peak_bytes", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("raw_size_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "structured_size_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "metadata_size_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("structured_completeness", sa.Numeric(7, 6)),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'retryable_failure', "
            "'terminal_failure', 'duplicate', 'worker_lost')",
            name="ck_scrape_attempt_status",
        ),
        sa.CheckConstraint(
            "delivery_no > 0 AND wall_time_ms >= 0 AND cpu_time_ms >= 0 "
            "AND memory_peak_bytes >= 0",
            name="ck_scrape_attempt_measurements",
        ),
        sa.CheckConstraint(
            "raw_size_bytes >= 0 AND structured_size_bytes >= 0 "
            "AND metadata_size_bytes >= 0",
            name="ck_scrape_attempt_storage_sizes",
        ),
        sa.CheckConstraint(
            "structured_completeness IS NULL OR "
            "(structured_completeness >= 0 AND structured_completeness <= 1)",
            name="ck_scrape_attempt_completeness",
        ),
        sa.ForeignKeyConstraint(
            ["scrape_target_id"], ["scrape_targets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_item_id"], ["pricing_run_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scrape_target_id",
            "delivery_no",
            name="uq_scrape_attempt_target_delivery",
        ),
    )
    for index_name, columns in (
        ("ix_scrape_attempts_scrape_target_id", ["scrape_target_id"]),
        ("ix_scrape_attempts_pricing_run_item_id", ["pricing_run_item_id"]),
        ("ix_scrape_attempts_task_id", ["task_id"]),
        ("ix_scrape_attempt_target_status", ["scrape_target_id", "status"]),
    ):
        op.create_index(index_name, "scrape_attempts", columns)

    for column in (
        sa.Column("scrape_target_id", sa.Uuid()),
        sa.Column(
            "raw_size_bytes", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "structured_size_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "metadata_size_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("structured_completeness", sa.Numeric(7, 6)),
    ):
        op.add_column("raw_market_captures", column)
    op.create_foreign_key(
        "fk_raw_market_captures_scrape_target",
        "raw_market_captures",
        "scrape_targets",
        ["scrape_target_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_raw_market_captures_scrape_target_id",
        "raw_market_captures",
        ["scrape_target_id"],
    )
    op.create_check_constraint(
        "ck_raw_market_capture_storage_sizes",
        "raw_market_captures",
        "raw_size_bytes >= 0 AND structured_size_bytes >= 0 "
        "AND metadata_size_bytes >= 0",
    )
    op.create_check_constraint(
        "ck_raw_market_capture_completeness",
        "raw_market_captures",
        "structured_completeness IS NULL OR "
        "(structured_completeness >= 0 AND structured_completeness <= 1)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_raw_market_capture_completeness",
        "raw_market_captures",
        type_="check",
    )
    op.drop_constraint(
        "ck_raw_market_capture_storage_sizes",
        "raw_market_captures",
        type_="check",
    )
    op.drop_index(
        "ix_raw_market_captures_scrape_target_id",
        table_name="raw_market_captures",
    )
    op.drop_constraint(
        "fk_raw_market_captures_scrape_target",
        "raw_market_captures",
        type_="foreignkey",
    )
    for column in (
        "structured_completeness",
        "metadata_size_bytes",
        "structured_size_bytes",
        "raw_size_bytes",
        "scrape_target_id",
    ):
        op.drop_column("raw_market_captures", column)

    op.drop_table("scrape_attempts")

    op.drop_index(
        "ix_pricing_run_items_scrape_target_id",
        table_name="pricing_run_items",
    )
    op.drop_constraint(
        "fk_pricing_run_items_scrape_target",
        "pricing_run_items",
        type_="foreignkey",
    )
    op.drop_column("pricing_run_items", "scrape_target_id")

    op.drop_table("scrape_targets")
