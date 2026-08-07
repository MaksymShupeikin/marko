"""Add Luna identity and deterministic pricing-admission contract v2.

Revision ID: 20260804_0044
Revises: 20260802_0043
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260804_0044"
down_revision = "20260802_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_comparability_reviews",
        sa.Column(
            "contract_version",
            sa.String(length=40),
            server_default="comparability-v1",
            nullable=False,
        ),
    )
    for column in (
        sa.Column("reasoning_effort", sa.String(length=16), nullable=True),
        sa.Column("model_settings_hash", sa.String(length=64), nullable=True),
        sa.Column("identity_verdict", sa.String(length=24), nullable=True),
        sa.Column("identity_match_level", sa.String(length=32), nullable=True),
        sa.Column("identity_match_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("decision_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("image_consistency", sa.String(length=24), nullable=True),
        sa.Column("pricing_admission", sa.String(length=24), nullable=True),
        sa.Column("rate_card_version", sa.String(length=120), nullable=True),
    ):
        op.add_column("candidate_comparability_reviews", column)
    for name, default in (
        ("reason_codes", "'[]'::json"),
        ("pricing_reason_codes", "'[]'::json"),
        ("estimated_cost", "'{}'::json"),
    ):
        op.add_column(
            "candidate_comparability_reviews",
            sa.Column(
                name,
                sa.JSON(),
                server_default=sa.text(default),
                nullable=False,
            ),
        )

    op.create_check_constraint(
        "ck_candidate_comparability_review_contract",
        "candidate_comparability_reviews",
        "contract_version IN ('comparability-v1', 'comparability-v2')",
    )
    op.create_check_constraint(
        "ck_candidate_comparability_review_v2_complete",
        "candidate_comparability_reviews",
        "contract_version <> 'comparability-v2' OR ("
        "identity_verdict IN ('MATCH', 'NOT_MATCH', 'MANUAL_REVIEW') AND "
        "identity_match_level IN "
        "('EXACT', 'ACCEPTABLE_ANALOGUE', 'SUSPICIOUS', 'NOT_APPLICABLE') AND "
        "identity_match_score >= 0 AND identity_match_score <= 1 AND "
        "decision_confidence >= 0 AND decision_confidence <= 1 AND "
        "image_consistency IN "
        "('SUPPORTS', 'CONFLICTS', 'NON_DIAGNOSTIC', 'UNAVAILABLE') AND "
        "pricing_admission IN ('ADMITTED', 'EXCLUDED', 'MANUAL_REVIEW') AND "
        "reasoning_effort IN ('none', 'low', 'medium', 'high', 'xhigh', 'max') AND "
        "char_length(model_settings_hash) = 64)",
    )
    op.create_check_constraint(
        "ck_candidate_comparability_review_v2_identity_level",
        "candidate_comparability_reviews",
        "contract_version <> 'comparability-v2' OR "
        "((identity_verdict = 'MATCH' AND identity_match_level IN "
        "('EXACT', 'ACCEPTABLE_ANALOGUE')) OR "
        "(identity_verdict <> 'MATCH' AND identity_match_level IN "
        "('SUSPICIOUS', 'NOT_APPLICABLE')))",
    )
    op.create_check_constraint(
        "ck_candidate_comparability_review_v2_projection",
        "candidate_comparability_reviews",
        "contract_version <> 'comparability-v2' OR "
        "((pricing_admission = 'ADMITTED' AND verdict = 'COMPARABLE') OR "
        "(pricing_admission = 'EXCLUDED' AND verdict = 'NOT_COMPARABLE') OR "
        "(pricing_admission = 'MANUAL_REVIEW' AND verdict = 'INSUFFICIENT_DATA'))",
    )
    for column in (
        "model_settings_hash",
        "identity_verdict",
        "pricing_admission",
    ):
        op.create_index(
            f"ix_candidate_comparability_reviews_{column}",
            "candidate_comparability_reviews",
            [column],
        )
    op.create_index(
        "ix_candidate_comparability_review_model_settings",
        "candidate_comparability_reviews",
        ["workspace_id", "input_hash", "model_settings_hash"],
    )

    for column in (
        sa.Column("corrected_identity_verdict", sa.String(length=24), nullable=True),
        sa.Column(
            "corrected_identity_match_level", sa.String(length=32), nullable=True
        ),
        sa.Column("corrected_pricing_admission", sa.String(length=24), nullable=True),
    ):
        op.add_column("candidate_comparability_feedback", column)
    op.create_check_constraint(
        "ck_candidate_comparability_feedback_identity_verdict",
        "candidate_comparability_feedback",
        "corrected_identity_verdict IS NULL OR corrected_identity_verdict IN "
        "('MATCH', 'NOT_MATCH', 'MANUAL_REVIEW')",
    )
    op.create_check_constraint(
        "ck_candidate_comparability_feedback_identity_level",
        "candidate_comparability_feedback",
        "corrected_identity_match_level IS NULL OR corrected_identity_match_level IN "
        "('EXACT', 'ACCEPTABLE_ANALOGUE', 'SUSPICIOUS', 'NOT_APPLICABLE')",
    )
    op.create_check_constraint(
        "ck_candidate_comparability_feedback_pricing_admission",
        "candidate_comparability_feedback",
        "corrected_pricing_admission IS NULL OR corrected_pricing_admission IN "
        "('ADMITTED', 'EXCLUDED', 'MANUAL_REVIEW')",
    )
    op.create_check_constraint(
        "ck_candidate_comparability_feedback_v2_correction",
        "candidate_comparability_feedback",
        "(corrected_identity_verdict IS NULL AND "
        "corrected_identity_match_level IS NULL AND "
        "corrected_pricing_admission IS NULL) OR "
        "(decision = 'CORRECT' AND corrected_identity_verdict IS NOT NULL AND "
        "corrected_identity_match_level IS NOT NULL AND "
        "corrected_pricing_admission IS NOT NULL)",
    )


def downgrade() -> None:
    bind = op.get_bind()
    v2_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM candidate_comparability_reviews "
            "WHERE contract_version = 'comparability-v2'"
        )
    ).scalar_one()
    v2_feedback_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM candidate_comparability_feedback "
            "WHERE corrected_identity_verdict IS NOT NULL"
        )
    ).scalar_one()
    if int(v2_count) or int(v2_feedback_count):
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260804_0044: "
            f"{int(v2_count)} v2 review(s) and {int(v2_feedback_count)} "
            "v2 feedback row(s) would lose evidence"
        )

    for name in (
        "ck_candidate_comparability_feedback_v2_correction",
        "ck_candidate_comparability_feedback_pricing_admission",
        "ck_candidate_comparability_feedback_identity_level",
        "ck_candidate_comparability_feedback_identity_verdict",
    ):
        op.drop_constraint(name, "candidate_comparability_feedback", type_="check")
    for column in (
        "corrected_pricing_admission",
        "corrected_identity_match_level",
        "corrected_identity_verdict",
    ):
        op.drop_column("candidate_comparability_feedback", column)

    op.drop_index(
        "ix_candidate_comparability_review_model_settings",
        table_name="candidate_comparability_reviews",
    )
    for column in (
        "pricing_admission",
        "identity_verdict",
        "model_settings_hash",
    ):
        op.drop_index(
            f"ix_candidate_comparability_reviews_{column}",
            table_name="candidate_comparability_reviews",
        )
    for name in (
        "ck_candidate_comparability_review_v2_projection",
        "ck_candidate_comparability_review_v2_identity_level",
        "ck_candidate_comparability_review_v2_complete",
        "ck_candidate_comparability_review_contract",
    ):
        op.drop_constraint(name, "candidate_comparability_reviews", type_="check")
    for column in (
        "rate_card_version",
        "estimated_cost",
        "pricing_reason_codes",
        "pricing_admission",
        "reason_codes",
        "image_consistency",
        "decision_confidence",
        "identity_match_score",
        "identity_match_level",
        "identity_verdict",
        "model_settings_hash",
        "reasoning_effort",
        "contract_version",
    ):
        op.drop_column("candidate_comparability_reviews", column)
