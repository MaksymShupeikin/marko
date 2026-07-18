# KEMP-normalized pricing engine

Этот документ описывает фактически реализованный pricing-контур Marko для
секций 3.2–3.6: cross-tier normalization, robust fair price, confidence,
recommendation modes и economic priority. Каноническая реализация находится в
`backend/src/metis/pricing/`; orchestration — в
`backend/src/marko/services/market_collection.py` и
`backend/src/marko/services/pricing_runs.py`.

## 1. Инварианты

- Все цены, коэффициенты, пороги и persisted scores используют `Decimal` /
  PostgreSQL `NUMERIC`. `float` применяется только внутри `log`, `exp`, `sqrt`
  и half-life transform с немедленным возвратом в `Decimal`.
- Рыночная fair price не зависит от себестоимости, текущей закупки или курса.
- Один продавец даёт максимум один голос на SKU и один голос на tier внутри
  paired-OE calibration unit.
- Один OE даёт максимум один ratio для `(category, tier, OE)`.
- Used, owned seller, stale/unavailable, weak match/tier/source и conflicting
  observations сохраняются как evidence, но не участвуют в центре рынка.
- Fresh item никогда автоматически не получает `LOWER`.
- Любое `RAISE`/`LOWER` требует прохождения всех action gates.
- Below-cost цена допустима только для `dead_stock`, только с append-only
  authorization, подтверждённым предупреждением и абсолютным floor.
- Recommendation, evidence, context, policy и coefficient versions сохраняются
  так, чтобы расчёт можно было воспроизвести без изменившегося runtime state.

## 2. Domain boundaries

Чистый pricing domain не зависит от FastAPI, SQLAlchemy, Celery или Flutter:

```text
ProductPricingContext
+ CompetitorOffer[]
+ TierCoefficient[]
+ PricingPolicy
        |
        v
recommend_price(...)
        |
        v
PricingResult
```

Модули:

- `metis/pricing/types.py` — canonical contracts и versioned policy;
- `metis/pricing/statistics.py` — median, percentile, raw/scaled MAD и IQR,
  exact Rousseeuw-Croux Sn/Qn, versioned finite corrections, winsorization,
  effective sample size, geometric mean и tick rounding;
- `metis/pricing/calibration.py` — simple median и hierarchical shrinkage;
- `metis/pricing/tiering.py` — tier classification contract;
- `metis/pricing/engine.py` — eligibility, normalization, fair price, confidence,
  modes, priority и invariant enforcement;
- `metis/pricing/observability.py` — low-cardinality structured events.

## 3. Calibration dataset

Calibration unit — независимый paired OE, не listing:

\[
P_{u,ref}=\operatorname{median}(\text{seller-deduplicated KEMP/Budget prices})
\]

\[
P_{u,\tau}=\operatorname{median}(\text{seller-deduplicated tier }\tau\text{ prices})
\]

\[
r_{u,g,\tau}=\frac{P_{u,\tau}}{P_{u,ref}},\qquad
l_{u,g,\tau}=\log r_{u,g,\tau}
\]

Quality weight:

\[
a_u=match_u\times tier_u\times source_u\times freshness_u
\]

\[
n_{eff}=\frac{(\sum a_u)^2}{\sum a_u^2}
\]

Несколько listings одного продавца сначала схлопываются. Несколько listings
одного OE затем становятся одной calibration point через robust median.

### 3.1 Simple robust category median

\[
\hat l_{g,\tau}=\operatorname{median}(l_{u,g,\tau}),\qquad
m_{g,\tau}=\exp(\hat l_{g,\tau})
\]

Коэффициент валиден только при достаточных `sample_size` и `n_eff`, положительном
multiplier, существующем uncertainty interval и допустимой ширине interval.
Невалидный коэффициент сохраняется, но offer получает
`UNVALIDATED_TIER_COEFFICIENT` и не влияет на recommendation.

### 3.2 Hierarchical shrinkage in log space

Global prior считается отдельно для каждого tier и исключает target category:

\[
l^{global}_{-g,\tau}=\operatorname{median}
\{l_{u,g',\tau}:g'\neq g\}
\]

\[
w_{g,\tau}=\frac{n_{eff,g,\tau}}{n_{eff,g,\tau}+k_\tau}
\]

\[
\log m_{g,\tau}=w_{g,\tau}l^{local}_{g,\tau}
+(1-w_{g,\tau})l^{global}_{-g,\tau}
\]

Fallback branches реализованы явно:

1. local + global sufficient — shrinkage;
2. local sufficient, global insufficient — local robust estimate с пониженной
   confidence;
3. local sparse, global sufficient — strongly shrunk global fallback, если
   policy разрешает;
4. local + global insufficient — unvalidated, automatic normalization запрещена.

### 3.3 Защита от leakage

Run сначала фиксирует полный paired-OE dataset и его SHA-256 hash, затем обе
модели coefficients, и только после этого выпускает calculation tasks. Если
target OE участвовал в run calibration, для его рекомендации коэффициент
пересчитывается с `exclude_oe_norm=target`, то есть leave-one-OE-out. Если после
исключения безопасного коэффициента нет, cross-tier observations не используются
и engine abstains.

`coefficient_version`, `dataset_hash`, `excluded_oe_norm`, sample sizes,
intervals и validation reasons входят в immutable trace.

### 3.4 Model comparison

| Criterion | Simple robust median | Hierarchical shrinkage |
|---|---|---|
| Explainability | Максимальная: median ratios | Средняя: local + prior + weight |
| Sparse-category stability | Низкая/средняя | Высокая при хорошем global prior |
| Implementation complexity | Низкая | Средняя |
| Data requirement | Category pairs | Category + cross-category tier history |
| Risk of overfitting | Низкий при hard gates | Контролируется LOO prior и versioned `k` |
| Global fallback | Нет | Да, leave-one-category-out |
| Version stability | Резкие изменения около sample gate | Плавнее на long tail |
| MVP suitability | Предпочтительный benchmark/default | Challenger после validation |
| Production suitability | Контрольная модель и diagnostic | Предпочтительный default после holdout |

Обязательный итог:

- MVP default: simple robust category median with hard validation gates and
  abstention.
- Production default: hierarchical log-space shrinkage with
  leave-one-category-out prior, versioned `k`, frozen coefficient snapshot,
  uncertainty validation, and simple median as benchmark.

Текущий `PricingPolicy` настроен на production path (`coefficient_model =
shrinkage`), но каждый run может явно выбрать `simple_median`; barrier всегда
сохраняет обе модели для benchmark/diagnostics.

## 4. Normalization to KEMP level

Для валидного cross-tier offer:

\[
\tilde q_{ij}=\frac{q_{ij}}{m_{g(i),\tau_{ij}}}
\]

Пример:

```text
OEM raw price       = 2400 UAH
OEM/KEMP multiplier = 2.4
KEMP-equivalent     = 1000 UAH
```

- Direct KEMP и Budget используют `m = 1`.
- `m <= 0` отклоняется.
- `m < 1` по умолчанию не масштабируется вверх; offer исключается как
  `LOWER_TIER_EXCLUDED`.
- Direct KEMP может участвовать в cohort и только уменьшать raise target как
  ceiling. Он никогда не повышает recommendation.
- Explicit dumping сохраняется, но исключается. Дополнительный dumping inference
  возможен только при наличии минимум трёх независимых direct-KEMP sellers и
  сравнивает KEMP с KEMP, а не с ценой клиента или другим tier.

Каждый использованный offer хранит raw price, tier, multiplier, coefficient
model/version/sample/confidence/hash, normalized price, match/tier/source
confidence, age, source и listing URL.

## 5. Robust fair price

После eligibility, normalization и seller deduplication:

- `< 3` unique sellers: `INSUFFICIENT_DATA`, fair price отсутствует;
- `3..n_min_action-1`: descriptive median разрешена, automatic action запрещён;
- `n >= iqr_min_competitors`: IQR cleaning;
- иначе при `n >= min_competitors`: MAD cleaning.

IQR:

\[
IQR=Q_3-Q_1,\quad
[L,U]=[Q_1-1.5IQR,\ Q_3+1.5IQR]
\]

MAD:

\[
M=median(Q),\quad MAD=median(|q-M|)
\]

\[
z_j=0.6745\frac{|q_j-M|}{MAD}
\]

При `MAD = 0` деления нет: применяется
`max(minimum_absolute_tolerance, M * mad_zero_tolerance)`.

Primary estimator всегда:

\[
P^*=median(Q_{clean})
\]

Arithmetic mean не используется как primary estimator. P10/P90 winsorization
служит только sensitivity diagnostic:

\[
sensitivity=\frac{|P^*-P_{winsor}|}{P^*}
\]

Превышение tolerance блокирует automatic action с
`ESTIMATOR_SENSITIVITY`. UI range — Q1/Q3 cleaned cohort.

### 5.1. Versioned robust dispersion profile

Fair-price location не изменилась: `P*` остаётся median cleaned
seller-deduplicated cohort. Отдельный scale profile вычисляется дважды:

1. `pre_clean` — после eligibility/normalization/seller dedup;
2. `post_clean` — на cohort, из которого берётся `P*`.

На одной Gaussian-consistent шкале сохраняются:

\[
IQR_\sigma=\frac{Q_3-Q_1}{1.348979500392163},\qquad
MAD_\sigma=1.482602218505602\,MAD
\]

\[
S_n=c_n\,1.1926\,\operatorname{lowmed}_i
\left(\operatorname{highmed}_j |x_i-x_j|\right)
\]

\[
Q_n=d_n\,2.219144465985076\,OS_{\binom{\lfloor n/2\rfloor+1}{2}}
\{|x_i-x_j|:i<j\}
\]

Sn включает self-distance, использует inner high median и outer low median.
Qn использует только `i < j`, 1-based rank и corrected constant; historical
`2.2219` не используется под новым version ID. Finite corrections соответствуют
`robustbase-modern-v1`; для Qn при `n >= 13` результат делится на `f_n`.

Policy paths разделены явно:

- `pricing-v2`: `legacy_mad`, то есть прежний
  `1.4826 * raw_MAD / median`; scalar output и replay-v1 не переопределяются;
- `pricing-v3-robust-dispersion`: default `qn`; scalar `dispersion` равен
  corrected `Qn / median`, а остальные estimators остаются diagnostics.

Если часть scales равна нулю, а часть положительна, v3 блокирует automatic
action с `ROBUST_SCALE_PARTIAL_DEGENERACY`. Полностью равный independent-seller
cohort является валидным zero-scale case. Exact implementation ограничена
`robust_scale_max_cohort_size=500`; production collector имеет более строгий
default bound `pricing_scraper_max_sellers=10`.

## 6. Confidence and hard gates

Positive quality factors лежат в `[0,1]`:

- coverage — logarithmic transform от weighted `n_eff`;
- dispersion — `1 - selected_post_clean_robust_cv / max_dispersion`;
- freshness — Q1 истинного half-life score `2^(-age/half_life)`;
- match — Q1 match confidence;
- tier — Q1 `tier_confidence * coefficient_confidence`;
- source — Q1 source confidence.

Default aggregation — weighted geometric mean:

\[
C=\exp\left(\frac{\sum w_k\log(\max(\epsilon,s_k))}{\sum w_k}\right)
\]

Policy также поддерживает conservative `minimum`. Factor scores никогда не
вычитаются. Даже высокий aggregate не скрывает слабый factor: каждый factor
имеет hard floor. Automatic action требует одновременно:

- no severe data-health issue;
- enough cleaned sellers;
- enough `n_eff`;
- aggregate confidence >= `confidence_min`;
- каждый factor >= собственному floor;
- sensitivity <= tolerance.
- для non-legacy policy нет partial robust-scale degeneracy.

Grades `A/B/C/MANUAL` — evidence grades, не probability of correctness.

## 7. Recommendation modes

### 7.1 Fresh / unknown

Fresh и unknown работают raise-only. Raise рассматривается, только если:

\[
P^*>p(1+min\_raise\_threshold)
\]

Target:

\[
R=\min(P^*\cdot safety\_discount,\ p(1+max\_raise\_step),\ Q_1,
direct\_KEMP\_ceiling)
\]

Неактивное изменение меньше `min_action_change` превращается в `HOLD`.
`unknown` дополнительно помечается reason code и никогда не получает markdown.

### 7.2 Stale / dead stock

Lower market — versioned quantile cleaned cohort. Markdown:

\[
target=(1-\beta)p+\beta\min(p,Q_{lower})
\]

- stale использует `stale_markdown_beta`;
- dead stock — `dead_stock_markdown_beta`;
- `liquidity_target` может увеличить beta в `[0,1]`.

Обычный floor:

\[
floor=cost(1+minimum\_margin)
\]

Below-cost path требует всех полей authorization: override id, user, timestamp,
reason, warning confirmation и absolute floor. Окончательная цена округляется к
versioned price tick и не может пересечь floor. Решение оператора повторно
проверяется API и сохраняет cost/recommended/floor/context/policy snapshots.

## 8. Economic priority

Raise с доступными sales:

\[
priority=(R-p)\times monthly\_units\times C\times urgency\times manual\_priority
\]

Sales hierarchy:

1. rolling 30/60/90-day units;
2. historical monthly units с half-life по days since last sale;
3. views × calibrated conversion proxy;
4. stock exposure proxy;
5. dimensionless relative-gap proxy.

Каждый fallback имеет явный `priority_score_type` и unit. Proxy не выдаётся за
UAH/month.

Clearance:

\[
inventory\_value=p\times qty
\]

\[
age\_weight=clip(age/age\_reference,\ min,\ max)
\]

\[
clearance\_priority=inventory\_value\times age\_weight\times C
\times deadstock\_factor\times manual\_priority
\]

Отдельно сохраняется `cost_basis_inventory_value = cost * qty`, но он не
подменяет business-defined retail inventory value.

Manual-review queue:

\[
review\_priority=capital\_lock\times(1-C)\times deadstock\_factor
\times manual\_priority
\]

Flutter показывает отдельные queues: raise opportunity, clearance/capital,
manual review, hold и grouped all. Raw scores разных единиц не смешиваются в
одном рейтинге.

## 9. Versioned policy defaults

Основные defaults `pricing-v2`:

| Group | Default |
|---|---|
| Currency / age | `UAH`, max age 72h |
| Eligibility | match 0.70, tier 0.60, source 0.50 |
| Samples | min 5, effective min 3, IQR from 8 |
| Confidence | geometric, min 0.55, factor floors 0.40 |
| Freshness | half-life 24h |
| Robustness | MAD z 3.5, relative MAD-zero tolerance 2%, sensitivity 5% |
| Calibration | category min 8, effective min 5, global min 20, `k=10` |
| Raise | threshold 5%, safety 95%, max step 15%, min action 2% |
| Markdown | stale beta 0.50, dead beta 1.00, lower quantile 25% |
| Price | integer UAH tick, version `uah-integer-v1` |
| Priority | age reference 365d, dead-stock factor 1.5 |

Policy constructor rejects non-finite values, invalid currency, probability
outside `[0,1]`, thresholds below 3, IQR threshold below minimum sample,
non-positive half-life/tick/dispersion/`k`, negative margin, invalid quantiles and
incomplete factor maps.

## 10. Persistence and run workflow

```text
catalog snapshot
  -> PricingRun + idempotent PricingRunItem per SKU
  -> rate-limited collection queue
  -> raw capture + MarketObservation + append-only classification
  -> run-level barrier
  -> frozen TierCalibrationPair records + dataset hash
  -> simple + shrinkage TierCoefficient records
  -> selected coefficient snapshot frozen
  -> calculation queue with target leave-one-OE-out protection
  -> immutable PricingRecommendation + calculation trace
  -> append-only RecommendationDecision
```

Run/item claims use row locks, task ids, unique idempotency keys, checkpoints and
terminal-state checks. Duplicate delivery reuses capture/recommendation records.
Retry after a successful capture resumes from the persisted checkpoint instead
of scraping again.

Migration `20260716_0006_kemp_pricing_engine.py` adds run calibration snapshots,
coefficient versions/selection, evidence counts, outlier/sensitivity/action-gate
fields, sales inputs, below-cost audit fields and PostgreSQL constraints/triggers.
Upgrade and downgrade SQL are valid in Alembic offline mode.

## 11. API and UI

Capabilities:

```text
POST /api/v1/pricing/evaluate
POST /api/v1/pricing/runs
GET  /api/v1/pricing/runs
GET  /api/v1/pricing/runs/{id}
GET  /api/v1/pricing/runs/{id}/collection-metrics
GET  /api/v1/pricing/runs/{id}/collection-metrics/prometheus
POST /api/v1/pricing/runs/{id}/cancel
POST /api/v1/pricing/coefficients/calibrate
GET  /api/v1/pricing/coefficients
GET  /api/v1/pricing/recommendations
GET  /api/v1/pricing/recommendations/{id}
GET  /api/v1/pricing/recommendations/{id}/evidence
POST /api/v1/pricing/catalog-items/{id}/overrides
POST /api/v1/pricing/observations/{id}/tier-overrides
POST /api/v1/pricing/recommendations/{id}/decisions
```

Все persisted endpoints workspace-scoped. Recommendation listing поддерживает
pagination, action/category/confidence/score-type filters и unit-safe queues.

Flutter сначала показывает действие, текущую/целевую цену, economic effect и
confidence. В раскрытии видны fair-price range, evidence counts, weakest factor,
raw price, tier, multiplier, KEMP-equivalent price, coefficient model/confidence,
age и listing link. Оператор может добавить stock/sales/cost context, создать
append-only tier override и принять/отклонить/переопределить цену. Below-cost UI
не отправляет решение без явного checkbox confirmation.

## 12. Calculation trace

Recommendation хранит:

- catalog snapshot, run, parser/classifier/policy/coefficient/tick versions;
- calibration dataset hash;
- estimator, outlier filter, confidence aggregation и factor floors;
- `rc-scale-v1` pre/post profiles, selected method, finite-correction version и
  Decimal constants;
- raw/unique/clean/effective counts, dispersion, outliers и sensitivity;
- полный normalized-offer trace;
- применённые tier coefficients и validation reasons;
- exclusions с stage/reason;
- priority raw score, type, unit и inputs;
- context snapshot, включая below-cost authorization metadata.

Evidence endpoint возвращает только IDs, реально вошедшие в cleaned cohort этой
recommendation.

## 12.1. Deterministic recommendation replay

Старые recommendations с `recommendation-replay-v1` остаются читаемыми. Каждая
новая recommendation хранит `recommendation-replay-v2` и точный `calculated_at`.
Network-free replay повторно собирает frozen context,
observations, последнюю на тот момент classification, run policy и выбранные
run-scoped coefficients. V1 сравнивает прежние durable scalar fields; V2
дополнительно сравнивает selected method, pre/post normalized profiles,
profile/correction versions и constants:

```text
GET /api/v1/pricing/recommendations/{recommendation_id}/replay
```

Ответ содержит `exact_match`, field-level `mismatches` и replayed summary.
Legacy recommendations без replay contract честно возвращают
`RECOMMENDATION_REPLAY_UNAVAILABLE`, а не подменяют проверку приблизительным
сравнением.

## 13. Observability

Structured events без raw sensitive payload:

```text
pricing_run_started
pricing_run_completed
pricing_run_partial
pricing_item_failed
market_collection_retry
collection_circuit_open
coefficient_calibrated
coefficient_unvalidated
recommendation_raise
recommendation_lower
recommendation_hold
recommendation_manual_review
below_cost_decision
scrape_task_execution_started
scrape_task_retry_wait
scrape_items_terminal
scrape_target_materialized
```

Scraper telemetry separates logical items, logical HTTP requests, physical
attempts, task executions, raw evidence, and structured output. The complete
capacity/retry/storage contract is documented in
[`scraper_scaling.md`](scraper_scaling.md).

## 14. Semantic validation

| Scenario | Expected behavior |
|---|---|
| Mixed VAG 3200 / Bosch 2000 / Febi 1400 / KEMP 850 / used 400 | used excluded; cross tiers normalize near KEMP level; direct KEMP remains evidence/guardrail; no raw-OEM recommendation |
| Fresh 800, normalized market around 1100 | conservative `RAISE`, capped at 15% step |
| Fresh 1500, normalized market around 1100 | `HOLD`, never `LOWER` |
| Stale 1500, cost 1200, lower market 1050 | markdown, not below cost floor |
| Dead 1500, cost 1200, market 850, approved floor 700 | possible below-cost `LOWER`, never below 700, full audit metadata |
| Three old/mixed/volatile competitors | `MANUAL_REVIEW`, no invented actionable price |

Эти сценарии и property-like fresh-never-lower checks находятся в
`backend/tests/test_pricing_engine_matrix.py`.

## 15. Verification

```bash
cd backend
PYTHONPATH=src .venv/bin/python -m pytest -q
cd ..
backend/.venv/bin/python scripts/run_robust_dispersion_mutation_probes.py
backend/.venv/bin/python scripts/validate_robust_dispersion_decision_diff.py
backend/.venv/bin/python scripts/benchmark_robust_dispersion.py --repeats 5
cd backend
.venv/bin/alembic upgrade head --sql
.venv/bin/alembic downgrade 20260716_0009:base --sql

cd ../frontend
dart format --output=none --set-exit-if-changed lib test
dart analyze lib test
flutter test
flutter build web --release
```

В текущем Unicode path wrapper `flutter analyze` может аварийно завершиться
внутри LSP JSON transport до анализа исходников. Прямой `dart analyze lib test`
использует тот же analyzer ruleset и проходит; release Flutter build является
дополнительной compiler-проверкой.

## 16. External production gates

Код не выдумывает business evidence, которого нет. Перед включением массовых
автоматических действий нужны:

- labeled holdout по реальным OE/category/tier;
- выбор `k_tau` по out-of-sample log error и recommendation false-action rate;
- подтверждение pilot thresholds клиентом;
- live PostgreSQL/Redis/Celery/Prom smoke run в целевом окружении;
- мониторинг parser drift и последующая calibration reliability review.

Robust-dispersion v3 отдельно остаётся `NO_GO`: synthetic decision diff нашёл
один unsafe `MANUAL_REVIEW -> RAISE` transition на двухкластерной выборке, а
разрешённого representative dataset для calibration нет. Поэтому
`PRICING_V3_ROBUST_DISPERSION_ENABLED=false` по умолчанию блокирует persisted
v3 runs; side-effect-free preview и replay доступны для validation.

При отсутствии этих подтверждений engine корректно работает в shadow/manual
review режиме, но evidence grade нельзя называть вероятностью правильности.

## 17. Master-prompt traceability

| Requirement | Domain implementation | Persistence / API / UI | Verification |
|---|---|---|---|
| 3.2 KEMP normalization | `metis/pricing/calibration.py`, `metis/pricing/engine.py`, simple median and hierarchical log-shrinkage, leakage guards and coefficient validation | append-only pairs/coefficients, coefficient API, raw and normalized evidence in Flutter | `test_tier_calibration.py`, `test_pricing_engine_matrix.py` |
| 3.3 Robust fair price | `metis/pricing/statistics.py`, IQR/MAD cleaning, exact Sn/Qn diagnostics, pre/post scale profiles, partial-degeneracy and capacity gates, median/range output | method/profile/constants in API and immutable trace; v1/v2 replay | `test_pricing_statistics.py`, `test_robust_dispersion*.py`, mutation and decision-diff scripts |
| 3.4 Confidence | coverage, dispersion, half-life freshness, match/tier/source/independence factors, geometric/minimum aggregation and hard floors | factor breakdown, weakest factor, gates and human-readable reasons in API/UI | confidence matrix and policy validation tests |
| 3.5 Recommendation modes | fresh raise-only invariant; stale/dead markdown; cost and approved below-cost floor enforcement | action constraints, immutable decisions, explicit warning confirmation and audit event | engine matrix, API safety tests, Flutter below-cost dialog tests |
| 3.6 Economic priority | typed raw score with explicit unit; separate actionable and manual-review queues | priority fields in DB/API and operator-first ordering in Flutter | priority scenarios and API queue tests |
| Cross-cutting sections 23–30 | pure domain boundary, run-level calibration barrier, deterministic versions/hashes, structured events | migration `20260716_0006`, Celery orchestration, recommendation replay, calculation trace | backend suite, replay tests, OpenAPI build, Alembic chain, Flutter tests/analyzer/release build |
