"""Add trusted scraper contracts, explicit fencing, and dispatch outbox.

Revision ID: 20260717_0010
Revises: 20260716_0009
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0010"
down_revision: str | None = "20260716_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sync_runs",
        sa.Column(
            "scrape_fencing_token",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "store_sync_task_executions",
        sa.Column(
            "fencing_token",
            sa.BigInteger(),
            server_default="1",
            nullable=False,
        ),
    )
    op.drop_constraint(
        "ck_store_sync_task_execution_measurements",
        "store_sync_task_executions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_store_sync_task_execution_measurements",
        "store_sync_task_executions",
        "execution_no > 0 AND wall_time_ms >= 0 AND cpu_time_ms >= 0 "
        "AND memory_peak_bytes >= 0 AND fencing_token > 0",
    )

    target_columns = (
        sa.Column(
            "source_type",
            sa.String(50),
            server_default="prom_public",
            nullable=False,
        ),
        sa.Column(
            "source_lane",
            sa.String(32),
            server_default="PUBLIC_COMPETITOR",
            nullable=False,
        ),
        sa.Column("source_policy_decision_id", sa.String(160)),
        sa.Column("source_policy_version", sa.String(160)),
        sa.Column("source_policy_state", sa.String(24)),
        sa.Column("submission_key", sa.String(64)),
        sa.Column("acquisition_key", sa.String(64)),
        sa.Column("parse_key", sa.String(64)),
        sa.Column(
            "freshness_generation",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("attempt_group_id", sa.Uuid()),
        sa.Column("winning_attempt_id", sa.Uuid()),
        sa.Column(
            "fencing_token",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("parser_name", sa.String(160)),
        sa.Column("parser_config_hash", sa.String(64)),
        sa.Column("output_schema_version", sa.String(160)),
        sa.Column(
            "execution_status",
            sa.String(24),
            server_default="QUEUED",
            nullable=False,
        ),
        sa.Column(
            "acquisition_status",
            sa.String(24),
            server_default="NOT_STARTED",
            nullable=False,
        ),
        sa.Column(
            "parse_status",
            sa.String(24),
            server_default="NOT_STARTED",
            nullable=False,
        ),
        sa.Column(
            "evidence_status",
            sa.String(32),
            server_default="NONE",
            nullable=False,
        ),
        sa.Column(
            "downstream_eligibility",
            sa.String(24),
            server_default="UNKNOWN",
            nullable=False,
        ),
        sa.Column(
            "operator_action",
            sa.String(32),
            server_default="NO_RECOMMENDATION",
            nullable=False,
        ),
        sa.Column(
            "reason_codes",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    for column in target_columns:
        op.add_column("scrape_targets", column)

    op.execute(
        """
        UPDATE scrape_targets
        SET
          source_policy_decision_id = 'legacy-unverified-' || id::text,
          source_policy_version = 'legacy-v0',
          source_policy_state = 'UNKNOWN',
          submission_key = repeat('0', 64),
          acquisition_key = repeat('0', 64),
          attempt_group_id = md5(id::text)::uuid,
          parser_name = 'marko.parsers.prom',
          parser_config_hash = repeat('0', 64),
          output_schema_version = 'prom-price-comparison-v1',
          execution_status = CASE status
            WHEN 'succeeded' THEN 'SUCCEEDED'
            WHEN 'terminal_failure' THEN 'TERMINAL_FAILED'
            WHEN 'cancelled' THEN 'CANCELLED'
            WHEN 'collecting' THEN 'RUNNING'
            WHEN 'retryable_failure' THEN 'RETRY_WAIT'
            ELSE 'QUEUED'
          END,
          acquisition_status = CASE
            WHEN status = 'succeeded' THEN 'SUCCEEDED'
            WHEN status = 'terminal_failure' THEN 'FAILED'
            ELSE 'NOT_STARTED'
          END,
          parse_status = CASE
            WHEN status = 'succeeded' THEN 'SUCCEEDED'
            WHEN status = 'terminal_failure' AND raw_size_bytes > 0 THEN 'FAILED'
            ELSE 'NOT_STARTED'
          END,
          evidence_status = CASE
            WHEN status = 'succeeded' AND raw_size_bytes > 0
              THEN 'STRUCTURED_AVAILABLE'
            WHEN raw_size_bytes > 0 THEN 'RAW_AVAILABLE'
            ELSE 'NONE'
          END,
          downstream_eligibility = 'UNKNOWN',
          operator_action = 'NO_RECOMMENDATION'
        """
    )
    for name in (
        "source_policy_decision_id",
        "source_policy_version",
        "source_policy_state",
        "submission_key",
        "acquisition_key",
        "attempt_group_id",
        "parser_name",
        "parser_config_hash",
        "output_schema_version",
    ):
        op.alter_column("scrape_targets", name, nullable=False)

    op.drop_constraint(
        "ck_scrape_target_attempt_counts", "scrape_targets", type_="check"
    )
    op.create_check_constraint(
        "ck_scrape_target_attempt_counts",
        "scrape_targets",
        "delivery_count >= 0 AND network_attempts >= 0 "
        "AND max_task_executions > 0 AND freshness_generation >= 0 "
        "AND fencing_token >= 0",
    )
    checks = {
        "ck_scrape_target_source_policy_state": (
            "source_policy_state IN "
            "('PERMITTED', 'OWNER_RISK_ACCEPTED', 'NOT_PERMITTED', 'UNKNOWN')"
        ),
        "ck_scrape_target_source_lane": (
            "source_lane IN "
            "('OWNED_STOREFRONT', 'PUBLIC_COMPETITOR', 'REPLAY', 'CLIENT_EXPORT')"
        ),
        "ck_scrape_target_execution_status": (
            "execution_status IN ('QUEUED', 'RUNNING', 'RETRY_WAIT', "
            "'SUCCEEDED', 'TERMINAL_FAILED', 'CANCELLED', 'DEAD_LETTERED')"
        ),
        "ck_scrape_target_acquisition_status": (
            "acquisition_status IN ('NOT_STARTED', 'SUCCEEDED', 'FAILED', 'BLOCKED')"
        ),
        "ck_scrape_target_parse_status": (
            "parse_status IN "
            "('NOT_STARTED', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'NOT_APPLICABLE')"
        ),
        "ck_scrape_target_evidence_status": (
            "evidence_status IN ('NONE', 'RAW_AVAILABLE', 'STRUCTURED_AVAILABLE', "
            "'INGESTED', 'INTEGRITY_FAILED')"
        ),
        "ck_scrape_target_downstream_eligibility": (
            "downstream_eligibility IN ('ELIGIBLE', 'INELIGIBLE', 'UNKNOWN')"
        ),
        "ck_scrape_target_operator_action": (
            "operator_action IN ('NONE', 'MANUAL_REVIEW_REQUIRED', "
            "'REPLAY_REQUIRED', 'NO_RECOMMENDATION')"
        ),
    }
    for name, expression in checks.items():
        op.create_check_constraint(name, "scrape_targets", expression)
    for name, columns in (
        ("ix_scrape_targets_source_policy_decision_id", ["source_policy_decision_id"]),
        ("ix_scrape_targets_submission_key", ["submission_key"]),
        ("ix_scrape_target_acquisition_key", ["acquisition_key"]),
        ("ix_scrape_targets_parse_key", ["parse_key"]),
    ):
        op.create_index(name, "scrape_targets", columns)

    op.add_column(
        "scrape_attempts",
        sa.Column(
            "fencing_token",
            sa.BigInteger(),
            server_default="1",
            nullable=False,
        ),
    )
    op.drop_constraint(
        "ck_scrape_attempt_measurements", "scrape_attempts", type_="check"
    )
    op.create_check_constraint(
        "ck_scrape_attempt_measurements",
        "scrape_attempts",
        "delivery_no > 0 AND wall_time_ms >= 0 AND cpu_time_ms >= 0 "
        "AND memory_peak_bytes >= 0 AND fencing_token > 0",
    )

    op.create_table(
        "scrape_dispatch_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_key", sa.String(255), nullable=False),
        sa.Column("workspace_id", sa.Uuid()),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(255), nullable=False),
        sa.Column("task_id", sa.String(255), nullable=False),
        sa.Column("queue", sa.String(100)),
        sa.Column("task_args", sa.JSON(), nullable=False),
        sa.Column("task_kwargs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="20", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
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
            "status IN ('pending', 'dispatching', 'published', 'terminal_failed')",
            name="ck_scrape_dispatch_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_scrape_dispatch_outbox_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_scrape_dispatch_outbox_event_key"),
        sa.UniqueConstraint("task_id", name="uq_scrape_dispatch_outbox_task_id"),
    )
    for name, columns in (
        ("ix_scrape_dispatch_outbox_workspace_id", ["workspace_id"]),
        (
            "ix_scrape_dispatch_outbox_ready",
            ["status", "available_at", "created_at"],
        ),
        (
            "ix_scrape_dispatch_outbox_aggregate",
            ["aggregate_type", "aggregate_id"],
        ),
    ):
        op.create_index(name, "scrape_dispatch_outbox", columns)


def downgrade() -> None:
    op.drop_table("scrape_dispatch_outbox")

    op.drop_constraint(
        "ck_scrape_attempt_measurements", "scrape_attempts", type_="check"
    )
    op.drop_column("scrape_attempts", "fencing_token")
    op.create_check_constraint(
        "ck_scrape_attempt_measurements",
        "scrape_attempts",
        "delivery_no > 0 AND wall_time_ms >= 0 AND cpu_time_ms >= 0 "
        "AND memory_peak_bytes >= 0",
    )

    for name in (
        "ix_scrape_targets_parse_key",
        "ix_scrape_target_acquisition_key",
        "ix_scrape_targets_submission_key",
        "ix_scrape_targets_source_policy_decision_id",
    ):
        op.drop_index(name, table_name="scrape_targets")
    for name in (
        "ck_scrape_target_operator_action",
        "ck_scrape_target_downstream_eligibility",
        "ck_scrape_target_evidence_status",
        "ck_scrape_target_parse_status",
        "ck_scrape_target_acquisition_status",
        "ck_scrape_target_execution_status",
        "ck_scrape_target_source_lane",
        "ck_scrape_target_source_policy_state",
    ):
        op.drop_constraint(name, "scrape_targets", type_="check")
    op.drop_constraint(
        "ck_scrape_target_attempt_counts", "scrape_targets", type_="check"
    )
    for name in (
        "reason_codes",
        "operator_action",
        "downstream_eligibility",
        "evidence_status",
        "parse_status",
        "acquisition_status",
        "execution_status",
        "output_schema_version",
        "parser_config_hash",
        "parser_name",
        "fencing_token",
        "winning_attempt_id",
        "attempt_group_id",
        "freshness_generation",
        "parse_key",
        "acquisition_key",
        "submission_key",
        "source_policy_state",
        "source_policy_version",
        "source_policy_decision_id",
        "source_lane",
        "source_type",
    ):
        op.drop_column("scrape_targets", name)
    op.create_check_constraint(
        "ck_scrape_target_attempt_counts",
        "scrape_targets",
        "delivery_count >= 0 AND network_attempts >= 0 "
        "AND max_task_executions > 0",
    )

    op.drop_constraint(
        "ck_store_sync_task_execution_measurements",
        "store_sync_task_executions",
        type_="check",
    )
    op.drop_column("store_sync_task_executions", "fencing_token")
    op.create_check_constraint(
        "ck_store_sync_task_execution_measurements",
        "store_sync_task_executions",
        "execution_no > 0 AND wall_time_ms >= 0 AND cpu_time_ms >= 0 "
        "AND memory_peak_bytes >= 0",
    )
    op.drop_column("sync_runs", "scrape_fencing_token")
