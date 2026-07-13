"""Initial accounts, marketplace catalog, pricing, and matching schema.

Revision ID: 20260713_0001
Revises:
Create Date: 2026-07-13
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260713_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

workspace_role = sa.Enum("owner", "admin", "member", name="workspace_role")
store_kind = sa.Enum("owned", "competitor", name="store_kind")
match_source = sa.Enum("manual", "automatic", name="match_source")
match_status = sa.Enum("candidate", "approved", "rejected", name="match_status")
sync_status = sa.Enum("queued", "running", "completed", "failed", name="sync_status")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"])

    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", workspace_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
    )

    op.create_table(
        "marketplace_stores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("marketplace", sa.String(32), server_default="prom", nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("marketplace", "external_id", name="uq_store_marketplace_external"),
    )

    op.create_table(
        "workspace_stores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("kind", store_kind, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["marketplace_stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "store_id", name="uq_workspace_store"),
    )
    op.create_index("ix_workspace_stores_store_id", "workspace_stores", ["store_id"])
    op.create_index("ix_workspace_stores_workspace_id", "workspace_stores", ["workspace_id"])

    op.create_table(
        "listings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("sku", sa.String(255)),
        sa.Column("model_id", sa.String(255)),
        sa.Column("brand", sa.String(255)),
        sa.Column("currency", sa.String(3), server_default="UAH", nullable=False),
        sa.Column("current_price", sa.Numeric(14, 2)),
        sa.Column("is_available", sa.Boolean()),
        sa.Column("raw_data", sa.JSON()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["marketplace_stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_id", "external_id", name="uq_listing_store_external"),
    )
    op.create_index("ix_listings_store_id", "listings", ["store_id"])
    op.create_index("ix_listing_model_id", "listings", ["model_id"])
    op.create_index("ix_listing_sku", "listings", ["sku"])

    op.create_table(
        "price_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("is_available", sa.Boolean()),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_price_observations_listing_id", "price_observations", ["listing_id"])
    op.create_index(
        "ix_price_observation_listing_time", "price_observations", ["listing_id", "observed_at"]
    )

    op.create_table(
        "product_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_listing_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_listing_id", sa.Uuid(), nullable=False),
        sa.Column("source", match_source, nullable=False),
        sa.Column("status", match_status, nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("matcher_version", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source_listing_id <> candidate_listing_id", name="ck_product_match_distinct"),
        sa.ForeignKeyConstraint(["candidate_listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "source_listing_id", "candidate_listing_id", name="uq_product_match"
        ),
    )
    op.create_index("ix_product_matches_workspace_id", "product_matches", ["workspace_id"])
    op.create_index("ix_product_matches_source_listing_id", "product_matches", ["source_listing_id"])
    op.create_index("ix_product_matches_candidate_listing_id", "product_matches", ["candidate_listing_id"])

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid()),
        sa.Column("store_id", sa.Uuid()),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("status", sync_status, nullable=False),
        sa.Column("task_id", sa.String(255)),
        sa.Column("progress_current", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_total", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["marketplace_stores.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index("ix_sync_runs_store_id", "sync_runs", ["store_id"])
    op.create_index("ix_sync_runs_workspace_id", "sync_runs", ["workspace_id"])
    op.create_index("ix_sync_run_workspace_status", "sync_runs", ["workspace_id", "status"])


def downgrade() -> None:
    op.drop_table("sync_runs")
    op.drop_table("product_matches")
    op.drop_table("price_observations")
    op.drop_table("listings")
    op.drop_table("workspace_stores")
    op.drop_table("marketplace_stores")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    op.drop_table("users")

    bind = op.get_bind()
    sync_status.drop(bind, checkfirst=True)
    match_status.drop(bind, checkfirst=True)
    match_source.drop(bind, checkfirst=True)
    store_kind.drop(bind, checkfirst=True)
    workspace_role.drop(bind, checkfirst=True)
