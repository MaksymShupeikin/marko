# Semantic Prom discovery for KEMP rows without OE

This isolated experiment implements the second path requested for KEMP catalog
rows that have no confirmed OE number:

See [`RESULTS.md`](RESULTS.md) for the measured 2026-08-09 whole-catalog audit,
live Prom pilot and final Luna xhigh outcome.

```text
KEMP workbook row
  -> original KEMP card text, characteristics and images
  -> descriptive Prom query without internal/MPN/unconfirmed numbers
  -> frozen raw search/detail responses
  -> deterministic semantic hard rejects
  -> Luna gpt-5.6-luna/xhigh with frozen images
  -> MATCH / NOT_MATCH / MANUAL_REVIEW
  -> manual-review candidate only
```

It does **not** update the identity graph, infer an OE number, write a price,
change a recommendation, write to the database, or admit anything to automatic
pricing.  Luna `MATCH` is mapped to
`SEMANTIC_MATCH_CANDIDATE_MANUAL_REVIEW`, not to product identity.

## Inputs

- `../OE_каталог_2026-08-09.xlsx`, sheet `Импорт`;
- `backend/data/kemp_prom_catalog.xlsx`, sheet `Export Products Sheet`.

The join key is the Prom card ID: master column `Артикул` to source
column `Унікальний_ідентифікатор`.  The loader refuses duplicate or missing
keys.

## Safety boundaries

- Live collection is off unless `--live` is supplied and Marko's existing
  `source_access` gate is currently permitted.
- At most 20 seeds, three query variants per seed, two search pages, five
  detail cards per query, and five Luna calls are accepted by the CLI.
- Queries are generated only from descriptive card evidence.  Internal codes,
  MPN, and `Кандидаты (не подтверждены)` are stripped and checked
  again before collection.
- The Luna text snapshot removes the KEMP internal/source catalog codes and
  unconfirmed candidates, plus candidate SKU/MPN/OE/part-number fields and
  Prom OE-grouping numbers. Semantic descriptions, fitment, non-identifier
  characteristics and frozen images remain. Raw evidence is never rewritten.
- Owned KEMP seller IDs are excluded from the independent market.
- HTTP 403/429, CAPTCHA/challenge, or source-access denial stops further live
  collection.  The response trace already obtained is retained.
- Raw HTML is stored separately before verdicting, together with URL, status,
  timestamp and SHA-256.
- Structured candidates and Luna input omit monetary fields and redact obvious
  currency amounts in prose.  Raw source HTML can naturally contain a price;
  those bytes are evidence and are never sent to Luna.
- Images are accepted only from Prom image hosts, downloaded once without a
  retry loop, size bounded, hashed, and attached from local frozen files.
- The Codex CLI invocation is `gpt-5.6-luna`, `xhigh`, `read-only`, `ephemeral`,
  with `OPENAI_API_KEY` explicitly removed from the child environment.
- The server builds a snapshot-bound evidence catalog. Luna may return only
  its short `evidence_id` values; each ID is bound to an exact source path and
  value SHA-256. A schema-valid answer still fails if an ID is absent/moved or
  diagnostic image use lacks the image content-hash evidence ID. One bounded
  repair call may correct formatting/evidence selection only; a second failure
  stays `LUNA_FAILED`.

## Run tests

```bash
cd backend
PYTHONPATH=src .venv/bin/python -m pytest -q \
  ../experiments/semantic_discovery_without_oe/test_semantic_discovery.py
```

## Profile/query-plan only (no network, no Luna)

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  experiments/semantic_discovery_without_oe/run_pilot.py \
  --row-id 1153724243
```

## Audit query planning over every no-OE row (no network, no Luna)

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  experiments/semantic_discovery_without_oe/audit_catalog.py \
  --output .artifacts/semantic_discovery_without_oe_catalog_audit.json
```

## Frozen measurement gate

The checked-in experimental fixture
`fixtures/stratified_sample_2026-08-09.json` freezes 80 of the 1,617 no-OE
rows using deterministic category/part-family round-robin sampling. It contains
46 categories, 43 part families, four live batches of 20, and forces the two
untyped rows `1230665005` and `2179741467` into the sample.

File SHA-256:
`351446c1d99c1beeda28084596a9c38c02f597744c36292d539c0f9965e84e23`.

Rebuild the selection into a new output (the CLI refuses overwrite):

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  experiments/semantic_discovery_without_oe/evaluation_cli.py freeze \
  --sample-size 80 \
  --selection-seed semantic-discovery-gate-2026-08-09-v1 \
  --output /tmp/semantic-discovery-stratified-sample-replay.json
```

After the customer has explicitly authorized and run all four bounded live
batches, build prediction-blind human label files. At least one independently
known canary is mandatory, and its answer key must be outside the human-review
folder:

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  experiments/semantic_discovery_without_oe/evaluation_cli.py prepare-labels \
  --sample experiments/semantic_discovery_without_oe/fixtures/stratified_sample_2026-08-09.json \
  --run-dir .artifacts/semantic-gate/batch-01 \
  --run-dir .artifacts/semantic-gate/batch-02 \
  --run-dir .artifacts/semantic-gate/batch-03 \
  --run-dir .artifacts/semantic-gate/batch-04 \
  --canary-source-csv /secure/semantic_canaries.csv \
  --seed-labels-out .artifacts/semantic-gate/review/seed_labels.csv \
  --candidate-labels-out .artifacts/semantic-gate/review/candidate_labels.csv \
  --system-predictions-out .artifacts/semantic-gate/system_predictions.json \
  --canary-key-out .artifacts/semantic-gate/secure-key/key.json \
  --manifest-out .artifacts/semantic-gate/review/manifest.json
```

Keep `system_predictions.json` and the canary key hidden until human labelling
is complete. Edit only the documented human label fields: every seed and
candidate evidence row carries an independently recomputed `evidence_sha256`,
and any evidence edit makes the measurement incomplete. `prepare-labels`
requires an exact non-overlapping partition of all 80 frozen seeds across live,
Luna-enabled runs whose status is exactly `COMPLETED`; partial/profile-only or
error-bearing runs are rejected. Then compute retrieval recall,
deterministic-rejection precision and false rejects, Luna false
accepts/abstention, detail/candidate-image availability (the seed image does
not count), independent-seller coverage, and HTTP/Luna/runtime budgets:

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  experiments/semantic_discovery_without_oe/evaluation_cli.py evaluate \
  --sample experiments/semantic_discovery_without_oe/fixtures/stratified_sample_2026-08-09.json \
  --seed-labels .artifacts/semantic-gate/review/seed_labels.csv \
  --candidate-labels .artifacts/semantic-gate/review/candidate_labels.csv \
  --system-predictions .artifacts/semantic-gate/system_predictions.json \
  --canary-key .artifacts/semantic-gate/secure-key/key.json \
  --label-manifest .artifacts/semantic-gate/review/manifest.json \
  --output .artifacts/semantic-gate/evaluation.json
```

Canaries are excluded from model metrics. A failed canary makes the measurement
incomplete. Before scoring, the evaluator verifies the frozen sample, system
predictions, and canary-key hashes against the label manifest; editable human
CSV fields remain protected by row-level evidence hashes. Any critical Luna
false accept forces `LEAVE_AS_MANUAL_TOOL`; all paths continue to report zero
automatic identity and pricing admissions.

## One bounded live pilot with one Luna review

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  experiments/semantic_discovery_without_oe/run_pilot.py \
  --row-id 1153724243 \
  --live \
  --run-luna \
  --queries-per-seed 1 \
  --max-search-pages 1 \
  --max-detail-cards 3 \
  --max-luna-pairs 1
```

The output directory contains profiles, query plans, raw pages, HTTP manifest,
non-monetary candidate cards, deterministic matrices/verdicts, frozen images,
strict Luna schema/input/output, summary, report, and a SHA-256 artifact
manifest.  A new timestamped directory is used by default; the CLI refuses to
overwrite a non-empty directory.

## What a real coverage claim still requires

This pilot establishes mechanics, provenance and fail-closed behavior.  It
does not establish representative precision or recall.  Before using this as
catalog coverage, manually label a category-stratified sample and measure at
least: retrieval recall, critical false accepts, deterministic rejection
precision, Luna abstention, image availability, independent-seller coverage,
and per-category results.  Any critical false accept must keep automatic
admission at zero until the relevant rule and replay test are corrected.

Until that gate is completed, this directory should remain an isolated
experiment/manual-review tool rather than being integrated into production
identity or pricing.
