# Marko/METIS — OE/OEM coverage audit, 2026-08-08

Это свежий read-only план по полному каталогу KEMP. Он не пишет в БД, не меняет
цены и не расширяет pricing admission. Основной знаменатель — **4 901 строка
каталога**; reference-code universe **7 193 кода** показан отдельно и не
выдаётся за покрытие каталога.

## Как воспроизвести

```bash
cd "marko — копия"
PYTHONPATH=backend/src backend/.venv/bin/python \
  -m marko.catalog_identity_reparse_cli plan \
  --catalog backend/data/kemp_prom_catalog.xlsx \
  --owner-store /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/prom_stores_numbers_catalog.csv \
  --owner-candidates /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/prom_own_store_oe_candidates.csv \
  --optkiev-catalog /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/optkiev_numbers_catalog.csv \
  --json /tmp/identity-owner-candidate-site-final2.json
```

В прогоне использованы обе ревизии reference map, `kemp_site_numbers.csv`,
owner-card CSV, отдельный page-area candidate export и присланный
`optkiev_numbers_catalog.csv`. Строгий карточный Avto.pro/Exist source остаётся
`REVIEW` и в граф не подмешан: разрешённой независимой выгрузки для
автоматического приёма нет.

Зафиксированные входы: каталог SHA256
`7871f6b20b21d96bbd7b5c2ea8c951c2144a6adec04acac5229261c2172e0e91`;
identity config `f7956348af0fce6aafa9d4851a2d0d432a02f09dc991971fe2ae7628c78248f6`;
method `identity-graph-v6`; semantic extractor
`semantic-features-v43-transmission-mount`.

Полная machine-readable provenance-очередь (все 4 901 строки, все 504
противоречия, все 1 883 review-строки, все 573 candidate-строки и 225 delta
строк) лежит в JSON, который создаёт команда выше: `row_results`,
`review_queue`, `contradictions`, `owner_candidate_review[0].rows` и
`deltas.accepted_new_oe_sample`; 1 950 строк OPTKiev находятся в
`optkiev_catalog_review[0].rows`.

## 1. Общая OEM-полнота каталога (4 901 строка)

| Класс | Строк | Доля |
|---|---:|---:|
| `OE_CONFIRMED` | **3 018** | **61.5793%** |
| `REVIEW_OWNER_ASSERTED_OE` | 203 | 4.1410% |
| `REVIEW_REFERENCE_ONLY` | 701 | 14.3032% |
| `MPN_ONLY` | 435 | 8.8757% |
| `UNRESOLVED` | 40 | 0.8162% |
| `REJECTED_NOISE` | 0 | 0.0000% |
| `CONFLICT` | 504 | 10.2836% |
| **Всего** | **4 901** | **100%** |

Дополнительные показатели:

- уникальных подтверждённых OE: **3 043**;
- review-only (`OWNER_ASSERTED_OE` + `REFERENCE_ONLY`): **904 строки / 18.4452%**;
- без usable identity source: **40**;
- строки, изменённые новой evidence: **3 733**;
- identity-status changed: **3 466**; OE-value changed: **123**;
- подтверждённых links: **1 762**, links в `REVIEW`: **557**;
- нормализованный union номеров в source roles: **9 813**; номеров в двух и
  более ролях: **5 126 (52.2368%)**. Это overlap, не независимые голоса.

Причины, по которым строки не стали автоматически подтверждёнными:

| Причина | Строк |
|---|---:|
| `reference_only_cross_or_supplier_number` | 701 |
| `supplier_number_or_cross_not_oe` | 435 |
| `shared_code_or_multiple_catalog_rows` | 459 |
| `variant_side_assembly_or_shared_public_number` | 34 |
| `source_semantic_conflict` | 5 |
| `supersession` | 6 |
| `multiple_owner_cards_for_code` | 42 |
| `missing_independent_assertion` | 904 |
| `no_usable_identity_source` | 40 |

Причины намеренно могут пересекаться: одна строка может одновременно иметь
owner evidence и shared-code anomaly. Ни один MPN, supplier article, внутренний
KEMP-код, кросс или title-token не повышается до OE только из-за формы,
частоты или substring совпадения.

## 2. Reference-code coverage (7 193 кодов, не строки каталога)

| Показатель | Значение |
|---|---:|
| `OE_CONFIRMED` | **5 219 / 7 193 = 72.5567%** |
| `MPN_ONLY` | 1 954 |
| `UNRESOLVED` | 20 |
| заблокировано всего | **1 974** |

Disjoint-разбиение заблокированных кодов:

| Причина блокировки | Кодов |
|---|---:|
| `NO_OE_ASSERTION` — ни один подключённый source role не утверждает OE | **1 277** |
| `GRAPH_QUARANTINE` — OE-source есть, но граф удержан anomaly | **549** |
| `CLEAN_ANCHOR_NOT_ELIGIBLE` — чистый anchor есть, но assertion остаётся REVIEW/неэлигибельным | **148** |
| `OTHER` | 0 |
| **Итого** | **1 974** |

Диагностические (пересекающиеся, поэтому их нельзя суммировать) счётчики:
764 кодов имеют любую graph anomaly; 751 — shared/public-number ambiguity.
Аномалии: `SHARED_ARTICLE_FANOUT` 703, `PUBLIC_NUMBER_SEMANTIC_FANOUT` 48,
`SOURCE_SEMANTIC_CONFLICT` 6, `OE_SUPERSEDED_BY_NEWER_REFERENCE` 7.

## 3. Source-by-source matrix

`catalog_rows_with_confirmed_oe` — строки, где source входит в итоговое
подтверждённое assertion set; `incremental_unique_confirmed_rows` — строки,
где подтверждающий assertion set принадлежит только этому source role. V1/V2
имеют одного publisher и не считаются двумя независимыми голосами.

| Source | Publisher / role | Status, asserts OE | Cards/codes | Catalog evidence | Confirmed OE | Review-only | Conflicts | Unique nums / dup | Incremental |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `KEMP_REFERENCE_MAP_V1` | `kemp_reference_book` / reference OE | CONFIRMED, yes | 3 218 | 2 381 | 2 158 | 223 | 223 | 3 150 / 63 (2.0000%) | 241 |
| `KEMP_REFERENCE_MAP_V2` | `kemp_reference_book` / reference OE | CONFIRMED, yes | 5 331 | 3 027 | 2 777 | 250 | 250 | 5 203 / 127 (2.4409%) | 761 |
| `KEMP_REFERENCE_ARTICLE` | `kemp_reference_article` / cross | CONFIRMED, no | 4 367 | 2 215 | 0 | 1 122 | 361 | 4 800 / 356 (7.4167%) | 0 |
| `KEMP_SITE` | `kemp_site` / site review | REVIEW, yes | 832 | 228 | 93* | 135 | 116 | 803 / 73 (9.0909%) | 0 |
| `OWN_STORE_LABELLED_OE` | `kemp_owned_store` / exact owner card | REVIEW, yes | 1 301 / 1 306 URLs | 1 121 | 0 | 303 | 100 | 4 567 / 1 071 (23.4508%) | 0 |
| `OWN_STORE_CANDIDATE_REVIEW` | `kemp_owned_store` / page-area discovery | REVIEW, no | 141 / 116 URLs | 498 | 0 | 543 clean rows | 0 | 419 / 0 | 0 |
| `OPTKIEV_NUMBERS_CATALOG_REVIEW` | `avtopro_optkiev` / seller review | REVIEW, no | 1 922 / 1 950 URLs | 12 | 0 | 1 950 | 1 | 1 922 / 20 (1.0406%) | 0 |
| `OWN_EXPORT_CODE` | own export code/cross | CONFIRMED, no | — | 4 335 | 0 | 1 440 | 404 | — | 0 |
| `OWN_EXPORT_CHARACTERISTIC` | own characteristic/cross | CONFIRMED, no | — | 811 | 0 | 447 | 243 | — | 0 |
| `AVTOPRO_CARD_OE/CROSS` | avto.pro review | REVIEW | 0 (not loaded) | 0 | 0 | 0 | 0 | 0 | 0 |

`*` KEMP_SITE подтверждает только там, где допустимая corroboration прошла
гейт; один REVIEW site field сам по себе не заполняет OE.

## 4. Owner-card и 135-code queue

`OWN_STORE_LABELLED_OE` загружен только из exact Prom detail-card URL и
подписанных полей (`Оригинальные номера`, `Оригінальні номери`, `OE/OEM`,
`ОЕ номер`, `OEM номери`). Для каждой записи сохранены URL, KEMP code/SKU,
точный label, raw/normalized value, brand, title/spec, captured_at,
parser/source version и file hash. Listing title, общий DOM и `oem == number`
не являются OEM evidence.

- owner rows read: **12 702**; bound rows: **11 916**; exact cards: **1 316**;
  ambiguous codes: **5**; rejected/noise rows: **5 851**;
- owner evidence на catalog rows: **1 121**, из них с подтверждённым графом
  **818**, в owner review **303**;
- unique owner candidates: **4 520**; уже на catalog rows **1 192**; в
  reference graph **1 435**; отсутствуют в reference graph **3 085**.

Отдельный файл `prom_own_store_oe_candidates.csv` — только discovery/review,
не источник подтверждения:

| Метрика | Значение |
|---|---:|
| строк прочитано | 573 |
| clean после детерминированной валидации | 543 |
| clean по исходному noise-флагу | 547 |
| noise всего / по флагу | 30 / 26 |
| KEMP-кодов с clean-кандидатами | 133 (135 до дополнительной проверки) |
| кодов, оставшихся только с noise | 2 |
| уникальных номеров clean | 392 |
| clean номеров отсутствуют в reference maps | 392 |
| clean номеров с structured owner match | 13 |
| exact catalog-code bindings | 498; multiple-row bindings: 0 |

Все 573 строки сохраняются с URL/title/кодом и причинами (`noise flag`, дата/
размер, internal KEMP code, missing structured field, absent reference map и
т. п.) в `owner_candidate_review[0].rows` полного JSON.

Операционная разбивка очереди: **498** строк имеют exact binding к строкам
каталога; **392** clean номера отсутствуют в reference maps; **30** строк
(`27` уникальных номеров) отброшены как явный noise; **13** clean номеров уже
имеют structured owner-field match; оставшиеся **379** clean номеров требуют
ручного решения по detail-card и bound semantics. Ни один из этих 392 clean
page-area кандидатов не принят автоматически как OE.

### OPTKiev / Avto.pro export

Присланный `optkiev_numbers_catalog.csv` прочитан отдельно как seller-card
review, не как OE-asserting source. В нём **1 950/1 950 строк имеют
`oem == номер`**, то есть поле не даёт независимой связи; 1 497 строк помечены
`Аналоги`, 453 — `Оригінальні номери`. Все 1 950 URL — безопасные exact
Avto.pro product-card URLs, но только один `код_kemp` совпал с формой
внутреннего KEMP-кода.

Точное сопоставление с внутренним каталогом дало **12 строк / 11 уникальных
номеров**, включая одну multiple-row ambiguity; с двумя reference maps —
**8 строк / 8 уникальных номеров**. Ни одна запись не стала
`OE_CONFIRMED`. Полная строковая provenance-выгрузка находится в
`optkiev_catalog_review[0].rows` JSON-отчёта.

## 5. Принятые новые OE

Принято **225 catalog-row deltas**, содержащих **223 уникальных новых
нормализованных OE**. Полный список и bound row/source provenance —
`catalog.deltas.accepted_new_oe_sample` в JSON из команды выше. Начало списка:

```text
0021549806, 0159974792, 034198025, 03H115562, 04E145933A, 06A121021,
06A121133D, 06D903137F, 06E903137AA, 120005013, 1233200989, 1243241104,
1243241204, 1245000406, 1300084, 1300270, 132706, 132709, 132711,
13300883, 13300884, 1334024, 1489342080, 150867, 1602435, 1621830,
1661165, 1689810327, 191615123, 1J0411105BG, 1J0615423, 1K0412249,
1K0615423A, 1K0615424A, 1K0927807, 1K0927808, 1T0598611A, 225156QQ,
331511115F, 332627, 377959455G, 443199381C, 443853909AS, 893827552,
8D0615423, 8E0615423A, 9024201101, 96342022, 96549622, D6RA511, KL228,
S6460010
```

<details>
<summary>Полный список 223 уникальных новых OE</summary>

```text
0021549806, 0159974792, 034198025, 03H115562, 04E145933A, 06A121021, 06A121133D, 06D903137F, 06E903137AA, 120005013, 1233200989, 1243241104
1243241204, 1245000406, 1300084, 1300270, 132706, 132709, 132711, 13300883, 13300884, 1334024, 1489342080, 150867
1602435, 1621830, 1661165, 1689810327, 1755031, 1755032, 191615123, 191615124, 1H1857507A, 1H5827550, 1J0411105BG, 1J0615423
1J0615424, 1J6827565B, 1K0412249, 1K0615423A, 1K0615424A, 1K0927807, 1K0927808, 1T0598611A, 1U6827550H, 1U9827550A, 1Z5827550, 1Z9827550
225156QQ, 2D0411051, 2D0411052, 2K0827550, 2K5615424, 330765, 331511115F, 332627, 352362, 364067, 377959455G, 3A9511105
3B5827550, 3B5827550A, 3B5827550E, 3B9827550, 3C0615403, 3C0615403B, 3C0615404, 3C0615404B, 3C0823359A, 3U0823359, 4007N4, 402109533R
424345, 440014373R, 4400N0, 4400N1, 4400P8, 4400P9, 4401620, 4401F2, 4401F3, 4401J6, 4401J7, 4401J8
4401J9, 4401K0, 4401K1, 4401K4, 4401K5, 4401L0, 4401L1, 4401N0, 4401N1, 443199381C, 443823359B, 443823359D
443853909AS, 4A0615423, 4A0807683A, 4A5827552, 4A9827552, 4B0823359A, 4B5827552D, 4B9827552C, 4F5827552, 500279, 5002J6, 5020122
542106, 542290, 542291, 5J7827550, 5K0615424, 6001550441, 6001550442, 6001550443, 6122312, 6124144, 6148604, 6186886
6383210404, 6383230568, 6384280835, 6394280435, 6394280835, 6441E3, 6460920001, 6512000970, 6518302, 6900216, 6962811, 6N0905104
6Q0927803A, 6Q0927804A, 6Q0927807B, 6Q0927808B, 6Y0827550A, 701615423, 71245047, 71753810, 7700419117, 7701049108, 7701206754, 7701206755
7701208058, 7701208361, 7701208362, 7704003765, 7710043963, 7H0827550B, 7L0927807A, 7L0927808A, 7L5919679, 7L6413032L, 7L6945511A, 811827552A
8201167981, 843005, 85BB5310JA, 8731C1, 8731J8, 8731N9, 893827552, 8D0615423, 8D0615424, 8D0823359A, 8D5827552, 8E0615423A
8E0615423B, 8E0615424, 8E0615424A, 8E0615424B, 8E9827552E, 8P0823359, 8P3827552D, 8R0823359A, 9024201101, 90273102, 90297533, 90297534
90353038, 90353039, 90379054, 9062900112, 9064280435, 9064280635, 9064280935, 9193225, 91AB1104AD, 91AB3L519BA, 92AB8005BB, 93302485
93732355, 93740622, 93740623, 93742272, 94580413, 96179833, 96205809, 96211128, 96232994, 96232995, 96273700, 96273701
96342022, 96391875, 96403099, 96403100, 96404803, 96404804, 96407485, 96407486, 96407749, 96407753, 96490218, 96494603
96534637, 96534638, 96540939, 96549622, D6RA511, KL228, S6460010
```

</details>

Это не список кандидатов из собственных карточек: owner candidates остаются
`REVIEW` до ручного подтверждения bound pair или независимой assertion.

## 6. Противоречия, пропуски и negative checks

- Полная очередь: **1 883** non-confirmed catalog rows; полная contradiction
  очередь: **504**. Для каждой записи есть source names, raw discarded values,
  graph anomalies и `review_reasons`.
- Проверены и сохранены shared code/multiple rows, variant/side/assembly,
  supplier/cross, page boilerplate, missing detail card, semantic conflict,
  supersession и missing independent assertion.
- Exact token boundary сохраняется: `123456` не матчит `1234567`; fuzzy,
  substring, title-only и транзитивная clique-склейка запрещены.
- При отсутствии detail-card characteristics title/общий HTML не повышаются в
  OE; карточка с несовпадением product identity остаётся `FAILED/REVIEW`.
- Owner label parsing не принимает `Код запчастини` как OEM; exact card binding
  с неподписанным или небезопасным URL отвергается.
- Автоматический pricing publication, migrations и production writes не
  выполнялись.

## 7. Изменённые файлы и проверка

Основные изменения: `catalog_identity_coverage.py` (полный audit/report,
source matrix, disjoint blocked split, owner queue),
`catalog_identity_reparse_cli.py` (owner-candidate input и полный detail limit),
`catalog_identity_reparse.py` (exact owner-card provenance),
`parser_models.py`, `parsers/prom/gateway.py`, `services/owned_catalog.py`,
`config/identity_graph.yaml`, плюс соответствующие negative/coverage tests.

Проверка:

- `python -m compileall -q backend/src backend/tests` — **pass**;
- targeted identity/coverage/graph/owner/detail/Avto suites — **307 passed**;
- финальный coverage+CLI subset (включая OPTKiev review loader) — **8 passed**;
- полный `pytest -q` остановился на существующей test-environment ошибке
  async fixture `_isolate_database_engine_per_event_loop` без plugin/hook до
  выполнения тестов; это не ошибка OE/OEM кода.

Итоговая граница честности: **3 018 строк — подтверждённое OE-покрытие**.
Ещё **904 строки** имеют review-only evidence, а 543 owner-candidate rows,
392 clean candidate numbers, 1 950 OPTKiev seller rows и Avto.pro/Exist
discovery — только потенциальный рост, не подтверждённый OEM.
