# Metis bounded Prom authority — additional 54 review listings

## Authority basis

On 2026-07-19 the project owner explicitly instructed Codex to implement
`/Users/leonidpofa/Downloads/METIS_ACTION_PLAN.md`. Step 2 of that plan directs
the existing parser to collect the next OE sample so the real review workbook
contains 200 source listings instead of 146.

This record is the scope-specific internal authority reference required by the
fail-closed Marko source-access boundary. It does not replace Prom.ua terms,
applicable law, or any external policy that may apply.

## Permitted scope

- source: publicly accessible Prom.ua product and search pages;
- purpose: obtain at least 54 additional source listings for the 200-row human
  tier/comparability review workbook;
- catalog: Yuri's supplied 4,901-row Prom.ua export;
- targets: a deterministic follow-on sample excluding the first 30 OE targets;
- maximum attempted targets: 30 distinct additional OE values;
- stop as soon as at least 54 seller-deduplicated additional listings have been
  stored, unless completing the current single target is necessary;
- category sampling: radiator, shock absorber, electrical, gasket, and filter;
- maximum search depth: 2 result pages per OE;
- maximum retained sellers per OE: 50;
- minimum configured request delay: 1 second;
- allowed operations: read public pages, store bounded local evidence, parse,
  aggregate, and prepare an unlabelled human-review workbook;
- prohibited operations: authentication or anti-bot bypass, CAPTCHA bypass,
  account access, price writeback, listing modification, description-cross
  expansion, Autopro access, full 4,901-target collection, and continuous
  production collection.

## Stop conditions

Collection stops when any of the following occurs:

1. at least 54 additional seller-deduplicated listings have been stored;
2. 30 additional OE targets have been attempted;
3. Prom.ua returns an explicit access denial, CAPTCHA, or blocking response;
4. the bounded circuit/error policy stops the run;
5. the task owner revokes the instruction.

The authority expires when this bounded top-up run finishes. It does not
authorize cross-number collection, calibration, a 100–200 product recommendation
E2E, or the 4,901-row live run.
