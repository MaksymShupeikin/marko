"""Server-side owned-catalog identity, sorting and paging support.

Revision ID: 20260730_0028
Revises: 20260729_0027
Create Date: 2026-07-30

The functions deliberately mirror ``marko.services.owned_catalog``.  Keeping
the expressions in the database lets the API group and page before loading
listing payloads while preserving the stable product identifiers exposed by
the original Python implementation.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260730_0028"
down_revision: str | None = "20260729_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION public.marko_catalog_normalize(value text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
          SELECT regexp_replace(
            upper(normalize(coalesce(value, ''), NFKC)),
            '[^[:alnum:]]',
            '',
            'g'
          )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.marko_catalog_canonical_sku(
          value text,
          brand_value text
        )
        RETURNS text
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
        DECLARE
          result text := public.marko_catalog_normalize(value);
          brand_code text := public.marko_catalog_normalize(brand_value);
        BEGIN
          IF result = '' OR brand_code = '' THEN
            RETURN result;
          END IF;
          IF left(result, length(brand_code)) = brand_code
             AND length(result) - length(brand_code) >= 3 THEN
            result := substr(result, length(brand_code) + 1);
          END IF;
          IF right(result, length(brand_code)) = brand_code
             AND length(result) - length(brand_code) >= 3 THEN
            result := left(result, length(result) - length(brand_code));
          END IF;
          RETURN result;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.marko_catalog_identity_kind(
          brand_value text,
          sku_value text,
          model_value text,
          oe_value text
        )
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
          SELECT CASE
            WHEN public.marko_catalog_normalize(brand_value) <> ''
              AND public.marko_catalog_canonical_sku(sku_value, brand_value) <> ''
              THEN 'brand_sku'
            WHEN btrim(coalesce(model_value, '')) <> '' THEN 'prom_model'
            WHEN public.marko_catalog_normalize(brand_value) <> ''
              AND public.marko_catalog_normalize(oe_value) <> ''
              THEN 'brand_oe'
            WHEN length(public.marko_catalog_canonical_sku(sku_value, brand_value)) >= 3
              THEN 'sku'
            ELSE 'listing'
          END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.marko_catalog_identity_value(
          brand_value text,
          sku_value text,
          model_value text,
          oe_value text,
          store_value uuid,
          listing_value uuid
        )
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
          SELECT CASE
            WHEN public.marko_catalog_normalize(brand_value) <> ''
              AND public.marko_catalog_canonical_sku(sku_value, brand_value) <> ''
              THEN public.marko_catalog_normalize(brand_value)
                || ':' || public.marko_catalog_canonical_sku(sku_value, brand_value)
            WHEN btrim(coalesce(model_value, '')) <> ''
              THEN btrim(model_value)
            WHEN public.marko_catalog_normalize(brand_value) <> ''
              AND public.marko_catalog_normalize(oe_value) <> ''
              THEN public.marko_catalog_normalize(brand_value)
                || ':' || public.marko_catalog_normalize(oe_value)
            WHEN length(public.marko_catalog_canonical_sku(sku_value, brand_value)) >= 3
              THEN public.marko_catalog_canonical_sku(sku_value, brand_value)
            ELSE store_value::text || ':' || listing_value::text
          END
        $$
        """
    )

    # The first index supplies bounded identity lookups for the selected page.
    # The remaining expression indexes document and accelerate the normalized
    # code/name lookup contract without storing a second mutable identity copy.
    op.execute(
        """
        ALTER TABLE listings
          ADD COLUMN catalog_identity_kind text
            GENERATED ALWAYS AS (
              public.marko_catalog_identity_kind(
                brand, sku, model_id, raw_data ->> 'oe_raw'
              )
            ) STORED,
          ADD COLUMN catalog_identity_value text
            GENERATED ALWAYS AS (
              public.marko_catalog_identity_value(
                brand, sku, model_id, raw_data ->> 'oe_raw', store_id, id
              )
            ) STORED,
          ADD COLUMN catalog_sku_norm text
            GENERATED ALWAYS AS (
              public.marko_catalog_normalize(sku)
            ) STORED,
          ADD COLUMN catalog_oe_norm text
            GENERATED ALWAYS AS (
              public.marko_catalog_normalize(raw_data ->> 'oe_raw')
            ) STORED,
          ADD COLUMN catalog_model_norm text
            GENERATED ALWAYS AS (
              public.marko_catalog_normalize(model_id)
            ) STORED,
          ADD COLUMN catalog_brand_norm text
            GENERATED ALWAYS AS (
              public.marko_catalog_normalize(brand)
            ) STORED,
          ADD COLUMN catalog_name_norm text
            GENERATED ALWAYS AS (
              public.marko_catalog_normalize(name)
            ) STORED,
          ADD COLUMN catalog_description_norm text
            GENERATED ALWAYS AS (
              public.marko_catalog_normalize(raw_data ->> 'description')
            ) STORED,
          ADD COLUMN catalog_completeness smallint
            GENERATED ALWAYS AS (
              (
                CASE
                  WHEN btrim(coalesce(raw_data ->> 'image', ''))
                    LIKE 'http://%'
                    OR btrim(coalesce(raw_data ->> 'image', ''))
                      LIKE 'https://%'
                    THEN 1 ELSE 0
                END
                + CASE WHEN brand IS NOT NULL AND brand <> ''
                    THEN 1 ELSE 0 END
                + CASE WHEN sku IS NOT NULL AND sku <> ''
                    THEN 1 ELSE 0 END
                + CASE WHEN current_price IS NOT NULL THEN 1 ELSE 0 END
                + CASE WHEN is_available IS NOT NULL THEN 1 ELSE 0 END
                + CASE WHEN model_id IS NOT NULL AND model_id <> ''
                    THEN 1 ELSE 0 END
              )
            ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_listings_owned_catalog_identity
        ON listings (catalog_identity_kind, catalog_identity_value, store_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_listings_owned_catalog_sku_norm
        ON listings (catalog_sku_norm)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_listings_owned_catalog_oe_norm
        ON listings (catalog_oe_norm)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_listings_owned_catalog_name_lower
        ON listings (lower(name))
        """
    )
    op.execute(
        """
        CREATE INDEX ix_listings_owned_catalog_store_first
        ON listings (store_id, name, id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_listings_owned_catalog_store_first")
    op.execute("DROP INDEX ix_listings_owned_catalog_name_lower")
    op.execute("DROP INDEX ix_listings_owned_catalog_oe_norm")
    op.execute("DROP INDEX ix_listings_owned_catalog_sku_norm")
    op.execute("DROP INDEX ix_listings_owned_catalog_identity")
    op.execute(
        """
        ALTER TABLE listings
          DROP COLUMN catalog_completeness,
          DROP COLUMN catalog_description_norm,
          DROP COLUMN catalog_name_norm,
          DROP COLUMN catalog_brand_norm,
          DROP COLUMN catalog_model_norm,
          DROP COLUMN catalog_oe_norm,
          DROP COLUMN catalog_sku_norm,
          DROP COLUMN catalog_identity_value,
          DROP COLUMN catalog_identity_kind
        """
    )
    op.execute(
        "DROP FUNCTION public.marko_catalog_identity_value("
        "text, text, text, text, uuid, uuid)"
    )
    op.execute(
        "DROP FUNCTION public.marko_catalog_identity_kind(text, text, text, text)"
    )
    op.execute("DROP FUNCTION public.marko_catalog_canonical_sku(text, text)")
    op.execute("DROP FUNCTION public.marko_catalog_normalize(text)")
