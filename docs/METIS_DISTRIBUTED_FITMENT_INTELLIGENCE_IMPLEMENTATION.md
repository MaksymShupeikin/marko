# Metis Distributed Fitment Intelligence — implementation and operations contract

> Historical v1 document. The current v2 scoring, verified hard-rejection gate,
> source reliability and HITL pricing contract is documented in
> `METIS_HITL_COMPETITIVE_PRICING_IMPLEMENTATION_2026-07-21.md`.

Status date: 2026-07-21

Implementation contract: `metis-distributed-fitment-v1`

Scoring contract: `fitment-logit-v1`

Source policy: `fitment-source-policy-v1`

## 1. Result and boundary

The project now contains an evidence-first fitment subsystem that:

1. accepts a catalog part, persisted market candidates and provenance-bearing claims;
2. separates physical fitment from commercial price comparability;
3. rejects deterministic side, axle, category, generation, year and unresolved OE conflicts;
4. prevents own or related sellers from influencing the market envelope;
5. persists source policy, source documents, claims, decisions, cross references, human reviews and audit events;
6. executes analysis through an idempotent, leased Celery job and transactional outbox;
7. exposes workspace-scoped API and an operator-facing Flutter candidate/evidence panel;
8. produces advisory prices only. No implemented path publishes or automatically applies a marketplace price.

The existing Prom parser remains frozen. The new layer consumes persisted observations and evidence around that boundary; it is not a replacement scraper.

This implementation does **not** silently authorize PartSouq, 7zap, ZF, KYB, Bosch or any other external source. Source routing is a query-level plan. Actual evidence admission requires a registered, current access policy and immutable source document.

## 2. End-to-end data flow

```text
CatalogItem + normalized target identity
        |
        v
Persisted MarketObservation candidates
        |
        +--> SellerRelationRecord (own / related / independent / unknown)
        |
        +--> FitmentSource + FitmentSourceDocument
        |          |
        |          v
        +--> submitted EvidenceClaim[] with provenance
                   |
                   v
POST /api/v1/fitment/products/{catalog_item_id}/analyze
                   |
                   v
FitmentAnalysis(queued) + ScrapeDispatchOutbox (one transaction)
                   |
                   v
Celery task + lease + idempotent replay
                   |
                   v
CompatibilityAssessment (physical)
                   |
                   v
PriceComparabilityAssessment (commercial)
                   |
                   +--> FitmentCandidateAssessment
                   +--> FitmentEvidenceClaim
                   +--> FitmentAuditEvent
                   |
                   v
Flutter pricing card -> evidence expansion -> human review
                   |
                   v
append-only review/cross-reference evidence
```

Discovery is not confirmation. A title, photo, search query or Prom “similar products” block can create a candidate, but cannot by itself create authoritative fitment identity.

## 3. Identity and normalization invariants

Part numbers are normalized as strings:

```text
normalize(value) = NFKC(uppercase(value)) with non [0-9A-Z] removed
```

Leading zeroes are preserved. `001-AB` becomes `001AB`, never integer `1AB`.

The physical identity contract includes:

- category;
- axle;
- side and `side_specific` applicability;
- vehicle make/model;
- generation;
- year interval;
- engine;
- body;
- manufacturer article;
- zero or more OE numbers.

An identity confirmation requires at least one positive exact OE, supersession or confirmed-cross claim. Vehicle/title/photo similarity without one of these identifiers is capped at `uncertain`.

Hard rejections are non-overridable by accumulated positive soft evidence:

- `SIDE_MISMATCH` for side-specific parts;
- `AXLE_MISMATCH`;
- `PART_CATEGORY_MISMATCH`;
- `VEHICLE_MAKE_MISMATCH`;
- `VEHICLE_MODEL_MISMATCH`;
- `GENERATION_MISMATCH`;
- `YEAR_RANGE_DISJOINT`;
- `OE_IDENTITY_CONFLICT` when exact OE is disproved and no verified supersession/cross bridge exists.

## 4. Evidence model

Each `EvidenceClaim` stores:

- immutable evidence ID;
- feature and signed value from `{-1, -0.5, 0, 0.5, 1}`;
- source ID/type/tier;
- source URL and source-document SHA-256;
- source reliability;
- extraction confidence;
- independence and freshness factors;
- upstream correlation group;
- polarity;
- `FACT`, `INFERENCE`, `ASSUMPTION`, `UNKNOWN` or `CONFLICT` status;
- raw fragment and structured claim value;
- retrieval timestamp.

Effective claim weight is:

```text
e_i = reliability_i
    * extraction_confidence_i
    * independence_factor_i
    * freshness_factor_i
```

Repeated mirrors from one upstream correlation group have idempotent influence: positive and negative maxima are resolved once per group. Ten copied pages therefore cannot outvote one independent source ten times.

Zero/unknown evidence:

- contributes neither positive nor negative signal;
- does not increase coverage;
- cannot fill a critical field;
- cannot claim supportive or contradictory polarity.

Any explicit negative signal prevents `confirmed_compatible`; any source contradiction routes the candidate to manual handling.

### 4.1 Source tiers

New policies enforce the following reliability intervals:

| Tier | Intended evidence | Reliability interval |
|---|---|---:|
| A | official manufacturer/OEM authority | 0.95–1.00 |
| B | strong structured independent industry catalog | 0.75–0.90 |
| C | structured distributor/search corroboration | 0.55–0.75 |
| D | marketplace/replay/discovery evidence | 0.30–0.55 |
| E | weak or unverified discovery lead | 0.10–0.35 |

Authoritative identity confirmation requires either:

- one positive Tier A `FACT` identity group with effective weight at least `0.60`; or
- two independent positive Tier B `FACT` identity groups, each with effective weight at least `0.55`.

Two mirrors of the same catalog remain one group and do not satisfy the second rule.

## 5. Compatibility mathematics

Feature weights are versioned and sum exactly to one:

| Feature | Weight |
|---|---:|
| exact OE | 0.22 |
| supersession | 0.10 |
| confirmed cross | 0.16 |
| part category | 0.10 |
| axle | 0.08 |
| side | 0.08 |
| vehicle make/model | 0.08 |
| generation | 0.06 |
| year overlap | 0.04 |
| engine | 0.03 |
| body | 0.02 |
| technical specifications | 0.03 |

For feature consensus `s_j in [-1, 1]`:

```text
P = sum(w_j * max(s_j, 0))
N = sum(w_j * max(-s_j, 0))
C = sum(w_j where non-zero evidence is present)
D = sum(w_j where independent source groups contradict)
K = missing_critical_fields / applicable_critical_fields

z = -1.5 + 5P - 6N + 1.2C - 2D - 2.5K
p_fit = 1 / (1 + exp(-z))
```

Decision policy:

```text
hard rejection or p_fit < 0.40 -> not_compatible
no verified identifier             -> uncertain (maximum allowed state)
0.40 <= p_fit < 0.70               -> uncertain
0.70 <= p_fit < 0.90               -> likely_compatible
p_fit >= 0.90 + authority
  + no negative/conflicting facts  -> confirmed_compatible
otherwise                          -> likely_compatible + manual review
```

The decision persists probability, P/N/C/D/K components, reasons, missing fields, hard rejections, authority flag and exact evidence IDs.

## 6. Physical fitment versus price comparability

A physically fitting product is not automatically a valid price competitor. The commercial gate independently checks:

- fitment review state;
- seller ownership/relationship and stable seller identity;
- new/used/remanufactured condition;
- package quantity;
- unit basis;
- currency;
- brand/tier relation;
- availability;
- source quality and freshness.

Own and related sellers, incompatible condition/package/unit/currency and out-of-stock offers are `not_comparable`. Unknown seller identity, unknown unit/package/tier and a not-yet-reviewed likely fitment are `manual_review` and receive zero price weight.

For an eligible competitor:

```text
W_j = p_fit^2 * q_j * d_j * a_j * f_j * t_j * c_j
```

where:

- `q_j` — source quality;
- `d_j` — seller independence;
- `a_j` — availability;
- `f_j` — freshness;
- `t_j` — tier comparability;
- `c_j` — condition comparability.

Influence is capped by `brand_article_key` and seller group before calculating weighted q20/q25/q35/q50/q75/q80. At least three independent seller groups are required for a sufficient market envelope.

Price advice selects a strategy anchor, applies a bounded undercut, cost/margin floor when supplied, and maximum raise/lower limits. `requires_manual_approval` is invariantly `true`; no method in this subsystem writes marketplace price.

## 7. Persistence and migrations

Migration chain:

```text
20260719_0016
  -> 20260721_0017 distributed fitment evidence/review schema
  -> 20260721_0018 source-policy provenance and tier checks
  -> 20260721_0019 durable analysis queue and lease state
```

Tables:

- `fitment_sources` — versioned access and reliability policy;
- `fitment_source_documents` — immutable retrieval identity/hash/metadata;
- `seller_relation_records` — append-only seller relationship decisions;
- `fitment_analyses` — durable job and target snapshot;
- `fitment_candidate_assessments` — physical and commercial results;
- `fitment_evidence_claims` — persisted claim lineage;
- `fitment_human_reviews` — append-only reviewer labels;
- `fitment_cross_references` — confirmed/rejected article-OE relations;
- `fitment_audit_events` — actor/time/entity/payload audit trail.

All mutable business records are workspace-scoped. Cross-reference confirmation resolves persisted claim UUIDs server-side; it does not trust caller-supplied source or human-review counts.

## 8. Durable queue and idempotency

Admission transaction:

1. validate workspace, catalog item, pricing run, observations and source documents;
2. acquire a PostgreSQL transaction advisory lock over `(workspace_id, idempotency_key)`;
3. compare request SHA-256 with any existing job;
4. insert `FitmentAnalysis(queued)` and outbox event atomically;
5. commit;
6. publish the outbox event to Celery.

Same key and same hash returns the existing job. Same key and different hash returns `409 FitmentIdempotencyConflict`.

Worker contract:

- `acks_late=true`;
- reject on worker loss;
- 240-second soft and 300-second hard limit;
- maximum three Celery retries with bounded exponential delay;
- 300-second database lease;
- task owner ID and attempt counter persisted;
- completed jobs are replay-idempotent;
- a live lease prevents another task from concurrently executing the job;
- expired leases can be recovered;
- failures persist typed error context and an audit event.

State machine:

```text
queued -> running -> completed
                 -> partial
                 -> failed -> retry/running
```

## 9. API contract

All endpoints are under `/api/v1/fitment` and enforce current-workspace scope.

Read/operator endpoints:

- `GET /source-routing?brand=...`;
- `GET /products/{catalog_item_id}/candidates`;
- `GET /analysis-jobs/{analysis_id}`;
- `GET /analysis-jobs/{analysis_id}/metrics`;
- `POST /candidates/{assessment_id}/review`;
- `GET /cross-references/search`.

Admin mutation endpoints:

- `POST /sources`;
- `POST /sources/{source_id}/documents`;
- `POST /products/{catalog_item_id}/analyze` (`202 Accepted`);
- `POST /sellers/{seller_external_id}/mark-own`;
- `POST /sellers/{seller_external_id}/mark-related`;
- `POST /cross-references/confirm`;
- `POST /cross-references/reject`.

Candidate responses contain physical status/probability, evidence coverage, missing/conflicting features, seller relationship, tier, price eligibility/weight/reasons and expandable source evidence with provenance.

## 10. Flutter operator workflow

The pricing recommendation card now includes a fitment candidate panel. The operator can:

- see candidate title, seller, brand, current observed price and URL;
- inspect physical probability/status, side, axle, tier and seller relationship;
- see whether the offer is admitted to pricing and why;
- expand evidence and inspect feature, source tier, effective weight, polarity, raw fragment and source URL;
- submit `compatible`, `incompatible` or `needs review` feedback.

The panel does not expose a price-publication action.

## 11. Observability

Per-analysis metrics include:

- candidate collection coverage;
- completed and failed candidate counts;
- physical status and price-eligibility distributions;
- manual-review rate;
- source failure/conflict counts;
- average independent source groups;
- analysis duration;
- human acceptance rate;
- confusion matrix, precision, recall, false-positive and false-negative rates when human labels exist.

Metrics without a gold label or downstream business outcome are returned as explicit `null` with a reason. The service does not invent precision, recall, sales lift or margin impact.

Operational alerts should be attached to:

- analysis jobs remaining queued/running beyond lease SLA;
- repeated retry/failure rate;
- source policy/document rejection rate;
- sudden candidate-coverage drop;
- source conflict and manual-review spikes;
- own/related seller leakage attempts;
- evidence documents expiring without replacement.

## 12. Security and source-access controls

1. Every read and write is scoped to the authenticated workspace.
2. Source, analysis, seller-relation and cross-reference mutations require workspace admin.
3. Approved/owner-risk source access requires a non-empty access reference plus robots and terms review.
4. A source document URL and final redirect must remain under the registered source domain.
5. Unregistered marketplace/replay evidence is capped at Tier D, reliability `<= 0.55`, and inference status.
6. Unregistered external catalog evidence is rejected.
7. Source routing never grants access; it explicitly reports `automatic_access_authorized=false`.
8. Human review and cross decisions are append-only audit facts.

## 13. Verification corpus

The executable synthetic-adversarial dataset contains exactly 25 required case classes, including exact OE, cross, supersession, side/axle/category/generation conflicts, years/engine/body variants, seller networks, copied sources, condition, missing identity, contradictory claims, availability and currency.

Files:

- `backend/tests/fixtures/fitment_evaluation_dataset_v1.json`;
- `backend/tests/test_fitment_evaluation_dataset.py`;
- `backend/tests/test_fitment_intelligence.py`;
- `backend/tests/test_fitment_source_policy.py`;
- `backend/tests/test_fitment_api_contract.py`;
- `backend/tests/test_fitment_postgres.py`;
- `frontend/test/fitment_models_test.dart`;
- `frontend/test/fitment_api_test.dart`.

The dataset is explicitly marked `representative=false`. It proves deterministic contract behavior and catches regressions; it cannot establish production precision or coverage on Yuri's live catalog.

## 14. Deployment, rollback and recovery

Deployment order:

1. backup database and record current Alembic revision;
2. build backend/frontend images;
3. run migrations through `20260721_0019`;
4. start API and general Celery worker;
5. verify the task registry contains `marko.worker.process_fitment_analysis`;
6. start frontend;
7. run readiness and OpenAPI smoke tests;
8. submit one permitted retained-fixture analysis and verify queue -> completed -> UI review;
9. keep external source policies `NOT_PERMITTED`/`UNKNOWN` until separately approved.

Rollback:

- stop admission of new fitment analysis jobs;
- drain or revoke queued tasks;
- roll application images back first;
- preserve append-only evidence/audit rows;
- downgrade `0019 -> 0018` only after verifying no queued/running job needs the removed payload/lease columns;
- downgrade `0018 -> 0017` only if source policy hardening is deliberately removed;
- take a fresh backup before destructive schema downgrade.

Application rollback is preferred over data rollback because assessments and reviews are auditable historical facts.

## 15. Rollout gates

### Gate R0 — implementation

Required:

- migrations compile and apply on disposable PostgreSQL;
- unit, API, policy, queue and Flutter tests pass;
- OpenAPI exposes the fitment endpoints;
- no price publication path exists.

### Gate R1 — permission-safe shadow pilot

Required inputs:

- approved query-level access policies or immutable permitted captures;
- representative sample from Yuri's catalog;
- independent human labels for identity, side/axle, condition, package/unit, tier and price eligibility.

Required measurements must be computed separately for exact OE, supersession and cross paths:

```text
precision = TP / (TP + FP)
recall    = TP / (TP + FN)
FPR       = FP / (FP + TN)
coverage  = evaluated_candidates / discovered_candidates
abstain   = manual_or_uncertain / evaluated_candidates
```

No denominator may be replaced with zero or hidden. Undefined metrics remain null.

### Gate R2 — controlled operational pilot

Required:

- representative accuracy thresholds approved by product/domain owner;
- zero own/related seller leakage into eligible market envelope;
- zero unresolved hard-conflict admissions;
- queue throughput, p95 latency, retry amplification and drain capacity measured under production-like load;
- backup/restore and application rollback drill;
- operator review SLA and rejection-reason analysis.

### Gate R3 — broader use

Even after R2, recommendations remain human-approved. Automatic marketplace price publication is outside this contract and requires a separate design, authorization, safety analysis and release gate.

## 16. Known boundaries and next evidence

Current implementation evidence is engineering-level and non-representative. The following remain outside the implementation PASS claim:

- no external catalog adapter is automatically enabled;
- source availability, terms and retrieval stability are not inferred from a routing entry;
- no representative live Prom/Yuri precision-recall evaluation has been completed by this implementation stage;
- no sustained production-like load, backup/restore or rollback drill has yet been recorded for this subsystem;
- the supplied checkout has no Git metadata, so the result is path/hash-bound rather than commit-bound;
- the frozen Prom parser was not rewritten.

Therefore the fitment implementation gate may pass after local verification, while production activation remains blocked until R1/R2 evidence exists. These are intentionally separate statuses.
