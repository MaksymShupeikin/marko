"""Persist the complete AI-evidence binding and verifier identity.

Rows created before this migration are retained but receive explicit legacy
sentinels for digests that cannot be reconstructed safely in SQL.  Such rows
fail closed under the current verifier and are never silently reused.

Revision ID: 20260802_0042
Revises: 20260802_0041
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op


revision = "20260802_0042"
down_revision = "20260802_0041"
branch_labels = None
depends_on = None


_LEGACY_DIGEST = "0" * 64


def upgrade() -> None:
    table = "ai_evidence_extractions"
    # 0041 already protects this table with the generic append-only trigger.
    # This migration owns the one allowed historical backfill, so suspend that
    # trigger transactionally and restore it after every new column is bound.
    # If any statement fails PostgreSQL rolls the trigger drop back as well.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_ai_evidence_extractions_append_only "
        "ON ai_evidence_extractions"
    )
    columns = (
        sa.Column("source_listing_id", sa.String(length=255), nullable=True),
        sa.Column("source_offer_locator_sha256", sa.String(length=64), nullable=True),
        sa.Column("document_sha256", sa.String(length=64), nullable=True),
        sa.Column("prepared_input_sha256", sa.String(length=64), nullable=True),
        sa.Column("model_settings_sha256", sa.String(length=64), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("max_input_chars", sa.Integer(), nullable=True),
        sa.Column("target_fields", sa.JSON(), nullable=True),
        sa.Column("verifier_version", sa.String(length=80), nullable=True),
        sa.Column("oe_normalization_version", sa.String(length=80), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("verification_report", sa.JSON(), nullable=True),
    )
    for column in columns:
        op.add_column(table, column)

    op.execute(
        sa.text(
            "UPDATE ai_evidence_extractions AS extraction SET "
            "source_listing_id = observation.source_listing_id, "
            "source_offer_locator_sha256 = :legacy_digest, "
            "document_sha256 = :legacy_digest, "
            "prepared_input_sha256 = :legacy_digest, "
            "model_settings_sha256 = :legacy_digest, "
            "max_output_tokens = 1200, max_input_chars = 20000, "
            "target_fields = COALESCE(extraction.input_snapshot->'target_fields', '[]'::json), "
            "verifier_version = 'legacy-unverifiable', "
            "oe_normalization_version = 'legacy-unverifiable', "
            "mode = CASE WHEN extraction.status = 'UNCONFIGURED' THEN 'off' ELSE 'shadow' END, "
            "outcome = CASE "
            "  WHEN extraction.status IN ('COMPLETED', 'CACHED') THEN 'EXTRACTED' "
            "  WHEN extraction.status = 'UNCONFIGURED' THEN 'UNCONFIGURED' "
            "  WHEN extraction.status = 'SKIPPED' THEN 'NOT_ELIGIBLE' "
            "  ELSE 'PROVIDER_ERROR' END, "
            "verification_report = '{}'::json "
            "FROM market_observations AS observation "
            "WHERE observation.id = extraction.market_observation_id"
        ).bindparams(legacy_digest=_LEGACY_DIGEST)
    )
    for name in (
        "source_listing_id",
        "source_offer_locator_sha256",
        "document_sha256",
        "prepared_input_sha256",
        "model_settings_sha256",
        "max_output_tokens",
        "max_input_chars",
        "target_fields",
        "verifier_version",
        "oe_normalization_version",
        "mode",
        "outcome",
        "verification_report",
    ):
        op.alter_column(table, name, nullable=False)

    op.drop_constraint("ck_ai_evidence_extraction_digest_shape", table, type_="check")
    op.create_check_constraint(
        "ck_ai_evidence_extraction_digest_shape",
        table,
        "char_length(request_key) = 64 AND char_length(input_hash) = 64 AND "
        "char_length(candidate_snapshot_hash) = 64 AND char_length(capture_sha256) = 64 AND "
        "char_length(source_offer_locator_sha256) = 64 AND "
        "char_length(document_sha256) = 64 AND char_length(prepared_input_sha256) = 64 AND "
        "char_length(model_settings_sha256) = 64",
    )
    op.create_check_constraint(
        "ck_ai_evidence_extraction_mode", table, "mode IN ('off', 'shadow')"
    )
    op.create_check_constraint(
        "ck_ai_evidence_extraction_bounds",
        table,
        "max_output_tokens > 0 AND max_input_chars > 0",
    )
    if context.is_offline_mode():
        op.execute(
            sa.text(
                """
                DO $marko_ai_cache_guard$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM ai_evidence_extractions AS cached
                        LEFT JOIN ai_evidence_extractions AS source
                          ON source.id = cached.cache_hit_extraction_id
                        WHERE cached.status = 'CACHED'
                          AND (source.status IS DISTINCT FROM 'COMPLETED'
                               OR jsonb_typeof(source.raw_output::jsonb)
                                  IS DISTINCT FROM 'object')
                    ) THEN
                        RAISE EXCEPTION
                            'AI_EVIDENCE_CACHE_SOURCE_INVALID: cached rows must '
                            'reference completed strict extractions';
                    END IF;
                END
                $marko_ai_cache_guard$
                """
            )
        )
    else:
        invalid_cache_sources = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT count(*) FROM ai_evidence_extractions AS cached "
                    "LEFT JOIN ai_evidence_extractions AS source "
                    "ON source.id = cached.cache_hit_extraction_id "
                    "WHERE cached.status = 'CACHED' "
                    "AND (source.status IS DISTINCT FROM 'COMPLETED' "
                    "OR jsonb_typeof(source.raw_output::jsonb) "
                    "IS DISTINCT FROM 'object')"
                )
            )
            .scalar_one()
        )
        if int(invalid_cache_sources):
            raise RuntimeError(
                "AI_EVIDENCE_CACHE_SOURCE_INVALID: "
                f"{int(invalid_cache_sources)} cached row(s) do not reference a "
                "completed strict extraction"
            )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION marko_validate_ai_evidence_cache_source()
        RETURNS trigger AS $$
        DECLARE
          source_status text;
          source_has_output boolean;
        BEGIN
          IF NEW.status = 'CACHED' THEN
            SELECT status, jsonb_typeof(raw_output::jsonb) = 'object'
              INTO source_status, source_has_output
              FROM ai_evidence_extractions
             WHERE id = NEW.cache_hit_extraction_id;
            IF source_status IS DISTINCT FROM 'COMPLETED'
               OR source_has_output IS DISTINCT FROM true THEN
              RAISE EXCEPTION
                'AI_EVIDENCE_CACHE_SOURCE_INVALID: cache source must be a completed strict extraction';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_ai_evidence_extractions_cache_source "
        "BEFORE INSERT OR UPDATE ON ai_evidence_extractions FOR EACH ROW "
        "EXECUTE FUNCTION marko_validate_ai_evidence_cache_source()"
    )
    op.execute(
        "CREATE TRIGGER trg_ai_evidence_extractions_append_only "
        "BEFORE UPDATE OR DELETE ON ai_evidence_extractions FOR EACH ROW "
        "EXECUTE FUNCTION marko_reject_append_only_mutation()"
    )


def downgrade() -> None:
    table = "ai_evidence_extractions"
    op.execute(
        "DROP TRIGGER IF EXISTS trg_ai_evidence_extractions_cache_source "
        "ON ai_evidence_extractions"
    )
    op.execute("DROP FUNCTION IF EXISTS marko_validate_ai_evidence_cache_source()")
    op.drop_constraint("ck_ai_evidence_extraction_bounds", table, type_="check")
    op.drop_constraint("ck_ai_evidence_extraction_mode", table, type_="check")
    op.drop_constraint("ck_ai_evidence_extraction_digest_shape", table, type_="check")
    op.create_check_constraint(
        "ck_ai_evidence_extraction_digest_shape",
        table,
        "char_length(request_key) = 64 AND char_length(input_hash) = 64 AND "
        "char_length(candidate_snapshot_hash) = 64 AND char_length(capture_sha256) = 64",
    )
    for name in reversed(
        (
            "source_listing_id",
            "source_offer_locator_sha256",
            "document_sha256",
            "prepared_input_sha256",
            "model_settings_sha256",
            "max_output_tokens",
            "max_input_chars",
            "target_fields",
            "verifier_version",
            "oe_normalization_version",
            "mode",
            "outcome",
            "verification_report",
        )
    ):
        op.drop_column(table, name)
