# Prompt 15.013 — Machine-readable summary implementation

Status: implemented  
Schema: `metis_marko_machine_readable_stage_summary`  
Schema version: `1.1.0`  
Scope owner: Cross-cutting Marko + Metis governance  
Source prompt SHA-256: `a6c5e5566a6b6c3ba7e590cae9ed3cdf5f9b84ad52033870964f2e6676af2ea8`

## 1. Scope and outcome

Section 16 is implemented as the machine boundary following the Section 15
human footer. This change implements the format and its validators. It does not
start a new project audit, change pricing, redesign the parser, mutate scraper
behavior, or claim production readiness.

The implementation provides:

- immutable typed schema models for every canonical top-level section;
- explicit enums for terminal, verification, evidence, production, repository,
  maturity, queue, reuse, source, decision, assumption, and gap states;
- strict YAML parsing with duplicate-key and unsafe-feature rejection;
- deterministic serialization and parse/serialize/parse equality validation;
- readiness intervals that retain unknown dimensions in the denominator;
- evidence ceilings, critical-floor, weighted-system, RPN, reuse, and scraper
  capacity arithmetic;
- repository, production, scraper, reuse, gap, source, unknown, next-stage, and
  stop-gate cross-field invariants;
- exact validation of the sequence `Section 15 stop-gate -> final Section 16
  YAML`;
- executable CLI, self-review output, canonical example, and hostile tests.

## 2. Final response order

For a substantive project response, the publication boundary is:

````text
STAGE_RESULT
BLOCKERS
NEXT_STAGE
STOP_GATE_<NORMALIZED_STAGE_ID> = PASS|FAIL|BLOCKED|NO_GO
MACHINE_READABLE_SUMMARY:
```yaml
<one schema 1.1.0 document>
```
````

The stop-gate remains the final human-readable status line. The YAML document
is the final substantive block. No explanation, correction, second gate, or
roadmap may follow its closing fence.

## 3. Schema implementation

The typed root has the exact canonical sections:

```text
schema
stage
repository
metis
marko
combined_system
gaps
business_decisions_required
source_access_states
engineering_assumptions
future_hypotheses
unknowns
next_stage
validation
termination
```

The implementation extends the canonical readiness objects with
`dimension_weights`, `capabilities`, and `critical_capability_ids`. These fields
are required for executable reverse arithmetic: without the underlying
capability records, a system score cannot be independently recalculated.

The Marko reuse object similarly adds `evaluated_component_ids`, allowing the
validator to prove both disjointness and completeness rather than checking only
for duplicates.

## 4. Unknown and empty-value semantics

Scalar unknowns use `null`; verification unknowns use the explicit `UNKNOWN`
enum. `false` is never silently interpreted as unknown. Material nulls require
an `unknown_record` whose `field_path` is exact or a declared wildcard such as
`marko.*`.

An empty audited category must either:

- carry a matching unknown record, meaning the category was not assessed; or
- carry an explicit `EMPTY_CATEGORY_VERIFIED:<path>` validation warning,
  meaning the category was checked and no items were found.

This rule applies to gaps, reuse, business decisions, and source-access state.

## 5. Strict YAML boundary

The parser accepts exactly one non-empty mapping document and rejects:

- duplicate mapping keys;
- tabs in indentation;
- anchors and aliases;
- explicit/custom tags;
- merge keys;
- implicit YAML timestamps;
- unquoted YAML 1.1 `YES/NO/ON/OFF` values;
- multi-document input;
- empty strings;
- unresolved `<PLACEHOLDER>` and enum-union values;
- numeric and boolean strings where numbers or booleans are required;
- NaN and Infinity;
- unknown fields.

The serializer disables aliases, preserves field order, quotes timestamp-like
strings, and must satisfy:

```text
Parse(Serialize(Parse(YAML))) = Parse(YAML)
```

## 6. Readiness arithmetic

Default dimension weights are exactly:

```text
implementation  0.20
verification    0.15
integration     0.15
auditability    0.15
operations      0.15
security        0.10
documentation   0.10
```

They sum to one and remain an engineering assumption until approved.

For an unknown dimension, lower input is zero and upper input is one. The
unknown weight is retained; known weights are never renormalized. Each
capability records raw and evidence-capped intervals. Evidence caps are:

| Evidence | Cap |
|---|---:|
| E0 | 0 |
| E1 | 25 |
| E2 | 50 |
| E3 | 75 |
| E4 | 90 |
| E5 | 100 |

System `weighted_readiness` must equal the conservative weighted lower bound.
`critical_floor` is the minimum critical-capability lower bound and
`evidence_level` is the minimum critical evidence rank. The highest average
cannot override either floor.

All comparisons use a tolerance of `1e-6` before display rounding.

## 7. Scraper mathematics and evidence

Capacity validation implements:

```text
mu_eff = mu / average_attempts
C      = active_workers * mu_eff
rho    = arrival_rate / C, only when C > 0
drain  = backlog / (C - arrival_rate), only when C > arrival_rate
```

When `C <= arrival_rate`, queue state must be `UNSTABLE` and drain time must be
`null`. A stable queue above the engineering target `rho <= 0.70` requires an
explicit warning.

`located=VERIFIED` does not promote runtime, batch, concurrency, queue, load, or
production states. Batch, parallel, queue, and production claims each have
separate prerequisite checks. `production_proven=VERIFIED` requires every
mandatory runtime/scale/storage/evidence/replay/observability field plus
measured capacity.

## 8. Reuse and gaps

Reuse score is recalculated as:

```text
100 * (0.30F + 0.25K + 0.20M + 0.15T + 0.10(1-C))
```

Component IDs must occur in exactly one reuse array, and their union must equal
`evaluated_component_ids`. `REUSABLE_AS_IS` is rejected when evidence is
incomplete, adaptation remains, or any Metis invariant is violated, regardless
of numeric score.

Gap priority remains semantic. RPN is used only for ordering inside priority:

```text
RPN = severity * likelihood * detection_difficulty * dependency_centrality
normalized = 100 * (RPN - 1) / 374
```

Gap IDs are unique across P0-P3, their embedded priority must match their array,
and every record requires an evidence trace.

## 9. Production and end-to-end gates

Stage `PASS` is independent of system production eligibility. Combined
production eligibility requires all of the following simultaneously:

- Metis and Marko production eligibility;
- production gate `PASS` with no open gates;
- verified E4+ end-to-end flow;
- zero critical unknowns;
- no P0 or P1 production gap;
- verified explainability, auditability, replay, abstention, and manual review;
- passed replay, security, tenant isolation, deployment, backup/restore,
  observability, rollback/recovery, source-access, and abstention gates;
- no unknown or prohibited source state.

An end-to-end flow may be `VERIFIED` only with traced E4+ evidence. Production
maturity classes have the same E4 floor and cannot be inferred from a score.

## 10. Repository and temporal identity

Metis and Marko repository components are always represented separately. A
combined verified identity requires complete component snapshots, runtime
paths, evidence references, no unresolved duplicate copy, and a non-unknown
topology. A dirty worktree is allowed only when disclosed and traced.

The canonical example intentionally records the supplied workspace as
`identity_verified=false`: it has no Git metadata. Evidence therefore remains
path-bound rather than commit-bound.

`next_stage.started` is fixed to `false` and
`new_direct_instruction_required` is fixed to `true`. FAIL, BLOCKED, and NO_GO
successors are validated against repair, dependency-resume, and
decision/redesign semantics respectively.

## 11. CLI

Validate the canonical manifest:

```bash
make validate-machine-summary
```

Render the final block or print the executable self-review:

```bash
cd backend
uv run validate-machine-summary \
  --manifest ../docs/examples/machine_readable_summary_prompt_15_013.yaml \
  --render

uv run validate-machine-summary \
  --manifest ../docs/examples/machine_readable_summary_prompt_15_013.yaml \
  --self-check
```

Validate a complete response against both Section 15 and Section 16 manifests:

```bash
uv run validate-machine-summary \
  --manifest MACHINE_SUMMARY.yaml \
  --footer-manifest END_OF_RESPONSE.yaml \
  --response RESPONSE.md
```

Exit codes:

- `0`: valid schema and optional response;
- `1`: structural, arithmetic, semantic, trace, or alignment defect;
- `2`: unreadable or unparsable input.

## 12. Acceptance-criteria mapping

| Criteria | Enforcement |
|---|---|
| AC-01–AC-03 | strict parse, duplicate rejection, literal schema name/version |
| AC-04–AC-05 | separate component identities and human/machine gate comparison |
| AC-06–AC-09 | capability arithmetic, evidence caps, intervals, floors, typed evidence |
| AC-10 | stage result and production eligibility are separate fields/invariants |
| AC-11 | independent located/runtime/batch/parallel/queue/load/production fields |
| AC-12 | disjoint and complete reuse partition |
| AC-13 | unique and correctly partitioned P0-P3 gap records |
| AC-14 | distinct typed arrays for decisions, sources, assumptions, hypotheses, unknowns |
| AC-15 | literal stopped next-stage contract |
| AC-16 | material evidence refs plus material-null unknown coverage |
| AC-17–AC-18 | V-01–V-16 tests and executable hostile self-review |
| AC-19 | PASS forbids declared validation errors or false validation flags |
| AC-20 | combined-response validator requires YAML fence to be final |

## 13. Variation coverage

| Variations | Automated coverage |
|---|---|
| V-01 | audit PASS with combined production false |
| V-02 | PASS rejected when required validation/artifact state fails |
| V-03 | BLOCKED remains primary over secondary FAIL |
| V-04 | NO_GO requires decision/redesign successor |
| V-05 | system weighted value and critical floor independently recomputed |
| V-06 | E3 raw score 90 capped to 75 |
| V-07 | unknown dimension retained in lower/upper interval and unknown weight |
| V-08 | located scraper with all runtime states not verified remains valid |
| V-09 | batch/parallel claims require their own evidence prerequisites |
| V-10 | overloaded queue is unstable with null drain time |
| V-11 | Metis invariant violation forbids reusable-as-is |
| V-12 | unknown/prohibited source state blocks combined production claim |
| V-13 | repository dirtiness/identity remain explicit fields and evidence limits |
| V-14 | duplicate/unresolved identity prevents aggregate identity verification |
| V-15 | unaudited empty gap list requires unknown or explicit assessment warning |
| V-16 | production predicate requires verified abstention and cannot use missing evidence |

## 14. Implementation map

- `backend/src/marko/governance/machine_summary_models.py` — schema and enums.
- `backend/src/marko/governance/machine_summary.py` — math, strict YAML,
  serializer, invariants, response alignment, self-review.
- `backend/src/marko/governance/machine_summary_cli.py` — CLI.
- `backend/tests/test_machine_summary.py` — arithmetic, parser, semantic,
  cross-field, response, CLI, and hostile variations.
- `docs/examples/machine_readable_summary_prompt_15_013.yaml` — truthful
  current-stage manifest with explicit non-assessed project readiness.

This implementation proves the response contract locally. It does not prove
Marko/Metis production readiness or scraper production capacity.
