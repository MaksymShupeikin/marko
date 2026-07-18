# Scraper Architecture Audit and Implementation — 2026-07-17

Execution target: `SCRAPER_ARCHITECTURE_AUDIT_AND_SCALING_REVIEW`  
Source prompt revision: `2.0`  
Selected root: `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`

## 1. Executive technical conclusion

The existing Prom extraction component remains the canonical black-box parser. Its selector and
extraction logic were not redesigned. The project now has implemented, versioned contracts for
trusted admission, four idempotency namespaces, multi-axis results, typed errors, bounded fetch
security, full-jitter HTTP retry, explicit fencing generations, durable dispatch outbox recovery,
hash-verified raw evidence manifests, Metis lineage, and outbox observability.

The implementation stage is successful at focused executable evidence level `E3`. Scraper scaling
and production eligibility remain `BLOCKED`, not `PASS`: the configured public Prom source state is
`NOT_PERMITTED`, no approved workload/SLO exists, and no representative PostgreSQL/Redis/Celery
load or recovery run has been supplied. Unit-test runtime is not used as a capacity measurement.

## 2. Repository identity and audit scope

| Field | Result |
|---|---|
| Selected Marko root | nested `marko — копия` root selected by active workspace and `AGENTS.md` |
| Metis root | `backend/src/metis` inside the selected root |
| Git identity | unavailable; no `.git` metadata in selected or outer root |
| Replacement identity | sorted 137-file path/size/SHA-256 manifest, excluding the two self-referential audit artifacts |
| Manifest SHA-256 | `97aa36f1f4c85599571d180e4e5ce1bf991f2fdf478019c1276e846ffc0a543a` |
| Audit mode | implementation explicitly authorized by user; parser black-box restriction retained |
| Live source execution | not performed because fail-closed source state is `NOT_PERMITTED` |

Git commit, branch, tracked diff, and pre-existing dirty state are `UNKNOWN`, not silently mapped to
clean. The selected physical root is nevertheless verified by absolute path, instructions, file
manifest, component hashes, and executable tests.

## 3. Duplicate-root divergence and component identity matrix

Two physical Marko parser trees exist:

| Candidate | Tree hash | Status | Use |
|---|---|---|---|
| selected `SaaS/marko/marko — копия/.../parsers/prom` | `361447bc…08f544` | `CANONICAL_EXTRACTION` | implementation and evidence source |
| sibling `SaaS/metis_alpha/marko/.../parsers/prom` | `d0a623a7…833651` | `DUPLICATE_DIVERGED` | cross-copy reference only |

The extraction parser file itself has the same SHA-256 in both trees
(`1856f717…7b66`), while the fetch client trees differ. No runtime/test evidence from the sibling
copy is borrowed into the selected root.

| Component ID | Path | Role | Canonical status |
|---|---|---|---|
| `marko-prom-extraction` | `backend/src/marko/parsers/prom` | existing fetch/parser/gateway | `CANONICAL_EXTRACTION` |
| `marko-metis-evidence-adapter` | `services/market_collection.py` + `scrape_journal.py` | immutable evidence and observation mapping | `CANONICAL_EVIDENCE_ADAPTER` |
| `marko-outbox-orchestration` | `services/scraper_outbox.py` + Celery tasks | DB-to-broker recovery | `REUSED_ORCHESTRATION` |
| sibling Metis collector | `metis_alpha/metis/metis/collect/prom.py` | different physical tree | `DUPLICATE_DIVERGED` |

## 4. Existing scraper/parser/evidence/orchestration map

| Component | Type | State | Runtime evidence | Risk |
|---|---|---|---|---|
| `PromGateway` | scraper entrypoint | implemented | focused smoke/boundary tests | real source not authorized |
| `FrozenPromScraperAdapter` | black-box wrapper | implemented | deterministic serialization tests | no E5 traffic |
| `ScrapeExecutionTrace` | HTTP journal boundary | implemented | replay/attempt tests | process-local trace context |
| `ScrapeEvidenceBlob` | raw storage | implemented | hash/decompression checks | PostgreSQL storage scale unknown |
| `ScrapeTarget` / `ScrapeAttempt` | job/attempt state | implemented | focused fencing tests | migration integration pending |
| `ScrapeDispatchOutbox` | durable dispatch | implemented | publish/failure/lease tests | multi-host integration pending |
| `DistributedCollectionGuard` | global source limiter | implemented | Redis behaviour tests | real Redis failover unknown |
| `market_collection` | Metis adapter | implemented | focused evidence/recommendation tests | lane integration partial |
| scraper metrics endpoints | observability | implemented/partial | renderer and math tests | alert delivery unverified |
| frontend batch/operator flow | UI | reference only | no new integration evidence | multi-axis state not yet exposed end-to-end |

## 5. Current execution trace and transaction/ack boundaries

```text
authenticated API request
-> trusted server source gate
-> canonical URL/query and server idempotency namespaces
-> domain job + ScrapeDispatchOutbox in one DB transaction
-> deterministic Celery task id
-> immediate publish or periodic outbox reconciliation
-> late-ack Celery worker
-> row lock + monotonic fencing token + lease
-> Redis-wide source slot/circuit gate
-> frozen Prom fetch/parser boundary
-> content-addressed compressed raw HTTP blobs
-> deterministic structured output
-> hash-verified raw evidence manifest
-> Metis RawMarketCapture -> MarketObservation -> classification
-> recommendation evidence/abstention gates
-> durable terminal/retry state
-> task return and broker acknowledgement
```

Implemented recovery windows:

- DB commit before broker publish: pending outbox row survives and is reconciled.
- Publish before outbox state update: expired dispatch lease republishes the same task ID.
- Broker redelivery: target/item effects are idempotent and fenced.
- Raw capture before crash: content-addressed evidence survives and replay avoids refetch.
- Stale worker after lease takeover: target/store fencing token rejects the write.

The remaining `PARTIAL` claim is operational: these paths are focused-tested but not demonstrated
against a real multi-host broker/database topology.

## 6. Logical item/request/attempt ontology

The implementation and metrics keep distinct units:

```text
N_item     = admitted store_sync or comparison_job logical items
N_req      = logical HTTP requests within an item
N_attempt  = physical network attempts
N_task     = Celery executions/redeliveries
N_capture  = immutable response blobs/references
N_terminal = unique logical items with explicit terminal outcome
```

Retry ratios are computed directly:

```text
A_http  = N_attempt / N_req
A_task  = N_task / N_item
A_total = N_attempt / N_item
```

Terminal item throughput is never divided by retry amplification again. Store sync, comparison
job, replay, and other future item kinds must remain separate cohorts.

## 7. Input/admission/security contract

Implemented in `scraper_architecture.py` and `scraper_contract.py`:

- strict `scrape-request.v2` schema with bounded item count, metadata, priority, query, and IDs;
- `extra="forbid"`: a client cannot supply `source_policy_state`, canonical input, tenant authority,
  or server idempotency keys;
- trusted `prom_public` admission derives policy state from server settings and auditable reference;
- Prom-only URL/path canonicalization and query normalization;
- embedded URL credentials rejected;
- redirects fail closed instead of following an unvalidated host;
- streamed responses enforce content type, declared/decoded byte limit, and compression ratio;
- timeouts, retry count, Retry-After cap, source circuit, and global rate control are bounded;
- tenant/workspace authorization remains at API and read boundaries.

Arbitrary URL fetching was not introduced. DNS rebinding is avoided for this path by accepting only
the canonical Prom host and refusing redirects; any future multi-host redirect support requires a
new per-hop admission contract.

## 8. Output and multi-axis status contract

`scrape-result.v2` independently records:

```text
execution_status
acquisition_status
parse_status
evidence_status
downstream_eligibility
operator_action
```

Hard validation rejects:

- acquisition success without raw capture ID and SHA-256;
- structured/ingested evidence without immutable raw identity;
- partial/failed parse marked downstream eligible;
- eligible output without ingested evidence and valid offers;
- offer evidence pointing at another raw capture;
- price amount without currency or a non-canonical/non-positive decimal string;
- successful execution without a winning attempt.

Legacy target state remains for compatibility, but worker transitions now update the v2 axes in the
same transaction. Metis ingestion changes `STRUCTURED_AVAILABLE` to `INGESTED`; it does not mark a
recommendation eligible by itself.

## 9. Runtime/evidence readiness table and critical floor

| Domain | Evidence | Conservative readiness | Production implication |
|---|---:|---:|---|
| input/admission contract | E3 | 75 | focused verified, no production traffic |
| fetch/raw capture/replay | E3 | 70 | integrity proven on fixtures |
| retry/idempotency/fencing | E3 | 65 | real multi-host contention absent |
| dispatch/outbox/ack | E3 | 60 | migration/broker integration required |
| observability/reconciliation | E3 | 60 | alert delivery and real lag absent |
| Metis evidence adapter | E3 | 55 | focused lineage, lane integration partial |
| security/tenant scope | E3 | 50 | route-level evidence, full integration pending |
| representative load | E0 | 0 | hard scaling blocker |

Declared capability weights sum to `1.00`; weighted lower-bound readiness is `59.75`, capped below
the E3 ceiling of `75`. The production-critical floor is `0` because representative load is E0.
The weighted average cannot override this floor.

## 10. Capacity, bottleneck and queueing model

The executable math layer distinguishes baseline, observed, and derived throughput:

```text
C_worker_derived = c * eta(c) * mu_attempt_1 / A_total
C_worker_observed = c * mu_terminal_c
C_source = R_source / A_total
C_db = R_db / writes_per_item
C_terminal = min(C_worker, C_source, C_db, C_queue)
C_success = C_terminal * p_success
```

`eta(c)` is not applied to a rate already observed at concurrency `c`; terminal throughput is not
divided by retry amplification. Continuous stability requires every required capacity and every
per-bottleneck `rho < 1`. `rho_system <= 0.70` is recorded only as an unapproved engineering
assumption.

The executable layer also returns Wilson confidence intervals for binary success/error rates and
a weighted completeness distribution (`minimum`, `p05`, `p50`, `p95`, critical-field missing
rate, per-field missing rate). Empty cohorts remain explicit `null`/unknown observations.

```text
T_drain_closed = B / C_terminal
T_drain_open   = B / (C_terminal - lambda_item), only if C_terminal > lambda_item
```

All current capacity fields are intentionally `null`: no approved cohort/environment exists. This
prevents a false scaling PASS from fast unit-test execution.

## 11. Retry/deadline/idempotency/outbox/fencing design

Implemented controls:

- separate HTTP-attempt and task-execution budgets;
- capped full-jitter exponential HTTP and outbox retry;
- bounded numeric `Retry-After` handling;
- item deadlines retained independently from broker redelivery count;
- `submission_key`, `acquisition_key`, `parse_key`, and `observation_key` namespaces;
- payload mismatch under one outbox event key raises `OutboxConflict`;
- at-least-once semantics are explicit; exactly-once is not claimed;
- deterministic Celery task ID survives ambiguous publish outcome;
- outbox claim lease and retry budget;
- target and store-sync monotonic fencing tokens persisted on each owning execution;
- late acknowledgements and reject-on-worker-loss remain enabled.

DLQ/operator replay is still a P1 gap. Terminal immutable history is preserved; remediation must
create a new generation rather than rewrite failure in place.

## 12. Storage, integrity, replay and reconciliation architecture

Raw HTTP bodies are compressed, content-addressed, and verified on persistence and replay. A new
Metis capture contains an ordered manifest of logical request ID, request key/kind, execution,
evidence blob ID, raw SHA-256, raw bytes, and stored bytes. The manifest itself is SHA-256 hashed and
is stored with parser name/version/config hash, output schema, source-policy decision, and lane.

Replay verifies decompression, size, and SHA-256 before returning a response. Structured output is
canonical JSON with its own hash and is not allowed to substitute for raw response identity.

Reconciliation formulas and endpoints exist, but no representative closed cohort was executed in
this run. Therefore `N_loss` is `null`, not invented as zero. Production acceptance requires:

```text
N_submitted = N_deduplicated + N_rejected + N_admitted
N_admitted = N_queued + N_running + N_retry_wait + N_success + N_failed + N_cancelled
N_loss = 0
```

## 13. Parallel-safety and failure-recovery assessment

Focused tests cover single delivery, broker failure, expired dispatch lease, deterministic task ID,
generation takeover, raw replay, duplicate inputs, bounded HTTP attempts, and output hash checks.
Per-extraction gateway/session construction avoids shared parser state. Redis provides a global
source start-rate budget rather than a per-worker limiter.

Still required in Phase 9:

- two API processes racing on the same idempotency token against PostgreSQL;
- multiple worker hosts sharing Redis limiter and circuit state;
- actual worker loss after raw persistence and before terminal commit;
- stale worker continuing after lease expiry;
- concurrent outbox reconcilers with `FOR UPDATE` contention;
- cancellation during fetch/storage/evidence ingestion;
- soak test for connection, memory, file-descriptor, and backlog leakage.

## 14. Observability, SLI/SLO and cardinality contract

The existing metrics expose item lifecycle, direct retry amplification, empirical p50/p95/p99,
queue depth/age, worker occupancy, raw/structured/journal storage, evidence coverage, CPU/RSS,
database probe, and compatibility metrics. Added outbox metrics:

```text
scrape_outbox_pending
scrape_outbox_dispatching
scrape_outbox_terminal_failed
scrape_outbox_oldest_pending_age_seconds
```

Metric labels remain bounded; URLs, queries, product IDs, user IDs, and exception text are not
labels. Dashboard/alert definitions remain only operationally `PARTIAL` until data paths and alert
delivery are exercised. Client-approved SLO targets and error budgets are absent.

## 15. Metis evidence adapter and source-lane integration

The implemented adapter preserves this chain:

```text
request -> target -> attempt -> raw HTTP evidence manifest -> structured output
-> RawMarketCapture -> MarketObservation -> tier classification
-> comparable cohort -> recommendation evidence or abstention
```

Scraper output cannot directly set a recommendation. Missing, invalid, partial, owned-seller, weak
match, insufficient cohort, or failed evidence gates yield manual review/no recommendation.

Lane status:

- `PUBLIC_COMPETITOR`: trusted contract implemented but live execution blocked by source policy.
- `REPLAY`: focused verified and permitted without new network traffic.
- `OWNED_STOREFRONT`: partial; current public catalog sync is not falsely relabelled as an official
  seller-cabinet API. Official API/export credentials and semantics require a client decision.

## 16. Marko reuse/adaptation map

| Marko component | Classification | Adaptation/invariant |
|---|---|---|
| authenticated workspace API reads | `REUSABLE_AS_IS` | preserve tenant filters |
| late-ack Celery config | `REUSABLE_AS_IS` | keep idempotent effects/fencing |
| direct task dispatch | `ADAPT_BEFORE_REUSE` | now routed through outbox |
| listing sync | `ADAPT_BEFORE_REUSE` | listing cache never replaces evidence truth |
| frontend sync status | `REFERENCE_ONLY` | must expose parse/evidence/review axes |
| mutable `Listing.raw_data` | `DO_NOT_PORT` | not immutable/replayable evidence |
| sync success as recommendation readiness | `DO_NOT_PORT` | violates Metis hard gates |

## 17. Failure-mode, hard-gate and RPN table

| Failure mode | S/O/D | RPN | Hard gate | Current mitigation | Residual status |
|---|---:|---:|---|---|---|
| DB commit, no task publish | 5/3/3 | 45 | yes | transactional outbox + reconciler | E3, integration pending |
| publish succeeded, state not updated | 4/3/3 | 36 | yes | deterministic task ID + lease recovery | E3 |
| stale worker overwrites new owner | 5/3/3 | 45 | yes | monotonic fencing token | E3 |
| structured observation loses raw lineage | 5/2/3 | 30 | yes | verified raw manifest in capture | E3 |
| client forges source policy | 5/2/2 | 20 | yes | strict request excludes authority fields | E3 |
| redirect reaches private host | 5/2/3 | 30 | yes | redirects rejected fail-closed | E3 |
| decompression/size memory exhaustion | 5/2/3 | 30 | yes | streamed byte/type/ratio limits | E3 |
| per-worker rate limits exceed source budget | 4/3/3 | 36 | yes | Redis-wide limiter | E3, multi-host pending |
| owned data enters competitor cohort | 5/3/4 | 60 | yes | owned registry gate; lanes still partial | P1 |
| retry storm/backlog runaway | 4/3/3 | 36 | no | jitter, deadlines, circuit, outbox age | load blocked |
| partial data creates recommendation | 5/2/2 | 20 | yes | multi-axis contract + Metis abstention | E3 |
| high average hides p99 failure | 4/3/3 | 36 | no | empirical percentiles/critical floor | SLO absent |

Hard-invariant failures remain P0/P1 regardless of a modest numeric RPN.

## 18. Architecture options, uncertainty and sensitivity analysis

Hard-gate eligibility is evaluated before utility score.

| Option | Hard-gate status | Utility interval | Result |
|---|---|---:|---|
| A — thin wrapper only | `NO_GO` in unaugmented form | `[45, 63]` | cannot prove dispatch/fencing/global recovery |
| B — batch queue/worker subsystem | eligible design | `[67, 82]` | strong scale path, larger duplicate domain surface |
| C — separate acquisition service | eligible design | `[59, 80]` | clean boundary but premature distributed complexity |
| D — Marko shell + canonical Metis adapter | eligible and partially implemented | `[72, 86]` | selected incremental target |

Weights follow the prompt and sum to `1.00`. Varying each non-hard weight by ±20% with
renormalization keeps D ahead in the central assumptions; B can tie/lead only when independent
scalability is weighted materially above migration reversibility and Marko reuse. That uncertainty
is not a reason to create a new service before the approved workload demonstrates the need.

## 19. Recommended target architecture

Selected: **Option D — canonical adapter over Marko orchestration and Metis evidence**.

Why:

- preserves the existing extraction component and minimizes parser regression risk;
- makes Marko the authenticated job/operator shell without making listings pricing truth;
- keeps immutable raw/evidence/classification/recommendation authority in Metis;
- provides transactional outbox, at-least-once idempotency, fencing, replay, and metrics now;
- permits a reversible strangler move to Option C only after measured independent-scaling need.

Confidence is `MEDIUM`, bounded by E3 evidence. Non-reversible decisions such as broker topology,
object storage, public-source authorization, and service separation are deferred.

## 20. Dependency-based development roadmap

| Phase | State | Exit evidence / stop gate |
|---|---|---|
| 0 audit/baseline | completed | identity, map, focused baseline |
| 1 canonical root/ownership ADR | completed for selected workspace | duplicate isolated; no evidence mixing |
| 2 versioned boundaries/replay | implemented E3 | strict contracts and replay tests |
| 3 raw/structured integrity/lineage | implemented E3 | content hashes and raw manifest |
| 4 admission/job/idempotency/outbox | implemented E3 | trusted admission + durable outbox |
| 5 worker/retry/deadline/fencing/DLQ | partial | retry/fencing done; DLQ/operator flow pending |
| 6 observability/reconciliation/dashboard | partial | metrics done; dashboard/alerts operational proof pending |
| 7 canonical Metis adapter | implemented E3 | observation lineage and abstention tests |
| 8 Marko UI/API adaptation | pending | multi-axis operator UX decision |
| 9 concurrency/load/failure validation | blocked | workload/SLO/env/source-emulator inputs required |
| 10 controlled shadow rollout | not started | direct instruction plus Phase 9 PASS required |

No automatic phase transition is authorized by this report.

## 21. Client decisions required

1. Public competitor source verdict and auditable authorization/reference.
2. First item kind to scale and average/peak/burst/max batch envelope.
3. Latency, freshness, success, manual-review, confidence, and evidence SLOs.
4. Raw retention, compression, backup/restore, deletion, and legal-hold classes.
5. Queue/broker/database/worker deployment topology and global source budget.
6. Official owned-store API/export lane versus separate public collection.
7. Marko operator UI scope, DLQ replay roles, force-refresh roles, and review approval roles.
8. Shadow/operator-assisted/automated read-only rollout mode.

## 22. Blockers, unknowns and contract conflicts

P0 blockers:

- `P0-SOURCE-AUTHORIZATION` — public live collection is fail-closed.
- `P0-MIGRATION-INTEGRATION` — migration `20260717_0010` needs isolated PostgreSQL validation.
- `P0-REPRESENTATIVE-LOAD-ENVELOPE` — no target workload/SLO/capacity environment.

Contract conflicts:

- The attached prompt calls itself `PROMPT_15_013`, while this repository already assigns
  `PROMPT_15_013` to the Section 16 machine-readable summary. The implementation uses descriptive
  scraper filenames and records the conflict instead of overwriting the normative Section 16 file.
- The prompt defaults to read-only audit, but explicitly permits implementation upon direct user
  instruction. The user's direct request authorizes implementation; automatic next-stage/live
  rollout remains forbidden.

## 23. Validation, hostile review and variation results

Executed validators/tests cover strict YAML duplicate rejection and round-trip, evidence ceiling,
gate consistency, request-policy forgery, URL credentials, redirect refusal, response byte limit,
Retry-After cap, idempotency namespace separation, multi-axis abstention, money serialization,
outbox publish/failure/lease recovery, explicit fencing takeover, HTTP retry/replay, capacity math,
Wilson confidence bounds, weighted completeness, cohort reconciliation, Prometheus output, and
black-box gateway behaviour.

Mental variations V1–V33 were rechecked against implementation and gaps. Variations requiring
real concurrency/load/source behaviour are not reported as runtime PASS; they map to Phase 9 and
the scaling `BLOCKED` gate. Hostile review answers:

- measured numbers are reproducible from commands/artifact hashes;
- item/request/attempt units remain separated;
- retries are counted once;
- stale/redelivered effects are fenced/idempotent in focused evidence;
- outbox closes the DB-to-broker silent-loss window by design and test;
- every new Metis observation capture retains a raw evidence manifest;
- source policy is server-owned;
- cross-copy evidence is isolated;
- audit PASS is explicitly separate from production;
- missing data cannot produce automated recommendation.

## 24. Audit/scaling/production stop-gates

```text
STAGE_RESULT:
- stage: SCRAPER_ARCHITECTURE_AUDIT_AND_SCALING_REVIEW
- status: PASS
- completed_scope: audit, contracts, P0 boundary/outbox/fencing/lineage implementation, focused validation
- strongest_verified_result: deterministic outbox recovery plus immutable raw-to-Metis lineage at E3
- weakest_critical_area: representative load and operational recovery at E0
- evidence_quality: E3 focused executable evidence
- production_implication: production remains blocked; audit/implementation success is not production approval

BLOCKERS:
- P0: SOURCE_AUTHORIZATION; MIGRATION_INTEGRATION; REPRESENTATIVE_LOAD_ENVELOPE
- P1: DLQ_OPERATOR_REPLAY; MULTI_HOST_RECOVERY; TENANT_INTEGRATION; PER_LANE_SLI
- business_decisions: workload, SLO, retention, deployment, lane, operator authority
- source_access: prom_public_marketplace=NOT_PERMITTED
- data: no approved representative replay/load corpus
- environment_reproducibility: no Git metadata and no production-like PostgreSQL/Redis/Celery run
- unknowns: capacity, tail latency, error bounds, storage growth, alert delivery

NEXT_STAGE:
- id: SCRAPER_PHASE_9_INTEGRATION_AND_LOAD_VALIDATION
- title: PostgreSQL/Redis/Celery migration, recovery, concurrency, and replay load validation
- why_it_is_next: it is the first stage that can raise queue/recovery/load evidence above E3
- required_inputs: workload/SLO, isolated environment, replay corpus, lane/retention decisions
- expected_artifacts: L0-L7 load results, fingerprints, confidence bounds, reconciliation, updated gates
- acceptance_criteria: zero silent loss/duplicate effect/stale writes/evidence link failures; known bottlenecks and empirical tails
- stop_condition: stop after Phase 9 gate reassessment; no automatic live pilot
- client_decisions_required: source, workload, SLO, retention, topology, operator roles

STOP_GATES:
- GATE_AUDIT_ARTIFACT: PASS
- GATE_SCRAPER_SCALING: BLOCKED
- GATE_PRODUCTION_ELIGIBILITY: BLOCKED
```

## 25. Machine-readable summary

The canonical final YAML document is
[`SCRAPER_ARCHITECTURE_AUDIT_SUMMARY_2026-07-17.yaml`](./SCRAPER_ARCHITECTURE_AUDIT_SUMMARY_2026-07-17.yaml).
It is intentionally a separate strict artifact so the CLI can reject duplicate keys, validate
cross-field invariants, and verify round-trip equality without parsing Markdown.
