"""Привязать прогон к каноническому телу старта, его актору и полосе власти.

Независимая проверка 2026-08-02 (F1): «идемпотентный победитель» опознавался по
совпадению области и источника подтверждения.  Этого хватало ровно до двух
случаев, и оба воспроизводились на живой базе:

* два канонически РАЗНЫХ тела старта, нормализующихся в одну политику и одну
  область (``policy: null`` против ``policy: {"version": "pricing-v2"}``),
  считались одним запросом — второй молча получал прогон, запущенный по первому;
* второй актор со СВОИМ законным контрактом предпросмотра называл чужой ключ
  идемпотентности и получал в ответ прогон первого актора.  Это межпользовательская
  утечка, а не идемпотентность.

Ключ идемпотентности — это имя попытки, а не личность просящего.  Чтобы отличить
повтор той же попытки от чужого запроса под тем же именем, строка обязана помнить
три вещи, и все три — неизменяемо:

1. ``canonical_start_request_hash`` — отпечаток канонического тела старта, тот же
   самый, которым закрывается контракт предпросмотра;
2. ``start_actor_id`` / ``start_actor_type`` — носитель власти (для доверенной
   полосы это служба, названная источником подтверждения);
3. ``start_lane`` — сама полоса: человек или служба.

Существующие строки получают NULL по всем четырём колонкам: у них этих
утверждений никогда не было, и придумывать их миграцией нельзя.  Практическое
следствие — повтор по ключу для такой строки теперь отвечает типизированным
конфликтом вместо тихой выдачи чужого прогона; это отказ, а не порча данных.

Revision ID: 20260802_0038
Revises: 20260801_0037
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260802_0038"
down_revision: str | None = "20260801_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Тот же список, что и в 0035, плюс четыре колонки личности старта.  Личность
# обязана быть неизменяемой ровно по той же причине, что и политика: иначе
# «сравнение личности» опирается на значение, которое можно переписать одним
# UPDATE, и вся проверка сводится к одному лишнему запросу.
RUN_IMMUTABLE_COLUMNS = (
    "workspace_id",
    "import_batch_id",
    "policy_version",
    "policy_snapshot_hash",
    "parser_version",
    "classifier_version",
    "coefficient_model",
    "total_items",
    "scope_contract_version",
    "scope_mode",
    "scope_confirmation_source",
    "full_catalog_confirmed",
    "catalog_snapshot_hash",
    "scope_hash",
    "idempotency_key",
    "scope_frozen_at",
    "canonical_start_request_hash",
    "start_lane",
    "start_actor_id",
    "start_actor_type",
)
PRE_0038_RUN_IMMUTABLE_COLUMNS = RUN_IMMUTABLE_COLUMNS[:-4]


def _run_mutation_guard(columns: Sequence[str]) -> str:
    changed = " OR ".join(
        f"NEW.{column} IS DISTINCT FROM OLD.{column}" for column in columns
    )
    return f"""
        CREATE OR REPLACE FUNCTION marko_reject_pricing_run_scope_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF {changed}
             OR NEW.scope_manifest::text IS DISTINCT FROM OLD.scope_manifest::text
             OR NEW.policy_config::text IS DISTINCT FROM OLD.policy_config::text
          THEN
            RAISE EXCEPTION
              'pricing run execution inputs are immutable after creation (run %)',
              OLD.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """


def upgrade() -> None:
    op.add_column(
        "pricing_runs",
        sa.Column("canonical_start_request_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "pricing_runs", sa.Column("start_lane", sa.String(length=24), nullable=True)
    )
    op.add_column(
        "pricing_runs", sa.Column("start_actor_id", sa.String(length=160), nullable=True)
    )
    op.add_column(
        "pricing_runs", sa.Column("start_actor_type", sa.String(length=24), nullable=True)
    )
    op.create_check_constraint(
        "ck_pricing_run_start_request_hash",
        "pricing_runs",
        "canonical_start_request_hash IS NULL "
        "OR char_length(canonical_start_request_hash) = 64",
    )
    op.create_check_constraint(
        "ck_pricing_run_start_lane",
        "pricing_runs",
        "start_lane IS NULL OR start_lane IN ('OPERATOR', 'TRUSTED')",
    )
    # Половина личности личностью не является: полоса без актора и отпечатка
    # запроса сравнению не подлежит, и хранить такую строку нельзя.
    op.create_check_constraint(
        "ck_pricing_run_start_identity_complete",
        "pricing_runs",
        "start_lane IS NULL OR ("
        "canonical_start_request_hash IS NOT NULL "
        "AND start_actor_id IS NOT NULL "
        "AND start_actor_type IS NOT NULL)",
    )
    op.execute(_run_mutation_guard(RUN_IMMUTABLE_COLUMNS))


def downgrade() -> None:
    bound = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) AS bound FROM pricing_runs WHERE start_lane IS NOT NULL"
            )
        )
        .one()
    )
    if int(bound.bound):
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260802_0038: "
            f"{int(bound.bound)} pricing run(s) carry an immutable start identity "
            "that would be erased, leaving their idempotency keys unattributable; "
            "restore a pre-migration PostgreSQL backup instead of downgrading"
        )

    op.execute(_run_mutation_guard(PRE_0038_RUN_IMMUTABLE_COLUMNS))
    op.drop_constraint(
        "ck_pricing_run_start_identity_complete", "pricing_runs", type_="check"
    )
    op.drop_constraint("ck_pricing_run_start_lane", "pricing_runs", type_="check")
    op.drop_constraint(
        "ck_pricing_run_start_request_hash", "pricing_runs", type_="check"
    )
    op.drop_column("pricing_runs", "start_actor_type")
    op.drop_column("pricing_runs", "start_actor_id")
    op.drop_column("pricing_runs", "start_lane")
    op.drop_column("pricing_runs", "canonical_start_request_hash")
