# PROMPT 15.016 — Yuri V1 implementation report

Date: 2026-07-18  
Checkout: `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`  
Repository binding: physical path plus SHA-256; `.git` metadata is not available in this checkout.

## Terminal result

- Independent implementation stage: **PASS**.
- Overall prompt gate: **BLOCKED**.
- Controlled-pilot ready: **false**.
- Production ready: **false**.
- First unverified transition: **measured client catalog -> permission-safe representative market replay**.

The code now enforces the Yuri V1 semantics covered by `R-01…R-17`. All seventeen
requirements pass. Yuri selected `SERVER_SIDE_ENCRYPTED`, so `R-05` passes with
application-level AES-256-GCM persistence, append-only audit records, key rotation,
safe derived outputs and a real PostgreSQL rollback-only proof. On 2026-07-19 Yuri
provided the real 4,901-row client workbook; deterministic measurement reproduced
the stated approximately 94% KEMP, 97% distinct normalized OE and 22% dimension
coverage, so `R-15` now passes. Market replay, source authority and operational E5
gates still veto pilot and production claims.

## First broken transitions and remediation

| Area | Baseline first broken transition | Implemented behavior |
|---|---|---|
| Identity | Candidate retrieval -> OE evidence rejected a different brand before normalized OE | OE is the identity key; brand is informational. Same normalized OE can continue across brands; conflicting or colliding OE fails closed. |
| Tiering | Identity -> tier normalization could not be reached cross-brand; an absent coefficient could become `1` | Tiering is downstream of identity. Only explicitly validated coefficients are used; unknown coefficients abstain. |
| Condition | Frozen payload -> persistence discarded description | An additive boundary preserves available description and condition without editing parser internals. Used/refurbished signals from any available lane hard-exclude the offer. |
| Cohorts | KEMP classification -> target eligibility | Cohorts are explicit and disjoint. `KEMP_REFERENCE` is retained for diagnostics but cannot enter cleaning, target median, guardrails, or recommendation. |
| Age policy | Stock status -> price target used a status constant and fresh inventory could only rise | Fresh inventory can follow a supported market down. Stale/dead inventory uses monotone versioned age pressure. |
| Cost | Manual cost -> plaintext persistence/API/snapshot had no approved privacy architecture | `SERVER_SIDE_ENCRYPTED` stores only AES-GCM ciphertext with external keys and append-only audit records. Raw cost is absent from responses/snapshots; cost is not a universal market-price floor. |
| Sorting | Recommendation -> listing ordered by an economic priority while the label implied price change | Absolute and percentage changes are persisted; API/UI implement a stable literal absolute-change sort independent of the review queue. |
| Evidence links | Observation -> operator evidence lacked lane-specific absence semantics | Each evidence row carries an openable HTTP(S) URL or an explicit absence reason. |
| Crosses | Description -> identity had no safe phase-2 lane | Description-derived cross numbers are stored as unvalidated phase-2 candidates and never become automatic identity evidence. |

## Pricing model implemented

For stale/dead inventory the age component is deterministic and monotone:

\[
\beta_{age}(a)=1-\exp\left(-\ln(2)\frac{\max(0,a-a_0)}{h}\right),
\]

\[
\beta=\operatorname{clamp}_{[0,1]}\left(
\max(\beta_{base},\beta_{age},\ell,u)
\right),
\]

\[
p^*=(1-\beta)p_{current}+\beta\min(p_{current},Q_{low}(P_{target})).
\]

Here `a` is stock age, `a0` the status threshold, `h` the status-specific
half-life, `ell` the liquidity target, and `u` urgency. The target is bounded above
by current price for clearance. Policy validation requires positive half-lives,
dead-stock pressure at least as strong as stale pressure, and versioned parameters.
If exact age is unavailable, the declared stock status applies the base policy and
the trace records `STOCK_AGE_UNKNOWN_BASE_POLICY_ONLY`; no fabricated zero age is
inserted.

Sunk cost is excluded from fair-market estimation and from the hard price floor.
Any below-cost decision remains an explicit manual operator action. The accepted
privacy ADR selects `SERVER_SIDE_ENCRYPTED`; fair-market estimation remains cost-free.

## Requirement status matrix

| ID | Status | Decisive evidence |
|---|---|---|
| R-01 | PASS | OE-first positive, conflicting-OE negative, Unicode normalization and collision tests |
| R-02 | PASS | Tier-after-identity and unknown-coefficient fail-closed tests |
| R-03 | PASS | Append-only manual decision API/UI; E2E reports zero automatic applications |
| R-04 | PASS | Fresh-lower plus stale/dead monotonicity and policy-boundary tests |
| R-05 | PASS | AES-256-GCM encrypted append-only persistence, external keyring, tamper/AAD/rotation tests, safe API/UI outputs and PostgreSQL rollback-only runtime proof |
| R-06 | PASS | API and Flutter contract tests for literal absolute-change sort |
| R-07 | PASS | URL protocol validation, persistence, API and operator evidence lanes |
| R-08 | PASS | Additive description boundary and isolated unvalidated cross-candidate lane |
| R-09 | PASS | Title/description/explicit-condition used signals hard-reject target membership |
| R-10 | PASS | KEMP price and persisted-role metamorphic tests leave target recommendation unchanged |
| R-11 | PASS | No Autopro, TecDoc/full-cross, 1C/BAS or writeback path was added |
| R-12 | PASS | Physical-inventory context remains; no FX/replacement-cost core coupling |
| R-13 | PASS | Missing/cost-mutated input does not floor or block supported clearance; decision remains manual |
| R-14 | PASS | No elasticity or causal demand output was added |
| R-15 | PASS | Client-provided SHA-bound 4,901-row workbook measured: 94.27% KEMP, 97.41% distinct normalized OE/rows, 22.10% complete dimensions; 4,647 rows auto-admissible and 254 routed to OE review |
| R-16 | PASS | Prom-only provider boundary preserved |
| R-17 | PASS | Sparse, conflicting and unknown evidence abstains rather than producing a false recommendation |

Detailed per-requirement code, schema, test and UI references are in
`PROMPT_15_016_REQUIREMENTS_TRACE_2026-07-18.yaml`.

## Persistence, API and UI impact

Migration `20260718_0012_yuri_v1_alignment.py` additively introduces condition,
competitor URL/absence reason, cross-candidate, cohort-count, absolute-delta and
percentage-delta fields plus constraints and indexes. A clean disposable PostgreSQL
upgrade passed. Migration `20260718_0013_encrypted_catalog_cost.py` adds the
append-only encrypted cost ledger with deterministic sequence ordering, tenant/item
scope, AES-GCM metadata and DB constraints. Existing legacy plaintext columns were
not destructively removed; the active flow ignores and redacts them.

The API now:

- exposes explicit cohort and evidence-lane fields;
- validates competitor URL protocols, including legacy rows;
- supports literal absolute-change ordering;
- accepts raw cost only in validated `SERVER_SIDE_ENCRYPTED` manual writes, encrypts
  it before persistence, and strips it from validation errors, catalog raw rows,
  contexts, replay mismatches and decision responses;
- preserves replay V1-V4 compatibility while producing the V4 contract;
- keeps price changes as manual audited decisions only.

The Flutter operator surface now displays comparable target evidence separately
from KEMP/reference/rejected lanes, links only openable competitor URLs, explains
missing links, offers the literal maximum-change sort, displays confidence/manual
review states, and supports encrypted cost set/replace/clear without reading raw cost
back from the server.

## Material implementation files

Backend semantics and data flow:

- `backend/src/metis/pricing/{types,comparability,tiering,engine}.py`
- `backend/src/marko/services/{matching,parser_models,market_collection,pricing_runs}.py`
- `backend/src/marko/core/cost_encryption.py`
- `backend/src/marko/services/{catalog_costs,cost_privacy,recommendation_replay,xlsx_catalog}.py`
- `backend/src/marko/api/{main.py,schemas/catalog.py,schemas/pricing.py}`
- `backend/src/marko/api/routers/v1/{catalog.py,pricing.py}`
- `backend/src/marko/infrastructure/db/models.py`
- `backend/migrations/versions/20260718_0012_yuri_v1_alignment.py`
- `backend/migrations/versions/20260718_0013_encrypted_catalog_cost.py`

Operator UI:

- `frontend/lib/features/pricing/{pricing_models,pricing_api,pricing_controller}.dart`
- `frontend/lib/features/pricing/{recommendations_page,catalog_context_dialog,recommendation_decision_dialog}.dart`
- `frontend/test/{pricing_api_test,pricing_below_cost_dialog_test,pricing_encrypted_cost_dialog_test}.dart`

Contracts and regression evidence:

- `backend/tests/test_yuri_v1_contract.py`
- pricing, API, catalog, replay and tenant test modules under `backend/tests/`
- all `PROMPT_15_016_*_2026-07-18` artifacts in `docs/`

The frozen files `backend/src/marko/parsers/prom/parser.py` and
`backend/src/marko/parsers/prom/gateway.py` were not modified; their final hashes
exactly equal the recorded pre-change hashes.

## Verification

| Check | Result | Evidence level |
|---|---|---|
| `cd backend && uv run pytest -q` | **590 passed** | E3 local regression |
| `cd backend && uv run pytest -q tests/test_yuri_v1_contract.py` | **40 passed in 1.51s** | E3 targeted contract |
| `cd backend && uv run ruff check .` | PASS | E3 |
| `cd backend && uv run python -m compileall -q src tests` | PASS | E3 |
| Flutter tests | **25 passed** | E3 |
| `dart analyze --fatal-infos` | PASS, no issues | E3 |
| Native `flutter analyze` on Unicode checkout path | `BLOCKED_ENVIRONMENT`, exit 255 before diagnostics | tooling limitation, not converted to PASS |
| Alembic offline SQL and local PostgreSQL upgrade | PASS; head `20260718_0013` | E4 local integration |
| Encrypted-cost PostgreSQL transaction proof | PASS; authenticated decrypt succeeded, rollback left 0 synthetic records, no key printed | E4 local integration |
| Current Compose stack | API healthy, frontend HTTP 200, DB head `20260718_0013` | E4 local integration |
| Isolated full-stack run `20260718T204534Z-05fa3ff1` | PASS; failure injections 10/10, browser assertions 10/10, exact replay, cleanup true | E4 non-representative |
| Frozen parser hashes | parser `1856f717…a7b66`; gateway `3c480c04…8cb` unchanged | E3 |

The E2E used content-addressed synthetic catalog and immutable replay evidence.
It made **0 live Prom requests** and **0 automatic price applications**. It proves
the executable local workflow, not representative market correctness or production
readiness.

## Variation, metamorphic and mutation results

Fourteen named safety mutations were killed; none survived. Covered counterexamples
include cross-brand same-OE, same-brand conflicting-OE, Unicode separator variants,
normalized OE collisions, unknown condition, description-only used markers, forged
persisted cohort roles, KEMP-only price mutations, age monotonicity, dead/stale
dominance, missing coefficients, raw-cost leakage, URL protocol abuse, insufficient
sample size and misleading sort semantics.

An earlier E2E run (`20260718T204246Z-ffc64f36`) correctly failed when the privacy
redactor removed safe derived `cost_configured` metadata only from replay fingerprint
input. The fix introduced an explicit safe-derived allowlist and regression tests;
the terminal rerun passed with equal original/replay decision hashes. This failed run
is retained as evidence rather than hidden.

## Cost privacy decision

`PROMPT_15_016_COST_PRIVACY_ADR_2026-07-18.md` is now
`ACCEPTED_IMPLEMENTED` with mode `SERVER_SIDE_ENCRYPTED`. The implementation uses
AES-256-GCM, a fresh nonce, row/tenant-bound associated data, an external versioned
keyring and append-only SET/CLEAR records. It honestly does not claim to hide raw cost
from a compromised runtime holding the key. The local `.env` remains `UNDECIDED`
until a real deployment key is provisioned; that is an operational secret-management
gate rather than an unresolved R-05 business decision.

## Remaining blockers and owners

| Gate | Status | Owner | Exact missing input |
|---|---|---|---|
| `REPRESENTATIVE_CLIENT_CATALOG` | PASS | Yuri/data owner | Client workbook measured in `PROMPT_15_016_YURI_CATALOG_MEASUREMENT_2026-07-19.md` |
| `REPRESENTATIVE_MARKET_REPLAY` | BLOCKED_DATA | Product/data owner | Pinned, permission-safe representative Prom snapshot with expected outcomes |
| `SOURCE_ACCESS_PERMISSION` | BLOCKED_AUTHORITY_EVIDENCE for production | Source/product owner | Immutable production-scope authority/policy reference; local runtime configuration is only conditional evidence |
| `BACKUP_RESTORE`, `OBSERVABILITY`, `ROLLBACK`, controlled pilot | BLOCKED_E5 | Operations/product owners | Representative operational drill and approved pilot policy |
| Repository provenance | BLOCKED_ENVIRONMENT | Repository owner | Git metadata or signed source snapshot if commit-level provenance is required |

Yuri confirmed the practical workbook workflow: client-supplied values are entered
in convenient cells. The generated sheet therefore uses manual stock status plus
optional age days and never fabricates a purchase date or zero age.

## Hostile self-review outcome

- A KEMP observation cannot re-enter the target through legacy/replay/backfill paths;
  the engine re-derives safety signals and honors persisted non-target roles.
- Missing description is not interpreted as new condition; unknown/conflicting
  condition abstains.
- Seller independence and sparse-sample gates remain fail-closed.
- Unknown tier coefficients cannot become multiplier `1`.
- Greater stock age cannot weaken stale/dead markdown pressure under a valid policy.
- Raw cost is encrypted before persistence and absent from validation errors,
  responses, snapshots, replay and decision payloads; tampering and cross-row copying
  fail authentication.
- The UI sort label and API sort key both mean absolute recommended price change.
- Frozen-parser compatibility and real catalog coverage are proven. Representative
  market observations and permission-safe replay are not; that is now the first
  external gate.
- No Autopro/TecDoc/1C/writeback scope was introduced.

## Production implication and next action

The implementation may be used for further controlled validation, but **must not be
described as pilot-ready or production-ready**. The single dependency-correct next
stage is `PERMISSION_SAFE_PROM_REPLAY_VALIDATION`: record source authority, freeze a
pinned permission-safe market snapshot and run a representative replay against the
measured catalog.
Production activation additionally requires external key provisioning plus a
backup/restore drill. Those stages are not started or authorized by this report.
