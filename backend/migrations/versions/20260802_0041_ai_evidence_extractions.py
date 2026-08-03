"""Неизменяемая история ИИ-извлечений улик и разделение бюджета по назначению.

Round 6. Извлечение — отдельная таблица, а не расширение
``candidate_comparability_reviews``: вопросы разные («тот же товар?» против «что
буквально написано в захвате?»), версии у них независимые, а общая таблица
сделала бы каждую колонку одной необязательной для другой — после чего CHECK
перестаёт что-либо утверждать.

Идентичность запроса включает ``capture_sha256`` и ``candidate_snapshot_hash``.
Без хеша захвата повторный скрейп страницы с новыми ценами переиспользовал бы
ответ, посчитанный по старой: протухшая улика, неотличимая в записи от свежей.

Второй кусок — ``llm_provider_call_budget``. Ключом была одна позиция прогона,
поэтому извлечение и сравнимость делили бы одну строку и один ``call_limit``:
резервирование извлечения с лимитом 4 сузило бы уже начатый бюджет сравнимости
с 10 до 4 (``least(call_limit, limit)`` — правило намеренно однонаправленное).
Ключ становится составным ``(pricing_run_item_id, purpose)``; существующие
строки получают ``purpose='comparability'`` через DEFAULT, поэтому обратной
засыпки не требуется и старые вызовы продолжают считаться там же, где считались.

Revision ID: 20260802_0041
Revises: 20260802_0040
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260802_0041"
down_revision = "20260802_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_evidence_extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_item_id", sa.Uuid(), nullable=False),
        sa.Column("market_observation_id", sa.Uuid(), nullable=False),
        sa.Column("raw_capture_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("candidate_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("capture_sha256", sa.String(length=64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("reasoning_effort", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("raw_output", sa.JSON(), nullable=True),
        sa.Column(
            "findings",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "verification_status",
            sa.String(length=24),
            server_default="NOT_RUN",
            nullable=False,
        ),
        sa.Column(
            "verification_reasons",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "verified_field_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "rejected_field_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "input_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column("cache_hit_extraction_id", sa.Uuid(), nullable=True),
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
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('COMPLETED', 'CACHED', 'FAILED', 'SKIPPED', 'UNCONFIGURED')",
            name="ck_ai_evidence_extraction_status",
        ),
        sa.CheckConstraint(
            "verification_status IN "
            "('VERIFIED', 'PARTIALLY_VERIFIED', 'REJECTED', 'NOT_RUN')",
            name="ck_ai_evidence_extraction_verification_status",
        ),
        sa.CheckConstraint(
            "(status = 'CACHED' AND cache_hit_extraction_id IS NOT NULL) OR "
            "(status <> 'CACHED' AND cache_hit_extraction_id IS NULL)",
            name="ck_ai_evidence_extraction_cache_binding",
        ),
        sa.CheckConstraint(
            "status NOT IN ('SKIPPED', 'UNCONFIGURED') OR "
            "(provider_response_id IS NULL AND provider_model IS NULL AND "
            "raw_output IS NULL AND latency_ms = 0 AND "
            "usage::jsonb = '{}'::jsonb)",
            name="ck_ai_evidence_extraction_no_request_states",
        ),
        sa.CheckConstraint(
            "(status = 'FAILED' AND error_code IS NOT NULL) OR (status <> 'FAILED')",
            name="ck_ai_evidence_extraction_failure_code",
        ),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR error_code IS NULL",
            name="ck_ai_evidence_extraction_completed_clean",
        ),
        sa.CheckConstraint(
            "char_length(request_key) = 64 AND char_length(input_hash) = 64 AND "
            "char_length(candidate_snapshot_hash) = 64 AND "
            "char_length(capture_sha256) = 64",
            name="ck_ai_evidence_extraction_digest_shape",
        ),
        sa.CheckConstraint("attempt_no > 0", name="ck_ai_evidence_extraction_attempt"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_ai_evidence_extraction_latency"),
        sa.CheckConstraint(
            "reasoning_effort IN ('none', 'low', 'medium', 'high', 'xhigh', 'max')",
            name="ck_ai_evidence_extraction_reasoning_effort",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_item_id"], ["pricing_run_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["market_observation_id"],
            ["market_observations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_capture_id"], ["raw_market_captures.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["cache_hit_extraction_id"],
            ["ai_evidence_extractions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_key", name="uq_ai_evidence_extraction_request_key"
        ),
    )
    op.create_index(
        "ix_ai_evidence_extraction_cache",
        "ai_evidence_extractions",
        ["workspace_id", "input_hash", "status"],
    )
    op.create_index(
        "ix_ai_evidence_extraction_observation_time",
        "ai_evidence_extractions",
        ["market_observation_id", "extracted_at"],
    )
    op.create_index(
        "ix_ai_evidence_extraction_position_time",
        "ai_evidence_extractions",
        ["pricing_run_item_id", "extracted_at"],
    )
    # Уникальный намеренно: модель объявляет ``unique=True, index=True``, и
    # обычный индекс здесь означал бы вечное расхождение в ``alembic check``
    # (ровно то, что чинила миграция 0037 для ``candidate_comparability_reviews``
    # — повторять её ошибку в новой таблице смысла нет).
    op.create_index(
        "ix_ai_evidence_extractions_request_key",
        "ai_evidence_extractions",
        ["request_key"],
        unique=True,
    )
    for column in (
        "workspace_id",
        "pricing_run_item_id",
        "market_observation_id",
        "raw_capture_id",
        "input_hash",
        "capture_sha256",
        "status",
        "cache_hit_extraction_id",
    ):
        op.create_index(
            f"ix_ai_evidence_extractions_{column}",
            "ai_evidence_extractions",
            [column],
        )

    op.execute(
        "CREATE TRIGGER trg_ai_evidence_extractions_append_only "
        "BEFORE UPDATE OR DELETE ON ai_evidence_extractions FOR EACH ROW "
        "EXECUTE FUNCTION marko_reject_append_only_mutation()"
    )

    # --- бюджет вызовов: ключ по (позиция, назначение) ------------------------
    op.add_column(
        "llm_provider_call_budget",
        sa.Column(
            "purpose",
            sa.String(length=32),
            nullable=False,
            server_default="comparability",
        ),
    )
    op.drop_constraint(
        "llm_provider_call_budget_pkey",
        "llm_provider_call_budget",
        type_="primary",
    )
    op.create_primary_key(
        "llm_provider_call_budget_pkey",
        "llm_provider_call_budget",
        ["pricing_run_item_id", "purpose"],
    )
    op.create_check_constraint(
        "ck_llm_provider_call_budget_purpose",
        "llm_provider_call_budget",
        "purpose IN ('comparability', 'ai_evidence_extraction')",
    )


def downgrade() -> None:
    extraction_count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM ai_evidence_extractions"))
        .scalar_one()
    )
    if int(extraction_count):
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260802_0041: "
            f"{int(extraction_count)} AI evidence extraction(s) would be erased; "
            "restore a pre-migration PostgreSQL backup instead of downgrading"
        )

    # Сужать составной ключ обратно к одной позиции можно только если ни одна
    # позиция не тратила бюджет на два назначения: иначе строки схлопнутся в
    # одну и потраченное перестанет быть потраченным.
    collisions = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "  SELECT pricing_run_item_id FROM llm_provider_call_budget"
                "  GROUP BY pricing_run_item_id HAVING count(*) > 1"
                ") AS duplicated"
            )
        )
        .scalar_one()
    )
    if int(collisions):
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260802_0041: "
            f"{int(collisions)} pricing position(s) hold a call budget for more "
            "than one purpose; collapsing the key would forget calls that were "
            "already billed"
        )

    op.drop_constraint(
        "ck_llm_provider_call_budget_purpose",
        "llm_provider_call_budget",
        type_="check",
    )
    op.drop_constraint(
        "llm_provider_call_budget_pkey",
        "llm_provider_call_budget",
        type_="primary",
    )
    op.create_primary_key(
        "llm_provider_call_budget_pkey",
        "llm_provider_call_budget",
        ["pricing_run_item_id"],
    )
    op.drop_column("llm_provider_call_budget", "purpose")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_ai_evidence_extractions_append_only "
        "ON ai_evidence_extractions"
    )
    op.drop_table("ai_evidence_extractions")
