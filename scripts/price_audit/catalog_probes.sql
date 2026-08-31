\set ON_ERROR_STOP on
\pset format unaligned
\pset fieldsep '|'
\pset tuples_only on

\echo [snapshot]
SELECT now() AT TIME ZONE 'UTC' AS captured_utc,
       count(*) AS listings,
       count(*) FILTER (WHERE current_price IS NULL) AS price_null,
       count(*) FILTER (WHERE current_price <= 0) AS price_non_positive,
       count(*) FILTER (WHERE is_available IS FALSE) AS unavailable
FROM listings;

\echo [raw_data_keys]
SELECT key, count(*)
FROM listings AS listing
CROSS JOIN LATERAL jsonb_object_keys(
    COALESCE(listing.raw_data::jsonb, '{}'::jsonb)
) AS key
GROUP BY key
ORDER BY count(*) DESC, key;

\echo [currency_and_measure_unit]
SELECT 'currency', currency, count(*)
FROM listings
GROUP BY currency
UNION ALL
SELECT 'measure_unit',
       COALESCE(
           raw_data::jsonb->>'measure_unit',
           raw_data::jsonb->>'measureUnit',
           '<missing>'
       ),
       count(*)
FROM listings
GROUP BY 2
ORDER BY 1, 3 DESC, 2;

\echo [raw_price_shapes]
SELECT count(*) AS total,
       count(*) FILTER (WHERE raw_data::jsonb->>'price' LIKE '%,%') AS comma,
       count(*) FILTER (WHERE raw_data::jsonb->>'price' LIKE '%.%') AS dot,
       count(*) FILTER (
           WHERE raw_data::jsonb->>'price' LIKE '%,%'
             AND raw_data::jsonb->>'price' LIKE '%.%'
       ) AS comma_and_dot,
       count(*) FILTER (
           WHERE raw_data::jsonb->>'price' ~ '[[:space:]]'
              OR position(chr(160) IN raw_data::jsonb->>'price') > 0
       ) AS whitespace_grouping
FROM listings;

\echo [number_shape_counts]
WITH candidates AS (
    SELECT id, name, sku, value AS candidate, 'raw_oem' AS origin
    FROM listings
    CROSS JOIN LATERAL jsonb_array_elements_text(
        raw_data::jsonb->'oem_numbers'
    ) AS value
    UNION ALL
    SELECT id, name, sku, sku, 'sku'
    FROM listings
    WHERE NULLIF(btrim(sku), '') IS NOT NULL
)
SELECT origin,
       count(*) AS total,
       count(*) FILTER (WHERE candidate !~ '[0-9]') AS without_digit,
       count(*) FILTER (WHERE candidate ~ '[А-Яа-яІіЇїЄєЁё]') AS cyrillic,
       count(*) FILTER (WHERE length(candidate) > 20) AS longer_than_20,
       count(*) FILTER (WHERE candidate ~ '^[0-9 .+()/-]{8,}$') AS numeric_like,
       count(*) FILTER (
           WHERE candidate ~ '^[[:alpha:]]+[0-9]+$'
              OR candidate ~ '^[0-9]+[[:alpha:]]+$'
       ) AS word_model_like
FROM candidates
GROUP BY origin
ORDER BY origin;

\echo [suspicious_number_samples]
WITH candidates AS (
    SELECT id, name, value AS candidate, 'raw_oem' AS origin
    FROM listings
    CROSS JOIN LATERAL jsonb_array_elements_text(
        raw_data::jsonb->'oem_numbers'
    ) AS value
    UNION ALL
    SELECT id, name, sku, 'sku'
    FROM listings
    WHERE NULLIF(btrim(sku), '') IS NOT NULL
)
SELECT origin, candidate, left(name, 120), id
FROM candidates
WHERE candidate !~ '[0-9]'
   OR candidate ~ '[А-Яа-яІіЇїЄєЁё]'
   OR length(candidate) > 20
   OR candidate IN ('PEUGEOT206', 'FORDSIERRA')
ORDER BY origin, candidate
LIMIT 80;

\echo [catalog_name_pathology_counts]
SELECT count(*) FILTER (
           WHERE name ~* '(комплект|пара|2[[:space:]]*шт)'
       ) AS set_pair_or_two,
       count(*) FILTER (
           WHERE name ~* '(лів|прав|лев|перед|задн|внутр|зовніш|внешн)'
       ) AS side_position,
       count(*) FILTER (
           WHERE name ~* 'передач'
       ) AS transmission_word_prefix_collision,
       count(*) FILTER (
           WHERE name ~* 'кпп'
       ) AS kpp_without_prefix_collision,
       count(*) FILTER (
           WHERE name ~* '(маточин|ступиц|кришк|крышк)'
       ) AS bilingual_synonym_candidates
FROM listings;

\echo [laterality_prefix_collision_exposure]
SELECT count(*) FILTER (WHERE name ~* 'передач') AS transmission_word,
       count(*) FILTER (
           WHERE name ~* 'передач'
             AND name ~* 'задн'
       ) AS transmission_word_with_rear,
       count(*) FILTER (
           WHERE name ~* '(внутр)'
       ) AS inner,
       count(*) FILTER (
           WHERE name ~* '(зовніш|внешн)'
       ) AS outer
FROM listings;

\echo [catalog_pathology_samples]
SELECT id, left(name, 150), sku, raw_data::jsonb->'oem_numbers'
FROM listings
WHERE name ~* '('
    'комплект|пара|2[[:space:]]*шт|'
    'короб[^ ]*[[:space:]]+передач|'
    'внутр|зовніш|внешн'
    ')'
ORDER BY name
LIMIT 60;
