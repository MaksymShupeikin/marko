# 02 — ТЕКУЩАЯ АРХИТЕКТУРА И СКВОЗНОЙ ПОТОК ДАННЫХ

**Этапы:** PHASE 1 (картография) и PHASE 2 (end-to-end data flow)
**Дата:** 2026-08-01 · HEAD `f28a981`
**Основание:** чтение текущих файлов и исполнение кода. Где утверждение взято из
документа — помечено.

---

## 1. Сквозная цепочка

```text
XLSX каталога заказчика
  └─> catalog_import            services/catalog_import.py
        └─> PricingRun + по одному PricingRunItem на SKU
              └─> prepare_run_dispatch          market_collection.py:302
                    └─> process_pricing_item    market_collection.py:419
                          └─> _collect_comparison  market_collection.py:661
                                └─> PromGateway.compare   parsers/prom/gateway.py:207
                                      ├── есть страница кода детали?
                                      │     └─ ДА  -> _compare_via_oe_page  :267   source=PROM_OE_PAGE
                                      │     └─ НЕТ -> текстовый поиск       :242   source=SEARCH
                                      └─> build_comparison  services/matching.py:346
                                            ├─ match_offer               :136
                                            ├─ дешевейшее на продавца    :384
                                            └─ срез [:max_sellers]       :398
                          └─> _persist_payload_observations  :2037
                                └─> MarketObservation (иммутабельно) + candidate_snapshot
                                      └─> build_product_comparison_evidence  matching.py:403
                                            └─> evaluate_comparison_evidence  comparability.py:200
                                                  -> PASS | MANUAL_REVIEW | REJECT
              └─> барьер: собраны все SKU
                    └─> claim_collection_finalization        :2657
                    └─> calibrate_run_and_prepare_calculations :2770
                          ├─ _derive_calibration_pairs        :2917
                          └─ _calibration_quality             :3179
              └─> calculate_pricing_item                     :3200
                    └─> _calculate_and_persist               :3248
                          ├─ decide_raise                    metis/pricing/raise_policy.py:341
                          │    └─ _decide_budget_floor       :524
                          ├─ grade_confidence                :321
                          ├─ customer_budget_floor_trace     market_collection.py:164
                          └─ apply_comparability_activation_gate  :244
                                └─> Recommendation + иммутабельный calculation trace
                                      └─> UI Flutter -> ручное решение заказчика
```

Автоматической записи цены на Prom.ua в цепочке нет ни в одной ветви.

---

## 2. Получение кандидатов — фактическое, не архивное

§2.2 мастер-промпта прямо предупреждает не считать, что `compare()` всегда ищет
текстом. Проверено по коду: это так.

| Ветвь | Условие | Где | `source` | Потолок |
|---|---|---|---|---|
| страница кода детали | `motors.has_oe_page` | `gateway.py:226-229` | `PROM_OE_PAGE` | `max_search_pages=3` × 30 = 90 предложений |
| текстовый поиск | иначе | `gateway.py:230-258` | `SEARCH` | `max_search_pages=3` страниц поиска |
| сырое обнаружение | `search()` | `gateway.py:179-205` | — | не вызывает `build_comparison`, цену авторизовать не может |

Обе ветви затем проходят один `build_comparison` и один потолок
`max_sellers=10`.

### 2.1. Ветви из §2.2, которые нужно было проверить

| Ветвь по §2.2 | Есть? | Где |
|---|---|---|
| automotive vertical | да | `parse_motors_context`, `MotorsContext` |
| normalized product/OE code | да | `context.oe_page_url(lang)`, `/auto/oen/<id>-<alias>` |
| `iceComparison` или аналог | да | `gateway.py`, `matching.py`, `market_collection.py`, `scraper_contract.py`, `cli.py` |
| text search | да | `_collect_candidates` `gateway.py:342` |
| fallback search | да | текстовый поиск и есть fallback, когда страницы кода нет |
| related OE traversal | да | `via_oe_number`, `is_widened` в `MotorsContext` |
| cache/replay path | да | `recommendation_replay.py`, `scrape_journal.py`, replay contract v6 |
| motors-specific path | да | `services/prom_motors.py` — вторая, применяющая ворота копия обхода |
| seller exclusions | да | `excluded_seller_ids` `matching.py:343`, прокинуто в обе ветви |

**Намеренная дубликация.** Обход страницы кода существует дважды:
`gateway._collect_oe_candidates` (граница извлечения, ворота не импортирует) и
`services/prom_motors` (применяет ворота). Комментарий `gateway.py:324-327`
называет это осознанным решением, а не копипастой.

### 2.2. Provenance кандидата

`SourceProvenance` требует одновременно `source_type` ∈ `{prom, prom_public,
persisted_replay, official_feed, test_fixture}`, непустой `source_record_id`,
`raw_evidence_sha256` вида `^[0-9a-f]{64}$`, `parser_contract_version` и
`schema_version == "comparison-evidence-v3"` (`comparability.py:281-290`).
Отсутствие любого → `MANUAL_MISSING_SOURCE_PROVENANCE` и `MANUAL_REVIEW`.

Это соответствует требованию §2.2 о фиксации provenance. При построении
доказательства прямо из парсера (`matching.py:482-487`) provenance не
заполняется — она привязывается позже, в `bind_persisted_provenance`
(`comparability.py:480`), из иммутабельной записи.

---

## 3. Решение о сопоставимости: два независимых контура

### 3.1. Детерминированный контур — работает

13 размерностей (`comparability.py:29-43`), три состояния плюс
`NOT_APPLICABLE`. Семантика зафиксирована в самой политике
(`comparability.py:160-161`):

```text
unknown_semantics  = MANUAL_REVIEW
conflict_semantics = REJECT
```

Правило вычисления (`comparability.py:241-266`, решение `:311-326`):

| Ситуация | Результат |
|---|---|
| CONFLICT в любой неинформационной размерности | **REJECT** |
| CONFLICT в `IDENTITY_DIMENSIONS` (`oe_reference`) | REJECT с `REJECTED_IDENTITY_CONFLICT` |
| UNKNOWN в размерности из `hard_required` | MANUAL_REVIEW |
| UNKNOWN в `conditional` | проходит молча |
| `brand_manufacturer` | пропускается целиком — единственная информационная |
| всё сошлось + provenance + seller + валюта | PASS, `ELIGIBLE_VERIFIED` |

Пропуск бренда корректно реализует §2.5: уровень бренда не определяет цену.

### 3.2. LLM-контур — реализован, но ни разу не работал

`PRICING_LLM_COMPARABILITY_MODE` ∈ `off | shadow | required`, по умолчанию
`off` (`core/config.py:88`). В `shadow`/`required` обязательны
`PRICING_LLM_API_KEY` и `PRICING_LLM_MODEL` (`core/config.py:215-221`); ключ
пуст. Модель по умолчанию `gpt-5-mini`.

Существенное для науки: **финализатор run имеет отдельный барьер** и не
начинает калибровку, пока для каждого кандидата в `classified`-позиции не
сохранён результат проверки либо fail-closed результат ошибки
(`docs/LLM_COMPARABILITY_2026-07-31.md:66-72` — утверждение документа,
исполнением не проверялось).

Отказ, timeout, некорректная схема → `INSUFFICIENT_DATA`, кандидат к расчёту не
допускается. Marketplace-текст объявлен недоверенным, system instructions
запрещают исполнять команды из карточки.

### 3.3. Два словаря не заведены

HANDOFF §«Чего не делать» фиксирует, что параллельный словарь сопоставимости
был написан и удалён. Канонические:

```text
COMPARABLE | NOT_COMPARABLE | INSUFFICIENT_DATA
EXACT | ACCEPTABLE_ANALOGUE | SUSPICIOUS | NOT_APPLICABLE
```

---

## 4. Ценовое решение

### 4.1. Нормативная политика

`backend/config/raise_policy.yaml`, `active_strategy: budget_floor`:

| Параметр | Значение | Строка |
|---|---|---|
| `target_quantile` | `0` | :25 |
| `psychological_step` | `1` UAH | :28 |
| `minimum_discount` | `0.02` | :29 |
| `maximum_discount` | `0.05` | :30 |
| `target_floor_ratio` | `0` — выключено | :43 |
| `floor_corroboration_sellers` | `1` — буквальный минимум | :47 |
| `tier_agnostic` | `true` | :48 |
| `ignore_stock_status` | `true` | :50 |
| `ignore_cost_floor` | `true` | :51 |
| `owner_decision_reference` | `customer-reply-2026-07-30` | :52 |
| `min_evidence` | `3` | :56 |

Полоса цели: `market_floor × (1 − maximum_discount)` … `market_floor × (1 −
minimum_discount)` (`raise_policy.py:636-637`).

Соответствие §2.6 бизнес-контракта — полное: закупка, возраст остатка и уровень
бренда в формулу не входят, и это обеспечено флагами `ignore_*` и
`tier_agnostic`, а не соглашением.

### 4.2. Признание breakdown point в самом коде

`raise_policy.py:531-536` прямо говорит: у минимума breakdown point равен нулю,
одно предложение, которое не может быть настоящей ценой, становится
рекомендацией целиком. Названы две причины — числовая коллизия и цена-заглушка —
и сказано, что вторая недостижима для улучшений сопоставления.

Защиты реализованы, но **выключены по решению владельца**:

- `target_floor_ratio = 0`: кандидат `0.35` измерен на 292 позициях (сырой
  минимум — 193 понижения, из них 109 глубже −50 %; кандидат — 167 понижений,
  55 глубоких, на 19 поднятий больше), но это измерение, а не решение
  (`raise_policy.yaml:35-43`);
- `floor_corroboration_sellers = 1`: воспроизводит буквальный минимум.

При этом факт «стоит ли за минимумом второй продавец» **измеряется всегда** и
выдаётся флагом `FLOOR_RESTS_ON_ONE_SELLER` (`raise_policy.py:621-635`). Это
методологически правильное разделение: измеряем всегда, действуем только по
решению владельца.

### 4.3. Активационные ворота: advisory-only обеспечен кодом

`apply_comparability_activation_gate` (`market_collection.py:244-271`): если
`activation_verified` ложно, любой `automatic_eligible` результат превращается в

```text
action           = MANUAL_REVIEW
recommended_price = None
automatic_eligible = False
confidence_grade  = "MANUAL"
reasons          += COMPARABILITY_AUTOMATIC_ACTIVATION_BLOCKED, MANUAL_REVIEW_REQUIRED
```

`activation_verified` требует одновременно
`pricing_comparability_v1_automatic_enabled`,
`pricing_comparability_activation_artifact` и
`pricing_comparability_activation_sha256` (`core/config.py:85-87, 290-293`;
`market_collection.py:3351-3355`). В поставке первое `False`, два других пусты.

**Следствие для оценки рисков:** сегодня система не может выдать автоматическую
цену даже при ошибке в сопоставимости — она выдаст advisory. Это лучшее
свойство текущей архитектуры, и оно проверяется одинаково в расчёте и в replay.

---

## 5. Воспроизводимость и аудит

| Механизм | Где | Назначение |
|---|---|---|
| `MarketObservation` | иммутабельная таблица | сырое наблюдение рынка |
| `candidate_snapshot` | вместе с наблюдением | карточка кандидата на момент решения |
| `raw_evidence_sha256` | `SourceProvenance` | хэш сырого доказательства |
| calculation trace | иммутабельно | почему получилась именно эта цена |
| decision fingerprint v3 | `services/decision_fingerprint.py` | идентичность решения |
| replay contract v6 | `services/recommendation_replay.py` | воспроизведение старой рекомендации |
| append-only review/feedback | миграция `20260731_0031` | человеческая разметка не переписывает машинную |
| `COMPARABILITY_POLICY_HASH` | `comparability.py:165-167` | sha256 от payload политики |

**Замеченное следствие хэша политики.** `policy_valid` требует совпадения
`policy_id` и `policy_hash` (`comparability.py:226-233`). Любое изменение
состава размерностей, правил категорий или семантики массово инвалидирует
сохранённые доказательства — они станут `MANUAL_POLICY_NOT_APPROVED` и уйдут в
`MANUAL_REVIEW`. Это верное fail-closed поведение, но означает, что изменение
политики — не локальная правка, а событие масштаба run. Любой эксперимент,
меняющий размерности, обязан это учитывать.

---

## 6. Границы модулей

| Модуль | Владеет | Не владеет |
|---|---|---|
| `parsers/prom` | URL, HTTP, Apollo cache Prom | ценовые ворота — импортировать их запрещено (`gateway.py:324-327`) |
| `services/matching` | ретривал, свёртка, построение доказательств | решение о сопоставимости |
| `metis/pricing/comparability` | политика ворот | ретривал |
| `metis/pricing/raise_policy` | ценовое решение | нормализация цен — приходят уже приведёнными (`raise_policy.py:351-352`) |
| `services/market_collection` | оркестрация, персистентность, барьеры | владелец — другая сессия, править нельзя |
| `marko/pricing` | только compatibility facade | реализацию (`docs/architecture.md:30-32`, из документа) |

---

## 7. Где поток теряет информацию

Собрано из PHASE 0 §7, здесь — как места в цепочке.

| Место | Что теряется | Строка |
|---|---|---|
| `_collect_oe_candidates` | `page.total` известен и отбрасывается; забирается ≤ 90 из листинга в порядке marketplace | `gateway.py:335-340` |
| `build_comparison` | всё, кроме 10 дешевейших продавцов | `matching.py:398` |
| `build_product_comparison_evidence` | утверждение источника об идентичности не попадает в `oe_reference` | `matching.py:417-424` |
| то же | `part_type` жёстко UNKNOWN | `matching.py:435-438` |
| `categorical_dimension` | всякая разница написания = CONFLICT | `comparability.py:589-608` |
| `_year_dimension` | любой None из четырёх → UNKNOWN | `matching.py:532-534` |
| `grade_confidence` | зависимость наблюдений не отличается от их согласия | `raise_policy.py:276, 321-338` |

---

## 8. Что в этих фазах не проверено

- `market_collection.py` прочитан выборочно (ключевые функции), не все 4 372 строки.
- Барьер финализатора LLM описан по документу, исполнением не проверялся.
- Утверждение о `marko.pricing` как о чистом фасаде взято из `docs/architecture.md`.
- Схема БД не инвентаризирована по таблицам — только по точкам использования.
- Фронтенд-маршруты и экраны не картографированы; для научной программы это не
  на критическом пути, но в Repository gate §19 это отдельный пункт.
