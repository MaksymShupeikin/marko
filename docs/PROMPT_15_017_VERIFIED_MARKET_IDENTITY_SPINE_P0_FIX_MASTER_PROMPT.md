# PROMPT 15.017 — VERIFIED MARKET IDENTITY SPINE P0 FIX

- Статус: `EXECUTABLE_IMPLEMENTATION_MASTER_PROMPT`
- Версия: `1.0.0`
- Дата: `2026-07-19`
- Язык: русский + machine-oriented identifiers, formulas, pseudocode, SQL/YAML contracts
- Режим: `IMPLEMENTATION_AND_VERIFICATION`
- Приоритет: `P0 / FAIL_CLOSED / DATA_IDENTITY_AND_CALIBRATION_SAFETY`
- Целевой проект: `Marko + Metis`
- Целевой checkout: `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`
- Prompt ID: `PROMPT_15_017_VERIFIED_MARKET_IDENTITY_SPINE_P0_FIX`

---

## 0. Назначение

Этот документ — исполнимое задание для ИИ-агента, который должен исправить шесть
связанных P0-дефектов в реальном пути:

```text
CatalogItem
  -> search/acquisition
  -> raw Prom evidence
  -> parsed offer
  -> OE extraction
  -> verified part identity
  -> commercial comparability
  -> tier classification
  -> calibration pairs
  -> pricing recommendation
```

Исправляемые P0:

1. При отсутствии `product_url` создаётся `invalid://missing-product-url`, и позиция
   фактически не может пройти реальный acquisition path.
2. `MarketObservation.matched_oe_norm` присваивается из `CatalogItem.oe_norm`, хотя это
   поисковое намерение, а не доказательство OE найденного предложения.
3. Calibration selection не требует одновременно `automatic_eligible=true` и
   `hard_gate_result=PASS`.
4. `search_oe_norm`, `extracted_oe_norms` и `verified_matched_oe_norm` не разделены как
   разные факты с разным происхождением.
5. Отсутствующая ожидаемая Apollo-запись в listing/search parser возвращается как пустой
   рынок вместо явного `PARSER_SCHEMA_CHANGED`.
6. Некорректные offers местами молча отбрасываются через `continue`, а
   `source_confidence` безусловно устанавливается в `1`.

Требуется не написать ещё один аудит, а изменить код, БД, миграции, тесты,
observability и replay/E2E контракты. Результат должен быть fail-closed: поисковый запрос
никогда не становится доказательством совпадения, неизвестность не превращается в PASS,
а schema drift не превращается в «на рынке нет конкурентов».

---

# 1. MASTER PROMPT ДЛЯ ИИ-АГЕНТА

## 1.1. Роль

ТЫ — principal backend engineer, data-contract architect, applied statistician,
PostgreSQL migration engineer, scraper-boundary engineer, adversarial test engineer и
production-safety reviewer проекта Marko + Metis.

Твоя задача — фактически реализовать `PROMPT_15_017_VERIFIED_MARKET_IDENTITY_SPINE_P0_FIX`
в указанном checkout. Не ограничивайся рекомендациями или псевдокодом. Терминальный
результат — исправленный код, миграция, тесты, replay/integration proof, метрики,
hostile self-review и честный stop-gate.

## 1.2. Анти-упрощающий контракт

ОБЯЗАТЕЛЬНО:

1. НЕ думай о токенах, лимитах контекста, длине ответа, стоимости рассуждения или объёме
   работы. Если контекст сжимается — продолжай по manifest/checkpoint, не сокращай scope.
2. НЕ упрощай задачу до локального patch, нескольких unit-тестов, документации или
   переименования поля.
3. НЕ заменяй implementation очередным аудитом. Audit допустим только как короткий
   baseline перед изменениями и как hostile review после них.
4. Работай по фактам текущего checkout. Документ, старый отчёт и существующий тест не
   являются истиной, пока не сверены с исполняемым кодом.
5. Пиши объяснения и отчёты на русском языке. Идентификаторы, enum, reason codes,
   schemas, formulas, SQL, JSON/YAML и pseudocode пиши однозначным machine-oriented
   языком.
6. После каждого смыслового блока запускай targeted tests. После полной реализации
   проведи variation testing, migration testing, replay testing и hostile self-review.
7. Если variation обнаружила ошибку — исправь код и повтори соответствующую матрицу,
   прежде чем формировать финальный отчёт.
8. Не ослабляй fail-closed gates ради роста coverage или зелёных тестов.
9. Не выдавай `UNKNOWN`, отсутствие данных, отсутствие live-разрешения или отсутствие
   representative evidence за `PASS`.
10. Не меняй несвязанные пользовательские файлы, не очищай dirty worktree, не применяй
    destructive Git-команды и не выполняй push без отдельной прямой команды.
11. Не записывай secrets, raw credentials, персональные данные или полный чувствительный
    payload в logs, outcomes и test snapshots.
12. Не применяй цены автоматически. Этот prompt исправляет evidence/calibration spine,
    а не разрешает live price side effects.

## 1.3. Буквальная terminal objective

Работа завершена только если одновременно истинно:

```yaml
terminal_objective:
  query_only_acquisition:
    required: true
    invariant: catalog OE can start comparison without product_url or sentinel URL
  identity_separation:
    required: true
    invariant: search intent, extracted candidate OEs and verified identity are distinct
  evidence_lineage:
    required: true
    invariant: every verified OE points to retained raw evidence and extractor provenance
  calibration_safety:
    required: true
    invariant: only automatic-eligible PASS observations with verified identity are paired
  parser_truthfulness:
    required: true
    invariant: empty market and parser schema drift are distinguishable
  outcome_accounting:
    required: true
    invariant: every retrieved offer has exactly one terminal processing outcome
  confidence_truthfulness:
    required: true
    invariant: source_confidence is versioned and computed, never assigned 1 by default
  regression_safety:
    required: true
    invariant: URL-seed and replay paths remain compatible and fail closed
```

## 1.4. Начальный execution manifest

Перед изменением кода создай рабочий manifest:

```yaml
execution_input:
  prompt_id: PROMPT_15_017_VERIFIED_MARKET_IDENTITY_SPINE_P0_FIX
  requested_repo: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия
  repo_realpath: DISCOVER
  git_top_level: DISCOVER_OR_NOT_AVAILABLE
  git_commit_before: DISCOVER_OR_NOT_AVAILABLE
  branch_before: DISCOVER_OR_NOT_AVAILABLE
  dirty_paths_before: []
  database_engine: DISCOVER
  alembic_heads_before: DISCOVER
  python_version: DISCOVER
  source_access_state: DISCOVER_WITHOUT_CHANGING
  live_prom_requests_authorized: false
  automatic_price_application_authorized: false
  baseline_tests:
    command: DISCOVER
    passed: 0
    failed: 0
    skipped: 0
```

Если физический checkout не содержит `.git`, укажи `NOT_AVAILABLE`; не заимствуй commit
из соседней копии. Live-запросы не выполняй, пока они не разрешены существующей source
policy и не нужны для конкретной проверки. Основная доказательная база этого этапа —
fixtures, retained captures, deterministic replay и disposable PostgreSQL integration.

## 1.5. Подтверждённые исходные точки кода

Сначала перепроверь, затем используй как стартовую карту:

- `backend/src/marko/services/pricing_runs.py` создаёт `InputKind.PRODUCT_SEED` и
  `invalid://missing-product-url`;
- `backend/src/marko/services/scraper_architecture.py` уже содержит `InputKind.QUERY`,
  но trusted Prom admission принимает только `URL` и `PRODUCT_SEED`;
- `backend/src/marko/services/scraper_contract.py` содержит URL-only `ScrapeInput` и
  `FrozenPromScraperAdapter.extract()` через `gateway.compare()`;
- `backend/src/marko/parsers/prom/gateway.py` уже содержит raw `PromGateway.search()`;
- `backend/src/marko/services/market_collection.py` записывает каталожный OE в
  `matched_oe_norm`, безусловно задаёт `source_confidence=Decimal("1")`, молча делает
  `continue` для части invalid offers и недостаточно строго фильтрует calibration pairs;
- `backend/src/marko/parsers/prom/parser.py` возвращает пустой `ListingPage`, если
  ожидаемая listing/search Apollo-запись не найдена;
- `backend/src/marko/infrastructure/db/models.py` содержит текущий контракт
  `MarketObservation` и его constraints;
- migrations находятся в `backend/migrations/versions/`;
- parser/product normalization находится в
  `backend/src/marko/services/parser_models.py`;
- comparability policy находится в `backend/src/metis/pricing/comparability.py`;
- calibration находится в `backend/src/marko/services/market_collection.py` и
  `backend/src/metis/pricing/calibration.py`.

Если фактический код уже отличается, обнови implementation plan по текущей версии, но не
ослабляй инварианты этого prompt.

## 1.6. Жёсткие границы

НЕ ДЕЛАТЬ:

- не проектировать новый Prom parser с нуля;
- не переписывать HTTP client, pagination, retry или anti-bot logic без отдельного
  воспроизводимого дефекта;
- не считать query/catalog OE доказательством candidate OE;
- не считать fuzzy title/model/SKU достаточным основанием для verified OE;
- не backfill-ить исторический `matched_oe_norm` как verified только потому, что поле уже
  заполнено;
- не разрешать calibration через soft confidence при проваленном hard gate;
- не скрывать rejection через `continue`, пустой `except` или aggregate-only log;
- не использовать seller name как verified seller identity;
- не трактовать `source_confidence` как identity confidence или tier confidence;
- не включать automatic pricing activation;
- не удалять retained raw evidence, replay lineage или existing idempotency/fencing;
- не менять source-access verdict этим prompt.

Допускается минимальное изменение listing/search parser boundary, потому что найден
воспроизводимый дефект: отсутствие ожидаемой Apollo-записи ложно моделируется как пустой
рынок. Изменение должно быть узким, typed и покрытым fixtures.

---

# 2. Нормативная модель данных и терминология

## 2.1. Три OE-факта нельзя объединять

```text
Q = search_oe_norm
E = extracted_oe_norms
V = verified_matched_oe_norm
K = comparison_identity_key
```

Семантика:

```yaml
search_oe_norm:
  meaning: normalized OE used to discover candidates
  source: CatalogItem.oe_norm or explicit operator query
  evidentiary_value_for_candidate: none

extracted_oe_norms:
  meaning: normalized OE tokens actually observed in candidate evidence
  source: candidate structured field, SKU, title, description, characteristic or detail page
  required_lineage: raw_capture + source_path_or_span + extractor_version

verified_matched_oe_norm:
  meaning: one extracted candidate OE selected by deterministic verification
  source: must be an element of extracted_oe_norms
  nullable: true

comparison_identity_key:
  meaning: canonical part-identity cluster used for grouping
  exact_case: equals verified_matched_oe_norm
  confirmed_cross_case: approved canonical cluster key
  nullable_until_verified: true
```

Обязательные инварианты:

```text
V != null  =>  V ∈ E
K != null  =>  V != null
Q ∉ evidence_sources
E = ∅      =>  V = null
oe_status ∈ {VERIFIED_EXACT, VERIFIED_CROSS} => V != null AND K != null
oe_status ∈ {UNKNOWN, CONFLICT, AMBIGUOUS, LEGACY_UNVERIFIED} => automatic_eligible = false
```

Для exact case:

```text
VERIFIED_EXACT ⇔ V = Q ∧ evidence_strength(V) >= tau_oe
K = V
```

Для cross case:

```text
VERIFIED_CROSS ⇔ V != Q
                 ∧ CONFIRMED_CROSS(Q, V)
                 ∧ evidence_strength(V) >= tau_oe
K = canonical_cross_cluster(Q, V)
```

Сам факт, что Prom вернул предложение по запросу `Q`, не входит в формулу
`evidence_strength`.

## 2.2. OE verification status

Введи стабильный enum/string contract:

```text
VERIFIED_EXACT
VERIFIED_CROSS
UNKNOWN
CONFLICT
AMBIGUOUS
LEGACY_UNVERIFIED
```

Смысл:

- `UNKNOWN`: не найдено допустимое candidate evidence;
- `CONFLICT`: найденные сильные OE не соответствуют `Q` и не имеют подтверждённого cross;
- `AMBIGUOUS`: одновременно найдены противоречивые сильные кандидаты и невозможно
  выбрать один без ручной проверки;
- `LEGACY_UNVERIFIED`: историческая строка создана старой логикой и не может быть
  автоматически повышена до verified;
- `VERIFIED_EXACT`: OE кандидата доказан и равен `Q`;
- `VERIFIED_CROSS`: OE кандидата доказан и связан с `Q` только подтверждённым cross link.

## 2.3. Evidence item contract

Каждое извлечение OE хранить как отдельный immutable item:

```yaml
oe_evidence_item:
  raw_value: "1K0 121 251"
  normalized_value: "1K0121251"
  source_kind: STRUCTURED_OE_FIELD|LABELED_CHARACTERISTIC|SKU|TITLE|DESCRIPTION|DETAIL_PAGE
  source_record_id: "prom-product-id"
  raw_capture_id: "uuid"
  raw_content_sha256: "64-hex"
  json_path: "result.listing.page.products[3].product.sku"
  char_span:
    start: 0
    end: 9
  context_label: "OE"
  extractor_method: "structured_field|anchored_token|exact_sku|description_pattern"
  extractor_version: "oe-extractor-v1"
  confidence: "0.0000..1.0000"
  correlation_group: "listing-card:product-123:title"
```

`json_path` и `char_span` могут быть `null`, но не одновременно, если источник
не является структурированным полем. Evidence без raw hash или source record может быть
сохранён для review, но не может давать `VERIFIED_*`.

## 2.4. Acquisition input union

Не перегружай URL-only `ScrapeInput` sentinel-значением. Введи явный tagged union:

```python
AcquisitionInput = ProductSeedInput | QueryInput

class ProductSeedInput:
    input_kind = "product_seed"
    product_url: str
    canonical_url: str
    product_key: str
    query: str
    input_hash: str

class QueryInput:
    input_kind = "query"
    query: str
    language: str
    query_key: str
    input_hash: str
```

Нормативный hash:

```text
H_url = SHA256(canonical_json({
  adapter_version,
  input_kind: "product_seed",
  product_key,
  query
}))

H_query = SHA256(canonical_json({
  adapter_version,
  input_kind: "query",
  source: "prom_public",
  language,
  query
}))
```

`invalid://...` и любой другой sentinel запрещены. Повторный query в одном run обязан
дедуплицироваться по `H_query`.

## 2.5. Scraper output v2

Подними output schema additively, сохранив replay старого v1:

```yaml
schema_version: prom-market-acquisition-v2
adapter_version: prom-parser-adapter-vNEXT
input:
  input_kind: query|product_seed
  query: "1K0121251"
  canonical_url: null
  input_hash: "..."
output:
  acquisition_outcome: RESULTS|EMPTY_SEARCH_RESULT
  candidates_scanned: 12
  records: []
```

Для `query` branch используй существующий `PromGateway.search(..., strict=True)`. Не
создавай фиктивный `SeedInfo` и не выдавай query за seed evidence. Raw candidates должны
быть сериализованы детерминированно и пройти enrichment/materialization позже.

Единица `records[]` — `CandidateEnvelope`, а не заранее доказанный offer:

```yaml
candidate_envelope:
  raw_offer_index: 0
  retrieval_kind: search_query|product_seed_comparison
  retrieval_score: null
  product: {}
  upstream_comparison_evidence: null
```

Для query search `retrieval_score=null`: сам факт выдачи в поиске не должен получать
искусственный `match_score`. Для legacy product-seed payload compatibility adapter
преобразует старые `offers[]` в `records[]` и сохраняет upstream retrieval score как
недоказательный retrieval signal.

`match_confidence` формируется после OE verification:

```text
VERIFIED_EXACT: match_confidence = C_oe(V)
VERIFIED_CROSS: match_confidence = min(C_oe(V), confirmed_cross_confidence)
UNKNOWN/CONFLICT/AMBIGUOUS: match_confidence may be stored for diagnostics,
                            but automatic_eligible = false
```

Для `product_seed` branch сохрани текущую совместимость `gateway.compare()`, но приведи
его persisted offer к тому же downstream identity contract.

V1 replay должен читаться через explicit compatibility adapter:

```text
v1 payload -> LegacyPayloadAdapter -> v2 internal representation
legacy OE attribution -> LEGACY_UNVERIFIED unless raw evidence is re-enriched
```

---

# 3. Математический safety contract

## 3.1. Identity evidence aggregation

Пусть для нормализованного OE `x` найдено множество evidence items `I_x`. Сначала
группируй коррелированные копии, чтобы одна и та же строка, продублированная в title и
description, не считалась независимыми подтверждениями.

Для каждой независимой группы `g`:

```text
c_g(x) = max(c_i), i ∈ I_x and group(i)=g
```

Агрегированная уверенность:

```text
C_oe(x) = 1 - product_g(1 - c_g(x))
```

Рекомендуемые стартовые веса должны быть versioned config, а не magic numbers:

```yaml
oe_extractor_v1:
  structured_oe_field: 0.99
  labeled_manufacturer_code: 0.97
  exact_sku_with_oe_label: 0.93
  anchored_title_token: 0.90
  exact_sku_without_label: 0.78
  anchored_description_token: 0.75
  unanchored_numeric_token: 0.20
  verification_threshold: 0.90
```

Один unanchored token никогда не может дать `VERIFIED_*`, даже если формула после
ошибочного дублирования стала высокой. Добавь rule:

```text
VERIFIED requires:
  provenance_complete
  AND C_oe(x) >= 0.90
  AND (
    exists STRONG_SOURCE with c >= 0.90
    OR exists >= 2 independent MEDIUM_SOURCE groups
  )
```

Не извлекай как OE:

- цены, телефоны, годы, количество, product ID и seller ID;
- токены без букв/цифр, не проходящие действующий `normalize_oe`/validation contract;
- значение, которое существует только в `search_oe_norm` или URL query parameters.

## 3.2. Automatic eligibility gate

Определи hard gates:

```text
g_oe          = 1 iff oe_status in {VERIFIED_EXACT, VERIFIED_CROSS}
g_policy      = 1 iff hard_gate_result = PASS
g_seller      = 1 iff seller_identity_verified = true
g_provenance  = 1 iff source_provenance_verified = true
g_currency    = 1 iff explicit normalized currency matches policy currency
g_condition   = 1 iff category condition rule passes
g_package     = 1 iff category package rule passes or is approved N/A
g_source      = 1 iff source_confidence >= source_confidence_min

G_auto = product(g_oe, g_policy, g_seller, g_provenance,
                 g_currency, g_condition, g_package, g_source)
```

Нормативно:

```text
automatic_eligible ⇔ G_auto = 1
G_auto = 0 => observation may be stored, but cannot enter automatic cohort
```

Нельзя вычислять `automatic_eligible` только как
`comparison_evidence.hard_gate_result == PASS`, если scalar identity fields не
согласованы с evidence.

## 3.3. Calibration eligibility gate

Для observation `o`:

```text
g_cal(o) =
  I[o.automatic_eligible = true]
  * I[o.comparability_hard_gate_result = PASS]
  * I[o.oe_verification_status in {VERIFIED_EXACT, VERIFIED_CROSS}]
  * I[o.verified_matched_oe_norm != null]
  * I[o.comparison_identity_key != null]
  * I[o.seller_identity_verified = true]
  * I[o.source_provenance_verified = true]
  * I[o.is_available = true]
  * I[o.currency = policy.currency]
  * I[o.match_confidence >= tau_match]
  * I[o.source_confidence >= tau_source]
  * I[tier_confidence >= tau_tier]
  * I[condition/package/category hard rules pass]
  * I[not used]
  * I[not owned]
  * I[tier != UNKNOWN]
```

Только `g_cal(o)=1` допускает observation в calibration pair.

Группировка:

```text
calibration_group_key = (canonical_category_id, comparison_identity_key)
```

Не используй `(item.category, item.oe_norm)` как доказательство identity. Raw category
может временно остаться до отдельной нормализации, но identity key уже должен быть
verified.

Для каждой исключённой строки сохраняй один или несколько `calibration_exclusion_codes`:

```text
CAL_NOT_AUTOMATIC_ELIGIBLE
CAL_HARD_GATE_NOT_PASS
CAL_OE_NOT_VERIFIED
CAL_IDENTITY_KEY_MISSING
CAL_SELLER_NOT_VERIFIED
CAL_PROVENANCE_NOT_VERIFIED
CAL_SOURCE_CONFIDENCE_LOW
CAL_TIER_CONFIDENCE_LOW
CAL_USED
CAL_OWNED
CAL_CURRENCY_MISMATCH
CAL_STALE
CAL_UNAVAILABLE
```

## 3.4. Source confidence

`source_confidence` измеряет надёжность acquisition/parser/provenance источника. Он НЕ
измеряет OE identity, tier или коммерческую сопоставимость.

Введи versioned method `source-confidence-v1` и сохраняй factors:

```text
g_raw      = I[retained raw capture exists and SHA-256 verifies]
g_contract = I[recognized parser/output schema contract]

q_listing      ∈ [0,1]
q_seller       ∈ [0,1]
q_price_fx     ∈ [0,1]
q_availability ∈ [0,1]
q_url          ∈ [0,1]
q_structure    ∈ [0,1]

w = {0.20, 0.20, 0.20, 0.10, 0.10, 0.20}

C_source = 0, if g_raw=0 or g_contract=0
C_source = sum_i(w_i * q_i), otherwise
```

Требования:

```text
0 <= C_source <= 1
C_source = 1 iff all q_i = 1 and both hard gates pass
missing stable seller ID => q_seller < 1 and g_seller=0 separately
inferred currency => q_price_fx < 1 and g_currency=0 separately
fallback-hashed listing identity => q_listing < 1
schema drift => g_contract=0 => C_source=0
```

Значения факторов зафиксируй в коде/конфиге и протестируй; не разбрасывай literals по
двум persistence paths. Используй один pure function для payload и legacy materializer.

## 3.5. Conservation law для offers

Пусть:

```text
R = retrieved_offer_total
O = observation_persisted_total
J = offer_rejected_total
F = offer_internal_failure_total
```

Для каждого capture/run item:

```text
R = O + J + F
R, O, J, F >= 0
```

Каждый retrieved element получает ровно один terminal outcome. `parsed`, `enriched` и
`eligible` — промежуточные monotonic counters, а не элементы partition:

```text
R >= parsed >= enriched >= eligible >= 0
```

Нарушение conservation law — `EVIDENCE_ACCOUNTING_ERROR`, run item не может считаться
успешно materialized.

## 3.6. Empty market vs schema drift

```text
EMPTY_SEARCH_RESULT iff:
  expected Apollo query record exists
  AND result.listing.page has recognized schema
  AND products is a valid empty list
  AND total is 0 or semantically equivalent verified empty indicator

PARSER_SCHEMA_CHANGED iff:
  Apollo state exists
  AND expected query record is absent
  OR listing/page/products shape violates recognized contract
```

`EMPTY_SEARCH_RESULT` — успешный acquisition outcome с `offers=[]`.
`PARSER_SCHEMA_CHANGED` — terminal parse failure с retained raw evidence,
`operator_action=REPLAY_REQUIRED`, `downstream_eligibility=INELIGIBLE` и alert.

---

# 4. Целевая архитектура

```text
CatalogItem.oe_norm
  |
  v
InputFactory
  |-- product_url exists --> ProductSeedInput --> gateway.compare(strict=True)
  |-- no product_url ------> QueryInput -------> gateway.search(strict=True)
  |
  v
ScrapeOutput v2 + retained raw HTTP captures
  |
  v
OfferProcessor (total typed function)
  |-- INVALID --------------------------> OfferProcessingOutcome(REJECTED_*)
  |-- VALID --> OEExtractor ------------> extracted_oe_norms + provenance
                  |
                  v
              OEVerifier(Q, E, cross_links)
                  |-- UNKNOWN/CONFLICT --> persisted review observation
                  |-- VERIFIED ---------> comparability evaluation
                                             |
                                             v
                                       automatic eligibility
                                             |
                                             v
                                       calibration selector
```

`OfferProcessor` должен быть total-function по входному raw element:

```python
def process_offer(raw_offer, context) -> AcceptedObservation | RejectedOffer:
    ...
```

Запрещён control flow, где invalid row исчезает без typed result.

---

# 5. PHASE 0 — Baseline и воспроизведение

## 5.1. Обязательные действия

1. Прочитай `AGENTS.md` полностью.
2. Зафиксируй path/provenance/dirty state.
3. Найди все read/write использования:
   - `matched_oe_norm`;
   - `source_confidence`;
   - `automatic_eligible`;
   - `hard_gate_result`;
   - `InputKind.QUERY`;
   - `ScrapeInput.build`;
   - parser empty-result semantics;
   - calibration selection.
4. Запусти baseline tests.
5. Добавь шесть regression tests, которые сначала воспроизводят P0 и падают на старом
   коде.

## 5.2. Baseline reproduction matrix

| ID | Вход | Старое ошибочное поведение | Требуемое поведение |
|---|---|---|---|
| R1 | CatalogItem с OE, без URL | sentinel/terminal failure | valid `QueryInput` |
| R2 | Query Q, offer без OE evidence | `matched_oe_norm=Q` | `V=null`, `UNKNOWN` |
| R3 | hard gate manual/reject | может войти в calibration | excluded with code |
| R4 | Apollo state без expected search record | empty market | schema-changed failure |
| R5 | invalid price/malformed offer | silent continue | persisted rejection outcome |
| R6 | incomplete source fields | confidence `1` | computed `<1` |

Stop-gate:

```text
STOP_GATE_PHASE_0 = PASS iff all six defects are reproduced deterministically
```

---

# 6. PHASE 1 — Query-only acquisition без product_url

## 6.1. Изменения input/admission contract

1. Используй существующий `InputKind.QUERY`.
2. Разреши его только для разрешённых acquisition modes, минимум:
   `COMPARISON_JOB` и `QUERY_BATCH`.
3. Валидируй query:
   - Unicode normalization;
   - trim/collapse whitespace;
   - uppercase;
   - length `1..255`;
   - reject control characters;
   - никакого URL/sentinel в query field.
4. Trusted admission должен создавать server-side policy decision и idempotency keys для
   query точно так же, как для URL lane.
5. Source access policy остаётся неизменной.

## 6.2. Input selection

```python
if catalog_item.product_url is not None:
    item = ScrapeRequestItem(
        input_kind=InputKind.PRODUCT_SEED,
        input_value=catalog_item.product_url,
        metadata={"query": catalog_item.oe_norm},
    )
else:
    item = ScrapeRequestItem(
        input_kind=InputKind.QUERY,
        input_value=catalog_item.oe_norm,
        metadata={"language": "ua"},
    )
```

Удалить `invalid://missing-product-url` из production path и tests. Добавить static test:

```text
rg "invalid://missing-product-url" backend/src backend/tests => no runtime occurrences
```

## 6.3. Adapter branch

Расширь frozen wrapper, не меняя parser internals:

```python
match acquisition_input:
    case ProductSeedInput():
        result = gateway.compare(url, query=query, strict=True)
        return output_from_comparison(result)
    case QueryInput():
        products = list(gateway.search(query, lang=language, strict=True))
        return output_from_search(products)
```

`output_from_search` не должен вызывать `match_offer` до OE enrichment. Он сериализует
retrieved candidates в `CandidateEnvelope.records` и их source fields. Не добавляй
фиктивный `match_score=1` для удовлетворения старой schema.

## 6.4. Compatibility

Проверь:

- URL-present item продолжает использовать product-seed path;
- URL-absent item использует query path;
- одинаковые query в одном run дедуплицируются;
- разные tenant/workspace scope не разделяют unsafe cache;
- redelivery не создаёт второй target;
- replay не делает network request;
- URL query и query-only имеют разные input hashes.

Stop-gate:

```text
STOP_GATE_PHASE_1 = PASS iff no URL is required to create and execute a query target
```

---

# 7. PHASE 2 — PostgreSQL identity schema и безопасная миграция

## 7.1. Новые поля MarketObservation

Добавь минимум:

```text
search_oe_norm                    VARCHAR(255) NOT NULL
extracted_oe_norms                JSON NOT NULL DEFAULT '[]'
verified_matched_oe_norm          VARCHAR(255) NULL
comparison_identity_key           VARCHAR(255) NULL
oe_verification_status            VARCHAR(32) NOT NULL
oe_evidence                       JSON NOT NULL DEFAULT '[]'
comparability_hard_gate_result    VARCHAR(32) NOT NULL
source_confidence_factors         JSON NOT NULL DEFAULT '{}'
source_confidence_method_version  VARCHAR(80) NOT NULL
```

Существующий `matched_oe_norm`:

- объявить deprecated;
- изменить на nullable, если он нужен для rolling compatibility;
- новый код не должен использовать его для eligibility/calibration;
- удалить отдельной последующей migration только после исчезновения всех readers.

## 7.2. Constraints

Добавь DB constraints, насколько позволяет PostgreSQL/schema:

```sql
CHECK (oe_verification_status IN (
  'VERIFIED_EXACT', 'VERIFIED_CROSS', 'UNKNOWN',
  'CONFLICT', 'AMBIGUOUS', 'LEGACY_UNVERIFIED'
));

CHECK (comparability_hard_gate_result IN ('PASS', 'MANUAL_REVIEW', 'REJECT'));

CHECK (
  (oe_verification_status IN ('VERIFIED_EXACT', 'VERIFIED_CROSS')
   AND verified_matched_oe_norm IS NOT NULL
   AND comparison_identity_key IS NOT NULL)
  OR
  (oe_verification_status NOT IN ('VERIFIED_EXACT', 'VERIFIED_CROSS')
   AND verified_matched_oe_norm IS NULL
   AND comparison_identity_key IS NULL)
);

CHECK (
  NOT automatic_eligible OR (
    oe_verification_status IN ('VERIFIED_EXACT', 'VERIFIED_CROSS')
    AND verified_matched_oe_norm IS NOT NULL
    AND comparison_identity_key IS NOT NULL
    AND comparability_hard_gate_result = 'PASS'
    AND seller_identity_verified
    AND source_provenance_verified
  )
);
```

JSON membership `V ∈ E` дополнительно валидируй в service/domain layer и integration
tests. Если используешь PostgreSQL JSONB, можешь добавить constraint, но не создавай
непереносимую illusion safety без теста реальной БД.

## 7.3. Backfill policy

Исторические данные не являются verified.

```text
legacy.search_oe_norm = legacy.matched_oe_norm or CatalogItem.oe_norm
legacy.extracted_oe_norms = []
legacy.verified_matched_oe_norm = null
legacy.comparison_identity_key = null
legacy.oe_verification_status = LEGACY_UNVERIFIED
legacy.comparability_hard_gate_result = value_from_evidence_or_MANUAL_REVIEW
legacy.automatic_eligible = false unless row is deterministically re-enriched from raw capture
```

Запрещено:

```text
UPDATE ... SET verified_matched_oe_norm = matched_oe_norm
```

без повторной extraction/verification по retained raw evidence.

## 7.4. Migration verification

Обязательны:

- upgrade from previous head on populated PostgreSQL;
- constraint violation tests;
- downgrade или документированная irreversible boundary;
- replay старой fixture после upgrade;
- `alembic current`, `alembic heads`, single-head check;
- model/migration parity test.

Stop-gate:

```text
STOP_GATE_PHASE_2 = PASS iff legacy rows remain explicitly unverified and new invalid states are rejected
```

---

# 8. PHASE 3 — OE extraction, provenance и verification

## 8.1. Один deterministic enrichment service

Создай отдельный модуль, например:

```text
backend/src/marko/services/offer_identity.py
```

Он должен содержать pure/domain functions:

```python
extract_oe_evidence(raw_offer, raw_capture_manifest) -> tuple[OeEvidenceItem, ...]
verify_offer_identity(search_oe_norm, evidence_items, confirmed_crosses) -> OeVerification
build_comparison_identity_key(verification) -> str | None
```

Обе persistence ветки в `market_collection.py` обязаны вызывать один service. Не
дублируй логику для stored payload и legacy `PriceComparison` path.

## 8.2. Source precedence

Проверяй источники в порядке:

1. typed `comparisonEvidence.oeRaw`;
2. labeled structured characteristics (`OE`, `OEM`, manufacturer code);
3. `sku` с явным OE label/provenance;
4. anchored OE token в title;
5. anchored OE token в description;
6. detail-page enrichment только для bounded shortlist и только через существующий
   acquisition/evidence journal.

Ни один источник не должен читать `search_oe_norm` как candidate field.

## 8.3. Verification algorithm

```python
def verify(Q, evidence, confirmed_crosses):
    E = unique(item.normalized_value for item in evidence)
    if not E:
        return UNKNOWN

    strong = {x for x in E if eligible_strength(x, evidence) >= TAU_OE}
    if not strong:
        return UNKNOWN

    exact = {x for x in strong if x == Q}
    cross = {x for x in strong if confirmed_cross(Q, x)}
    incompatible = strong - exact - cross

    if incompatible and (exact or cross):
        return AMBIGUOUS
    if len(exact) == 1 and not cross:
        return VERIFIED_EXACT(V=Q, K=Q)
    if not exact and len(cross) == 1:
        x = only(cross)
        return VERIFIED_CROSS(V=x, K=canonical_cluster(Q, x))
    if len(exact | cross) > 1:
        return AMBIGUOUS
    return CONFLICT
```

Не используй transitive cross closure без отдельного подтверждённого policy. Только
существующий `CONFIRMED` one-hop link может дать `VERIFIED_CROSS`.

## 8.4. Comparability evidence binding

После verification обнови dimension `oe_reference`:

```text
VERIFIED_EXACT or VERIFIED_CROSS -> EvidenceState.MATCH with evidence_refs
CONFLICT                         -> EvidenceState.CONFLICT
UNKNOWN or AMBIGUOUS             -> EvidenceState.UNKNOWN / manual review
```

Evidence refs должны указывать на реальные `oe_evidence_item`, а не на query.
Повторно вычисли comparability decision после binding persisted provenance, condition,
package и category policy.

Stop-gate:

```text
STOP_GATE_PHASE_3 = PASS iff Q alone cannot produce V and every V is traceable to raw evidence
```

---

# 9. PHASE 4 — Empty market и Apollo schema drift

## 9.1. Typed parser outcomes

В parser/exceptions добавь специализированную ошибку или stable error code:

```text
PARSER_SCHEMA_CHANGED
```

В scraper error taxonomy добавь machine code:

```text
parser_schema_changed
```

Он должен маппиться как:

```yaml
retryable: false
acquisition_status: SUCCEEDED
parse_status: FAILED
evidence_status: RAW_AVAILABLE
downstream_eligibility: INELIGIBLE
operator_action: REPLAY_REQUIRED
reason_codes: [parser_schema_changed]
```

Если raw HTTP получить не удалось, это network/acquisition failure, а не schema change.

## 9.2. Parser behavior

Измени только воспроизводимый boundary:

```python
record = find_expected_record(cache, key_prefix)
if record is None:
    raise ParserSchemaChanged("expected Apollo record is absent")

page = get_nested(record, "result.listing.page")
if not recognized_page_shape(page):
    raise ParserSchemaChanged("listing page shape is invalid")

if page["products"] == [] and normalized_total(page) == 0:
    return ListingPage(products=[], total=0, ..., outcome="EMPTY_SEARCH_RESULT")
```

Не определяй empty market по отсутствию record.

## 9.3. Fixtures

Добавь минимум:

1. valid results;
2. valid explicit empty result;
3. Apollo state missing entirely;
4. Apollo state exists, expected record absent;
5. expected record exists, `listing.page` absent;
6. `products` wrong type;
7. total contradicts empty products;
8. unrelated Apollo records only;
9. v1 retained capture replay;
10. schema-changed capture produces replay-required, not zero-market recommendation.

Stop-gate:

```text
STOP_GATE_PHASE_4 = PASS iff no schema-drift fixture can become EMPTY_SEARCH_RESULT
```

---

# 10. PHASE 5 — Total offer processing и truthful source confidence

## 10.1. Outcome model

Введи append-only `OfferProcessingOutcome` table или эквивалентный persisted typed
ledger:

```text
id
pricing_run_item_id
raw_market_capture_id
market_observation_id nullable
source_listing_id nullable
raw_offer_index
outcome_code
stage
reason_codes JSON
payload_sha256 nullable
safe_sample JSON nullable
created_at
```

Добавь unique constraint минимум на
`(raw_market_capture_id, pricing_run_item_id, raw_offer_index)`, чтобы один raw element
не мог получить два terminal outcomes при redelivery. Для
`OBSERVATION_PERSISTED` поле `market_observation_id` обязательно; для rejection/failure —
`null`.

Terminal codes минимум:

```text
OBSERVATION_PERSISTED
REJECTED_NOT_MAPPING
REJECTED_INVALID_PRICE
REJECTED_INVALID_MATCH_SCORE
REJECTED_MISSING_LISTING_IDENTITY
REJECTED_SCHEMA_MISMATCH
REJECTED_SERIALIZATION
FAILED_INTERNAL_PROCESSING
```

Identity/comparability unknown не обязательно отклонять: сохраняй observation с
`automatic_eligible=false`, чтобы оператор видел причину и система измеряла coverage.

## 10.2. Удаление silent continue

Заменить:

```python
except Exception:
    continue
```

на узкие exception types и typed rejection. Не перехватывай `BaseException`; неожиданный
bug должен дать `FAILED_INTERNAL_PROCESSING`, metric и fail/partial materialization по
явной policy.

## 10.3. Atomicity

В одной транзакции materialization должны согласованно появиться:

- `RawMarketCapture`;
- accepted `MarketObservation`;
- tier classification;
- terminal outcome для каждого raw offer;
- aggregate accounting counters/checkpoint.

Если conservation law не выполняется, rollback materialization и пометь target/run item
`EVIDENCE_ACCOUNTING_ERROR`. Не коммить частичный набор без explicit partial contract.

## 10.4. Confidence function

Создай один pure function:

```python
assess_source_confidence(
    raw_capture_verified,
    parser_contract_verified,
    listing_identity_quality,
    seller_identity_quality,
    price_currency_quality,
    availability_quality,
    url_quality,
    structured_completeness,
) -> SourceConfidenceAssessment
```

Возвращай:

```yaml
value: "0.8425"
method_version: source-confidence-v1
factors: {}
reason_codes: []
```

Удалить unconditional `Decimal("1")` из обеих persistence веток.

Stop-gate:

```text
STOP_GATE_PHASE_5 = PASS iff R=O+J+F and no incomplete offer receives confidence 1
```

---

# 11. PHASE 6 — Calibration hardening

## 11.1. Selection predicate

Перепиши `_derive_calibration_pairs` так, чтобы predicate был отдельной pure function или
query specification с reason codes:

```python
evaluate_calibration_eligibility(
    item,
    observation,
    classification,
    policy,
    now,
) -> CalibrationEligibilityDecision
```

Первым слоем проверяй:

```text
automatic_eligible
comparability_hard_gate_result == PASS
oe_verification_status verified
verified_matched_oe_norm present
comparison_identity_key present
seller_identity_verified
source_provenance_verified
```

Только затем price/currency/availability/age/confidence/tier/used/owned.

## 11.2. Dataset identity

Calibration dataset hash должен включать:

```text
observation_id
comparison_identity_key
verified_matched_oe_norm
oe_verification_status
comparability_policy_hash
source_confidence_method_version
tier_method_version
price
currency
seller_id
observed_at
```

Изменение identity/evidence должно менять dataset hash и replay fingerprint.

## 11.3. Exclusion accounting

Финальный calibration report обязан показывать:

```yaml
calibration_accounting:
  observations_considered: 0
  eligible_observations: 0
  excluded_observations: 0
  exclusion_counts_by_reason: {}
  exact_oe_groups: 0
  confirmed_cross_groups: 0
  category_tier_pairs: 0
  dataset_hash: null
```

Инвариант:

```text
considered = eligible + unique_excluded
```

## 11.4. Fail-closed sparse data

Если после новых gates пар недостаточно, calibration должна вернуть existing
`insufficient/unvalidated/global fallback` semantics, а не ослабить thresholds.

Stop-gate:

```text
STOP_GATE_PHASE_6 = PASS iff one failed identity/comparability gate excludes the row deterministically
```

---

# 12. PHASE 7 — API, replay, observability и operator trace

## 12.1. API/read models

В observation/recommendation debug endpoints отдай безопасно:

```text
search_oe_norm
extracted_oe_norms
verified_matched_oe_norm
comparison_identity_key
oe_verification_status
oe_evidence_summary
comparability_hard_gate_result
automatic_eligible
source_confidence
source_confidence_factors
source_confidence_method_version
offer_outcome_counts
calibration_exclusion_codes
```

Не отдавай полный raw HTML через обычный API. Evidence detail должен ссылаться на
controlled evidence endpoint/ID.

## 12.2. Metrics

Добавь counters/gauges:

```text
pricing_query_only_targets_total
pricing_product_seed_targets_total
prom_empty_search_result_total
prom_parser_schema_changed_total
offer_retrieved_total
offer_observation_persisted_total
offer_rejected_total{reason}
offer_internal_failure_total{reason}
oe_extraction_total{source_kind}
oe_verification_total{status}
oe_verified_exact_total
oe_verified_cross_total
oe_unknown_total
oe_conflict_total
oe_ambiguous_total
calibration_observation_excluded_total{reason}
source_confidence_bucket
evidence_accounting_error_total
```

Не помещай raw OE, URL, payload или seller name в metric labels.

## 12.3. Alerts

Минимальные operational signals:

```text
parser_schema_changed_total > 0 in rolling window -> alert
schema_changed_rate > 1% of parsed pages -> critical alert
offer_internal_failure_total > 0 -> alert
evidence_accounting_error_total > 0 -> critical alert
verified_oe_rate sudden drop > configured delta -> warning
source_confidence p50 sudden drop -> warning
```

Thresholds должны быть config/versioned; не hardcode production alert routing в domain
logic.

## 12.4. Replay invariants

Replay одного и того же capture с теми же версиями должен давать:

```text
same extracted_oe_norms
same verification status
same verified_matched_oe_norm
same identity key
same source confidence
same outcome partition
same calibration eligibility
same decision fingerprint
zero network requests
```

Stop-gate:

```text
STOP_GATE_PHASE_7 = PASS iff operator can explain every inclusion/exclusion from persisted trace
```

---

# 13. Обязательная variation test matrix

## 13.1. Query-only acquisition

| Case | URL | OE query | Expected |
|---|---:|---|---|
| Q1 | absent | valid | query target admitted per source policy |
| Q2 | present | valid | product-seed target |
| Q3 | absent | empty | invalid input before network |
| Q4 | absent | >255 chars | invalid input |
| Q5 | absent | same normalized query twice | one deduplicated target |
| Q6 | absent | two different queries | two targets |
| Q7 | absent | valid, replay mode | zero network |
| Q8 | sentinel string | valid | rejected; sentinel forbidden |

## 13.2. OE identity

| Case | Q | Candidate evidence | Expected |
|---|---|---|---|
| O1 | X | none | UNKNOWN, V=null |
| O2 | X | search query only | UNKNOWN, V=null |
| O3 | X | structured OE=X | VERIFIED_EXACT |
| O4 | X | anchored title OE=X | VERIFIED_EXACT if threshold/provenance pass |
| O5 | X | unanchored number X | UNKNOWN |
| O6 | X | strong OE=Y, no cross | CONFLICT |
| O7 | X | strong OE=Y, CONFIRMED one-hop cross | VERIFIED_CROSS |
| O8 | X | strong X and incompatible Y | AMBIGUOUS |
| O9 | X | SKU=X but no label/second source | below automatic threshold per policy |
| O10 | X | price/year/phone resembles OE | ignored |
| O11 | X | normalized punctuation variant of X | deterministic exact |
| O12 | X | same text duplicated in title/description | no false independence |
| O13 | X | different brand, exact OE, new compatible unit | identity can pass; brand only tier |
| O14 | X | exact OE, USED vs NEW | comparability rejects/manual |
| O15 | X | exact OE, package 1 vs 2 | conflict/manual per category policy |

## 13.3. Parser result taxonomy

| Case | Apollo record | page shape | products | Expected |
|---|---|---|---|---|
| P1 | present | valid | non-empty | RESULTS |
| P2 | present | valid | [] + total 0 | EMPTY_SEARCH_RESULT |
| P3 | absent | n/a | n/a | PARSER_SCHEMA_CHANGED |
| P4 | present | missing page | n/a | PARSER_SCHEMA_CHANGED |
| P5 | present | valid | wrong type | PARSER_SCHEMA_CHANGED |
| P6 | no Apollo state | n/a | n/a | PARSE_CONTRACT/antibot-specific failure |
| P7 | unrelated query record | n/a | n/a | PARSER_SCHEMA_CHANGED |

## 13.4. Calibration

Сделай pairwise variation: одна полностью valid observation и по одной мутации каждого
gate. Каждая мутация обязана исключаться с точным code:

```text
automatic_eligible=false
hard_gate=MANUAL_REVIEW
hard_gate=REJECT
oe_status=UNKNOWN
verified OE=null
identity key=null
seller unverified
provenance unverified
source confidence below threshold
tier confidence below threshold
used=true
owned=true
unavailable
currency mismatch
stale
```

## 13.5. Offer outcomes/confidence

Проверь:

- non-mapping element;
- missing/invalid/NaN/infinite/negative price;
- missing seller;
- invalid match score;
- invalid evidence JSON;
- invalid URL;
- duplicate listing;
- unexpected exception inside extractor;
- incomplete but storable observation;
- fully complete observation;
- conservation law under mixed batch;
- rollback when ledger write fails.

## 13.6. Concurrency/idempotency

Проверь на PostgreSQL:

- два worker delivery одного target;
- expired lease/redelivery;
- same query for multiple CatalogItems;
- replay после partial failure;
- migration + worker старой версии не создают unsafe verified rows;
- unique constraints не вызывают silent data loss;
- winner fencing не позволяет stale attempt перезаписать evidence.

---

# 14. Test pyramid и обязательные команды

## 14.1. Unit tests

Минимум:

```text
test_query_input_contract.py
test_offer_identity.py
test_source_confidence.py
test_offer_processing_outcomes.py
test_parsing.py
test_tier_calibration.py
```

Имена адаптируй к текущей структуре, не создавая дубликаты существующих suites.

## 14.2. PostgreSQL integration

SQLite/mocks недостаточны для migration/constraint доказательства. Нужны tests на
PostgreSQL:

1. upgrade populated previous schema;
2. legacy rows становятся `LEGACY_UNVERIFIED`;
3. invalid verified state отвергается constraint;
4. query-only pricing run создаётся без URL;
5. materialization сохраняет outcomes и observations атомарно;
6. calibration читает verified identity fields;
7. redelivery идемпотентен.

## 14.3. Replay E2E

Используй retained fixture/capture:

```text
catalog item without URL
-> query acquisition input
-> replayed search capture
-> candidate extraction
-> OE verification
-> comparability
-> calibration inclusion/exclusion
-> recommendation/manual review
```

Assert `network_requests=0`.

## 14.4. Suggested command sequence

Сначала выясни реальные команды проекта. Ожидаемый минимум:

```bash
cd backend
uv run pytest -q tests/test_parsing.py tests/test_prom_search_boundary.py
uv run pytest -q tests/test_matching.py tests/test_comparability_contract.py
uv run pytest -q tests/test_tier_calibration.py
uv run pytest -q <new-targeted-tests>
uv run alembic upgrade head
uv run pytest -q
```

Если проект имеет lint/typecheck/format/migration check — запусти их. Не утверждай, что
команда прошла, если она не выполнялась или была `SKIPPED`.

---

# 15. Performance и scaling contract

P0 не должен создавать безграничный detail-page fan-out.

Обозначения:

```text
N_q      = unique query inputs
n_s      = search candidates per query
k        = detail-page shortlist size
r_d      = detail page requests per query
a        = retry amplification
S_raw    = average retained raw bytes
S_struct = average structured bytes
```

Ограничения:

```text
0 <= r_d <= k <= n_s
Requests_total <= N_q * (search_pages + k) * a
Storage_total ≈ captures * (S_raw + S_struct + S_metadata)
```

Detail enrichment по умолчанию выполняется только для candidates, которые прошли
price/seller/availability prefilter, но ещё не имеют достаточного OE evidence. `k` должен
быть config-bounded. Если detail enrichment не реализован в этом P0, система обязана
оставить OE как UNKNOWN, а не предположить match.

Измерь до/после хотя бы на replay batch:

```text
query_targets_total
candidates_per_query p50/p95
offer_processing_latency p50/p95
oe_extraction_latency p50/p95
memory_peak
raw_storage_bytes
structured_storage_bytes
retry_amplification
```

Performance regression не должен оправдывать удаление evidence или outcomes.

---

# 16. Security, privacy и deterministic behavior

1. Query и URL проходят trusted server-side validation.
2. Query input не должен позволять SSRF: query никогда не интерпретируется как URL.
3. URL path продолжает принимать только разрешённые Prom hosts/product paths.
4. Raw payload хранится существующим evidence layer, а outcomes содержат hash и
   минимальный safe sample.
5. Logs не содержат secrets, cookies, Authorization headers или полный HTML.
6. Evidence/order serialization использует canonical JSON и stable sorting.
7. Hashes включают версии extractor/policy/schema.
8. Tenant/workspace scope входит в submission/acquisition idempotency namespace.
9. Cross-link decision требует существующий confirmed status; agent не имеет права
   автоматически «одобрить» cross ради теста.
10. Historical records не становятся automatic eligible после одной migration.

---

# 17. Rollout и backward compatibility

## 17.1. Safe deployment order

```text
1. Deploy additive migration and compatibility readers.
2. Deploy code that writes new fields and no longer trusts matched_oe_norm.
3. Re-enrich retained raw captures in bounded background job.
4. Measure UNKNOWN/CONFLICT/verified rates.
5. Enable calibration reader on new verified fields.
6. Observe shadow/manual mode.
7. Remove deprecated matched_oe_norm only in later migration.
```

Если rolling deploy невозможен, документируй required maintenance window, но не
симулируй compatibility.

## 17.2. Re-enrichment job

Background job обязан:

- работать только по retained raw evidence;
- не выполнять новые network requests;
- быть idempotent;
- записывать extractor version;
- не повышать status при недостаточном evidence;
- публиковать counts `verified/unknown/conflict/ambiguous/failed`;
- поддерживать dry-run.

## 17.3. Rollback

Rollback приложения не должен приводить к записи ложных verified значений. Если старая
версия несовместима с новой schema semantics, release gate обязан потребовать coordinated
deployment или временную DB protection/trigger. Не оставляй mixed-version corruption как
«операционный риск» без решения.

---

# 18. Hostile self-review

После зелёных тестов проведи отдельный adversarial review. Ответь доказательно:

1. Можно ли всё ещё получить `verified_matched_oe_norm` только из query?
2. Может ли legacy row стать verified без raw replay?
3. Может ли `automatic_eligible=false` попасть в calibration?
4. Может ли `hard_gate_result != PASS` попасть в calibration?
5. Может ли `PARSER_SCHEMA_CHANGED` стать нулевым рынком?
6. Есть ли `except Exception: continue` или эквивалентный silent loss в offer path?
7. Остался ли unconditional `source_confidence=1`?
8. Есть ли две расходящиеся реализации identity/confidence?
9. Может ли duplicate/redelivery нарушить `R=O+J+F`?
10. Может ли cross `REVIEW/UNKNOWN/REJECTED` дать verified identity?
11. Может ли missing seller/currency/raw hash компенсироваться soft score?
12. Совпадают ли migration constraints и ORM defaults?
13. Меняется ли dataset hash при изменении verified identity?
14. Делает ли replay ноль network calls?
15. Сохранился ли URL-seed path?

Используй repository search:

```bash
rg -n "invalid://missing-product-url|matched_oe_norm|source_confidence=Decimal\(\"1\"\)|except Exception" backend/src backend/tests
```

Каждое совпадение классифицируй: исправлено, допустимо с объяснением или blocker.

После review исправь найденные дефекты и повтори тесты. Review без repair не закрывает
prompt.

---

# 19. Финальные acceptance criteria

## 19.1. Functional acceptance

- [ ] Catalog item без URL создаёт query target, а не sentinel.
- [ ] Query-only path проходит admission, idempotency, worker, raw persistence и replay.
- [ ] `Q`, `E`, `V`, `K` физически и семантически разделены.
- [ ] `V` никогда не заполняется без candidate evidence.
- [ ] Legacy rows маркируются `LEGACY_UNVERIFIED`.
- [ ] Exact and confirmed-cross cases различаются.
- [ ] UNKNOWN/CONFLICT/AMBIGUOUS fail closed.
- [ ] Calibration требует automatic eligible + PASS + verified identity.
- [ ] Calibration группирует по verified comparison identity.
- [ ] Empty result отличается от schema drift.
- [ ] Каждый raw offer имеет terminal outcome.
- [ ] Conservation law проверяется.
- [ ] Source confidence вычисляется одной versioned функцией.
- [ ] Неполный source не получает confidence `1`.

## 19.2. Test acceptance

- [ ] Unit variation matrix зелёная.
- [ ] PostgreSQL migration/constraint tests зелёные.
- [ ] Replay E2E зелёный и network-free.
- [ ] Full backend suite зелёный.
- [ ] Lint/typecheck/migration-head checks зелёные или честно BLOCKED с evidence.
- [ ] URL-seed regression зелёный.
- [ ] Concurrency/redelivery tests зелёные.

## 19.3. Production-safety acceptance

```text
G_P0 = G_query * G_identity * G_calibration * G_parser * G_outcomes * G_confidence
```

Где каждый gate бинарный и подтверждён E3/E4 evidence:

```text
G_P0 = 1 => STAGE_RESULT may be PASS
G_P0 = 0 => STAGE_RESULT must be FAIL or BLOCKED
```

`STAGE_RESULT=PASS` означает только закрытие этого P0 implementation stage. Оно НЕ
означает автоматически:

- разрешение live Prom source;
- representative accuracy на каталоге Юрия;
- approval brand tiers/cross links;
- automatic pricing activation;
- production deployment/recovery/load readiness.

---

# 20. Обязательные artifacts

ИИ-агент должен вернуть или сохранить:

```yaml
required_artifacts:
  - implementation_diff_or_changed_files_manifest
  - alembic_migration
  - data_contract_documentation
  - unit_variation_tests
  - postgresql_integration_tests
  - replay_e2e_evidence
  - calibration_exclusion_report
  - offer_outcome_accounting_report
  - hostile_self_review
  - command_evidence_with_exit_codes
  - final_section_15_16_response
```

Для каждой команды укажи:

```yaml
command_evidence:
  command: "..."
  cwd: "..."
  exit_code: 0
  result: PASS|FAIL|BLOCKED|SKIPPED
  summary: "..."
```

Не прикладывай гигантские logs вместо summary; сохрани полный log как artifact и укажи
путь/hash.

---

# 21. Формат финального отчёта агента

Финальный отчёт на русском языке:

1. **Итог:** что реализовано и какой stage gate.
2. **Изменённые файлы:** путь + назначение.
3. **Data contract:** итоговая семантика `Q/E/V/K`.
4. **Migration:** upgrade/backfill/constraints/rollback.
5. **Acquisition:** query-only и URL-seed compatibility.
6. **Evidence:** extractor/provenance/verification.
7. **Parser outcomes:** empty vs schema drift.
8. **Offer accounting:** conservation law и rejection taxonomy.
9. **Calibration:** predicate и exclusion counts.
10. **Confidence:** формула, version, factors.
11. **Tests:** команды, exit codes, counts, variation coverage.
12. **Hostile review:** найденные и исправленные дефекты.
13. **Оставшиеся ограничения:** только реальные, не замаскированные.
14. **Production readiness separation:** что этот PASS не доказывает.
15. **Section 15.1 footer + Section 16 machine-readable summary** по `AGENTS.md`.

Финальный machine-readable фрагмент дополнительно должен содержать:

```yaml
p0_identity_spine:
  query_only_supported: true|false
  sentinel_url_occurrences_runtime: 0
  identity_fields_separated: true|false
  legacy_rows_marked_unverified: true|false
  calibration_requires_automatic_eligible: true|false
  calibration_requires_hard_gate_pass: true|false
  calibration_requires_verified_oe: true|false
  empty_vs_schema_drift_distinguished: true|false
  offer_accounting_conservation_verified: true|false
  unconditional_source_confidence_one_occurrences: 0
  replay_network_requests: 0
  postgresql_migration_verified: true|false
  full_suite:
    passed: 0
    failed: 0
    skipped: 0
  remaining_blockers: []
```

---

# 22. Финальная инструкция

Начни с воспроизведения шести P0 на текущем коде. Затем реализуй изменения строго в
порядке зависимостей:

```text
query-only acquisition
-> identity schema migration
-> deterministic OE enrichment/provenance
-> parser outcome correction
-> typed offer accounting/source confidence
-> calibration hardening
-> replay/integration/variation tests
-> hostile self-review and repair
```

Не объявляй успех по количеству написанных тестов. Успех существует только тогда, когда
проверены инварианты, migration безопасна для legacy данных, replay детерминирован,
PostgreSQL constraints работают, а ни один поисковый OE не может быть ошибочно принят за
доказанный OE кандидата.

Если любой hard gate не доказан, верни `FAIL` или `BLOCKED` с точным blocker и следующим
конкретным действием. Не фальсифицируй `PASS`.

<!-- END PROMPT_15_017_VERIFIED_MARKET_IDENTITY_SPINE_P0_FIX -->
