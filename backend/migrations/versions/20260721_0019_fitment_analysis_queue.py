"""Add durable queue state to fitment analysis jobs.

Revision ID: 20260721_0019
Revises: 20260721_0018
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_0019"
down_revision: str | None = "20260721_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fitment_analyses",
        sa.Column(
            "request_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "fitment_analyses",
        sa.Column("dispatch_task_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "fitment_analyses",
        sa.Column("owner_task_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "fitment_analyses",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "fitment_analyses",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "fitment_analyses",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("fitment_analyses", "request_payload", server_default=None)
    op.drop_constraint("ck_fit_analysis_counts", "fitment_analyses", type_="check")
    op.create_check_constraint(
        "ck_fit_analysis_counts",
        "fitment_analyses",
        "candidate_count >= 0 AND completed_candidate_count >= 0 "
        "AND failed_candidate_count >= 0 AND attempt_count >= 0",
    )
    op.create_index(
        "ix_fitment_analyses_dispatch_task_id",
        "fitment_analyses",
        ["dispatch_task_id"],
    )
    op.create_index(
        "ix_fitment_analyses_owner_task_id",
        "fitment_analyses",
        ["owner_task_id"],
    )
    op.create_index(
        "ix_fitment_analyses_lease_expires_at",
        "fitment_analyses",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_fitment_analyses_lease_expires_at", table_name="fitment_analyses")
    op.drop_index("ix_fitment_analyses_owner_task_id", table_name="fitment_analyses")
    op.drop_index("ix_fitment_analyses_dispatch_task_id", table_name="fitment_analyses")
    op.drop_constraint("ck_fit_analysis_counts", "fitment_analyses", type_="check")
    op.create_check_constraint(
        "ck_fit_analysis_counts",
        "fitment_analyses",
        "candidate_count >= 0 AND completed_candidate_count >= 0 "
        "AND failed_candidate_count >= 0",
    )
    op.drop_column("fitment_analyses", "last_attempt_at")
    op.drop_column("fitment_analyses", "lease_expires_at")
    op.drop_column("fitment_analyses", "attempt_count")
    op.drop_column("fitment_analyses", "owner_task_id")
    op.drop_column("fitment_analyses", "dispatch_task_id")
    op.drop_column("fitment_analyses", "request_payload")
