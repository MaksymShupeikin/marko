# METIS Description Crosses Path 2 — Stages A+B Implementation

Date: 2026-07-19  
Stage identity: `METIS_DESCRIPTION_CROSSES_AB`  
Gate result: `BLOCKED_INPUT_DESCRIPTIONS`  
Stage C/D status: not started

## 1. Literal scope executed

The attached instruction was implemented only through `STOP-GATE AB`:

- Stage A deterministic extraction from `listing.description`;
- every length, ratio, and context/window threshold is loaded from
  `backend/config/crosses.yaml`;
- false-positive filters for dimensions, years/ranges, phones, VIN, GTIN,
  engine displacement, Yuri's own OE, and prices;
- raw context retention using 80 configured characters on each side;
- Stage B category, price-band, reciprocity, explicit-marker, and pair
  deduplication rules;
- `CONFIRMED | REVIEW | REJECTED | UNKNOWN` fail-closed states;
- an append-only canonical `cross_links` persistence model;
- `market_observations.via_cross` and nullable `cross_link_id` provenance;
- a runtime Stage C guard that checks active approved non-KEMP rules rather
  than draft YAML rows;
- offline replay and a human-review workbook.

The frozen Prom parser was not changed. No Stage C collection, cross-expanded
offer ingestion, pricing use, recommendation E2E, or Stage D UI/report path was
started.

## 2. Important append-only interpretation

The instruction simultaneously says that Stage A emits `UNKNOWN`, Stage B
selects one senior status per pair, and `cross_links` is append-only. Persisting
an A row and then mutating it in B would violate append-only; persisting both
would violate "one pair — one record".

The implementation therefore performs A and B in one deterministic analysis
snapshot, aggregates every source in `source_evidence`, selects the senior
status, and appends exactly one immutable canonical row per
`(pricing_run_id, our_oem_norm, extracted_oem_norm)`. `UNKNOWN` remains a valid
final state for evidence that cannot pass validation. Existing run snapshots
may be reused only with the same pair set, method version, and config SHA-256;
they are never updated.

## 3. Replay facts

Pinned input:

`./.artifacts/metis_next_steps_20260719/METIS_30_OE_OFFERS.csv`

Input SHA-256:

`7ff431a5cceb923586ccc07fc9cc3f786247a4d10b73bbbcf28775f4f9de26d9`

Observed facts:

| Metric | Result |
|---|---:|
| Saved listings | 146 |
| Unique listing IDs | 146 |
| Unique Prom URLs | 146 |
| Non-empty descriptions | 0 |
| Empty/short descriptions | 146 |
| Stage A candidates | 0 |
| CONFIRMED | 0 |
| REVIEW | 0 |
| REJECTED | 0 |
| Network requests during replay | 0 |

The zero candidate count is not evidence that real cross numbers do not exist.
It proves only that the saved structured replay discarded or never received
all 146 descriptions.

## 4. Mandatory real-fixture gate

The instruction requires positive fixtures taken from the 146 real saved
descriptions. The source corpus contains no such descriptions, so the following
acceptance cases cannot truthfully be created:

- real radiator description where a dimension is rejected;
- real description with three `аналог` numbers extracted;
- real description where phone and year are rejected.

The empty-description case is proven by all 146 rows. Synthetic logic tests
exercise the remaining branches, but they are explicitly named and are not
counted as the mandatory real-fixture proof.

## 5. Stage C runtime gate

The current approved brand loader exposes KEMP only. Calling the Stage C guard
therefore raises exactly:

```text
brand dictionary is empty; Stage C is pointless: new offers would all classify as UNKNOWN
```

Draft non-KEMP rows in `backend/config/brands.yaml` do not satisfy this guard.

## 6. Verification evidence

- Ruff: passed.
- Python compileall: passed.
- Tests: `645 passed, 1 skipped`.
- Stage-specific synthetic A/B tests: 13 passed.
- Skipped test: optional disposable-PostgreSQL store-registration integration;
  unrelated to Path 2.
- Alembic offline PostgreSQL SQL generation: passed through current head; the
  generated SQL contains `cross_links`, both observation provenance columns,
  foreign keys, indexes, and checks.
- Offline replay: byte-deterministic on a repeated execution.
- Workbook: four sheets inspected, top and bottom of the 146-row availability
  sheet rendered, no formula-error matches.

## 7. STOP-GATE AB decision

`BLOCKED_INPUT_DESCRIPTIONS`

Human review cannot answer "real link or garbage?" because the review export
contains zero rows. Execution stops here as required.

The next permissible stage is not C. First obtain a permission-safe pinned
description snapshot for these same 146 URLs (or a user-supplied equivalent),
rerun A+B offline, and let a human review every `CONFIRMED` and `REVIEW` row.
