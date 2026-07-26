# METIS Candidate Selection Enhancement — отчёт исполнения

**Stage:** `METIS_CANDIDATE_SELECTION_ENHANCEMENT_20260726`  
**Дата исполнения:** 2026-07-25/26  
**Контрольный запрос:** `7E5827505A`  
**Baseline run:** `aa621d41-646b-4875-bb0c-138423901a8a`  
**Первый полный run:** `d4919d0d-41f7-4d1b-ac7a-bee1f369314e`  
**Финальный run:** `16e1a598-d60a-4e07-ab3b-c74fe14ea372`

## 0. Итог

Пагинационный P0 устранён и подтверждён живым Prom:

- было: `29/90`, одна страница, coverage `0.322222`;
- стало: `90/90`, четыре страницы `29 + 29 + 29 + 3`, coverage `1.000000`;
- HTTP: `4/4` ответов `200`, по одной попытке;
- `unfetched_count: 61 → 0`;
- `coverage_reason: SEARCH_PAGE_LIMIT → FULL_REPORTED_RESULT_SET`.

Добавлена защита от повторяющихся страниц, дедупликация listing identity,
динамическая остановка после получения Prom `total` и настраиваемый hard-cap
`1..50`, default `10`.

Полный мастер-промпт не может быть закрыт как `PASS`: WP-2 требует
утверждённых владельцем и доказанных market-specific tier rules, WP-4 требует
не менее 30 подтверждённых COMPARABLE на category/tier (факт: `0`), WP-6
требует 200 слепых человеческих меток на стратифицированной выборке (факт:
`0` меток и только `131` уникальная пара query/listing), а WP-7 не
авторизован.

## 1. Гистограмма причин ДО

Run `aa621d41-646b-4875-bb0c-138423901a8a`, одна страница:

| Причина | Количество |
|---|---:|
| `DISMANTLER_SELLER` | 2 |
| `OEM_NOT_FOUND` | 1 |
| `TIER_UNKNOWN (REVIEW)` | 25 |
| `USED` | 1 |
| **Всего сохранено** | **29** |

Покрытие: `29/90 = 0.322222`; не загружено `61`;
`coverage_reason=SEARCH_PAGE_LIMIT`.

## 2. Гистограмма причин ПОСЛЕ

Run `16e1a598-d60a-4e07-ab3b-c74fe14ea372`, полный Prom result set:

| Причина | Количество |
|---|---:|
| `DISMANTLER_SELLER` | 5 |
| `OEM_NOT_FOUND` | 31 |
| `OWN_SELLER` | 1 |
| `TIER_UNKNOWN (REVIEW)` | 49 |
| `USED` | 1 |
| **Всего сохранено и классифицировано** | **87** |
| Rejected до gate chain | 3 |
| **Всего извлечено** | **90** |

Покрытие: `90/90 = 1.000000`; не загружено `0`;
`coverage_reason=FULL_REPORTED_RESULT_SET`.

Сравнение двух полных прогонов до/после добавления украинского dismantler
маркера:

| Метрика | До (`d4919d0d…`) | После (`16e1a598…`) | Дельта |
|---|---:|---:|---:|
| Сохранённых listing IDs | 87 | 87 | 0 |
| Различий в множестве listing IDs | 0 | 0 | 0 |
| `TIER_UNKNOWN` | 51 | 49 | -2 |
| `DISMANTLER_SELLER` | 3 | 5 | +2 |
| REVIEW | 51 | 49 | -2 |
| SKIP | 36 | 38 | +2 |

Ровно две карточки изменили verdict:

| Listing ID | До | После |
|---|---|---|
| `2277454073` | `TIER_UNKNOWN` | `DISMANTLER_SELLER` |
| `2277483292` | `TIER_UNKNOWN` | `DISMANTLER_SELLER` |

Обе принадлежат продавцу `Авторозбірка Мікроавтобусів`; причина была в
отсутствии украинского токена `розбірка`.

## 3. WP-1 — устранение пагинационного разрыва

До: `29/90`, `unfetched=61`, `search_pages=1`, coverage `0.322222`.  
После: `90/90`, `unfetched=0`, `search_pages=4`, coverage `1.000000`.  
Дельта: `+61` извлечённая карточка, `+0.677778` coverage.

Реальные страницы:

| Страница | Products | Новых unique | Prom total |
|---:|---:|---:|---:|
| 1 | 29 | 29 | 90 |
| 2 | 29 | 29 | 90 |
| 3 | 29 | 29 | 90 |
| 4 | 3 | 3 | 90 |

Команды воспроизведения:

```bash
cd backend
uv run pytest -q tests/test_prom_search_pagination.py tests/test_catalog_discovery.py

docker compose build api
docker compose up -d --no-deps api
docker compose exec -T api catalog-candidate-report \
  --run-id 16e1a598-d60a-4e07-ab3b-c74fe14ea372
```

Live-run выполнен прямым вызовом
`marko.services.catalog_discovery.collect_catalog_discovery()` внутри API
container с:

```text
workspace_id=4ba8055e-b448-4c19-b90b-27c1f1b78001
sku=7E5 827 505 A
title=VW Transporter T5 T6 03-замок дверної задньої кришки багажника на ляду 7E5827505A
current_price=1800.00 UAH
```

Файлы изменены:

- `backend/src/marko/core/config.py`;
- `backend/src/marko/parsers/prom/gateway.py`;
- `backend/src/marko/services/catalog_discovery.py`;
- `.env.example`;
- `compose.yaml`;
- `frontend/lib/features/catalog/widgets/catalog_competitor_section.dart`.

Тесты добавлены/изменены:

- `4` pagination cases;
- `5` coverage-reason cases;
- `3` hard-cap validation/default cases;
- `1` Flutter hard-cap UI case.

Вариации проверены:

- `total=90`, размеры страниц `29/29/32`;
- `total=None`;
- `total=0`;
- размер страницы меняется;
- Prom повторяет уже полученную страницу;
- hard-cap ниже объёма;
- upstream gap до hard-cap;
- границы hard-cap `0/51` отклоняются.

**WP-1 = PASS.**

## 4. WP-2 — tier dictionary

Архитектурная часть уже реализована до текущего документа:

- runtime получает tier rules из `backend/config/brands.yaml`;
- `load_approved_brand_rules()` активирует non-KEMP правило только при
  одновременном document-level и row-level approval;
- неутверждённые записи остаются `UNKNOWN`;
- KEMP остаётся единственным контрактным safe default.

Распределение оставшихся `49` `TIER_UNKNOWN`:

| Brand value | Количество |
|---|---:|
| `Detali IF` | 10 |
| `Polcar` | 9 |
| `<EMPTY>` | 7 |
| `Noname` | 6 |
| `NTY` | 3 |
| `No brand` | 3 |
| `Без бренду` | 3 |
| `Autotechteile` | 2 |
| `Volkswagen` | 2 |
| `No Name` | 1 |
| `VAG` | 1 |
| `VIKA` | 1 |
| `Аналог` | 1 |

До: `51/87 = 0.586207`.  
После безопасного словарного исправления dismantler: `49/87 = 0.563218`.  
Дельта: `-2` карточки; `-0.022989` абсолютной доли.

`21/49` записей по определению не имеют пригодного brand identity
(`<EMPTY>`, Noname, No brand, Без бренду, No Name, Аналог). Остальные нельзя
автоматически разнести по `OEM/OES/AFTERMARKET_A/AFTERMARKET_B/BUDGET` по
одной цене или названию. `backend/config/brands.yaml` остаётся
`domain_policy_approved: false`; агент не подставлял `approved_by` от имени
владельца.

Файлы изменены:

- `backend/config/comparability.yaml`;
- `backend/tests/test_candidate_selection.py`.

Вариации проверены: `розборка`, `розбірка`, `разборка`, mixed-script brand.

**WP-2 = BLOCKED_DATA_APPROVAL.** Нужна экспертная разметка и явное
утверждение non-KEMP tier rows владельцем продукта.

## 5. WP-3 — applicability

До: `APPLICABILITY_UNKNOWN=4/87=0.045977`.  
После: `4/87=0.045977`.  
Дельта: `0`.

Четыре случая вручную просмотрены по сохранённым title:

- один title содержит `VW T5/T6`, но не содержит однозначную модель;
- один содержит `Volkswagen Transporter`, но не содержит generation;
- два содержат `Volkswagen T5`, но не однозначную модель.

Добавление `T5 → Transporter` было отклонено: T5 также встречается у
Multivan/Caravelle и создало бы ложный model match. Текущий soft flag является
корректным fail-closed результатом, а не словарным пропуском.

Полноценный stop-gate WP-3 требует стратифицированный gold set WP-6; текущий
run представляет один OE и не позволяет доказать отсутствие ложных
`APPLICABILITY_MISMATCH` на других категориях.

**WP-3 = BLOCKED_REPRESENTATIVE_DATA.**

## 6. WP-5 — CrossLink

SQL по реальной PostgreSQL:

| validation_status | Количество |
|---|---:|
| `CONFIRMED` | 0 |
| `REVIEW` | 0 |
| `REJECTED` | 0 |
| `UNKNOWN` | 0 |
| **Всего** | **0** |

`confirmed_share` не равен нулю; он **не определён**, потому что знаменатель
равен нулю.

`persist_cross_links_for_run()` создаёт append-only snapshot из
`MarketObservation.description` и решений `run_cross_stages_ab()`.
`_confirmed_cross_oems()` корректно допускает только `CONFIRMED`. Ослабление
до любого статуса не выполнялось.

Рекомендация: отдельный WP нужен не для ослабления gate 5, а для наполнения
description evidence, запуска Stage A+B и операторского подтверждения спорных
пар. Пока таблица пуста, `CROSS_TABLE` не может увеличить coverage.

**WP-5 audit = PASS; CrossLink data readiness = BLOCKED_EMPTY_DATASET.**

## 7. WP-4 — price anomaly calibration

Условие запуска:

```text
N_comparable_confirmed >= 30 на category/tier
```

Факт по PostgreSQL:

| Category | Tier | N | Median premium | Новые thresholds |
|---|---|---:|---|---|
| все | все | 0 | не вычисляется | не вычисляются |

`category_tier_premiums` остаётся пустым, default premium остаётся
документированным нейтральным `1.0`. Произвольные коэффициенты не внесены.

**WP-4 = BLOCKED: N=0 < 30.**

## 8. WP-6 — gold set 200

Фактический доступный корпус:

| Метрика | Значение |
|---|---:|
| Completed discovery runs | 7 |
| Distinct queries | 3 |
| Persisted rows с повторами между runs | 247 |
| Distinct query/listing pairs | 131 |
| Human blind labels | 0 |
| Runs с непустой reference category | 1 |

Требуется `200` уникальных, стратифицированных по нескольким category/tier
пар, объявлений. Сейчас не хватает минимум `69` уникальных пар, но простое
добавление 69 карточек одной категории всё равно не выполнит требование
стратификации.

Confusion matrix не вычислялась: подстановка прогнозов алгоритма вместо
слепых `true_status` дала бы круговую и ложную оценку.

| true \ predicted | COMPARABLE | REVIEW | SKIP |
|---|---:|---:|---:|
| COMPARABLE | N/A | N/A | N/A |
| REVIEW | N/A | N/A | N/A |
| SKIP | N/A | N/A | N/A |

- `false_comparable_rate = NOT_MEASURED`;
- `false_skip_rate = NOT_MEASURED`;
- `review_overflow_rate = NOT_MEASURED`.

**WP-6 = BLOCKED: 131/200 unique, 0/200 blind labels, insufficient category
stratification.**

## 9. WP-7 — LLM triage

WP-7 не реализован и не авторизован:

- WP-6 не дал измеримой доли неформализуемых condition errors;
- владелец продукта не дал отдельную санкцию после confusion matrix;
- runtime остаётся полностью детерминированным, без LLM.

**WP-7 = NOT_AUTHORIZED.**

## 10. WP-8 — вариации и условная селективность

Все десять обязательных вариаций представлены явными assertions:

| # | Вариация | Результат |
|---:|---|---|
| 1 | mixed-script brand `КEМP` | `REVIEW/TIER_UNKNOWN`, fail-closed |
| 2 | `ё/і/ї/є` в разных позициях | нормализуются во всём тексте |
| 3 | used + new | `REVIEW/CONDITION_CONFLICT` |
| 4 | OE только в description | evidence `DESCRIPTION` |
| 5 | `max_oem_in_title + 1` | flag `OEM_STUFFED` |
| 6 | обе стороны side совпадают | не SKIP |
| 7 | side известна только с одной стороны | не SKIP |
| 8 | ratio ровно `0.35/3.0` | не anomaly (`<`/`>` строгие) |
| 9 | OE/article `None` | `SKIP/OEM_NOT_FOUND`, без exception |
| 10 | reference без generation | soft `APPLICABILITY_UNKNOWN`, не mismatch |

Условная селективность live run:

| Gate | Reached | Terminal | `s_i=terminal/reached` |
|---|---:|---:|---:|
| `own_seller` | 87 | 1 | 0.011494 |
| `dismantler_seller` | 86 | 5 | 0.058140 |
| `condition` | 81 | 1 | 0.012346 |
| `remanufactured` | 80 | 0 | 0.000000 |
| `oem_identity` | 80 | 31 | 0.387500 |
| `oem_stuffing` | 49 | 0 | 0.000000 |
| `variant` | 49 | 0 | 0.000000 |
| `package` | 49 | 0 | 0.000000 |
| `applicability` | 49 | 0 | 0.000000 |
| `tier` | 49 | 49 | 1.000000 |
| `price_anomaly` | 0 | 0 | не определено |

Порядок не менялся: `N=87 < 200`, выборка состоит из одного OE, а перенос
`tier` раньше identity gates сделал бы REVIEW для 31 карточки, которые
доказанно не содержат целевой OE. Это ухудшило бы диагностический reason.

## 11. Полный чек-лист проверки

| Проверка | Результат |
|---|---|
| Backend full pytest | `981 passed, 6 skipped in 4.43s` |
| Flutter full test | `54 passed` |
| Ruff full backend | PASS |
| Python compileall | PASS |
| Dart format | `60 files, 0 changed` |
| Flutter analyze, Unicode path | infrastructure failure: Dart LSP truncated JSON |
| Flutter analyze, fresh ASCII copy | `No issues found!` |
| Flutter release web build | PASS, Docker image built |
| `docker compose config -q` | PASS |
| Alembic check | `No new upgrade operations detected` |
| Alembic current | `20260725_0022 (head)` |
| API readiness | `{"status":"ok"}` |
| Frontend HTTP | `200 OK` |
| Docker services | `8/8 running healthy` |
| Live Prom coverage | `90/90`, 4 HTTP requests, 4×200 |

## 12. Изменённые файлы

| Файл | Было | Стало |
|---|---|---|
| `.env.example` | нет catalog hard-cap | документирован default `10` |
| `compose.yaml` | discovery cap не передавался | env hard-cap передаётся backend |
| `backend/src/marko/core/config.py` | нет отдельного discovery cap | bounded `1..50`, default `10` |
| `backend/src/marko/parsers/prom/gateway.py` | fixed page loop | unique dedupe, total stop, repeated-page stop |
| `backend/src/marko/services/catalog_discovery.py` | hardcoded `1` | per-run cap + точный coverage reason |
| `backend/config/comparability.yaml` | нет `розбірка` | украинский dismantler marker |
| `backend/src/metis/pricing/candidate_selection.py` | gate order не экспортировался | `CANDIDATE_GATE_ORDER` |
| `backend/src/marko/services/catalog_candidate_report.py` | histogram/coverage | conditional gate metrics, applicability, CrossLink counts |
| `frontend/.../catalog_competitor_section.dart` | только legacy page-limit | legacy + `SEARCH_PAGE_HARD_CAP` |
| `backend/tests/test_prom_search_pagination.py` | отсутствовал | pagination/repeat/unknown-total matrix |
| `backend/tests/test_catalog_discovery.py` | 3 contract tests | coverage + hard-cap variations |
| `backend/tests/test_candidate_selection.py` | базовые gates | обязательная десятистрочная variation matrix |
| `backend/tests/test_catalog_candidate_report.py` | histogram only | conditional denominator/CrossLink/applicability |
| `frontend/test/catalog_page_test.dart` | legacy UI fixture | hard-cap UI regression |

Миграция не требовалась: существующая schema уже хранит page limit, request
count, coverage, verdict details и flags.

## 13. Артефакт

Полный JSON финального live run:

`.artifacts/metis_candidate_selection_enhancement_20260726/live_run_7E5827505A.json`

## 14. Финальный stop-gate

- WP-1: `PASS`;
- WP-2: `BLOCKED_DATA_APPROVAL`;
- WP-3: `BLOCKED_REPRESENTATIVE_DATA`;
- WP-4: `BLOCKED_N_0`;
- WP-5 audit: `PASS`, data readiness `BLOCKED_EMPTY_DATASET`;
- WP-6: `BLOCKED_131_OF_200_AND_ZERO_LABELS`;
- WP-7: `NOT_AUTHORIZED`;
- WP-8 variation implementation: `PASS`; ordering decision deferred until
  representative `N>=200`.

Следовательно:

```text
STOP_GATE_METIS_CANDIDATE_SELECTION_ENHANCEMENT_20260726 = BLOCKED
```
