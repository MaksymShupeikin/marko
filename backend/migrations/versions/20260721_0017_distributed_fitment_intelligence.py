"""Add distributed fitment intelligence evidence and review spine.

Revision ID: 20260721_0017
Revises: 20260719_0016
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_0017"
down_revision: str | None = "20260719_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fitment_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("source_key", sa.String(length=160), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_tier", sa.String(length=1), nullable=False),
        sa.Column("base_reliability", sa.Numeric(5, 4), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("access_method", sa.String(length=80), nullable=False),
        sa.Column("access_status", sa.String(length=24), nullable=False),
        sa.Column("robots_checked", sa.Boolean(), nullable=False),
        sa.Column("terms_checked", sa.Boolean(), nullable=False),
        sa.Column("rate_limit", sa.String(length=120), nullable=False),
        sa.Column("cache_policy", sa.String(length=120), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_tier IN ('A','B','C','D','E')", name="ck_fit_source_tier"
        ),
        sa.CheckConstraint(
            "base_reliability >= 0 AND base_reliability <= 1",
            name="ck_fit_source_reliability",
        ),
        sa.CheckConstraint(
            "access_status IN ('PERMITTED','OWNER_RISK_ACCEPTED','NOT_PERMITTED','UNKNOWN')",
            name="ck_fit_source_access",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "source_key", "policy_version", name="uq_fit_source_policy"
        ),
    )
    op.create_index(
        "ix_fit_source_workspace_key", "fitment_sources", ["workspace_id", "source_key"]
    )
    op.create_index(
        "ix_fitment_sources_workspace_id", "fitment_sources", ["workspace_id"]
    )

    op.create_table(
        "fitment_source_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("retrieval_query", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_locator", sa.Text(), nullable=True),
        sa.Column("response_metadata", sa.JSON(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(content_sha256) = 64", name="ck_fit_source_document_hash"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["fitment_sources.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "content_sha256", name="uq_fit_source_document_hash"
        ),
    )
    op.create_index(
        "ix_fit_source_document_retrieved",
        "fitment_source_documents",
        ["source_id", "retrieved_at"],
    )
    op.create_index(
        "ix_fitment_source_documents_source_id",
        "fitment_source_documents",
        ["source_id"],
    )
    op.create_index(
        "ix_fitment_source_documents_content_sha256",
        "fitment_source_documents",
        ["content_sha256"],
    )

    op.create_table(
        "seller_relation_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column("seller_external_id", sa.String(length=255), nullable=False),
        sa.Column("seller_name", sa.String(length=255), nullable=True),
        sa.Column("relation", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "relation IN ('own','related','possibly_related','independent','unknown')",
            name="ck_seller_relation_value",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_seller_relation_confidence"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["seller_relation_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_seller_relation_idempotency"
        ),
    )
    op.create_index(
        "ix_seller_relation_current",
        "seller_relation_records",
        ["workspace_id", "marketplace", "seller_external_id", "created_at"],
    )
    op.create_index(
        "ix_seller_relation_records_workspace_id",
        "seller_relation_records",
        ["workspace_id"],
    )
    op.create_index(
        "ix_seller_relation_records_supersedes_id",
        "seller_relation_records",
        ["supersedes_id"],
    )
    op.create_index(
        "ix_seller_relation_records_created_by",
        "seller_relation_records",
        ["created_by"],
    )

    op.create_table(
        "fitment_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="queued", nullable=False
        ),
        sa.Column("target_identity", sa.JSON(), nullable=False),
        sa.Column("target_commercial_context", sa.JSON(), nullable=False),
        sa.Column("source_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("contract_version", sa.String(length=80), nullable=False),
        sa.Column("scoring_version", sa.String(length=80), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("candidate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "completed_candidate_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "failed_candidate_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','partial','failed')",
            name="ck_fit_analysis_status",
        ),
        sa.CheckConstraint(
            "candidate_count >= 0 AND completed_candidate_count >= 0 AND failed_candidate_count >= 0",
            name="ck_fit_analysis_counts",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_id"], ["pricing_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_fit_analysis_idempotency"
        ),
    )
    op.create_index(
        "ix_fit_analysis_product_time",
        "fitment_analyses",
        ["catalog_item_id", "created_at"],
    )
    op.create_index(
        "ix_fit_analysis_workspace_status",
        "fitment_analyses",
        ["workspace_id", "status"],
    )
    for column in ("workspace_id", "catalog_item_id", "pricing_run_id", "requested_by"):
        op.create_index(f"ix_fitment_analyses_{column}", "fitment_analyses", [column])

    op.create_table(
        "fitment_candidate_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("market_observation_id", sa.Uuid(), nullable=False),
        sa.Column("seller_relation_record_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_identity", sa.JSON(), nullable=False),
        sa.Column("candidate_commercial_context", sa.JSON(), nullable=False),
        sa.Column("compatibility_status", sa.String(length=32), nullable=False),
        sa.Column("compatibility_probability", sa.Numeric(7, 6), nullable=False),
        sa.Column("positive_evidence", sa.Numeric(7, 6), nullable=False),
        sa.Column("negative_evidence", sa.Numeric(7, 6), nullable=False),
        sa.Column("coverage", sa.Numeric(7, 6), nullable=False),
        sa.Column("contradiction_rate", sa.Numeric(7, 6), nullable=False),
        sa.Column("missing_critical_ratio", sa.Numeric(7, 6), nullable=False),
        sa.Column("hard_rejections", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("missing_critical_fields", sa.JSON(), nullable=False),
        sa.Column("feature_consensus", sa.JSON(), nullable=False),
        sa.Column("authoritative_confirmation", sa.Boolean(), nullable=False),
        sa.Column("requires_manual_review", sa.Boolean(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("price_comparability_status", sa.String(length=24), nullable=False),
        sa.Column("price_eligible", sa.Boolean(), nullable=False),
        sa.Column("competitor_weight", sa.Numeric(9, 8), nullable=False),
        sa.Column("price_factor_trace", sa.JSON(), nullable=False),
        sa.Column("price_reason_codes", sa.JSON(), nullable=False),
        sa.Column(
            "automatic_price_change_allowed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("contract_version", sa.String(length=80), nullable=False),
        sa.Column("scoring_version", sa.String(length=80), nullable=False),
        sa.Column(
            "assessed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "compatibility_status IN ('confirmed_compatible','likely_compatible','uncertain','not_compatible')",
            name="ck_fit_assessment_status",
        ),
        sa.CheckConstraint(
            "compatibility_probability BETWEEN 0 AND 1 AND positive_evidence BETWEEN 0 AND 1 AND negative_evidence BETWEEN 0 AND 1 AND coverage BETWEEN 0 AND 1 AND contradiction_rate BETWEEN 0 AND 1 AND missing_critical_ratio BETWEEN 0 AND 1",
            name="ck_fit_assessment_scores",
        ),
        sa.CheckConstraint(
            "price_comparability_status IN ('comparable','manual_review','not_comparable')",
            name="ck_fit_assessment_price_status",
        ),
        sa.CheckConstraint(
            "competitor_weight >= 0 AND competitor_weight <= 1",
            name="ck_fit_assessment_weight",
        ),
        sa.CheckConstraint(
            "NOT automatic_price_change_allowed", name="ck_fit_assessment_no_auto_price"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["fitment_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["market_observation_id"], ["market_observations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["seller_relation_record_id"],
            ["seller_relation_records.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id", "market_observation_id", name="uq_fit_assessment_candidate"
        ),
    )
    op.create_index(
        "ix_fit_assessment_analysis_status",
        "fitment_candidate_assessments",
        ["analysis_id", "compatibility_status"],
    )
    op.create_index(
        "ix_fit_assessment_observation",
        "fitment_candidate_assessments",
        ["market_observation_id"],
    )
    op.create_index(
        "ix_fitment_candidate_assessments_analysis_id",
        "fitment_candidate_assessments",
        ["analysis_id"],
    )
    op.create_index(
        "ix_fitment_candidate_assessments_seller_relation_record_id",
        "fitment_candidate_assessments",
        ["seller_relation_record_id"],
    )

    op.create_table(
        "fitment_evidence_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_key", sa.String(length=255), nullable=False),
        sa.Column("feature", sa.String(length=40), nullable=False),
        sa.Column("evidence_value", sa.Numeric(3, 1), nullable=False),
        sa.Column("source_external_id", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_tier", sa.String(length=1), nullable=False),
        sa.Column("source_reliability", sa.Numeric(5, 4), nullable=False),
        sa.Column("extraction_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("independence_factor", sa.Numeric(5, 4), nullable=False),
        sa.Column("freshness_factor", sa.Numeric(5, 4), nullable=False),
        sa.Column("correlation_group", sa.String(length=255), nullable=False),
        sa.Column("polarity", sa.String(length=16), nullable=False),
        sa.Column("statement_status", sa.String(length=16), nullable=False),
        sa.Column("claim_value", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_fragment", sa.Text(), nullable=True),
        sa.Column("source_document_sha256", sa.String(length=64), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "feature IN ('oe_exact','oe_supersession','cross_confirmed','part_category','axle','side','vehicle_make_model','generation','year_overlap','engine','body','technical_specs')",
            name="ck_fit_evidence_feature",
        ),
        sa.CheckConstraint(
            "evidence_value IN (-1,-0.5,0,0.5,1)", name="ck_fit_evidence_value"
        ),
        sa.CheckConstraint(
            "source_tier IN ('A','B','C','D','E')", name="ck_fit_evidence_source_tier"
        ),
        sa.CheckConstraint(
            "source_reliability BETWEEN 0 AND 1 AND extraction_confidence BETWEEN 0 AND 1 AND independence_factor BETWEEN 0 AND 1 AND freshness_factor BETWEEN 0 AND 1",
            name="ck_fit_evidence_factors",
        ),
        sa.CheckConstraint(
            "polarity IN ('supports','contradicts','neutral','unknown')",
            name="ck_fit_evidence_polarity",
        ),
        sa.CheckConstraint(
            "statement_status IN ('FACT','INFERENCE','ASSUMPTION','UNKNOWN','CONFLICT')",
            name="ck_fit_evidence_statement",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["fitment_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["fitment_candidate_assessments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["fitment_source_documents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id", "evidence_key", name="uq_fit_evidence_analysis_key"
        ),
    )
    op.create_index(
        "ix_fit_evidence_assessment_feature",
        "fitment_evidence_claims",
        ["assessment_id", "feature"],
    )
    op.create_index(
        "ix_fit_evidence_correlation",
        "fitment_evidence_claims",
        ["analysis_id", "correlation_group"],
    )
    for column in ("analysis_id", "assessment_id", "source_document_id"):
        op.create_index(
            f"ix_fitment_evidence_claims_{column}", "fitment_evidence_claims", [column]
        )

    op.create_table(
        "fitment_human_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("system_status_snapshot", sa.String(length=32), nullable=False),
        sa.Column("system_probability_snapshot", sa.Numeric(7, 6), nullable=False),
        sa.Column("evidence_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('mark_candidate_compatible','mark_candidate_incompatible','postpone','request_additional_check')",
            name="ck_fit_review_decision",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["fitment_candidate_assessments.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_fit_review_idempotency"
        ),
    )
    op.create_index(
        "ix_fit_review_assessment_time",
        "fitment_human_reviews",
        ["assessment_id", "created_at"],
    )
    for column in ("workspace_id", "assessment_id", "reviewer_id"):
        op.create_index(
            f"ix_fitment_human_reviews_{column}", "fitment_human_reviews", [column]
        )

    op.create_table(
        "fitment_cross_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=False),
        sa.Column("normalized_brand", sa.String(length=255), nullable=False),
        sa.Column("article", sa.String(length=255), nullable=False),
        sa.Column("normalized_article", sa.String(length=255), nullable=False),
        sa.Column("oe", sa.String(length=255), nullable=False),
        sa.Column("normalized_oe", sa.String(length=255), nullable=False),
        sa.Column("installation_position", sa.String(length=80), nullable=True),
        sa.Column("vehicle_key", sa.String(length=255), nullable=True),
        sa.Column("relation_status", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("human_feedback_count", sa.Integer(), nullable=False),
        sa.Column("record_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("method_version", sa.String(length=80), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "relation_status IN ('machine_discovered','source_confirmed','human_confirmed','human_rejected','conflicting','deprecated','superseded')",
            name="ck_fit_cross_status",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1 AND source_count >= 0 AND human_feedback_count >= 0",
            name="ck_fit_cross_metrics",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["fitment_cross_references.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "record_fingerprint", name="uq_fit_cross_fingerprint"
        ),
    )
    op.create_index(
        "ix_fit_cross_lookup",
        "fitment_cross_references",
        ["workspace_id", "normalized_article", "normalized_oe", "relation_status"],
    )
    for column in (
        "workspace_id",
        "normalized_brand",
        "normalized_article",
        "normalized_oe",
        "supersedes_id",
        "created_by",
    ):
        op.create_index(
            f"ix_fitment_cross_references_{column}",
            "fitment_cross_references",
            [column],
        )

    op.create_table(
        "fitment_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("event_key", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "event_key", name="uq_fit_audit_event_key"),
    )
    op.create_index(
        "ix_fit_audit_entity",
        "fitment_audit_events",
        ["workspace_id", "entity_type", "entity_id"],
    )
    op.create_index(
        "ix_fit_audit_time", "fitment_audit_events", ["workspace_id", "occurred_at"]
    )
    op.create_index(
        "ix_fitment_audit_events_workspace_id", "fitment_audit_events", ["workspace_id"]
    )
    op.create_index(
        "ix_fitment_audit_events_actor_user_id",
        "fitment_audit_events",
        ["actor_user_id"],
    )

    for table in (
        "fitment_sources",
        "fitment_source_documents",
        "seller_relation_records",
        "fitment_candidate_assessments",
        "fitment_evidence_claims",
        "fitment_human_reviews",
        "fitment_cross_references",
        "fitment_audit_events",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION marko_reject_append_only_mutation()"
        )


def downgrade() -> None:
    append_only_tables = (
        "fitment_audit_events",
        "fitment_cross_references",
        "fitment_human_reviews",
        "fitment_evidence_claims",
        "fitment_candidate_assessments",
        "seller_relation_records",
        "fitment_source_documents",
        "fitment_sources",
    )
    for table in append_only_tables:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    for table in (
        "fitment_audit_events",
        "fitment_cross_references",
        "fitment_human_reviews",
        "fitment_evidence_claims",
        "fitment_candidate_assessments",
        "fitment_analyses",
        "seller_relation_records",
        "fitment_source_documents",
        "fitment_sources",
    ):
        op.drop_table(table)
