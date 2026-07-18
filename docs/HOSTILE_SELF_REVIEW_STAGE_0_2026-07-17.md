# HOSTILE SELF-REVIEW — MATCHING STAGE 0

Review ID: `hsr-matching-stage0-20260717`  
Review date: `2026-07-17`  
Master prompt SHA-256: `f123f88fb819ceadf34b636187008c0a8ad792a50133b4e2dcc71d86f6d28b68`

## 1. REVIEW TARGET

- Target report:
  `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/docs/METIS_MATCHING_GOLD_SET_STAGE_0_AUDIT_2026-07-17.md`
- Baseline version: SHA-256
  `323896819162ee2065a0ac85d03422a6edf63ec0410aeeb1ccdcd5c9a40e68f5`.
- Corrected version: SHA-256
  `e34bdd9e8feb6d2c46c9b1096d349428df5f6b65bdd978f608c8c50f50396530`.
- Physical review root:
  `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`.
- Commit: `NOT_AVAILABLE`; the selected physical copy contains no `.git` metadata.
- Scope: report/evidence review and report repair only. Matcher, parser, pricing, models,
  migrations, config, tests, runtime state, and frontend behavior were out of write scope.

Frozen input manifest:

```yaml
review_input:
  target_report:
    path: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/docs/METIS_MATCHING_GOLD_SET_STAGE_0_AUDIT_2026-07-17.md"
    version: "sha256:323896819162ee2065a0ac85d03422a6edf63ec0410aeeb1ccdcd5c9a40e68f5"
    generated_at: "2026-07-17"
    generated_by: "previous Codex Stage 0 execution"
  current_stage:
    stage_id: "0"
    stage_name: "MATCHING REALITY AUDIT"
    expected_deliverables:
      - "reality audit"
      - "facts/assumptions/decisions/blockers separation"
      - "stage stop-gate"
  repository_candidates:
    metis:
      - "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/metis"
      - "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/metis_alpha/metis"
    marko:
      - "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko"
      - "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/metis_alpha/marko"
    other_related_copies:
      - "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/metis_alpha"
  expected_repository_identity:
    metis_path: "task-pinned active checkout/backend/src/metis"
    marko_path: "task-pinned active checkout/backend/src/marko"
    remote: "unknown for selected checkout"
    branch: "unknown for selected checkout"
    commit: "unknown for selected checkout"
  evidence_ledger_path: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/docs/HOSTILE_SELF_REVIEW_CLAIM_LEDGER_2026-07-17.yaml"
  previous_gate_result: "Stage 0 PASS; current matcher production eligibility BLOCKED"
  approved_business_decisions: []
  unresolved_business_decisions:
    - "No D1-D20 approval artifact supplied; external state unknown"
  source_access_states:
    - "prom_public_marketplace=NOT_PERMITTED; reference missing"
  review_scope_constraints:
    - "no implementation changes"
    - "no parser redesign"
    - "no pricing/matcher/schema/config/test changes"
    - "no calendar roadmap"
```

## 2. EXECUTIVE VERDICT

```text
report_review_gate = PASS
reviewed_stage_gate = NO_GO
material_claims = 44
report_defects_found = 8
report_corrections_applied = 8
real_blockers = 8
NO_GO_findings = 2
```

The corrected report is publishable as an evidence-backed Stage 0 audit. The current system
approach is still `NO_GO`: (1) Marko matching results bypass mandatory Metis
identity/comparability invariants, and (2) missing critical automotive/provenance data can
still produce an automatic price. Benchmark eligibility is additionally `BLOCKED` by absent
authority artifacts and labeled evidence.

Report-quality metrics:

```text
claim_traceability = 44 / 44 = 1.00
control_coverage = 15 / 15 = 1.00
defect_closure_rate = 8 / max(8, 1) = 1.00
unsupported_claim_rate = (44 - 35 - 8 - 1) / 44 = 0
critical_report_defects_open = 0
score_cap_violations = 0
```

The hostile control aggregate is `NO_GO`, because HR-10 and HR-11 are system-level `NO_GO`
findings. That aggregate determines `reviewed_stage_gate`; it does not invalidate the separate
`report_review_gate = PASS` after all report defects were closed.

## 3. REPOSITORY IDENTITY

| Identity | Input/physical path | Git identity | Review decision |
|---|---|---|---|
| Metis code in selected project | `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/metis` | inherited selected checkout: no Git root | authoritative for this target report because task workspace and report path pin it |
| Marko code in selected project | `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko` | inherited selected checkout: no Git root | authoritative for this target report |
| Existing scraper | `backend/src/marko/services/scraper_contract.py:445` plus `backend/src/marko/parsers/prom` | same selected checkout | verified bounded extraction component |
| Related Git checkout | `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/metis_alpha` | `main`, commit `9ea24b0f9bfd081215b16e7bfb0e7980b3c74f92`, remote `https://github.com/plenipotentiaryy/metis_alpha.git` | disclosed only; not substituted for selected copy |
| Related Marko subtree | `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/metis_alpha/marko` | same Git root/commit as above | disclosed; some matching files hash-identical, Metis/pricing additions are absent there |
| Related Metis subtree | `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/metis_alpha/metis` | same Git root/commit as above | disclosed; not used as evidence about selected copy |

Input identity is resolved: the user task, active workspace, and target-report location all
select the nested copy. Historical code lineage is not resolved because that copy has no
commit, branch, remote, or saved mapping to the related Git checkout. HR-13 therefore passes
for review-target identity while readiness retains a repository-lineage blocker.

Deterministic implementation-tree manifest used by this review:

```text
roots = backend/src, backend/tests, backend/migrations, frontend/lib,
        frontend/test, scripts
extra = backend/pyproject.toml, frontend/pubspec.yaml,
        frontend/analysis_options.yaml, .env.example
exclusions = __pycache__, *.pyc, *.pyo
files = 170
algorithm = SHA256(sorted(relative_path || NUL || file_SHA256 || LF))
fingerprint = 777d4e0620571556af2400685a6133798b321a49c295a669baca3d84e8977a90
```

## 4. CLAIM LEDGER SUMMARY

| Claim type | Total | Supported | Corrected | Contradicted | Blocked |
|---|---:|---:|---:|---:|---:|
| REPOSITORY_FACT | 25 | 20 | 5 | 0 | 0 |
| ENGINEERING_INFERENCE | 8 | 7 | 1 | 0 | 0 |
| ENGINEERING_ASSUMPTION | 3 | 2 | 1 | 0 | 0 |
| BUSINESS_DECISION | 1 | 0 | 0 | 0 | 1 |
| SOURCE_AUTHORITY_BLOCKER | 1 | 1 | 0 | 0 | 0 |
| FUTURE_HYPOTHESIS | 0 | 0 | 0 | 0 | 0 |
| EXTERNAL_RESEARCH_FACT | 1 | 1 | 0 | 0 | 0 |
| MEASURED_RESULT | 5 | 4 | 1 | 0 | 0 |
| **Total** | **44** | **35** | **8** | **0** | **1** |

The atomic ledger is saved at
`docs/HOSTILE_SELF_REVIEW_CLAIM_LEDGER_2026-07-17.yaml` (SHA-256
`e35d84d29ed048607c32f22770a5c930995b1c1df46f3843829e2aa2bad305e7`).

## 5. HOSTILE CONTROL MATRIX

| Control | Result | Main evidence | Defect | Correction | Residual risk |
|---|---|---|---|---|---|
| HR-01 README_IS_NOT_IMPLEMENTATION | PASS | Source symbols, schema, executed probes/tests | Overbroad `implemented/production` wording | Scoped to E2/E3 located path | No live E2E |
| HR-02 UNIT_TEST_IS_NOT_E2E | PASS | 323 backend + 21 Flutter tests; no live DB/queue | `full available` wording | Explicit E3 ceiling and analyzer failure | Cross-boundary behavior unverified |
| HR-03 MARKO_IS_NOT_METIS | PASS | Metis implementation plus Marko facade | Ownership stated as direct fact | Fact/inference split | Organizational authority still external |
| HR-04 EXISTING_SCRAPER_NOT_IGNORED | PASS | FrozenPromScraperAdapter and gateway located | None after review | Existing component preserved | Representative capacity not measured here |
| HR-05 NO_PARSER_REDESIGN_WITHOUT_REPRODUCIBLE_DEFECT | PASS | No parser fixture demonstrating required-output failure | Matching defects could be confused with parser defect | No redesign authorized or started | Parser production error rate unknown |
| HR-06 TECHNICAL_AND_SOURCE_STATES_SEPARATED | PASS | Technical E3 checks; NOT_PERMITTED source state | Production-path wording mixed states | Live path marked source-blocked | External permission absent |
| HR-07 ASSUMPTION_IS_NOT_BUSINESS_DECISION | PASS | D1-D20 artifact search; candidate reuse labels | Missing-side label and global D-state were invented | Reclassified as blocked/unknown | Domain contract absent |
| HR-08 AVERAGE_DOES_NOT_HIDE_CRITICAL_FLOOR | PASS | No readiness average in target; hard gates listed | None after review | Weighted score and floor remain null | Numeric readiness unavailable |
| HR-09 SCORE_IS_CAPPED_BY_EVIDENCE | PASS | No target readiness score; cap boundaries executed | None | V_score=0 | E3 cannot become E4 by test count |
| HR-10 REUSE_PRESERVES_METIS_INVARIANTS | **NO_GO** | Match -> observation -> pricing path; exact/missing-data probes | Current reuse bypasses INV-04/08/12 | Report marks current approach NO_GO; future reuse restricted | System code unchanged |
| HR-11 MISSING_DATA_CANNOT_CREATE_FALSE_RECOMMENDATION | **NO_GO** | Automatic `RAISE 920` with missing structured evidence | Critical missing data can create a price | Finding exposed; gate changed to NO_GO | System code unchanged |
| HR-12 RECOMMENDATION_IS_REPRODUCIBLE | PASS | Replay v1/v2 service/tests; missing commit/env/run fingerprint | Replay capability could be overstated | Claim limited to E3 partial traceability | E4 replay blocked |
| HR-13 CORRECT_PHYSICAL_REPOSITORY_VERIFIED | PASS | Workspace/report path agreement; all copies disclosed | Other copies initially omitted | Identity manifest added | Historical lineage unavailable |
| HR-14 NO_IMPLEMENTATION_CODE_STARTED | PASS | Allowed write paths and 170-file fingerprint | None | Docs/review artifacts only | Active checkout lacks Git diff |
| HR-15 NO_PREMATURE_CALENDAR_ROADMAP | PASS | Report and review contain no duration commitments | None | One next required part only | Scheduling intentionally not assessed |

Detailed control results:

```yaml
control_results:
  - control_id: HR-01
    applicable: true
    inspected_claims: [CLM-002, CLM-007, CLM-013, CLM-018, CLM-025, CLM-042]
    inspected_artifacts: ["backend/src", "backend/tests", "backend/migrations", "target report"]
    falsification_attempt: "Searched for narrative-only implementation claims and required a source symbol or executable result."
    evidence_found: ["matching.py", "models.py", "executed tests/probes"]
    counterevidence_found: ["no live E2E", "Flutter analyzer did not complete"]
    defects: ["production/full wording exceeded E2/E3 evidence"]
    corrections: ["scoped claims to located active-checkout path and E3 checks"]
    residual_risk: "live behavior remains unverified"
    status: PASS

  - control_id: HR-02
    applicable: true
    inspected_claims: [CLM-025, CLM-042]
    inspected_artifacts: ["backend tests", "frontend tests", "recommendation_replay.py"]
    falsification_attempt: "Looked for a saved cross-component run with DB, queue, inputs, outputs, failure path, and lineage."
    evidence_found: ["323 backend tests", "21 Flutter tests", "focused replay tests"]
    counterevidence_found: ["no live PostgreSQL/Redis/Celery", "no pinned commit"]
    defects: ["local test suite was described too broadly"]
    corrections: ["evidence ceiling fixed at E3"]
    residual_risk: "integration and operational behavior unknown"
    status: PASS

  - control_id: HR-03
    applicable: true
    inspected_claims: [CLM-023, CLM-031]
    inspected_artifacts: ["backend/src/metis/pricing", "backend/src/marko/pricing/__init__.py"]
    falsification_attempt: "Checked whether Marko contains an independent pricing-semantic implementation or replaces Metis."
    evidence_found: ["Marko facade re-exports Metis API", "engine located under metis.pricing"]
    counterevidence_found: ["module names alone do not grant organizational authority"]
    defects: ["ownership was mislabeled as direct repository fact"]
    corrections: ["implementation location is fact; ownership is inference"]
    residual_risk: "formal owner approval not supplied"
    status: PASS

  - control_id: HR-04
    applicable: true
    inspected_claims: [CLM-003, CLM-004, CLM-005, CLM-006]
    inspected_artifacts: ["scraper_contract.py", "prom/gateway.py", "market_collection.py"]
    falsification_attempt: "Searched for a newly invented parser/extractor path that bypassed the existing adapter."
    evidence_found: ["FrozenPromScraperAdapter", "versioned input/output and hashes"]
    counterevidence_found: ["no representative E4/E5 load run in this review"]
    defects: []
    corrections: ["existing component explicitly retained as bounded extraction"]
    residual_risk: "capacity and live compatibility are not proven by this Stage 0 report"
    status: PASS

  - control_id: HR-05
    applicable: true
    inspected_claims: [CLM-006, CLM-039]
    inspected_artifacts: ["prom parser/gateway", "matching.py", "probe inputs"]
    falsification_attempt: "Tried to attribute exact-ID and missing-data failures to parser internals."
    evidence_found: ["defects reproduce in matcher/pricing without parser execution"]
    counterevidence_found: ["no saved parser input/expected/actual fixture proving required-output failure"]
    defects: []
    corrections: ["no parser change or redesign authorization"]
    residual_risk: "absence of a located fixture is not proof of parser perfection"
    status: PASS

  - control_id: HR-06
    applicable: true
    inspected_claims: [CLM-037, CLM-042]
    inspected_artifacts: ["source_access.py", "core/config.py", ".env.example", "test outputs"]
    falsification_attempt: "Tested whether technical code/test success was used to infer source permission."
    evidence_found: ["NOT_PERMITTED default", "reference required", "fail-closed exception"]
    counterevidence_found: ["technical adapter/tests exist"]
    defects: ["live path was called production/executable without source qualifier"]
    corrections: ["technical E3 and source authority are now separate axes"]
    residual_risk: "permission authority remains external"
    status: PASS

  - control_id: HR-07
    applicable: true
    inspected_claims: [CLM-010, CLM-034, CLM-035, CLM-036, CLM-044]
    inspected_artifacts: ["target report candidate-integration section", "decision-artifact scan"]
    falsification_attempt: "Treated every unlabeled domain/reuse statement as unapproved until an authority artifact was located."
    evidence_found: ["no supplied D1-D20 authority artifact"]
    counterevidence_found: ["engineering candidates are plausible but not approved"]
    defects: ["one-sided missing side called a defect", "external D-state called unresolved globally"]
    corrections: ["behavior-only result", "external decision state unknown", "reuse remains assumption"]
    residual_risk: "domain semantics await owner approval"
    status: PASS

  - control_id: HR-08
    applicable: true
    inspected_claims: [CLM-026, CLM-027, CLM-028, CLM-033]
    inspected_artifacts: ["target report metrics and gates"]
    falsification_attempt: "Searched for an average/percentage that could hide a critical dimension."
    evidence_found: ["no numeric readiness vector is published"]
    counterevidence_found: ["critical system gates are NO_GO/BLOCKED"]
    defects: []
    corrections: ["weighted score and critical floor explicitly null; hard gates shown"]
    residual_risk: "no numeric readiness comparison can be made"
    status: PASS

  - control_id: HR-09
    applicable: true
    inspected_claims: [CLM-042]
    inspected_artifacts: ["target report", "evidence-cap boundary script"]
    falsification_attempt: "Injected E3=75.01 and E4=90.01 reported scores."
    evidence_found: ["both exceed their caps before correction", "target contains no readiness score"]
    counterevidence_found: []
    defects: []
    corrections: ["V_score remains zero"]
    residual_risk: "future scores must retain evidence level and critical floor"
    status: PASS

  - control_id: HR-10
    applicable: true
    inspected_claims: [CLM-014, CLM-027, CLM-031, CLM-032, CLM-034, CLM-040]
    inspected_artifacts: ["matching.py", "market_collection.py", "metis/pricing/engine.py", "reuse table"]
    falsification_attempt: "Tested exact conflicts and missing critical fields through the current Marko-to-Metis boundary."
    evidence_found: ["exact conflicts score 1.0", "accepted matches become observations", "automatic price 920"]
    counterevidence_found: ["pricing has several other hard rejections and can abstain on sample count"]
    defects: ["INV-04, INV-08, and INV-12 are violated by current production approach"]
    corrections: ["current approach marked NO_GO; future matching reuse limited to pattern/baseline or adapter"]
    residual_risk: "system implementation is unchanged by mandate"
    status: NO_GO

  - control_id: HR-11
    applicable: true
    inspected_claims: [CLM-011, CLM-015, CLM-024, CLM-040]
    inspected_artifacts: ["pricing types/engine", "market_collection._currency_code", "mutation outputs"]
    falsification_attempt: "Removed/unknowned OE, brand, condition, quantity, side, fitment, raw currency, provenance, seller identity, and tier/freshness fields."
    evidence_found: ["automatic RAISE without automotive fields", "unknown source passes at confidence 1", "blank seller IDs pass via names", "None currency becomes UAH"]
    counterevidence_found: ["empty/single/stale/unavailable/unknown-tier/low-confidence/conflict cohorts return null", "empty observation IDs force manual review"]
    defects: ["G_recommend can be 1 while mandatory comparability/provenance gates are absent"]
    corrections: ["false-recommendation path recorded and system gate set NO_GO"]
    residual_risk: "automatic false recommendation remains possible"
    status: NO_GO

  - control_id: HR-12
    applicable: true
    inspected_claims: [CLM-006, CLM-025, CLM-043]
    inspected_artifacts: ["recommendation_replay.py", "test_recommendation_replay.py", "pricing persistence models"]
    falsification_attempt: "Tried to build the required run fingerprint from commit, environment, policy, inputs, hashes, cohort, and seed."
    evidence_found: ["network-free replay v1/v2", "context/policy/cohort reconstruction", "exact comparator tests"]
    counterevidence_found: ["no active commit", "no environment fingerprint", "no matching config hash", "no live replay run"]
    defects: ["content hashing/replay wording was stronger than demonstrated"]
    corrections: ["status limited to partially_traceable/not_yet_E4_reproducible"]
    residual_risk: "production recommendation cannot be independently replayed from a complete manifest"
    status: PASS

  - control_id: HR-13
    applicable: true
    inspected_claims: [CLM-001, CLM-043]
    inspected_artifacts: ["filesystem paths", "Git metadata", "target report path", "related metis_alpha checkout"]
    falsification_attempt: "Enumerated other physical copies and checked whether selection depended on mtime, file count, or test success."
    evidence_found: ["workspace and target path pin same copy", "other copies disclosed"]
    counterevidence_found: ["selected copy lacks Git lineage"]
    defects: ["other copies and selection basis omitted"]
    corrections: ["repository identity manifest added"]
    residual_risk: "mapping to authoritative historical commit remains blocked"
    status: PASS

  - control_id: HR-14
    applicable: true
    inspected_claims: [CLM-043]
    inspected_artifacts: ["review write log", "170-file implementation-tree manifest"]
    falsification_attempt: "Checked every mutated path against the allowed docs-only set."
    evidence_found: ["only target report and HOSTILE_SELF_REVIEW artifacts changed"]
    counterevidence_found: ["no Git diff available in selected copy"]
    defects: []
    corrections: []
    residual_risk: "verification relies on frozen operation scope plus deterministic manifest, not Git history"
    status: PASS

  - control_id: HR-15
    applicable: true
    inspected_claims: [CLM-026, CLM-028, CLM-044]
    inspected_artifacts: ["target report", "hostile review"]
    falsification_attempt: "Searched for duration, deadline, week/month, or launch commitments unsupported by capacity and decisions."
    evidence_found: ["no calendar commitment"]
    counterevidence_found: []
    defects: []
    corrections: ["only one non-calendar next required part retained"]
    residual_risk: "none within review scope"
    status: PASS
```

Validation passes:

- Pass A, structural: all 17 output sections, 15 controls, claim types, evidence references,
  formulas, gate taxonomies, and YAML artifacts were checked; no placeholder remains.
- Pass B, semantic: every strong claim was treated as false until source/probe evidence was
  resolved; eight report defects were repaired.
- Pass C, numerical: evidence caps, null/empty behavior, queue stability boundaries, report
  metric denominators, and hard-gate aggregation were executed.
- Pass D, variation: all V-01 through V-20 were evaluated below.
- Pass E, mutation: all required hostile report mutations were detected by the mapped control.
- Repair pass R1: the complete corrected report was reread; no new editor-repairable material
  defect remained. System gaps and blockers were retained.

Hostile variation matrix:

| Variation | Review reaction | Result |
|---|---|---|
| V-01 README without implementation | HR-01 rejects implementation claim until source artifact exists | detected |
| V-02 unit tests without integration/E2E | evidence stays E3 | detected in current review |
| V-03 Marko full, Metis partial | Marko cannot replace Metis pricing semantics | detected |
| V-04 scraper asserted but artifact absent | preserve user assertion as unverified location, do not declare nonexistence | validator reaction verified; actual artifact was found |
| V-05 intermittent parser error without fixture | parser redesign remains forbidden | detected |
| V-06 technical scraper ready, source unknown/blocked | technical and authority states remain separate | detected in current review |
| V-07 engineering assumption written as client decision | reclassify and block pending authority | detected and repaired |
| V-08 average `90`, critical floor `20` | PASS forbidden | numerical branch verified |
| V-09 reported score `90`, evidence E3 | cap violation; corrected maximum `75` | numerical branch verified |
| V-10 Marko reuse bypasses abstention/invariants | production reuse rejected or adapter required | current HR-10 NO_GO |
| V-11 critical matching fields absent | expected price `null`; actual `RAISE 920` | current HR-11 NO_GO |
| V-12 recommendation lacks complete input snapshot/lineage | claim downgraded to partially traceable | detected |
| V-13 multiple physical copies | BLOCKED unless explicit input identity resolves selection | task/report pin resolved review input; lineage still blocked |
| V-14 source code changed during review | HR-14 would FAIL | mutation detected; actual source unchanged |
| V-15 calendar dates with unresolved decisions | calendar commitment removed/forbidden | no calendar commitment present |
| V-16 E4 success without failure path | E4 claim rejected | no E4 claim published |
| V-17 many E2 artifacts | evidence does not become E3/E4 | enforced |
| V-18 stale but otherwise complete data | freshness gate returns `null` price | executed and passed |
| V-19 exact OE with fitment conflict | comparability must fail; current contract cannot represent fitment | current approach NO_GO; domain label still authority-blocked |
| V-20 replay uses different evidence cohort | reproducibility fails and comparator must report mismatch | comparator contract/tests inspect evidence IDs; live E4 run absent |

Mutation review:

| Mutated report statement | Detecting control/result |
|---|---|
| `documented` → `implemented` | HR-01 rejects without source evidence |
| `unit-tested` → `end-to-end verified` | HR-02 rejects above E3 |
| remove `assumption` | HR-07 reclassifies/blocker |
| E3 score `75` → `76` | HR-09 records cap violation |
| remove critical floor | HR-08 forbids publishing the average |
| remove `null` on missing data | HR-11 detects unsafe output contract |
| move pricing ownership from Metis to Marko | HR-03 rejects replacement claim |
| remove parser defect fixture | HR-05 forbids redesign |
| replace selected physical path with a similar path | HR-13 blocks identity |
| add launch date without capacity/authority evidence | HR-15 rejects calendar roadmap |

## 6. SCORE AND FLOOR AUDIT

Evidence caps:

| Evidence | Cap |
|---|---:|
| E0 | 0 |
| E1 | 25 |
| E2 | 50 |
| E3 | 75 |
| E4 | 90 |
| E5 | 100 |

The target report contains no numerical readiness score or weighted dimension vector.
Therefore:

```yaml
score_audit:
  readiness_scores_found: 0
  score_cap_violations: 0
  weighted_score: null
  critical_floor: null
  null_reason: "No evidence-capped readiness dimension vector exists; inventing one is forbidden."
```

Numerical boundary tests:

| Boundary | Result |
|---|---|
| E3 reported score `75` | valid |
| E3 reported score `75.01` | pre-correction violation; capped to `75` |
| E4 reported score `90` | valid |
| E4 reported score `90.01` | pre-correction violation; capped to `90` |
| `C = lambda = 10` | unstable; drain time undefined |
| `C = 9.99 < lambda = 10` | unstable |
| `C = 10.01 > lambda = 10`, backlog `100` | stable; drain time `10000` seconds |
| `N_material = 0` | traceability undefined; PASS forbidden |
| `N_defects_found = 0` | closure formula returns `0 / 1 = 0`, not silent PASS |
| empty critical set | configuration error |
| missing critical automotive/provenance fields | expected null; actual `RAISE 920`; HR-11 NO_GO |

Critical hard gates:

| Critical dimension | Gate | Evidence |
|---|---|---|
| repository_identity | BLOCKED | input copy resolved, but no active commit/branch/remote or historical mapping |
| metis_invariant_preservation | NO_GO | exact identifiers and current Marko-to-Metis path bypass INV-04/08/12 |
| data_sufficiency | NO_GO | missing automotive/provenance fields can still produce price |
| recommendation_reproducibility | BLOCKED | E3 replay component exists; complete E4 manifest/run fingerprint does not |
| source_state_separation | PASS | technical and NOT_PERMITTED authority states are separate |
| scraper_boundary_preservation | PASS | existing adapter preserved; parser not redesigned |
| implementation_scope_compliance | PASS | docs/review-only changes |

`G_critical = 0`. No average or null numeric floor can override these hard gates.

## 7. METIS/MARKO BOUNDARY REVIEW

Direct fact: implementation is located under `metis.pricing`; `marko.pricing` re-exports it and
calls itself a compatibility facade. Engineering inference: Metis retains pricing semantics;
Marko supplies application/infrastructure reuse only through invariant-preserving boundaries.

| Reuse candidate | Source component | Target responsibility | Preserved invariants | Violated/unknown invariants | Adapter | Decision |
|---|---|---|---|---|---|---|
| Pricing kernel | `metis.pricing` | deterministic pricing semantics | INV-01, 05, 06, 09 | complete provenance/replay depends on caller | evidence/provenance adapter outside kernel | REUSE_AS_IS |
| Pricing compatibility facade | `marko.pricing` | legacy import compatibility | INV-01, 06 | none observed in facade | none while it stays a pure re-export | REUSE_AS_IS |
| Frozen Prom scraper adapter | `marko.services.scraper_contract` | bounded extraction | INV-07 partly, INV-11 | full candidate/rejection provenance and E4 replay unknown | capture every retrieved candidate/rank/hash without parser redesign | REUSE_WITH_ADAPTER |
| Current `match_offer` as production gate | `marko.services.matching` | identity/comparability admission | deterministic behavior only | INV-04, 05, 08, 12 | additive hard-gate/version/abstention wrapper would be required | DO_NOT_REUSE |
| Current `match_offer` as benchmark baseline | same | frozen legacy comparator | INV-11 unaffected | not production-safe | version/config-freezing adapter | REUSE_PATTERN_ONLY |
| Legacy `ProductMatch` | ORM schema | gold labels | none sufficient for gold provenance | INV-02, 08, 10 | replacement schema, not in-place semantic reuse | DO_NOT_REUSE |
| Recommendation replay service | `marko.services.recommendation_replay` | recomputation/compare pattern | INV-02, 09, 10 partly | commit, environment, matching config, raw hashes incomplete | complete manifest and run fingerprint | REUSE_WITH_ADAPTER |
| Workspace auth/job/review UI patterns | Marko app infrastructure | annotation/benchmark operations | potentially INV-02/07 | tenancy pooling, blindness, abstention unknown | dedicated benchmark authorization and blind annotation adapters | REUSE_PATTERN_ONLY |

The current production approach fails the multiplicative reuse condition because at least one
critical invariant value is `0`; unknown critical invariants are not treated as preserved.

## 8. SCRAPER BOUNDARY REVIEW

- Existing component status: located and retained as an extraction component.
- Artifact location:
  `backend/src/marko/services/scraper_contract.py:445` (`FrozenPromScraperAdapter`), with
  extraction implemented through `backend/src/marko/parsers/prom`.
- Black-box contract status: versioned input/output structures, canonical serialization,
  content hash, and failure taxonomy are present at E2/E3.
- Measurement status: scraper scaling/metrics code and tests are present and included in the
  323-test run; no representative E4/E5 capacity or live-source run was performed here.
- Parser-defect evidence: no saved parser input/expected/actual fixture was found that proves a
  parser-internal defect affecting this Stage 0 required output. Matching and missing-data
  defects reproduce without invoking parser internals.
- Redesign authorization: `false`.
- Parser redesign started: `false`.
- Source authority: live public Prom access remains `NOT_PERMITTED`; persisted replay and
  permitted client-supplied inputs are separate paths.

Conclusion: HR-04 and HR-05 pass. The scraper was neither ignored nor redesigned.

## 9. MISSING-DATA SAFETY REVIEW

The exact domain set `H` is not approved: D1-D3 have no supplied authority artifact. This
review therefore does not invent domain truth. It separately tests the prompt-required safety
dimensions and the hard gates actually implemented.

Implemented fail-closed gates:

- non-positive price;
- direct currency mismatch;
- unavailable or stale offer;
- used/owned offer;
- explicit severe conflict;
- low match/tier/source confidence;
- unknown tier;
- insufficient unique/clean/effective cohort;
- missing/duplicate evidence identity invariant at result validation.

Absent or bypassable critical gates:

- verified candidate OE/reference and cross-reference provenance;
- structured brand/manufacturer compatibility at exact-ID tier;
- fitment/vehicle/year/engine/body variant;
- side/position when one side is missing, and side conflicts at exact-ID tier;
- condition and package quantity/kit composition as hard structured fields;
- stable seller ID;
- verifiable source identity rather than a caller-supplied confidence number;
- raw currency presence (`None` becomes `UAH`);
- complete recommendation run fingerprint.

Mutation results:

| Variation | Actual result | Safety result |
|---|---|---|
| missing OE/reference, fitment, vehicle, years, engine, side, position, condition, quantity | `RAISE 920`, gates passed | NO_GO |
| missing brand as structured pricing field | field does not exist; `RAISE 920` | NO_GO pending domain contract |
| `source = unknown`, source confidence `1` | `RAISE 920` | NO_GO provenance path |
| blank stable seller IDs, unique names | `RAISE 920` | NO_GO stable-identity path |
| raw missing currency through runtime normalizer | becomes `UAH`; `RAISE 920` | NO_GO missingness masking |
| direct empty currency passed to engine | `INSUFFICIENT_DATA`, price `null` | implemented currency gate passes |
| empty cohort | `INSUFFICIENT_DATA`, price `null` | PASS |
| single observation | `INSUFFICIENT_DATA`, price `null` | PASS |
| unknown availability | `INSUFFICIENT_DATA`, price `null` | PASS |
| stale observations | `INSUFFICIENT_DATA`, price `null` | PASS |
| unknown pricing tier | `INSUFFICIENT_DATA`, price `null` | PASS |
| low source confidence | `INSUFFICIENT_DATA`, price `null` | PASS |
| severe classification conflict | `INSUFFICIENT_DATA`, price `null` | PASS |
| empty observation IDs | `MANUAL_REVIEW`, price `null`, duplicate-evidence invariant | PASS |

Manual review is therefore real for implemented cohort/identity invariants, but it is not a
substitute for absent identity/comparability/provenance gates. `G_recommend` can be nonzero in
a scenario where the hostile contract's `G_hard`, `G_comparability`, `G_provenance`, and
`G_reproducibility` should be zero. HR-11 is `NO_GO`.

## 10. REPRODUCIBILITY REVIEW

| Required element | Located state | Evidence level |
|---|---|---|
| Context input snapshot | `PricingRecommendation.context_snapshot` consumed by replay | E2/E3 |
| Observation/classification cohort | Reconstructed as of `calculated_at` | E3 component |
| Pricing policy/config | Loaded from pricing run | E3 component |
| Tier coefficients | Loaded for target category/OE | E3 component |
| Replay contract version | v1/v2 supported | E3 component |
| Output/reason/evidence comparison | Exact comparator with quantization | E3 component |
| Code commit | unavailable in selected checkout | missing |
| Working-tree/environment fingerprint | not stored per recommendation | missing |
| Matching policy/config hash | absent from comparison/recommendation manifest | missing |
| Raw and normalized evidence hashes | not complete in recommendation manifest | partial/missing |
| Retrieval candidate/rejection ranks | not persisted in structured comparison | missing |
| Deterministic run fingerprint | not implemented as required contract | missing |
| Live persisted recommendation replay | not executed in this review | missing E4 evidence |

Component-level tests show exact comparison and drift detection, but a unit/component test is
not a production replay. Correct status:

```text
recommendation_traceability = partial
recommendation_reproducibility = not_yet_E4_reproducible
run_fingerprint = NOT_AVAILABLE
```

HR-12 passes because the corrected report no longer claims complete reproducibility. The
readiness hard gate remains `BLOCKED`.

## 11. CORRECTION LOG

| Correction ID | Original claim | Defect | Corrected claim | Evidence | Impact |
|---|---|---|---|---|---|
| COR-001 | Nested copy named without other candidates | Incomplete identity | Task/report-pinned copy plus disclosed candidates | CLM-001 | HR-13 auditable |
| COR-002 | Current production eligibility BLOCKED | Deterministic invariant failures hidden by blockers | Current approach NO_GO; benchmark gate BLOCKED | CLM-027/039/040 | dual gates restored |
| COR-003 | Immutable/replayable evidence | Hash/docstring treated as E4 capability | Content-hashed/application-managed; full proof absent | CLM-006/021/034 | capability claim downgraded |
| COR-004 | Gold/split counts equal zero | Fabricated population counts | NOT_AVAILABLE; no local artifact, live DB unknown | CLM-022 | measurement integrity restored |
| COR-005 | Metis ownership as direct fact | Fact/inference mixed | implementation/facade fact; ownership inference | CLM-023/031 | boundary made explicit |
| COR-006 | Missing-side fixture is a confirmed defect at 0.833 | Unapproved domain decision and wrong fixture result | observed 0.875; label blocked pending authority | CLM-010/039/044 | invented semantics removed |
| COR-007 | Missing fields listed but not tested for automatic pricing | HR-11 path omitted | automatic `RAISE 920` and other mutations recorded | CLM-024/040 | system NO_GO exposed |
| COR-008 | Production/full/global D-state/replayable fingerprint wording | Scope/authority/evidence overclaim | active-checkout E2/E3 scope; external decisions unknown; original fingerprint non-replayable | CLM-037/042/043/044 | report becomes publishable |

Full correction artifact:
`docs/HOSTILE_SELF_REVIEW_CORRECTION_LOG_2026-07-17.md` (SHA-256
`03c5af019861e9e4b598618d35eaf9634d604c6139497f4c2f9c5e29ab8f8744`).

## 12. UNRESOLVED SYSTEM GAPS

These are not defects of the corrected report and were not remediated:

1. Exact `model_id` and SKU matches bypass brand/laterality conflicts.
2. Missing structured automotive identity/comparability fields can still yield an automatic
   price.
3. Unknown source and blank stable seller IDs can still yield an automatic price when numeric
   confidence is high.
4. Missing raw currency is converted to UAH.
5. Pairwise negative, hard conflict, insufficient evidence, and uncertainty collapse into
   `None`.
6. Matcher policy/version/config hash is not persisted with comparison output.
7. Retrieval ranks and rejected candidates are absent from structured evidence.
8. No approved local identity/comparability/annotation/release contract is available.
9. No compliant labeled gold set, split manifest, evaluation runner, or confidence-bound report
   was found in the audited checkout.
10. Full recommendation run fingerprints and E4 replay evidence are absent.
11. Live public source access is fail-closed at `NOT_PERMITTED`.
12. Live DB/queue/worker and representative load behavior were not validated.
13. Flutter analyzer exits before diagnostics.

## 13. BLOCKERS

```yaml
blockers:
  - blocker_id: BLK-HSR-001
    type: business_decision
    blocked_claims: ["approved identity ontology", "approved comparability ontology", "hard-field set H"]
    owner: "product/risk owner plus automotive domain authority"
    resolution_condition: "Supply an authoritative D1-D3 decision artifact."
    fabrication_forbidden: true

  - blocker_id: BLK-HSR-002
    type: authority
    blocked_claims: ["annotation roles", "adjudication authority", "double-label scope", "budget"]
    owner: "project owner"
    resolution_condition: "Supply authoritative D4-D8 decisions and named roles."
    fabrication_forbidden: true

  - blocker_id: BLK-HSR-003
    type: data
    blocked_claims: ["gold metrics", "Recall@K", "precision/recall bounds", "slice results"]
    owner: "data/annotation owner"
    resolution_condition: "Create a compliant, versioned, authority-approved labeled dataset after ontology approval."
    fabrication_forbidden: true

  - blocker_id: BLK-HSR-004
    type: access
    blocked_claims: ["live public Prom sampling", "production-like refresh"]
    owner: "source/legal/business authority"
    resolution_condition: "Record a permitted verdict and auditable reference, or use permitted supplied/persisted evidence."
    fabrication_forbidden: true

  - blocker_id: BLK-HSR-005
    type: repository_identity
    blocked_claims: ["active code commit", "historical lineage", "complete run fingerprint"]
    owner: "repository maintainer"
    resolution_condition: "Map the selected physical copy to an authoritative commit and preserve working-tree identity."
    fabrication_forbidden: true

  - blocker_id: BLK-HSR-006
    type: business_decision
    blocked_claims: ["release thresholds", "confidence level", "minimum slice sizes", "review capacity"]
    owner: "product/risk owner"
    resolution_condition: "Supply authoritative D9-D20 policy artifacts."
    fabrication_forbidden: true

  - blocker_id: BLK-HSR-007
    type: access
    blocked_claims: ["E4 DB/queue/worker validation", "tenant isolation integration", "failure recovery"]
    owner: "platform/deployment owner"
    resolution_condition: "Provide a disposable PostgreSQL/Redis/Celery integration environment with saved inputs/outputs."
    fabrication_forbidden: true

  - blocker_id: BLK-HSR-008
    type: artifact
    blocked_claims: ["Flutter static-analysis result"]
    owner: "frontend/toolchain maintainer"
    resolution_condition: "Repair the analysis-server LSP truncation and rerun flutter analyze to diagnostics."
    fabrication_forbidden: true
```

## 14. FINAL GATES

```yaml
final_gates:
  report_review_gate: PASS
  reviewed_stage_gate: NO_GO
  hostile_control_aggregate: NO_GO
  stage_0_audit_completion: PASS
  benchmark_production_gate: BLOCKED
  production_readiness_proven: false
  implementation_started: false
  calendar_roadmap_generated: false
```

`report_review_gate = PASS` means the corrected report is truthful, scoped, traceable, and has
no open report defect. `reviewed_stage_gate = NO_GO` means the current implementation approach
violates mandatory invariants in its present form. Neither gate authorizes production use or
Stage 1 implementation.

## 15. STRUCTURED RESULT OF CURRENT STAGE

Established:

- 44 material claims are typed and traced;
- all HR-01 through HR-15 were executed;
- exact-conflict and missing-data false-recommendation paths are deterministic at E3;
- existing scraper and Metis/Marko boundaries are located;
- technical readiness and source authority are separate;
- current approach has two system-level NO_GO controls.

Corrected:

- 8 report defects were closed in one repair iteration;
- physical-copy scope, dual gates, evidence levels, counts, ownership labels, missing-side
  semantics, missing-data behavior, and fingerprint limitations are now explicit.

Still unknown:

- external D1-D20 approval state;
- live-database contents;
- production prevalence, precision, recall, and unseen/slice behavior;
- active-copy historical commit;
- E4 replay/integration and E5 operational readiness.

Claims downgraded:

- current production eligibility: `BLOCKED` → current approach `NO_GO`, benchmark gate
  separately `BLOCKED`;
- immutable/replayable → content-hashed/application-managed, proof incomplete;
- global nonexistence/zero counts → no local artifact/`NOT_AVAILABLE`;
- direct ownership fact → repository fact plus engineering inference;
- missing-side confirmed defect → observed behavior pending domain decision;
- full/production path → located E2/E3 path with source/live limitations.

Current gate meaning: the Stage 0 audit and hostile report review are complete, but the current
matching-to-pricing approach must not be represented as production eligible.

## 16. FOUND BLOCKERS

- `BLK-HSR-001`: no authoritative D1-D3 identity/comparability/hard-field contract.
- `BLK-HSR-002`: no supplied D4-D8 annotation authority/budget artifact.
- `BLK-HSR-003`: no compliant labeled gold/benchmark data.
- `BLK-HSR-004`: live Prom source state is `NOT_PERMITTED` without reference.
- `BLK-HSR-005`: selected checkout has no historical Git identity.
- `BLK-HSR-006`: no supplied D9-D20 release-policy artifact.
- `BLK-HSR-007`: no disposable E4 PostgreSQL/Redis/Celery integration environment.
- `BLK-HSR-008`: Flutter analysis server fails before diagnostics.

## 17. NEXT REQUIRED PART

Следующая необходимая часть: получить authoritative D1-D3 artifact, который определяет
product identity, pricing comparability и обязательный hard-field set `H`; до этого не начинать
implementation следующего этапа.

Stop-gate reached. No next stage, implementation, or calendar roadmap was started.
