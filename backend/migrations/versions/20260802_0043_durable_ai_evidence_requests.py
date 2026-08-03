"""Pre-commit AI request events, append-only leases, and terminal binding.

Revision ID: 20260802_0043
Revises: 20260802_0042
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260802_0043"
down_revision = "20260802_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_evidence_request_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_item_id", sa.Uuid(), nullable=False),
        sa.Column("market_observation_id", sa.Uuid(), nullable=False),
        sa.Column("raw_capture_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("source_listing_id", sa.String(length=255), nullable=False),
        sa.Column("capture_sha256", sa.String(length=64), nullable=False),
        sa.Column("candidate_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_offer_locator_sha256", sa.String(length=64), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("prepared_input_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_settings_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=False),
        sa.Column("verifier_version", sa.String(length=80), nullable=False),
        sa.Column("oe_normalization_version", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("reasoning_effort", sa.String(length=16), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("max_input_chars", sa.Integer(), nullable=False),
        sa.Column("target_fields", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("attempt_no > 0", name="ck_ai_evidence_request_attempt"),
        sa.CheckConstraint(
            "char_length(request_key) = 64 AND char_length(input_hash) = 64 AND "
            "char_length(prepared_input_sha256) = 64 AND char_length(capture_sha256) = 64 AND "
            "char_length(candidate_snapshot_sha256) = 64 AND "
            "char_length(source_offer_locator_sha256) = 64 AND "
            "char_length(document_sha256) = 64 AND char_length(model_settings_sha256) = 64",
            name="ck_ai_evidence_request_digest_shape",
        ),
        sa.CheckConstraint(
            "max_output_tokens > 0 AND max_input_chars > 0",
            name="ck_ai_evidence_request_bounds",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_item_id"], ["pricing_run_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["market_observation_id"], ["market_observations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["raw_capture_id"], ["raw_market_captures.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_key", name="uq_ai_evidence_request_event_key"),
        sa.UniqueConstraint(
            "workspace_id",
            "market_observation_id",
            "input_hash",
            "attempt_no",
            name="uq_ai_evidence_request_event_attempt",
        ),
    )
    op.create_index(
        "ix_ai_evidence_request_input",
        "ai_evidence_request_events",
        ["workspace_id", "market_observation_id", "input_hash", "attempt_no"],
    )
    for column in (
        "workspace_id",
        "pricing_run_item_id",
        "market_observation_id",
        "raw_capture_id",
        "request_key",
        "input_hash",
    ):
        op.create_index(
            f"ix_ai_evidence_request_events_{column}",
            "ai_evidence_request_events",
            [column],
            unique=column == "request_key",
        )

    op.create_table(
        "ai_evidence_request_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_event_id", sa.Uuid(), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=False),
        sa.Column("recovery", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_event_id"],
            ["ai_evidence_request_events.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_token", name="uq_ai_evidence_request_claim_token"),
    )
    op.create_index(
        "ix_ai_evidence_request_claim_latest",
        "ai_evidence_request_claims",
        ["request_event_id", "claimed_at"],
    )
    op.create_index(
        "ix_ai_evidence_request_claims_request_event_id",
        "ai_evidence_request_claims",
        ["request_event_id"],
    )
    op.create_index(
        "ix_ai_evidence_request_claims_claim_token",
        "ai_evidence_request_claims",
        ["claim_token"],
        unique=True,
    )

    op.add_column(
        "ai_evidence_extractions",
        sa.Column("request_event_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ai_evidence_extraction_request_event",
        "ai_evidence_extractions",
        "ai_evidence_request_events",
        ["request_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_ai_evidence_extractions_request_event_id",
        "ai_evidence_extractions",
        ["request_event_id"],
        unique=True,
    )

    for table in ("ai_evidence_request_events", "ai_evidence_request_claims"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION marko_reject_append_only_mutation()"
        )


def downgrade() -> None:
    bind = op.get_bind()
    event_count = bind.execute(
        sa.text("SELECT count(*) FROM ai_evidence_request_events")
    ).scalar_one()
    claim_count = bind.execute(
        sa.text("SELECT count(*) FROM ai_evidence_request_claims")
    ).scalar_one()
    if int(event_count) or int(claim_count):
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260802_0043: "
            f"{int(event_count)} AI evidence request event(s) and "
            f"{int(claim_count)} request claim(s) would be erased; "
            "restore a pre-migration PostgreSQL backup instead of downgrading"
        )

    op.drop_index(
        "ix_ai_evidence_extractions_request_event_id",
        table_name="ai_evidence_extractions",
    )
    op.drop_constraint(
        "fk_ai_evidence_extraction_request_event",
        "ai_evidence_extractions",
        type_="foreignkey",
    )
    op.drop_column("ai_evidence_extractions", "request_event_id")
    for table in ("ai_evidence_request_claims", "ai_evidence_request_events"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.drop_table("ai_evidence_request_claims")
    op.drop_table("ai_evidence_request_events")
