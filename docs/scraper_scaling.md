# Scraper scaling contract

## Scope and verified repository facts

The Prom extraction parser remains a frozen component. Scaling code may change
queueing, HTTP instrumentation, retries, persistence, replay, and metrics, but
does not change `parsers/prom/parser.py` or the extraction/matching algorithms.
`PromGateway` only gained an opt-in `strict=True` boundary mode so an
orchestrated job cannot silently convert a failed required page into a partial
success.

Repository verification established:

- one current catalog logical item is one `store_sync` / `SyncRun`;
- `PromGateway.scrape(store_url)` can fetch many catalog pages and emit many
  products from one seller URL;
- one `HttpClient` logical request can execute several physical attempts;
- `ScrapeConfig.max_attempts=4` means four physical attempts total;
- local client delay is per client session, not a global source limit;
- Celery uses late acknowledgement, reject-on-worker-loss, and prefetch `1`;
- Compose has a dedicated `store-sync` queue/worker; concurrency `2` is a local
  default, not a production optimum;
- `Listing.raw_data` is structured `Product` JSON, not raw HTML evidence.

## Implemented boundary

The revision-2 architecture implementation is audited in
`SCRAPER_ARCHITECTURE_AUDIT_AND_IMPLEMENTATION_2026-07-17.md`; its strict
machine summary is `SCRAPER_ARCHITECTURE_AUDIT_SUMMARY_2026-07-17.yaml` and is
validated with `uv run validate-scraper-audit --manifest <path>`.

```text
logical item
  store_sync       -> SyncRun
  comparison_job   -> ScrapeTarget

task execution
  store_sync       -> StoreSyncTaskExecution
  comparison_job   -> ScrapeAttempt

logical HTTP request
  -> ScrapeHttpRequest

physical HTTP attempt
  -> ScrapeHttpAttempt

immutable raw response
  -> ScrapeEvidenceBlob (SHA-256, zlib compressed)

structured comparison result
  -> ScrapeTarget.payload + content SHA-256

immutable store-sync result
  -> StoreSyncProductSnapshot(sync_run_id, external_id, content SHA-256)

Metis evidence lineage
  -> RawMarketCapture(scrape_target_id, hash-verified raw HTTP manifest)
  -> MarketObservation
  -> ObservationTierClassification
```

The item kind and contract version are persisted and included in metrics.
`store_sync` and `comparison_job` are never combined under an unlabelled
“URLs/minute” capacity measure.

## Three work levels

1. Logical item: `store_sync`, `comparison_job`, or a future `product_url` /
   `replay_job`.
2. Logical HTTP request: `catalog_page`, `product_page`, or `search_page`.
3. Physical HTTP attempt: one actual `requests.Session.get` invocation.

A replayed logical request has zero physical attempts.

## Retry and deadline contract

HTTP and task retries use separate budgets:

- `ScrapeConfig.max_attempts` is `K_http`;
- `STORE_SYNC_MAX_TASK_EXECUTIONS` is store-sync `K_task`;
- `PRICING_COLLECTION_MAX_TASK_EXECUTIONS` is comparison-job `K_task`;
- each logical item has a persisted finite deadline;
- retryable and terminal failures have separate reason codes;
- task execution, logical request, and physical attempt counters are separate;
- exhausted retry budget becomes explicit `terminal_failure`;
- retryable work cannot circulate indefinitely.
- HTTP retries use capped full-jitter exponential backoff;
- numeric `Retry-After` is honored only within the configured cap.

## Trusted admission and multi-axis result

`services/scraper_architecture.py` owns strict `scrape-request.v2` and
`scrape-result.v2` contracts. A client cannot supply source-policy authority,
canonical input, or server idempotency keys. The trusted server computes four
separate namespaces: submission, acquisition, parse, and observation.

Execution, acquisition, parse, evidence, downstream eligibility, and operator
action are independent axes. In particular, a worker may finish successfully
while the result still requires review/no recommendation. Partial or invalid
evidence cannot be marked downstream eligible.

## Transactional dispatch outbox

Accepted store-sync/pricing jobs and their first dispatch event are committed
in one database transaction. Pricing fan-out and calculation fan-out use the
same outbox. Every event has an immutable payload and deterministic Celery task
ID. The recovery task `marko.worker.reconcile_scrape_outbox` republishes pending
or expired-lease events; consumers remain at-least-once, idempotent, and fenced.

This closes the silent DB-to-broker gap without claiming exactly-once delivery.
The following metrics expose its operational state:

```text
scrape_outbox_pending
scrape_outbox_dispatching
scrape_outbox_terminal_failed
scrape_outbox_oldest_pending_age_seconds
```

Measured amplification:

\[
A_{http} =
\frac{physical\_http\_attempts}{logical\_http\_requests}
\]

\[
A_{task} =
\frac{task\_executions}{unique\_logical\_items}
\]

\[
A_{total} =
\frac{physical\_http\_attempts}{unique\_logical\_items}
\]

The implementation uses direct counts. It does not multiply averages when
telemetry exists.

The independent-attempt equation is implemented only as a sanity check:

\[
P_{success,request}(k)=1-(1-p)^k
\]

\[
E[A_{request}] =
\begin{cases}
\frac{1-(1-p)^k}{p}, & p>0\\
k, & p=0
\end{cases}
\]

## Idempotency, checkpointing, and replay

Store sync:

- an active `(workspace, store)` run is reused instead of queued twice;
- a PostgreSQL advisory lock and partial unique index close the concurrent
  get-or-create race;
- one immutable `StoreSyncProductSnapshot` is unique by
  `(sync_run_id, external_id)`, including products with no usable price;
- `PriceObservation` is unique by `(sync_run_id, listing_id)`;
- listing upserts remain stable by `(store_id, external_id)`;
- completed HTTP responses are stored by content SHA-256;
- redelivery loads the prior request-fingerprint → raw-response cache;
- `HttpClient` returns immutable stored HTML to the unchanged parser;
- already persisted products are skipped;
- remaining uncaptured requests continue through the network boundary.

Thus replay does not require a repeated network fetch for retained pages and
does not duplicate observations.

Comparison jobs:

- one `ScrapeTarget` is created per canonical `(product identity, query,
  adapter version)` input;
- only one representative `PricingRunItem` is dispatched per target;
- successful target output is persisted before item evidence fan-out;
- redelivery reuses target output and raw responses;
- every write is fenced by target generation, owner task, delivery number, and
  concrete attempt ID; stale workers are recorded as `worker_lost`;
- bounded retries and broker redeliveries may supersede an unexpired lease,
  preventing a failed persistence attempt from leaving a target permanently in
  `collecting`;
- each dependent item receives a target reference and its own Metis observation
  lineage without duplicating the parser payload.

## Global source coordination

The Redis coordination slot is acquired before every physical HTTP attempt, not
once per seller or comparison task.

For one local session:

\[
r_{session}\approx
\frac{1}{
\max(E[T_{network}], delay+E[jitter])
}
\]

Without global coordination aggregate request starts grow with active sessions.
The Redis limiter enforces:

\[
R_{issued}\le R_{source}
\]

`PRICING_COLLECTION_MIN_INTERVAL_SECONDS` configures the shared Prom budget.
It must be calibrated against controlled-load evidence and provider limits.

## Capacity model

Terminal worker time already includes waits, HTTP retries, backoff, parsing,
persistence, and task re-execution:

\[
\mu_{terminal}=\frac{1}{E[T_i]}
\]

\[
C_{worker}(c)=c\times\eta(c)\times\mu_{terminal}
\]

The implementation never divides this capacity by retry amplification again.

\[
C_{source}=\frac{R_{source}}{h}
\qquad
C_{db}=\frac{R_{db}}{w}
\]

\[
C_{terminal}=
\min(C_{worker},C_{source},C_{db},C_{queue})
\]

\[
C_{success}=C_{terminal}\times p_{success}
\]

Terminal and successful capacity are returned separately. Derived and measured
models are explicitly tagged; a measured full-system capacity is not penalized
again.

\[
\rho_{item}=\frac{\lambda_{item}}{C_{terminal}}
\qquad
\rho_{source}=\frac{\lambda_{item}h}{R_{source}}
\qquad
\rho_{db}=\frac{\lambda_{item}w}{R_{db}}
\]

Continuous-flow stability requires every required subsystem capacity to be
known and every resulting utilization to remain below `1`. Initial engineering
headroom `0.70` is reported as an assumption, not a universal law. The
implementation does not mark stability/headroom as proven and does not emit a
drain-time estimate while any required source, database, or queue capacity is
unknown.

\[
T_{drain,no-arrivals}\approx\frac{B}{C_{terminal}}
\]

\[
T_{drain,with-arrivals}\approx
\frac{B}{C_{terminal}-\lambda_{item}}
\]

Finite batch lower bound:

\[
T_{batch,lower} =
\max\left(
\frac{\sum_i T_i}{c\eta(c)},
\frac{\sum_i H_i}{R_{source}},
\frac{\sum_i W_i}{R_{db}}
\right)
\]

Scheduler overhead and tail time are added separately.

## Reconciliation

Admission and lifecycle reconciliation are kept as two explicit equations:

\[
N_{submitted} = N_{deduplicated}+N_{rejected}+N_{admitted}
\]

\[
N_{admitted} = N_{queued}+N_{running}+N_{retry-wait}+N_{success}
+N_{failed}+N_{cancelled}
\]

The compatibility snapshot also calculates:

\[
N_{valid} =
N_{queued}+N_{running}+N_{retry-wait}+N_{success}+N_{failed}
\]

\[
N_{loss}=N_{valid}-N_{accounted}
\]

`N_loss` must be zero. Terminal rate and success rate are separate. An explicit
terminal failure is preferable to a silently lost item.

Binary rates are accompanied by a Wilson confidence interval rather than an
unqualified point estimate. Structured completeness is a weighted per-record
distribution (`minimum`, `p05`, `p50`, `p95`) plus per-field and critical-field
missing rates; an empty cohort is represented as unknown, not as perfect data.

## Storage

Raw and structured layers are not double-counted:

```text
raw_unique_html_bytes × compression_ratio
+ structured Product/comparison bytes
+ request/attempt journal bytes
+ observation bytes
+ recommendation lineage bytes
+ index/database overhead
```

`ScrapeEvidenceBlob` is immutable, compressed, and content-addressed. Metrics
expose raw unique bytes, compressed bytes, structured bytes, journal bytes,
observation bytes, recommendation lineage, and net storage.
`StoreSyncProductSnapshot` is the immutable structured store output;
`Listing.raw_data` remains only the mutable current-state cache. Index/database
overhead is explicitly reported as unmeasured until a deployment supplies a
physical database measurement.

## Metrics API

Authenticated JSON:

```text
GET /api/v1/jobs/{sync_run_id}/scrape-metrics
GET /api/v1/pricing/runs/{run_id}/collection-metrics
```

Prometheus text:

```text
GET /api/v1/jobs/{sync_run_id}/scrape-metrics/prometheus
GET /api/v1/pricing/runs/{run_id}/collection-metrics/prometheus
```

Capacity query parameters:

```text
arrival_rate_items_per_second
parallel_efficiency
database_write_capacity_per_second
queue_capacity_items_per_second
```

The Prometheus response contains all required item, request, attempt, queue,
worker, output, evidence, resource, and dependency metric families. Persisted
`queued + retry_wait` state is the logical queue-depth measure. Broker publish
latency, broker-native consumer lag, object-storage latency, and physical
database/index overhead are emitted as unavailable or warned as unmeasured
until those deployment paths are instrumented. A real `SELECT 1` round-trip is
reported separately as `database_probe_latency_seconds`; it is not mislabeled
as transaction latency.

## Controlled benchmark protocol

Do not infer production capacity from one local run. Use an approved controlled
workload only.

```text
c = 1, 2, 4, 8, ... until first material saturation or configured ceiling
```

Required workload classes:

- small, medium, and large store;
- successful path;
- retryable failure;
- terminal failure;
- worker-loss / broker redelivery;
- raw-evidence replay;
- comparison job.

Every run records:

- configuration and dataset fingerprints;
- item/page/product/request/attempt counts;
- `A_http`, `A_task`, `A_total`;
- `C_terminal`, `C_success`, and system `eta(c)`;
- p50/p95/p99 latency and oldest queue age;
- error and HTTP-status distribution;
- database writes, CPU, memory, storage;
- evidence coverage and silent-loss reconciliation.

Evaluator:

```bash
python scripts/evaluate_scraper_benchmark.py benchmark-input.json \
  --output benchmark-decision.json
```

Input skeleton:

```json
{
  "acceptance": {
    "required_terminal_capacity": 1.5,
    "required_successful_capacity": 1.5,
    "minimum_success_rate": 0.95,
    "latency_p95_slo_seconds": 20,
    "latency_p99_slo_seconds": 30,
    "max_http_attempts_per_item": 3,
    "max_source_utilization": 0.7,
    "max_database_utilization": 0.7,
    "max_error_rate": 0.05,
    "max_rate_limited_attempt_rate": 0.01,
    "minimum_evidence_coverage": 1.0
  },
  "runs": []
}
```

The evaluator selects the smallest concurrency satisfying every condition,
stops selection at saturation/error degradation, and refuses to call capacity
proven without a `c=1` baseline and at least two comparable concurrency levels.
`eta(c)` is marked as worker-code-interpretable only while source and database
remain below headroom.

## Acceptance status

Implemented and locally verified:

1. versioned logical item definitions;
2. explicit terminal states and `N_loss` reconciliation;
3. separate bounded HTTP/task retry budgets;
4. finite item deadlines;
5. idempotent redelivery effects;
6. global physical-attempt request budget;
7. separate terminal/success capacity;
8. p50/p95/p99 and oldest queue age;
9. stable versioned output serialization;
10. immutable raw evidence linked to structured output;
11. network-free replay of retained responses;
12. worker/source/database capacity decomposition;
13. saturation-aware benchmark decision rules;
14. generation/attempt fencing for stale-worker rejection;
15. race-safe content-addressed evidence insertion and hash verification;
16. bounded orphan-evidence garbage collection;
17. extraction parser internals unchanged;
18. fail-closed source authorization before every physical HTTP attempt;
19. workspace-scoped dead-letter visibility and admin-only replay into a new
    workflow without rewriting terminal history.

Source-access behavior is deliberately asymmetric:

- retained raw evidence can replay without network permission;
- client-supplied XLSX can be ingested without marketplace permission;
- `NOT_PERMITTED` or `UNKNOWN` blocks all new public-marketplace HTTP attempts;
- a `PERMITTED_*` verdict is invalid without an auditable reference.

Dead-letter endpoints:

```text
GET  /api/v1/operations/dead-letters
POST /api/v1/operations/dead-letters/{kind}/{id}/replay
```

Requires an approved controlled benchmark before production PASS:

- measured capacity at multiple concurrency levels;
- calibrated `eta(c)`;
- empirical source/database/queue limits;
- verified p95/p99 and retry/error SLO for real workload classes;
- final production worker count.

No external load test is run automatically by the repository or verification
suite. Unit/contract tests and offline PostgreSQL migration SQL validate local
correctness, but a live PostgreSQL + Redis + Celery failure/recovery exercise is
still required before production PASS.
