# Metis cross live smoke — 2026-07-20

## Result

A bounded discovery-only cross test completed successfully. No price recommendation
was activated and no database row or seller price was changed.

## Offline extraction replay

- retained Prom product pages: 146;
- non-empty descriptions: 146;
- physical network requests: 0;
- extracted source candidates: 608;
- rejected noise tokens: 6,715;
- deduplicated OE pairs: 408;
- `CONFIRMED`: 68;
- `REVIEW`: 339;
- `REJECTED`: 1;
- result: `READY_FOR_HUMAN_REVIEW`.

The output is in `.artifacts/metis_cross_smoke_20260720`.

## Compatibility regression found and repaired

The 60-query coverage replay initially failed because retained normalized Product
snapshots predated the additive `characteristics` field. Reconstructing the dataclass
with `Product(**snapshot)` was not backward-compatible.

The fix adds `Product.from_normalized_snapshot()`:

- missing additive fields become `None` and remain fail-closed;
- existing SKU, seller and availability evidence is retained;
- unknown snapshot fields are rejected as schema drift;
- Apollo data is not re-parsed through the normalized snapshot boundary.

The 60 cached cross queries then replayed with zero network requests. Coverage remained:

- exact OE: 91 independent sellers across 28/30 positions;
- OE plus cross discovery: 155 independent sellers across 28/30 positions;
- added seller candidates: 64 across 5 positions;
- confident recommendations: 0.

## Fresh bounded Prom smoke

The fresh run used a one-time `PERMITTED_LIMITED` scope reference:
`user-directive-2026-07-20-bounded-cross-smoke-3-queries`.

Limits:

- three cross-OE queries;
- one search page per query;
- two attempts maximum;
- discovery only;
- no recommendation emission;
- no database writes.

Queries and raw result counts:

| Cross OE | Raw products |
|---|---:|
| `0025165` | 16 |
| `02090F` | 29 |
| `1190108` | 29 |

Aggregate:

- network queries: 3;
- raw candidates scanned: 74;
- exact cross offer rows: 1;
- discovery candidates after hard filters: 1;
- positions with added independent seller candidates: 1;
- automatic pricing allowed: false.

Retained candidate:

| Field | Value |
|---|---|
| Yuri OE | `9065401517` |
| Cross OE | `1190108` |
| Listing | `3122803874` |
| Seller | `VIA-MARKET`, seller ID `4078882` |
| Brand | `Metzger` |
| SKU | `1190108` |
| Price | `412 UAH` |
| Title | `Датчик гальмівний MB VITO/MIXTO ФУРГОН (W639) 115 CDI 2003.09- METZGER (1190108)` |
| URL | `https://prom.ua/ua/p3122803874-datchik-tormoznoj-vitomixto.html` |
| Pricing eligible | `false` |

The row remains blocked by missing category validation, human match label and human tier
label. Condition is `UNKNOWN`; predicted tier is `unknown`. The smoke proves that the
fresh acquisition and cross discovery path works, not that this pair is commercially
comparable.

## Visual candidate adjudication

The retained candidate was opened in Safari through Computer Use and reviewed against
the Yuri catalog seed.

- identity decision: `MATCH` with high confidence;
- normalized part type: brake-pad wear sensor;
- Prom manufacturer and part code: `Metzger 1190108`;
- Prom original-number section explicitly contains `9065401517`;
- Prom marks the product as `New` and compatible with Mercedes-Benz and Volkswagen;
- independent indexed catalog evidence also maps `Metzger 1190108` to OEM
  `9065401517` and describes it as a brake-pad wear warning contact.

This clears the identity question for this single candidate, but not commercial price
comparability. Package quantity, unit basis, installation-position equivalence and an
approved tier label remain unknown. The offer therefore stays fail-closed at
`MANUAL_REVIEW` and is not admitted to pricing or calibration.

The live page showed a sale price of `330 UAH` with `412 UAH` crossed out. The earlier
discovery snapshot retained `412 UAH`; this is a concrete example of why observation
time and sale/reference price must remain separate fields.

Review artifact:

- `.artifacts/metis_cross_candidate_review_20260720/METIS_CROSS_CANDIDATE_REVIEW_3122803874.yaml`.

## Verification

- targeted cross/parser tests: `45 passed`;
- full backend suite: `771 passed, 4 skipped`;
- Ruff: passed;
- compileall: passed;
- fail-closed probe: `NOT_PERMITTED` stopped before the first HTTP request;
- offline coverage replay: `60/60`, zero network requests.

Artifacts:

- `.artifacts/metis_cross_smoke_20260720/METIS_CROSSES_AB_SUMMARY.json`;
- `.artifacts/metis_cross_live_smoke_20260720/METIS_CROSS_COVERAGE_SUMMARY.json`;
- `.artifacts/metis_cross_live_smoke_20260720/METIS_CROSS_COVERAGE_MANIFEST.json`;
- `.artifacts/metis_cross_live_smoke_20260720/cross_search_outputs/`.
