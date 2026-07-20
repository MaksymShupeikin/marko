# METIS Exact OE vs OE + Crosses — Implemented Discovery Measurement

Date: 2026-07-19  
Stage: `METIS_CROSS_DISCOVERY_MEASUREMENT_2026_07_19`  
Stage result: `PASS`  
Automatic pricing: `NO`

## 1. Direct result

The requested same-set A/B measurement is implemented and reproducible. It
uses the same stratified 30-OE sample for exact OE and one-hop description
cross discovery. The cross path found more unvalidated seller candidates, but
did not increase the number of positions with any result.

| Metric | Exact OE | OE + cross discovery | Delta |
|---|---:|---:|---:|
| Positions with candidate results | 28/30 | 28/30 | 0 |
| Positions with at least 2 independent seller candidates | 19/30 | 20/30 | +1 |
| Independent seller candidates summed across positions | 91 | 155 | +64 |
| Mean candidates per position | 3.0333 | 5.1667 | +2.1334 |
| Median candidates per position | 2 | 2 | 0 |
| Positions receiving any added seller candidate | — | 5/30 | — |
| Match precision | not labeled | not labeled | unknown |
| Tier precision | not labeled | not labeled | unknown |
| Confident recommendations | 0 | 0 | 0 |
| Erroneous upward recommendations emitted | 0 | 0 | 0 |

The `+64` value is a discovery ceiling, not a valid-offer count and not a
commercial-lift claim. An exact SKU can still refer to another product category;
one captured example demonstrates this failure mode. The implementation keeps
all such rows outside pricing until independent labels exist.

## 2. Defects repaired

### Product description boundary

Prom product pages expose description evidence as `descriptionPlain` and
`descriptionFull`. The normalized `Product` model previously read only
`description`, making all 146 retained descriptions empty. The boundary now
prefers `descriptionPlain`, falls back to `descriptionFull`, and leaves the
frozen Prom parser unchanged.

Result: 146/146 pinned product pages now have non-empty descriptions and 146
gzip raw-evidence snapshots. The normalized description input SHA-256 is
`a6014d9afba196e53e8d43850976b47d65891521cf314a6b29b11c7460e78bd9`.

### Reproducible default replay

`run_description_crosses_replay.py` previously defaulted to the historical
empty-description CSV. It now defaults to the enriched pinned snapshot, while
the old input remains addressable through `--input`.

### Independent-seller identity

Cross corroboration now counts stable Prom `seller_id` values. A normalized
seller name is used only when the ID is absent. Two display-name variants from
one seller therefore cannot satisfy the two-independent-seller gate.

### KEMP exclusion policy

Owned inventory is excluded by Yuri's `seller_id=2847093`, not by the KEMP
brand. This returns 15 independent KEMP offers to the exact-OE discovery
baseline: the old working count was 76 rows; the corrected count is 91.

## 3. Cross extraction and discovery controls

- one-hop expansion only;
- 608 extracted source candidates and 6,715 rejected noise tokens;
- 408 deduplicated `(our OE, cross OE)` pairs;
- 68 `CONFIRMED`, 339 `REVIEW`, 1 `REJECTED`;
- only 60 `CONFIRMED` links with at least two independent source sellers enter
  search discovery;
- 60 pinned cross queries replayed offline, 0 network queries on verification;
- 2,740 raw candidates scanned and 95 discovery-candidate offer rows exported;
- owned seller, unavailable, used/refurbished, and condition-conflict rows are
  excluded from discovery candidates;
- every retained row has `pricing_eligible=false` and block reasons for missing
  category, human match, and human tier validation.

The public `PromGateway.search()` boundary yields raw products only. It never
calls the similarity/comparability engine and cannot authorize a recommendation.

## 4. Workbook

The review workbook is:

`outputs/metis_cross_coverage_20260719/METIS_EXACT_OE_VS_CROSSES.xlsx`

It contains:

1. the exact-OE versus cross A/B dashboard;
2. all 30 target positions;
3. 60 cross-link review rows with `MATCH/NOT_MATCH/UNCERTAIN` controls;
4. 95 offer-review rows with match, tier, condition, and availability controls;
5. method, input hashes, parser boundary, KEMP policy, and stop-gate notes.

All six rendered review ranges were inspected. The formula-error scan found no
`#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, or `#N/A` cells. Workbook SHA-256:
`162b71e24c34feceb44633b13c826c66cee26ab54c1c9c0b55cc96a4ba8f093d`.

## 5. Verification

- `uv run ruff check .`: passed;
- complete backend suite: 666 passed, 1 skipped;
- description A+B replay: 146/146 descriptions, 0 network requests,
  `READY_FOR_HUMAN_REVIEW`;
- cross discovery replay: 60/60 pinned queries, 0 network requests;
- frozen parser SHA-256:
  `1856f717a7fa1933c98487260d1873f9f1f4d16058af0250019d3fcfb25a7b66`.

The test count above is the required final target after the stable-seller-ID
regression test; it must be reconfirmed by the final full-suite run.

## 6. Gate interpretation

The implementation and measurement stage passes. Pricing activation does not:
match precision and tier precision are intentionally `null`, not zero, because
the workbook has not yet been independently labeled. The next stage is human
validation of links and offers. Until that stage passes, recommendation state
is `INSUFFICIENT_VALIDATED_DATA` and automatic pricing remains disabled.

