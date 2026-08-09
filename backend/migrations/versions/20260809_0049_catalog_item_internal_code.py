"""Наш внутренний код на строке каталога — то, чем она связывается с витриной.

До этой правки код позиции (776…) доезжал до базы только внутри ``raw_row``:
колонки, по которой можно искать и соединять, не существовало, и связь каталога
с напарсенными листингами шла по бренду с артикулом либо по промовскому id.
Артикул принадлежит площадке, OE — детали, и только этот код принадлежит нам.

Обратная засыпка берёт значение из уже импортированных строк, поэтому
переимпортировать каталог не нужно.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260809_0049"
down_revision = "20260805_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "catalog_items",
        sa.Column(
            "internal_code_raw", sa.Text(), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "catalog_items",
        sa.Column(
            "internal_code_norm",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
    )
    op.create_index(
        "ix_catalog_items_internal_code_norm",
        "catalog_items",
        ["internal_code_norm"],
    )
    # Уже импортированные строки: код лежит в сырой строке под тем же
    # заголовком, под которым его писал экспорт. Повторять импорт не нужно.
    #
    # Засыпка обязана нормализовать ровно так же, как приложение, иначе одна и
    # та же позиция получит разные ключи и связь молча промахнётся. Проверено на
    # формах кода заказчика («7764 586», «776-440», « 776440 »): питоновский
    # normalize_identifier и marko_catalog_normalize дают одно и то же. Расходятся
    # они на перечислении через запятую, поэтому здесь берётся первый элемент —
    # так же, как это делает _IDENTIFIER_SPLIT_RE в xlsx_catalog.
    op.execute(
        """
        UPDATE catalog_items
        SET internal_code_raw = btrim(
            regexp_replace(raw_row ->> 'Внутренний код', '[,;|\r\n].*$', '')
        )
        -- raw_row объявлен как json, а не jsonb, поэтому оператор ? здесь
        -- недоступен: отсутствующий ключ проверяется через ->>, который
        -- возвращает NULL.
        WHERE btrim(coalesce(raw_row ->> 'Внутренний код', '')) <> ''
        """
    )
    # И тот же отказ, что в приложении: в эту колонку принимается только наш
    # код. Шаблон — из config/kemp_site_tokens.yaml (internal_code_pattern).
    # Засыпка идёт по всем партиям, когда-либо импортированным, а не только по
    # нашей книге, поэтому чужое значение здесь вероятнее, чем в ней.
    op.execute(
        """
        UPDATE catalog_items
        SET internal_code_norm = public.marko_catalog_normalize(internal_code_raw)
        WHERE internal_code_raw <> ''
          AND public.marko_catalog_normalize(internal_code_raw) ~ '^776[0-9A-Z]{1,9}$'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_items_internal_code_norm", table_name="catalog_items")
    op.drop_column("catalog_items", "internal_code_norm")
    op.drop_column("catalog_items", "internal_code_raw")
