"""Add verified market identity, offer accounting, and query inputs.

Revision ID: 20260719_0016
Revises: 20260719_0015
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_0016"
down_revision: str | None = "20260719_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pricing_runs",
        sa.Column(
            "calibration_accounting",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "scrape_targets",
        sa.Column(
            "input_kind",
            sa.String(length=24),
            server_default="product_seed",
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE scrape_targets SET input_kind = 'query' "
        "WHERE original_url IS NULL AND query IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_scrape_target_input_kind",
        "scrape_targets",
        "input_kind IN ('product_seed', 'query')",
    )

    op.add_column(
        "market_observations",
        sa.Column("search_oe_norm", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "extracted_oe_norms",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "market_observations",
        sa.Column("verified_matched_oe_norm", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "market_observations",
        sa.Column("comparison_identity_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "oe_verification_status",
            sa.String(length=32),
            server_default="LEGACY_UNVERIFIED",
            nullable=False,
        ),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "oe_evidence",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "oe_extractor_version",
            sa.String(length=80),
            server_default="legacy-unverified-v0",
            nullable=False,
        ),
    )
    op.add_column(
        "market_observations",
        sa.Column("oe_reenriched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "market_observations",
        sa.Column("oe_reenrichment_error_code", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "canonical_category_id",
            sa.String(length=120),
            server_default="generic_unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "comparability_hard_gate_result",
            sa.String(length=32),
            server_default="MANUAL_REVIEW",
            nullable=False,
        ),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "source_confidence_factors",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "source_confidence_method_version",
            sa.String(length=80),
            server_default="legacy-unverified-v0",
            nullable=False,
        ),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "calibration_exclusion_codes",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )

    # Preserve historical search intent but never promote it to candidate proof.
    # The table is append-only since 0005.  This one transactional migration
    # backfill is the only broad UPDATE; the trigger is restored immediately.
    op.execute(
        "ALTER TABLE market_observations "
        "DISABLE TRIGGER trg_market_observations_append_only"
    )
    op.execute(
        "UPDATE market_observations SET "
        "search_oe_norm = COALESCE(NULLIF(matched_oe_norm, ''), 'LEGACY_UNKNOWN'), "
        "extracted_oe_norms = '[]'::json, "
        "verified_matched_oe_norm = NULL, "
        "comparison_identity_key = NULL, "
        "oe_verification_status = 'LEGACY_UNVERIFIED', "
        "oe_evidence = '[]'::json, "
        "oe_extractor_version = 'legacy-unverified-v0', "
        "oe_reenriched_at = NULL, "
        "oe_reenrichment_error_code = NULL, "
        "comparability_hard_gate_result = 'MANUAL_REVIEW', "
        "automatic_eligible = false, "
        "source_confidence = 0, "
        "source_confidence_factors = '{}'::json, "
        "source_confidence_method_version = 'legacy-unverified-v0', "
        "calibration_exclusion_codes = '[\"CAL_LEGACY_UNVERIFIED\"]'::json"
    )
    op.execute(
        "ALTER TABLE market_observations "
        "ENABLE TRIGGER trg_market_observations_append_only"
    )
    op.alter_column("market_observations", "search_oe_norm", nullable=False)
    op.alter_column("market_observations", "matched_oe_norm", nullable=True)
    op.alter_column(
        "market_observations", "source_confidence", server_default=sa.text("0")
    )

    op.drop_constraint(
        "ck_market_observation_auto_evidence",
        "market_observations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_market_observation_oe_verification_status",
        "market_observations",
        "oe_verification_status IN ('VERIFIED_EXACT', 'VERIFIED_CROSS', "
        "'UNKNOWN', 'CONFLICT', 'AMBIGUOUS', 'LEGACY_UNVERIFIED')",
    )
    op.create_check_constraint(
        "ck_market_observation_comparability_result",
        "market_observations",
        "comparability_hard_gate_result IN ('PASS', 'MANUAL_REVIEW', 'REJECT')",
    )
    op.create_check_constraint(
        "ck_market_observation_verified_identity",
        "market_observations",
        "((oe_verification_status IN ('VERIFIED_EXACT', 'VERIFIED_CROSS') AND "
        "verified_matched_oe_norm IS NOT NULL AND comparison_identity_key IS NOT NULL) "
        "OR (oe_verification_status NOT IN ('VERIFIED_EXACT', 'VERIFIED_CROSS') AND "
        "verified_matched_oe_norm IS NULL AND comparison_identity_key IS NULL))",
    )
    op.create_check_constraint(
        "ck_market_observation_auto_evidence",
        "market_observations",
        "NOT automatic_eligible OR (currency_raw IS NOT NULL AND "
        "comparison_evidence IS NOT NULL AND comparability_policy_id IS NOT NULL AND "
        "comparability_policy_hash IS NOT NULL AND char_length(comparability_policy_hash) = 64 "
        "AND seller_identity_verified AND source_provenance_verified AND "
        "oe_verification_status IN ('VERIFIED_EXACT', 'VERIFIED_CROSS') AND "
        "verified_matched_oe_norm IS NOT NULL AND comparison_identity_key IS NOT NULL AND "
        "comparability_hard_gate_result = 'PASS')",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION marko_reject_append_only_mutation()
        RETURNS trigger AS $$
        DECLARE
          reenrichment_version text;
          calibration_version text;
          immutable_old jsonb;
          immutable_new jsonb;
          allowed_identity_fields text[] := ARRAY[
            'matched_oe_norm',
            'extracted_oe_norms',
            'verified_matched_oe_norm',
            'comparison_identity_key',
            'oe_verification_status',
            'oe_evidence',
            'oe_extractor_version',
            'oe_reenriched_at',
            'oe_reenrichment_error_code',
            'match_confidence',
            'comparison_evidence',
            'comparability_hard_gate_result',
            'automatic_eligible',
            'via_cross',
            'cross_link_id',
            'calibration_exclusion_codes'
          ];
        BEGIN
          reenrichment_version := current_setting(
            'marko.identity_reenrichment', true
          );
          calibration_version := current_setting(
            'marko.calibration_evaluation', true
          );
          IF TG_OP = 'UPDATE'
             AND TG_TABLE_NAME = 'market_observations'
             AND reenrichment_version IS NOT NULL
             AND reenrichment_version <> '' THEN
            immutable_old := to_jsonb(OLD) - allowed_identity_fields;
            immutable_new := to_jsonb(NEW) - allowed_identity_fields;
            IF immutable_new IS DISTINCT FROM immutable_old THEN
              RAISE EXCEPTION
                'market_observations re-enrichment changed immutable fields';
            END IF;
            IF to_jsonb(NEW)->>'oe_reenriched_at' IS NULL THEN
              RAISE EXCEPTION
                'market_observations re-enrichment timestamp is required';
            END IF;
            IF to_jsonb(NEW)->>'oe_reenrichment_error_code' IS NULL THEN
              IF COALESCE(to_jsonb(NEW)->>'oe_extractor_version', '')
                 <> reenrichment_version THEN
                RAISE EXCEPTION
                  'market_observations re-enrichment version mismatch';
              END IF;
            ELSE
              IF COALESCE((to_jsonb(NEW)->>'automatic_eligible')::boolean, false) THEN
                RAISE EXCEPTION
                  'failed market_observations re-enrichment cannot be eligible';
              END IF;
              IF (
                to_jsonb(NEW) - ARRAY[
                  'automatic_eligible',
                  'oe_reenriched_at',
                  'oe_reenrichment_error_code'
                ]::text[]
              ) IS DISTINCT FROM (
                to_jsonb(OLD) - ARRAY[
                  'automatic_eligible',
                  'oe_reenriched_at',
                  'oe_reenrichment_error_code'
                ]::text[]
              ) THEN
                RAISE EXCEPTION
                  'failed market_observations re-enrichment changed evidence fields';
              END IF;
            END IF;
            RETURN NEW;
          END IF;
          IF TG_OP = 'UPDATE'
             AND TG_TABLE_NAME = 'market_observations'
             AND calibration_version = 'calibration-eligibility-v1' THEN
            IF (to_jsonb(NEW) - 'calibration_exclusion_codes')
               IS DISTINCT FROM
               (to_jsonb(OLD) - 'calibration_exclusion_codes') THEN
              RAISE EXCEPTION
                'calibration evaluation changed immutable observation fields';
            END IF;
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for name, columns in (
        ("ix_market_observations_search_oe_norm", ["search_oe_norm"]),
        (
            "ix_market_observations_verified_matched_oe_norm",
            ["verified_matched_oe_norm"],
        ),
        (
            "ix_market_observations_comparison_identity_key",
            ["comparison_identity_key"],
        ),
        (
            "ix_market_observations_oe_verification_status",
            ["oe_verification_status"],
        ),
    ):
        op.create_index(name, "market_observations", columns)

    op.create_table(
        "offer_processing_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_item_id", sa.Uuid(), nullable=False),
        sa.Column("raw_market_capture_id", sa.Uuid(), nullable=False),
        sa.Column("market_observation_id", sa.Uuid(), nullable=True),
        sa.Column("source_listing_id", sa.String(length=255), nullable=True),
        sa.Column("raw_offer_index", sa.Integer(), nullable=False),
        sa.Column("outcome_code", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column(
            "reason_codes",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("payload_sha256", sa.String(length=64), nullable=True),
        sa.Column("safe_sample", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("raw_offer_index >= 0", name="ck_offer_outcome_index"),
        sa.CheckConstraint(
            "outcome_code IN ('OBSERVATION_PERSISTED', 'REJECTED_NOT_MAPPING', "
            "'REJECTED_INVALID_PRICE', 'REJECTED_INVALID_MATCH_SCORE', "
            "'REJECTED_MISSING_LISTING_IDENTITY', 'REJECTED_SCHEMA_MISMATCH', "
            "'REJECTED_SERIALIZATION', 'FAILED_INTERNAL_PROCESSING')",
            name="ck_offer_outcome_code",
        ),
        sa.CheckConstraint(
            "((outcome_code = 'OBSERVATION_PERSISTED' AND market_observation_id IS NOT NULL) "
            "OR (outcome_code <> 'OBSERVATION_PERSISTED' AND market_observation_id IS NULL))",
            name="ck_offer_outcome_observation_binding",
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_item_id"], ["pricing_run_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["raw_market_capture_id"], ["raw_market_captures.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["market_observation_id"], ["market_observations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "raw_market_capture_id",
            "pricing_run_item_id",
            "raw_offer_index",
            name="uq_offer_processing_outcome_capture_item_index",
        ),
    )
    op.create_index(
        "ix_offer_processing_outcomes_pricing_run_item_id",
        "offer_processing_outcomes",
        ["pricing_run_item_id"],
    )
    op.create_index(
        "ix_offer_processing_outcomes_raw_market_capture_id",
        "offer_processing_outcomes",
        ["raw_market_capture_id"],
    )
    op.create_index(
        "ix_offer_processing_outcomes_market_observation_id",
        "offer_processing_outcomes",
        ["market_observation_id"],
    )
    op.create_index(
        "ix_offer_outcome_item_code",
        "offer_processing_outcomes",
        ["pricing_run_item_id", "outcome_code"],
    )
    op.execute(
        "CREATE TRIGGER trg_offer_processing_outcomes_append_only "
        "BEFORE UPDATE OR DELETE ON offer_processing_outcomes FOR EACH ROW "
        "EXECUTE FUNCTION marko_reject_append_only_mutation()"
    )

    op.add_column(
        "tier_calibration_pairs",
        sa.Column(
            "identity_evidence",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("tier_calibration_pairs", "identity_evidence")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_offer_processing_outcomes_append_only "
        "ON offer_processing_outcomes"
    )
    op.drop_index("ix_offer_outcome_item_code", table_name="offer_processing_outcomes")
    op.drop_index(
        "ix_offer_processing_outcomes_market_observation_id",
        table_name="offer_processing_outcomes",
    )
    op.drop_index(
        "ix_offer_processing_outcomes_raw_market_capture_id",
        table_name="offer_processing_outcomes",
    )
    op.drop_index(
        "ix_offer_processing_outcomes_pricing_run_item_id",
        table_name="offer_processing_outcomes",
    )
    op.drop_table("offer_processing_outcomes")

    for name in (
        "ix_market_observations_oe_verification_status",
        "ix_market_observations_comparison_identity_key",
        "ix_market_observations_verified_matched_oe_norm",
        "ix_market_observations_search_oe_norm",
    ):
        op.drop_index(name, table_name="market_observations")
    op.drop_constraint(
        "ck_market_observation_auto_evidence",
        "market_observations",
        type_="check",
    )
    op.drop_constraint(
        "ck_market_observation_verified_identity",
        "market_observations",
        type_="check",
    )
    op.drop_constraint(
        "ck_market_observation_comparability_result",
        "market_observations",
        type_="check",
    )
    op.drop_constraint(
        "ck_market_observation_oe_verification_status",
        "market_observations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_market_observation_auto_evidence",
        "market_observations",
        "NOT automatic_eligible OR (currency_raw IS NOT NULL AND "
        "comparison_evidence IS NOT NULL AND comparability_policy_id IS NOT NULL AND "
        "comparability_policy_hash IS NOT NULL AND char_length(comparability_policy_hash) = 64 "
        "AND seller_identity_verified AND source_provenance_verified)",
    )
    # A downgrade restores the lossy legacy field solely for old application
    # compatibility; it does not claim that this value was candidate evidence.
    op.execute(
        "ALTER TABLE market_observations "
        "DISABLE TRIGGER trg_market_observations_append_only"
    )
    op.execute(
        "UPDATE market_observations SET matched_oe_norm = search_oe_norm "
        "WHERE matched_oe_norm IS NULL"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION marko_reject_append_only_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "ALTER TABLE market_observations "
        "ENABLE TRIGGER trg_market_observations_append_only"
    )
    op.alter_column("market_observations", "matched_oe_norm", nullable=False)
    op.alter_column(
        "market_observations", "source_confidence", server_default=sa.text("1")
    )
    for column in (
        "calibration_exclusion_codes",
        "source_confidence_method_version",
        "source_confidence_factors",
        "comparability_hard_gate_result",
        "canonical_category_id",
        "oe_reenrichment_error_code",
        "oe_reenriched_at",
        "oe_extractor_version",
        "oe_evidence",
        "oe_verification_status",
        "comparison_identity_key",
        "verified_matched_oe_norm",
        "extracted_oe_norms",
        "search_oe_norm",
    ):
        op.drop_column("market_observations", column)

    op.drop_constraint("ck_scrape_target_input_kind", "scrape_targets", type_="check")
    op.drop_column("scrape_targets", "input_kind")
    op.drop_column("pricing_runs", "calibration_accounting")
