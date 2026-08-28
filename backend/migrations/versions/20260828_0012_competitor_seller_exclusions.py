"""Persist owned seller exclusions independently from imported catalogs.

Revision ID: 20260828_0012
Revises: 20260826_0011
Create Date: 2026-08-28
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260828_0012"
down_revision: str | None = "20260826_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "competitor_seller_exclusions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "marketplace",
            sa.String(32),
            server_default="prom",
            nullable=False,
        ),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(255), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "marketplace",
            "external_id",
            name="uq_competitor_seller_exclusion_identity",
        ),
    )
    op.create_index(
        "ix_competitor_seller_exclusions_workspace_id",
        "competitor_seller_exclusions",
        ["workspace_id"],
    )

    # Every store already labelled as owned must remain excluded even if its
    # catalog is deleted after this migration.
    op.execute(
        """
        INSERT INTO competitor_seller_exclusions (
            id,
            workspace_id,
            marketplace,
            external_id,
            slug,
            canonical_url,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            ms.workspace_id,
            ms.marketplace,
            ms.external_id,
            lower(ms.name),
            ms.canonical_url,
            now(),
            now()
        FROM marketplace_stores ms
        JOIN workspace_stores ws
          ON ws.workspace_id = ms.workspace_id
         AND ws.store_id = ms.id
        WHERE ws.kind = 'owned'
          AND lower(ms.marketplace) = 'prom'
        ON CONFLICT ON CONSTRAINT uq_competitor_seller_exclusion_identity
        DO UPDATE SET
            slug = EXCLUDED.slug,
            canonical_url = EXCLUDED.canonical_url,
            updated_at = now()
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_competitor_seller_exclusions_workspace_id",
        table_name="competitor_seller_exclusions",
    )
    op.drop_table("competitor_seller_exclusions")
