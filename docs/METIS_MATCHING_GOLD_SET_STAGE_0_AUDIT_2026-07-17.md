# METIS MATCHING GOLD SET AND BENCHMARK — STAGE 0 REALITY AUDIT

Audit date: `2026-07-17`  
Project root: `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`  
Master prompt SHA-256: `815042ad2abd171dde0ddee3133bdbe45d73bdaf6e632ed1d3ae9014d042799c`  
Original Stage 0 source/config/test fingerprint (reported; input file manifest was not
retained): `7e94498116acc6766baab7f578e47cf211cc7d2707c627c08246dc5ec645bc39`  
Repository commit: `NOT_AVAILABLE` — the checkout contains no `.git` metadata.

## Executive decision

```text
STAGE_0_AUDIT = PASS
CURRENT_MATCHER_PRODUCTION_ELIGIBILITY = NO_GO
BENCHMARK_PRODUCTION_GATE = BLOCKED
GOLD_SET_ARTIFACT = NOT_FOUND_IN_AUDITED_CHECKOUT
BENCHMARK_ARTIFACT = NOT_FOUND_IN_AUDITED_CHECKOUT
MATCHER_CODE_CHANGED = NO
PRICING_ENGINE_CHANGED = NO
NEXT_STAGE_STARTED = NO
```

`PASS` applies only to the completeness of **Stage 0 — Matching Reality Audit**.
It does not assert matcher quality or production eligibility. The current implementation is
`NO_GO` as a production matching/comparability approach because exact identifiers bypass hard
conflicts and because the pricing path can produce an automatic price without structured OE,
fitment, side, quantity, or condition evidence. Separately, the benchmark production gate is
`BLOCKED`: precision/recall and release thresholds cannot be evaluated because the audited
checkout has no approved identity/comparability artifact, validated gold set, locked test
manifests, approved release-threshold artifact, or representative labeled sample.

The current matcher also has reproducible safety defects: exact `model_id` and exact `sku`
return a `1.0` match before brand and laterality checks. These defects are recorded, but were
not remediated because Stage 0 explicitly forbids changing matcher internals, pricing logic,
labels, or thresholds.

## Scope and evidence rules

This audit inspected the task-pinned active local checkout, models, migrations, API surface,
matching and pricing services, worker orchestration, tests, frontend, and source-access
boundary. It did not inspect a live database or queue, create labels, or infer production
quality from synthetic fixtures.

Physical-copy resolution:

- selected input/real path:
  `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`;
- selection basis: the active Codex workspace and this target report both explicitly pin that
  path; selection was not based on modification time, file count, or test success;
- other located copies:
  `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/metis_alpha`,
  `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/metis_alpha/marko`, and
  `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/metis_alpha/metis`;
- those other copies were not substituted for, or treated as evidence about, the selected
  checkout;
- remote, branch, and commit are `NOT_AVAILABLE` for the selected checkout because it contains
  no Git metadata. Historical lineage remains a blocker even though the review input identity
  is resolved.

Evidence labels used below:

- `REPOSITORY_FACT`: directly established from current code, schema, tests, or a reproducible
  read-only probe.
- `PAPER_FACT`: established by the cited primary publication.
- `ENGINEERING_ASSUMPTION`: a future additive integration boundary; not implemented.
- `BUSINESS_DECISION`: requires owner/domain approval and was not selected by the agent.
- `DATA_BLOCKER`: required labeled or production-like evidence does not exist locally.

`PAPER_FACT`: WDC Products evaluates entity matching along combinations of corner-case
amount, unseen-entity generalization, and development-set size. The paper does not establish
Metis automotive labels, thresholds, or production readiness. Primary source:
[Peeters, Der, and Bizer, WDC Products](https://arxiv.org/abs/2301.09521).

---

## A. Current matcher architecture

### A.1. Located implemented path (live source execution blocked)

```text
Catalog XLSX
  -> CatalogItem(oe_norm, sku, name, category, brand, product_url)
  -> PricingRun / ScrapeTarget
  -> Prom product page as seed
  -> Prom search(query = CatalogItem.oe_norm, max 3 pages)
  -> Product candidates in upstream search order
  -> match_offer(seed, candidate, threshold = 0.55)
       exact model_id -> Match("model", 1.0)
       exact sku      -> Match("sku", 1.0)
       else brand-compatible + no title laterality conflict + token score
  -> build_comparison
       removes seed and same seller
       keeps positive-price matches
       keeps cheapest offer per seller
       sorts by price and caps at 10 sellers
  -> application-updated ScrapeTarget payload / content-hashed RawMarketCapture reference
  -> MarketObservation(matched_oe_norm = catalog item OE,
                       match_confidence = heuristic score)
  -> ObservationTierClassification
  -> Metis pricing eligibility and tier normalization
  -> PricingRecommendation or pricing-level manual review
```

Evidence:

- `backend/src/marko/services/xlsx_catalog.py:55-150,459-517`
- `backend/src/marko/services/pricing_runs.py:216-367`
- `backend/src/marko/parsers/prom/gateway.py:119-199`
- `backend/src/marko/services/matching.py:21-114,225-257`
- `backend/src/marko/services/scraper_contract.py:79-176,199-317,445-475`
- `backend/src/marko/services/market_collection.py:1068-1285,1396-1525`
- `backend/src/metis/pricing/engine.py:48-113,360-388`

This is a located code path (`E2`) with deterministic local probes/tests (`E3`), not a verified
live production E2E path. Public Prom competitor collection is fail-closed under the current
`NOT_PERMITTED` source state.

### A.2. Candidate retrieval

`REPOSITORY_FACT`:

- The implemented pricing retrieval path, when source policy permits execution, uses Prom
  search with `search_term = oe_norm`.
- Retrieval scans at most `pricing_scraper_max_search_pages = 3` by default.
- The parser yields every product on each fetched search page; there is no internal learned
  ranker or explicit top-K retrieval contract.
- The persisted structured comparison contains only accepted matches and
  `candidates_scanned`. Rejected candidates and their retrieval ranks are not present in the
  structured output.
- Raw HTTP evidence is content-addressed and is a candidate input for future controlled replay,
  but exact retrieval reconstruction has not been validated and no matching benchmark adapter
  currently reconstructs retrieval sets from it.
- The final offer list is price-sorted and capped per seller; it is not a retrieval ranking.
- There is no verified set `G_s`, so `Recall@K`, zero-candidate true-miss rate, and retrieval
  false negatives are not measurable.

### A.3. Pairwise decision

`REPOSITORY_FACT`:

- `match_offer()` returns `Match | None`, not `same | different | manual_review_required`.
- `None` conflates a verified negative, insufficient evidence, a hard conflict, and a score
  below threshold.
- Exact `model_id` and `sku` equality take precedence over all later checks.
- Fuzzy matching uses an equal blend of token-set Jaccard and containment.
- Fuzzy matching requires equal/unknown brand and checks three title-token antonym groups:
  left/right, front/rear, and upper/lower.
- Missing brand is treated as compatible.
- A missing side/position marker is not a conflict.
- There are no structured engine, fitment, year, body variant, category, part type, package
  quantity, kit composition, dimensions, condition, or manufacturer-part conflict gates.
- `Product` does not expose OEM arrays, description, structured fitment, engine, side,
  position, condition, or package quantity.
- The configured fuzzy threshold is `0.55`; it is not backed by a gold-set evaluation.

### A.4. Pricing comparability

`REPOSITORY_FACT`:

- There is no separately persisted `comparability_label` or comparability decision service.
- Accepted pairwise matches are immediately materialized as market observations.
- `matched_oe_norm` is copied from the catalog query; it is not extracted and independently
  verified from the candidate offer.
- Downstream pricing hard-rejects non-positive price, currency mismatch, unavailable/stale
  offers, used/refurbished tier, owned seller, a tier conflict, low match confidence, unknown
  or low-confidence tier, and low source confidence.
- Default pricing `match_confidence_min` is `0.70`, so fuzzy matches in `[0.55, 0.70)` may be
  persisted and then excluded later.
- Exact identifier matches receive `1.0`; therefore they bypass the downstream low-match
  gate even when they contain brand or laterality conflicts.
- Condition detection is only best-effort text-based tier classification, not a complete
  identity/comparability contract.
- Pricing-level `MANUAL_REVIEW` and `INSUFFICIENT_DATA` are recommendation outcomes, not
  pairwise matching labels.
- A deterministic local probe supplied five fresh, independent, high-confidence KEMP offers to
  `recommend_price()` while the `Product` and `ProductPricingContext` contracts had no OE-array,
  fitment, vehicle, year, engine, side, position, condition, or package-quantity fields. The
  engine returned `RAISE`, `recommended_price = 920`, and `action_gates_passed = true`.
- `_currency_code(None)` returns `UAH`; therefore missing source currency is defaulted rather
  than represented as unknown before the pricing currency gate.

### A.5. Legacy relational matching surface

`REPOSITORY_FACT`:

- `product_matches` exists from the initial schema.
- It points to mutable `listings`, not immutable snapshots.
- It stores `candidate | approved | rejected`, `manual | automatic`, nullable confidence,
  and nullable `matcher_version`.
- It has no `uncertain`, comparability label, reason codes, annotation guideline version,
  annotator A/B records, adjudication, sampling probability, or label history.
- No current service, API route, worker, test, or frontend feature reads or writes
  `ProductMatch`; only the ORM model and migration reference it.
- The OpenAPI document has no path containing `match`, `annotation`, `gold`, or `benchmark`.

Evidence: `backend/src/marko/infrastructure/db/models.py:46-55,206-236` and
`backend/migrations/versions/20260713_0001_initial_schema.py:19-22,134-157`.

---

## B. Retrieval, decision, and comparability boundaries

| Layer | Current input | Current output | Boundary status | Main gap |
|---|---|---|---|---|
| Candidate retrieval | seed product URL + normalized OE query | streamed Prom `Product` records | Present but implicit | no relevant-candidate truth, rank persistence, or Recall@K |
| Pairwise entity decision | seed `Product`, candidate `Product`, threshold | `Match(kind, score)` or `None` | Present but binary/implicit | no `uncertain`, reasons, structured automotive gates, or versioned config |
| Pricing comparability | accepted match + tier/quality fields | offer admitted/excluded inside pricing engine | Mixed into pricing eligibility | no independent label, decision record, or benchmark metric |
| Manual review | pricing result | recommendation queue item | Present at pricing level | no blind pair annotation or adjudication workflow |

The architecture therefore does **not** satisfy the required three-way decomposition. It has
retrieval, heuristic filtering, and pricing eligibility steps, but no independent contracts or
evaluation records between them.

### B.1. Reproducible safety probes

The following probes called current `match_offer()` with threshold `0.55` through the active
checkout (`PYTHONPATH=src`):

| Probe | Safety expectation | Actual result | Status |
|---|---|---|---|
| same `model_id`; opposite left/right; Audi vs BMW | conflict must not auto-match | `Match(kind='model', score=1.0)` | CONFIRMED SYSTEM DEFECT |
| same `sku`; front/rear conflict; KEMP vs Other | conflict must not auto-match | `Match(kind='sku', score=1.0)` | CONFIRMED SYSTEM DEFECT |
| same fuzzy title core; left explicit on seed, side missing on candidate | observed behavior only; required label depends on approved domain semantics | `Match(kind='fuzzy', score=0.875)` | BLOCKED_PENDING_DOMAIN_DECISION |
| same fuzzy title core; explicit left/right conflict | reject | `None` | PASS FOR THIS FIXTURE |

Missing-data pricing probe:

| Cohort | Missing structured identity/comparability fields | Actual result | Status |
|---|---|---|---|
| five fresh independent KEMP offers | OE array, fitment, vehicle, years, engine, side, position, condition, package quantity | `RAISE`, price `920`, gates passed | NO_GO |
| one otherwise valid KEMP offer | same missing fields plus insufficient cohort | `INSUFFICIENT_DATA`, price `null` | fail-closed only on sample count |
| missing raw currency | currency absent before normalization | normalized to `UAH` | missingness is masked |
| five offers with `source = unknown`, confidence `1` | verifiable source provenance | `RAISE`, price `920`, gates passed | NO_GO |
| five offers with blank stable seller IDs but unique names | stable seller identity | `RAISE`, price `920`, gates passed | NO_GO |
| empty observation IDs | stable observation identity | `MANUAL_REVIEW`, price `null` | fail-closed invariant |
| unavailable, stale, unknown-tier, low-source-confidence, or severe-conflict cohorts | corresponding quality field | `INSUFFICIENT_DATA`, price `null` | fail-closed on implemented gates |

The exact-identifier probes and automatic-price probe establish deterministic system defects.
The missing-side fuzzy probe establishes current behavior only; without an approved domain
contract it is not classified as a confirmed false positive. None of the probes estimates
production prevalence or precision. Both complete probe runs produced byte-identical JSON.

---

## C. Existing test coverage

### C.1. What exists

`backend/tests/test_matching.py` contains 33 collected unit tests covering:

- token normalization;
- token similarity arithmetic;
- explicit opposite laterality/position title markers;
- brand compatibility;
- exact `model_id` and exact `sku` acceptance;
- fuzzy threshold acceptance/rejection;
- price parsing;
- own-seller exclusion;
- cheapest-per-seller selection;
- seller cap, sorting, and summary statistics;
- search-query construction.

Additional tests cover parser boundaries, stable scraper contracts, evidence persistence,
tenant authorization around existing APIs, pricing engine hard gates, tiering, replay, and
scraper scaling. A selected matching/gateway/pricing collection contains 95 tests; the
collected local backend suite contains 323 tests. These counts describe the audited checkout,
not a live E2E environment.

### C.2. What tests do not establish

- No manually verified pair labels are loaded by tests.
- No test samples random production candidates outside current retrieval.
- No candidate-retrieval recall is measured.
- No false-positive/false-negative corpus exists.
- No unseen entity split exists.
- No corner-case ratio or 27-variant cube exists.
- No confidence interval or cluster bootstrap is calculated.
- No annotation agreement or adjudication is tested.
- No matcher-version regression report is produced.
- Existing exact-ID tests explicitly expect acceptance even with an unrelated title; they do
  not exercise exact-ID plus hard-conflict rejection.
- Unit tests prove deterministic implementation behavior, not production precision.

### C.3. Verification executed during this audit

```text
Backend pytest:          323 passed in 1.98s
Ruff:                    PASS
Python compileall:       PASS
Alembic upgrade SQL:     PASS through head 20260716_0009
Alembic downgrade SQL:   PASS from 20260716_0009 to base
Flutter tests:           21 passed
Flutter analyze:         TOOLING_FAILURE (exit 255)
```

The isolated `flutter analyze --no-pub` run failed before producing code diagnostics because
the Dart analysis server parsed a truncated LSP JSON message and raised
`FormatException: Unexpected end of input`. This is a tooling issue, not evidence of either a
clean or defective Flutter source tree.

No live PostgreSQL/Redis/Celery integration was run: `docker`, `psql`, and `redis-cli` are not
installed in the audited environment. No matching dataset artifact was found in the active
checkout outside virtual-environment/cache paths; a live database was not inspected, so its
record count is unknown.

---

## D. Missing gold-set and benchmark infrastructure

| Required component | Current status | Evidence / consequence |
|---|---|---|
| Approved identity ontology | Missing | no `same/different/uncertain` contract |
| Approved comparability ontology | Missing | pricing eligibility is not a label contract |
| Versioned reason taxonomy | Missing | matcher returns only kind/score or `None` |
| Annotation guideline | Missing | no artifact or version field |
| Immutable gold pair schema | Missing | no gold tables/files; `ProductMatch` points to mutable listings |
| Dual annotation | Missing | no annotator A/B persistence |
| Adjudication | Missing | no workflow, records, or API |
| Label history | Missing | no append-only correction lineage |
| Sampling streams S1-S12 | Missing | no sampler or sampling manifest |
| Production-like sample | Missing | no labeled production data locally |
| Matcher-independent candidates | Missing | persisted structured output contains accepted matches only |
| Split generator | Missing | no train/dev/test manifests |
| Leakage validator | Missing | no offer/pair/entity/near-duplicate checks |
| 27 benchmark variants | Missing | no cube or insufficient-data statuses |
| Matcher adapter protocol | Missing | current matcher has no benchmark interface |
| Prediction journal | Missing | no immutable per-run predictions |
| Retrieval runner | Missing | no Recall@K or seed-level reports |
| Pairwise runner | Missing | no TP/FP/FN/TN over resolved labels |
| End-to-end runner | Missing | no comparability inclusion precision |
| Wilson/cluster-aware intervals | Missing | no matching metric implementation |
| Slice reports | Missing | no S01-S22 evaluation |
| Release policy | Missing locally | no approved threshold/decision artifact was found in the audited checkout; external decision state is unknown |
| Regression/CI gate | Missing | CI benchmark does not exist |
| Benchmark UI | Missing | frontend has pricing review only |

The existing `scripts/evaluate_scraper_benchmark.py` and
`backend/src/marko/services/scraper_benchmark.py` benchmark scraper capacity/reliability. They
are not entity-matching benchmark infrastructure and must not be repurposed semantically.

---

## E. Candidate integration points

The following are `ENGINEERING_ASSUMPTION` candidates for later stages. None was implemented
in Stage 0.

1. `StoreSyncProductSnapshot` may provide content-hashed, application-created owned/store
   payloads with timestamps. Database-level immutability is not proven.
2. `ScrapeTarget`, `ScrapeHttpRequest`, `ScrapeEvidenceBlob`, and `RawMarketCapture` may provide
   content-addressed/application-managed candidate-side evidence. Exact candidate replay and
   database-level immutability are not proven.
3. A future Metis-governed append-only gold schema should be separate from legacy
   `ProductMatch` and should reference content hashes/versioned snapshots, not current
   `Listing` rows.
4. A matcher adapter can wrap `match_offer()` without changing its internals and must freeze
   matcher name/version, threshold, stopword/normalization policy, and config hash.
5. Candidate retrieval evaluation must capture every retrieved candidate and rank before
   pairwise filtering and before price sorting/capping.
6. Identity and comparability decisions must be separate records; exact identity may not
   automatically set comparability.
7. Existing workspace authorization patterns can be reused, but benchmark pooling across
   workspaces requires explicit D19 approval.
8. Existing Celery/job patterns can host sampling and evaluation runs only after schemas and
   label semantics are approved.
9. Existing pricing recommendation review UI can inform interaction patterns, but matching
   annotation must be blind to matcher prediction, score, price recommendation, and the other
   annotator's label.
10. Pricing integration should remain fail-closed: no benchmark result should mutate historical
    recommendations, and no candidate should enter a pricing cohort solely from text similarity.

---

## F. Confirmed repository facts

- `RF-001`: the task-pinned active code is in nested `marko — копия`; the outer
  directory is a wrapper. Other located copies were not audited as substitutes.
- `RF-002`: the checkout has no `.git`, so a benchmark `code_commit` cannot currently be
  populated truthfully.
- `RF-003`: the deterministic pricing implementation is located in `metis.pricing`, while
  `marko.pricing` re-exports it and describes itself as a compatibility facade. Treating this
  as the ownership boundary is an engineering inference consistent with those artifacts.
- `RF-004`: the located collection code wraps the existing Prom parser and matcher through
  `FrozenPromScraperAdapter`; live public-source execution is blocked by source policy.
- `RF-005`: adapter and output schema are versioned, but matcher version and matcher config hash
  are absent from the comparison payload.
- `RF-006`: retrieval query is normalized catalog OE, but candidate records do not expose an OEM
  array and matching does not verify the queried OE.
- `RF-007`: exact `model_id`/`sku` bypass brand and laterality checks.
- `RF-008`: fuzzy matching checks only title tokens, brand compatibility, and three antonym
  groups.
- `RF-009`: `None` is the only negative/abstention output from pairwise matching.
- `RF-010`: accepted matches are directly materialized as market evidence.
- `RF-011`: pricing has quality/commercial hard rejections, but no independent comparability
  label or decision record.
- `RF-012`: legacy `ProductMatch` exists but is not connected to services, API, workers, tests,
  or UI.
- `RF-013`: capture primitives expose content hashes and application-level insertion/update
  paths; database-level immutability and gold-grade replay are not proven.
- `RF-014`: no compliant matching gold-set, annotation workflow, manifest, evaluation runner,
  slice report, or release-gate artifact was found in the audited checkout; live database state
  was not inspected.
- `RF-015`: live public Prom collection defaults to `NOT_PERMITTED` with no reference and is
  blocked fail-closed.
- `RF-016`: the collected backend tests and Flutter tests passed; Flutter static analysis did
  not complete, and the tests contain no production labels.
- `RF-017`: a deterministic E3 probe produced an automatic `RAISE` recommendation without
  structured automotive identity/comparability fields in either input contract.
- `RF-018`: missing raw currency is normalized to `UAH` by `_currency_code(None)`.

---

## G. Blockers

### BLK-MATCH-001 — identity-semantics approval artifact not found

- Type: `BUSINESS_DECISION`
- Owner: product owner + automotive domain reviewer
- Evidence: no approved D1/D3 artifact was found in the audited checkout; external approval
  state is unknown.
- Required resolution: define product entity and acceptable verified cross-reference evidence.
- Affected stage: Stage 1 and all later stages.

### BLK-MATCH-002 — comparability-semantics approval artifact not found

- Type: `BUSINESS_DECISION`
- Owner: pricing/product owner + automotive domain reviewer
- Evidence: no independent comparability contract; current eligibility is executable policy,
  not gold truth.
- Required resolution: approve D2 and critical conflict semantics.
- Affected stage: Stage 1 onward.

### BLK-MATCH-003 — annotation authority/budget artifact absent locally

- Type: `BUSINESS_DECISION`
- Owner: project owner
- Evidence: no D4-D8 approval artifact, named annotator/adjudicator, budget, or development-set
  sizes were found in the audited checkout; external decision state is unknown.
- Required resolution: name annotators/adjudicator, double-label scope, budget, and nested
  development sizes.
- Affected stage: Stages 1, 3, and 4.

### BLK-MATCH-004 — no labeled pair-data artifact found locally

- Type: `DATA_BLOCKER`
- Owner: data/annotation owner
- Evidence: no local gold/silver pairs, annotations, CSV, Parquet, or database fixture.
- Required resolution: create snapshots and a blinded pilot only after Stage 1 semantics pass.
- Affected stage: Stage 4 onward.

### BLK-MATCH-005 — production source unavailable by policy

- Type: external source-access blocker
- Owner: source/legal/business owner
- Evidence: default verdict `NOT_PERMITTED`, empty reference, fail-closed runtime gate.
- Required resolution: use permitted client-supplied/persisted evidence or record an auditable
  permitted source reference; do not bypass the gate.
- Affected stage: production-like sampling and future refreshes.

### BLK-MATCH-006 — matcher lineage incomplete

- Type: engineering blocker
- Owner: repository maintainer
- Evidence: no Git metadata; no matcher version/config hash in comparison output.
- Required resolution: restore immutable code lineage and design a matcher adapter/version
  contract in the permitted later stage.
- Affected stage: Stages 6-12.

### BLK-MATCH-007 — upstream fields and safety gates incomplete

- Type: reproducible engineering defect
- Owner: matching/domain engineering
- Evidence: exact-ID conflict probes auto-match; candidate `Product` lacks required structured
  automotive fields.
- Required resolution: after ontology approval, implement additive hard gates and abstention or
  explicitly constrain eligible scope. Do not silently reinterpret current scores.
- Affected stage: Stage 8 baseline and any production eligibility claim.

### BLK-MATCH-008 — release-threshold approval artifact not found

- Type: `BUSINESS_DECISION`
- Owner: product/risk owner
- Evidence: no approved D9-D18/D20 threshold artifact was found in the audited checkout;
  external decision state is unknown.
- Required resolution: approve confidence level, precision/recall lower bounds, minimum sample
  sizes, zero-tolerance slices, and review capacity before Stage 9/12.
- Affected stage: Stages 9-12.

### BLK-MATCH-009 — no live integration environment

- Type: environment blocker
- Owner: platform/deployment owner
- Evidence: Docker, PostgreSQL CLI, and Redis CLI are unavailable locally.
- Required resolution: provide a disposable Postgres/Redis/Celery environment for storage,
  concurrency, and tenant-isolation integration validation.
- Affected stage: Stage 2 onward.

### BLK-MATCH-010 — Flutter analyzer tooling failure

- Type: tooling blocker
- Owner: frontend/toolchain maintainer
- Evidence: repeatable analysis-server `FormatException` before diagnostics.
- Required resolution: repair/update the local Flutter/Dart analysis toolchain and rerun
  `flutter analyze`.
- Affected stage: future annotation UI validation; not a blocker to Stage 0 audit completion.

---

# STAGE RESULT

## 1. Stage

- stage_id: `0`
- stage_name: `MATCHING REALITY AUDIT`
- terminal_status: `PASS`

The audit objective is complete. This status does not override the separate
`CURRENT_MATCHER_PRODUCTION_ELIGIBILITY = NO_GO` or
`BENCHMARK_PRODUCTION_GATE = BLOCKED` results.

## 2. Structured result

- completed:
  - located active-checkout matching-path audit;
  - retrieval/decision/comparability boundary map;
  - persistence/API/test/versioning inventory;
  - deterministic conflict probes;
  - declared local regression/static commands attempted, with Flutter analyzer unresolved;
  - missing-infrastructure and blocker register.
- created:
  - this Stage 0 audit report only.
- changed:
  - documentation only.
- explicitly_not_changed:
  - matcher internals;
  - pricing engine and formula;
  - parser/gateway behavior;
  - threshold `0.55` or pricing policy thresholds;
  - ORM models and migrations;
  - API schemas/routes;
  - workers and queues;
  - production labels;
  - database state;
  - frontend behavior.
- repository_facts:
  - listed as `RF-001` through `RF-018`.
- engineering_assumptions:
  - additive candidate integration points are listed in Section E; none is implemented.
- business_decisions:
  - no approved `D1-D20` decision artifact was found in the audited checkout;
  - external decision state is `UNKNOWN`, not inferred as approved or rejected.
- data_blockers:
  - no gold/silver labels;
  - no production-like sample;
  - no annotation provenance;
  - no local live database/queue environment;
  - public source verdict is `NOT_PERMITTED`.

## 3. Gold-set status

- gold_set_version: `NOT_AVAILABLE`
- schema_version: `NOT_AVAILABLE`
- annotation_guideline_version: `NOT_AVAILABLE`
- total_pairs: `NOT_AVAILABLE`
- same: `NOT_AVAILABLE`
- different: `NOT_AVAILABLE`
- uncertain: `NOT_AVAILABLE`
- double_labeled: `NOT_AVAILABLE`
- disagreements: `NOT_AVAILABLE`
- adjudicated: `NOT_AVAILABLE`
- unique_entities: `NOT_AVAILABLE`
- unique_oe_families: `NOT_AVAILABLE`

No compliant local artifact is called `gold` or `silver_candidate_set`. Absence of an artifact
in the audited checkout does not establish that an uninspected live database contains zero
records; counts are therefore `NOT_AVAILABLE`, not fabricated zeroes.

## 4. Benchmark status

- manifest_id: `NOT_AVAILABLE`
- corner_case_level: `NOT_AVAILABLE`
- unseen_level: `NOT_AVAILABLE`
- development_size: `NOT_AVAILABLE`
- train_pairs: `NOT_AVAILABLE`
- dev_pairs: `NOT_AVAILABLE`
- test_pairs: `NOT_AVAILABLE`
- leakage_check: `NOT_AVAILABLE — no benchmark records or splits exist`
- reproducibility_check: `NOT_AVAILABLE — no benchmark manifest exists`

## 5. Metrics

- retrieval_recall_at_k:
  - value: `NOT_AVAILABLE`
  - reason: no verified relevant-candidate sets and no preserved candidate ranking.
- identity_precision:
  - value: `NOT_AVAILABLE`
  - reason: no resolved binary gold labels.
- identity_precision_lower_bound:
  - value: `NOT_AVAILABLE`
  - reason: no numerator, denominator, or approved confidence level.
- identity_recall:
  - value: `NOT_AVAILABLE`
  - reason: no resolved gold labels or retrieval truth.
- identity_recall_lower_bound:
  - value: `NOT_AVAILABLE`
  - reason: no numerator, denominator, or approved confidence level.
- comparability_inclusion_precision:
  - value: `NOT_AVAILABLE`
  - reason: no independent comparability labels.
- unseen_precision:
  - value: `NOT_AVAILABLE`
  - reason: no entity grouping policy or unseen split.
- automatic_coverage:
  - value: `NOT_AVAILABLE`
  - reason: current matcher has no pairwise abstention label and no benchmark denominator.
- manual_review_rate:
  - value: `NOT_AVAILABLE`
  - reason: pricing manual review is not pairwise matching review.
- critical_false_positive_count:
  - value: `NOT_AVAILABLE`
  - reason: three deterministic defect probes are not a locked representative test set.

## 6. Slice failures

No S01-S22 metric is reportable because no compliant gold-set artifact was found and no live
dataset was inspected. Marking a slice `100%`, `0%`, or `PASS` from unit fixtures would
fabricate evidence.

Known deterministic contract violations, pending gold-set prevalence measurement:

- slice_id: `S03/S09 exact_model_id_with_side_and_brand_conflict`
- n: `1 synthetic probe`
- metric: `auto-match safety behavior`
- expected: `reject or manual_review_required`
- actual: `Match(model, 1.0)`
- confidence_bound: `NOT_APPLICABLE`
- severity: `critical implementation defect; production prevalence unknown`

- slice_id: `S04 exact_sku_with_front_rear_conflict`
- n: `1 synthetic probe`
- metric: `auto-match safety behavior`
- expected: `reject or manual_review_required`
- actual: `Match(sku, 1.0)`
- confidence_bound: `NOT_APPLICABLE`
- severity: `critical implementation defect; production prevalence unknown`

- slice_id: `missing_side_marker`
- n: `1 synthetic probe`
- metric: `abstention behavior`
- expected: `NOT_APPROVED — requires domain decision on one-sided missingness`
- actual: `Match(fuzzy, 0.875)`
- confidence_bound: `NOT_APPLICABLE`
- severity: `observed behavior; classification blocked pending domain decision`

## 7. Validation and variation

- happy_path:
  - exact identifier, fuzzy identical title, compatible brand, per-seller deduplication, and
    pricing hard-gate unit tests pass.
- boundary_cases:
  - empty tokens, threshold boundary behavior, missing brand, missing price, and explicit
    laterality conflict have unit coverage.
- adversarial_cases:
  - exact-ID conflict bypass, missing-side fuzzy acceptance, and automatic pricing without
    structured comparability fields reproduced during audit;
  - two independent processes produced byte-identical probe JSON.
- leakage_tests:
  - `NOT_AVAILABLE`; no benchmark splits exist.
- variation_matrix:
  - current unit tests cover only a small subset; the master prompt's 25-dimension matrix is
    not implemented.
- reproducibility:
  - pure matcher probes repeat deterministically;
  - scraper payload hashing exists;
  - benchmark reproducibility is unavailable;
  - the original source fingerprint is recorded above, but its input file manifest was not
    retained and the value is therefore not independently reconstructible;
  - code commit unavailable.
- unresolved_defects:
  - exact identifier bypasses hard conflicts;
  - negative and uncertain collapse to `None`;
  - matcher version/config not frozen in output;
  - required automotive fields/gates absent;
  - automatic recommendation can be emitted without those fields;
  - missing raw currency is normalized to `UAH`;
  - Flutter analyzer tool failure.

## 8. Evidence

- files_inspected:
  - master prompt (all 2644 lines);
  - `backend/src/marko/services/matching.py`;
  - `backend/src/marko/parsers/prom/{config,gateway,parser}.py`;
  - `backend/src/marko/services/{parser_models,scraper_contract,market_collection,pricing_runs,source_access}.py`;
  - `backend/src/metis/pricing/{engine,types,tiering}.py`;
  - `backend/src/marko/infrastructure/db/models.py`;
  - all migration versions through `20260716_0009`;
  - pricing/catalog/API schemas and routes;
  - backend and frontend matching/pricing tests;
  - frontend pricing/manual-review surfaces;
  - project configuration, docs, and scripts.
- files_changed:
  - `docs/METIS_MATCHING_GOLD_SET_STAGE_0_AUDIT_2026-07-17.md`
- tests_executed:
  - `PYTHONPATH=src .venv/bin/python -m pytest -q` → 323 passed;
  - `/opt/anaconda3/bin/ruff check backend/src backend/tests scripts` → PASS;
  - `python -m compileall -q src tests` → PASS;
  - Alembic offline upgrade/downgrade → PASS;
  - `flutter test` → 21 passed;
  - isolated `flutter analyze --no-pub` → tooling exit 255 before diagnostics;
  - deterministic matcher/OpenAPI/model/source-access probes → results recorded above.
  - two independent matching/missing-data pricing probe processes → byte-identical results;
    exact conflicts matched, missing-side fuzzy score `0.875`, automatic `RAISE` price `920`,
    one-offer result `INSUFFICIENT_DATA` with `null` price, missing currency → `UAH`.
- reports:
  - this file.
- manifests:
  - `NOT_AVAILABLE`.
- hashes:
  - master prompt: `815042ad2abd171dde0ddee3133bdbe45d73bdaf6e632ed1d3ae9014d042799c`;
  - original audit-reported source/config/test fingerprint (non-replayable without its missing
    file-set manifest):
    `7e94498116acc6766baab7f578e47cf211cc7d2707c627c08246dc5ec645bc39`;
  - report hash: computed externally after the final write and reported in the handoff.

## 9. Blockers

See `BLK-MATCH-001` through `BLK-MATCH-010` in Section G. Hard prerequisites for the next
stage are:

- a named product/domain owner with authority to approve semantics;
- explicit decisions for D1-D6 at minimum;
- direct authorization to begin Stage 1.

## 10. Forbidden claims

Current evidence does not permit claiming that:

- the matcher is accurate, safe, or production-ready;
- exact OE, `model_id`, or SKU proves automotive identity or commercial comparability;
- observed query results contain the queried OE;
- pricing recommendation manual review is matching abstention;
- `ProductMatch.approved` is a gold label;
- current unit tests estimate precision, recall, or unseen generalization;
- the three probes estimate production error prevalence;
- a gold or silver candidate set exists;
- any 27 benchmark variant exists or passes;
- any production precision threshold is met;
- public competitor collection is permitted;
- benchmark PASS would imply pricing-engine production readiness.

## 11. Next permitted stage

- next_stage: `STAGE 1 — LABEL ONTOLOGY AND DOMAIN CONTRACT`
- prerequisites:
  - direct new user authorization;
  - D1: approved product-entity definition;
  - D2: approved pricing-comparability definition;
  - D3: policy for verified cross-reference evidence;
  - D4: primary annotator role;
  - D5: adjudicator role;
  - D6: double-annotation scope;
  - named owner/domain reviewer with approval authority.
- direct_user_authorization_required: `true`

Stage 1 may create ADR/guideline artifacts only after those semantics are supplied or approved.
It must not silently invent them.

## 12. Stop confirmation

The agent stopped after the Stage 0 stop-gate. Stage 1 was not started. Matcher, parser,
pricing engine, thresholds, ORM schema, migrations, API, labels, and runtime behavior were not
changed.
