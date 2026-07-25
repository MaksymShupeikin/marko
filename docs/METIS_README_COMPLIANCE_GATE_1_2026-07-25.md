# Metis — Фаза 1: матрица соответствия README

**Дата среза:** 2026-07-25  
**Ветка / HEAD:** `leonid/pricing-engine` / `ccaa0be`  
**Объект аудита:** текущее рабочее дерево, а не только `HEAD`  
**Режим:** read-only audit; сетевые запросы к Prom.ua не выполнялись  
**Результат фазы:** `PASS` — матрица построена; это не означает соответствие README или production readiness

## 1. Метод и границы доказательства

README разложен на 64 атомарных требования. Для каждого проверены:

- фактическое тело реализации;
- фактические `assert` релевантных тестов;
- класс фикстуры: real / synthetic / отсутствует;
- наличие сохранённого live-артефакта, подтверждающего именно требуемое поведение.

Статус `IMPLEMENTED_VERIFIED` не присваивался только по зелёному тесту или
наличию live CSV. Для него одновременно требуются код, тест на реальной
фикстуре и связанный live evidence. Текущая кодовая база не даёт такого полного
набора ни для одного из 64 требований README.

Сокращения evidence:

| Сокращение | Артефакт | Ограничение |
|---|---|---|
| `LIVE30` | `.artifacts/metis_next_steps_20260719/METIS_30_OE_LIVE_SUMMARY.json` | 30 SKU, не стратифицированы по продажам; старше части текущего кода |
| `CROSS_AB` | `.artifacts/metis_cross_coverage_20260719/METIS_CROSS_COVERAGE_SUMMARY.json` | replay/discovery-only; precision не размечена |
| `SMOKE6` | `.artifacts/metis_parser_product_smoke_20260725/METIS_PRODUCT_PARSER_SMOKE_SUMMARY.json` | свежие 6 запросов; pricing eligibility не проверялась |
| `REAL_NATURE` | `backend/tests/fixtures/catalog_number_nature_real_*` | реальные строки/offer rows, но проверяют только природу каталожного номера |

## 2. Полная матрица

| ID | Требование README | Статус | Code | Test / fixture | Evidence |
|---|---|---|---|---|---|
| R-01 | OE нормализуется детерминированно; raw и norm сохраняются | IMPLEMENTED_UNVERIFIED | `comparability.py:561`; `models.py:809` | `test_yuri_v1_contract.py:201`, synthetic | `SMOKE6` показывает query norm, но не полный persist path |
| R-02 | Fuzzy matching OE запрещён | IMPLEMENTED_UNVERIFIED | `matching.py:141`; `offer_identity.py:325` | `test_offer_identity.py:87`, synthetic | `SMOKE6`: два SKU-collision не верифицированы |
| R-03 | Сравнение части OE запрещено | IMPLEMENTED_UNVERIFIED | `matching.py:141`; `comparability.py:561` | `test_offer_identity.py:87`, synthetic | `NONE` |
| R-04 | Leading zero не удаляется | IMPLEMENTED_UNVERIFIED | `comparability.py:561`; `xlsx_catalog.py:1` | `test_fitment_intelligence.py:131`; `test_xlsx_catalog.py:317`, synthetic | `LIVE30` содержит `0001108121`, но не доказывает весь pipeline |
| R-05 | Похожее название не доказывает совместимость | IMPLEMENTED_UNVERIFIED | `offer_identity.py:133`; `comparability.py:223` | `test_offer_identity.py:40`; `test_comparability_contract.py:383`, synthetic | `SMOKE6`: title/SKU discovery остаётся review |
| R-06 | В основной расчёт допускается только exact OE | PARTIAL | `comparability.py:223`; `engine.py:626`; `offer_identity.py:101` | `test_comparability_contract.py:383`; `test_offer_identity.py:101`, synthetic | `CROSS_AB` discovery-only; код также допускает verified cross identity |
| R-07 | Допускается только condition=new | IMPLEMENTED_UNVERIFIED | `comparability.py:64,73,87`; `engine.py:602` | `test_yuri_v1_contract.py:318,341`, synthetic | `LIVE30`: UNKNOWN condition удерживался вне automatic cohort |
| R-08 | seller_relation=own исключается | IMPLEMENTED_UNVERIFIED | `market_collection.py:2062`; `engine.py:161` | `test_pricing_engine.py:156`; `test_catalog_competitors.py:62`, synthetic | `LIVE30` использовал configured owned seller IDs, но не текущий E2E |
| R-09 | seller_relation=related исключается | PARTIAL | `metis/fitment/engine.py:728`; core pricing relation не читает | `test_fitment_evaluation_dataset.py`, synthetic/non-representative | `NONE` |
| R-10 | possibly_related идёт на ручную проверку | PARTIAL | `metis/fitment/hitl.py:379`; `metis/fitment/engine.py:731` | `test_fitment_hitl_math.py:94`, synthetic; нет pricing integration assert | `NONE` |
| R-11 | unknown seller учитывается осторожно/review | PARTIAL | `metis/fitment/engine.py:731`; pricing использует лишь `is_owned` | `test_fitment_hitl_math.py:94`, synthetic | `NONE` |
| R-12 | Цена должна быть валидной | IMPLEMENTED_UNVERIFIED | `offer_processing.py:249`; `engine.py:602` | `test_offer_processing_outcomes.py:75`, synthetic | `SMOKE6`: 3/158 rows получили `REJECTED_INVALID_PRICE` |
| R-13 | Количество нормализовано до цены за штуку | PARTIAL | `metis/fitment/hitl.py:152`; `comparability.py:64`; для shock absorber quantity не hard gate | `test_fitment_hitl_math.py:118`, synthetic | `SMOKE6`: package/unit не извлечены |
| R-14 | Tier кандидата доказан и сопоставим | PARTIAL | `tiering.py:95`; `engine.py:255` | `test_tiering.py:80`; `test_yuri_v1_contract.py:689`, synthetic | `LIVE30`: automatic eligible `0/146`; approved brand `1/51` |
| R-15 | n=0 → insufficient_data | IMPLEMENTED_UNVERIFIED | `engine.py:316` | `test_pricing_engine.py:132`, synthetic boundary `<3` | `LIVE30`: 7/30 имели zero after filter |
| R-16 | n=1 → single reference + manual review | CONTRADICTED | `engine.py:316` возвращает `INSUFFICIENT_DATA` для всего n<3 | `test_pricing_engine.py:132` закрепляет объединённое поведение | `NONE` |
| R-17 | n=2 → low-confidence recommendation | CONTRADICTED | `engine.py:316` | `test_pricing_engine.py:132` прямо ожидает `INSUFFICIENT_DATA` | `NONE` |
| R-18 | n≥3 → normal recommendation | CONTRADICTED | `types.py:336`; `engine.py:460,518` требуют 5 | `test_pricing_engine.py:139`; `test_pricing_engine_matrix.py:219` ожидают review для 3/4 | `NONE` |
| R-19 | target=lower reference×(1-buffer) | CONTRADICTED | `engine.py:924` использует `min(fair×discount, current×cap, lower_bound)` | `test_pricing_engine.py:116`, synthetic | `NONE` |
| R-20 | Настраиваемый deadband 3–5% | IMPLEMENTED_UNVERIFIED | `types.py:365,366,369`; `engine.py:924` | `test_pricing_engine.py:116,124`, synthetic | `NONE` |
| R-21 | Stale отмечает клиент вручную | IMPLEMENTED_UNVERIFIED | `schemas/pricing.py:144`; `catalog_context_dialog.dart:145` | `test_pricing_api.py:114`; Flutter dialog tests, synthetic | `NONE` |
| R-22 | Нет cost → margin unknown + manual review | CONTRADICTED | `engine.py:957`; отсутствие cost не блокирует clearance | `test_yuri_v1_contract.py:617` прямо требует actionability без cost | `NONE`; client workbook raw cost columns = 0 |
| R-23 | Cost не попадает в API/logs/analytics/LLM/dev | CONTRADICTED | raw API input `schemas/pricing.py:145`; decrypt `pricing_runs.py:1391`; encrypted DB `models.py:918`; legacy plaintext fields `models.py:836,891,2069` | `test_cost_encryption.py`; `test_yuri_v1_contract.py:458,495,646`, synthetic | реального client cost нет |
| R-24 | Margin/loss считается на устройстве | CONTRADICTED | frontend отправляет cost; server decrypts and checks at `pricing_runs.py:1391` | `pricing_encrypted_cost_dialog_test.dart` ожидает отправку `cost` | `NONE` |
| R-25 | Доступны все 9 HITL-действий | PARTIAL | pricing: `schemas/pricing.py:283`; fitment: `schemas/fitment.py:256`; seller endpoints `fitment.py:650,670` | backend/frontend tests synthetic; defer не показан pricing UI | `NONE` |
| R-26 | Каждое решение сохраняется как feedback | PARTIAL | `models.py:2040,2482,2802`; `pricing_runs.py:1358` | `pricing_api_test.dart:43`; Postgres fitment tests skipped by default | `NONE` |
| R-27 | Цена не меняется без подтверждения человека | IMPLEMENTED_UNVERIFIED | `pricing_runs.py:1358` только пишет decision; UI явно предупреждает `recommendation_decision_dialog.dart:140` | `pricing_api_test.dart:43`, synthetic | нет production writeback evidence |
| R-28 | Причина включения/исключения каждого offer видима | PARTIAL | excluded reason `engine.py:163`; target effect/API `pricing.py:621`; UI `recommendations_page.dart:919` | `pricing_models_test.dart:113`, synthetic | `LIVE30` содержит reason codes, но включение не всегда имеет отдельную human reason |
| R-29 | Ссылки конкурентов сохраняются | IMPLEMENTED_UNVERIFIED | `types.py:219`; API `pricing.py:572`; UI `recommendations_page.dart:865` | `test_yuri_v1_contract.py:521`, synthetic URL | `SMOKE6`: реальные URLs сохранены и replay-identical |
| R-30 | OE/цены/продавцы/tiers/relations не выдумываются | PARTIAL | `offer_identity.py:133`; `offer_processing.py:320`; tier fail-closed `tiering.py:151` | identity/tiering tests synthetic | `SMOKE6`: collisions abstain; relation path не сквозной |
| R-31 | Нормализация/фильтры/математика детерминированы | IMPLEMENTED_UNVERIFIED | pure code in `comparability.py`, `statistics.py`, `engine.py` | focused deterministic tests synthetic | `SMOKE6` replay 6/6 byte-equivalent structured outputs |
| R-32 | “Цей товар…” не является рынком конкурентов | IMPLEMENTED_UNVERIFIED | main acquisition uses `SearchListingQuery` in `parser.py:15,126`; product page читается только как seed | `test_prom_search_boundary.py:22`, synthetic | `NONE`; отдельный block-name regression test отсутствует |
| R-33 | Все магазины заказчика вне market statistics | IMPLEMENTED_UNVERIFIED | workspace owned IDs `market_collection.py:1331,2062`; `engine.py:161` | own-seller tests synthetic | `LIVE30` policy had only owned seller id `2847093`, не все 4 stores |
| R-34 | Без exact OE выставляется literal not_in_scope status | MISSING | literal status отсутствует; фактически используется `MANUAL_REVIEW`/OE UNKNOWN | `rg` по source/tests: 0 occurrences | `SMOKE6`: safe abstention, но другого кода статуса |
| R-35 | Out-of-scope модули не реализуются без согласования | PARTIAL | имеются отдельно запрошенные пользователем `fitment_intelligence.py`, `metis/fitment/*`, `cross_links.py`; README не обновлён | сотни synthetic fitment/cross tests | `CROSS_AB`; это подтверждённый scope drift, а не доказательство отсутствия разрешения |
| R-36 | Один seller group даёт один голос | IMPLEMENTED_UNVERIFIED | `engine.py:308`; `_deduplicate_sellers` | `test_pricing_engine.py:156`; `test_comparability_contract.py:267`, synthetic | `CROSS_AB` считает seller groups, но не linked fixture |
| R-37 | independent seller учитывается | PARTIAL | pricing трактует verified non-owned seller как eligible; relation enum не связан с pricing | fitment dataset synthetic | `NONE` |
| R-38 | Tier taxonomy: original/recognized/generic/unknown | PARTIAL | фактический enum имеет 8 tier: `types.py:16` | `test_tiering.py`, synthetic | `LIVE30`: 51 token, 50 unapproved |
| R-39 | Сравнение преимущественно same/comparable tier | IMPLEMENTED_UNVERIFIED | validated tier coefficients `engine.py:255`; KEMP lane separated `engine.py:205` | `test_pricing_engine.py:100,166`, synthetic | `LIVE30`: ни одной automatic recommendation |
| R-40 | Ходовой товар может получить RAISE | IMPLEMENTED_UNVERIFIED | `engine.py:916` | `test_pricing_engine.py:116`, synthetic | `NONE` |
| R-41 | Залежалый товар может снижаться к рынку | IMPLEMENTED_UNVERIFIED | `engine.py:957` | `test_pricing_engine.py:235`; `test_yuri_v1_contract.py:542`, synthetic | `NONE` |
| R-42 | Снижение учитывает разрешённый убыток | IMPLEMENTED_UNVERIFIED | decision guard `pricing_runs.py:131`; API flags `schemas/pricing.py:160` | `test_pricing_api.py:149,171`, synthetic | `NONE` |
| R-43 | Рекомендация понятна и содержит evidence links | IMPLEMENTED_UNVERIFIED | `RecommendationResponse`; evidence endpoint/UI | `pricing_models_test.dart`; `pricing_api_test.dart`, synthetic | `SMOKE6` доказывает links только на parser boundary |
| R-44 | Финальное решение остаётся человеку | IMPLEMENTED_UNVERIFIED | decision API/UI; нет Prom writeback client | decision dialog/API tests synthetic | `NONE` |
| R-45 | Different-OE/cross matching не автоматизируется в MVP | CONTRADICTED | `ConfirmedCross`/`VERIFIED_CROSS` в `offer_identity.py:101`; `via_cross` persist path | `test_offer_identity.py:101`; cross tests synthetic | `CROSS_AB` пока discovery-only, но кодовая возможность существует |
| R-46 | Дубли карточек не считаются независимыми | IMPLEMENTED_UNVERIFIED | gateway product dedupe `gateway.py:46`; pricing seller dedupe `engine.py:308` | `test_prom_gateway_boundary.py:7`; `test_pricing_engine.py:156` | `NONE` |
| R-47 | Left/right mismatch исключается | IMPLEMENTED_UNVERIFIED | `matching.py:78,95`; comparability side gate | `test_matching.py:54,124`; comparability tests synthetic | `SMOKE6` не enriched по side |
| R-48 | Front/rear position mismatch исключается | IMPLEMENTED_UNVERIFIED | `matching.py:82`; comparability position gate | `test_matching.py:58`; `test_comparability_contract.py:135` | `SMOKE6` не enriched по position |
| R-49 | Original и budget не смешиваются “в лоб” | IMPLEMENTED_UNVERIFIED | unvalidated coefficient excluded `engine.py:255`; divide by multiplier `engine.py:274` | `test_pricing_engine.py:100,166`; `test_yuri_v1_contract.py:689` | approved tier data отсутствуют |
| R-50 | Used offers исключаются | IMPLEMENTED_UNVERIFIED | `engine.py:172,602`; condition classifier | `test_yuri_v1_contract.py:318`, synthetic | `SMOKE6`: used marker виден, search card condition остаётся null |
| R-51 | Комплект не смешивается с ценой за штуку | PARTIAL | fitment unit normalizer есть; pricing hard gate не универсален | `test_fitment_hitl_math.py:118`, synthetic | package/unit отсутствуют в `SMOKE6` |
| R-52 | Ошибочный OE не допускается | IMPLEMENTED_UNVERIFIED | identity conflict `offer_identity.py:362`; comparability reject `comparability.py:293` | `test_offer_identity.py:87`; `test_yuri_v1_contract.py:178` | `SMOKE6`: 2 obvious collisions не verified |
| R-53 | В 30-SKU замере измерены raw offers | PARTIAL | разовый workbook script/artifact, не продуктовый metric path | no linked real pytest | `LIVE30`: 1296 candidates, 146 retrieved |
| R-54 | В 30-SKU замере измерены exact OE | CONTRADICTED | artifact definition считает candidate SKU равным доказанному OE | no linked real pytest | `LIVE30`: 91 “exact”; `SMOKE6`: 2/6 запросов дали obvious cross-product SKU collisions |
| R-55 | Измерены own seller offers | MISSING | итоговый summary не содержит отдельного own count | no test | `LIVE30`: только configured id/policy, без отдельной метрики |
| R-56 | Измерены independent new offers | PARTIAL | `after_used_kemp_filter` удерживает UNKNOWN condition | no linked real pytest | `LIVE30`: 76, но summary прямо говорит “not proven new” |
| R-57 | Измерены same-tier offers | MISSING | approved tier classification отсутствует | tier tests synthetic | `LIVE30`: approved 1/51; production-valid count отсутствует |
| R-58 | Доли SKU с 0/1/2/3+ измерены раздельно | PARTIAL | artifact агрегирует `1 or 2`, `3 or 4`, `5+` | no linked real pytest | `LIVE30`: 7 zero; 13 one-or-two; 6 three-or-four; 4 five-plus |
| R-59 | Измерена доля manual_review_required | PARTIAL | automatic eligible посчитан, отдельный manual-review denominator не зафиксирован | no linked real pytest | `LIVE30`: automatic `0/146`, но это не полный status accounting |
| R-60 | 30 SKU стратифицированы 10 fast/10 normal/10 stale | CONTRADICTED | selection — 5 product families × 6, SHA order | no sales-strata test | `METIS_30_OE_SAMPLE.json`: нет sales velocity strata |
| R-61 | Факт/предположение/неопределённость разделены | PARTIAL | typed states есть в fitment (`StatementStatus`), pricing reasons частичны | fitment tests synthetic | live reports отделяют limitations, но UI не везде |
| R-62 | LLM используется для text extraction/classification | MISSING | runtime LLM provider/call отсутствует | no test | `NONE` |
| R-63 | Future R&D не превращается в current MVP commitment | CONTRADICTED | fitment/cross подсистемы уже добавлены в product repo | synthetic fitment/cross suites | `CROSS_AB`; README не обновлён под новый scope |
| R-64 | Финансово значимые price changes приоритизируются | IMPLEMENTED_UNVERIFIED | absolute sort `pricing_runs.py:1209`; priority score `engine.py:1075` | `test_pricing_api.py:139`; `test_yuri_v1_contract.py:634` | `NONE` |

## 3. Сводка статусов

| Статус | Кол-во | Доля |
|---|---:|---:|
| IMPLEMENTED_VERIFIED | 0 | 0.00% |
| IMPLEMENTED_UNVERIFIED | 30 | 46.88% |
| PARTIAL | 19 | 29.69% |
| MISSING | 4 | 6.25% |
| CONTRADICTED | 11 | 17.19% |
| **Итого** | **64** | **100.00%** |

`IMPLEMENTED_VERIFIED = 0` не означает, что кода нет. Это означает, что ни одно
требование не имеет одновременно current code + проверяющий именно это assert
на representative real fixture + связанный live evidence.

## 4. CONTRADICTED и MISSING: влияние

| ID | Дефект | Влияние на рекомендацию |
|---|---|---|
| R-16 | n=1 объединён с n<3 | Цена не выдаётся; покрытие ниже README; завышения/занижения нет |
| R-17 | n=2 → insufficient вместо low-confidence | Цена не выдаётся; покрытие ниже README |
| R-18 | normal action требует 5, не 3 | Для n=3–4 действие подавляется; безопаснее, но расходится с продуктовым контрактом |
| R-19 | Другая target formula | Цена меняется; направление не фиксировано: lower-bound branch может дать выше README buffer target, max-step branch — ниже |
| R-22 | Missing cost не вызывает review | Разрешает LOWER без серверной проверки маржи; повышает риск фактического убытка относительно README abstention |
| R-23 | Raw cost может пройти API/server | Рыночный target напрямую не меняет; создаёт confidentiality/legal risk и позволяет server-side below-cost gating |
| R-24 | Margin считается сервером, не только клиентом | Цена рынка не меняется; меняется доверительная граница и доступность decision |
| R-45 | Verified cross может стать automatic identity | Может изменить fair price в обе стороны; сейчас live cross artifact корректно discovery-only |
| R-54 | Candidate SKU считался exact OE | Завышает measured exact-match coverage; при допуске без нового identity gate могло бы смешивать цены разных товаров |
| R-60 | 30 SKU не sales-stratified | Не меняет отдельную цену; смещает оценку coverage по 4901, направление смещения неизвестно |
| R-63 | Future R&D уже в MVP repo | Непосредственного ценового эффекта без activation нет; увеличивает surface area и doc drift |
| R-34 | Нет literal not-in-scope status | Сейчас fail-closed; цена не завышается, но operator reason не соответствует README |
| R-55 | Нет own-offer count | Нельзя количественно проверить own-store leakage; возможное ценовое смещение не определено |
| R-57 | Нет production-valid same-tier metric | Нельзя оценить usable tier coverage; направление ценового смещения не определено |
| R-62 | Нет LLM extraction/classification | Снижает extraction coverage; fail-closed поведение подавляет рекомендации, а не повышает цену |

## 5. Отдельный аудит R-23 — себестоимость

| Путь утечки | Факт | Статус относительно README |
|---|---|---|
| API request | `CatalogItemOverrideRequest.cost` принимает raw Decimal в encrypted-server mode | CONTRADICTED |
| API response | raw cost удаляется; возвращаются `cost_configured` и privacy mode | PASS на response boundary |
| Validation error | input/context вырезаются глобальным handler | PASS для проверенного 422 path |
| DB | новый path хранит AES-256-GCM ciphertext; legacy plaintext columns остаются в schema | PARTIAL |
| Server computation | worker и decision service расшифровывают cost | CONTRADICTED |
| Logs/analytics | прямого raw-cost logging не найдено; события содержат derived flags/mode | PASS статического поиска |
| ORM SQL logging | `create_async_engine(..., pool_pre_ping=True)`, `echo` не включён | PASS текущего config |
| Test fixtures | только synthetic canary values; реальных закупочных цен нет | NO CLIENT DATA |
| XLSX/output | client workbook metrics: `raw_cost_columns_present=[]` | NO CLIENT DATA |
| LLM prompts | runtime LLM вызовы отсутствуют | PASS by absence |
| Developer access | server-side mode и key-bearing runtime не гарантируют “developer cannot see” | CONTRADICTED |

Фактический `.env` не задаёт `COST_PRIVACY_MODE`; действует default
`UNDECIDED`, поэтому raw cost сейчас fail-closed. Одновременно весь
encrypted-server implementation остаётся мёртвым для текущего клиента:
в подтверждённом workbook нет raw cost columns, а заказчик закупочные цены не
передаёт.

## 6. Проверка

Выполнено без сети:

```text
Backend focused audit suite:
277 passed in 1.93s

Flutter pricing/HITL suite:
14 passed
```

Прочитанные asserts подтверждают четыре документ-код расхождения напрямую:

1. `n=2 → INSUFFICIENT_DATA`;
2. `n=3 → MANUAL_REVIEW`;
3. `n=4 → MANUAL_REVIEW`;
4. missing cost не блокирует clearance recommendation.

## 7. Состязательная самопроверка

- 64 = 0 + 30 + 19 + 4 + 11; доли повторно пересчитаны из абсолютных чисел.
- Live claims не повышены до representative: `LIVE30`, `CROSS_AB` и `SMOKE6`
  имеют разные задачи и не взаимозаменяются.
- Отсутствие LLM и Prom writeback проверено статическим поиском, но отсутствие
  runtime side-effect не объявлено production-доказательством.
- `R-19` не получил выдуманного направления: фактическая `min(...)` формула
  может отклоняться от README в обе стороны в зависимости от active branch.
- Исходный код, тесты и конфиги не изменялись; в product tree добавлен только
  этот отчёт. Обязательные Section 15.1/16 validation manifests сохранены
  отдельно в gitignored `.artifacts/`.
- Сетевых запросов к Prom.ua не выполнялось.

## ГЕЙТ 1

Фаза 1 завершена: 64/64 требования получили статус. Матрица выявила
11 прямых противоречий и 4 отсутствующих требования. Фаза 2
(математический аудит ценового ядра) не запускалась.
