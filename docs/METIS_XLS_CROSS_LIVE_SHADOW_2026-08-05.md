# METIS XLS-cross live shadow — 2026-08-05

## Verdict

The customer XLS identity spine now produces live, externally sold Prom
candidates that survive the deterministic identity and semantic boundaries.
This is a positive controlled-pilot result, not a production-accuracy claim.

The final bounded replay used `oe-extractor-v4` and
`semantic-features-v23`. The post-replay hardening reached
`semantic-features-v40-damaged-condition`; v27 added the seed-asserted analogue gate, v28 added
explicit inner/outer CV-joint and thermostat-housing distinctions, and v29
adds explicit fuel-type, upper/lower installation, brake-disc diameter, and
power-steering-reservoir-cap contradictions. v30 adds explicit component
boundaries for radiator caps, wheel-hub flanges, alternator regulators, water
pump impellers, A/C compressor clutches, oil-filter housings, timing kits, ABS
rings, headlamp housings, door-handle mechanisms, and brake-disc versus pad
titles. v31 adds the remaining high-confidence boundaries for wheel bearings,
injector repair kits, air-filter housings, and engine-mount brackets. v32 adds
explicit with/without motor variants for window regulators and with/without
brake-wear-sensor variants for brake pads. v33 adds explicit package
boundaries for drum-brake repair kits versus adjusters, A/C condensers with
versus without a drier, steering racks with versus without tie rods, and
calipers with versus without a bracket. v34 prevents a hub title's parenthetical
bearing dimensions from being reclassified as a standalone bearing. v35
extends the admission boundary to exact-OE offers: explicitly asserted
sellable configuration (subtype, assembly, side/position, pins and package
components) must still be confirmed by the candidate, while physical geometry
remains an analogue/category requirement. v36 makes the same gate symmetric:
candidate-only sellable assertions also require a matching seed fact before
pricing. Its changes are covered by targeted
regressions and a regenerated semantic smoke artifact below. The replay
made no database write and ignored all monetary fields.
v37 additionally preserves Prom/XLS package quantity and unit-basis labels;
the persisted pricing path holds a candidate for manual review until those
facts (and, for cross-OE paths, the required category-specific dimensions)
are explicitly comparable. The current persisted semantic admission contract
is `semantic-pricing-gate-v8-ambiguous-sellable-values`: multi-valued sellable
assertions and authoritative-but-untyped cards remain discovery-visible but
cannot enter pricing evidence.

## Scope

- 20 confirmed XLS cross pairs selected across 19 catalogue categories;
- one Prom search page per cross number;
- at most three product-detail requests per query;
- owned sellers `2847093`, `3325174`, `3912822`, and `4015921` excluded from
  the detail shortlist and evaluation;
- source access admitted only for this bounded replay as
  `PERMITTED_LIMITED`, reference
  `user-explicit-bounded-live-shadow-2026-08-05`;
- no recommendation, calibration, price, migration, or production database
  mutation.

## Final measurements

| Metric | Result |
|---|---:|
| Queries completed | 20/20 |
| Prom search rows | 430 |
| External candidates evaluated | 341 |
| Successful detail cards | 50 |
| `VERIFIED_CROSS` candidates | 30 |
| `VERIFIED_CROSS` retained after semantic hard stops | 27 |
| Queries with at least one retained true cross | 14/20 |
| Retained true-cross seller observations, summed per query | 26 |
| Queries with at least three retained cross sellers | 3/20 |
| All identity-retained candidates, including exact seed numbers | 37 |
| Queries with any retained candidate | 16/20 |
| Semantic hard-stop candidates | 50 |

The ten retained `VERIFIED_EXACT` rows found under cross-number searches are
valid candidates, but they are not counted as evidence that the cross itself
retrieved a different article. True cross coverage is therefore 14/20 rather
than 16/20.

Retained true-cross examples include:

- `1300152 -> 63254A`: two independent Opel radiator sellers;
- `0384J9 -> 0384N6`: two independently sold intercoolers, with supplier
  articles `DAC006TT` and `30192` separated from their compatible OE lists;
- `64320A -> PCC500630`: a Land Rover intercooler candidate;
- `66864 -> CV618005DE`: a candidate-native Ford radiator code retained while
  its compatible OE list remains auditable;
- `9015010701 -> 2D0145805`: a Volkswagen LT35 intercooler;
- `7E0905865 -> 6R0905865`: five listings across four sellers for the same
  ignition contact-group family;
- `6N0412249C -> 1K0412249`: a VAG strut top-mount bearing;
- `0024205483 -> 2D0615424C`: a Mercedes/VW brake-caliper candidate;
- `VOES0510 -> 6X0422812`: three steering tie-rod-end candidates;
- `314042 -> 54302JY01B`: two right-front Nissan/Renault shock-absorber
  listings.

The detail-native boundary also recovered `863130 -> 02090F`: the retained
Elring gasket card names `02090F` as its own verified Prom Motors part code,
while other compatible references remain visible without making that native
code ambiguous.

The final hard stops among otherwise verified candidates are materially
correct on the saved evidence:

- a complete Daewoo Nexia radiator versus a radiator tank/component;
- a right-front shock absorber versus a left-front shock absorber.

## Accuracy defects found and fixed

### 1. Fictitious concatenated public identifiers

The initial source plan exposed values such as
`037103493AK037103211`, `1K09058511K0905865`, `AUDI4F0260403E`, and
`OPEL1850062`. They came from multiple numbers separated by `+` or whitespace,
and from editorial manufacturer labels in catalogue characteristics.

The XLS boundary now:

- treats `+` as a number separator;
- splits adjacent complete identifiers;
- strips editorial leading labels without damaging formatted identifiers such
  as `7E5 827 505 A`;
- routes own-export characteristics through the same tested number tokenizer;
- preserves private `776...` codes only as join keys and never as public
  crosses.

The usable confirmed-pair pool fell from 1,613 to 1,554. The removed 59 pairs
were not lost market coverage; they were malformed or non-informative identity
nodes that could create useless searches or false graph joins.

### 2. Top-mount bearing misclassified as a shock absorber

`Підшипник амортизатора` previously matched the generic shock-absorber rule
before the bearing rule and caused a false hard stop. A specific top-mount
bearing rule now precedes the generic absorber rule. The real live candidate
`VAG 1K0412249 Підшипник амортизатора` is retained.

### 3. Structured radiator axes compared incorrectly

Prom detail cards may provide length, width, and depth as separate
characteristics. The old extractor kept one scalar such as `270` and compared
it against `680x278`, creating a false conflict.

v22 now:

- recognizes Ukrainian and Russian length/width/depth labels;
- normalizes scalar millimetre values;
- assembles multiple axis-labelled scalars into one geometry vector;
- treats a lone anonymous axis against full geometry as `UNKNOWN`;
- excludes parcel/package dimensions from part geometry.

The live `63254A` radiator with `680 x 270 x 23` now correctly remains
compatible with the seed's `680 x 278` under the bounded radiator tolerance.

### 4. Candidate-native detail code drowned by compatible references

A provenance-verified Prom Motors `normalizedPartCode` could previously become
`AMBIGUOUS` merely because the same card also listed several compatible OE
references. The verifier now lets exactly one detail-native code bind an
already confirmed one-hop XLS cross. It does not grant this precedence to a
title, SKU, MPN, unretained detail metadata, or unconfirmed cross; a conflicting
exact query or another native detail code still stops verification.

This narrow change increased retained true-cross coverage from 5/20 to 7/20
on the same query set, without weakening the radiator-tank or left/right hard
stops.

### 5. Multiple structured OE values were concatenated

Some Prom cards publish several complete identifiers separated by `+`, a line
break, or plain whitespace. The candidate evidence boundary could normalize
the entire field into one fictitious code such as
`06A121031C06B121011H06B121019D`. It now splits adjacent complete identifiers
while preserving formatted multi-token numbers such as `A 000 090 26 51`.
This change did not loosen any final live admission metric; it removes false
conflict/noise nodes from retained evidence and makes later review auditable.

### 6. Compatible-reference lists were treated as conflicting identities

Prom cards often place one candidate identity beside a list of explicitly
compatible OE or cross references. Previously, every number in that list was
treated as if the seller claimed several mutually exclusive identities, so a
valid exact seed or confirmed one-hop cross became `AMBIGUOUS`.

The verifier now gives this field an explicit
`COMPATIBLE_REFERENCE_LIST` provenance. An exact seed number, or exactly one
confirmed one-hop XLS cross, may bind identity while the other compatible
references remain reviewable evidence. Candidate-native SKU, MPN, and detail
part code remain separate namespaces. A conflicting ordinary `oe_raw` value,
an unconfirmed cross, or more than one incompatible native code still blocks
admission.

This change lifted retained true-cross query coverage from 7/20 to 10/20 on the
same fixed set before the verified platform-compatibility boundary described
below. It also retained exact-seed candidates found in compatible-reference
lists, including an `8200221132` result under the `RT5340` search.

### 7. Prom Motors compatible OE values were audit-only but unusable

The parser already retained a provenance-verified Prom Motors product-detail
object containing the candidate supplier article and the platform's compatible
OE list. The identity extractor used only the supplier article, so valid
aftermarket codes such as `NRF 30192` conflicted with confirmed OE numbers
`0384J9/0384N6`.

`oe-extractor-v4` now records those values as
`PLATFORM_COMPATIBLE_REFERENCE_LIST`, while generic `Код запчастини` values are
recorded as `CANDIDATE_PART_NUMBER`. Automatic verification still requires a
confirmed one-hop XLS route and retained detail provenance. An unconfirmed
platform suggestion remains `UNKNOWN`; an ordinary structured OE conflict
still blocks verification.

This boundary raised true-cross query coverage from 10/20 to 14/20 and retained
cross seller observations from 15 to 26. Supplier SKU/MPN values remain
auditable without masquerading as OE values.

### 8. Fuel-filter pressure is now a required analogue dimension

The recovered `6Q0201051` market contains fuel-filter variants whose pressure
may differ. v25 extracts `bar/бар` values from titles and structured pressure
characteristics, compares them as a hard commercial dimension, and lists
`operating_pressure` as required for fuel-filter analogues. A missing pressure
therefore stays `UNKNOWN` and cannot be represented as a fully decision-ready
price comparison; an explicit `6.4 bar` versus `4 bar` is a hard conflict.

### 9. Top-mount bearing wording no longer loses to generic bearing

`Підшипник опори передньої стійки` was captured by the earlier generic-bearing
rule before the specific top-mount rule. v25 moves the specific rule ahead of
the fallback and covers this real wording. The candidate is no longer a false
hard stop, while the radiator-tank and opposite-side cases remain blocked.

### 10. Category requirements now reach pricing admission fail-closed

`operating_pressure` was present in the semantic matrix but absent from the
comparability dimension whitelist. Admission therefore discarded the field
when it assembled required analogue evidence. The whitelist and prompt contract
now include it: missing pressure yields
`PRICING_EVIDENCE_MISSING_OPERATING_PRESSURE`, while an explicit mismatch
yields `HARD_STOP_OPERATING_PRESSURE`.

A second bypass let a model label a `VERIFIED_CROSS` candidate as `EXACT`, which
skipped every `analogue_required_dimensions` check. The effective match level
is now deterministically capped to `ACCEPTABLE_ANALOGUE` whenever OE status is
`VERIFIED_CROSS`. Both pricing admission and the persisted legacy/identity
match levels use the cap. This is part of prompt contract
`marko-product-comparability-v3.4`; any older activation freeze is historical.

### 11. Cross admission now controls calibration and pricing in every mode

The calculation and calibration consumers previously made semantic review
mandatory only when the global provider mode was `required`. In `off` or
`shadow`, a `VERIFIED_CROSS` observation could therefore reach those consumers
through the older deterministic gates without a current review whose
`pricing_admission` was `ADMITTED`.

The authority is now per observation. Every `VERIFIED_CROSS` observation
requires a current-runtime effective review and `pricing_admission=ADMITTED`,
independently of the global provider mode. Missing reviews and non-admitted
reviews receive separate calibration exclusion codes. Exact-OE observations
retain the existing deterministic path unless the global mode is `required`.
New calculation traces freeze `required_observation_ids`; replay uses that
frozen set, while traces written before this field preserve their original
global-only semantics.

### 12. Live brake-line and steering wording is no longer left UNKNOWN

The retained live set exposed a verified cross whose seed was a flexible brake
hose but whose candidate was explicitly a rigid `Гальмівна трубка`. v25 left
the candidate part type unknown, so only the later admission layer could stop
it. v26 adds a distinct `brake_line` subtype (`трубка`, `трубопровод`, `brake
line/pipe/tube`); hose-versus-line is now an immediate deterministic
`part_subtype` hard stop.

The same replay contained `Кермові наконечники`, which was missed because the
extractor covered only noun-first singular wording. v26 recognizes the
adjective-first plural form as `tie_rod_end` without inferring package quantity
from grammar. The actual live titles now produce one additional explicit false
comparison rejection and one additional correctly typed candidate.

The extractor's closed regex vocabulary is now compiled once. This does not
change decisions, but prevents cache thrashing during full XLS reparse: the
previous seven-module regression was interrupted after 103.53 seconds while
building the reparse fixture; after caching, the complete set passed in 7.27
seconds.

### 13. Seed-asserted commercial facts are mandatory for analogues

The earlier default analogue contract required only the broad part family for
most categories. A verified cross could therefore keep `side`, `position`,
subtype or assembly as `UNKNOWN` and rely on the general review path. v27 makes
every commercially relevant fact explicitly asserted by the customer seed a
required deterministic dimension: subtype, assembly level, serviceability,
side, position, connector count, dimensions, opening temperature, pressure,
housing, included components and the extracted climate/transmission/core/
power variants. Missing candidate evidence yields `MANUAL_REVIEW`; a conflict
remains excluded. Vehicle make/model are deliberately not universal
requirements because legitimate crosses span badge-engineered platforms.

Re-evaluation of the 30 live `VERIFIED_CROSS` candidates under v27 produces:

- 3 explicit deterministic hard stops;
- 22 candidates with missing required analogue evidence, therefore manual
  review before pricing;
- only 5 candidates with the semantic analogue requirements complete (the
  independent identity/admission gates still apply).

### 14. Short numeric articles use bounded retrieval context

The replay also exposed a retrieval failure for short numeric supplier
articles such as `25307`: an exact marketplace query can be dominated by
unrelated products that happen to repeat the same number. Parser adapter v5
keeps the normalized article as the immutable identity query and freezes the
catalogue brand/title in a separate `search_context` field. Only for 4-6 digit
numeric queries, the gateway now performs the exact query plus at most one
bounded contextual query and deduplicates their union before the existing
detail budget is applied.

The context affects `query_key`, `input_hash`, and acquisition idempotency, so
different retrievals cannot collide. It is never copied into extracted OE/MPN
evidence and never proves identity or comparability. Tampering with persisted
context invalidates the acquisition contract. Exact alphanumeric and longer
identifiers retain the single-query behavior.

The change passed 35 focused contract, search, architecture, and fencing tests,
including contextual ranking, deduplication, idempotency separation, and
tamper rejection. A new live `25307` request was **not executed**: the current
runtime correctly rejected it under source policy `NOT_PERMITTED`. Therefore
this section establishes offline contract correctness, not new live coverage.

### 15. v28 closes two additional variant-collision paths

The historical v28 extractor added a separate
`cv_joint_variant` dimension (`inner`/`outer`) so a front/rear position fact
cannot mask an inner-versus-outer CV-joint conflict. It also distinguishes a
standalone `thermostat_housing` from a coolant thermostat and from a complete
thermostat-with-housing assembly. These are hard semantic boundaries for
identity/pricing; an exact shared OE does not erase the package/component
difference.

The downstream comparability contract now registers `cv_joint_variant` as an
allowed semantic and identity-hard-stop dimension. Without that registry entry
the extractor could detect the conflict but the final comparability object
would reject the dimension as unknown; this path is covered by the downstream
test suite.

The regenerated 20-pair semantic smoke remains 10/10 positive survivors and
10/10 hard negatives blocked. The v28 report is
`.artifacts/metis_luna_benchmark_20260803/semantic_gate_v28_report.json`
(SHA-256
`54fdc6c9aa7f1f7a054b8c0952d5f22b50baee4479cf80ac5aa57b76ffcff5e9`).
This is a deterministic regression result, not a production precision claim.

### 16. v29 closes four reproduced precision gaps

The current extractor version is `semantic-features-v29`. A targeted probe
showed four concrete false-match paths that were not covered by the pinned
20-pair smoke: an explicitly diesel injector versus petrol injector, an upper
versus lower ball joint, brake-disc titles containing only nominal diameters
such as `256mm` versus `280mm`, and a power-steering reservoir versus its cap.
v29 adds provenance-bearing `fuel_type`, `vertical_position`, title-level
brake-disc diameter, and reservoir-cap evidence.
When both sides assert incompatible values, the downstream contract returns
`NOT_MATCH`; missing values remain `UNKNOWN` and therefore cannot become a
pricing admission by themselves.

The v29 downstream registry includes all four new semantic dimensions as
identity-hard-stop dimensions. The targeted regression completed `927 passed,
4 skipped, 1 warning`; the focused semantic/comparability subset completed
`660 passed`. The regenerated 20-pair smoke remains 10/10 positive survivors
and 10/10 hard negatives blocked. This is still a development smoke result,
not a production precision claim.

The v29 report is
`.artifacts/metis_luna_benchmark_20260803/semantic_gate_v29_report.json`
(SHA-256
`c0c0c1646aff17a722c1344cb5cffc8ebf08b4b54b566691c15bd19ee38b89a0`).

### 17. v30 closes component-versus-assembly false matches

The current extractor version is `semantic-features-v30`. A deterministic
probe found that a broad family match still allowed a complete assembly to be
treated as a separately sold component (for example a radiator as a radiator
cap, a generator as a voltage regulator, a water pump as an impeller, or an
oil filter as its housing). v30 adds closed, provenance-bearing subtypes and
assembly levels for twelve such high-confidence boundaries. Patterns are
deliberately one-sided for component-only wording: titles such as “radiator
with cap” remain a complete radiator rather than being reclassified as a cap.

The new regression adds 13 tests. The full affected regression completed
`941 passed, 4 skipped, 1 warning`; the v30 semantic smoke remains 10/10
positive survivors and 10/10 hard negatives blocked. The smoke report is
`.artifacts/metis_luna_benchmark_20260803/semantic_gate_v30_report.json`
(SHA-256
`1fcd0175148c7ace3e76ebacb46475235beab4250a1fce7907c96fb581ddfa9b`).

### 18. v31 closes four remaining component boundaries

The current extractor version is `semantic-features-v31`. The next offline
probe found four high-confidence cases that were still only broadly typed:
“wheel bearing” versus “wheel hub”, an injector versus its repair kit, an air
filter versus its housing, and an engine mount versus its bracket. v31 adds
specific subtypes and assembly levels for these cases. It does not classify a
generic number or a vague word such as “support” on its own.

The affected regression completed `945 passed, 4 skipped, 1 warning`; the v31
semantic smoke remains 10/10 positive survivors and 10/10 hard negatives
blocked. The smoke report is
`.artifacts/metis_luna_benchmark_20260803/semantic_gate_v31_report.json`
(SHA-256
`49ca522d7ac3059c5ce91892aacdb87614dc7dbd0dde5801494413cc74689e45`).

### 19. v32 closes optional-component price contamination

The historical v32 extractor was `semantic-features-v32`. Real saved titles
showed two commercial variants that share the same part subtype but are not
the same sellable package: a window regulator with versus without its motor,
and brake pads with versus without a wear sensor. v32 records these facts as
provenance-bearing included components and returns a hard conflict only when
the two sides explicitly assert opposite variants. A missing assertion remains
`UNKNOWN` and does not become a positive match.

The v32 semantic/comparability regression completed `949 passed, 4 skipped, 1 warning`; the v32
semantic smoke remains 10/10 positive survivors and 10/10 hard negatives
blocked. The smoke report is
`.artifacts/metis_luna_benchmark_20260803/semantic_gate_v32_report.json`
(SHA-256
`c445084a94fb0b57f3e567ee78cbeb101e0caa1e65e59894a74ffd8a78f1d40d`).

Pricing admission also treats an explicit optional-component assertion on
either side as required commercial evidence. A candidate that says “with
motor” or “with wear sensor” therefore cannot enter an automatic price cohort
when the catalogue seed has no corresponding package fact: identity may
remain `MATCH`, but admission is `MANUAL_REVIEW` with
`PRICING_EVIDENCE_MISSING_INCLUDED_COMPONENTS`. This is a pricing safety gate,
not an additional identity match.

### 20. v33 closes four explicit package boundaries

The current extractor is `semantic-features-v33`. It now hard-stops only
explicit opposite package assertions for drum-brake repair kits versus
adjusters, A/C condensers with/without a drier, steering racks with/without
tie rods, and calipers with/without a bracket. Missing assertions remain
`UNKNOWN`; the pricing admission gate therefore keeps those candidates in
manual review rather than inventing a package match.

The affected regression completed `953 passed, 4 skipped, 1 warning`. The
regenerated smoke report is
`.artifacts/metis_luna_benchmark_20260803/semantic_gate_v33_report.json`
(SHA-256
`2d706da06317e0440f3adbd42d87b09c808b8d10eaa33e5b7f4fc0a9fed6c63c`).

### 21. v34 removes a real-XLS false semantic conflict

Some catalogue hub titles contain the bearing size in parentheses, for
example `Ступица ... (подшипник 37*82*45/43)`. The v31 wheel-bearing rule
treated the parenthetical component specification as the sellable part and
created a false `wheel_hub` versus `wheel_bearing` conflict. v34 gives the
explicit hub title precedence while preserving the hard stop for a true
`Подшипник ступицы` versus `Ступица` pair.

The affected regression completed `954 passed, 4 skipped, 1 warning`. The
regenerated smoke report is
`.artifacts/metis_luna_benchmark_20260803/semantic_gate_v34_report.json`
(SHA-256
`eac5a2b8d33272e23d373395350faf83c4f74bb3d3b31f10cd1c61adc9fcb72b`).

### 22. v35 closes exact-OE sellable-configuration leakage

An exact normalized OE is strong identity evidence, but it does not prove that
the candidate title carries the same sellable configuration. Before v35, an
exact-OE candidate could enter pricing with an UNKNOWN seed-asserted subtype or
assembly level. v35 emits `seed_asserted_dimensions` from the semantic matrix
and applies those requirements to exact and verified-cross admission alike.
An UNKNOWN candidate fact now yields `MANUAL_REVIEW`; an explicit conflict is
excluded. Physical dimensions, opening temperature, pressure and similar
category-specific facts are intentionally not promoted into the exact gate,
preserving the existing exact-OE boundary.

The v35 semantic smoke report is
`.artifacts/metis_luna_benchmark_20260803/semantic_gate_v35_report.json`
(SHA-256
`835d881b326e8469f2207e7fc8bd949f91385d5958633cf38c6f3b8563f43394`). It
retains 10/10 hard-negative blocks and 10/10 positive survivors; this remains a
development regression signal, not a production-accuracy estimate.

### 23. v36 closes candidate-only configuration leakage

The semantic matrix now records `candidate_asserted_dimensions` for explicit
subtype, assembly, position, connector and package facts. If the candidate is
more specific than an underspecified seed, the comparison remains identity
`UNKNOWN` for that dimension and pricing stays `MANUAL_REVIEW`. This is
deliberately not a hard `NOT_MATCH`: an exact OE or a later operator review may
still establish equivalence, but a richer candidate title cannot manufacture
missing seed evidence.

### 24. Every Prom price path now preserves sale/reference boundaries

The detail response can expose an active promotional price together with a
crossed-out reference price. The legacy `PromGateway` path previously kept the
listing-time value, so a card such as `sale_price=330` and
`reference_price=412` could be represented as 412 in the comparison. The
boundary now prefers the active discounted value, keeps the reference value as
separate evidence, serializes both fields, and re-sorts enriched offers after
detail fetch. This prevents a 24.85% stale-price uplift from entering market
ordering or downstream evidence. An inverted/stale discounted field is also
treated conservatively: if it is higher than the current/base price, the
base price remains sale and the higher value remains reference-only evidence.
The separate `prom_motors` OE-listing path and store-catalog import now apply
the same rule, so neither a part-code harvest nor an own-catalog sync can
reintroduce the stale-price bias through a second entry point.

### 25. The database now enforces the same price boundary

The ORM and migration `20260805_0048` add a fail-closed invariant to both
`market_observations` and `catalog_discovery_offers`: when both values exist,
`sale_price <= reference_price`.  Positive-value checks remain in force, and
legacy observations with a missing `sale_price` remain readable.  The
migration refuses to rewrite already persisted evidence; it first aborts with
`BLOCKED_MIGRATION_20260805_0048` if inverted rows exist.  This closes the
remaining persistence-level bypass after the runtime normalizers.

### 26. Short numeric title collisions are no longer priceable by default

The deterministic candidate gate previously only flagged a six-digit-or-shorter
all-numeric OE found in free text.  That allowed a random product-domain title
to reach later pricing gates when it happened to contain the same digits.  The
gate now keeps such an unlabelled substring visible but `REFERENCE_ONLY`.
Structured article fields remain eligible for the ordinary downstream checks;
the live `offer_identity` path now additionally holds even an explicitly
labelled short numeric title token until structured/detail proof exists.
Title/description matching also requires identifier token boundaries
and still supports grouped forms such as `7E5 827 505 A`; `7E5827505A` inside a
longer SKU is no longer identity evidence.  This is a precision-first change:
it sacrifices ambiguous coverage, not evidence-backed candidates, and
preserves the flag/reason for audit.

### 27. The same short-numeric gate now covers the live identity spine

The legacy candidate selector was not the only identity path. The main market
materializer uses `offer_identity.verify_offer_identity`, where an explicit
`OE: 123456` title could previously satisfy the strong text threshold and
become `VERIFIED_EXACT`. That is unsafe for short all-numeric values: a seller
article, phone fragment, or private row id can be repeated in both title and
description without being an OE.

`oe-extractor-v5` keeps those findings in `extracted_oe_norms` for operator
review, but removes them from automatic eligibility unless the same value is
present in a provenance-verified structured OE/cross field or retained detail
page. Confirmed cross and source-page authority remain separate, explicit
routes. The regression covers both rejection of repeated free text and
preservation of a structured six-digit OE. Existing alphanumeric and long
numeric OE paths are unchanged.

### 28. Retrieval-only number matching now has the same boundary contract

The legacy `matching.match_offer(search_number=...)` and Prom detail shortlist
used normalized substring checks. A query such as `123456` could therefore
rank or retain `1234567`, and an alphanumeric OE could match a longer suffixed
SKU. Both paths now require an identifier-shaped token; short numeric title
hits require an explicit OE/article label, while an exact structured SKU keeps
its exact-equality route. A catalog identity query also cannot fall back to
unverified free-text results after the identity lane is empty. This affects
retrieval/ranking only and does not turn a retrieval hit into pricing evidence.

## Verification

- 671 focused tests passed across semantic extraction, OE verification, and
  real XLS identity reparse during the earlier implementation; the final
  affected OE, semantic, comparability, and activation modules passed 687
  tests, including platform compatibility, namespace, pressure, top-mount,
  model-level capping, admission, and conflict regressions;
- Ruff, compileall, and `git diff --check` passed;
- an additional downstream calibration, pricing, replay, identity and semantic
  regression set passed 815/815 after the per-observation authority fix;
- the v26 semantic/reparse/comparability regression completed with 769/769;
- the v27 admission/semantic/reparse regression completed with 734/734;
- the v28 semantic/comparability regression completed with 703/703;
- the v29 targeted semantic/comparability and downstream regression completed
  with 927 passed and 4 skipped (one existing Starlette deprecation warning);
- the v33 targeted semantic/comparability and downstream regression completed
  with 953 passed and 4 skipped (one existing Starlette deprecation warning);
- the v34 targeted semantic/comparability and downstream regression completed
  with 954 passed and 4 skipped (one existing Starlette deprecation warning);
- the full backend run after the `oe-extractor-v5` hardening completed with
  3,101 passed, 142 skipped and 3
  existing Starlette deprecation warnings; the KEMP count contract now
  explicitly records 5,796 OE-bearing positions after refusing the
  `77646444-34` private variant as a public OE;
- the new short-numeric identity regression completed with 52 passed, covering
  repeated free-text rejection, structured six-digit acceptance, and the
  existing source-assertion/re-enrichment contracts;
- the catalog-search precision regression completed with 21 passed: title
  identity hits now require token boundaries, short numeric title hits require
  an explicit label, normalized-substring-only rows are discarded before
  they reach the cross-store UI, and identity queries cannot fall back to
  wording;
- the matcher and Prom shortlist boundary regression completed with 56 passed:
  search-number hits reject suffix collisions and preserve grouped OE tokens;
- the comparability mutation probe killed all 7 critical mutants (0 survived);
- the AI-evidence mutation probe killed all 17 valid mutants (0 survived);
- model and offline-migration checks for the new database boundary completed
  with 22 passed, including the complete Alembic chain and its fail-closed
  guard;
- the short-numeric-identity and candidate-selection regression completed with
  73 passed; unlabelled free-text hits are now held `REFERENCE_ONLY` while
  labelled/structured identifier paths remain covered;
- the sale/reference price-boundary regression completed with 107 passed,
  including detail-time discount replacement, inverted-discount rejection,
  incomplete-card fallback, own-catalog import, serialization of separate
  `sale_price`/`reference_price`, OE-listing harvest, and scraper contract
  compatibility;
- the v30 targeted semantic/comparability and downstream regression completed
  with 941 passed and 4 skipped (one existing Starlette deprecation warning);
- the v31 targeted semantic/comparability and downstream regression completed
  with 945 passed and 4 skipped (one existing Starlette deprecation warning);
- the v32 targeted semantic/comparability and downstream regression completed
  with 948 passed and 4 skipped (one existing Starlette deprecation warning);
- the pinned 20-pair semantic smoke remains 10/10 positive survivors and
  10/10 hard negatives blocked under v27, v28, and v29;
- no paid model was called.

Artifacts:

- live shadow:
  `.artifacts/metis_xls_cross_live_shadow_20260805/METIS_XLS_CROSS_LIVE_SHADOW.json`,
  SHA-256
  `c92f1ddcf4e1df020175d800c695c7e1973c46fbdc9f0d42a3176cfc09511a51`;
- pinned semantic smoke:
  `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v27_report.json`,
  SHA-256
  `6d91b7753d54071a0d2ab8ab7b3cc2ec293e0caee34dc0568c494fa59604c5c3`.
- current semantic smoke:
  `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v28_report.json`,
  SHA-256
  `54fdc6c9aa7f1f7a054b8c0952d5f22b50baee4479cf80ac5aa57b76ffcff5e9`.
- current semantic smoke after v29 precision hardening:
  `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v29_report.json`,
  SHA-256
  `c0c0c1646aff17a722c1344cb5cffc8ebf08b4b54b566691c15bd19ee38b89a0`.
- current semantic smoke after v30 component-boundary hardening:
  `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v30_report.json`,
  SHA-256
  `1fcd0175148c7ace3e76ebacb46475235beab4250a1fce7907c96fb581ddfa9b`.
- current semantic smoke after v31 component-boundary hardening:
  `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v31_report.json`,
  SHA-256
  `49ca522d7ac3059c5ce91892aacdb87614dc7dbd0dde5801494413cc74689e45`.
- current semantic smoke after v32 optional-component hardening:
  `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v32_report.json`,
  SHA-256
  `c445084a94fb0b57f3e567ee78cbeb101e0caa1e65e59894a74ffd8a78f1d40d`.
- current semantic smoke after v35 exact-OE admission hardening:
  `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v35_report.json`,
  SHA-256
  `835d881b326e8469f2207e7fc8bd949f91385d5958633cf38c6f3b8563f43394`.
- current semantic smoke after v36 symmetric admission hardening:
  `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v36_report.json`,
  SHA-256
  `a9c31e571c626cd2cfa26dfe7646bf9d6c324fbbef31be06d6b74a33d2d37e0d`.

## Evidence boundary and next gate

This replay proves live retrieval and deterministic gate behavior for the
sample. It does not estimate production precision because the XLS links are
customer-supplied authority rather than independently adjudicated labels, the
sample has only 20 queries, Prom is dynamic, and the ephemeral detail bytes
were hashed but not retained in the production evidence journal.

The working database also remains on its pre-reparse state. These improvements
will not become visible to the web application until the already verified
migrations and current identity reparse are deliberately applied to the main
environment. Independent manual labels and the larger shadow pilot remain the
release gate for automatic pricing.
