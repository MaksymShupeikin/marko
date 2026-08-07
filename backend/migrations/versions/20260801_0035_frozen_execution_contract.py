"""Заморозить политику, снимок позиции и состав прогона на уровне базы.

Ревью 2026-08-01 (второе, враждебное): миграции 0032 и 0033 закрыли область, но
не закрыли то, ПО ЧЕМУ прогон исполняется.

* 0032 перечислила неизменяемые колонки прогона и не назвала среди них
  ``policy_version`` и ``policy_config``: ``UPDATE pricing_runs SET
  policy_config = ...`` на уже ограниченном прогоне проходил. Исторический вход
  расчёта можно было переписать задним числом.
* ``total_items`` тоже оставался изменяемым, а барьер дозаписи членства из 0033
  именно на него и опирался: поднять счётчик, вставить строку — и состав
  прогона вырос после заморозки.  Барьер к тому же считал строки и лишь потом
  вставлял, то есть в гонке пропускал обоих.
* Снимок позиции (``start_snapshot``) хранился без отпечатка: испорченный
  снимок ничем не отличался от целого.

Что делает эта миграция:

1. ``pricing_runs.policy_snapshot_hash`` — отпечаток канонических байт снимка
   политики.  Существующие прогоны получают NULL: их политика не была
   заморожена, и притворяться замороженной она не должна.
2. ``pricing_run_items.start_snapshot_hash`` и ``membership_position`` — то же
   самое для позиции: отпечаток снимка и замороженный порядок членства.
3. Список неизменяемых колонок прогона расширен до всего, что определяет
   исполнение: политика и её отпечаток, ``total_items``, версии парсера и
   классификатора, модель коэффициентов, рабочее пространство.
4. Барьер дозаписи членства переписан: он берёт блокировку на строке прогона
   (``FOR UPDATE``) и сверяется с НЕИЗМЕНЯЕМЫМ манифестом, а не с изменяемым
   счётчиком.  Для ограниченной области дополнительно проверяется, что
   вставляемая позиция вообще перечислена в замороженном членстве.
5. Таблица контрактов предпросмотра: непрозрачный токен (хранится только его
   sha256), срок годности, актор с ролью и правами, отпечатки запроса, области,
   каталога и политики.

Revision ID: 20260801_0035
Revises: 20260801_0034
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260801_0035"
down_revision: str | None = "20260801_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Всё, что определяет ИСПОЛНЕНИЕ прогона. Счётчики хода (``completed_items``,
# ``failed_items``, ``coefficient_version``, ``calibration_*``) сюда намеренно
# не входят: они заполняются по мере работы и обязаны меняться.
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
)
ITEM_IMMUTABLE_COLUMNS = (
    "catalog_item_id",
    "catalog_item_override_id",
    "cost_record_id",
    "start_snapshot_hash",
    "membership_position",
)


ACTIVE_STATUS_SQL = (
    "'queued', 'running', 'collecting', 'classifying', 'calibrating', 'calculating'"
)


def _reject_in_flight_bounded_runs() -> None:
    """Не ломать молча прогоны, начатые между 0032 и этой миграцией.

    У них нет ни ``membership_position``, ни отпечатка снимка позиции, а
    задним числом их не восстановить: порядок членства можно было бы вывести
    из ``start_snapshot``, но отпечаток пришлось бы посчитать по снимку СТАРОГО
    состава — без запаса, продаж и значений правки.  Такой отпечаток утверждал
    бы заморозку, которой не было.  Поэтому после апгрейда проверка состава и
    снимка честно отвергнет такой прогон, а миграция обязана предупредить об
    этом ДО того, как это случится на работающей системе.
    """

    if context.is_offline_mode():
        op.execute(
            sa.text(
                f"""
                DO $marko_frozen_guard$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM pricing_runs
                        WHERE status IN ({ACTIVE_STATUS_SQL})
                          AND scope_contract_version IS NOT NULL
                          AND scope_contract_version <> 'LEGACY_UNBOUNDED'
                    ) THEN
                        RAISE EXCEPTION
                            'BLOCKED_MIGRATION_20260801_0035: bounded pricing '
                            'runs must finish or be cancelled before migration';
                    END IF;
                END
                $marko_frozen_guard$
                """
            )
        )
        return

    in_flight = (
        op.get_bind()
        .execute(
            sa.text(
                f"""
                SELECT id, workspace_id, status
                FROM pricing_runs
                WHERE status IN ({ACTIVE_STATUS_SQL})
                  AND scope_contract_version IS NOT NULL
                  AND scope_contract_version <> 'LEGACY_UNBOUNDED'
                ORDER BY created_at
                LIMIT 20
                """
            )
        )
        .all()
    )
    if in_flight:
        detail = "; ".join(
            f"run {row.id} (workspace {row.workspace_id}, status {row.status})"
            for row in in_flight
        )
        raise RuntimeError(
            "BLOCKED_MIGRATION_20260801_0035: bounded pricing runs are still in "
            "flight and carry no frozen membership position or snapshot hash, so "
            "after this migration their calculation would fail closed. Let them "
            "finish, or cancel them through "
            "POST /api/v1/pricing/runs/{run_id}/cancel, and re-run the migration. "
            f"Offending runs: {detail}"
        )


def upgrade() -> None:
    _reject_in_flight_bounded_runs()

    op.add_column(
        "pricing_runs",
        sa.Column("policy_snapshot_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "pricing_run_items",
        sa.Column("start_snapshot_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "pricing_run_items",
        sa.Column("membership_position", sa.Integer(), nullable=True),
    )
    # Прогон, объявивший отпечаток политики, обязан нести и саму политику.
    op.create_check_constraint(
        "ck_pricing_run_policy_snapshot_hash",
        "pricing_runs",
        "policy_snapshot_hash IS NULL OR char_length(policy_snapshot_hash) = 64",
    )
    op.create_check_constraint(
        "ck_pricing_run_item_start_snapshot_hash",
        "pricing_run_items",
        "start_snapshot_hash IS NULL OR char_length(start_snapshot_hash) = 64",
    )
    op.create_check_constraint(
        "ck_pricing_run_item_membership_position",
        "pricing_run_items",
        "membership_position IS NULL OR membership_position >= 0",
    )
    # Порядок членства уникален внутри прогона: две позиции не могут занимать
    # одно место, иначе упорядоченный отпечаток перестаёт быть определённым.
    op.create_index(
        "uq_pricing_run_item_membership_position",
        "pricing_run_items",
        ["pricing_run_id", "membership_position"],
        unique=True,
        postgresql_where=sa.text("membership_position IS NOT NULL"),
    )
    op.create_index(
        "uq_pricing_run_item_membership_catalog_item",
        "pricing_run_items",
        ["pricing_run_id", "catalog_item_id"],
        unique=True,
    )

    op.create_table(
        "pricing_run_preview_contracts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.String(length=160), nullable=False),
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column("workspace_role", sa.String(length=32), nullable=False),
        sa.Column(
            "permissions",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("scope_mode", sa.String(length=20), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("scope_hash", sa.String(length=64), nullable=False),
        sa.Column("catalog_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("policy_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "requires_full_catalog_confirmation",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("consumed_run_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"], ["catalog_import_batches.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("token_sha256", name="uq_pricing_run_preview_token"),
        sa.CheckConstraint(
            "char_length(token_sha256) = 64 AND char_length(request_hash) = 64 "
            "AND char_length(scope_hash) = 64 "
            "AND char_length(catalog_snapshot_hash) = 64 "
            "AND char_length(policy_snapshot_hash) = 64",
            name="ck_pricing_run_preview_digests",
        ),
        sa.CheckConstraint(
            "expires_at > issued_at",
            name="ck_pricing_run_preview_expiry_after_issue",
        ),
        sa.CheckConstraint(
            "(consumed_at IS NULL AND consumed_idempotency_key IS NULL) OR "
            "(consumed_at IS NOT NULL AND consumed_idempotency_key IS NOT NULL)",
            name="ck_pricing_run_preview_consumption",
        ),
    )
    op.create_index(
        "ix_pricing_run_preview_contracts_workspace_id",
        "pricing_run_preview_contracts",
        ["workspace_id"],
    )
    op.create_index(
        "ix_pricing_run_preview_contracts_import_batch_id",
        "pricing_run_preview_contracts",
        ["import_batch_id"],
    )
    op.create_index(
        "ix_pricing_run_preview_workspace_batch",
        "pricing_run_preview_contracts",
        ["workspace_id", "import_batch_id"],
    )

    run_changed = " OR ".join(
        f"NEW.{column} IS DISTINCT FROM OLD.{column}"
        for column in RUN_IMMUTABLE_COLUMNS
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION marko_reject_pricing_run_scope_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF {run_changed}
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
    )

    item_changed = " OR ".join(
        f"NEW.{column} IS DISTINCT FROM OLD.{column}"
        for column in ITEM_IMMUTABLE_COLUMNS
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION marko_reject_pricing_run_item_snapshot_mutation()
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

    # Барьер дозаписи членства.  Три отличия от 0033:
    #
    # * блокировка строки прогона (``FOR UPDATE``) сериализует конкурирующие
    #   вставки — без неё два транзакционных потока считают одно и то же число
    #   и оба проходят;
    # * граница берётся из ``scope_manifest`` (он неизменяем с 0032), а не из
    #   ``total_items``, который до этой миграции можно было поднять;
    # * для ограниченной области дополнительно проверяется, что вставляемая
    #   позиция вообще перечислена в замороженном членстве.
    op.execute(
        """
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
    )


def downgrade() -> None:
    frozen = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (
                        SELECT count(*)
                        FROM pricing_runs
                        WHERE policy_snapshot_hash IS NOT NULL
                    ) AS frozen_policies,
                    (
                        SELECT count(*)
                        FROM pricing_run_items
                        WHERE start_snapshot_hash IS NOT NULL
                    ) AS frozen_snapshots,
                    (
                        SELECT count(*) FROM pricing_run_preview_contracts
                    ) AS preview_contracts
                """
            )
        )
        .one()
    )
    if any(int(value) for value in frozen):
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260801_0035: "
            f"{int(frozen.frozen_policies)} frozen execution policy snapshot(s), "
            f"{int(frozen.frozen_snapshots)} frozen item snapshot hash(es) and "
            f"{int(frozen.preview_contracts)} preview contract(s) would be "
            "erased; restore a pre-migration PostgreSQL backup instead of "
            "downgrading"
        )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION marko_reject_run_membership_growth()
        RETURNS trigger AS $$
        DECLARE
          contract text;
          frozen_total integer;
          present integer;
        BEGIN
          SELECT scope_contract_version, total_items
            INTO contract, frozen_total
          FROM pricing_runs WHERE id = NEW.pricing_run_id;
          IF contract IS NULL OR contract = 'LEGACY_UNBOUNDED' THEN
            RETURN NEW;
          END IF;
          SELECT count(*) INTO present
          FROM pricing_run_items WHERE pricing_run_id = NEW.pricing_run_id;
          IF present >= frozen_total THEN
            RAISE EXCEPTION
              'pricing run scope is frozen at % items (run %)',
              frozen_total, NEW.pricing_run_id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    legacy_run_columns = (
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
    run_changed = " OR ".join(
        f"NEW.{column} IS DISTINCT FROM OLD.{column}" for column in legacy_run_columns
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION marko_reject_pricing_run_scope_mutation()
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
    legacy_item_columns = (
        "catalog_item_id",
        "catalog_item_override_id",
        "cost_record_id",
    )
    item_changed = " OR ".join(
        f"NEW.{column} IS DISTINCT FROM OLD.{column}" for column in legacy_item_columns
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION marko_reject_pricing_run_item_snapshot_mutation()
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

    op.drop_index(
        "ix_pricing_run_preview_workspace_batch",
        table_name="pricing_run_preview_contracts",
    )
    op.drop_index(
        "ix_pricing_run_preview_contracts_import_batch_id",
        table_name="pricing_run_preview_contracts",
    )
    op.drop_index(
        "ix_pricing_run_preview_contracts_workspace_id",
        table_name="pricing_run_preview_contracts",
    )
    op.drop_table("pricing_run_preview_contracts")
    op.drop_index(
        "uq_pricing_run_item_membership_catalog_item",
        table_name="pricing_run_items",
    )
    op.drop_index(
        "uq_pricing_run_item_membership_position",
        table_name="pricing_run_items",
    )
    op.drop_constraint(
        "ck_pricing_run_item_membership_position",
        "pricing_run_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_pricing_run_item_start_snapshot_hash",
        "pricing_run_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_pricing_run_policy_snapshot_hash", "pricing_runs", type_="check"
    )
    op.drop_column("pricing_run_items", "membership_position")
    op.drop_column("pricing_run_items", "start_snapshot_hash")
    op.drop_column("pricing_runs", "policy_snapshot_hash")
