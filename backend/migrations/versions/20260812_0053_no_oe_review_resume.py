"""Add bounded no-OE human review and resume persistence.

Revision ID: 20260812_0053
Revises: 20260812_0052
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0053"
down_revision: str | None = "20260812_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_pricing_run_active_import_batch", table_name="pricing_runs")
    op.drop_constraint("ck_pricing_run_status", "pricing_runs", type_="check")
    op.create_check_constraint(
        "ck_pricing_run_status",
        "pricing_runs",
        "status IN ('queued', 'running', 'collecting', 'classifying', 'calibrating', "
        "'calculating', 'awaiting_review', 'completed', 'partial', 'failed', 'cancelled')",
    )
    op.create_index(
        "uq_pricing_run_active_import_batch",
        "pricing_runs",
        ["workspace_id", "import_batch_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued', 'running', 'collecting', 'classifying', "
            "'calibrating', 'calculating', 'awaiting_review')"
        ),
    )
    op.add_column("pricing_runs", sa.Column("review_snapshot_hash", sa.String(64)))
    op.add_column(
        "pricing_runs", sa.Column("review_frozen_at", sa.DateTime(timezone=True))
    )

    op.drop_constraint("ck_pricing_run_item_status", "pricing_run_items", type_="check")
    op.alter_column(
        "pricing_run_items",
        "status",
        existing_type=sa.String(20),
        type_=sa.String(32),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_pricing_run_item_status",
        "pricing_run_items",
        "status IN ('queued', 'discovering', 'awaiting_discovery_review', "
        "'review_frozen', 'collecting', 'collected', 'classified', 'calculating', "
        "'calculated', 'manual_review', 'failed', 'cancelled')",
    )
    op.add_column("pricing_run_items", sa.Column("no_oe_discovery_run_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_pricing_run_items_no_oe_discovery_run",
        "pricing_run_items",
        "catalog_discovery_runs",
        ["no_oe_discovery_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_pricing_run_items_no_oe_discovery_run_id",
        "pricing_run_items",
        ["no_oe_discovery_run_id"],
    )

    op.create_table(
        "pricing_discovery_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_item_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_discovery_offer_id", sa.Uuid(), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "evidence_references", sa.JSON(), server_default="[]", nullable=False
        ),
        sa.Column("conflicts", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("offer_sha256", sa.String(64), nullable=False),
        sa.Column("prompt_sha256", sa.String(64), nullable=False),
        sa.Column("schema_sha256", sa.String(64), nullable=False),
        sa.Column("model_sha256", sa.String(64), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("reasoning_effort", sa.String(16), nullable=False),
        sa.Column("canonical_input", sa.JSON(), nullable=False),
        sa.Column("canonical_output", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "verdict IN ('MATCH', 'NO_MATCH', 'INSUFFICIENT_EVIDENCE')",
            name="ck_pricing_discovery_review_verdict",
        ),
        sa.CheckConstraint(
            "char_length(offer_sha256) = 64 AND char_length(prompt_sha256) = 64 "
            "AND char_length(schema_sha256) = 64 AND char_length(model_sha256) = 64 "
            "AND char_length(input_sha256) = 64 AND char_length(output_sha256) = 64",
            name="ck_pricing_discovery_review_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_id"], ["pricing_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_item_id"], ["pricing_run_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_discovery_offer_id"],
            ["catalog_discovery_offers.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pricing_run_item_id",
            "catalog_discovery_offer_id",
            name="uq_pricing_discovery_review_item_offer",
        ),
    )
    for column in (
        "workspace_id",
        "pricing_run_id",
        "pricing_run_item_id",
        "catalog_discovery_offer_id",
    ):
        op.create_index(
            f"ix_pricing_discovery_reviews_{column}",
            "pricing_discovery_reviews",
            [column],
        )

    op.create_table(
        "pricing_discovery_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_item_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_discovery_offer_id", sa.Uuid(), nullable=False),
        sa.Column("luna_review_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("actor_type", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("offer_sha256", sa.String(64), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("measure_unit", sa.String(80)),
        sa.Column("is_available", sa.Boolean()),
        sa.Column("seller_id", sa.String(255), nullable=False),
        sa.Column("offer_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('APPROVE', 'REJECT')",
            name="ck_pricing_discovery_decision_value",
        ),
        sa.CheckConstraint(
            "price > 0 AND char_length(offer_sha256) = 64",
            name="ck_pricing_discovery_decision_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_id"], ["pricing_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_item_id"], ["pricing_run_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_discovery_offer_id"],
            ["catalog_discovery_offers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["luna_review_id"], ["pricing_discovery_reviews.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_pricing_discovery_decision_idempotency",
        ),
    )
    for column in (
        "workspace_id",
        "pricing_run_id",
        "pricing_run_item_id",
        "catalog_discovery_offer_id",
        "luna_review_id",
    ):
        op.create_index(
            f"ix_pricing_discovery_decisions_{column}",
            "pricing_discovery_decisions",
            [column],
        )
    op.create_index(
        "ix_pricing_discovery_decision_item_offer_time",
        "pricing_discovery_decisions",
        ["pricing_run_item_id", "catalog_discovery_offer_id", "created_at"],
    )
    for table_name in (
        "pricing_discovery_reviews",
        "pricing_discovery_decisions",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table_name} FOR EACH ROW "
            "EXECUTE FUNCTION marko_reject_append_only_mutation()"
        )


def downgrade() -> None:
    op.drop_table("pricing_discovery_decisions")
    op.drop_table("pricing_discovery_reviews")
    op.drop_index(
        "ix_pricing_run_items_no_oe_discovery_run_id", table_name="pricing_run_items"
    )
    op.drop_constraint(
        "fk_pricing_run_items_no_oe_discovery_run",
        "pricing_run_items",
        type_="foreignkey",
    )
    op.drop_column("pricing_run_items", "no_oe_discovery_run_id")
    op.drop_constraint("ck_pricing_run_item_status", "pricing_run_items", type_="check")
    op.create_check_constraint(
        "ck_pricing_run_item_status",
        "pricing_run_items",
        "status IN ('queued', 'collecting', 'collected', 'classified', 'calculating', "
        "'calculated', 'manual_review', 'failed', 'cancelled')",
    )
    op.alter_column(
        "pricing_run_items",
        "status",
        existing_type=sa.String(32),
        type_=sa.String(20),
        existing_nullable=False,
    )
    op.drop_column("pricing_runs", "review_frozen_at")
    op.drop_column("pricing_runs", "review_snapshot_hash")
    op.drop_index("uq_pricing_run_active_import_batch", table_name="pricing_runs")
    op.drop_constraint("ck_pricing_run_status", "pricing_runs", type_="check")
    op.create_check_constraint(
        "ck_pricing_run_status",
        "pricing_runs",
        "status IN ('queued', 'running', 'collecting', 'classifying', 'calibrating', "
        "'calculating', 'completed', 'partial', 'failed', 'cancelled')",
    )
    op.create_index(
        "uq_pricing_run_active_import_batch",
        "pricing_runs",
        ["workspace_id", "import_batch_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued', 'running', 'collecting', 'classifying', "
            "'calibrating', 'calculating')"
        ),
    )
