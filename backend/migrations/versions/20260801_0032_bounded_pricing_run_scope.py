"""Bounded, immutable pricing-run scope with atomic active-run protection.

Revision ID: 20260801_0032
Revises: 20260731_0031
Create Date: 2026-08-01

Существующие прогоны создавались до этого контракта: у них не было ни манифеста
области, ни подтверждения полного каталога.  Поэтому ``scope_contract_version``
остаётся у них NULL, а источник подтверждения — ``LEGACY_UNBOUNDED``; выдавать
их за подтверждённые нельзя.

Апгрейд отказывается выполняться, если в базе уже лежат несколько активных
прогонов по одному импорту — это и есть след незакрытой гонки.  Такие прогоны
надо сначала отменить штатным эндпоинтом ``POST /runs/{id}/cancel``: молча
переписывать их статус миграцией значит уничтожать историю.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260801_0032"
down_revision: str | None = "20260731_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_STATUS_SQL = (
    "'queued', 'running', 'collecting', 'classifying', 'calibrating', 'calculating'"
)
RUN_IMMUTABLE_COLUMNS = (
    "import_batch_id",
    "scope_contract_version",
    "scope_mode",
    "scope_confirmation_source",
    "full_catalog_confirmed",
    "catalog_snapshot_hash",
    "scope_hash",
    "idempotency_key",
    "scope_frozen_at",
)
ITEM_IMMUTABLE_COLUMNS = (
    "catalog_item_id",
    "catalog_item_override_id",
    "cost_record_id",
)


def _reject_duplicate_active_runs() -> None:
    if context.is_offline_mode():
        # Offline generation has no connection and therefore cannot fetch the
        # diagnostic rows below.  Keep the safety gate in the generated SQL
        # itself instead of silently skipping it or crashing on ``None.all``.
        op.execute(
            sa.text(
                f"""
                DO $marko_scope_guard$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM pricing_runs
                        WHERE status IN ({ACTIVE_STATUS_SQL})
                        GROUP BY workspace_id, import_batch_id
                        HAVING count(*) > 1
                    ) THEN
                        RAISE EXCEPTION
                            'BLOCKED_MIGRATION_20260801_0032: duplicate active '
                            'pricing runs must be cancelled before migration';
                    END IF;
                END
                $marko_scope_guard$
                """
            )
        )
        return
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                f"""
                SELECT workspace_id, import_batch_id, count(*) AS active_runs
                FROM pricing_runs
                WHERE status IN ({ACTIVE_STATUS_SQL})
                GROUP BY workspace_id, import_batch_id
                HAVING count(*) > 1
                ORDER BY count(*) DESC
                LIMIT 20
                """
            )
        )
        .all()
    )
    if duplicates:
        detail = "; ".join(
            f"workspace {row.workspace_id} / import {row.import_batch_id}: "
            f"{int(row.active_runs)} active runs"
            for row in duplicates
        )
        raise RuntimeError(
            "BLOCKED_MIGRATION_20260801_0032: the pre-migration race left several "
            "active pricing runs on the same catalog import, which the new unique "
            "index would reject. Cancel the redundant runs through "
            "POST /api/v1/pricing/runs/{run_id}/cancel and re-run the migration. "
            f"Offending pairs: {detail}"
        )


def upgrade() -> None:
    _reject_duplicate_active_runs()

    op.add_column(
        "pricing_runs",
        sa.Column("scope_contract_version", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "pricing_runs",
        sa.Column(
            "scope_mode",
            sa.String(length=20),
            server_default="FULL_CATALOG",
            nullable=False,
        ),
    )
    op.add_column(
        "pricing_runs",
        sa.Column(
            "scope_confirmation_source",
            sa.String(length=24),
            server_default="LEGACY_UNBOUNDED",
            nullable=False,
        ),
    )
    op.add_column(
        "pricing_runs",
        sa.Column(
            "full_catalog_confirmed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "pricing_runs",
        sa.Column("catalog_snapshot_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "pricing_runs", sa.Column("scope_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "pricing_runs",
        sa.Column(
            "scope_manifest",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "pricing_runs",
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "pricing_runs",
        sa.Column("scope_frozen_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_check_constraint(
        "ck_pricing_run_scope_mode",
        "pricing_runs",
        "scope_mode IN ('FULL_CATALOG', 'EXPLICIT_ITEMS')",
    )
    op.create_check_constraint(
        "ck_pricing_run_scope_confirmation_source",
        "pricing_runs",
        "scope_confirmation_source IN "
        "('OPERATOR', 'SYSTEM_REPLAY', 'E2E_FIXTURE_REPLAY', 'LEGACY_UNBOUNDED')",
    )
    op.create_check_constraint(
        "ck_pricing_run_full_catalog_confirmation",
        "pricing_runs",
        "scope_confirmation_source <> 'OPERATOR' "
        "OR scope_mode <> 'FULL_CATALOG' "
        "OR full_catalog_confirmed",
    )
    op.create_check_constraint(
        "ck_pricing_run_scope_manifest_complete",
        "pricing_runs",
        "scope_contract_version IS NULL OR ("
        "scope_hash IS NOT NULL AND catalog_snapshot_hash IS NOT NULL "
        "AND scope_frozen_at IS NOT NULL)",
    )
    op.create_unique_constraint(
        "uq_pricing_run_workspace_idempotency",
        "pricing_runs",
        ["workspace_id", "idempotency_key"],
    )
    op.create_index("ix_pricing_runs_scope_hash", "pricing_runs", ["scope_hash"])
    # Атомарная защита от двух одновременных прогонов: SELECT перед вставкой
    # гонку не выдерживает, частичный уникальный индекс — выдерживает.
    op.create_index(
        "uq_pricing_run_active_import_batch",
        "pricing_runs",
        ["workspace_id", "import_batch_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN ({ACTIVE_STATUS_SQL})"),
    )

    op.add_column(
        "pricing_run_items",
        sa.Column("catalog_item_override_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "pricing_run_items", sa.Column("cost_record_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "pricing_run_items",
        sa.Column(
            "start_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_pricing_run_item_start_override",
        "pricing_run_items",
        "catalog_item_overrides",
        ["catalog_item_override_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_pricing_run_item_start_cost_record",
        "pricing_run_items",
        "catalog_item_cost_records",
        ["cost_record_id"],
        ["id"],
    )
    op.create_index(
        "ix_pricing_run_items_catalog_item_override_id",
        "pricing_run_items",
        ["catalog_item_override_id"],
    )
    op.create_index(
        "ix_pricing_run_items_cost_record_id",
        "pricing_run_items",
        ["cost_record_id"],
    )

    run_changed = " OR ".join(
        f"NEW.{column} IS DISTINCT FROM OLD.{column}"
        for column in RUN_IMMUTABLE_COLUMNS
    )
    op.execute(
        f"""
        CREATE FUNCTION marko_reject_pricing_run_scope_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF {run_changed}
             OR NEW.scope_manifest::text IS DISTINCT FROM OLD.scope_manifest::text
          THEN
            RAISE EXCEPTION
              'pricing run scope is immutable after creation (run %)', OLD.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_pricing_runs_immutable_scope "
        "BEFORE UPDATE ON pricing_runs FOR EACH ROW "
        "EXECUTE FUNCTION marko_reject_pricing_run_scope_mutation()"
    )

    item_changed = " OR ".join(
        f"NEW.{column} IS DISTINCT FROM OLD.{column}"
        for column in ITEM_IMMUTABLE_COLUMNS
    )
    op.execute(
        f"""
        CREATE FUNCTION marko_reject_pricing_run_item_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF {item_changed}
             OR NEW.start_snapshot::text IS DISTINCT FROM OLD.start_snapshot::text
          THEN
            RAISE EXCEPTION
              'pricing run item start-time snapshot is immutable (item %)', OLD.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_pricing_run_items_immutable_start_snapshot "
        "BEFORE UPDATE ON pricing_run_items FOR EACH ROW "
        "EXECUTE FUNCTION marko_reject_pricing_run_item_snapshot_mutation()"
    )


def downgrade() -> None:
    persisted = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (
                        SELECT count(*)
                        FROM pricing_runs
                        WHERE scope_contract_version IS NOT NULL
                    ) AS scoped_runs,
                    (
                        SELECT count(*)
                        FROM pricing_run_items
                        WHERE start_snapshot::jsonb <> '{}'::jsonb
                    ) AS start_snapshots
                """
            )
        )
        .one()
    )
    if any(int(value) for value in persisted):
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260801_0032: "
            f"{int(persisted.scoped_runs)} bounded run scope(s) and "
            f"{int(persisted.start_snapshots)} start-time snapshot(s) would be "
            "erased; restore a pre-migration PostgreSQL backup instead of "
            "downgrading"
        )

    op.execute(
        "DROP TRIGGER IF EXISTS trg_pricing_run_items_immutable_start_snapshot "
        "ON pricing_run_items"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS marko_reject_pricing_run_item_snapshot_mutation()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_pricing_runs_immutable_scope ON pricing_runs"
    )
    op.execute("DROP FUNCTION IF EXISTS marko_reject_pricing_run_scope_mutation()")

    op.drop_index("ix_pricing_run_items_cost_record_id", table_name="pricing_run_items")
    op.drop_index(
        "ix_pricing_run_items_catalog_item_override_id", table_name="pricing_run_items"
    )
    op.drop_constraint(
        "fk_pricing_run_item_start_cost_record",
        "pricing_run_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_pricing_run_item_start_override", "pricing_run_items", type_="foreignkey"
    )
    op.drop_column("pricing_run_items", "start_snapshot")
    op.drop_column("pricing_run_items", "cost_record_id")
    op.drop_column("pricing_run_items", "catalog_item_override_id")

    op.drop_index("uq_pricing_run_active_import_batch", table_name="pricing_runs")
    op.drop_index("ix_pricing_runs_scope_hash", table_name="pricing_runs")
    op.drop_constraint(
        "uq_pricing_run_workspace_idempotency", "pricing_runs", type_="unique"
    )
    for constraint in (
        "ck_pricing_run_scope_manifest_complete",
        "ck_pricing_run_full_catalog_confirmation",
        "ck_pricing_run_scope_confirmation_source",
        "ck_pricing_run_scope_mode",
    ):
        op.drop_constraint(constraint, "pricing_runs", type_="check")
    for column in (
        "scope_frozen_at",
        "idempotency_key",
        "scope_manifest",
        "scope_hash",
        "catalog_snapshot_hash",
        "full_catalog_confirmed",
        "scope_confirmation_source",
        "scope_mode",
        "scope_contract_version",
    ):
        op.drop_column("pricing_runs", column)
