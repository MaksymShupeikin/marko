"""Прибрати product_matches: таблицю ніхто не читає і не пише.

Revision ID: 20260824_0009
Revises: 20260824_0008
Create Date: 2026-08-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0009"
down_revision: str | None = "20260824_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

match_source = sa.Enum("manual", "automatic", name="match_source")
match_status = sa.Enum("candidate", "approved", "rejected", name="match_status")


def upgrade() -> None:
    op.drop_table("product_matches")
    bind = op.get_bind()
    match_status.drop(bind, checkfirst=True)
    match_source.drop(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    match_source.create(bind, checkfirst=True)
    match_status.create(bind, checkfirst=True)
    op.create_table(
        "product_matches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_listing_id",
            sa.Uuid(),
            sa.ForeignKey("listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_listing_id",
            sa.Uuid(),
            sa.ForeignKey("listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", match_source, nullable=False),
        sa.Column("status", match_status, nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("matcher_version", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "source_listing_id", "candidate_listing_id", name="uq_product_match"
        ),
        sa.CheckConstraint(
            "source_listing_id <> candidate_listing_id", name="ck_product_match_distinct"
        ),
    )
    op.create_index("ix_product_matches_workspace_id", "product_matches", ["workspace_id"])
    op.create_index("ix_product_matches_source_listing_id", "product_matches", ["source_listing_id"])
    op.create_index("ix_product_matches_candidate_listing_id", "product_matches", ["candidate_listing_id"])
