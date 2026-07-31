"""Add immutable LLM candidate-comparability reviews and customer labels.

Revision ID: 20260731_0031
Revises: 20260730_0030
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260731_0031"
down_revision: str | None = "20260730_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "market_observations",
        sa.Column(
            "candidate_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )

    op.create_table(
        "candidate_comparability_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("market_observation_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("decision_source", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("verdict", sa.String(length=24), nullable=False),
        sa.Column("match_level", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "dimension_findings",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "hard_stop_conflicts",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "image_urls",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("cache_hit_review_id", sa.Uuid(), nullable=True),
        sa.Column("provider_response_id", sa.String(length=255), nullable=True),
        sa.Column("provider_model", sa.String(length=160), nullable=True),
        sa.Column(
            "usage",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('COMPLETED', 'HARD_STOP', 'CACHED', 'FAILED', 'SKIPPED')",
            name="ck_candidate_comparability_review_status",
        ),
        sa.CheckConstraint(
            "verdict IN ('COMPARABLE', 'NOT_COMPARABLE', 'INSUFFICIENT_DATA')",
            name="ck_candidate_comparability_review_verdict",
        ),
        sa.CheckConstraint(
            "match_level IN "
            "('EXACT', 'ACCEPTABLE_ANALOGUE', 'SUSPICIOUS', 'NOT_APPLICABLE')",
            name="ck_candidate_comparability_review_match_level",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_candidate_comparability_review_confidence",
        ),
        sa.CheckConstraint(
            "(verdict = 'COMPARABLE' AND "
            "match_level IN ('EXACT', 'ACCEPTABLE_ANALOGUE')) OR "
            "(verdict <> 'COMPARABLE' AND "
            "match_level IN ('SUSPICIOUS', 'NOT_APPLICABLE'))",
            name="ck_candidate_comparability_review_positive_level",
        ),
        sa.CheckConstraint(
            "decision_source IN "
            "('LLM', 'HARD_RULE', 'CACHE', 'HUMAN_CACHE', 'UNCONFIGURED')",
            name="ck_candidate_comparability_review_source",
        ),
        sa.CheckConstraint(
            "(decision_source IN ('CACHE', 'HUMAN_CACHE') AND "
            "cache_hit_review_id IS NOT NULL) OR "
            "(decision_source NOT IN ('CACHE', 'HUMAN_CACHE') AND "
            "cache_hit_review_id IS NULL)",
            name="ck_candidate_comparability_review_cache_source",
        ),
        sa.CheckConstraint(
            "status NOT IN ('FAILED', 'SKIPPED') OR verdict = 'INSUFFICIENT_DATA'",
            name="ck_candidate_comparability_review_failure_verdict",
        ),
        sa.CheckConstraint(
            "attempt_no > 0",
            name="ck_candidate_comparability_review_attempt",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name="ck_candidate_comparability_review_latency",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_observation_id"],
            ["market_observations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"],
            ["catalog_items.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cache_hit_review_id"],
            ["candidate_comparability_reviews.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_key",
            name="uq_candidate_comparability_review_request_key",
        ),
    )
    op.create_index(
        "ix_candidate_comparability_review_observation_time",
        "candidate_comparability_reviews",
        ["market_observation_id", "reviewed_at"],
    )
    op.create_index(
        "ix_candidate_comparability_review_cache",
        "candidate_comparability_reviews",
        ["workspace_id", "input_hash", "prompt_version", "model_id"],
    )
    for column in (
        "workspace_id",
        "market_observation_id",
        "catalog_item_id",
        "request_key",
        "input_hash",
        "verdict",
        "cache_hit_review_id",
    ):
        op.create_index(
            f"ix_candidate_comparability_reviews_{column}",
            "candidate_comparability_reviews",
            [column],
        )

    op.create_table(
        "candidate_comparability_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("market_observation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("corrected_verdict", sa.String(length=24), nullable=True),
        sa.Column("corrected_match_level", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "evidence_corrections",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('CONFIRM', 'CORRECT')",
            name="ck_candidate_comparability_feedback_decision",
        ),
        sa.CheckConstraint(
            "corrected_verdict IS NULL OR corrected_verdict IN "
            "('COMPARABLE', 'NOT_COMPARABLE', 'INSUFFICIENT_DATA')",
            name="ck_candidate_comparability_feedback_verdict",
        ),
        sa.CheckConstraint(
            "corrected_match_level IS NULL OR corrected_match_level IN "
            "('EXACT', 'ACCEPTABLE_ANALOGUE', 'SUSPICIOUS', 'NOT_APPLICABLE')",
            name="ck_candidate_comparability_feedback_level",
        ),
        sa.CheckConstraint(
            "(decision = 'CONFIRM' AND corrected_verdict IS NULL AND "
            "corrected_match_level IS NULL) OR "
            "(decision = 'CORRECT' AND corrected_verdict IS NOT NULL AND "
            "corrected_match_level IS NOT NULL)",
            name="ck_candidate_comparability_feedback_correction",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_candidate_comparability_feedback_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["candidate_comparability_reviews.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_observation_id"],
            ["market_observations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_candidate_comparability_feedback_review_time",
        "candidate_comparability_feedback",
        ["review_id", "created_at"],
    )
    for column in ("workspace_id", "review_id", "market_observation_id", "user_id"):
        op.create_index(
            f"ix_candidate_comparability_feedback_{column}",
            "candidate_comparability_feedback",
            [column],
        )

    for table in (
        "candidate_comparability_reviews",
        "candidate_comparability_feedback",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION marko_reject_append_only_mutation()"
        )


def downgrade() -> None:
    evidence_counts = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM candidate_comparability_reviews)
                        AS review_count,
                    (SELECT count(*) FROM candidate_comparability_feedback)
                        AS feedback_count,
                    (
                        SELECT count(*)
                        FROM market_observations
                        WHERE candidate_snapshot::jsonb <> '{}'::jsonb
                    ) AS snapshot_count
                """
            )
        )
        .one()
    )
    if any(int(value) for value in evidence_counts):
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260731_0031: "
            f"{int(evidence_counts.review_count)} review(s), "
            f"{int(evidence_counts.feedback_count)} feedback row(s), and "
            f"{int(evidence_counts.snapshot_count)} candidate snapshot(s) "
            "would be erased; restore a pre-migration PostgreSQL backup "
            "instead of downgrading"
        )

    for table in (
        "candidate_comparability_feedback",
        "candidate_comparability_reviews",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.drop_table("candidate_comparability_feedback")
    op.drop_table("candidate_comparability_reviews")
    op.drop_column("market_observations", "candidate_snapshot")
