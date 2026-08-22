"""Card-level comparability: its own ledger, because a storefront card has no run item.

The paid comparability review already had a home, but only inside a pricing
run: ``pricing_discovery_reviews.pricing_run_item_id`` is NOT NULL and points
at a row whose ``catalog_item_id`` exists solely for imported XLSX positions.
A Prom storefront card -- the whole population the "Сопоставить" button exists
for -- can never have one, so nulling that column would not be a relaxation but
an unsatisfiable foreign key. Worse, PostgreSQL treats NULLs as distinct in a
unique constraint, so ``uq_pricing_discovery_review_item_offer`` would stop
holding and a second click would silently buy the same verdict twice.

Revision ID: 20260822_0056
Revises: 20260818_0055
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260822_0056"
down_revision: str | None = "20260818_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_match_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_key", sa.String(length=64), nullable=False),
        sa.Column(
            "discovery_run_id",
            sa.Uuid(),
            sa.ForeignKey("catalog_discovery_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="queued"
        ),
        sa.Column(
            "product_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("offer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("group_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "reviewed_group_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "comparable_group_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("minimum_comparable_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("advisory_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column(
            "grouping_summary",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_catalog_match_run_status",
        ),
    )
    op.create_index(
        "ix_catalog_match_runs_workspace_id", "catalog_match_runs", ["workspace_id"]
    )
    op.create_index(
        "ix_catalog_match_runs_product_key", "catalog_match_runs", ["product_key"]
    )
    op.create_index(
        "ix_catalog_match_runs_discovery_run_id",
        "catalog_match_runs",
        ["discovery_run_id"],
    )
    op.create_index(
        "ix_catalog_match_run_workspace_product_time",
        "catalog_match_runs",
        ["workspace_id", "product_key", "created_at"],
    )

    op.create_table(
        "catalog_match_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "catalog_match_run_id",
            sa.Uuid(),
            sa.ForeignKey("catalog_match_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "catalog_discovery_offer_id",
            sa.Uuid(),
            sa.ForeignKey("catalog_discovery_offers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("group_key", sa.String(length=512), nullable=False),
        sa.Column(
            "offer_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column(
            "seller_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column(
            "gate_rejected_reasons",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "evidence_references",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "conflicts", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("output_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("reasoning_effort", sa.String(length=16), nullable=False),
        sa.Column("canonical_input", sa.JSON(), nullable=False),
        sa.Column("canonical_output", sa.JSON(), nullable=False),
        sa.Column(
            "usage", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        sa.Column(
            "estimated_cost",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("rate_card_version", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "catalog_match_run_id",
            "group_key",
            name="uq_catalog_match_review_run_group",
        ),
        sa.CheckConstraint(
            "verdict IN ('MATCH', 'NO_MATCH', 'INSUFFICIENT_EVIDENCE')",
            name="ck_catalog_match_review_verdict",
        ),
        sa.CheckConstraint(
            "char_length(prompt_sha256) = 64 AND char_length(schema_sha256) = 64 "
            "AND char_length(model_sha256) = 64 AND char_length(input_sha256) = 64 "
            "AND char_length(output_sha256) = 64",
            name="ck_catalog_match_review_hashes",
        ),
    )
    op.create_index(
        "ix_catalog_match_reviews_workspace_id",
        "catalog_match_reviews",
        ["workspace_id"],
    )
    op.create_index(
        "ix_catalog_match_reviews_run_id",
        "catalog_match_reviews",
        ["catalog_match_run_id"],
    )
    op.create_index(
        "ix_catalog_match_reviews_offer_id",
        "catalog_match_reviews",
        ["catalog_discovery_offer_id"],
    )
    op.create_index(
        "ix_catalog_match_review_cache",
        "catalog_match_reviews",
        ["workspace_id", "input_sha256"],
    )


def downgrade() -> None:
    op.drop_table("catalog_match_reviews")
    op.drop_table("catalog_match_runs")
