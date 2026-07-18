# HOSTILE SELF-REVIEW — CORRECTION LOG

Target report:
`/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/docs/METIS_MATCHING_GOLD_SET_STAGE_0_AUDIT_2026-07-17.md`

Baseline SHA-256:
`323896819162ee2065a0ac85d03422a6edf63ec0410aeeb1ccdcd5c9a40e68f5`

Corrected SHA-256:
`e34bdd9e8feb6d2c46c9b1096d349428df5f6b65bdd978f608c8c50f50396530`

Repair iterations: `1` of maximum `3`. A complete second review pass found no remaining
editorially repairable material defect. System gaps were not changed.

| Correction ID | Original claim | Defect | Corrected claim | Evidence | Impact |
|---|---|---|---|---|---|
| COR-001 | Active code is in the nested copy. | Other physical copies and the selection basis were omitted; historical lineage could be confused with input identity. | The task workspace and target-report path pin the nested copy; three other candidates are disclosed and not substituted; active commit/remote remain unavailable. | Filesystem identity checks; Git metadata inspection; CLM-001. | HR-13 input identity becomes auditable; lineage blocker remains. |
| COR-002 | `CURRENT_MATCHER_PRODUCTION_ELIGIBILITY = BLOCKED`. | Missing benchmark evidence hid deterministic mandatory-invariant violations. | Current implementation approach is `NO_GO`; the separate benchmark production gate is `BLOCKED`; Stage 0 audit completion remains `PASS`. | Exact conflict probes and missing-data pricing probe; CLM-027, CLM-028, CLM-039, CLM-040. | Restores dual-gate semantics without claiming production readiness. |
| COR-003 | Raw/snapshot evidence was described as immutable and replayable. | Content hashes, docstrings, and application persistence do not prove database immutability or exact candidate reconstruction. | Evidence is content-hashed/application-managed; schema-level immutability and gold-grade replay are unproven; reuse is conditional. | Models and market collection assignment paths; CLM-006, CLM-021, CLM-034. | Removes E4-style capability overclaim; preserves later reuse candidate. |
| COR-004 | Gold and split counts were all `0`; gold/benchmark were `NOT_CREATED`. | Artifact absence and an uninspected live database do not establish a zero population or global nonexistence. | Artifacts are `NOT_FOUND_IN_AUDITED_CHECKOUT`; all counts are `NOT_AVAILABLE`; live-database state is unknown. | Scoped file/schema scan and no live DB access; CLM-022. | Prevents fabricated measurements and unsupported global claims. |
| COR-005 | `metis.pricing` ownership was stated as a direct repository fact. | Module placement and a facade docstring directly prove implementation location, not organizational authority by themselves. | Source location/facade role is a repository fact; Metis pricing ownership is an explicit engineering inference. | `marko/pricing/__init__.py`, `metis/pricing/__init__.py`; CLM-023, CLM-031. | Separates fact from inference while preserving the intended boundary. |
| COR-006 | One-sided missing laterality was labeled a failed safety contract. | The report converted an unapproved proposed ontology into a confirmed defect and reported the wrong fixture/score. | The observed fuzzy result is `0.875`; its desired label is `BLOCKED_PENDING_DOMAIN_DECISION`; exact opposite-side fixture still rejects. | Two deterministic matcher probes; CLM-010, CLM-039, CLM-044. | Removes a fabricated business decision; retains reproducible behavior. |
| COR-007 | Missing comparability fields were listed as gaps but not tested against automatic pricing. | The report did not establish whether missing critical evidence could create a price and therefore understated the system gate. | Five fixed KEMP offers produced `RAISE` at `920` without structured automotive fields; unknown source and blank stable seller IDs also allowed a price; implemented sample/freshness/tier gates still fail closed. | Missing-data mutation matrix; CLM-024, CLM-040. | Establishes HR-11 `NO_GO` and the false-recommendation path. |
| COR-008 | The report used `production`, `full`, globally unresolved D1-D20, and a replayable-looking source fingerprint too broadly. | E2/E3 evidence was presented with live/E2E scope; external decision state and the fingerprint file set were not available. | Claims are scoped to the located active checkout; live execution is source-blocked; D1-D20 have no local approval artifact and external state is unknown; the original fingerprint is marked non-reconstructible. | Source-access gate, test reruns, repository scan, and missing original file-set manifest; CLM-037, CLM-042, CLM-043, CLM-044. | Eliminates scope, authority, and reproducibility overclaims. |

No correction changed matcher, parser, pricing, source policy, models, migrations, API, workers,
configuration, tests, database state, or frontend behavior.
