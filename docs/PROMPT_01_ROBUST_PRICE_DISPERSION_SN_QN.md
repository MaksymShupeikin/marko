# MASTER PROMPT 01 — Robust Price Dispersion: Median, IQR, MAD, S_n, Q_n

## 0. Назначение артефакта

Этот файл — исполняемый мастер-промпт для ИИ-агента, который должен внедрить в
Metis/Marko робастный модуль оценки разброса рыночных цен на основе median, IQR,
MAD, Rousseeuw-Croux `S_n` и `Q_n`.

Это **не** утверждение, что новая статистика находит «оптимальную цену».
Результат задачи должен повысить надежность оценки того, насколько согласованно
рынок поддерживает текущую `fair_price`, сохранив abstention/manual-review
семантику и воспроизводимость старых рекомендаций.

```yaml
artifact_type: executable_master_prompt
language: ru-RU_with_machine_readable_contracts
target_repo: Marko shell with Metis-owned pricing kernel
primary_code_root: backend/src/metis/pricing
implementation_mode: execute_until_verified
scope: robust_price_dispersion_only
research_basis:
  - Rousseeuw_and_Croux_1993
  - modern_robustbase_Sn_Qn_reference
status: READY_FOR_AGENT_EXECUTION
```

---

# НАЧАЛО МАСТЕР-ПРОМПТА ДЛЯ ИИ-АГЕНТА

## 1. Роль

Ты работаешь как одновременно:

1. senior Python engineer;
2. statistical-computing engineer;
3. reviewer математических контрактов;
4. maintainer детерминированного Metis pricing kernel;
5. adversarial tester, который обязан попытаться опровергнуть собственную
   реализацию до того, как она будет признана готовой.

Ты отвечаешь не за красивую демонстрацию формул, а за корректный, versioned,
replayable и протестированный production-контракт.

## 2. Жесткий режим исполнения

```yaml
EXECUTION_MODE:
  token_budget_bias: disabled
  brevity_bias: disabled
  simplification_for_convenience: forbidden
  silent_scope_reduction: forbidden
  silent_behavior_change: forbidden
  fabricated_test_results: forbidden
  fabricated_market_data: forbidden
  float_in_core_scale_math: forbidden
  automatic_price_optimization_claim: forbidden
  stop_on_first_test_failure: forbidden
  continue_after_fix: required
  final_self_review: required
  independent_oracle_check: required
  variation_testing: required
```

- Не думай о токенах, лимитах ответа или удобстве краткого ответа. Если объем не
  помещается в один проход, дели работу на последовательные checkpoints, но не
  сокращай обязательную математику, интеграцию, тесты или отчет.
- Не упрощай задачу заменой `S_n`/`Q_n` на библиотечный псевдоаналог, standard
  deviation, trimmed mean или еще один MAD.
- Не ограничивайся созданием функций без интеграции в policy, result, trace,
  API и replay там, где эти контракты реально затронуты.
- Не переписывай pricing engine целиком. Изменяй только то, что необходимо для
  robust price dispersion и его безопасного versioned rollout.
- Не начинай сбор новых конкурентных данных и не обходи source-access policy.
  Для проверки используй только разрешенные локальные fixtures/snapshots и
  синтетические числовые unit-test vectors, которые не изображаются как реальные
  рыночные наблюдения.
- Не делай commit, push, deployment или включение feature flag во внешней среде,
  если это не было отдельно разрешено пользователем.

## 3. Миссия

Реализуй отдельный, чистый, детерминированный модуль робастного разброса цен,
который:

1. вычисляет median, Q1, Q3, raw IQR, raw MAD;
2. приводит IQR и MAD к Gaussian-consistent scale для честного сравнения;
3. вычисляет `S_n` и `Q_n` с точной семантикой порядковых статистик;
4. применяет явно versioned normal-consistency constants и finite-sample
   corrections;
5. возвращает по каждому estimator абсолютный scale и относительный
   `CV_estimator = scale_estimator / median_price`;
6. выбирает policy-controlled primary dispersion estimator;
7. сохраняет весь comparison profile в immutable calculation trace;
8. не меняет старые `pricing-v2` результаты и replay скрытым образом;
9. сохраняет `INSUFFICIENT_DATA` и `MANUAL_REVIEW` на малых/дегенеративных
   выборках;
10. не меняет определение `fair_price`: primary market center остается median
    очищенного seller-deduplicated cohort;
11. проходит unit, property, integration, replay, API, regression, variation и
    performance checks;
12. выпускает доказательный финальный отчет, а не голословное «готово».

## 4. Не перепутай цель

```text
robust scale estimation != optimal price estimation
robust_cv              != expected profit
low dispersion         != product comparability
high sample size       != source validity
statistical robustness != legal permission to collect data
```

`S_n` и `Q_n` отвечают только на вопрос о robust scale выборки. Они не доказывают:

- что listings относятся к одному коммерчески сравнимому товару;
- что tier normalization корректна;
- что данные свежие и разрешенные;
- что рекомендованная цена максимизирует прибыль;
- что автоматическое изменение цены безопасно.

Все существующие eligibility, matching, source confidence, tier confidence,
freshness, cost/below-cost и action gates должны продолжать действовать.

## 5. Сначала установи факты из репозитория

Перед изменением кода прочитай актуальные файлы. Не доверяй этому snapshot, если
репозиторий успел измениться.

Минимальный reading set:

```text
backend/src/metis/pricing/statistics.py
backend/src/metis/pricing/engine.py
backend/src/metis/pricing/types.py
backend/src/metis/pricing/__init__.py
backend/src/marko/pricing/__init__.py
backend/src/marko/services/market_collection.py
backend/src/marko/services/pricing_runs.py
backend/src/marko/services/recommendation_replay.py
backend/src/marko/infrastructure/db/models.py
backend/src/marko/api/schemas/pricing.py
backend/src/marko/api/routers/v1/pricing.py
backend/tests/test_pricing_statistics.py
backend/tests/test_pricing_engine.py
backend/tests/test_pricing_engine_matrix.py
backend/tests/test_pricing_api.py
backend/tests/test_recommendation_replay.py
backend/tests/test_metis_boundary.py
docs/kemp_pricing_engine.md
docs/architecture.md
backend/pyproject.toml
```

### 5.1 Уже подтвержденный baseline на момент создания промпта

Проверь каждый пункт повторно:

1. Каноническое ядро принадлежит `metis.pricing`; `marko.pricing` — compatibility
   facade. Не создавай вторую реализацию статистики под `marko.pricing`.
2. Core pricing math использует `Decimal`.
3. `statistics.py` уже содержит `median`, linear-interpolated `percentile`, raw
   `mad`, `iqr_fences`, winsorization и другие helpers.
4. Текущий `_dispersion()` в `engine.py` вычисляет:

   \[
   dispersion_{legacy}=1.4826\cdot MAD / median,
   \]

   а **не** `IQR / median`.
5. IQR сейчас используется в outlier cleaning при
   `n >= policy.iqr_min_competitors`; при меньшем action-eligible `n` применяется
   MAD cleaning.
6. После seller deduplication:
   - `< 3` unique sellers -> `INSUFFICIENT_DATA`;
   - `3..4` observations могут дать descriptive median, но automatic action
     запрещен и результат остается `MANUAL_REVIEW`;
   - default action threshold начинается с `min_competitors = 5`.
7. `PricingResult.dispersion` влияет на confidence factor и hard gates.
8. Scalar `dispersion` сохраняется в recommendation model, API и replay
   comparison.
9. Immutable `calculation_trace` уже существует и подходит для сохранения
   полного diagnostic profile без немедленного размножения DB columns.
10. Старые рекомендации зависят от `PricingPolicy.version = pricing-v2` и
    `recommendation-replay-v1`.

### 5.2 Обязательная фиксация аудита

До implementation выведи короткую таблицу:

| Contract | Фактический symbol/file | Current behavior | Изменение нужно? |
|---|---|---|---|
| scale helpers | ... | ... | yes/no |
| primary dispersion | ... | ... | yes/no |
| policy serialization | ... | ... | yes/no |
| trace persistence | ... | ... | yes/no |
| API output | ... | ... | yes/no |
| replay | ... | ... | yes/no |
| old-policy compatibility | ... | ... | yes/no |

Если baseline выше не совпадает с текущим кодом, следуй текущему коду, но явно
зафиксируй drift и адаптируй план без потери требований.

## 6. Математический контракт

### 6.0 Зачем нужны несколько estimators

В асимптотической Gaussian model статья дает ориентировочную efficiency около
`36.7%` для MAD, `58.2%` для `S_n` и `82.2%` для `Q_n` относительно classical
scale benchmark, при сохранении максимально возможного breakdown порядка 50%
для `S_n`/`Q_n`. Кроме того, `S_n` и `Q_n` строятся по interpoint distances и не
требуют отдельного location estimate, что делает их естественными diagnostics
для асимметричных распределений.

Эти числа — теоретический контекст, а не обещание качества на marketplace
prices. Gaussian efficiency не является business KPI, а 50% breakdown не
компенсирует плохой matching, зависимых sellers, неверную normalization или
source bias. Поэтому задача требует comparison profile и behavior validation,
а не слепой замены одного числа другим.

### 6.1 Входные данные

Для общего statistics layer допустим конечный непустой набор:

\[
X=(x_1,\ldots,x_n),\quad x_i\in Decimal,\quad x_i\text{ finite}.
\]

Общие scale helpers могут принимать отрицательные значения, поскольку scale
translation invariant. Price-specific wrapper обязан дополнительно требовать:

\[
x_i>0,\qquad m=median(X)>0.
\]

Правила:

- пустой input -> `ValueError`;
- `NaN`, `Infinity`, `-Infinity` -> `ValueError` до сортировки;
- `n = 1` -> scale estimators возвращают `0`, но engine не получает права на
  market action;
- input не мутируется;
- результат не зависит от порядка input;
- никакого implicit conversion через binary `float` в core math.

### 6.2 Явная семантика order statistic

Определи helper:

\[
OS_k(A)=k\text{-й элемент отсортированного }A,
\]

где `k` — **1-based** rank, `1 <= k <= len(A)`.

Не используй обычный `median()`, который усредняет две центральные точки, там,
где статья требует low/high median.

```python
def _order_statistic(values: Sequence[Decimal], rank_1_based: int) -> Decimal:
    ...

def _low_median(values: Sequence[Decimal]) -> Decimal:
    # rank = (n + 1) // 2, 1-based
    ...

def _high_median(values: Sequence[Decimal]) -> Decimal:
    # rank = n // 2 + 1, 1-based
    ...
```

Для четного `n` low median и high median различаются. Это обязательный testable
contract, а не implementation detail.

### 6.3 Location и IQR

Сохрани текущую repository convention для descriptive quantiles: linear
interpolation по позиции `q * (n - 1)`.

\[
m=median(X),\quad Q_1=P_{0.25}(X),\quad Q_3=P_{0.75}(X),
\]

\[
IQR_{raw}=Q_3-Q_1.
\]

Чтобы сравнивать IQR с estimator-ами масштаба, приведи его к
Gaussian-consistent scale:

\[
IQR_{\sigma}=\frac{IQR_{raw}}{2\Phi^{-1}(0.75)}
=\frac{IQR_{raw}}{1.348979500392163\ldots}.
\]

Используй versioned Decimal constant, например:

```python
IQR_NORMAL_DENOMINATOR = Decimal("1.348979500392163")
```

Не называй raw IQR и scaled IQR одним полем.

### 6.4 MAD

Существующая `mad(values)` должна сохранить raw semantics:

\[
MAD_{raw}=median_i|x_i-median_j(x_j)|.
\]

Для сравнимого scale profile добавь:

\[
MAD_{\sigma}=\frac{MAD_{raw}}{\Phi^{-1}(0.75)}
=1.482602218505602\ldots\cdot MAD_{raw}.
\]

Исторический `pricing-v2` path обязан продолжать использовать именно старую
константу `1.4826`, если это необходимо для byte/quantized replay parity. Новый
profile может использовать более точную versioned Decimal constant.

### 6.5 Rousseeuw-Croux S_n

Определение из статьи:

\[
S_n=c_n\cdot 1.1926\cdot
\operatorname{lowmed}_{i}
\left(\operatorname{highmed}_{j}|x_i-x_j|\right).
\]

Точная процедура:

1. Для каждого `i` вычислить `n` расстояний `|x_i - x_j|` для **всех** `j`,
   включая `j = i`, то есть один из элементов равен нулю.
2. В каждой строке взять high median с 1-based rank `n // 2 + 1`.
3. Из полученных `n` внутренних median взять low median с 1-based rank
   `(n + 1) // 2`.
4. Умножить на normal-consistency constant `1.1926`.
5. Если включена finite-sample correction, умножить на `c_n`.

Запрещенные ошибки:

- исключить `j = i`;
- взять averaged median при четном `n`;
- поменять местами low/high median;
- использовать signed distance;
- применить Qn correction table к Sn;
- дважды применить `1.1926`.

Finite-sample multiplier для `S_n` согласно reference implementation
`robustbase`:

```text
n = 2:  0.743
n = 3:  1.851
n = 4:  0.954
n = 5:  1.351
n = 6:  0.993
n = 7:  1.198
n = 8:  1.005
n = 9:  1.131
n >= 10 and even: 1
n >= 11 and odd:  n / (n - 0.9)
```

Сохрани correction profile version в trace. Не оставляй безымянную таблицу
магических чисел.

### 6.6 Rousseeuw-Croux Q_n

Для `n >= 2` создай все pairwise distances только для `i < j`:

\[
D=\{|x_i-x_j|:i<j\},\quad |D|={n\choose 2}.
\]

Определи:

\[
h=\left\lfloor\frac n2\right\rfloor+1,
\qquad
k={h\choose 2}=\frac{h(h-1)}2.
\]

Тогда:

\[
Q_n=d_n\cdot C_Q\cdot OS_k(D).
\]

Здесь `k` — 1-based rank. Не используй обычный percentile interpolation.

#### 6.6.1 Обязательная production-поправка к константе

В печатной формуле статьи 1993 года указано `2.2219`, но современная исправленная
normal-consistency constant равна:

\[
C_Q=\frac{1}{\sqrt{2}\Phi^{-1}(5/8)}
\approx 2.219144465985076.
\]

Контракт:

- `2.219144465985076` — default для нового versioned implementation;
- `2.2219` допускается только в явно названном historical compatibility mode;
- нельзя смешивать эти значения под одним version identifier;
- robustbase может округлять default до `2.21914`; oracle comparison должен
  либо передавать ту же полную constant явно, либо использовать обоснованный
  tolerance.

#### 6.6.2 Finite-sample multiplier Q_n

Используй один явно versioned correction profile. Для нового профиля зафиксируй
современный `robustbase`-совместимый вариант:

```text
n = 2:  0.399356
n = 3:  0.99365
n = 4:  0.51321
n = 5:  0.84401
n = 6:  0.61220
n = 7:  0.85877
n = 8:  0.66993
n = 9:  0.87344
n = 10: 0.72014
n = 11: 0.88906
n = 12: 0.75743
```

Для `n >= 13` вычисли intermediate finite correction `f_n`:

для нечетного `n`:

\[
f_n=1+\frac{1.60188+\frac{-2.1284-5.172/n}{n}}{n};
\]

для четного `n`:

\[
f_n=1+\frac{3.67561+
\frac{1.9654+\frac{6.987-77/n}{n}}{n}}{n}.
\]

И применяй:

\[
d_n=1/f_n.
\]

Добавь unit tests, которые ловят ошибку `multiply by f_n` вместо `divide by
f_n`.

### 6.7 Общий scale profile

На одной и той же выборке сформируй:

\[
\mathcal S=
\{IQR_{\sigma},MAD_{\sigma},S_n,Q_n\}.
\]

Для каждого estimator `e`:

\[
CV_e=\frac{scale_e}{m},\qquad m>0.
\]

Не смешивай raw IQR с Gaussian-consistent MAD/Sn/Qn при сравнении. Сравнение
имеет смысл только после scale normalization.

Рекомендуемый typed contract:

```python
class RobustScaleMethod(str, Enum):
    LEGACY_MAD = "legacy_mad"
    IQR = "iqr"
    MAD = "mad"
    SN = "sn"
    QN = "qn"


@dataclass(frozen=True, slots=True)
class RobustDispersionProfile:
    version: str
    correction_profile_version: str
    sample_stage: str                 # pre_clean | post_clean
    sample_size: int
    center: Decimal
    q1: Decimal
    q3: Decimal
    raw_iqr: Decimal
    raw_mad: Decimal
    gaussian_scales: Mapping[str, Decimal]
    robust_cvs: Mapping[str, Decimal]
    selected_method: RobustScaleMethod
    selected_scale: Decimal
    robust_cv: Decimal
    zero_scale_methods: tuple[str, ...]
    all_scales_zero: bool
    partial_scale_degeneracy: bool
    cv_min: Decimal
    cv_max: Decimal
    cv_span: Decimal
    cv_median: Decimal
    cv_relative_span: Decimal | None
```

Имена можно адаптировать к repository style, но нельзя потерять смысл полей.

### 6.8 Comparison и degeneracy semantics

Вычисли:

\[
CV_{min}=\min_e CV_e,\quad
CV_{max}=\max_e CV_e,\quad
CV_{span}=CV_{max}-CV_{min},
\]

\[
CV_{med}=median_e(CV_e).
\]

Если `CV_med > 0`:

\[
CV_{relative\_span}=CV_{span}/CV_{med}.
\]

Если все scales равны нулю:

```yaml
all_scales_zero: true
partial_scale_degeneracy: false
cv_relative_span: 0
```

Если хотя бы один estimator равен нулю, а другой положителен:

```yaml
all_scales_zero: false
partial_scale_degeneracy: true
cv_relative_span: null
reason_code: ROBUST_SCALE_PARTIAL_DEGENERACY
automatic_action: forbidden
```

Не подменяй нулевой `Q_n` ненулевым `S_n` через тихий fallback. Если primary
estimator дегенеративен, а peers расходятся, безопасное действие —
`MANUAL_REVIEW`, а не выбор удобного числа.

`cv_relative_span` сначала является diagnostic, а не автоматическим gate:
порог estimator disagreement нельзя выдумать без calibration data. Добавить
configurable gate можно, но default activation разрешена только после
decision-diff validation. Не используй `sensitivity_tolerance` как случайную
замену — это другой статистический смысл.

## 7. Policy и backward compatibility

### 7.1 Нельзя тихо переопределить существующее поле dispersion

Существующее поле `PricingResult.dispersion` участвует в decision logic,
persistence и replay. Поэтому выполни versioned migration поведения:

```yaml
pricing-v2:
  primary_dispersion: legacy_1.4826_times_MAD_over_median
  replay_behavior: unchanged

pricing-v3-robust-dispersion:
  primary_dispersion: selected_scale_over_median
  default_selected_method: qn
  finite_sample_correction: enabled
  profile_version: rc-scale-v1
  correction_profile_version: robustbase-modern-v1
```

Добавь explicit policy fields, например:

```python
dispersion_method: RobustScaleMethod
finite_sample_scale_correction: bool
robust_dispersion_profile_version: str
```

Не полагайся только на `version.startswith(...)` в core math, если можно
сериализовать явные policy fields.

### 7.2 Default rollout

Реализация и активация — разные состояния:

1. Сначала реализуй оба пути.
2. Старые persisted policy configs без новых полей интерпретируй как
   `LEGACY_MAD`.
3. Новые runs могут получить `pricing-v3-robust-dispersion` только после PASS
   всех stop-gates ниже.
4. Не backfill старые `dispersion` values новой формулой.
5. Не называй rollout production-calibrated, если нет разрешенного
   representative decision-diff dataset.

### 7.3 Small-n contract

Сохрани fail-closed поведение:

| Unique seller count после dedup/cleaning | Разрешенный результат |
|---:|---|
| 0–2 | `INSUFFICIENT_DATA`, без automatic recommendation |
| 3–4 | descriptive median/profile разрешены, только `MANUAL_REVIEW` |
| >= 5 | automatic action только при прохождении всех прежних и новых gates |

`S_n`/`Q_n` могут быть математически вычислены при меньшем `n`, но сам факт
вычислимости не повышает evidence sufficiency.

### 7.4 Primary estimator для v3

Для нового профиля primary estimator — corrected `Q_n`, потому что задача
напрямую направлена на добавление Rousseeuw-Croux scale и `Q_n` дает эффективный
location-free scale на общей Gaussian-consistent шкале.

Но:

- `fair_price` остается median;
- existing outlier cleaning в этой задаче не заменяется на Qn-based filtering;
- `Q_n = 0` при ненулевых peer scales -> manual review;
- `max_dispersion` нельзя считать заново откалиброванным только потому, что все
  scales Gaussian-consistent; activation требует behavior comparison.

## 8. Где считать profile

Считай два диагностических профиля:

1. `pre_clean_profile` — после eligibility, normalization и seller
   deduplication, но до robust outlier cleaning;
2. `post_clean_profile` — на фактическом cleaned cohort, из которого берется
   `fair_price`.

Decision field `dispersion` для v3 должен ссылаться на `post_clean_profile`.
`pre_clean_profile` показывает, насколько cleaning изменил market-scale picture,
и помогает не скрыть выброс просто потому, что он уже исключен.

Не включай в profile:

- excluded observations;
- несколько listings одного seller после dedup;
- owned seller;
- invalid/negative/non-finite normalized price;
- observations, уже отклоненные существующими eligibility rules.

## 9. Алгоритмический контракт

### 9.1 Допустимая первая реализация

Для текущих небольших seller cohorts допустима простая exact реализация:

- `S_n`: `O(n^2 log n)` при сортировке каждой distance row, `O(n)` extra memory
  на row;
- `Q_n`: `O(n^2 log n)` и `O(n^2)` memory для pairwise distances;
- никаких approximate quantiles или random subsampling.

Статья описывает более быстрые `O(n log n)` алгоритмы, но их внедрение не нужно
изображать частью «быстрого engineering win», если repository evidence
подтверждает малый cohort.

### 9.2 Capacity guard

Проверь upstream limits и реальный максимум cohort:

- если upstream уже строго ограничивает `n` безопасным малым значением —
  задокументируй доказательство;
- если bound отсутствует — benchmark exact implementation и добавь
  policy/config capacity guard;
- при превышении validated ceiling запрещен silent fallback на legacy MAD или
  sampling;
- fail-closed outcome: `MANUAL_REVIEW` с reason
  `ROBUST_SCALE_CAPACITY_EXCEEDED`, либо внедрение exact fast algorithm.

Не выдумывай ceiling без benchmark evidence.

### 9.3 Determinism

- Sort order должен быть определен только значениями Decimal, не input order.
- Constants создаются из строк.
- JSON trace сериализует Decimal канонически строками, без float round-trip.
- Mapping order либо фиксирован, либо сравнение replay не должно зависеть от
  порядка keys.
- Одинаковый input + policy + constants version обязан давать одинаковый output.

## 10. Кодовая интеграция

### 10.1 `backend/src/metis/pricing/statistics.py`

Добавь или аккуратно выдели:

```text
_order_statistic
_low_median
_high_median
scaled_mad
scaled_iqr
sn_scale
qn_scale
robust_price_dispersion
```

Требования:

- не меняй raw semantics существующей `mad()`;
- не дублируй `median()`/`percentile()` без причины;
- все new public functions добавь в `__all__` только если они действительно
  являются domain API;
- constants и correction tables должны иметь имена и source comments;
- комментарий обязан объяснять `2.2219` vs `2.219144...`;
- invalid input rejection тестируется.

### 10.2 `backend/src/metis/pricing/types.py`

Добавь typed enum/profile/policy/result fields. Проверь:

- frozen/slots style;
- validation новых policy fields;
- serialization из старого config;
- отсутствие mutable defaults;
- наличие profile даже для manual-review descriptive result, если sample
  позволяет его вычислить;
- `None` используется только там, где значение действительно не определено.

### 10.3 `backend/src/metis/pricing/engine.py`

Измени flow минимально:

```text
eligible
 -> seller dedup
 -> small-n precheck
 -> pre_clean robust profile
 -> existing outlier cleaning
 -> post-clean small-n check
 -> post_clean robust profile
 -> median fair price unchanged
 -> versioned selected dispersion
 -> existing confidence/action gates
 -> additional partial-degeneracy/capacity fail-closed gate
```

Не делай следующее в рамках этой задачи:

- не замени median fair price на Qn/Sn: это scale, а не location estimator;
- не перепиши `_clean_outliers` на новый алгоритм без отдельного evidence;
- не ослабляй `min_competitors`, `n_effective`, confidence floors;
- не удаляй winsor sensitivity;
- не смешивай `outlier_method` и `dispersion_method`.

### 10.4 Public package boundary

Если profile/enum нужны Marko layer, экспортируй их через
`metis.pricing.__init__`. `marko.pricing` должен продолжать ссылаться на те же
Metis objects; boundary test обязан это доказать. Никакой copy-paste версии под
`src/marko/pricing`.

### 10.5 Trace и persistence

Для первой версии используй существующий immutable `calculation_trace`, если
репозиторный аудит подтверждает его надежную persistence:

```json
{
  "robust_dispersion": {
    "profile_version": "rc-scale-v1",
    "correction_profile_version": "robustbase-modern-v1",
    "selected_method": "qn",
    "pre_clean": {},
    "post_clean": {},
    "constants": {
      "mad_normal": "1.482602218505602",
      "iqr_normal_denominator": "1.348979500392163",
      "sn_normal": "1.1926",
      "qn_normal": "2.219144465985076"
    }
  }
}
```

- Scalar DB column `dispersion` остается selected decision value.
- Не создавай четыре новых DB columns только ради diagnostics, если они не нужны
  для indexed queries.
- Если текущий persistence path обрезает trace или требует schema change, создай
  migration, но докажи необходимость.
- Trace должен содержать enough inputs/versions для offline replay.

### 10.6 API

Добавь machine-readable `dispersion_method` и `dispersion_profile` в evaluate
response. Для stored recommendation profile может быть возвращен из immutable
trace, если это соответствует текущему API style.

Проверь:

- Decimal serialization;
- old response consumers не ломаются от additive field;
- `outlier_method` сохраняет прежний смысл;
- OpenAPI schema отражает новые поля;
- frontend не обязан отображать всю математику в этой задаче, но не должен
  падать от additive response fields.

### 10.7 Replay

Новый trace contract должен быть versioned, например
`recommendation-replay-v2`, но старый v1 нельзя просто сделать нечитаемым.

Требуется:

```yaml
replay_v1:
  accepted: true
  dispersion_path: legacy_mad
  expected_fields: old_contract

replay_v2:
  accepted: true
  dispersion_path: policy_selected
  compare:
    - scalar_dispersion
    - dispersion_method
    - normalized_profile_values
    - profile_version
    - correction_profile_version
```

Если old trace объективно не содержит enough data для нового profile, не
подделывай его. Replay v1 сравнивает старый contract; replay v2 — новый.

## 11. Пошаговый implementation plan

### STEP 00 — Repo truth audit

Действия:

1. Прочитай reading set.
2. Найди все references на `dispersion`, `_dispersion`, `max_dispersion`,
   `outlier_method`, policy serialization, calculation trace и replay.
3. Проверь dirty worktree; не перезаписывай пользовательские изменения.
4. Зафиксируй current tests/commands и Python environment.
5. Сверь фактические small-n transitions.

Выход:

```yaml
STEP_00_RESULT:
  repo_facts: [...]
  drift_from_prompt: [...]
  files_to_change: [...]
  files_read_only: [...]
  baseline_test_command: "..."
```

STOP GATE 00:

- `PASS`, если ownership и integration map понятны;
- `BLOCKED`, если канонический pricing kernel определить невозможно;
- не переходить к реализации при неразрешенном conflict между двумя активными
  kernels.

### STEP 01 — Pure order-statistic and scale helpers

Действия:

1. Реализуй explicit order-statistic helpers.
2. Реализуй scaled IQR/MAD без изменения raw helpers.
3. Реализуй exact `S_n`.
4. Реализуй exact `Q_n`.
5. Реализуй correction profiles.
6. Реализуй typed `RobustDispersionProfile` builder.
7. Добавь unit tests до engine integration.

STOP GATE 01:

- hand-calculated vectors PASS;
- independent reference parity PASS;
- permutation/translation/scale invariance PASS;
- invalid inputs PASS;
- even-n low/high median tests PASS.

При FAIL исправь реализацию и повтори весь gate, а не только упавший тест.

### STEP 02 — Shadow integration

Действия:

1. Вычисляй pre/post profiles.
2. Оставь `pricing-v2` scalar dispersion полностью legacy.
3. Запиши new profile в trace как diagnostic.
4. Добавь API additive fields.
5. Убедись, что old engine expectations не изменились.

STOP GATE 02:

- existing pricing engine tests PASS без ослабления assertions;
- legacy result/replay parity PASS;
- trace содержит deterministic profile;
- no automatic action changed under pricing-v2.

### STEP 03 — Versioned v3 behavior

Действия:

1. Добавь explicit v3 policy fields.
2. Для v3 выбери `Q_n / median` как scalar dispersion.
3. Сохрани все peer CVs.
4. Добавь partial-degeneracy fail-closed gate.
5. Сохрани small-n behavior.
6. Не активируй arbitrary estimator-disagreement threshold.

STOP GATE 03:

- v2 remains identical;
- v3 deterministic;
- v3 never converts `<5` seller sample to automatic action;
- partial degeneracy -> manual review;
- all-equal independent-seller cohort -> valid zero scale, не ложная degeneracy;
- all existing economic/quality gates remain active.

### STEP 04 — Persistence, API and replay

Действия:

1. Проверь trace persistence end-to-end.
2. Добавь response fields.
3. Поддержи replay v1 и v2.
4. Добавь compare fields для v2.
5. Проверь policy round-trip.

STOP GATE 04:

- API contract tests PASS;
- recommendation persistence/retrieval PASS;
- v1 replay PASS;
- v2 replay exact match PASS;
- deliberate constant/method/version mutation создает replay mismatch.

### STEP 05 — Decision-diff and variation validation

Сравни `pricing-v2` и candidate `pricing-v3` на всех существующих разрешенных
fixtures/snapshots и synthetic matrix.

Для каждого case зафиксируй:

```yaml
case_id: ...
n_raw: ...
n_unique: ...
n_clean: ...
legacy_dispersion: ...
iqr_cv: ...
mad_cv: ...
sn_cv: ...
qn_cv: ...
v2_action: ...
v3_action: ...
action_changed: true|false
change_direction: auto_to_manual|manual_to_auto|same|other
explanation: ...
```

Activation condition:

```text
unsafe_relaxation_count = count(
  v2_action in {MANUAL_REVIEW, INSUFFICIENT_DATA}
  and v3_action in {RAISE, HOLD, LOWER}
)
```

Для автоматической activation требуется:

```text
unsafe_relaxation_count == 0
```

Если значение больше нуля, implementation может считаться завершенной, но v3
activation получает `NO_GO` до ручного review/calibration. Не маскируй это
изменением fixtures или порогов.

STOP GATE 05:

- сам gate получает `PASS`, если decision-diff matrix полностью рассчитана,
  каждое изменение объяснено и `unsafe_relaxation_count` подтвержден;
- отдельно зафиксируй `activation_status = PASS`, если
  `unsafe_relaxation_count == 0` и остальные activation checks пройдены;
- отдельно зафиксируй `activation_status = NO_GO`, если обнаружена хотя бы одна
  unsafe relaxation или отсутствует достаточная calibration evidence;
- `activation_status = NO_GO` не разрешает пропустить STEP 06 и не превращает
  корректную implementation автоматически в `FAIL`.

### STEP 06 — Full verification and docs

1. Запусти targeted tests.
2. Запусти весь backend test suite.
3. Запусти lint/static checks, доступные в repo.
4. Запусти replay tests.
5. Запусти benchmark.
6. Обнови `docs/kemp_pricing_engine.md` и другие реально затронутые docs.
7. Проверь diff на случайные изменения.
8. Проведи self-review по секции 18.

STOP GATE 06:

- targeted tests, full backend suite и lint PASS;
- replay/API checks PASS;
- variation matrix и mutation probes PASS;
- benchmark и capacity conclusion зафиксированы;
- documentation соответствует фактическому коду;
- unrelated edits отсутствуют или явно исключены из scope;
- заполненный self-audit не содержит обязательных `no`.

При невыполнении любого пункта итоговый implementation status — `FAIL` или
`BLOCKED` с конкретным evidence, но не `PASS`.

## 12. Обязательная test matrix

### 12.1 Golden vector A — один экстремальный выброс, n=4

```text
X = [100, 105, 110, 1000]
```

При specified constants/corrections и текущем linear percentile ожидается
примерно:

```yaml
n: 4
median: 107.5
raw_iqr: 228.75
iqr_sigma: 169.5726287416
mad_sigma: 7.4130110925
sn: 11.3774040
qn: 11.3888713139
```

Проверить:

- IQR profile резко реагирует на interpolation в маленькой выборке;
- MAD/Sn/Qn не становятся порядка `1000`;
- action остается `MANUAL_REVIEW` из-за `n=4`;
- никакая новая статистика не превращает sample в «достаточный».

### 12.2 Golden vector B — чистая локальная сетка, n=5

```text
X = [100, 105, 110, 115, 120]
```

Ожидается примерно:

```yaml
median: 110
raw_iqr: 10
iqr_sigma: 7.4130110925
mad_sigma: 7.4130110925
sn: 8.0560130
qn: 9.3649006037
```

Проверить все CV делением на `110` и точное применение finite correction для
`n=5`.

### 12.3 Golden vector C — skewed prices

```text
X = [100, 101, 103, 108, 120, 160, 300]
```

Ожидается примерно:

```yaml
median: 108
raw_iqr: 38
iqr_sigma: 28.1694421516
mad_sigma: 11.8608177480
sn: 11.4298784
qn: 15.2458775444
```

Проверить:

- permutation invariance;
- все scales finite/nonnegative;
- estimator disagreement виден в profile;
- disagreement не замалчивается усреднением raw и normalized measures;
- отсутствие утверждения, что какой-либо estimator дает «истинную optimal
  price».

### 12.4 Duplicate price values от независимых sellers

```text
X = [100, 100, 100, 105, 110]
```

При заданной order-statistic semantics:

```yaml
median: 100
raw_iqr: 5
iqr_sigma: positive
mad_sigma: 0
sn: 0
qn: 0
partial_scale_degeneracy: true
automatic_action: forbidden
```

Это не ошибка алгоритма: pairwise/median estimators могут collapse при ties.
Ошибка — выдать из этого ложную высокую уверенность.

### 12.5 All-equal independent sellers

```text
X = [100, 100, 100, 100, 100]
```

Ожидается:

```yaml
all_scales_zero: true
partial_scale_degeneracy: false
robust_cv: 0
```

Не отправляй sample в manual review только из-за того, что истинный observed
spread равен нулю. Остальные gates продолжают действовать.

### 12.6 Duplicate observations одного seller

Создай engine-level case, где один seller имеет несколько listings/prices.

Проверить:

- seller дает один голос;
- representative выбирается прежним deterministic rule;
- scale profile строится после dedup;
- equal price от другого независимого seller не удаляется как seller duplicate;
- `sample_size` profile равен unique seller cohort, а не raw listing count.

### 12.7 Малые n

Обязательные cases:

```text
n=0 -> helper error / engine insufficient according to existing flow
n=1 -> scales 0 diagnostically, engine insufficient
n=2 -> Qn/Sn computable, engine insufficient
n=3 -> descriptive profile + manual review
n=4 -> descriptive profile + manual review
n=5 -> action still requires every other gate
```

### 12.8 Numeric edge cases

Проверь:

- Decimal с копейками;
- очень большие, но finite prices;
- очень малые positive values;
- negative values допустимы для generic scale helper, но запрещены price wrapper;
- zero price запрещена price wrapper;
- NaN/Infinity отклоняются;
- repeated pairwise distances;
- unsorted input;
- tuple/generator input, если public signature обещает Iterable;
- input collection не изменяется.

## 13. Property/invariant tests

Для каждого `T in {scaled_iqr, scaled_mad, S_n, Q_n}`:

### 13.1 Nonnegativity

\[
T(X)\ge 0.
\]

### 13.2 Permutation invariance

\[
T(\pi(X))=T(X).
\]

### 13.3 Translation invariance

\[
T(X+b)=T(X).
\]

### 13.4 Scale equivariance

\[
T(aX+b)=|a|T(X),\quad a\ne0.
\]

Для Decimal constants выбери explicit comparison tolerance и объясни его.

### 13.5 Constant sample

\[
T(c,c,\ldots,c)=0.
\]

### 13.6 Price-CV scale invariance

Для `a > 0`:

\[
CV_e(aX)=CV_e(X).
\]

## 14. Independent oracle validation

Нельзя проверять implementation копией того же production function.

Минимум два независимых источника проверки:

1. hand-calculated small vectors, где order statistics видны вручную;
2. external/reference implementation `robustbase::Sn` и `robustbase::Qn` для
   набора fixed vectors.

Reference use — только test/dev validation, не runtime dependency.

Для Qn explicitly вызывай согласованный contract:

```r
robustbase::Qn(
  x,
  constant = 2.219144465985076,
  finite.corr = TRUE
)
```

Для Sn:

```r
robustbase::Sn(
  x,
  constant = 1.1926,
  finite.corr = TRUE
)
```

Если R недоступен в execution environment:

- не добавляй R как production dependency;
- создай checked-in golden fixture с provenance: package version, command,
  constants, correction mode и generation date;
- дополни hand-derived oracle;
- честно отметь, была ли live parity check выполнена в этом run.

## 15. Вариационная и mutation-проверка

Пользователь требует не только happy-path tests, но и проверку вариациями.

### 15.1 Variation dimensions

Перебери комбинации:

```yaml
sample_size: [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 20]
shape:
  - all_equal
  - symmetric_clean
  - one_high_outlier
  - one_low_outlier
  - right_skew
  - left_skew_generic_scale_only
  - many_ties
  - two_clusters
ordering:
  - sorted
  - reversed
  - deterministic_permutations
decimal_scale:
  - integers
  - cents
  - very_small
  - very_large
```

### 15.2 Mutation probes

Временно/локально докажи, что tests падают при типичных ошибках:

1. Qn `k` сделать 0-based;
2. в Qn включить `i = j`;
3. в Sn исключить `i = j`;
4. в Sn заменить high median на averaged median;
5. заменить Qn `2.219144...` на `2.2219` при tight oracle tolerance;
6. для `n >= 13` умножать на `f_n` вместо деления;
7. считать CV от mean вместо median;
8. считать profile до seller dedup и использовать его как decision profile.

Не коммить мутации. В финальном отчете перечисли probes и укажи, какие tests
их ловят.

## 16. Regression и decision safety

### 16.1 Legacy invariance

Для `pricing-v2` должны совпасть как минимум:

- action;
- fair price;
- recommended price;
- scalar dispersion после существующей quantization;
- confidence/factor scores;
- reasons;
- evidence/excluded observation IDs;
- replay exact_match.

### 16.2 V3 behavior review

Любое изменение action объясни конкретными estimator values и gates.

Особенно опасно:

```text
legacy MANUAL_REVIEW/INSUFFICIENT_DATA -> v3 RAISE/HOLD/LOWER
```

Такое изменение не может быть silently accepted только потому, что Qn меньше
MAD/IQR. Оно блокирует activation до review.

### 16.3 No semantic overclaim

Документы/API labels должны говорить:

- `market-supported fair price`;
- `robust dispersion`;
- `estimator comparison`;
- `manual review` при недостаточной поддержке.

Не писать:

- `optimal price`;
- `guaranteed profit`;
- `true market value`;
- `AI-proven price`.

## 17. Performance verification

Сделай deterministic benchmark без network/DB минимум для:

```text
n = 10, 25, 50, 100, 250
```

Если execution time позволяет, добавь `n=500`.

Измерь отдельно:

- `S_n`;
- `Q_n`;
- full profile;
- peak/estimated pairwise distance count `n(n-1)/2`.

Отчет должен содержать:

```yaml
benchmark_environment:
  python: ...
  platform: ...
  decimal_precision: ...
results:
  - n: ...
    sn_ms: ...
    qn_ms: ...
    full_profile_ms: ...
    pair_count: ...
validated_ceiling: ...
upstream_bound_evidence: ...
```

Benchmark не является поводом заменить exact algorithm approximation без нового
решения.

## 18. Обязательная самопроверка перед финалом

Ответь `yes/no + evidence` на каждый пункт:

### Mathematics

- [ ] Qn использует только `i < j`?
- [ ] Qn rank `k = choose(floor(n/2)+1, 2)` и он 1-based?
- [ ] Sn включает `j = i`?
- [ ] Sn использует inner high median и outer low median?
- [ ] `2.219144...` отделен от historical `2.2219`?
- [ ] finite corrections применяются ровно один раз?
- [ ] Qn `n>=13` делит на `f_n`, а не умножает?
- [ ] IQR/MAD приведены к общей scale до comparison?
- [ ] CV делится на positive median?

### Domain safety

- [ ] fair price осталась median?
- [ ] seller dedup выполняется до decision profile?
- [ ] small-n abstention сохранен?
- [ ] partial scale degeneracy блокирует auto action?
- [ ] all-zero scale не ошибочно маркирован partial degeneracy?
- [ ] old quality/economic gates сохранены?

### Compatibility

- [ ] pricing-v2 output не изменен?
- [ ] old policy config round-trip работает?
- [ ] replay v1 поддерживается?
- [ ] replay v2 сравнивает profile/version?
- [ ] no silent backfill?

### Engineering

- [ ] core scale math без float?
- [ ] tests ловят low/high median confusion?
- [ ] tests ловят Qn constant typo?
- [ ] tests ловят wrong finite correction direction?
- [ ] full suite и lint пройдены?
- [ ] benchmark выполнен?
- [ ] docs обновлены?
- [ ] diff не содержит unrelated edits?

Если хотя бы один обязательный пункт `no`, статус не может быть `PASS`.

## 19. Команды проверки

Сначала установи фактическое окружение. Из-за возможного stale editable install
предпочитай явный source path:

```bash
cd backend
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_pricing_statistics.py
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_pricing_engine.py tests/test_pricing_engine_matrix.py
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_pricing_api.py tests/test_recommendation_replay.py tests/test_metis_boundary.py
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m ruff check src tests
```

Если executable paths отличаются, используй repository-approved equivalents и
зафиксируй точные команды. Не заявляй PASS по старому output из другой checkout.

Дополнительно:

```bash
git diff --check
git status --short
```

Если working tree не является git repository, честно зафиксируй это вместо
подделки git verification.

## 20. Definition of Done

Задача завершена только если одновременно истинны все условия:

```yaml
PURE_MATH:
  sn_implemented: true
  qn_implemented: true
  finite_corrections_versioned: true
  independent_oracle_passed: true

DOMAIN:
  pre_clean_profile: implemented
  post_clean_profile: implemented
  fair_price_location_unchanged: true
  small_n_fail_closed: true
  partial_degeneracy_fail_closed: true

COMPATIBILITY:
  pricing_v2_parity: true
  replay_v1_supported: true
  replay_v2_verified: true

QUALITY:
  targeted_tests: pass
  full_backend_tests: pass
  lint: pass
  variation_matrix: pass
  mutation_probes: pass
  benchmark: completed
  docs: synchronized

ROLLOUT:
  implementation_status: PASS
  activation_status: PASS_or_NO_GO_with_reason
```

`implementation_status = PASS` и `activation_status = NO_GO` — допустимый и
честный результат, если код корректен, но behavior calibration выявила unsafe
relaxations или отсутствует разрешенный representative dataset.

## 21. Формат финального отчета агента

Верни отчет строго в следующем порядке:

### A. Итог

```yaml
implementation_status: PASS|FAIL|BLOCKED
activation_status: PASS|NO_GO|NOT_REQUESTED
pricing_v2_parity: PASS|FAIL
pricing_v3_candidate: READY|NOT_READY
```

### B. Repo facts and drift

- что было подтверждено;
- где исходное предположение отличалось от кода;
- какие решения приняты.

### C. Mathematical implementation

- exact definitions;
- constants;
- finite correction profile;
- order-statistic semantics;
- complexity.

### D. Changed files

Для каждого файла:

```text
path -> purpose -> externally visible behavior
```

### E. Tests and validation

Таблица:

| Check | Command/method | Result | Evidence |
|---|---|---|---|

Включить golden vectors, property tests, oracle, variations, mutation probes,
full suite и lint.

### F. Decision diff

- количество same/auto-to-manual/manual-to-auto;
- unsafe relaxation count;
- конкретные изменившиеся cases;
- activation verdict.

### G. Replay/API compatibility

- v1 behavior;
- v2 behavior;
- trace fields;
- schema compatibility.

### H. Performance

- benchmark table;
- validated ceiling/upstream bound;
- remaining scaling risk.

### I. Residual risks

Раздели:

```yaml
known_limitations: [...]
unverified_assumptions: [...]
business_policy_needing_calibration: [...]
not_in_scope: [...]
```

### J. Final self-audit

Приложи заполненный checklist из секции 18.

## 22. Источники, которые должны быть сохранены в docs/comments

1. P. J. Rousseeuw, C. Croux (1993), *Alternatives to the Median Absolute
   Deviation*, JASA 88, 1273-1283:
   https://wis.kuleuven.be/stat/robust/papers/publications-1993/rousseeuwcroux-alternativestomedianad-jasa-1993.pdf
2. KU Leuven publication index:
   https://wis.kuleuven.be/stat/robust/papers-1990-1999
3. `robustbase` reference manual for `Qn`/`Sn`:
   https://stat.ethz.ch/CRAN/web/packages/robustbase/robustbase.pdf
4. `robustbase` reference source for constants/corrections:
   https://rdrr.io/cran/robustbase/src/R/qnsn.R

Не копируй длинные фрагменты источников в код. Сохрани краткую provenance note,
формулы, version identifiers и прямые ссылки.

## 23. Финальная инструкция

Начни со STEP 00. После каждого STOP GATE выведи результат и продолжай только
при `PASS`. При исправлении дефекта повторяй весь релевантный gate и downstream
checks. Не заканчивай на частичной реализации, если нет настоящего blocker.

Не заявляй, что цена стала «оптимальной». Заявляй только то, что доказано:
Metis получил более полный, робастный, versioned и replayable профиль разброса
цен, а автоматические действия по-прежнему ограничены evidence и safety gates.

# КОНЕЦ МАСТЕР-ПРОМПТА ДЛЯ ИИ-АГЕНТА
