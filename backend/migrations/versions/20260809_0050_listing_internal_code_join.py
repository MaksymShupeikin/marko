"""Extract private KEMP join codes from persisted owned-listing payloads.

Revision ID: 20260809_0050
Revises: 20260809_0049
Create Date: 2026-08-09

The source parser already persists labelled part numbers in ``raw_data``.  The
database derives the private join key from those immutable payload bytes so old
and new listing rows use one expression.  Multiple distinct private codes are
kept visible through the count and deliberately produce no join value.

The key itself must be the *same* string on both sides of the join.  The
catalogue column is written by ``normalize_identifier``, which folds confusable
Cyrillic letters into their Latin twins; ``marko_catalog_normalize`` keeps them.
Measured on the customer's own Prom export: one card carries ``77643352`` with a
Cyrillic ``с`` while the catalogue row carries a Latin ``C``.  Two normalizers
over one column do not produce a mismatch, they produce a position that never
joins and no report saying why, so the folding lives in ``marko_oem_join_key``
and the catalogue backfill of 20260809_0049 is corrected through it here.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260809_0050"
down_revision: str | None = "20260809_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION public.marko_oem_join_key(value text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
          SELECT regexp_replace(
            translate(
              upper(normalize(coalesce(value, ''), NFKC)),
              'АВСЕНКМОРТХУІЈЅ',
              'ABCEHKMOPTXYIJS'
            ),
            '[^A-Z0-9]',
            '',
            'g'
          )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.marko_listing_internal_codes(value json)
        RETURNS text[]
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
          SELECT CASE
            WHEN json_typeof(value -> 'part_numbers') = 'array' THEN
              COALESCE(
                ARRAY(
                  SELECT DISTINCT normalized
                  FROM (
                    SELECT public.marko_oem_join_key(part_number) AS normalized
                    FROM json_array_elements_text(
                      value -> 'part_numbers'
                    ) AS part_number
                  ) AS normalized_numbers
                  WHERE normalized ~ '^776[0-9A-Z]{1,9}$'
                  ORDER BY normalized
                ),
                ARRAY[]::text[]
              )
            ELSE ARRAY[]::text[]
          END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.marko_listing_internal_code(json)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
          SELECT CASE
            WHEN cardinality(codes) = 1 THEN codes[1]
            ELSE ''
          END
          FROM (
            SELECT public.marko_listing_internal_codes($1) AS codes
          ) AS extracted
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.marko_listing_internal_code_count(json)
        RETURNS smallint
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
          SELECT cardinality(
            public.marko_listing_internal_codes($1)
          )::smallint
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE listings
          ADD COLUMN catalog_internal_code_norm text
            GENERATED ALWAYS AS (
              public.marko_listing_internal_code(raw_data)
            ) STORED,
          ADD COLUMN catalog_internal_code_count smallint
            GENERATED ALWAYS AS (
              public.marko_listing_internal_code_count(raw_data)
            ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_listings_catalog_internal_code_norm
        ON listings (catalog_internal_code_norm)
        WHERE catalog_internal_code_norm <> ''
        """
    )
    # 20260809_0049 filled the catalogue column through marko_catalog_normalize,
    # which does not fold the Cyrillic twins.  Rows whose code was typed with one
    # were left empty there and would never join.  Only those are filled; a value
    # the application already wrote is never overwritten.
    op.execute(
        """
        UPDATE catalog_items
        SET internal_code_norm = public.marko_oem_join_key(internal_code_raw)
        WHERE internal_code_norm = ''
          AND internal_code_raw <> ''
          AND public.marko_oem_join_key(internal_code_raw) ~ '^776[0-9A-Z]{1,9}$'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_listings_catalog_internal_code_norm")
    op.execute(
        """
        ALTER TABLE listings
          DROP COLUMN catalog_internal_code_count,
          DROP COLUMN catalog_internal_code_norm
        """
    )
    op.execute("DROP FUNCTION public.marko_listing_internal_code_count(json)")
    op.execute("DROP FUNCTION public.marko_listing_internal_code(json)")
    op.execute("DROP FUNCTION public.marko_listing_internal_codes(json)")
    op.execute("DROP FUNCTION public.marko_oem_join_key(text)")
