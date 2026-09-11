"""Переоцінка каталогу: запуски та їхні рядки з доказами.

Revision ID: 20260911_0014
Revises: 20260829_0013
Create Date: 2026-09-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0014"
down_revision: str | None = "20260829_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE = sa.Enum("full", "partial", name="reprice_scope")
_MODE = sa.Enum("fresh", "resume", "carry_over", name="reprice_mode")
_POLICY = sa.Enum("aggressive", "balanced", "hold_margin", name="reprice_policy")
_OUTCOME = sa.Enum(
    "changed", "unchanged", "no_recommendation", name="reprice_outcome"
)
_ITEM_STATUS = sa.Enum("pending", "done", "failed", name="reprice_item_status")


def upgrade() -> None:
    op.create_table(
        "reprice_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid()),
        sa.Column("scope", _SCOPE, nullable=False),
        sa.Column("mode", _MODE, nullable=False),
        sa.Column("policy", _POLICY, nullable=False),
        sa.Column(
            "order_strategy",
            sa.String(32),
            server_default="value_at_risk",
            nullable=False,
        ),
        sa.Column("requested_count", sa.Integer()),
        sa.Column(
            "engine",
            sa.String(64),
            server_default="legacy_min_minus",
            nullable=False,
        ),
        sa.Column("catalog_scope_signature", sa.String(40), nullable=False),
        sa.Column(
            "catalog_item_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("store_ids", sa.JSON()),
        sa.Column("filter_json", sa.JSON()),
        sa.Column("changed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unchanged_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reprice_runs_workspace_id", "reprice_runs", ["workspace_id"])
    op.create_index("ix_reprice_runs_sync_run_id", "reprice_runs", ["sync_run_id"])
    op.create_index(
        "ix_reprice_run_workspace_created",
        "reprice_runs",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_reprice_run_catalog_signature",
        "reprice_runs",
        ["catalog_scope_signature"],
    )

    op.create_table(
        "reprice_run_items",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("group_key", sa.String(255)),
        sa.Column("status", _ITEM_STATUS, nullable=False),
        sa.Column("outcome", _OUTCOME),
        sa.Column("reason", sa.String(255)),
        sa.Column("old_price", sa.Numeric(14, 2)),
        sa.Column("new_price", sa.Numeric(14, 2)),
        sa.Column("delta_abs", sa.Numeric(14, 2)),
        sa.Column("delta_pct", sa.Numeric(7, 2)),
        sa.Column("price_at_compute", sa.Numeric(14, 2)),
        sa.Column("zone", sa.String(32)),
        sa.Column("tier", sa.String(32)),
        sa.Column("method", sa.String(64)),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("offers_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("evidence", sa.JSON()),
        sa.Column("computed_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
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
            ["run_id"], ["reprice_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"], ["listings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id", "listing_id"),
    )
    op.create_index(
        "ix_reprice_item_run_position", "reprice_run_items", ["run_id", "position"]
    )
    op.create_index("ix_reprice_item_listing", "reprice_run_items", ["listing_id"])


def downgrade() -> None:
    op.drop_index("ix_reprice_item_listing", table_name="reprice_run_items")
    op.drop_index("ix_reprice_item_run_position", table_name="reprice_run_items")
    op.drop_table("reprice_run_items")
    op.drop_index("ix_reprice_run_catalog_signature", table_name="reprice_runs")
    op.drop_index("ix_reprice_run_workspace_created", table_name="reprice_runs")
    op.drop_index("ix_reprice_runs_sync_run_id", table_name="reprice_runs")
    op.drop_index("ix_reprice_runs_workspace_id", table_name="reprice_runs")
    op.drop_table("reprice_runs")
    bind = op.get_bind()
    for enum_type in (_ITEM_STATUS, _OUTCOME, _POLICY, _MODE, _SCOPE):
        enum_type.drop(bind, checkfirst=True)
