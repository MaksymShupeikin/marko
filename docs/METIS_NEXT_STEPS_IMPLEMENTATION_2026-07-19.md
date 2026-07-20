# METIS_NEXT_STEPS implementation report — 2026-07-19

## Executive result

Block 0 is complete as a bounded live Prom.ua discovery run. The result is not
the healthy `5+` competitors per OE assumed by the optimistic branch of the
plan:

- mean exact-OE working cohort: **2.53 offers per OE**;
- median: **1.5**;
- **20 of 30** OEs have at most two working offers, including seven with zero;
- only **4 of 30** OEs have at least five;
- strict automatic comparability: **0 of 146 retrieved offers**.

The project has real exact-OE coverage, but the current evidence is too narrow
and too incomplete for unattended pricing. Crosses are therefore a justified
Path-2 candidate, especially for filters and shock absorbers, but the paid
crosses phase was not started automatically.

Blocks 1–3 now have the missing technical workflow: a real live-data brand
draft, fail-closed YAML loading, a 200-slot review workbook, and a reproducible
accuracy/confusion-matrix evaluator. They remain blocked on human domain labels
and approval. Block 4 was not run because the 30-OE authority expired and its
prerequisites are not closed.

## Block 0 — bounded live Prom run

### Scope and method

- Source catalog: Yuri's supplied 4,901-row workbook.
- Source SHA-256:
  `7871f6b20b21d96bbd7b5c2ea8c951c2144a6adec04acac5229261c2172e0e91`.
- Sample: 30 unique syntactically valid OEs, six in each of radiator,
  shock-absorber, electrical, gasket, and filter.
- Selection: deterministic SHA-256 ordering with catalog-group diversity.
- Collection bound: two search pages, at most 50 retained sellers, at least one
  second configured delay, public Prom pages only.
- Canonical result set: `live_outputs/001.json` through `030.json`. The earlier
  manual probe `001_09G409061.json` is excluded from every aggregate.
- One seller contributes at most one offer because the existing matcher
  deduplicates by stable seller ID.

The internal authority record is
`docs/METIS_PROM_LIMITED_30_OE_AUTHORITY_2026-07-19.md`. It does not replace
Prom.ua terms or applicable law, and it does not authorize a 4,901-target run.

### Exact metric definitions

| Metric | Definition |
|---|---|
| Exact OE | Normalized target OE equals candidate `oe_raw` or candidate `sku`. Model-only and title-only retrievals do not count. |
| After used/KEMP filter | Exact OE minus detected KEMP and detected used/refurbished markers. UNKNOWN condition is retained, but is not proven NEW. |
| Recognized legacy guess | Classified by the quarantined 24-entry engineering map. This is diagnostic only and is not a production-valid brand result. |
| Automatic eligible | Existing typed comparability hard gate returned `PASS`. |

### Measured totals

| Metric | Result |
|---|---:|
| OE targets | 30 |
| Search candidates scanned | 1,296 |
| Seller-deduplicated offers retrieved | 146 |
| Exact-OE offers | 91 |
| Exact OE after detected used/KEMP filter | 76 |
| Mean after filter | 2.5333 |
| Median after filter | 1.5 |
| Zero working offers | 7 / 30 |
| One or two working offers | 13 / 30 |
| Three or four working offers | 6 / 30 |
| Five or more working offers | 4 / 30 |
| Recognized by quarantined engineering guesses | 18 / 76 |
| UNKNOWN under quarantined engineering guesses | 58 / 76 |
| Detected used/refurbished | 0 / 146 |
| Exact working offers with verified NEW marker | 1 / 76 |
| Strict automatic eligible | 0 / 146 |

The absence of detected used offers is not evidence that all 146 offers are new:
145 condition states are UNKNOWN. Every retrieved offer remains
`MANUAL_REVIEW`, with the same four hard-gate reasons:

- `MANUAL_CATEGORY_POLICY_UNMAPPED` — 146;
- `MANUAL_MISSING_OE_PROVENANCE` — 146;
- `MANUAL_MISSING_CONDITION` — 146;
- `MANUAL_MISSING_SOURCE_PROVENANCE` — 146.

### Category distribution

| Category | OE | Retrieved | Exact OE | After filter | Mean/OE | Median/OE |
|---|---:|---:|---:|---:|---:|---:|
| electrical | 6 | 39 | 22 | 18 | 3.00 | 2.50 |
| filter | 6 | 13 | 9 | 6 | 1.00 | 0.50 |
| gasket | 6 | 33 | 26 | 26 | 4.33 | 2.50 |
| radiator | 6 | 46 | 23 | 19 | 3.17 | 1.00 |
| shock absorber | 6 | 15 | 11 | 7 | 1.17 | 1.00 |

This deterministic 30-OE discovery sample measures the selected OEs. It is not
a probabilistic or representative estimate of all 4,901 products, so no
population confidence interval is claimed.

## Block 1 — real brand dictionary

The source plan says `DEFAULT_BRAND_TIERS` had 12 guesses. Repository inspection
showed **24**, not 12. The critique was directionally correct but its exact count
was stale.

Implemented:

1. Extracted 53 non-empty raw brand tokens, of which 51 are usable under the
   current normalizer. Twenty-six offers have no brand and one Cyrillic token
   (`Аналог`) cannot be normalized by the current ASCII brand contract.
2. Created `backend/config/brands.yaml` from the live observations, including
   offer counts, distinct target OEs, exact-working counts, and paired price
   ratios where available.
3. Marked the document `representative: false` and
   `domain_policy_approved: false`. Only KEMP is approved because its separate
   tier is a contractual Yuri requirement, not a market-quality guess.
4. Added `load_approved_brand_rules(...)`. Non-KEMP rules become active only if
   the whole policy and the individual rule are approved and reviewer/timestamp
   metadata exist. Contradictory or malformed approval fails closed.
5. Changed the runtime default to KEMP-only. The former 24 values remain under
   `UNAPPROVED_ENGINEERING_BRAND_TIERS` for audit and migration, not runtime use.
6. Connected the YAML path to local settings, Docker, Compose, and production
   Compose. The synthetic E2E harness uses a separate explicitly synthetic Bosch
   fixture so production data cannot inherit a test assumption.

Remaining domain work: a Ukrainian Prom reviewer must fill the yellow cells on
the workbook's `Бренды` sheet, then approve the resulting policy. No agent-
invented non-KEMP tier was activated.

## Block 2 — calibration

No real coefficient was emitted. Doing so now would be false precision because:

- approved non-KEMP brand rules: 0;
- human tier labels: 0;
- verified-new exact working offers: 1 of 76;
- reusing the same 30-OE discovery cohort for both tuning and undisclosed
  validation would introduce leakage.

The existing robust shrinkage calibration code remains intact and will receive
approved observations after Block 1. Current readiness is recorded in
`.artifacts/metis_next_steps_20260719/METIS_REAL_CALIBRATION_READINESS.json`.

## Block 3 — real tier validation

Implemented:

- `outputs/metis_next_steps_20260719/METIS_30_OE_REVIEW.xlsx` with five sheets:
  summary, per-OE coverage, all 146 listings, observed brands, and 200 manual
  label slots;
- editable label fields for same-part decision, condition, gold tier, target
  inclusion, reviewer, and comment;
- data validation, formulas, filters, frozen panes, source URLs, and explicit
  pending/missing states;
- `scripts/evaluate_real_tier_labels.py`, which reads the filled workbook,
  applies only approved YAML rules, and produces accuracy, per-tier recall, and
  a full confusion matrix;
- fail-closed dataset gate requiring the requested 200 labels, representative
  approval, named reviewer, and approved domain policy.

Current measured state is **0 labeled / 200**, with 146 live source rows and 54
empty source slots. Accuracy remains `null`; it was not fabricated from the
unlabeled data. Readiness evidence is in
`.artifacts/metis_next_steps_20260719/METIS_REAL_TIER_VALIDATION_READINESS.json`.

## Block 4 — 4,901-row live E2E

The real operator catalog workbook exists and is reproducibly measured:

- 4,901 source rows;
- 4,647 parser-importable rows;
- artifact SHA-256:
  `c0337041455cf36ff2a0919e8b8f87158368b82603badcd740072f4b83850af5`.

The full live parser-to-classification-to-calibration-to-recommendation run was
not started. Blocks 1–3 are not closed, strict discovery eligibility is 0/146,
and the bounded 30-OE source authority does not authorize 4,901 targets. The
explicit state is recorded in
`.artifacts/metis_next_steps_20260719/METIS_4901_LIVE_E2E_READINESS.json`.

## Block 5 — crosses from descriptions

The result is `TRIGGER_CANDIDATE`, not an automatic start:

- the mean 2.53 is between the plan's two headline thresholds;
- the median is 1.5;
- two-thirds of sampled OEs have at most two working exact-OE offers;
- filters and shock absorbers average roughly one.

This is enough evidence to reopen the paid Path-2 discussion with Yuri. The
existing description-cross extractor stays disabled for automatic identity, as
required. No TecDoc-class cross database or unapproved scope expansion was
built.

## Runtime defects corrected during the live run

1. Seller-subdomain Prom product URLs returned a redirect that the safe client
   correctly refused. Product URLs are now validated and canonicalized to the
   central `https://prom.ua/{lang}/p...html` form without enabling redirects or
   weakening host checks.
2. JSON comparison output is now written even when zero sellers are found, so
   zero coverage is observable rather than silently missing.
3. Candidate `sku` and `model_id` are retained in comparison JSON, making the
   exact-OE audit reproducible.

## Verification

| Check | Result |
|---|---|
| `uv run ruff check . ../scripts` | PASS |
| `uv run pytest -q` | **605 passed** |
| `python -m compileall` | PASS |
| XLSX ZIP integrity | PASS |
| Workbook formula-error scan | 0 matches |
| Workbook visual QA | all five sheets inspected; summary and table headers corrected |
| Real tier evaluator on current workbook | BLOCKED truthfully at 0/200 labels |

## Primary artifacts

| Artifact | SHA-256 |
|---|---|
| `outputs/metis_next_steps_20260719/METIS_30_OE_REVIEW.xlsx` | `d927a60784a9da3829d76bf94caec73f4100072c13ba085aa476929ffcbb0b3f` |
| `.artifacts/metis_next_steps_20260719/METIS_30_OE_LIVE_SUMMARY.json` | `8a9cdf9eefffc7dd7277aca284859e6c1787b836be7218a37b3eaa134bbd8fc4` |
| `backend/config/brands.yaml` | `315162b610bd078501d78a75b6d104578a346db8dd3adbd5176328b258a9d601` |
| `.artifacts/metis_next_steps_20260719/METIS_REAL_TIER_VALIDATION_READINESS.json` | `761b16e7bb3a59ddc04a27a3ae07d4f03bcf33eabbd32de1c4b250b51a1af329` |
| `.artifacts/metis_next_steps_20260719/METIS_REAL_CALIBRATION_READINESS.json` | `a2d35a7eb4ca1891c8abe4587e0005dd32703711f63b16420d8c19289e1c6173` |
| `.artifacts/metis_next_steps_20260719/METIS_4901_LIVE_E2E_READINESS.json` | `a67cb36c542bbc6a4a48e0317a70674eb7c3c4eebdd7e30b7cb22d9114844f24` |

## Required next decision

The next stage must not be a 4,901-item crawl. First, a named domain reviewer
must fill the `Бренды` and `Разметка 200` sheets, while a newly authorized
bounded collection supplies the remaining 54 real listing rows. Only after the
brand policy and representative gold set are approved can calibration be run
without inventing its inputs.
