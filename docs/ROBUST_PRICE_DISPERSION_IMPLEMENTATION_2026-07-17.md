# Robust Price Dispersion — implementation evidence

Дата проверки: 2026-07-17  
Scope: `median`, scaled IQR/MAD, Rousseeuw-Croux Sn/Qn, policy, engine, trace,
API, replay, validation и capacity.  
Canonical owner: `backend/src/metis/pricing`; `marko.pricing` остаётся
compatibility facade.

## A. Итог

```yaml
implementation_status: PASS
activation_status: NO_GO
pricing_v2_parity: PASS
pricing_v3_candidate: READY
activation_blockers:
  - synthetic decision diff contains one unsafe MANUAL_REVIEW_to_RAISE transition
  - no permitted representative market calibration dataset
  - PRICING_V3_ROBUST_DISPERSION_ENABLED defaults to false
```

`NO_GO` относится только к persisted production activation v3, а не к
готовности реализации. Side-effect-free evaluate, tests и replay позволяют
продолжить calibration без включения новой policy в pricing runs.

## B. Repo facts and drift

| Contract | Подтверждённый symbol/file | Baseline | Реализованный результат |
|---|---|---|---|
| Canonical kernel | `backend/src/metis/pricing` | Metis-owned | сохранено |
| Compatibility path | `backend/src/marko/pricing/__init__.py` | re-export | Sn/Qn objects также identity-equal |
| Legacy dispersion | `engine._dispersion` | `1.4826 * MAD / median` | перенесено в explicit `legacy_mad` profile path без изменения arithmetic order |
| Cleaning | `_clean_outliers` | IQR при `n>=8`, MAD при action-eligible smaller n | не изменено |
| Small n | `recommend_price` | `<3` insufficient; `3..4` manual | не изменено |
| Trace | `PricingRecommendation.calculation_trace` JSON | replay-v1 scalar fields | replay-v2 additive robust profile; schema migration не нужна |
| API | evaluate/stored recommendation | scalar dispersion | additive method/profile fields |
| Replay | `recommendation_replay.py` | only v1 | v1 + v2 |
| Cohort bound | pricing collector config | default max 10 sellers | сохранён; independent policy guard 500 |

Baseline перед изменениями: `249 passed in 2.07s`. Текущий каталог не содержит
Git metadata, поэтому `git status/diff` недоступны; контроль scope выполнен по
явному перечню изменённых файлов и полным проверкам.

## C. Mathematical implementation

### Order statistics

`_order_statistic(A, k)` использует 1-based rank без усреднения. Для even `n`:

```text
low_median rank  = (n + 1) // 2
high_median rank = n // 2 + 1
```

Input новых scale helpers материализуется один раз, проверяется на empty и
non-finite Decimal до сортировки. Generic scale допускает отрицательные
значения; price profile требует все `x_i > 0` и positive median.

### Common Gaussian scale

```text
IQR_sigma = raw_IQR / 1.348979500392163
MAD_sigma = raw_MAD * 1.482602218505602
Sn        = c_n * 1.1926 * lowmed_i(highmed_j(|x_i-x_j|))
Qn        = d_n * 2.219144465985076 * OS_k({|x_i-x_j|: i<j})
k         = choose(floor(n/2)+1, 2), 1-based
```

Sn включает `j=i`. Qn не включает self-pairs. Historical Qn constant `2.2219`
объявлена только как provenance witness и не используется новым profile.
Finite corrections versioned как `robustbase-modern-v1`; Qn при `n>=13`
умножается на `1/f_n`, то есть делится на `f_n` ровно один раз.

### Profile and domain behavior

`RobustDispersionProfile` frozen/slots и содержит raw IQR/MAD, четыре normalized
scales/CV, selected method/scale/CV, min/max/span/median CV и explicit
degeneracy flags. Mapping values read-only. Decimal сериализуется строками.

- `pre_clean`: после eligibility, normalization и seller dedup;
- `post_clean`: cleaned decision cohort;
- fair price: по-прежнему median `post_clean` cohort;
- `pricing-v2`: selected `legacy_mad` с exact `1.4826`;
- `pricing-v3-robust-dispersion`: default selected `qn`;
- partial scale degeneracy: v3 `MANUAL_REVIEW`;
- all scales zero: valid zero dispersion, не ложная partial degeneracy;
- complexity: exact Sn `O(n^2 log n)`; exact Qn `O(n^2 log n)` и `O(n^2)` pair storage.

## D. Changed files

```text
backend/src/metis/pricing/statistics.py
  -> exact Decimal scale algorithms, constants, corrections, profile/trace serialization
  -> public behavior: new scale API

backend/src/metis/pricing/types.py
  -> RobustScaleMethod, RobustDispersionProfile, policy/result fields and validation
  -> public behavior: explicit versioned policy contract

backend/src/metis/pricing/engine.py
  -> pre/post profiles, v2/v3 selection, capacity and partial-degeneracy gates
  -> public behavior: additive diagnostics; v2 scalar parity

backend/src/metis/pricing/__init__.py
backend/src/marko/pricing/__init__.py (unchanged facade, verified by identity test)
  -> public package exports

backend/src/marko/services/market_collection.py
  -> recommendation-replay-v2 trace persistence

backend/src/marko/services/recommendation_replay.py
  -> v1 compatibility and v2 method/profile/version/constants comparison

backend/src/marko/services/pricing_runs.py
backend/src/marko/core/config.py
.env.example
compose.yaml
deploy/compose.production.yaml
  -> policy round-trip and disabled-by-default v3 persisted-run feature flag

backend/src/marko/api/schemas/pricing.py
backend/src/marko/api/routers/v1/pricing.py
  -> additive dispersion_method/dispersion_profile output and OpenAPI schema

backend/tests/fixtures/robust_scale_oracle_v1.json
backend/tests/test_robust_dispersion.py
backend/tests/test_robust_dispersion_engine.py
backend/tests/test_robust_dispersion_variations.py
backend/tests/test_pricing_api.py
backend/tests/test_recommendation_replay.py
backend/tests/test_metis_boundary.py
  -> oracle, unit/property/integration/API/replay/boundary coverage

scripts/benchmark_robust_dispersion.py
scripts/validate_robust_dispersion_decision_diff.py
scripts/run_robust_dispersion_mutation_probes.py
  -> reproducible capacity, behavior-diff and mutation evidence

README.md
docs/architecture.md
docs/kemp_pricing_engine.md
docs/ROBUST_PRICE_DISPERSION_IMPLEMENTATION_2026-07-17.md
  -> synchronized contracts and rollout status
```

DB columns не добавлялись: scalar `dispersion` остаётся indexed/durable decision
value, полный diagnostic profile хранится в существующем immutable JSON trace.

## E. Tests and validation

| Check | Command / method | Result | Evidence |
|---|---|---|---|
| Baseline | `PYTHONPATH=src .venv/bin/python -m pytest -q` до edits | PASS | 249 passed |
| Golden/order/property | pricing statistics + robust tests | PASS | vectors A/B/C; even low/high median; invalid/non-finite; invariants |
| Full variation | 13 sizes x 7 positive shapes x 3 orders x 4 Decimal scales plus left-skew generic | PASS | deterministic matrix test |
| Engine integration | robust engine + legacy engine/matrix | PASS | pre/post, dedup, small-n, ties, capacity, v2/v3 |
| API/OpenAPI | pricing API tests + `app.openapi()` | PASS | 31 paths; both additive fields present |
| Replay | replay tests | PASS | v1 exact; v2 exact; method/version/constant mutation mismatch |
| Boundary | Metis/Marko identity | PASS | policy, enum, Qn and engine are same objects |
| Full backend | `PYTHONPATH=src .venv/bin/python -m pytest -q` | PASS | 323 passed |
| Compile | `python -m compileall -q src tests` | PASS | no output/errors |
| Lint | `/opt/anaconda3/bin/ruff check backend/src backend/tests scripts` | PASS | all checks passed |
| Mutation probes | `scripts/run_robust_dispersion_mutation_probes.py` | PASS | 8/8 killed; temp copies only |
| Benchmark | `scripts/benchmark_robust_dispersion.py --repeats 5` | PASS | exact through n=500 |

### Independent oracle

R отсутствовал в execution environment, поэтому live `robustbase` call не
выполнялся и production dependency не добавлялась. Проверка использует два
независимых слоя:

1. hand-derived order-statistic witnesses, включая Sn `[0,1,2]` и Qn `n=2`;
2. checked-in golden fixture с package/version, commands, constants,
   finite-correction mode, date и explicit `live_r_check_in_this_run=false`.

Primary source code `robustbase 0.99-7` был отдельно проверен: corrected Qn
constant, tables и `r / Qn.finite.c(n)` совпадают с implementation contract.

### Mutation probes

Все восемь required mutations убиты targeted tests:

1. Qn zero-based `k`;
2. Qn self-pairs;
3. Sn without self-distance;
4. Sn averaged inner median;
5. Qn `2.2219` substitution;
6. Qn multiply by `f_n`;
7. CV divided by mean;
8. decision profile before seller dedup.

## F. Decision diff

Dataset: `synthetic_contract_matrix_v1`, 12 cases.

```yaml
same: 10
auto_to_manual: 1
manual_to_auto: 1
other: 0
unsafe_relaxation_count: 1
gate_status: PASS
activation_status: NO_GO
```

Changed cases:

- `partial_degeneracy`: v2 `RAISE` -> v3 `MANUAL_REVIEW`; expected conservative
  change from the new fail-closed gate;
- `two_clusters`: v2 `MANUAL_REVIEW` -> v3 `RAISE`; Qn is driven by small
  within-cluster distances (`qn_cv≈0.021`) while MAD/IQR/Sn remain large. This
  is an unsafe relaxation and proves that `max_dispersion` is not automatically
  calibrated for Qn.

The matrix is complete and explained, so STEP 05 gate itself passes. Activation
does not pass.

## G. Replay/API compatibility

- persisted v1 traces are accepted and compared only against their old fields;
- new traces use `recommendation-replay-v2`;
- v2 compares scalar dispersion, selected method, pre/post serialized profile,
  profile version, correction version, finite-correction flag and constants;
- deliberate method/version/constant drift produces field-level mismatch;
- evaluate response adds `dispersion_method` and `dispersion_profile`;
- stored recommendation response reads the same values from immutable trace;
- old consumers remain compatible because fields are additive;
- no historical dispersion backfill or DB rewrite is performed.

## H. Performance

Environment: Python 3.13.9, macOS arm64, Decimal precision 28, five repeats,
median wall time; no network/DB.

| n | Sn ms | Qn ms | Full profile ms | Pair count |
|---:|---:|---:|---:|---:|
| 10 | 0.021 | 0.011 | 0.045 | 45 |
| 25 | 0.116 | 0.070 | 0.205 | 300 |
| 50 | 0.482 | 0.315 | 0.823 | 1,225 |
| 100 | 2.043 | 1.449 | 3.648 | 4,950 |
| 250 | 14.587 | 11.926 | 27.956 | 31,125 |
| 500 | 70.566 | 64.243 | 152.345 | 124,750 |

Validated exact ceiling is 500: this means completion under the measured
environment, not a universal latency SLO. Normal production collection is
bounded at 10 sellers. Direct evaluate inputs and future adapters are protected
by `robust_scale_max_cohort_size=500`; exceeding it returns
`ROBUST_SCALE_CAPACITY_EXCEEDED` and never samples/falls back silently.

## I. Residual risks

```yaml
known_limitations:
  - exact Qn retains O(n^2) pair memory
  - max_dispersion is not calibrated for Qn on representative marketplace cohorts
  - two-cluster distributions can make Qn much smaller than peer estimators
unverified_assumptions:
  - no live R robustbase parity in this run
  - no permitted representative decision-diff dataset
  - benchmark timings are machine-specific and are not a service SLO
business_policy_needing_calibration:
  - Qn max_dispersion threshold
  - whether and where estimator-disagreement should become an action gate
  - explicit approval to enable PRICING_V3_ROBUST_DISPERSION_ENABLED
not_in_scope:
  - changing fair-price median
  - replacing existing IQR/MAD outlier cleaning
  - changing matching, source permission, tier normalization or economic rules
  - database backfill, deployment, commit or push
```

## J. Final self-audit

### Mathematics

- [x] yes — Qn uses only `i < j`; n=2 witness and mutation probe.
- [x] yes — `k=choose(floor(n/2)+1,2)`, 1-based; order-stat tests/probe.
- [x] yes — Sn includes `j=i`; `[0,1,2]` witness/probe.
- [x] yes — Sn inner high / outer low median; even-median tests/probe.
- [x] yes — corrected Qn constant separated from historical constant.
- [x] yes — finite corrections applied once.
- [x] yes — Qn `n>=13` divides by `f_n`; direction test/probe.
- [x] yes — IQR/MAD normalized before comparison.
- [x] yes — CV divides by positive median; mean mutation probe.

### Domain safety

- [x] yes — fair price remains median.
- [x] yes — seller dedup precedes both profiles.
- [x] yes — small-n abstention unchanged.
- [x] yes — v3 partial degeneracy blocks automatic action.
- [x] yes — all-zero profile is not partial degeneracy.
- [x] yes — existing quality/economic/action gates remain active.

### Compatibility

- [x] yes — pricing-v2 regression suite and scalar formula parity pass.
- [x] yes — old config without new fields resolves to `legacy_mad`.
- [x] yes — replay v1 supported.
- [x] yes — replay v2 compares profile and versions.
- [x] yes — no backfill/migration.

### Engineering

- [x] yes — new core scale math uses Decimal only.
- [x] yes — low/high median confusion is tested and mutated.
- [x] yes — Qn constant typo is tested and mutated.
- [x] yes — wrong finite-correction direction is tested and mutated.
- [x] yes — full suite and lint pass.
- [x] yes — benchmark completed through n=500.
- [x] yes — README, architecture and pricing docs synchronized.
- [x] yes, with limitation — no Git metadata; explicit scoped inventory and
  full project checks found no unrelated code change.

## Sources

1. P. J. Rousseeuw, C. Croux (1993), *Alternatives to the Median Absolute
   Deviation*: <https://wis.kuleuven.be/stat/robust/papers/publications-1993/rousseeuwcroux-alternativestomedianad-jasa-1993.pdf>
2. KU Leuven robust-statistics publication index:
   <https://wis.kuleuven.be/stat/robust/papers-1990-1999>
3. `robustbase` reference manual:
   <https://stat.ethz.ch/CRAN/web/packages/robustbase/robustbase.pdf>
4. `robustbase` Qn/Sn source:
   <https://rdrr.io/cran/robustbase/src/R/qnsn.R>
