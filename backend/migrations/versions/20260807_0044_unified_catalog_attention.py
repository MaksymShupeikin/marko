"""Unified catalog products and the live price-attention queue.

Revision ID: 20260807_0044
Revises: 20260802_0043
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260807_0044"
down_revision = "20260802_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_pricing_run_scope_confirmation_source",
        "pricing_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_pricing_run_scope_confirmation_source",
        "pricing_runs",
        "scope_confirmation_source IN "
        "('OPERATOR', 'AUTOMATED_MONITORING', 'SYSTEM_REPLAY', "
        "'E2E_FIXTURE_REPLAY', 'LEGACY_UNBOUNDED')",
    )

    op.create_table(
        "catalog_products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_product_id", sa.String(length=255), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=True),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("internal_code", sa.String(length=255), nullable=True),
        sa.Column("oe_raw", sa.Text(), nullable=True),
        sa.Column("oe_norm", sa.String(length=255), nullable=True),
        sa.Column("mpn_raw", sa.Text(), nullable=True),
        sa.Column("mpn_norm", sa.String(length=255), nullable=True),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("product_url", sa.Text(), nullable=True),
        sa.Column("current_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="UAH", nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=True),
        sa.Column(
            "identity_status",
            sa.String(length=24),
            server_default="UNRESOLVED",
            nullable=False,
        ),
        sa.Column("identity_reason", sa.String(length=80), nullable=True),
        sa.Column("raw_data", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_kind IN ('PROM_STORE', 'XLSX')",
            name="ck_catalog_product_source_kind",
        ),
        sa.CheckConstraint(
            "identity_status IN ('VERIFIED_EXACT', 'VERIFIED_CROSS', "
            "'AMBIGUOUS', 'UNRESOLVED', 'CONFLICT')",
            name="ck_catalog_product_identity_status",
        ),
        sa.CheckConstraint(
            "current_price IS NULL OR current_price > 0",
            name="ck_catalog_product_price_positive",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "source_kind",
            "source_id",
            "source_product_id",
            name="uq_catalog_product_source_identity",
        ),
    )
    op.create_index("ix_catalog_products_workspace_id", "catalog_products", ["workspace_id"])
    op.create_index("ix_catalog_products_source_id", "catalog_products", ["source_id"])
    op.create_index("ix_catalog_products_listing_id", "catalog_products", ["listing_id"])
    op.create_index(
        "ix_catalog_products_catalog_item_id", "catalog_products", ["catalog_item_id"]
    )
    op.create_index(
        "ix_catalog_product_workspace_status",
        "catalog_products",
        ["workspace_id", "identity_status"],
    )
    op.create_index(
        "ix_catalog_product_workspace_oe",
        "catalog_products",
        ["workspace_id", "oe_norm"],
    )
    op.create_index(
        "ix_catalog_product_workspace_name",
        "catalog_products",
        ["workspace_id", "name"],
    )
    # Existing source evidence must become visible immediately after deploy;
    # requiring every store to be re-scraped would leave the new home screen
    # empty and would turn rollout order into user-visible data loss.
    op.execute(
        """
        INSERT INTO catalog_products (
          id, workspace_id, source_kind, source_id, source_product_id,
          listing_id, name, sku, internal_code, oe_raw, oe_norm, mpn_raw,
          mpn_norm, brand, category, description, product_url, current_price,
          currency, is_available, identity_status, identity_reason, raw_data,
          source_updated_at, created_at, updated_at
        )
        SELECT
          md5('marko:catalog-product:prom:' || ws.workspace_id::text || ':' ||
              l.store_id::text || ':' || l.external_id)::uuid,
          ws.workspace_id,
          'PROM_STORE',
          l.store_id,
          l.external_id,
          l.id,
          l.name,
          l.sku,
          l.sku,
          nullif(btrim(coalesce(l.raw_data ->> 'oe_raw', '')), ''),
          nullif(btrim(coalesce(l.catalog_oe_norm, '')), ''),
          nullif(btrim(coalesce(l.model_id, '')), ''),
          nullif(btrim(coalesce(l.catalog_model_norm, '')), ''),
          l.brand,
          nullif(btrim(coalesce(l.raw_data ->> 'category_name', '')), ''),
          nullif(btrim(coalesce(l.raw_data ->> 'description', '')), ''),
          l.url,
          l.current_price,
          l.currency,
          l.is_available,
          'UNRESOLVED',
          CASE
            WHEN nullif(btrim(coalesce(l.catalog_oe_norm, '')), '') IS NULL
              THEN 'PROM_OE_NOT_FOUND'
            ELSE 'PROM_EXPLICIT_OE_REQUIRES_VERIFICATION'
          END,
          coalesce(l.raw_data, '{}'::json),
          l.last_seen_at,
          now(),
          now()
        FROM listings AS l
        JOIN workspace_stores AS ws ON ws.store_id = l.store_id
        WHERE ws.kind = 'owned'
        ON CONFLICT (workspace_id, source_kind, source_id, source_product_id)
        DO NOTHING
        """
    )
    op.execute(
        """
        WITH latest AS (
          SELECT
            ci.*,
            b.filename,
            row_number() OVER (
              PARTITION BY ci.workspace_id, lower(btrim(b.filename)), ci.sku
              ORDER BY b.created_at DESC, b.id DESC, ci.id DESC
            ) AS source_rank
          FROM catalog_items AS ci
          JOIN catalog_import_batches AS b ON b.id = ci.import_batch_id
          WHERE b.status IN ('completed', 'partial')
        )
        INSERT INTO catalog_products (
          id, workspace_id, source_kind, source_id, source_product_id,
          catalog_item_id, name, sku, internal_code, oe_raw, oe_norm, mpn_raw,
          mpn_norm, brand, category, description, product_url, current_price,
          currency, is_available, identity_status, identity_reason, raw_data,
          source_updated_at, created_at, updated_at
        )
        SELECT
          md5('marko:catalog-product:xlsx:' || workspace_id::text || ':' ||
              lower(btrim(filename)) || ':' || sku)::uuid,
          workspace_id,
          'XLSX',
          md5('marko:xlsx:' || workspace_id::text || ':' ||
              lower(btrim(filename)))::uuid,
          sku,
          id,
          name,
          sku,
          sku,
          nullif(oe_raw, ''),
          nullif(oe_norm, ''),
          nullif(mpn_raw, ''),
          nullif(mpn_norm, ''),
          brand,
          category,
          description,
          product_url,
          current_price,
          currency,
          is_available,
          CASE WHEN identity_status = 'OE_CONFIRMED'
            THEN 'VERIFIED_EXACT' ELSE 'UNRESOLVED' END,
          coalesce(identity_reason, 'XLSX_IDENTITY_UNRESOLVED'),
          coalesce(raw_row, '{}'::json),
          updated_at,
          now(),
          now()
        FROM latest
        WHERE source_rank = 1
        ON CONFLICT (workspace_id, source_kind, source_id, source_product_id)
        DO NOTHING
        """
    )

    op.create_table(
        "price_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=True),
        sa.Column("evaluation_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("our_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("market_low", sa.Numeric(14, 2), nullable=True),
        sa.Column("market_high", sa.Numeric(14, 2), nullable=True),
        sa.Column("suggested_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("difference_percent", sa.Numeric(20, 10), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), server_default="0", nullable=False),
        sa.Column("evidence_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reason_codes", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("market_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('OVERPRICED', 'UNDERPRICED', 'IN_MARKET', "
            "'REVIEW_REQUIRED', 'NO_DATA', 'PROCESSING')",
            name="ck_price_assessment_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_price_assessment_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["catalog_products.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["pricing_recommendations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluation_key", name="uq_price_assessment_evaluation_key"),
    )
    op.create_index("ix_price_assessments_product_id", "price_assessments", ["product_id"])
    op.create_index(
        "ix_price_assessments_recommendation_id",
        "price_assessments",
        ["recommendation_id"],
    )
    op.create_index(
        "ix_price_assessment_product_time",
        "price_assessments",
        ["product_id", "computed_at"],
    )

    op.create_table(
        "attention_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("latest_assessment_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status", sa.String(length=24), server_default="PROCESSING", nullable=False
        ),
        sa.Column("severity", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "review_state", sa.String(length=16), server_default="OPEN", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('OVERPRICED', 'UNDERPRICED', 'IN_MARKET', "
            "'REVIEW_REQUIRED', 'NO_DATA', 'PROCESSING')",
            name="ck_attention_item_status",
        ),
        sa.CheckConstraint(
            "review_state IN ('OPEN', 'RESOLVED', 'IGNORED')",
            name="ck_attention_item_review_state",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["catalog_products.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["latest_assessment_id"], ["price_assessments.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_attention_item_product"),
    )
    op.create_index("ix_attention_items_workspace_id", "attention_items", ["workspace_id"])
    op.create_index("ix_attention_items_product_id", "attention_items", ["product_id"])
    op.create_index(
        "ix_attention_items_latest_assessment_id",
        "attention_items",
        ["latest_assessment_id"],
    )
    op.create_index(
        "ix_attention_workspace_status",
        "attention_items",
        ["workspace_id", "status", "updated_at"],
    )
    op.execute(
        """
        INSERT INTO attention_items (
          id, workspace_id, product_id, latest_assessment_id, status, severity,
          review_state, created_at, updated_at
        )
        SELECT
          md5('marko:attention:' || id::text)::uuid,
          workspace_id,
          id,
          NULL,
          CASE
            WHEN is_available IS NOT FALSE
              AND current_price IS NOT NULL
              AND nullif(oe_norm, '') IS NOT NULL
              THEN 'PROCESSING'
            ELSE 'REVIEW_REQUIRED'
          END,
          CASE
            WHEN is_available IS FALSE THEN 0
            WHEN current_price IS NULL OR nullif(oe_norm, '') IS NULL THEN 50
            ELSE 0
          END,
          CASE WHEN is_available IS FALSE THEN 'RESOLVED' ELSE 'OPEN' END,
          now(),
          now()
        FROM catalog_products
        """
    )


def downgrade() -> None:
    automated_runs = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM pricing_runs "
            "WHERE scope_confirmation_source = 'AUTOMATED_MONITORING'"
        )
    ).scalar_one()
    if automated_runs:
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260807_0044: automatic monitoring runs "
            "already depend on the new confirmation source"
        )
    op.drop_table("attention_items")
    op.drop_table("price_assessments")
    op.drop_table("catalog_products")
    op.drop_constraint(
        "ck_pricing_run_scope_confirmation_source",
        "pricing_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_pricing_run_scope_confirmation_source",
        "pricing_runs",
        "scope_confirmation_source IN "
        "('OPERATOR', 'SYSTEM_REPLAY', 'E2E_FIXTURE_REPLAY', 'LEGACY_UNBOUNDED')",
    )
