# Metis limited Prom validation authority — 30 OE

## Authority basis

On 2026-07-19 the project owner explicitly instructed Codex to implement
`/Users/leonidpofa/Downloads/METIS_NEXT_STEPS.md`. Block 0 of that instruction
requires a live Prom.ua parser run for 30 distinct OE values from Yuri's catalog.

This file records the scope-specific internal authorization reference required by
the fail-closed Marko source-access boundary. It does not claim or replace any
permission that Prom.ua terms, applicable law, or another external policy may
require.

## Permitted scope

- source: publicly accessible Prom.ua product and search pages;
- purpose: discovery and validation of OE coverage, used/KEMP exclusion, brand
  recognition, calibration support and parser-to-engine evidence;
- catalog: Yuri's supplied 4,901-row Prom.ua export;
- maximum targets: 30 distinct OE values;
- sampling: 6 radiator, 6 shock-absorber, 6 electrical, 6 gasket and 6 filter
  targets selected deterministically from the catalog;
- maximum search depth: 2 result pages per OE;
- maximum retained sellers per OE: 50;
- minimum configured request delay: 1 second;
- allowed operations: read public pages, store local content-addressed evidence,
  parse, classify, aggregate and replay offline;
- prohibited operations: authentication bypass, anti-bot bypass, CAPTCHA bypass,
  account access, price writeback, listing modification, Autopro access, unrelated
  crawling and production continuous collection.

## Stop conditions

Collection stops when any of the following occurs:

1. 30 distinct OE targets have been attempted;
2. the source returns an explicit access denial, CAPTCHA or blocking response;
3. the bounded error/circuit policy stops the run;
4. the task owner revokes the instruction.

The authorization expires when this bounded validation run finishes. Any retry
beyond failed bounded attempts, larger sample, full 4,901-target run or production
collection requires a new scope-specific instruction and authority reference.
