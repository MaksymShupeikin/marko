# Prompt 15.012 — End-of-response contract implementation

Status: implemented  
Contract version: `15.1`  
Scope owner: Cross-cutting Marko + Metis governance  
Source prompt SHA-256: `6bc64e058a220b7e4bd31e6f2dded560326f66d03150e4cadbd9a1cf9228b481`

## 1. Outcome

Section 15 is implemented as an executable governance boundary rather than a
copy-only answer template. The project now has:

- immutable Pydantic models for the machine-readable manifest;
- deterministic stage-ID normalization and stop-gate generation;
- a canonical human-readable footer renderer;
- structural, semantic, mathematical, blocker, evidence, temporal, and
  status-precedence checks;
- a CLI that validates a manifest, renders a footer, and compares a complete
  response with its manifest;
- repository-wide agent instructions and a versioned valid example;
- hostile variation tests covering the canonical terminal states and failure
  patterns.

The implementation does not alter Metis pricing, matching, scraper, or Marko
application behavior. It is a cross-cutting response-governance component.

Section 16 integration note: the Section 15 stop-gate remains the last
human-readable status line. When the machine-readable summary contract is
active, one final Section 16 YAML block follows it. The combined validator
checks Section 15 on the prefix and Section 16 on the trailing block.

## 2. Canonical response boundary

Every substantive project response ends with exactly one footer in this order:

```text
STAGE_RESULT:
  stage, status, completed scope, strongest verified result,
  weakest critical area, evidence quality, production implication

BLOCKERS:
  P0, P1, business decisions, source/access, data,
  environment/reproducibility, unknowns

NEXT_STAGE:
  id, title, dependency reason, required inputs, expected future artifacts,
  testable acceptance criteria, stop condition, client decisions

STOP_GATE_<NORMALIZED_STAGE_ID> = PASS|FAIL|BLOCKED|NO_GO
```

The stop-gate is the last substantive line. There is one primary status and one
executable stop-gate. Secondary findings cannot weaken the primary status.

## 3. Identity and terminal-state rules

Stage normalization is deterministic:

1. uppercase;
2. spaces and hyphens become underscores;
3. characters outside `[A-Z0-9_]` are removed;
4. repeated underscores collapse;
5. leading and trailing underscores are removed.

If no truthful stage identity exists, the caller uses
`UNASSIGNED_CURRENT_STAGE`, records `missing_stage_identity`, and uses
`BLOCKED` where identity is required for the current gate.

Status semantics are enforced as follows:

| Status | Required meaning | Required successor |
|---|---|---|
| `PASS` | All hard current-stage scope is complete, traced, and supported by E2+ evidence; no P0 remains | Next dependency stage, not started |
| `FAIL` | An executable E3+ check proves a repairable current-stage defect | Repair or revalidation of the current stage |
| `BLOCKED` | A current hard dependency is external, owned, and unavailable; all available work is complete | Resolve dependency and resume |
| `NO_GO` | Reproducible E3+ evidence falsifies the bounded approach or a hard gate | Decision, alternative, replacement, or scope revision |

When findings coexist, precedence is:

```text
NO_GO > BLOCKED > FAIL > PASS
```

## 4. Evidence and scoring contract

The canonical evidence scale is preserved:

| Level | Meaning | Score cap |
|---|---|---:|
| E0 | no evidence | 0 |
| E1 | assertion or unverified documentation claim | 25 |
| E2 | located artifact, schema, configuration, or test definition | 50 |
| E3 | focused deterministic executable evidence | 75 |
| E4 | pinned reproducible integration, replay, or E2E evidence | 90 |
| E5 | representative operational, load, recovery, or pilot evidence | 100 |

For any raw score `s_raw` and evidence level `e`, the validator uses:

```text
s = min(s_raw, cap(e))
```

Coverage helpers implement `N / max(D, 1)`, reject negative counts, reject a
non-zero numerator with a zero denominator, and keep all manifest ratios in
`[0,1]`. The critical evidence floor cannot exceed either the highest declared
level or the weakest critical area's evidence level. A high average never
overrides the critical floor.

`PRODUCTION_READY_PROVEN` is valid only with `production_ready=true`, E5
evidence, and no failed or blocked hard gate. Current-stage `PASS` and
production readiness remain independent predicates.

## 5. Blocker contract

Every blocker has an ID, P0/P1 priority, canonical category, affected scope,
gate impact, evidence references, owner, observable resolution condition, and a
flag stating whether the agent can resolve it now.

- P0 may block truthful current completion, hard acceptance, integrity,
  security, reproducibility, or a non-negotiable invariant.
- P1 does not block the current gate. A P1 marked as affecting the current gate
  is rejected.
- `NONE_VERIFIED` requires a completed assessment of business decisions,
  source/access, data, environment/reproducibility, and unknowns, with no
  blocker or unknown remaining.
- `UNKNOWN_NOT_ASSESSED` is used when the search was incomplete or unresolved
  unknowns remain.

Category inventories must match the detailed blocker objects. Duplicate IDs,
empty blocked scope, and impact-free blockers are invalid.

## 6. NEXT_STAGE temporal boundary

`NEXT_STAGE` is a future dependency description, not authorization. The typed
contract fixes `started=false`, `authorized=false`,
`automatic_transition=false`, and `auto_continue=false`.

Every determined next stage needs:

- a stable normalized ID and dependency reason;
- explicit input availability (`true`, `false`, or `unknown`);
- artifacts marked `PLANNED_NOT_STARTED` and phrased as future work;
- boolean/testable acceptance criteria with evidence and threshold;
- its own normalized stop-gate and all four allowed terminal states;
- only real client decisions, with alternatives and architecture impact.

If a successor cannot be truthfully determined, use:

```yaml
id: NONE_AUTHORIZED
title: AWAITING_REQUIRED_DECISION
```

## 7. Machine manifest and CLI

The repository example is
`docs/examples/end_of_response_prompt_15_012.yaml`. Validate and render it:

```bash
cd backend
uv run validate-response-footer \
  --manifest ../docs/examples/end_of_response_prompt_15_012.yaml

uv run validate-response-footer \
  --manifest ../docs/examples/end_of_response_prompt_15_012.yaml \
  --render

uv run validate-response-footer \
  --manifest ../docs/examples/end_of_response_prompt_15_012.yaml \
  --self-check
```

Validate a complete response against its source manifest:

```bash
uv run validate-response-footer \
  --manifest MANIFEST.yaml \
  --footer RESPONSE.md
```

Exit codes:

- `0`: contract and optional response are valid;
- `1`: a contract/footer invariant failed;
- `2`: manifest or file input could not be parsed/read.

`--self-check` emits the complete Section 15.53 boolean publication checklist
from the same validated model.

The renderer and manifest are semantically coupled. When a footer differs from
the canonical rendering of its manifest, validation fails.

## 8. Validation passes

The implementation runs the four required classes of checks:

1. Structural: required blocks, order, field presence, exactly one final gate.
2. Semantic: stage/gate equality, terminal semantics, production separation,
   blocker consistency, no auto-transition, manifest/footer alignment.
3. Mathematical: bounded coverage and scores, protected denominators, evidence
   caps and floors, hard-gate semantics, status precedence.
4. Hostile variation: canonical status, evidence, blocker, identity,
   temporal, and alignment mutations.

Arbitrary natural-language claims cannot be proven semantically correct by a
deterministic parser. The validator therefore provides two hard machine
boundaries: exact manifest/footer equivalence and an explicit body marker such
as `CURRENT_STAGE_STATUS: FAIL`. Free-prose claim truthfulness remains a manual
review obligation and must use the same evidence ledger.

## 9. Acceptance-criteria coverage

| Contract criteria | Enforcement |
|---|---|
| AC-01–AC-07 | Required block/field/order checks, normalized stage ID, exact status and gate equality |
| AC-08–AC-12 | Completed-scope evidence, strongest result evidence, weakest area, floor, separate production model |
| AC-13–AC-15 | P0/P1 rules, category reconciliation, complete assessment before `NONE_VERIFIED` |
| AC-16–AC-21 | Frozen no-transition flags, typed inputs/future artifacts/criteria/stop condition/client decisions |
| AC-22–AC-23 | Status-specific invariants and independent production implication |
| AC-24 | Exact manifest/footer comparison and explicit body-status alignment |
| AC-25 | Typed ranges plus tested coverage and evidence-cap formulas |
| AC-26 | Focused unit and hostile-variation suite |
| AC-27 | Last-line and single-stop-gate checks |
| AC-28 | Literal-false transition fields and runtime invariant |

## 10. Variation coverage

| Variations | Test or invariant |
|---|---|
| V-01, V-02 | Audit `PASS` with production false; E3 does not imply E2E/production |
| V-03 | `FAIL` requires observed hard defect, E3+, repair/revalidation successor |
| V-04, V-14, V-23 | `BLOCKED` requires unavailable input and externally owned current P0; repository ambiguity case |
| V-05, V-15 | `NO_GO` requires reproducible E3+ falsification and decision/alternative successor |
| V-06, V-07 | Scope owner is explicit; combined production claim still requires E5 and closed gates |
| V-08, V-09, V-18 | `UNKNOWN_NOT_ASSESSED` vs fully assessed `NONE_VERIFIED` |
| V-10 | Weakest-area evidence cap and critical floor checks |
| V-11 | Stage/gate key mismatch is rejected |
| V-12 | Next artifact accepts only `PLANNED_NOT_STARTED` |
| V-13 | Status aggregation enforces canonical precedence |
| V-16 | `PASS` without an E2+ strongest result is rejected |
| V-17 | Production-ready E2 claim is rejected |
| V-19 | `NONE_AUTHORIZED / AWAITING_REQUIRED_DECISION` is supported |
| V-20 | A bounded abstention/insufficient-data stage can pass without emitting a production claim |
| V-21, V-22 | Scope-limited completion is allowed; hard current-scope defects force `FAIL` |
| V-24 | Manifest divergence and explicit body/footer status divergence are rejected |

## 11. Implementation map

| Prompt sections | Project implementation |
|---|---|
| 15.0–15.7 | Root instructions, stage models, normalizer, unassigned-stage checks |
| 15.8–15.18 | Renderer, result/evidence/production models, coverage and cap helpers |
| 15.19–15.24 | Blocker models, taxonomy reconciliation, status-specific validation |
| 15.25–15.36 | Next-stage models, frozen temporal flags, gate renderer |
| 15.37–15.41 | Versioned manifest, cross-field and temporal invariants |
| 15.42–15.54 | CLI repair boundary, hostile tests, acceptance matrix, root agent directive |

## 12. Files

- `AGENTS.md` — repository-wide publication rule.
- `backend/src/marko/governance/response_footer.py` — models, math,
  normalization, renderer, and validators.
- `backend/src/marko/governance/response_footer_cli.py` — executable CLI.
- `backend/tests/test_response_footer.py` — structural, semantic,
  mathematical, and hostile variation tests.
- `docs/examples/end_of_response_prompt_15_012.yaml` — valid manifest.

This contract establishes truthful response closure. It does not itself prove
that the Marko/Metis product is production-ready.
