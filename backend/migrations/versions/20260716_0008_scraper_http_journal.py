"""Add store-sync lifecycle, HTTP attempt journal, and raw evidence blobs.

Revision ID: 20260716_0008
Revises: 20260716_0007
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0008"
down_revision: str | None = "20260716_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sync_columns = (
        sa.Column(
            "scrape_item_version",
            sa.String(80),
            server_default="store-sync-v1",
            nullable=False,
        ),
        sa.Column("scrape_input_fingerprint", sa.String(64)),
        sa.Column(
            "scrape_state",
            sa.String(20),
            server_default="queued",
            nullable=False,
        ),
        sa.Column(
            "scrape_deduplicated_submissions",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "scrape_task_executions",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "scrape_task_redeliveries",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "scrape_max_task_executions",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
        sa.Column("scrape_deadline_at", sa.DateTime(timezone=True)),
        sa.Column("scrape_owner_task_id", sa.String(255)),
        sa.Column("scrape_lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("scrape_checkpoint", sa.JSON()),
        sa.Column(
            "scrape_catalog_pages",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "scrape_products_extracted",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "scrape_products_persisted",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "scrape_duplicate_products",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "scrape_database_writes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "scrape_raw_evidence_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("scrape_structured_completeness", sa.Numeric(7, 6)),
        sa.Column("scrape_evidence_coverage", sa.Numeric(7, 6)),
    )
    for column in sync_columns:
        op.add_column("sync_runs", column)
    op.create_index(
        "ix_sync_runs_scrape_input_fingerprint",
        "sync_runs",
        ["scrape_input_fingerprint"],
    )
    op.create_index(
        "ix_sync_run_scrape_state",
        "sync_runs",
        ["scrape_state"],
    )
    op.create_index(
        "ix_sync_runs_scrape_owner_task_id",
        "sync_runs",
        ["scrape_owner_task_id"],
    )
    op.create_check_constraint(
        "ck_sync_run_scrape_state",
        "sync_runs",
        "scrape_state IN ('queued', 'running', 'retry_wait', "
        "'succeeded', 'failed', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_sync_run_scrape_task_counts",
        "sync_runs",
        "scrape_task_executions >= 0 AND scrape_task_redeliveries >= 0 "
        "AND scrape_deduplicated_submissions >= 0",
    )
    op.create_check_constraint(
        "ck_sync_run_scrape_output_counts",
        "sync_runs",
        "scrape_catalog_pages >= 0 AND scrape_products_extracted >= 0 "
        "AND scrape_products_persisted >= 0 "
        "AND scrape_duplicate_products >= 0 AND scrape_database_writes >= 0 "
        "AND scrape_raw_evidence_bytes >= 0",
    )
    op.create_check_constraint(
        "ck_sync_run_scrape_completeness",
        "sync_runs",
        "scrape_structured_completeness IS NULL OR "
        "(scrape_structured_completeness >= 0 "
        "AND scrape_structured_completeness <= 1)",
    )
    op.create_check_constraint(
        "ck_sync_run_scrape_evidence_coverage",
        "sync_runs",
        "scrape_evidence_coverage IS NULL OR "
        "(scrape_evidence_coverage >= 0 AND scrape_evidence_coverage <= 1)",
    )

    op.add_column(
        "price_observations",
        sa.Column("sync_run_id", sa.Uuid()),
    )
    op.create_foreign_key(
        "fk_price_observations_sync_run",
        "price_observations",
        "sync_runs",
        ["sync_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_price_observations_sync_run_id",
        "price_observations",
        ["sync_run_id"],
    )
    op.create_unique_constraint(
        "uq_price_observation_sync_listing",
        "price_observations",
        ["sync_run_id", "listing_id"],
    )

    op.create_table(
        "store_sync_task_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.String(255)),
        sa.Column("execution_no", sa.Integer(), nullable=False),
        sa.Column(
            "is_redelivery",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("redelivery_reason", sa.String(100)),
        sa.Column(
            "outcome",
            sa.String(24),
            server_default="running",
            nullable=False,
        ),
        sa.Column("error_category", sa.String(50)),
        sa.Column("error_detail", sa.Text()),
        sa.Column(
            "wall_time_ms",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "cpu_time_ms",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "memory_peak_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "execution_no > 0 AND wall_time_ms >= 0 AND cpu_time_ms >= 0 "
            "AND memory_peak_bytes >= 0",
            name="ck_store_sync_task_execution_measurements",
        ),
        sa.CheckConstraint(
            "outcome IN ('running', 'succeeded', 'retryable_failure', "
            "'terminal_failure', 'worker_lost')",
            name="ck_store_sync_task_execution_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["sync_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sync_run_id",
            "execution_no",
            name="uq_store_sync_task_execution_no",
        ),
    )
    op.create_index(
        "ix_store_sync_task_executions_sync_run_id",
        "store_sync_task_executions",
        ["sync_run_id"],
    )
    op.create_index(
        "ix_store_sync_task_executions_task_id",
        "store_sync_task_executions",
        ["task_id"],
    )
    op.create_index(
        "ix_store_sync_task_execution_run_outcome",
        "store_sync_task_executions",
        ["sync_run_id", "outcome"],
    )

    op.create_table(
        "scrape_evidence_blobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_zlib", sa.LargeBinary(), nullable=False),
        sa.Column("raw_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("stored_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(255)),
        sa.Column("encoding", sa.String(50)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "raw_size_bytes >= 0 AND stored_size_bytes >= 0",
            name="ck_scrape_evidence_blob_sizes",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "content_sha256",
            name="uq_scrape_evidence_blobs_content_sha256",
        ),
    )
    op.create_index(
        "ix_scrape_evidence_blobs_content_sha256",
        "scrape_evidence_blobs",
        ["content_sha256"],
        unique=True,
    )

    op.create_table(
        "scrape_http_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid()),
        sa.Column("scrape_target_id", sa.Uuid()),
        sa.Column("evidence_blob_id", sa.Uuid()),
        sa.Column("execution_no", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("request_kind", sa.String(50), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("prepared_url", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column(
            "replayed",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("response_status_code", sa.Integer()),
        sa.Column(
            "latency_ms",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "rate_wait_ms",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "backoff_ms",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("error_category", sa.String(50)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(sync_run_id IS NOT NULL AND scrape_target_id IS NULL) OR "
            "(sync_run_id IS NULL AND scrape_target_id IS NOT NULL)",
            name="ck_scrape_http_request_one_owner",
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'replayed', 'retryable_failure', "
            "'terminal_failure')",
            name="ck_scrape_http_request_outcome",
        ),
        sa.CheckConstraint(
            "execution_no > 0 AND sequence_no > 0 AND attempt_count >= 0 "
            "AND latency_ms >= 0 AND rate_wait_ms >= 0 AND backoff_ms >= 0",
            name="ck_scrape_http_request_measurements",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["sync_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scrape_target_id"],
            ["scrape_targets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_blob_id"],
            ["scrape_evidence_blobs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sync_run_id",
            "execution_no",
            "sequence_no",
            name="uq_scrape_http_request_sync_execution_sequence",
        ),
        sa.UniqueConstraint(
            "scrape_target_id",
            "execution_no",
            "sequence_no",
            name="uq_scrape_http_request_target_execution_sequence",
        ),
    )
    for index_name, columns in (
        ("ix_scrape_http_requests_sync_run_id", ["sync_run_id"]),
        ("ix_scrape_http_requests_scrape_target_id", ["scrape_target_id"]),
        ("ix_scrape_http_requests_evidence_blob_id", ["evidence_blob_id"]),
        ("ix_scrape_http_requests_request_kind", ["request_kind"]),
        ("ix_scrape_http_requests_request_key", ["request_key"]),
        ("ix_scrape_http_request_sync_kind", ["sync_run_id", "request_kind"]),
        (
            "ix_scrape_http_request_target_kind",
            ["scrape_target_id", "request_kind"],
        ),
    ):
        op.create_index(index_name, "scrape_http_requests", columns)

    op.create_table(
        "scrape_http_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("logical_request_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("status_class", sa.String(20), nullable=False),
        sa.Column("latency_ms", sa.BigInteger(), nullable=False),
        sa.Column("local_rate_wait_ms", sa.BigInteger(), nullable=False),
        sa.Column("global_rate_wait_ms", sa.BigInteger(), nullable=False),
        sa.Column("retry_backoff_ms", sa.BigInteger(), nullable=False),
        sa.Column("error_category", sa.String(50)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('success', 'retryable_failure', 'terminal_failure')",
            name="ck_scrape_http_attempt_outcome",
        ),
        sa.CheckConstraint(
            "attempt_no > 0 AND latency_ms >= 0 AND local_rate_wait_ms >= 0 "
            "AND global_rate_wait_ms >= 0 AND retry_backoff_ms >= 0",
            name="ck_scrape_http_attempt_measurements",
        ),
        sa.ForeignKeyConstraint(
            ["logical_request_id"],
            ["scrape_http_requests.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "logical_request_id",
            "attempt_no",
            name="uq_scrape_http_attempt_request_no",
        ),
    )
    op.create_index(
        "ix_scrape_http_attempts_logical_request_id",
        "scrape_http_attempts",
        ["logical_request_id"],
    )
    op.create_index(
        "ix_scrape_http_attempt_outcome_status",
        "scrape_http_attempts",
        ["outcome", "status_class"],
    )


def downgrade() -> None:
    op.drop_table("scrape_http_attempts")
    op.drop_table("scrape_http_requests")
    op.drop_table("scrape_evidence_blobs")
    op.drop_table("store_sync_task_executions")

    op.drop_constraint(
        "uq_price_observation_sync_listing",
        "price_observations",
        type_="unique",
    )
    op.drop_index(
        "ix_price_observations_sync_run_id",
        table_name="price_observations",
    )
    op.drop_constraint(
        "fk_price_observations_sync_run",
        "price_observations",
        type_="foreignkey",
    )
    op.drop_column("price_observations", "sync_run_id")

    for constraint in (
        "ck_sync_run_scrape_evidence_coverage",
        "ck_sync_run_scrape_completeness",
        "ck_sync_run_scrape_output_counts",
        "ck_sync_run_scrape_task_counts",
        "ck_sync_run_scrape_state",
    ):
        op.drop_constraint(constraint, "sync_runs", type_="check")
    op.drop_index("ix_sync_run_scrape_state", table_name="sync_runs")
    op.drop_index(
        "ix_sync_runs_scrape_owner_task_id",
        table_name="sync_runs",
    )
    op.drop_index(
        "ix_sync_runs_scrape_input_fingerprint",
        table_name="sync_runs",
    )
    for column in (
        "scrape_evidence_coverage",
        "scrape_structured_completeness",
        "scrape_raw_evidence_bytes",
        "scrape_database_writes",
        "scrape_duplicate_products",
        "scrape_products_persisted",
        "scrape_products_extracted",
        "scrape_catalog_pages",
        "scrape_checkpoint",
        "scrape_lease_expires_at",
        "scrape_owner_task_id",
        "scrape_deadline_at",
        "scrape_max_task_executions",
        "scrape_task_redeliveries",
        "scrape_task_executions",
        "scrape_deduplicated_submissions",
        "scrape_state",
        "scrape_input_fingerprint",
        "scrape_item_version",
    ):
        op.drop_column("sync_runs", column)
