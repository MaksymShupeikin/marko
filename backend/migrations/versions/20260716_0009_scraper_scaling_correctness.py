"""Enforce scraper fencing prerequisites and immutable store-sync output.

Revision ID: 20260716_0009
Revises: 20260716_0008
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0009"
down_revision: str | None = "20260716_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Migration 0008 introduced scrape_state with a queued default. Correct
    # historical lifecycle rows before any queue metrics or active-run
    # uniqueness constraint can rely on that state.
    op.execute(
        """
        UPDATE sync_runs
        SET scrape_state = CASE status::text
            WHEN 'completed' THEN 'succeeded'
            WHEN 'failed' THEN 'failed'
            WHEN 'running' THEN 'running'
            ELSE 'queued'
        END
        """
    )

    # If historical application races created more than one active catalog
    # import, keep the newest run active and close older duplicates explicitly.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY workspace_id, store_id
                    ORDER BY created_at DESC, id DESC
                ) AS position
            FROM sync_runs
            WHERE kind = 'catalog_import'
              AND store_id IS NOT NULL
              AND scrape_state IN ('queued', 'running', 'retry_wait')
        )
        UPDATE sync_runs AS run
        SET
            status = 'failed',
            scrape_state = 'failed',
            error = COALESCE(
                run.error,
                'Closed by active store-sync uniqueness migration'
            ),
            scrape_owner_task_id = NULL,
            scrape_lease_expires_at = NULL,
            finished_at = COALESCE(run.finished_at, now())
        FROM ranked
        WHERE run.id = ranked.id
          AND ranked.position > 1
        """
    )
    op.create_index(
        "uq_sync_run_active_store_sync",
        "sync_runs",
        ["workspace_id", "store_id"],
        unique=True,
        postgresql_where=sa.text(
            "kind = 'catalog_import' "
            "AND store_id IS NOT NULL "
            "AND scrape_state IN ('queued', 'running', 'retry_wait')"
        ),
    )

    op.create_table(
        "store_sync_product_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid()),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("structured_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "structured_completeness",
            sa.Numeric(7, 6),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "structured_size_bytes >= 0",
            name="ck_store_sync_product_snapshot_size",
        ),
        sa.CheckConstraint(
            "structured_completeness >= 0 "
            "AND structured_completeness <= 1",
            name="ck_store_sync_product_snapshot_completeness",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["sync_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sync_run_id",
            "external_id",
            name="uq_store_sync_product_snapshot_external",
        ),
    )
    op.create_index(
        "ix_store_sync_product_snapshots_listing_id",
        "store_sync_product_snapshots",
        ["listing_id"],
    )
    op.create_index(
        "ix_store_sync_product_snapshots_content_sha256",
        "store_sync_product_snapshots",
        ["content_sha256"],
    )
    op.create_index(
        "ix_store_sync_product_snapshot_run",
        "store_sync_product_snapshots",
        ["sync_run_id"],
    )


def downgrade() -> None:
    op.drop_table("store_sync_product_snapshots")
    op.drop_index(
        "uq_sync_run_active_store_sync",
        table_name="sync_runs",
    )
