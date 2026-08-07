# METIS semantic gate v27/v28/v29/v30/v31/v32/v33/v34/v35/v36/v37/v8 — accuracy report

Date: 2026-08-05
Scope: deterministic post-parser and cross-source contradiction detection before Luna
The original pinned report was generated with `semantic-features-v27`. The
current implementation is `semantic-features-v40-damaged-condition`; v28 preserves the v27
decision boundary and additionally separates inner/outer CV joints and
standalone thermostat housings, v29 adds explicit fuel type, upper/lower
installation position, brake-disc diameter and reservoir-cap contradictions,
v30 adds high-confidence component-versus-assembly boundaries, and v31 adds
wheel-bearing, injector-kit, air-filter-housing and engine-mount-bracket
boundaries, v32 adds explicit with/without motor and brake-wear-sensor
component variants, and v33 adds explicit package boundaries for drum-brake
repair kits versus adjusters, A/C condensers with/without a drier, steering
racks with/without tie rods, and calipers with/without a bracket. v34 keeps
hub listings with parenthetical bearing dimensions typed as hubs, while a
standalone bearing remains distinct. v35 keeps exact-OE identity conservative:
seed-asserted sellable configuration must be confirmed before pricing, while
exact-OE does not invent missing category geometry. v36 applies the same
fail-closed rule when the candidate, rather than the seed, is the side with an
explicit sellable configuration.
v37 additionally extracts package quantity and unit basis from Prom/XLS
characteristic label/value pairs and applies a separate persisted-pricing
completeness gate; UNKNOWN remains manual review and never enters calibration.
v38 adds ignition-lock insert wording. v39 separates sensor connectors and
window-control modules from the adjacent sensor/switch components. v40 detects
damaged/bent/parts-only offers as a separate condition. A shared OE does not
override an explicit subtype, assembly, or unusable-condition conflict.
The current shared admission version is
`semantic-pricing-gate-v9-category-required-conflicts`: multi-valued sellable
assertions and authoritative-but-untyped cards remain discovery-visible but
cannot enter pricing evidence.
The pricing engine's KEMP reference lane uses the same persisted hard gate;
KEMP labels do not bypass missing or conflicting comparability evidence.
Result: `SEMANTIC_GATE_SMOKE_PASS`, not a production-accuracy claim

The regenerated v36 smoke artifact is
`.artifacts/metis_luna_benchmark_20260803/semantic_gate_v36_report.json`
(SHA-256
`a9c31e571c626cd2cfa26dfe7646bf9d6c324fbbef31be06d6b74a33d2d37e0d`). The
20-pair smoke remains 10/10 hard negatives blocked and 10/10 positive pairs
surviving; its zero-event upper bound is still 0.258866, so it is a regression
signal rather than a production precision estimate.

## What changed

### v35 exact-OE admission boundary

`seed_asserted_dimensions` is now part of the deterministic semantic matrix.
It contains only sellable-configuration facts explicitly present on the owned
seed: subtype, assembly level, serviceability, side/position, connector pins,
and package-changing variants. Exact OE candidates with UNKNOWN values in
those dimensions remain `MANUAL_REVIEW`; they cannot be priced from an
identifier alone. Geometry, opening temperature and pressure remain reserved
for category/analogue requirements so a valid exact OE does not acquire an
unjustified physical-specification gate.

### v36 candidate-only admission boundary

The matrix also records `candidate_asserted_dimensions`. If the candidate
explicitly says `contact group`, `with motor`, `right`, `6 pin` or another
sellable variant while the seed is UNKNOWN, the pricing arbiter returns
`MANUAL_REVIEW`. The identity layer remains conservative and does not convert
that asymmetry into an unsupported hard `NOT_MATCH`.

The semantic layer now extracts provenance-bearing facts and hard-stops only
explicit contradictions. It does not turn similarity or the absence of a
conflict into a positive `MATCH`.

The closed taxonomy now distinguishes, among other cases:

- automotive vs explicit non-automotive Prom noise;
- engine radiator, heater core, A/C condenser, intercooler, cooling fan,
  radiator tank, grille and support panel;
- ignition-lock housing, contact group and explicit complete assembly;
- explicit diesel/petrol fuel type for applicable offers;
- upper/lower installation variants where the title identifies a ball joint or
  mounting position;
- nominal brake-disc diameter from a title-level `mm` value;
- steering-reservoir body versus a separately listed reservoir cap;
- radiator versus radiator cap, wheel hub versus hub flange, alternator versus
  voltage regulator, water pump versus impeller, and A/C compressor versus
  compressor clutch;
- oil filter versus filter housing, timing belt/roller versus kits, ABS sensor
  versus ABS ring, headlamp versus housing, door handle versus its mechanism,
  and brake disc versus pads;
- cabin blower vs engine-cooling fan;
- cabin/engine-air/oil/fuel filters;
- clutch pressure plate vs clutch kit;
- caliper assembly, piston, guide and repair kit;
- cylinder-head/oil-pan/manifold/valve-cover gaskets and full gasket kits;
- temperature, reverse, oxygen, boost and brake-wear sensors, plus a sensor
  connector;
- fuel pump, injector and fuel-tank cap;
- brake pads/parking shoes, brake disc, flexible hose, rigid brake line,
  master/wheel cylinder, parking cable and vacuum pump;
- clutch disc, pressure plate, kit, release bearing and master/slave cylinder;
- timing/serpentine belt, timing roller, tensioner and idler roller;
- ABS/idle/temperature/reverse/oxygen/oil/boost/brake-wear sensors; brake-light,
  turn-signal and wiper switches; ignition wires and coil;
- window regulator, door/trunk lock and handle, mirror glass, expansion tank,
  expansion-tank cap, coolant-sensor flange and washer reservoir;
- camshaft, piston-ring set, connecting-rod/main bearing and propshaft support
  bearing;
- control-arm bushing, full control arm, stabilizer bushing, top mount, engine
  mount and coil spring;
- starter assembly versus starter components; power-steering reservoir, pump,
  pulley, rack, repair kit, tie rod and tie-rod end;
- wheel bearing versus complete hub; fan assembly versus impeller; EGR cooler
  versus the engine radiator; trunk/hood gas spring versus suspension shock;
- complete halfshaft, halfshaft flange and halfshaft repair kit;
- sliding-door roller/bracket;
- clutch-release bearing guide versus the bearing itself, air-filter housing
  versus the filter, transmission oil seal, mirror assembly, fuel-priming pump,
  standalone Bendix, bumper grille and fan impeller;
- stabilizer link versus bracket, complete steering rack versus repair kit or
  boot, radiator hose versus radiator, window-regulator crank versus complete
  regulator, universal joint, transmission oil cooler, engine piston, shifter
  bushing, door-lock striker, clutch cable, distributor rotor, exhaust hanger
  and valve-stem seal;
- side, axle position, pin count, package quantity, unit basis, dimensions,
  thermostat opening temperature, housing, explicit new/used condition and A/C
  variant.

Guardrails added after adversarial replay:

- category numbering such as `7,3 Радиаторы` is not parsed as an engine;
- `1.5 mm` is not parsed as engine displacement;
- unnamed dimensions are order-independent (`652x415 == 415x652`);
- `2.8` and `2.8TD` are compatible when the suffix is absent on one side;
- `радиатор под интеркулер` is not reclassified as the intercooler;
- a generic `замок зажигания` is not assumed to be a complete assembly;
- a control-arm bushing is not reclassified as the full control arm;
- saved Russian/Ukrainian naming variants such as `радіатор печі`,
  `радиатор отопителя`, `радіатор конденсатора`, `газова пружина`,
  `опора переднього амортизатора` and `бачок г/у керма` do not
  manufacture subtype conflicts;
- `впускний охолоджувач повітря` and equivalent Russian/English wording
  identify an intercooler even when Prom assigns a broad thermostat category;
- fuel-filter pressure in `bar/бар` is a required analogue dimension: explicit
  disagreement hard-stops, while missing pressure remains `UNKNOWN`;
- pricing admission recognizes `operating_pressure`; a missing value cannot
  disappear at the dimension whitelist, and a model cannot bypass analogue
  requirements by calling a `VERIFIED_CROSS` candidate `EXACT`;
- `підшипник опори передньої стійки` is classified as a top-mount bearing
  before the generic-bearing fallback;
- the live `гальмівна трубка` candidate is a rigid `brake_line`, not an
  unknown synonym of a flexible `brake_hose`; adjective-first plural
  `кермові наконечники` is typed as `tie_rod_end` without guessing package
  quantity;
- for an analogue, every commercially relevant semantic fact asserted by the
  seed is now required deterministic evidence. Missing subtype, assembly,
  side, position, connectors, dimensions or an asserted variant cannot be
  upgraded by the model and remains `MANUAL_REVIEW`;
- abbreviated/transliterated equivalents such as `кнопка ск/підймача`,
  `radiator kondicionera`, `направляющая выжимного` and
  `напрямна вибивного` are normalized to the same closed subtype;
- JSON-encoded characteristics are parsed without copying missing evidence,
  bare `new` does not turn `VW New Beetle` into a condition claim, and the
  marketplace unit `шт.` cannot erase an explicit title-level set/pair basis;
- explicit `title`/`name` identity now outranks a broad marketplace category
  and marketing description. Category and description are fallbacks only. This
  prevents a precise timing-belt roller from becoming a wheel bearing merely
  because the seller placed it under `Подшипники / Ступицы`;
- mixed-script catalogue abbreviations such as `AKП` normalize to the same
  automatic-transmission evidence as `АКП`/`АКПП`;
- radiator measurements allow one omitted thickness and at most 5%/20 mm
  supplier measurement variance; wheel-bearing thickness allows 1 mm. Larger
  geometry disagreements remain hard conflicts.
- joined customer notation such as `ГРМFord`, dotted position shorthand
  `пер.маточ.` and Cyrillic `АС+`/`АС-` is extracted without treating
  `АС+/-` as a contradiction;
- serviceable/non-serviceable fuel pumps, expansion tank/cap, cooling
  fan/flange, timing/serpentine roller and complete/repair-kit halfshaft
  conflicts are now explicit rather than hidden by the shared number.
- explicit `with/without` differences for commutator, tensioner mechanism,
  steering-rack servo sensor, bracket, cup and cover are commercial hard
  stops: they preserve `MANUAL_REVIEW` identity semantics but cannot enter the
  same price cohort.
- explicit radiator transmission/core-construction, engine-bearing cylinder
  count and starter power conflicts follow the same commercial boundary. The
  two XLS contain one АКПП/МКПП shared-number conflict, 25 shared numbers with
  flat/round radiator cores, one 4/5-cylinder bearing case and one 1.8/2.0 kW
  starter case. Missing variant evidence stays `UNKNOWN` and does not block.
- the v7 customer-title expansion recognizes conservative Russian/Ukrainian
  forms for electrical switches, lighting, locks and cylinders, alternator and
  starter components, engine lubrication/valvetrain, suspension inserts and
  mounts, body hardware, cables, transmission parts and common repair
  components. Generic wording keeps subtype/assembly `UNKNOWN`; it does not
  create a positive identity decision.
- ambiguous catalogue-language pairs—generic bearing versus wheel bearing and
  shock absorber versus removable strut insert—are demoted to `UNKNOWN` rather
  than manufactured as conflicts. Explicit dimensions, side, position and
  adjacent-component distinctions continue to hard-stop.
- the v8 residual pass adds only closed, commercially distinct terms observed
  in the remaining customer rows: oil-filler and fuel-tank caps, dipstick and
  guide, timing-chain tensioner and guide, crankshaft pulley, wiper blade,
  heater motor and resistor, clutch pressure plate, mass-airflow and idle-air
  components, crank/cam bearings, rocker arm, shift-linkage rod and door-lock
  eccentric. Adjacent components have explicit negative regression tests.
- the v9 pass adds another closed set from the remaining customer rows:
  brake drums, electrical pedal/door switches, distributor components,
  flywheel and ring gear, alternator rectifier/regulator, timing covers and
  sprockets, carburetor/repair kit, bulbs, washer caps, sliding-door parts,
  transmission mounts, propshaft couplings and oil-drain plugs. A source replay
  caught the ambiguous `roller of bracket` wording; v9 now refuses to treat
  roller-versus-bracket wording alone as identity disproof.
- the v10 residual pass covers another conservative set of sellable components,
  including gearbox bearings, hood/glovebox/seat handles, exhaust manifold and
  mounts, fuel regulators/valves, clutch controls, drive shafts, shifter parts,
  cooling-fan electronics, body trim and lighting components. Adjacent-part
  negatives are pinned separately. Russian/Ukrainian timing-belt-guide wording
  and `вентилятор основной` normalize without creating revision conflicts.
- the v11 pass closes explicit fasteners, brackets, controls, hoses, seals,
  trim, lighting, door hardware, pumps and transmission components while
  retaining generic `фланш`, `ролик CVH/ZETEC`, `демпфер`, `защита`
  and similar context-free rows as `UNKNOWN`. Eight Russian/Ukrainian canonical
  collisions found by the source replay were normalized before acceptance.
- the v12 boundary consumes explicit parser/enrichment fields instead of
  requiring the same facts to be repeated in marketplace prose. Snake-case and
  parser camel-case aliases are supported for side, axle position, body
  variant, package quantity, unit basis and year bounds, with provenance kept
  on every extracted value. It never invents a one-sided year range or an
  unknown body type. If one record contradicts itself (for example title says
  right while structured `side` says left), the comparison becomes `UNKNOWN`
  rather than exploiting the overlapping value to manufacture `MATCH`.
- the v13 boundary fixes two false-conflict mechanisms. Year ranges are now
  compared as inclusive intervals, so `2006-2011` and `2008-2010` match while
  disjoint ranges remain review evidence. More importantly, the primary typed
  `ComparisonEvidence` no longer treats every unequal string as a proven
  conflict: multilingual closed values such as `лівий/LEFT`,
  `передня вісь/front_axle` and `універсал/station-wagon` are canonicalized;
  different recognized exclusive values still conflict; opaque fitment,
  generation and engine wording drift becomes `UNKNOWN` rather than an early
  false `REJECT`.
- the v14 residual replay closes condition and sellable-package gaps observed
  directly in saved candidates. `Б.У`, `б-у`, `pre-owned` and `second-hand`
  now enter the same used/refurbished exclusion as `б/у`; the current
  classifier is re-run when old observations are reviewed, so a stale stored
  `UNKNOWN` cannot preserve eligibility. Full versus lower engine-gasket sets,
  a power-steering-pump repair kit versus the complete pump, and a fan module
  with shroud versus the generic cooling-fan listing receive distinct semantic
  evidence. Vehicle make is extracted as a diagnostic Luna dimension: an
  Audi/BMW difference is visible, while cross-platform titles sharing any make
  match and make mismatch alone is never a deterministic hard stop.
- the v15 boundary adds make-bound vehicle-model and tightly scoped
  model-qualified generation hints for Luna. Numeric model-like tokens are not
  accepted without nearby make/model context, preventing e.g. Zimmermann
  article `100.3377.20` from becoming `Audi 100`. Model and generation-hint
  conflicts are deliberately diagnostic only: they improve reviewer evidence
  but cannot independently create a deterministic rejection of an exact-OE or
  verified cross-platform candidate.
- the v16 boundary makes variant extraction provenance-aware. Explicit
  title/name, parser fields and structured characteristics remain one primary
  tier, so contradictions between them still fail closed; lower-authority SEO
  descriptions can no longer erase an explicit right/left or front/rear fact.
  This closes saved row 149 (right seed versus left candidate) without changing
  any other pair in the hard-stop denominator. Headlamp-after-`Б/У` and shock
  absorber rod/component wording receive precise taxonomy, while component
  phrases such as headlamp trim and fog-lamp frames remain protected by
  adversarial regressions. Vehicle make/model evidence uses the same fallback
  principle, preventing template descriptions from expanding a precise title
  into unrelated models.
- the v17 boundary adds a non-authoritative vehicle-platform diagnostic for
  stable badge-engineered model families: Ducato/Boxer/Jumper,
  Scudo/Expert/Jumpy and Qubo/Fiorino/Bipper/Nemo. A shared platform explains
  why different makes/models may still be comparable, but never proves that a
  specific part is interchangeable and never creates pricing admission.
- the v18 boundary separates package cardinality from commercial unit basis.
  `комплект 4 шт.` remains a four-element set rather than the ambiguous
  values `set + piece`; an explicit pair outranks the generic word `комплект`;
  and a genuine `1 шт.` listing still retains `piece`. This prevents the
  marketplace measure unit from manufacturing equality with a single-part
  offer while preserving package quantity as separate evidence.
- the v19 boundary recognizes compact automotive year intervals such as
  `95-00`, `03-10` and `84-93`. Century expansion is bounded to 1950–2040,
  reversed or wider-than-35-year intervals are rejected, and decimal engine
  ranges, chained article numbers and three-digit dimensions are excluded.
  Year disagreement remains diagnostic and non-hard: it improves Luna's
  evidence but cannot independently reject a candidate.
- the v20 boundary closes marketplace orthography and abbreviation gaps without
  converting vague text into positive identity. It recognizes mixed-script
  radiator wording, abbreviated tie-rod ends, connecting-rod bearings,
  stabilizer links, coolant-tank caps, external lifting-door handles and
  automotive vacuum-pump word order. Generic bushing, handle and fan-motor
  families remain deliberately coarse; explicit set-versus-single,
  motor-versus-impeller, cooling-versus-cabin and with-versus-without-impeller
  differences are the only new hard commercial boundaries. Latin `B/U` and
  the bounded saved-catalogue form `digits + BU + separator` enter condition
  exclusion, while brand/article fragments such as `Mercedes BU`,
  `A901...BU` and `BU-42` stay protected. The customer XLS revision replay
  exposes one additional real source contradiction for internal code
  `77644736`: one revision says fan motor without an impeller and the other
  says with an impeller. This conflict is preserved instead of being voted
  away; the two revisions are not treated as independent corroborating
  sources.
- the v21 boundary adds two coarse, automotive-context-only evidence families:
  `generic_hydraulic_pump` and `chassis_linkage`. They close saved marketplace
  wording gaps without asserting a subsystem, subtype or assembly level. A
  plausible power-steering-pump or control-arm comparison therefore remains
  `UNKNOWN`, while an explicitly unrelated family can still be disproved. The
  frozen 407-pair replay keeps the hard-stop denominator unchanged and reduces
  retained candidates with no candidate part family from six to four. Generic
  industrial hydraulic pumps and machine levers/rods without automotive
  context remain unclassified.

## Pinned 20-pair smoke

Inputs:

- `benchmark_input.json`: `51fd4253a3411da0e472de4b23fecb5c5beb20623375ebbbbc009d6985a91ace`
- `ground_truth.json`: `4718aa5b9d4d757dbed366166b626caa75ec044db6c89887287ec728aaedb3c2`
- generated report: `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v27_report.json`,
  SHA-256 `6d91b7753d54071a0d2ab8ab7b3cc2ec293e0caee34dc0568c494fa59604c5c3`;
- historical v28 regenerated report: `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v28_report.json`,
  SHA-256 `54fdc6c9aa7f1f7a054b8c0952d5f22b50baee4479cf80ac5aa57b76ffcff5e9`;
- current v29 regenerated report: `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v29_report.json`,
  SHA-256 `c0c0c1646aff17a722c1344cb5cffc8ebf08b4b54b566691c15bd19ee38b89a0`;
- current v30 regenerated report: `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v30_report.json`,
  SHA-256 `1fcd0175148c7ace3e76ebacb46475235beab4250a1fce7907c96fb581ddfa9b`;
- current v31 regenerated report: `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v31_report.json`,
  SHA-256 `49ca522d7ac3059c5ce91892aacdb87614dc7dbd0dde5801494413cc74689e45`;
- current v32 regenerated report: `.artifacts/metis_luna_benchmark_20260803/semantic_gate_v32_report.json`,
  SHA-256 `c445084a94fb0b57f3e567ee78cbeb101e0caa1e65e59894a74ffd8a78f1d40d`;
- extractor implementation SHA-256 is embedded in every generated report.

Measured result:

| Metric | Result | 95% boundary |
|---|---:|---:|
| Confirmed cross pairs surviving the gate | 10/10 | Wilson lower `0.722467` |
| False hard stops on confirmed pairs | 0/10 | one-sided upper `0.258866` |
| Hard negatives stopped | 10/10 | Wilson lower `0.722467` |
| Missed hard negatives | 0/10 | one-sided upper `0.258866` |

The point estimate is perfect on this smoke sample, but `n=10` per class is too
small to prove a low production error rate. Therefore the report always emits
`promotion_eligible=false`, even when every smoke gate passes.

Reproduction:

```bash
cd backend
uv run comparability-acceptance evaluate-semantic-gate \
  --benchmark ../.artifacts/metis_luna_benchmark_20260803/benchmark_input.json \
  --truth ../.artifacts/metis_luna_benchmark_20260803/ground_truth.json \
  --output ../.artifacts/metis_luna_benchmark_20260803/semantic_gate_v32_report.json
```

## Real saved development replays

`GOLD_SET.csv` contains 120 real saved Prom candidates but zero independent
manual labels. The current gate identifies 44/120 rows as explicit
contradictions. Those 44 include non-automotive search noise, different part
types/subtypes, incompatible assemblies, opposite side, climate variant and
engine conflicts.

`CUT_PRECISION_REVIEW.csv` contains another 292 real saved candidate pairs.
The v11 replay leaves 60 explicit stops after preserving the earlier fixes for
heater-core/condenser naming, thermostat-housing assembly, multi-engine
suffixes, caliper repair kits, top mounts, gas springs,
steering-reservoir abbreviations and category-aware dimension tolerances.
The stopped rows are recurring structural contradictions found by the
819-pair adversarial pass, not positive identity decisions.

The combined prediction-blind reservoir contains 819 pairs. Relative to the
v4 baseline, v11 keeps the deterministic hard-stop count at `229/819` after
expanding extraction coverage. The v6 change was from `144/819` to `229/819`
(`+85`, final rate `27.9609%`). That v6 pass added three directly inspectable
hard stops beyond v5: engine mount versus a code-only bearing, complete
steering rack versus a repair kit, and radiator versus stabilizer link. It also
removed one false category/language-led stop, for a net gain of two. The final
conflict histogram is:

| Dimension | Conflicting pairs |
|---|---:|
| explicit non-automotive domain | 102 |
| part subtype | 81 |
| part type/family | 49 |
| assembly level | 45 |
| new versus used condition | 33 |
| side | 8 |
| engine | 7 |
| front/rear position | 4 |
| dimensions/technical specs | 4 |
| unit basis | 2 |

By frozen source, the 229 stopped pairs are `44/120` from `GOLD_SET.csv`,
`60/292` from `CUT_PRECISION_REVIEW.csv` and `125/407` from the persisted
candidate export. The title-priority change also removes a false category-led
wheel-bearing/hub conflict and keeps a complete halfshaft classified from its
title rather than from broader descriptive text.

Part-family extraction is known on both sides for 673 pairs; 146 have only the
seed family, and no pair remains unknown on the seed side. Unknown never means
compatible. These 819 rows still have no independent truth labels, so the
increased stop rate is adversarial coverage evidence, not
measured precision or production accuracy. The pinned 10 positive pairs remain
`10/10` unblocked.

## Customer XLS taxonomy coverage

The two customer-supplied `.xls` files were read without modifying them and
are pinned by raw-file SHA-256:

- 4,646-row file:
  `1fb10a10794421e895c8b3e9ccdb19f2333aedaa07c6fa35da1fecebb8ad27ca`;
- 7,743-row file:
  `fb37b2102c58b5a65ed7bc115ff6616f89adb0a5e75a30329934bd40e450298e`.

Before the customer-title expansion, the extractor recognized a closed part
family in `2,858/4,646 = 61.52%` and `4,445/7,743 = 57.41%`. The final
version recognizes `4,637/4,646 = 99.81%` and
`7,728/7,743 = 99.81%`. Only 9 and 15 rows respectively remain `UNKNOWN`;
they are not guessed
into a family and still require Luna or manual review.

This is extractor coverage, not correctness. Correctness is guarded separately
by bilingual equivalence tests, adjacent-component negative tests, the pinned
20-pair benchmark and the two real saved-pair replays.

The saved replay is useful coverage evidence, not accuracy: the other 78 rows
are `NEEDS_REVIEW`, not `MATCH`, and none of the 120 system predictions is
copied into ground truth. `PRECISION_REPORT.json` therefore correctly remains
`BLOCKED_BY_MANUAL_LABELS`.

## Cross-revision semantic consistency gate

The shared private KEMP code is a join key, not evidence that every historical
row under it is the same physical part. A complete pairwise replay over the two
declared customer reference revisions compared 4,647 row pairs across 4,639
shared internal codes.

The first replay produced 13 conflicting codes. Eleven were extractor defects
caused by Russian/Ukrainian spelling drift, abbreviations or component wording:
`торм`/`гальмів`, `направляющая`/`напрямна`, `сайленблок`,
`трешип`/`трьохшипний`, `в сборе`/`в зборі`, caliper guides, camshaft oil seals
and a roller being mistaken for the serpentine belt itself. Those variants are
now normalized conservatively; a generic belt roller keeps its family while its
idler/tensioner subtype remains `UNKNOWN`.

After those fixes, plus the v11 residual replay, exactly five explicit source
conflicts remain:

- `7764`: three rows inside the newer revision reuse one truncated private key
  for unrelated parts — a rear brake disc, a rear coil spring and an
  intercooler; their four public numbers must never form one identity graph;
- `77643614`: old revision says a left Daewoo Lanos window-regulator motor,
  newer revision says right;
- `77648805`: old revision says a rear Audi A4 B6 shock absorber, newer revision
  says front;
- `77645658`: old revision says a brake-light switch, newer revision says a
  reverse-light switch;
- `77647853`: old revision says an electric fuel pump, newer revision says an
  automatic-transmission selector.

`identity-graph-v4` no longer treats these cases as ordinary recency
supersession. It records `SOURCE_SEMANTIC_CONFLICT`, retains the source titles,
dimensions and extractor version in validation details, and forces every edge
created through the affected private key to `REVIEW`. Such an edge cannot fill
OE, widen acquisition or move a price before adjudication.

## Public-number fan-out and shorthand gate

An exact public number may occur under several private KEMP keys because the
catalog contains duplicate rows as well as genuine conflicts. In the two XLS
revisions, after safe normalization, there are 9,629 distinct public numbers;
910 belong to more than one private key. Blanket quarantine is therefore too
coarse: it would discard hundreds of confirmations without showing that the
products are different.

The v11 semantic gate quarantines the 28 exact numbers whose associated titles
contradict on a structural identity dimension. This includes the canonical-only
`1K0905851` case: one private key describes an ignition-lock housing and another
describes a complete lock assembly. The old edge-only SQL guard could not see
that conflict because each graph contained only its canonical node and no link.
The retained KEMP-site title `radiator kondicionera ... GHR161480B` is now
correctly normalized as an A/C condenser instead of an engine radiator. DENSO's
public product bulletin independently identifies the same
`GHR161480/GHR161480A/GHR161480B` OE family as a condenser for Mazda 3/6. This
removes a false semantic conflict; it does not prove every advertised engine
application or authorize pricing without the remaining fitment evidence.

The adversarial fan-out pass added 15 source-only conflicts that the preceding
taxonomy missed: expansion tank versus cap, cooling fan versus coolant-sensor
flange, timing belt versus A/C condenser, timing roller versus serpentine
tensioner, front versus rear wheel bearing, `АС+` versus `АС-` radiator, and
halfshaft repair kit versus complete halfshaft. V10 additionally prevents a
halfshaft flange from joining a complete drive shaft and a hood-release handle
from joining its mounting bracket merely because the public number is shared.
Differences that may describe
fitment or commercial variants rather than distinct identity—starter power,
radiator core shape and door-roller included components—remain review evidence,
not automatic hard stops.

The customer files also use compact catalog notation. The tokenizer now expands
suffix lists before graph construction, for example:

- `1J0959455A/K` -> `1J0959455A`, `1J0959455K`;
- `1K0959455Q/ET/DH` -> three complete VAG numbers;
- `811959455B,L,R` -> three complete variants;
- `8K0407151/152/695` -> complete `8K...` numbers.

Composite slash identifiers are handled separately from suffix lists:
`331/28235L` and `331/28235R` are now retained as the complete normalized
identifiers `33128235L` and `33128235R`. The old split emitted a shared global
node `331` and falsely joined left and right JCB handles.

It no longer publishes suffixes such as `K`, `ET`, `L`, `R` or `MG` as global
identifiers. Dimension-only cells are ignored. The two remaining unsafe real
source values, `0` and `Fiat/Alfa/Lancia`, are retained in `graph.discarded`
with reason `UNSAFE_PUBLIC_NUMBER_SHAPE`; valid short identifiers such as
`258`, `KL2` and `S5G` remain available. The short identifier `148` is retained
but quarantined: it is assigned to two Ford mechanical fuel pumps while their
titles explicitly disagree on `serviceable` versus `non_serviceable`.

The final no-site source-only plan indexes 7,193 internal codes and yields:

- 5,222 `OE_CONFIRMED`, 1,951 `MPN_ONLY`, 20 `UNRESOLVED`;
- 3,250 codes with links and 3,399 links;
- 5 private-key semantic conflicts and 28 public-number semantic conflicts;
- 47 code-level `PUBLIC_NUMBER_SEMANTIC_FANOUT` quarantines, because one
  conflicting number may affect more than one private code.

The additional v7 quarantine is public number `6N0905865`: one customer row
describes an ignition-lock cylinder while two other revision rows describe the
electrical contact group. Treating that shared number as automatic identity
would join separately sold components, so the single confirmation lost versus
v6 is an intended safety correction rather than coverage regression.

The evidence artifact is
`.artifacts/catalog_identity_plan_xls_20260805_v11_no_site.json`, SHA-256
`e06492dfa4955ca52f18f3b2122cbe08b6291859b57502927465471ac5a77aa1`.
The optional retained KEMP-site plan is separately pinned at SHA-256
`9e35f9a6926b89dc2e127d458ddbd2a90e11136eb95a335c1cf9583bb28b5977`;
it contains the same 28 number-level and 47 code-level semantic-fanout
quarantines, and yields 5,498 `OE_CONFIRMED`, 1,675 `MPN_ONLY` and 20
`UNRESOLVED`. Site-only claims remain `REVIEW` unless corroborated.

## Persisted-edge version boundary

`identity-graph-v4` binds current reads to more than YAML configuration. The
runtime SHA-256 now includes the graph config, token config, semantic extractor
version and exact source-file hashes of:

- `metis/pricing/identity_graph.py`;
- `marko/services/catalog_identity_reparse.py`;
- `marko/services/semantic_candidate_features.py`.

Therefore an old edge produced before the composite-number or serviceability
fix cannot remain silently eligible after deployment. It fails the current
method/runtime-hash predicate until the atomic reparse recreates or quarantines
it. The same safe-shape rule is also applied to fitment-cross snapshots, so an
external Avto.pro/Exist.ua claim cannot reintroduce `0`, `MG` or another bare
editorial fragment through a separate ingestion path.

The source-only artifact carries this contract inside the JSON. Its current
runtime SHA-256 is
`294ec78858d46fd9506e0308de71d4fc16489e38bab2f474a7e43f86d379b7a4`;
the report can therefore be independently tied back to the exact implementation
and configs that produced it.

## Cross and coefficient confidence authority

Confidence is no longer synthesized at a read boundary. Every planned
`CatalogIdentityLink` now carries an explicit confidence and
`automatic_eligible` decision in its validation details. A frozen pricing read
rejects an old or malformed row that lacks an explicit finite confidence in
`(0, 1]`; it does not replace the missing value with `0.90`. Rebuilding the
artifacts after this writer change is why the plan and runtime hashes above
differ from the preceding report revision.

Description-derived `CrossLink` rows are run-scoped evidence. They become
automatic only after the cross decision is `CONFIRMED`, has at least two
independent sellers and records the current explicit `0.85` confidence. A
missing flag, missing/invalid confidence or one-seller decision fails closed.
Global catalog search and discovery no longer union every historical
workspace `CrossLink`: only current long-lived `CatalogIdentityLink` authority
is reused globally. Verified fitment crosses remain available when a new
pricing run builds and freezes its own scope; old run-local description
evidence cannot silently widen later searches.

The stateless `/pricing/evaluate` QA endpoint also stopped manufacturing
calibration proof. Model, method/version, support counts, confidence,
validation status, log effect, interval and dataset SHA-256 are now explicit
inputs. A validated coefficient requires positive sample/effective support, a
complete positive interval containing the multiplier and no validation-failure
reasons. This does not make caller-provided data authoritative; it prevents an
omitted payload from being presented as if ten verified pairs and confidence
`0.8` existed.

Legacy recommendation replay now maps missing `urgency` to the domain/API
default `0`, not maximum urgency `1`. Thus absence of an old optional field
cannot inflate the replayed priority score.

## Read-only replay against the current database

The database remained at migration `20260731_0031`; the replay ran in a
read-only transaction and was rolled back.

- observations replayed: 148;
- deterministic/persisted stops: 9;
- five are the saved ignition-housing item against an explicit contact group
  or complete lock assembly;
- one is non-automotive phone-case noise, two are already persisted rejects for
  a water-supply pipe, and one is a persisted OE conflict;
- `VERIFIED_EXACT` observations: 2;
- false hard stops among those exact observations: 0.

The run-level comparability API now returns Wilson 95% intervals and exact
one-sided zero-event upper bounds for false matches and unsafe admissions.
Consequently, `0` observed errors can no longer be rendered without its sample
size uncertainty.

The two exact observations are not treated as two independent statistical
labels. They are only a live-regression control.

## Verification

- semantic/identity/fitment-source targeted tests: PASS;
- semantic feature tests: `510 collected and covered by the full pass`;
- semantic/identity/source target set is covered by the full pass;
- the semantic/acceptance target set is included in the full backend pass;
- full backend suite after candidate-detail, cross-revision, public-fan-out,
  article-shorthand, serviceability, fan-out mining, runtime-hash,
  detail-journal, cross-confidence, QA-coefficient and v11 adversarial gates:
  `2852 passed, 142 skipped, 3 deprecation warnings`;
- previous frontend verification remains `218 passed` and `dart analyze` with
  no issues; it was not rerun for this backend-only v11 change;
- Ruff on touched Python files: PASS;
- no migration, main-DB write, live Prom scrape or paid model call was
  performed. A read-only web corroboration of `GHR161480B` used DENSO and
  catalog pages only.

## Customer XLS identity graph dry run

Both customer workbooks are byte-identical to the pinned sources already stored
under `backend/data/`:

- 4,646-row revision: XLS SHA-256
  `1fb10a10794421e895c8b3e9ccdb19f2333aedaa07c6fa35da1fecebb8ad27ca`;
- 7,743-row revision: XLS SHA-256
  `fb37b2102c58b5a65ed7bc115ff6616f89adb0a5e75a30329934bd40e450298e`.

The additional Telegram copy `2_5424827205639252305 (2).xls` has a different
raw container SHA-256
`819f54b0dc68e03e0269e19361616b5bb879c5acbaaa53a3b9661ecd4a853f01`,
but a read-only normalized row comparison shows the exact same 7,743-row
multiset as `(3).xls` (7,743 shared, zero rows unique to either copy). It is
therefore the same logical dataset and is not counted as an independent source
or an extra corroborating vote.

The final `identity-graph-v4` source-only plan indexes 7,193 internal codes,
produces 3,399 candidate links and refuses 456 claims where another revision
identifies the purported OE as a supplier article. Its exact status, anomaly and
hash totals are recorded in the public-number section above.

### 2026-08-05 live database reconciliation

The local development PostgreSQL database was subsequently inspected and the
current writer was executed in `--dry-run` mode only. No migration, reparse or
database write was performed. The deployed database is still at Alembic
revision `20260731_0031`; it contains 4,249 historical catalog-identity rows,
but the current runtime-hash predicate admits none of them. A direct call to
`load_scope_candidates()` over the 4,647-row import therefore returned:

- `items_with_confirmed_identity_links = 0`;
- `confirmed_identity_links = 0`;
- current persisted identity statuses: 129 `OE_CONFIRMED`, 4,482 `MPN_ONLY`,
  36 `UNRESOLVED`.

This is a deployment/data-state gap, not a hidden fallback: stale v1 edges fail
closed and cannot move a price. The current `identity-graph-v4` dry-run against
the same workspace predicts the post-reparse state as:

- 4,663 rows seen, 4,627 rows with a declared source;
- 1,933 rows with at least one planned link;
- 1,715 `CONFIRMED` and 368 `REVIEW` planned links;
- 3,097 `OE_CONFIRMED`, 1,530 `MPN_ONLY`, 36 `UNRESOLVED` rows;
- 3,560 private `776...` values discarded as internal catalog codes;
- 346 anomaly-bearing identities retained for review rather than promoted.

The dry-run output SHA-256 was
`d9a6b6dcca448974e6be6cba675eb047a0e287dc5948d39f1adb176019d339ba`;
its runtime config SHA-256 was
`af2272b18f08248ce5176e04cec6e11654a9f510b09659c8319256484fecd177`.
The deployment sequence was then exercised against a disposable PostgreSQL
clone of the same database. All migrations from `20260731_0031` through
`20260805_0047` applied successfully, and a non-dry atomic reparse completed
with the same totals. Reading that clone through the actual
`load_scope_candidates()` runtime predicate yielded 1,663 effective confirmed
links on 1,587 of the 4,647 imported rows. Freezing the resulting scope produced
exactly 1,663 unique run-owned pairs, with zero unsafe/private pairs and zero
missing confidence values. The disposable database and its 306 MB dump were
deleted after measurement; the main development database remained unchanged.

The shipped-XLS regression now also proves the catalog-shaped positive path
`863130 -> 02090F`: the private join key `77646363` is not exposed as an
identity, the supplier link is `CONFIRMED`, and a candidate carrying `0209.0F`
reaches `VERIFIED_CROSS`. Deployment remains intentionally unclaimed until the
pending migrations and atomic reparse are explicitly authorized and executed.

## Independent-label preparation

The acceptance CLI now creates a prediction-blind review set, exports it as an
Excel-friendly UTF-8 CSV and a standalone visual HTML workstation, imports only
operator labels back into the immutable JSON evidence tasks and refuses
finalization when:

- a development seed, candidate or exact pair leaks into the review set;
- a source/evidence/task hash changes;
- prices, semantic-gate output or model predictions appear in reviewer input;
- a task is silently added, removed or duplicated;
- independent reviewer attestation or evidence notes are absent;
- the final population is not exactly 100 MATCH plus 300 NOT_MATCH with one
  pair per seed group and candidate, including 50 pricing-eligible and 50
  pricing-ineligible MATCH rows.

The historical artifacts under `.artifacts/metis_locked_review_20260805*`
were generated with `comparability-locked-review-set-v1`. Revalidating the
same frozen sources under the current family-safe v2 contract exposed a real
capacity deficit that v1 had hidden:

- the DB-only v2 pool contains 396 tasks and exact bipartite capacity 395, so
  it lacks five independent seed/candidate families;
- adding the old GOLD/CUT reservoirs yields 768 tasks but capacity only 396,
  because they add alternate candidates for existing seeds rather than four
  new statistical seed units;
- all 11 DB seeds absent despite having persisted external offers are the
  deliberately excluded development benchmark; the remaining unselected DB
  seeds have no persisted external candidate.

A bounded permitted live expansion therefore queried nine previously unused
catalogue seeds by title/fitment, one search page per seed, excluding the four
owned seller IDs. All nine queries returned at least one external candidate.
The retained capture contains no monetary fields, model predictions or labels:

- seed input SHA-256:
  `225a3008f330bd0fe4493f38192208c1a1ea48c3e83cd6e8866fac0a1cd09266`;
- non-monetary capture SHA-256:
  `6301ce8251264e62744c53bfa4b602cf07e655ad613a327fb1cfdc40c5fc3c6e`;
- nine-row review source SHA-256:
  `338a929122df1540dc4ff0be53a746f88607eea4c62ec14415173c58a870e766`.

The current minimal reviewer artifact is
`.artifacts/metis_locked_review_20260805_db_plus_live_v21/`. It combines the
407-row DB source with the nine-row live source, excludes 11 development
overlap rows, and contains:

- 405 blinded tasks and 405 unique seed groups;
- 404 unique candidate listings/families;
- exact bipartite maximum-matching capacity 404;
- `locked_100_plus_300_structurally_reachable=true` and structural deficit 0;
- zero labels, no independent attestation and `promotion_authorized=false`.

The v2 task-manifest SHA-256 is
`fa96f09d197f9d216eee599ef7b635825d38e5de824e0f017eabf4bd68b0ece6`;
the reviewer CSV SHA-256 is
`b8a95fbfc077b23fe7c321645a5086da379988d2dda7122191e15a87da8c62f2`;
the HTML workstation SHA-256 is
`1561676c4160ddb467c48d5602472f2d5f01d846b50616f42f86f01cc449fed6`.
The unlabelled validator returns `PASS` for structure and leakage, while
`--require-complete` remains fail-closed until every selected task has an
independent label and evidence note. This closes the statistical-capacity gap;
it does not manufacture ground truth or guarantee the eventual class balance.

The old 41-task second-reviewer subset is tied to the rejected v1 manifest and
is historical only. A fresh blinded overlap must be generated from the
completed v2 primary review. The executable agreement stop gate remains:
identity raw agreement >=95% with Cohen's kappa >=0.85 and pricing-admission
raw agreement >=90% with kappa >=0.80, with every disagreement adjudicated.

## Candidate product-card evidence integration

The retained HTTP journal contains 22 `product_page` requests with only eight
distinct URLs. All are seed/KEMP cards; no competitor detail card had
previously been fetched. The nine v21 additions are bounded search-listing
captures, not product-detail enrichment. Consequently, missing candidate
description, condition, package quantity and fitment remain `UNKNOWN`; the
reviewer must open the source card or keep pricing admission at manual review.

A read-only replay of the eight distinct retained product pages found seven
readable `ProductCardPageQuery` documents and one explicit schema failure. In
the seven readable documents Prom stores the actual detail table in
`product.attributes`, not in the legacy `product.characteristics` location.
Before the fix the normalized coverage was 0/7; after parser adapter v4 it is:

- characteristics: 7/7, 59 retained scalar attribute values;
- explicit condition: 7/7;
- MPN: 5/7;
- category caption: 7/7;
- public-number exact verification against the known public seed identity:
  6/7;
- one remaining row uses a private `776...` shelf code as its catalog lookup
  value and correctly fails closed instead of promoting that code to OE.

The acquisition boundary now performs a second, bounded pass over at most
`max_sellers` distinct external sellers after search/matching selection. It:

- fetches only the deterministic shortlist, never every result page row;
- verifies both Prom product ID and seller ID before merging any field;
- retains listing-time price, availability, title and seller identity unchanged;
- merges only non-monetary detail evidence;
- binds the normalized fields to the exact product-card response SHA-256 and
  the HTTP journal;
- records `SUCCESS`, `SUCCESS_WITH_CONFLICTS`, `FAILED` or `NOT_SELECTED`
  explicitly, including schema drift and identity mismatch;
- preserves a listing candidate when detail retrieval fails instead of turning
  the failure into an empty market;
- permits automatic eligibility only for an exact, selected, conflict-free
  `SUCCESS` binding whose URL, product ID, seller ID and SHA-256 all validate;
- re-verifies the retained raw-evidence manifest and requires a matching
  `product_page` HTTP-journal entry with the same prepared URL and payload
  SHA-256, so forged or stale structured detail metadata cannot become
  automatic evidence by itself.

This closes the code-path gap, not the representative-market accuracy gate. No
new live request, database write, migration or paid model call was made while
implementing it; measured competitor detail coverage remains zero until the
next authorized/replayable acquisition.

## Luna admission, vision and citation grounding (through prompt v3.1)

The post-parser Luna layer is now enforced as a conservative semantic veto,
not as an authority that can manufacture automatic pricing evidence. Before
this hardening, a structurally valid high-confidence `MATCH` could fill an
otherwise `UNKNOWN` required dimension in `dimension_findings`; if the other
runtime checks passed, that model assertion could contribute to `ADMITTED`.
That violated the service's own stated boundary that the model is an
additional gate and cannot override missing deterministic proof.

The v2.5 boundary now requires all of the following before pricing admission:

- `comparability_hard_gate_result == PASS`;
- `automatic_eligible == true` from the deterministic evidence layer;
- the pre-existing seller, source-provenance, availability, OE/cross,
  ownership, condition and cohort checks;
- every required commercial/category dimension to be proven by captured
  deterministic evidence or the deterministic semantic matrix.

Luna can still veto a pair through `NOT_MATCH`, hard-stop conflicts or a
dimension conflict. Its positive `MATCH` findings can no longer turn an
unknown package quantity, unit basis, fitment or category-specific technical
field into automatic evidence. A deterministic `REJECT` is explicitly
`EXCLUDED`; a missing or manual deterministic result remains
`MANUAL_REVIEW`.

Diagnostic `SUPPORTS` or `CONFLICTS` image claims now also require at least one
structured `IMAGE` evidence reference whose value is the exact input image URL.
A model cannot emit a bare visual conclusion, cite an absent/foreign URL or use
an URL-only image as durable evidence. Non-diagnostic or absent images remain
`NON_DIAGNOSTIC`/`UNAVAILABLE`; images remain supporting/veto evidence and never
prove identity by similarity alone.

The image hash trust boundary was also made explicit. Marketplace/parser
fields such as `image_hashes`, `image_sha256` or a nearby page
`content_sha256` are ignored for authority even when they look syntactically
valid. The only accepted binding is a server-authored
`verified_image_evidence` row obtained from the same scrape target's immutable
HTTP journal. Before use, the compressed `ScrapeEvidenceBlob` is decompressed,
its media type must be `image/*`, its byte length must match and SHA-256 is
recomputed over the retained bytes. The exact URL, blob and logical request are
then included in the model snapshot and cache identity. Corrupt blobs, HTML
responses, untrusted hashes and unhashed remote URLs fail closed.

Textual negative evidence is now grounded with the same fail-closed discipline.
Every non-image evidence reference must resolve to an exact dot path under its
declared `our_product`, `candidate`, `deterministic_context`,
`deterministic_evidence` or `verified_cross_edge` source. Its value and optional
excerpt must occur at that resolved field after Unicode/whitespace
normalization. A model cannot reject a pair using a field, value or quote that
is absent from the immutable input snapshot.

Provider `NOT_MATCH` now requires at least one evidenced hard-stop conflict;
every conflict finding needs evidence, and each hard stop must cite both owned
and candidate sides unless deterministic evidence, a verified cross plus the
candidate, or a hash-bound image supplies authority. Invalid citations persist
as a typed failed/manual review rather than excluding a potentially valid
candidate. Deterministic hard stops remain unaffected because they originate
inside the application and bypass provider-grounding validation.

Required-mode runtime reads and the run finalization barrier now reject stale
reviews as well. Reusability requires an exact match on contract version,
schema version, prompt version, provider, model and the complete model-settings
hash (including reasoning effort, image detail and image count). Filtering is
performed before selecting the newest review per observation, so a newer row
from an obsolete prompt cannot hide an older current-contract decision. The
calibration and recommendation paths request current-runtime reviews whenever
LLM comparability is required; historical rows remain available to reporting
instead of silently becoming current evidence.

Regression coverage includes adversarial outputs with 0.99 model confidence
that attempt to promote a non-eligible candidate or fill a missing unit basis,
plus diagnostic claims with no image, a foreign image, URL-only evidence,
marketplace-supplied fake hashes, corrupt retained bytes and HTML masquerading
as image evidence. Further cases cover invented JSON paths, values, excerpts,
one-sided hard stops, unsupported `NOT_MATCH` outputs and newer stale-prompt
rows attempting to shadow a current review. All fail closed. The focused
LLM/comparability/semantic/calibration/model suite completed with 732 passed
and 14 PostgreSQL environment skips. The final full backend suite completed
with 2,880 passed, 142 environment-dependent skips and three existing
Starlette deprecation warnings. Ruff and `git diff --check` were clean. No paid
model call, live request, migration or database write was performed for this
hardening.

## Frozen semantic seed alignment

The comparability review previously rebuilt `OUR_PRODUCT` from the live
`CatalogItem` row even for a bounded pricing run. Pricing itself used the
verified run-item start snapshot. An operator edit after run start could
therefore make Luna judge a different name, description, OE/MPN, applicability
or characteristic set than the seed that the calculation was replaying.

`pricing-run-scope-v3` now freezes the complete semantic seed alongside the
existing numeric and identity inputs:

- raw and normalized OE/MPN;
- name, brand, category and description;
- normalized part-number list and confirmed identity links;
- applicability brands/models;
- structured catalog characteristics.

Each field participates in the catalog/scope fingerprint. The LLM preparation
path resolves the same verified `FrozenCatalogItem` used by bounded execution;
legacy unbounded runs retain their live-row compatibility path. Older bounded
v2 snapshots remain readable but absent semantic fields default to empty and
therefore lose evidence/coverage instead of silently falling back to mutable
catalog data.

Mutation tests change each semantic input independently and require a different
scope hash. A separate replay test mutates the live description, applicability
and pin count after freezing and proves that execution still returns the
original values. The focused scope/frozen/comparability suite completed with
742 passed, 71 environment-dependent skips and one existing Starlette warning.

The v2.8 model input additionally carries a server-authored `seed_binding`.
For a bounded run it includes the scope contract version, verified run-item
start-snapshot SHA-256, catalog-snapshot SHA-256 and scope SHA-256; legacy
unbounded runs are explicitly marked `LEGACY_LIVE_CATALOG` with no borrowed
frozen hashes. The binding is part of the canonical input/cache hash, but is
not product-identity evidence. Therefore two reviews over visually identical
fields but different frozen seed snapshots cannot share a cached verdict.

The prompt/runtime identity was advanced from v2.7 to v2.8. Existing runtime
filters consequently keep every pre-binding v2.7 review as historical evidence
only: it cannot satisfy required-mode finalization, calibration or
recommendation reads. Regression tests prove both the frozen/live distinction
and cache-hash divergence after changing only `start_snapshot_sha256`. The
expanded comparability/scope/pricing regression completed with 861 passed and
30 PostgreSQL environment skips. The final full backend suite completed with
2,889 passed, 142 environment-dependent skips and three existing Starlette
deprecation warnings. Ruff and `git diff --check` were clean. No live request,
paid model call, migration or database write was performed for this hardening.

The current prompt/runtime identity is v2.9 with semantic extractor v12. This
prevents a review cached against the older text-only semantic matrix from being
treated as current after structured side, position, package, unit, year or body
facts begin affecting the input. The focused semantic/comparability/activation
set completed with 569 passed tests. The final backend suite completed with
2,897 passed, 142 environment-dependent skips and three existing Starlette
deprecation warnings. Ruff, compileall and `git diff --check` were clean. No
live request, paid model call, migration or database write was performed.

The preceding runtime identity was prompt v3.0 with semantic extractor v13. The
categorical normalization behavior is policy-hash-bound as
`comparability-categorical-v1`; current policy SHA-256 is
`ac14f867dc4e5102a912fee4227f1870430c4638a89e6ccca11fbb9b45c47262`.
Therefore evidence produced under the former string-equality policy cannot
silently satisfy the current gate. A replay of the 407 saved candidate pairs
retained the same 125 explicit hard stops (zero drift in that frozen capture);
the capture has `measure_unit` on 407/407 rows but none of the newly consumed
detail-only structured fields. The focused matching/semantic/evidence suite
completed with 728 passed tests. The final backend suite completed with 2,902
passed, 142 environment-dependent skips and three existing Starlette
deprecation warnings. Ruff, compileall and `git diff --check` were clean. No
network request, paid model call, migration or database write was performed.

The preceding runtime identity was prompt v3.1 with semantic extractor v14 and
condition classifier `yuri-v1-condition-v2`. On the frozen 407-pair replay,
explicit stops increased from 125 to 134. The nine net additions are dominated
by punctuation variants of used-condition evidence; saved rows 153, 187 and
190 pin respectively `Б.У`, full-versus-lower gasket scope, and a fan module
versus the base cooling-fan wording. Vehicle-make comparison yields 270 MATCH,
24 CONFLICT and 113 UNKNOWN states, but all 24 conflicts remain diagnostic and
non-hard. Because the replay lacks independent truth labels, this is measured
coverage change rather than a precision claim. The focused matching/semantic/
evidence suite completed with 779 passed tests. The final backend suite
completed with 2,913 passed, 142 environment-dependent skips and three existing
Starlette deprecation warnings. Ruff, compileall and `git diff --check` were
clean. No network request, paid model call, migration or database write was
performed.

The preceding runtime identity was prompt v3.2 with semantic extractor v15 and
condition classifier `yuri-v1-condition-v2`. On the frozen 407-pair replay,
the deterministic denominator remains unchanged at 134 hard-stop and 273
non-hard-stop pairs. Vehicle make yields 272 MATCH, 24 CONFLICT and 111 UNKNOWN;
vehicle model yields 140 MATCH, 17 CONFLICT and 250 UNKNOWN; the conservative
generation hint yields 10 MATCH, 2 CONFLICT and 395 UNKNOWN. The union contains
18 model/generation diagnostic-conflict rows, all non-hard. The Audi article
number false-positive discovered during the first replay was fixed before
acceptance and pinned by regression. Because the replay has no independent
truth labels, these figures prove deterministic coverage and non-expansion of
the hard gate, not production precision. The focused semantic/comparability/
matching suite completed with 727 passed tests. The final backend suite
completed with 2,918 passed, 142 environment-dependent skips and three existing
Starlette deprecation warnings. Ruff, compileall and `git diff --check` were
clean. No network request, paid model call, migration or database write was
performed.

The preceding runtime identity was prompt v3.3 with semantic extractor v17 and
condition classifier `yuri-v1-condition-v2`. On the frozen 407-pair replay,
the deterministic denominator is 135 hard-stop and 272 non-hard-stop pairs.
The sole new stopped pair is saved row 149: an explicit right shock absorber
versus an explicit left candidate, previously hidden by a stale template
description. Vehicle make yields 262 MATCH, 37 CONFLICT and 108 UNKNOWN;
vehicle model yields 163 MATCH, 26 CONFLICT and 218 UNKNOWN; generation hint
yields 10 MATCH, 2 CONFLICT and 395 UNKNOWN. Vehicle platform contributes 14
MATCH and 393 UNKNOWN states, including the formerly model-conflicting
Ducato-versus-Boxer/Jumper row 75; it is diagnostic and non-hard. The focused
semantic/comparability/matching suite completed with 737 passed tests. The
final backend suite completed with 2,928 passed, 142 environment-dependent
skips and three existing Starlette deprecation warnings. Ruff, compileall and
`git diff --check` were clean. No network request, paid model call, migration
or database write was performed.

The preceding runtime identity was prompt v3.3 with semantic extractor v19 and
condition classifier `yuri-v1-condition-v2`. The v18/v19 replay preserves the
frozen denominator at 135 hard-stop and 272 non-hard-stop pairs. Unit-basis
normalization changes evidence on already stopped rows without adding a new
stopped pair; three explicit unit-basis conflict occurrences remain. Compact
year extraction yields 31 MATCH, two CONFLICT and 374 UNKNOWN states. The two
conflicts are saved row 92 (`1981-1990` versus `1991-1997`) and row 319 (older
Passat/Golf/Audi ranges versus `2012-2022`); both remain non-hard. The focused
semantic/comparability/matching set completed with 674 passed tests. The final
backend suite completed with 2,936 passed, 142 environment-dependent skips and
three existing Starlette deprecation warnings in 413.72 seconds. Because the
407-pair replay has no independent truth labels, these figures prove
deterministic coverage and regression safety, not production precision. No
network request, paid model call, migration or database write was performed.

The preceding runtime identity was prompt v3.3 with semantic extractor v20 and
condition classifier `yuri-v1-condition-v3`. On the frozen 407-pair replay,
the deterministic denominator is 140 hard-stop and 267 retained pairs. The
five newly stopped saved rows are 14, 209, 332, 334 and 378: three explicit
`BU` used offers, one radiator-versus-bare-handle part-family contradiction and
one single-bushing-versus-explicit-set package contradiction. Every newly
stopped row was inspected individually. Among retained pairs, rows without an
extracted candidate part family fell from 21 to six (3, 87, 105, 108, 365
and 385).
Compact-year evidence remains 31 MATCH, two CONFLICT and 374 UNKNOWN states.
The customer-source graph contains six semantic-conflict private codes and 28
public-number fanout conflicts; the new private-code conflict is `77644736`,
where the two same-publisher XLS revisions explicitly disagree about a cooling
fan motor without versus with an impeller. The source revisions remain one
publisher lineage and are not counted as independent confirmation.

The full backend regression run exposed three new assertion-contract
mismatches and no production-code change was made in response. Direct matrix
inspection showed that generic bushing family equality must remain `UNKNOWN`
while explicit set/single, subtype and assembly differences still hard-stop
pricing; it also confirmed that the source identity graph intentionally stores
the structural subtype/assembly dimensions while the broader feature matrix
retains `included_components` as a commercial conflict. The three assertions
were corrected to match those fail-closed semantics. The expensive real-XLS
source assertion passed, the four directly affected semantic contracts passed
across 22 parametrized cases, and the complete semantic feature module passed
575 tests. Ruff, compileall and whitespace/diff checks are clean. Because the
replay has no independent truth labels, the 140/267 split
proves deterministic coverage and regression behavior, not production
precision. No network request, paid model call, migration or database write
was performed.

The current runtime identity is prompt v3.3 with semantic extractor v22 and
condition classifier `yuri-v1-condition-v3`. The frozen 407-pair replay remains
at 140 hard-stop and 267 retained pairs: v21 adds no automatic admission and no
new rejection. Retained rows 3 and 105 now carry the coarse families
`generic_hydraulic_pump` and `chassis_linkage`; both compare to their plausible
seed family as `UNKNOWN` with zero hard-stop conflicts. Missing candidate
part-family evidence falls from six rows to four (87, 108, 365 and 385), whose
titles genuinely identify only vehicle fitment, a generic guide, a generic
retainer or an unnamed small kit.

The accuracy-measurement boundary was also corrected. Rebuilding the frozen
review sources under family-safe locked-review v2 showed the old v1 capacity
claim was stale. A nine-query, one-page-per-query permitted discovery capture
added nine previously unused seed groups without prices, predictions, labels
or database writes. The resulting minimal v2 reviewer set has 405 tasks, 405
seed groups and exact seed/candidate bipartite capacity 404, so the 100/300
denominator is structurally reachable. It remains unlabelled and cannot prove
precision until independent domain review is complete.

Final v21 verification reproduced the frozen 407-pair denominator at exactly
140 deterministic hard stops and 267 retained candidates. Among retained rows,
only ranks 87, 108, 365 and 385 still lack a candidate part family. The complete
semantic feature module passed 580 tests, locked-review live-expansion passed
3 tests, and comparability acceptance passed 15 tests. Ruff, compileall and
whitespace/diff checks are clean. The final full backend suite completed with
2,976 passed, 142 environment-dependent skips and three existing Starlette
deprecation warnings in 384.92 seconds. This v21 cycle made nine bounded,
permitted Prom search requests to construct prediction-blind review evidence;
it made no paid-model call, migration or database write. These results verify
the implementation and measurement boundary, not production accuracy: the 405
tasks still require independent labels and the separate 200-product shadow
pilot remains mandatory.

## Verified Prom detail identity boundary

The original detail boundary in this report was `oe-extractor-v3`. A
detail-derived identifier can enter
identity verification only when the product URL, product id, seller id, exact
content SHA-256 and retained `product_page` journal entry all agree. The
candidate-native `motors.normalizedPartCode` is strong identity evidence;
detail MPN remains medium supporting evidence rather than an OE claim, and
detail-derived characteristics no longer inherit the listing capture's
provenance when their own card bytes are absent or invalid.

The current boundary is `oe-extractor-v5`. It records retained
`motors.compatibleOENumbers` as a separate
`PLATFORM_COMPATIBLE_REFERENCE_LIST`, never as the candidate's native OE. A
platform value can verify only when the acquisition route is already backed by
a confirmed one-hop cross and the retained detail provenance is valid. An
unconfirmed platform proposal remains `UNKNOWN`; a conflicting structured OE
continues to block. Supplier SKU, MPN, `normalizedPartCode`, and generic
`Код запчастини` remain separately auditable namespaces.

`oe-extractor-v5` additionally keeps short all-numeric values found only in
free-text title/description out of automatic identity, even when a seller
labels the token `OE:`. Structured OE/cross fields and provenance-verified
detail cards remain eligible; the free-text finding is retained for manual
review with an explicit reason code.

The same change fixes a measured numeric-boundary defect: 10- and 11-digit
numeric identifiers such as BMW and JP Group numbers were previously rejected
by the generic phone-number guard. They are now accepted only in structured,
provenance-bearing OE/MPN/detail fields; unanchored title and description phone
numbers remain rejected. Structured cross-number cells also separate an
explicit manufacturer prefix (`BMW 34211157046`) from the number while keeping
grouped identifiers such as `A 000 090 26 51` intact.

A non-monetary replay of nine freshly captured product cards parsed all nine
successfully. The new boundary classified eight selected search candidates as
`CONFLICT` and retained one as `UNKNOWN`; it produced zero automatic matches.
This is useful false-positive suppression evidence, not a production precision
estimate, because the nine rows have no independent truth labels. The focused
identity/detail/materialization/reenrichment suite completed with 63 passed and
three environment-dependent skips. Ruff and compileall passed. No paid model
call, migration or database write was made.

Verified detail cards now also retain a proposal-only bridge for one-hop Prom
motors compatibility. A proposal is created only when the card has a distinct
candidate-native normalized code and explicitly lists the current search OE
among `compatibleOENumbers`. The edge is persisted in `cross_candidates` with
its detail hash, source record and `automatic_identity_eligible=false`. Without
a confirmed `CrossLink`, it can only soften that one candidate-code conflict to
`UNKNOWN / OE_CROSS_AWAITING_CONFIRMATION`; it cannot produce `MATCH`, a
comparison identity key or pricing admission. Once the exact one-hop edge is
confirmed, the same candidate-native evidence can yield `VERIFIED_CROSS`.
Adversarial tests cover missing detail provenance, irrelevant compatible lists,
proposal-only abstention and confirmed-cross promotion. The focused suite now
passes 65 tests. None of the nine live probe rows contained its seed code in
the candidate card's compatible list, so their measured result correctly
remained eight conflicts and one unknown rather than being relaxed by an
unrelated compatibility claim.

## Remaining accuracy gate

The locked-set identity contract is now `comparability-review-identity-v2`.
The previous fingerprint combined strong identifiers with mutable titles and
full URLs, so the same seed OE under a rewritten title or the same Prom
`p<ID>` under another shop host/slug could enter the denominator twice. The v2
contract uses identifier precedence for the seed, canonical Prom product IDs
for listing identity and a separate OE/brand+SKU/brand+title candidate-family
fingerprint. Final truth permits at most one row per seed family and candidate
product family. The validator recomputes every fingerprint from frozen evidence
and rejects stale v1 sets or forged groups. Adversarial regression covers title,
host, slug, query and cloned-listing variants. The focused acceptance/reporting/
comparability suite completed with 637 passed. The final full backend suite
completed with 2,890 passed, 142 environment-dependent skips and three existing
Starlette deprecation warnings; Ruff and `git diff --check` were clean.

The automatic activation boundary is now semantic rather than hash-only. The
previous generic helper accepted any existing file whose configured SHA-256
matched, including a JSON document that explicitly said `approved=false`.
Comparability now requires a typed v1 activation artifact embedding a passing
locked 100/300 result, a passing 200-product shadow result, the exact current
Luna runtime identity, the family-safe locked-truth v2 contract and distinct
product/risk-owner approvals. Runtime revalidates every required gate and both
embedded canonical hashes; production preflight applies the same typed check.
An exact hash remains necessary but is no longer sufficient. The focused
activation/preflight/pricing suite completed with 98 passed and two existing
Starlette warnings. The final full backend suite completed with 2,895 passed,
142 environment-dependent skips and three existing Starlette warnings.

The current review prompt is `marko-product-comparability-v3.4`. It adds the
fuel-filter pressure contract and deterministically caps `VERIFIED_CROSS` to
`ACCEPTABLE_ANALOGUE` before both admission and persistence. The affected OE,
semantic, comparability and activation modules pass 687 tests. This prompt
change intentionally invalidates the older activation freeze; a new freeze
requires the still-missing independent locked labels and shadow evidence.

Production accuracy is still not proven. The locked acceptance denominator is
unchanged: an independent, non-overlapping set of exactly 100 true matches and
300 hard negatives, with separate pricing-eligible/ineligible labels, followed
by a 200-product shadow pilot. Until those labels exist, unblocked candidates
continue to Luna/manual review and pricing remains advisory.

The previous Luna freeze predates prompt `v3.1` and this semantic extractor
implementation. It remains historical evidence only; a new freeze is required
after the locked dataset is assembled.

Avto.pro and Exist.ua are implemented as Tier C fallback discovery routes, not
automatic cross authorities. The shared confirmation policy now has a direct
regression test: two Tier C findings still fail source confirmation, as do two
Tier B findings from the same correlation group. Source-only confirmation
requires one Tier A group or two distinct Tier B groups; a Tier C relation must
receive a persisted positive human review before a hash-bound run snapshot can
use it.

The source-confirmation boundary is now identical at write time and pricing
read time. A `source_confirmed` row requires confidence >=0.75, FACT support
with full evidence value, minimum reliability/extraction/directness/
independence floors, an authoritative compatible assessment without hard
rejections, explicit source text naming both normalized numbers, an unexpired
hash-matching source document, matching registered domains and a current
PERMITTED or OWNER_RISK_ACCEPTED source-policy version. A revoked, stale,
cross-workspace, expired or metadata-rebound document cannot be recorded as
source-confirmed and is re-proved again before inclusion in a frozen pricing
snapshot.

The downstream consumer boundary is also fail-closed per observation. A
`VERIFIED_CROSS` observation now requires a current effective semantic review
with `pricing_admission=ADMITTED` before either calibration or price
calculation can consume it, even when the global provider mode is `off` or
`shadow`. New replay traces freeze the exact observation IDs that required this
authority; old traces remain reproducible under their historical global-only
contract. Exact-OE observations are not forced through the cross-only rule.
The focused downstream regression set completed with 815 passed.
