"""Защитить неизменяемый состав прогона от DELETE, дозаписи и каскада каталога.

Ревью 2026-08-01: миграция 0032 закрыла только UPDATE. Состав прогона можно было
удалить, дописать после заморозки, а удаление позиции каталога уносило членство
прогона каскадом — то есть доказательство расчёта уничтожалось задним числом.

Три правила:

* ``pricing_run_items.catalog_item_id`` переводится с ``CASCADE`` на
  ``RESTRICT``. Позицию каталога, участвующую в прогоне, больше нельзя удалить,
  не разобравшись с прогоном. Выбран RESTRICT, а не «снимок вместо ссылки»:
  снимок уже есть (``start_snapshot``), а ссылка нужна именно как улика.
* DELETE членства запрещён для прогонов с контрактом области.
* INSERT членства разрешён, пока прогон ещё набирается: число позиций не должно
  превышать замороженное ``total_items``. Это пропускает законное создание
  (позиции пишутся сразу после строки прогона) и запрещает дозапись после.

Прогоны без контракта области (``scope_contract_version IS NULL``) правилами не
затрагиваются: их состав никогда не был заморожен, и переписывать историю
миграция не должна.

Revision ID: 20260801_0033
Revises: 20260801_0032
"""

from __future__ import annotations

from alembic import op


revision = "20260801_0033"
down_revision = "20260801_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "pricing_run_items_catalog_item_id_fkey",
        "pricing_run_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "pricing_run_items_catalog_item_id_fkey",
        "pricing_run_items",
        "catalog_items",
        ["catalog_item_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute(
        """
        CREATE FUNCTION marko_reject_run_membership_delete()
        RETURNS trigger AS $$
        DECLARE
          contract text;
        BEGIN
          SELECT scope_contract_version INTO contract
          FROM pricing_runs WHERE id = OLD.pricing_run_id;
          IF contract IS NOT NULL AND contract <> 'LEGACY_UNBOUNDED' THEN
            RAISE EXCEPTION
              'pricing run membership is immutable evidence (run %)',
              OLD.pricing_run_id;
          END IF;
          RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_pricing_run_items_no_delete "
        "BEFORE DELETE ON pricing_run_items FOR EACH ROW "
        "EXECUTE FUNCTION marko_reject_run_membership_delete()"
    )

    op.execute(
        """
        CREATE FUNCTION marko_reject_run_membership_growth()
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
    op.execute(
        "CREATE TRIGGER trg_pricing_run_items_no_growth "
        "BEFORE INSERT ON pricing_run_items FOR EACH ROW "
        "EXECUTE FUNCTION marko_reject_run_membership_growth()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_pricing_run_items_no_growth ON pricing_run_items"
    )
    op.execute("DROP FUNCTION IF EXISTS marko_reject_run_membership_growth()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_pricing_run_items_no_delete ON pricing_run_items"
    )
    op.execute("DROP FUNCTION IF EXISTS marko_reject_run_membership_delete()")
    op.drop_constraint(
        "pricing_run_items_catalog_item_id_fkey",
        "pricing_run_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "pricing_run_items_catalog_item_id_fkey",
        "pricing_run_items",
        "catalog_items",
        ["catalog_item_id"],
        ["id"],
        ondelete="CASCADE",
    )
