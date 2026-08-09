# Semantic discovery without OE: pilot results (2026-08-09)

## Direct conclusion

The second parser is technically feasible and the isolated end-to-end pilot
works: KEMP card text/characteristics/images can generate descriptive Prom
queries, obvious false candidates can be rejected deterministically, and Luna
can review the remaining frozen card/image pair under a strict fail-closed
contract.

The pilot does **not** prove that all no-OE rows can be matched accurately.
It proves that all current rows can enter the planning layer and that one real
live acquisition/review path is reproducible. Representative retrieval
precision/recall still requires a category-stratified human-labelled sample.

## Current catalog boundary

Input: `OE_каталог_2026-08-09.xlsx`, current snapshot used by the audit.

- Catalog rows: **4,901**.
- Rows with confirmed OE: **3,284 (67.01%)**.
- Rows without confirmed OE: **1,617 (32.99%)**.
- No-OE rows joined to the original KEMP export: **1,617/1,617**.
- Safe descriptive query plans: **1,617/1,617**.
- Rows with source description: **1,617/1,617**.
- Rows with at least one source image: **1,617/1,617**.
- Rows with structured characteristics: **1,593/1,617 (98.52%)**.
- Rows typed by the current closed part-family vocabulary: **1,615/1,617
  (99.88%)**.
- Untyped rows: card `1230665005` (`Защита`) and card `2179741467`
  (`Прикуриватель в сборе Daewoo Lanos`).

This is **query-planning coverage**, not matching accuracy.

Audit artifact:
`.artifacts/semantic_discovery_without_oe_catalog_audit_final_20260809.json`

SHA-256:
`dc8a4732bc860ecdbb5b38cc78002fb6c5061f9472dcd88dc49d972b4205acc6`

## Real live pilot

Seed card: `1153724243`, rear oil shock absorber for Ford Sierra 1.6/1.8/2.0,
1982–1993.

Executed retrieval query:

```text
Амортизатор задний Ford (Форд) Sierra 1.6-1.8-2.0 82-93 масло
```

The query contained no KEMP internal/source code, MPN, or unconfirmed
candidate number. One Prom search page and three external detail cards were
allowed.

Observed results:

- 4 HTTP responses frozen and SHA-256 verified;
- 29 unique cards returned;
- 13 owned KEMP-store cards excluded;
- 10 external cards rejected by explicit conflicts: six front-position
  shocks and four rear gas shocks against the rear oil seed;
- 6 external oil/rear candidates remained eligible for Luna/manual review;
- no HTTP 403/429/CAPTCHA and no collection error.

The best-ranked retained card was Prom product `2136772682`, a SATO tech rear
oil shock absorber for the same broad Ford Sierra engine/year scope.

Collection artifact:
`.artifacts/semantic_discovery_without_oe_live_v3_20260809`

Collection summary SHA-256:
`302bd029c1d77238e049a4d34a86ff895f6382917d677d0accce66bbf0519782`

## Final Luna xhigh result

The final review replay used the frozen live candidate and two SHA-256-verified
images. It performed **zero** additional Prom requests. Before model review,
the text snapshot removed:

- KEMP internal and source catalog codes;
- every unconfirmed seed candidate number;
- candidate SKU, MPN, OE and labelled part-number fields;
- Prom part-code/OE grouping numbers;
- every monetary field and obvious price expression.

The model returned only snapshot-bound `evidence_id` values. The first answer
was rejected because it marked the images diagnostic without citing a bound
image-content-hash ID. The one permitted repair corrected that evidence
binding. The second answer passed the strict schema and server-side evidence
hash validation.

Final result:

- Luna verdict: `MANUAL_REVIEW`;
- pipeline status: `SEMANTIC_MANUAL_REVIEW`;
- match class: `PLAUSIBLE_ANALOGUE`;
- semantic score: `78/100` (uncalibrated, not a probability);
- decision confidence: `93/100` for the fail-closed decision;
- `oe_numbers_inferred=[]`;
- `identity_proven=false`;
- `automatic_eligible=false`;
- `pricing_eligible=false`.

Why Luna abstained: broad part type, rear position, oil damping, Ford Sierra,
years and engines align, and both images show the same broad eyelet-mounted
shock-absorber form. Exact dimensions, mounting geometry, detailed fitment,
construction equivalence and an independent identity anchor remain absent;
the aftermarket brands also differ. The candidate is useful for a human, but
not safe for an automatic merge or a pricing cohort.

Final review artifact:
`.artifacts/semantic_discovery_without_oe_identifier_clean_replay_20260809`

Final replay SHA-256:
`e2d0564069474c1a89bb99110336e41dcf306cef2712f4d1627761652f418ea6`

## Safety/accounting result

Across the implemented pilot and final validated review:

- OE assertions created: **0**;
- identity records written: **0**;
- database writes: **0**;
- prices written: **0**;
- automatic pricing admissions: **0**;
- production parser/pricing code changed: **0 files**.

Raw HTML may naturally contain prices and identifiers because it is immutable
source evidence. It is stored separately and is not copied into the Luna text
snapshot.

## Verification

- Experiment/semantic/source-access/scrape-runtime/comparability tests:
  **799 passed**.
- Python compile checks: passed.
- Whole-catalog offline query planning: **1,617/1,617**, zero planning errors.
- Final Luna output revalidated against the exact stored snapshot and evidence
  catalog: passed.
- Four live HTTP body hashes and two image hashes: passed.

## Required next gate before scaling

Do not run all 1,617 rows and call the resulting count "coverage" yet. First
freeze a category-stratified sample (recommended starting point: 60–100 rows,
including the two untyped items), manually label retrieval candidates, and
measure:

1. at-least-one-correct-candidate retrieval recall per category;
2. deterministic rejection precision, especially critical false rejects;
3. Luna/manual-review false accepts and abstention rate;
4. usable candidate-image/detail-card availability (the KEMP seed image does
   not satisfy this metric);
5. independent-seller coverage;
6. runtime and physical HTTP/model-call budgets.

Any critical false accept keeps automatic identity and pricing admission at
zero. The likely production value of this path is broader candidate discovery
and operator triage, not automatic recovery of a missing OE number.
