"""Add human-in-the-loop competitive pricing and learning spine.

Revision ID: 20260721_0020
Revises: 20260721_0019
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_0020"
down_revision: str | None = "20260721_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "market_observations",
        sa.Column("sale_price", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "market_observations",
        sa.Column("reference_price", sa.Numeric(14, 2), nullable=True),
    )
    op.execute("UPDATE market_observations SET sale_price = price")
    op.create_check_constraint(
        "ck_market_observation_price_boundaries",
        "market_observations",
        "(sale_price IS NULL OR sale_price > 0) AND "
        "(reference_price IS NULL OR reference_price > 0)",
    )

    op.add_column(
        "fitment_analyses",
        sa.Column(
            "workflow_state", sa.String(length=40), nullable=False, server_default="NEW"
        ),
    )
    op.execute(
        "UPDATE fitment_analyses SET workflow_state = CASE "
        "WHEN status = 'completed' THEN 'FITMENT_EVALUATED' "
        "WHEN status = 'failed' THEN 'FAILED' "
        "WHEN status = 'partial' THEN 'PARTIAL_FAILURE' "
        "ELSE 'EVIDENCE_COLLECTION_STARTED' END"
    )
    op.alter_column("fitment_analyses", "workflow_state", server_default=None)
    op.create_check_constraint(
        "ck_fit_analysis_workflow_state",
        "fitment_analyses",
        "workflow_state IN ('NEW','NORMALIZED','TARGET_VERIFICATION_STARTED',"
        "'TARGET_VERIFIED','CANDIDATES_DISCOVERED','SELLERS_RESOLVED',"
        "'EVIDENCE_COLLECTION_STARTED','EVIDENCE_COLLECTED','FITMENT_EVALUATED',"
        "'PRICE_COMPARABILITY_EVALUATED','MARKET_ANALYZED','RECOMMENDATION_READY',"
        "'NOTIFIED','UNDER_REVIEW','ACCEPTED','ACCEPTED_WITH_MODIFICATION',"
        "'REJECTED','DEFERRED','RESEARCH_REQUESTED','PARTIAL_FAILURE','FAILED')",
    )
    op.create_index(
        "ix_fitment_analyses_workflow_state",
        "fitment_analyses",
        ["workflow_state"],
    )

    op.add_column(
        "fitment_candidate_assessments",
        sa.Column("normalized_unit_price", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "fitment_candidate_assessments",
        sa.Column(
            "price_unit_status",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "fitment_candidate_assessments",
        sa.Column(
            "price_unit_certainty",
            sa.Numeric(5, 4),
            nullable=False,
            server_default="0.3",
        ),
    )
    op.alter_column(
        "fitment_candidate_assessments", "price_unit_status", server_default=None
    )
    op.alter_column(
        "fitment_candidate_assessments", "price_unit_certainty", server_default=None
    )
    op.create_check_constraint(
        "ck_fit_assessment_price_unit",
        "fitment_candidate_assessments",
        "price_unit_status IN ('verified_piece','normalized_pair',"
        "'normalized_axle_set','normalized_kit','unknown','incompatible') "
        "AND price_unit_certainty BETWEEN 0 AND 1 "
        "AND (normalized_unit_price IS NULL OR normalized_unit_price > 0)",
    )

    op.add_column(
        "fitment_evidence_claims",
        sa.Column(
            "directness", sa.Numeric(5, 4), nullable=False, server_default="1"
        ),
    )
    op.alter_column("fitment_evidence_claims", "directness", server_default=None)
    op.drop_constraint(
        "ck_fit_evidence_feature", "fitment_evidence_claims", type_="check"
    )
    op.create_check_constraint(
        "ck_fit_evidence_feature",
        "fitment_evidence_claims",
        "feature IN ('article_identity','oe_exact','oe_supersession',"
        "'cross_confirmed','part_category','axle','side','vehicle_make_model',"
        "'generation','year_overlap','engine','body','vehicle_market',"
        "'technical_specs')",
    )
    op.drop_constraint(
        "ck_fit_evidence_factors", "fitment_evidence_claims", type_="check"
    )
    op.create_check_constraint(
        "ck_fit_evidence_factors",
        "fitment_evidence_claims",
        "source_reliability BETWEEN 0 AND 1 "
        "AND extraction_confidence BETWEEN 0 AND 1 "
        "AND directness BETWEEN 0 AND 1 "
        "AND independence_factor BETWEEN 0 AND 1 "
        "AND freshness_factor BETWEEN 0 AND 1",
    )

    op.create_table(
        "fitment_source_capabilities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("authentication_required", sa.Boolean(), nullable=False),
        sa.Column("rate_limit", sa.String(length=120), nullable=False),
        sa.Column("retry_policy", sa.JSON(), nullable=False),
        sa.Column("cache_policy", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "capability IN ('search_by_article','search_by_oe','search_fitment',"
            "'fetch_document')",
            name="ck_fit_source_capability_name",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["fitment_sources.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "capability",
            "policy_version",
            name="uq_fit_source_capability_policy",
        ),
    )
    op.create_index(
        "ix_fit_source_capability_lookup",
        "fitment_source_capabilities",
        ["source_id", "capability"],
    )
    op.create_index(
        "ix_fitment_source_capabilities_source_id",
        "fitment_source_capabilities",
        ["source_id"],
    )

    op.create_table(
        "fitment_source_reliability_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("claim_type", sa.String(length=80), nullable=False),
        sa.Column("source_tier", sa.String(length=1), nullable=False),
        sa.Column("prior_alpha", sa.Numeric(12, 4), nullable=False),
        sa.Column("prior_beta", sa.Numeric(12, 4), nullable=False),
        sa.Column("confirmed_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("reliability", sa.Numeric(5, 4), nullable=False),
        sa.Column("label_event_key", sa.String(length=64), nullable=False),
        sa.Column("method_version", sa.String(length=80), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "prior_alpha > 0 AND prior_beta > 0 AND confirmed_count >= 0 "
            "AND rejected_count >= 0 AND reliability BETWEEN 0 AND 1",
            name="ck_fit_source_beta_values",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["fitment_sources.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["fitment_source_reliability_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "claim_type",
            "label_event_key",
            name="uq_fit_source_beta_event",
        ),
    )
    op.create_index(
        "ix_fit_source_beta_current",
        "fitment_source_reliability_snapshots",
        ["source_id", "claim_type", "created_at"],
    )
    for column in ("source_id", "supersedes_id"):
        op.create_index(
            f"ix_fitment_source_reliability_snapshots_{column}",
            "fitment_source_reliability_snapshots",
            [column],
        )

    op.create_table(
        "fitment_market_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("current_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("recommended_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("recommended_range_min", sa.Numeric(14, 2), nullable=True),
        sa.Column("recommended_range_max", sa.Numeric(14, 2), nullable=True),
        sa.Column("absolute_change", sa.Numeric(14, 2), nullable=True),
        sa.Column("relative_change", sa.Numeric(12, 8), nullable=True),
        sa.Column("market_anchor", sa.Numeric(14, 2), nullable=True),
        sa.Column("approved_price_floor", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("confidence_factors", sa.JSON(), nullable=False),
        sa.Column("market_summary", sa.JSON(), nullable=False),
        sa.Column("price_statistics", sa.JSON(), nullable=False),
        sa.Column("candidate_decisions", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("configuration_snapshot", sa.JSON(), nullable=False),
        sa.Column("contract_version", sa.String(length=80), nullable=False),
        sa.Column("recommendation_version", sa.String(length=80), nullable=False),
        sa.Column(
            "automatic_price_change_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('consider_raise','hold','consider_reduce',"
            "'insufficient_evidence','manual_research_required')",
            name="ck_fit_market_rec_action",
        ),
        sa.CheckConstraint(
            "current_price > 0 AND confidence BETWEEN 0 AND 1 "
            "AND (recommended_price IS NULL OR recommended_price > 0) "
            "AND NOT automatic_price_change_allowed",
            name="ck_fit_market_rec_safety",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["fitment_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_fit_market_rec_idempotency"
        ),
        sa.UniqueConstraint(
            "analysis_id", "input_fingerprint", name="uq_fit_market_rec_snapshot"
        ),
    )
    op.create_index(
        "ix_fit_market_rec_product_time",
        "fitment_market_recommendations",
        ["catalog_item_id", "created_at"],
    )
    op.create_index(
        "ix_fit_market_rec_review",
        "fitment_market_recommendations",
        ["workspace_id", "action", "confidence"],
    )
    for column in ("workspace_id", "analysis_id", "catalog_item_id", "created_by"):
        op.create_index(
            f"ix_fitment_market_recommendations_{column}",
            "fitment_market_recommendations",
            [column],
        )

    op.create_table(
        "fitment_recommendation_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("approved_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("recommendation_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('accepted','accepted_with_modification','rejected',"
            "'deferred','research_requested')",
            name="ck_fit_rec_review_decision",
        ),
        sa.CheckConstraint(
            "(decision IN ('accepted','accepted_with_modification') "
            "AND approved_price IS NOT NULL AND approved_price > 0) OR "
            "(decision NOT IN ('accepted','accepted_with_modification') "
            "AND approved_price IS NULL)",
            name="ck_fit_rec_review_price",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["fitment_market_recommendations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_fit_rec_review_idempotency"
        ),
    )
    op.create_index(
        "ix_fit_rec_review_time",
        "fitment_recommendation_reviews",
        ["recommendation_id", "created_at"],
    )
    for column in ("workspace_id", "recommendation_id", "reviewer_id"):
        op.create_index(
            f"ix_fitment_recommendation_reviews_{column}",
            "fitment_recommendation_reviews",
            [column],
        )

    op.create_table(
        "fitment_feedback_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("label_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("reverts_event_id", sa.Uuid(), nullable=True),
        sa.Column("label_version", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active','reverted')", name="ck_fit_feedback_status"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reverts_event_id"], ["fitment_feedback_events.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_fit_feedback_idempotency"
        ),
    )
    op.create_index(
        "ix_fit_feedback_entity",
        "fitment_feedback_events",
        ["workspace_id", "entity_type", "entity_id"],
    )
    for column in ("workspace_id", "reviewer_id", "reverts_event_id"):
        op.create_index(
            f"ix_fitment_feedback_events_{column}",
            "fitment_feedback_events",
            [column],
        )

    op.create_table(
        "fitment_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("notification_type", sa.String(length=80), nullable=False),
        sa.Column("group_key", sa.String(length=120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending','delivered','read','dismissed')",
            name="ck_fit_notification_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["fitment_market_recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recommendation_id", "notification_type", name="uq_fit_notification_rec_type"
        ),
    )
    op.create_index(
        "ix_fit_notification_group",
        "fitment_notifications",
        ["workspace_id", "group_key", "created_at"],
    )
    for column in ("workspace_id", "recommendation_id"):
        op.create_index(
            f"ix_fitment_notifications_{column}",
            "fitment_notifications",
            [column],
        )

    for table in (
        "fitment_source_capabilities",
        "fitment_source_reliability_snapshots",
        "fitment_market_recommendations",
        "fitment_recommendation_reviews",
        "fitment_feedback_events",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION marko_reject_append_only_mutation()"
        )


def downgrade() -> None:
    for table in (
        "fitment_feedback_events",
        "fitment_recommendation_reviews",
        "fitment_market_recommendations",
        "fitment_source_reliability_snapshots",
        "fitment_source_capabilities",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    for table in (
        "fitment_notifications",
        "fitment_feedback_events",
        "fitment_recommendation_reviews",
        "fitment_market_recommendations",
        "fitment_source_reliability_snapshots",
        "fitment_source_capabilities",
    ):
        op.drop_table(table)
    op.drop_constraint(
        "ck_fit_evidence_factors", "fitment_evidence_claims", type_="check"
    )
    op.create_check_constraint(
        "ck_fit_evidence_factors",
        "fitment_evidence_claims",
        "source_reliability BETWEEN 0 AND 1 "
        "AND extraction_confidence BETWEEN 0 AND 1 "
        "AND independence_factor BETWEEN 0 AND 1 "
        "AND freshness_factor BETWEEN 0 AND 1",
    )
    op.drop_constraint(
        "ck_fit_evidence_feature", "fitment_evidence_claims", type_="check"
    )
    op.create_check_constraint(
        "ck_fit_evidence_feature",
        "fitment_evidence_claims",
        "feature IN ('oe_exact','oe_supersession','cross_confirmed',"
        "'part_category','axle','side','vehicle_make_model','generation',"
        "'year_overlap','engine','body','technical_specs')",
    )
    op.drop_column("fitment_evidence_claims", "directness")
    op.drop_constraint(
        "ck_fit_assessment_price_unit", "fitment_candidate_assessments", type_="check"
    )
    op.drop_column("fitment_candidate_assessments", "price_unit_certainty")
    op.drop_column("fitment_candidate_assessments", "price_unit_status")
    op.drop_column("fitment_candidate_assessments", "normalized_unit_price")
    op.drop_index("ix_fitment_analyses_workflow_state", table_name="fitment_analyses")
    op.drop_constraint(
        "ck_fit_analysis_workflow_state", "fitment_analyses", type_="check"
    )
    op.drop_column("fitment_analyses", "workflow_state")
    op.drop_constraint(
        "ck_market_observation_price_boundaries", "market_observations", type_="check"
    )
    op.drop_column("market_observations", "reference_price")
    op.drop_column("market_observations", "sale_price")
