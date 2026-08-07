"""Сделать родительский прогон частью неизменяемого членства.

Независимая проверка 2026-08-02 (F5) воспроизвела это на живом PostgreSQL:
``pricing_run_items.pricing_run_id`` не входил в список неизменяемых колонок
(0032 → 0035), поэтому одним ``UPDATE`` строку членства можно было перевесить с
ограниченного прогона на другой — в том числе в чужое рабочее пространство и в
доконтрактный прогон.  Состав источника становился нулевым, состав цели —
единичным, и обе стороны переставали соответствовать своим манифестам.  Барьер
дозаписи из 0035 этого не видел: он срабатывает на INSERT, а переезд — это
UPDATE.

Две правки:

1. ``pricing_run_id`` неизменяем для ЗАМОРОЖЕННОГО членства.  Заморожено то,
   что либо заняло место в упорядоченном составе (``membership_position IS NOT
   NULL``), либо принадлежит прогону с контрактом области.  Переезд запрещён и
   в обратную сторону — принять чужую строку в ограниченный прогон значит
   дописать его состав в обход барьера 0035.  Доконтрактные строки, никогда не
   бывшие уликой, правилом не затрагиваются: переписывать историю миграция не
   должна.
2. Барьер дозаписи сверяет ТОЧНОЕ соответствие места и позиции каталога, а не
   вхождение во множество.  Прежняя проверка (``membership ? id``) пропускала
   вставку правильной позиции на ЧУЖОЕ место: множество совпадало, порядок —
   нет, и упорядоченный отпечаток расходился уже потом, на проверке перед
   расчётом.

Блокировка строки прогона (``FOR UPDATE``) из 0035 сохранена, поэтому точная
проверка места сериализуется вместе с проверкой границы: две одновременные
вставки на одно место не могут обе увидеть его свободным.

Revision ID: 20260802_0039
Revises: 20260802_0038
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260802_0039"
down_revision: str | None = "20260802_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ITEM_IMMUTABLE_COLUMNS = (
    "catalog_item_id",
    "catalog_item_override_id",
    "cost_record_id",
    "start_snapshot_hash",
    "membership_position",
)

ITEM_CHANGED = " OR ".join(
    f"NEW.{column} IS DISTINCT FROM OLD.{column}" for column in ITEM_IMMUTABLE_COLUMNS
)

# Строка, уже занявшая место в упорядоченном составе или принадлежащая прогону с
# контрактом области, — это улика расчёта. Ни увести её, ни принять чужую нельзя.
PARENT_RUN_GUARD = f"""
        CREATE OR REPLACE FUNCTION marko_reject_pricing_run_item_snapshot_mutation()
        RETURNS trigger AS $$
        DECLARE
          old_contract text;
          new_contract text;
        BEGIN
          IF NEW.pricing_run_id IS DISTINCT FROM OLD.pricing_run_id THEN
            SELECT scope_contract_version INTO old_contract
            FROM pricing_runs WHERE id = OLD.pricing_run_id;
            SELECT scope_contract_version INTO new_contract
            FROM pricing_runs WHERE id = NEW.pricing_run_id;
            IF OLD.membership_position IS NOT NULL
               OR (old_contract IS NOT NULL AND old_contract <> 'LEGACY_UNBOUNDED')
               OR (new_contract IS NOT NULL AND new_contract <> 'LEGACY_UNBOUNDED')
            THEN
              RAISE EXCEPTION
                'pricing run item membership is bound to run % and is immutable '
                '(item %)', OLD.pricing_run_id, OLD.id;
            END IF;
          END IF;
          IF {ITEM_CHANGED}
             OR NEW.start_snapshot::text IS DISTINCT FROM OLD.start_snapshot::text
          THEN
            RAISE EXCEPTION
              'pricing run item start-time snapshot is immutable (item %)', OLD.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """

PRE_0039_ITEM_GUARD = f"""
        CREATE OR REPLACE FUNCTION marko_reject_pricing_run_item_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF {ITEM_CHANGED}
             OR NEW.start_snapshot::text IS DISTINCT FROM OLD.start_snapshot::text
          THEN
            RAISE EXCEPTION
              'pricing run item start-time snapshot is immutable (item %)', OLD.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """

# Точное соответствие места и позиции каталога: ``->> position`` вместо ``?``.
EXACT_POSITION_GROWTH_GUARD = """
        CREATE OR REPLACE FUNCTION marko_reject_run_membership_growth()
        RETURNS trigger AS $$
        DECLARE
          contract text;
          manifest jsonb;
          membership jsonb;
          frozen_total integer;
          present integer;
          expected_item text;
        BEGIN
          SELECT scope_contract_version, scope_manifest::jsonb
            INTO contract, manifest
          FROM pricing_runs WHERE id = NEW.pricing_run_id
          FOR UPDATE;
          IF contract IS NULL OR contract = 'LEGACY_UNBOUNDED' THEN
            RETURN NEW;
          END IF;
          membership = manifest -> 'execution' -> 'membership';
          IF membership IS NULL OR membership ->> 'count' IS NULL THEN
            RAISE EXCEPTION
              'pricing run % declares a scope contract but no frozen membership',
              NEW.pricing_run_id;
          END IF;
          frozen_total = (membership ->> 'count')::integer;
          SELECT count(*) INTO present
          FROM pricing_run_items WHERE pricing_run_id = NEW.pricing_run_id;
          IF present >= frozen_total THEN
            RAISE EXCEPTION
              'pricing run scope is frozen at % items (run %)',
              frozen_total, NEW.pricing_run_id;
          END IF;
          IF NEW.membership_position IS NULL
             OR NEW.membership_position >= frozen_total THEN
            RAISE EXCEPTION
              'pricing run item must claim a frozen membership position below % '
              '(run %)', frozen_total, NEW.pricing_run_id;
          END IF;
          IF membership -> 'catalog_item_ids' IS NOT NULL THEN
            expected_item =
              membership -> 'catalog_item_ids' ->> NEW.membership_position;
            IF expected_item IS NULL THEN
              RAISE EXCEPTION
                'membership position % is outside the frozen membership of run %',
                NEW.membership_position, NEW.pricing_run_id;
            END IF;
            IF expected_item <> NEW.catalog_item_id::text THEN
              RAISE EXCEPTION
                'frozen membership of run % names catalog item % at position %, '
                'not %', NEW.pricing_run_id, expected_item,
                NEW.membership_position, NEW.catalog_item_id;
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """

PRE_0039_GROWTH_GUARD = """
        CREATE OR REPLACE FUNCTION marko_reject_run_membership_growth()
        RETURNS trigger AS $$
        DECLARE
          contract text;
          manifest jsonb;
          membership jsonb;
          frozen_total integer;
          present integer;
        BEGIN
          SELECT scope_contract_version, scope_manifest::jsonb
            INTO contract, manifest
          FROM pricing_runs WHERE id = NEW.pricing_run_id
          FOR UPDATE;
          IF contract IS NULL OR contract = 'LEGACY_UNBOUNDED' THEN
            RETURN NEW;
          END IF;
          membership = manifest -> 'execution' -> 'membership';
          IF membership IS NULL OR membership ->> 'count' IS NULL THEN
            RAISE EXCEPTION
              'pricing run % declares a scope contract but no frozen membership',
              NEW.pricing_run_id;
          END IF;
          frozen_total = (membership ->> 'count')::integer;
          SELECT count(*) INTO present
          FROM pricing_run_items WHERE pricing_run_id = NEW.pricing_run_id;
          IF present >= frozen_total THEN
            RAISE EXCEPTION
              'pricing run scope is frozen at % items (run %)',
              frozen_total, NEW.pricing_run_id;
          END IF;
          IF NEW.membership_position IS NULL
             OR NEW.membership_position >= frozen_total THEN
            RAISE EXCEPTION
              'pricing run item must claim a frozen membership position below % '
              '(run %)', frozen_total, NEW.pricing_run_id;
          END IF;
          IF membership -> 'catalog_item_ids' IS NOT NULL
             AND NOT (membership -> 'catalog_item_ids'
                      ? NEW.catalog_item_id::text) THEN
            RAISE EXCEPTION
              'catalog item % is not part of the frozen membership of run %',
              NEW.catalog_item_id, NEW.pricing_run_id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """


def _reject_misplaced_frozen_membership() -> None:
    """Не включать правило молча поверх состава, который ему уже не отвечает.

    Если в базе есть ограниченный прогон, где место N занято НЕ той позицией
    каталога, которую называет манифест, то новый барьер начнёт отвергать
    законные вставки в этот прогон, а расследование причины придётся вести уже
    на работающей системе.  Такое расхождение — след прежней дыры, и разбирать
    его должен человек, а не миграция.
    """

    if context.is_offline_mode():
        op.execute(
            sa.text(
                """
                DO $marko_membership_guard$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM pricing_run_items AS i
                        JOIN pricing_runs AS r ON r.id = i.pricing_run_id
                        CROSS JOIN LATERAL (
                            SELECT (r.scope_manifest::jsonb -> 'execution'
                                    -> 'membership' -> 'catalog_item_ids'
                                    ->> i.membership_position) AS expected
                        ) AS m
                        WHERE r.scope_contract_version IS NOT NULL
                          AND r.scope_contract_version <> 'LEGACY_UNBOUNDED'
                          AND i.membership_position IS NOT NULL
                          AND m.expected IS NOT NULL
                          AND m.expected <> i.catalog_item_id::text
                    ) THEN
                        RAISE EXCEPTION
                            'BLOCKED_MIGRATION_20260802_0039: materialized '
                            'membership disagrees with its frozen manifest';
                    END IF;
                END
                $marko_membership_guard$
                """
            )
        )
        return

    misplaced = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT i.pricing_run_id, i.membership_position,
                       i.catalog_item_id, m.expected
                FROM pricing_run_items AS i
                JOIN pricing_runs AS r ON r.id = i.pricing_run_id
                CROSS JOIN LATERAL (
                    SELECT (r.scope_manifest::jsonb -> 'execution' -> 'membership'
                            -> 'catalog_item_ids' ->> i.membership_position)
                        AS expected
                ) AS m
                WHERE r.scope_contract_version IS NOT NULL
                  AND r.scope_contract_version <> 'LEGACY_UNBOUNDED'
                  AND i.membership_position IS NOT NULL
                  AND m.expected IS NOT NULL
                  AND m.expected <> i.catalog_item_id::text
                ORDER BY i.pricing_run_id, i.membership_position
                LIMIT 20
                """
            )
        )
        .all()
    )
    if misplaced:
        detail = "; ".join(
            f"run {row.pricing_run_id} position {row.membership_position} holds "
            f"{row.catalog_item_id}, manifest names {row.expected}"
            for row in misplaced
        )
        raise RuntimeError(
            "BLOCKED_MIGRATION_20260802_0039: materialized run membership already "
            "disagrees with the frozen manifest on which catalog item occupies "
            "which position. That is evidence of the very reassignment this "
            "migration closes; investigate those runs (and cancel them through "
            "POST /api/v1/pricing/runs/{run_id}/cancel if they are still in "
            f"flight) before re-running the migration. Offending rows: {detail}"
        )


def upgrade() -> None:
    _reject_misplaced_frozen_membership()
    op.execute(PARENT_RUN_GUARD)
    op.execute(EXACT_POSITION_GROWTH_GUARD)


def downgrade() -> None:
    op.execute(PRE_0039_GROWTH_GUARD)
    op.execute(PRE_0039_ITEM_GUARD)
