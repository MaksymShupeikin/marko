# METIS action plan — implementation record

Date: 2026-07-19  
Input plan: `/Users/leonidpofa/Downloads/METIS_ACTION_PLAN.md`  
Input SHA-256: `8c171c0d350c670847d13da7e0d5ede9b0e350a53898015be067b63fac81af50`

## Outcome

The executable, non-impersonating part of the action plan is complete:

- a deterministic follow-on sample of 30 catalog OE values was prepared;
- collection stopped after 8 OE because the bounded target was exceeded;
- 67 additional seller-deduplicated listings were stored;
- the initial 146 and additional 67 listings form 213 distinct Prom URLs/product IDs;
- the manual-review sheet now contains exactly 200 real source rows and zero blank
  source slots;
- all human label and non-KEMP approval fields remain unfilled;
- Path 2 crosses, calibration, the recommendation E2E, and the 4,901-target run
  were not started because their stated human gates are not closed.

This is source-set completion, not real-market accuracy proof and not production
activation.

## Bounded collection

| Item | Result |
|---|---:|
| Initial OE targets | 30 |
| Additional OE targets attempted | 8 |
| Additional OE targets not attempted after stop | 22 |
| Initial listings | 146 |
| Additional listings | 67 |
| Stored listings total | 213 |
| Distinct listing URLs | 213 |
| Gold-set source rows | 200 |
| Missing gold-set source rows | 0 |
| Human labels | 0 / 200 |

The follow-on sample uses the same five families as the discovery run, excludes
the first 30 normalized OE values, requires an available positive-stock catalog
row and valid product URL, sorts candidates by SHA-256, selects six per family,
and interleaves families. Source authority is recorded in
`docs/METIS_PROM_ADDITIONAL_54_LISTINGS_AUTHORITY_2026-07-19.md`.

Three target logs report an HTTP 301 for search page 2. No CAPTCHA, explicit
access denial, 403, or parser traceback was observed. Those targets retained
their page-1 offers; the condition is preserved as a coverage caveat and was not
hidden by retrying outside the completed top-up authority.

## Review workbook

Final workbook:

`outputs/metis_action_plan_20260719/METIS_200_REAL_LISTING_REVIEW.xlsx`

Sheets:

1. `Итог` — reconciled totals and visible stop gates.
2. `OE покрытие` — all 38 attempted OE targets and extraction counts.
3. `Объявления` — all 213 raw parsed offers with URL and source hash.
4. `Бренды` — 65 observed rows, 63 usable normalized tokens, two evidence URLs
   per observed token where available, and explicit reviewer inputs.
5. `Разметка 200` — exactly 200 distinct real source listings; human inputs are
   `same_part_gold`, `condition_gold`, `tier_gold`,
   `include_in_target_gold`, `reviewer`, and `comment`.

The workbook was generated with `@oai/artifact-tool`, inspected for formula
errors, and rendered for visual review across all five sheets. No formula error
match was found.

## Contract corrections implemented

The action plan described two safeguards as already present, but the current
code did not fully implement them. They are now explicit:

1. `normalize_brand` maps the bounded aliases `КЕМР`, `КЕМП`, `БОШ`, and `ФЕБИ`
   to `KEMP`, `BOSCH`, and `FEBI`. Arbitrary Cyrillic text still normalizes to
   no rule and therefore abstains.
2. Every active non-KEMP Prom rule now requires row-level `approved_by`, a valid
   ISO-8601 `approved_at`, and at least one credential-free HTTPS Prom evidence
   URL. Document-level approval alone cannot activate an unauditable row.
3. The synthetic E2E brand fixture uses an explicit `fixture://` evidence
   namespace and remains non-market evidence.

The generated review draft is
`.artifacts/metis_action_plan_20260719/METIS_200_BRANDS_DRAFT.yaml`. It loads
fail-closed with only KEMP active. It was intentionally not copied over the
runtime dictionary because no human has approved a non-KEMP row.

## Evaluator behavior

`scripts/evaluate_real_tier_labels.py` now defaults to the 200-row workbook and
separates:

- rows reviewed by a human;
- rows included in accuracy metrics;
- rows deliberately excluded from metrics.

An included metric row must have `same_part_gold=yes` and cannot be marked used,
refurbished, or conflict. The current truthful result is `BLOCKED`: 200 source
rows, 200 pending labels, zero included cases, unapproved representativeness,
and an unapproved brand policy.

## Human gates that remain

### Brand policy

A domain reviewer must inspect live Prom evidence and approve only defensible
non-KEMP tiers. Every activated YAML row must include its own reviewer,
timestamp, and evidence URL. Unknown or heterogeneous umbrella brands remain
`unknown`. Current approved non-KEMP rules: **0**.

### Gold-set labels

A human must open each source URL before filling the six yellow columns in
`Разметка 200`. The classifier output must not be used as the basis for the gold
label. After all rows are reviewed, run:

```bash
cd backend
uv run python ../scripts/evaluate_real_tier_labels.py \
  --representative \
  --approved-by "REAL_REVIEWER_NAME" \
  --output ../.artifacts/metis_action_plan_20260719/METIS_200_TIER_VALIDATION.json
```

The reviewer name and representativeness flag must be supplied by the real
reviewer; they are not inferred from task ownership.

### Crosses and later stages

The proposed cross-number stage is commercial scope and requires Yuri's express
consent. Until then, do not extract or query description crosses. Calibration
must wait for approved brand tiers and reviewed labels. The first recommendation
E2E must be limited to 100–200 products with validated categories; the full
4,901-target run remains later.

## Stage decision

| Stage | Status | Reason |
|---|---|---|
| Complete 200 real source rows | COMPLETE | 200/200 populated, 0 duplicates |
| Approve brand tiers | BLOCKED_HUMAN_INPUT | 0 approved non-KEMP rows |
| Review 200 labels | BLOCKED_HUMAN_INPUT | 0/200 reviewed |
| Path 2 crosses | BLOCKED_YURI_CONSENT | No consent recorded |
| Real calibration | NOT_STARTED | Prior gates open |
| 100–200 recommendation E2E | NOT_STARTED | Prior gates open |
| Full 4,901 live run | NOT_STARTED | Explicitly later |

