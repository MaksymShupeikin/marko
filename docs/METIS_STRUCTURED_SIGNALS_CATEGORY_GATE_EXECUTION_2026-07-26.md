# ОТЧЁТ ОБ ИСПОЛНЕНИИ: СТРУКТУРНЫЕ СИГНАЛЫ PROM + ВОРОТА КАТЕГОРИЙНОГО ДОМЕНА

**Дата:** 2026-07-26
**Мастер-промпт:** `docs/METIS_STRUCTURED_SIGNALS_CATEGORY_GATE_MASTER_PROMPT_2026-07-26.md`
**Статус:** WP-0 PASS · WP-1 PASS (частично, по доказанным полям) · WP-2 PASS ·
WP-3 BLOCKED_NO_DATA_SOURCE (доказано числом)

---

## 1. WP-0 — эмпирический аудит сырых данных Prom

Аудит выполнен на **уже захваченных, SHA-256-верифицированных** блобах
(`scrape_evidence_blobs.content_zlib`), а не на новом запросе: 6 блобов,
3 разных запроса, **N = 137 сырых product-узлов**. Разбор — реальным
парсером проекта (`marko.parsers.prom.parser`), не собственной реализацией.

### 1.1. Таблица фактов (сырой Apollo-кэш Prom, не наш нормализованный слой)

| Поле (сырой путь Prom) | Присутствует | Заполненность | Вердикт |
|---|---|---|---|
| `categoryId` | да | **137/137 (100.00%)** | пригодно |
| `categoryIds` | да | **137/137 (100.00%)** | пригодно, **не было в маппинге** |
| `manufacturerInfo.name` | да | 127/137 (92.70%) | уже используется |
| `model.id` / `newModelId` | да | 16/137 (11.68%) | нативно, но потребителя нет |
| `characteristics` | **нет** | **0/137 (0.00%)** | источника нет |
| `comparisonEvidence.*` | **нет** | **0/137 (0.00%)** | источника нет |

Рекурсивный поиск на любой глубине вложенности (до 6 уровней) подтвердил:
`comparisonEvidence` — 0/137, `characteristics` — 0/137. Ключей нет физически,
а не «есть, но пустые».

### 1.2. Главный вывод WP-0

Исходная формулировка задачи предполагала, что поля `fitment`,
`vehicle_generation`, `year_from`, `year_to`, `side`, `position` можно
«начать использовать». Это предположение **опровергнуто**: они объявлены в
`_FIELDS_PATH_MAP` под префиксом `comparisonEvidence.*`, которого Prom не
отдаёт, и который в коде никто не заполняет. Запасной вариант — вытащить их
из `characteristics` — тоже отпал: этого ключа в поисковой выдаче нет вовсе.

Взамен обнаружено то, чего в постановке не было: **`categoryIds` — полный
путь предков от корня** (`[0, 55, 5502, 341529, 341550]`), 100% заполненность.
Это позволило реализовать категорийные ворота, **не выкачивая дерево
категорий Prom** — то есть снять главный риск блокировки WP-2.

---

## 2. WP-1 — поля в `CandidateItem`

| Поле из исходного списка | Решение | Основание |
|---|---|---|
| `category_id` | **ДОБАВЛЕНО** | 137/137, есть потребитель (ворота) |
| `category_path` (из `categoryIds`) | **ДОБАВЛЕНО** | 137/137, есть потребитель |
| `model_id` | **не добавлено** | 11.68%, потребителя нет; мёртвое поле |
| `fitment` | BLOCKED_NO_DATA_SOURCE | 0/137 |
| `vehicle_generation` | BLOCKED_NO_DATA_SOURCE | 0/137 |
| `year_from`, `year_to` | BLOCKED_NO_DATA_SOURCE | 0/137 |
| `side`, `position` | BLOCKED_NO_DATA_SOURCE | 0/137 |

`Product.category_ids` добавлен в `parser_models.py` (`categoryIds`), поэтому
значение автоматически течёт через `product.as_dict()` → `candidate_records`
→ `CandidateItem` → `raw_snapshot`. Обратная совместимость сохранена:
`from_normalized_snapshot` отдаёт `None` для старых снимков.

---

## 3. WP-2 — ворота категорийного домена

### 3.1. Почему deny-, а не allow-семантика по умолчанию

Наивное предположение «автозапчасти живут под `[0, 55, 5502]`» **опровергнуто
данными**: подлинные крышки маслозаливной горловины наблюдались под
`[0, 509, 71906]`, а `NTY KOREK OLEJU` — под `[0, 18, 208]`. Строгий allowlist
из одного корня дал бы ложные отсечения настоящих конкурентов.

Поэтому по умолчанию работает **denylist доказанных не-автомобильных
доменов**: неизвестная категория проходит (fail-open), и неполнота списка
физически не может вызвать ложный SKIP. Строгий allowlist реализован, но
выключен до утверждения владельцем.

### 3.2. Почему majority-vote выключён — измерено, а не предположено

| запрос | share (leaf) | share (prefix[:3]) |
|---|---|---|
| 2141006 | 0.3889 | 0.7778 |
| 324412 | 0.2414 | 0.2414 |
| 7E5827505A | 0.9667 | 1.0000 |

На префиксе голосование становится «эффективным» для 2141006, но проверка
того, **кого именно** оно отсекает, показала: из 4 отсечённых карточек
3 — подлинные сопоставимые автозапчасти из соседней ветки дерева, и лишь
1 — реальный посторонний товар. Доля ложных отсечений 75%. Режим оставлен
реализованным и конфигурируемым, но `enabled: false`, с обоснованием в
самом конфиге.

### 3.3. Критическая деталь корректности

Сравнение путей — **поэлементное по int**, не строковое. Строковый префикс
сделал бы предка `20` (`[0, 18, 20]`, самокати) совпадающим с категорией
`208` (`[0, 18, 208]`, автозапчасти) и отсёк бы `NTY KOREK OLEJU`. Покрыто
отдельным тестом.

### 3.4. Результат прогона по всем 137 захваченным карточкам

| причина | ДО | ПОСЛЕ | Δ |
|---|---:|---:|---:|
| CATEGORY_NOT_AUTOPARTS | 0 | **18** | **+18** |
| TIER_UNKNOWN (REVIEW) | 77 | **59** | **−18** |
| BRAND_MISMATCH | 5 | 5 | 0 |
| OEM_NOT_FOUND | 48 | 48 | 0 |
| DISMANTLER_SELLER | 5 | 5 | 0 |
| OWN_SELLER | 1 | 1 | 0 |
| USED | 1 | 1 | 0 |

Все 18 новых отсечений проверены по названиям товаров и верны: накладка для
сходів басейну Emaux, 6 самокатів, 4 бра, 3 брелоки, 2 бритви, пакет, зошит.
**Ложных отсечений — 0.** Запрос `7E5827505A` (настоящие автозапчасти) —
**0 изменений**.

### 3.5. Живые прогоны (стоп-гейт)

| запрос | run_id | покрытие | было | стало |
|---|---|---|---|---|
| 2141006 | `a41e072d-97e2-4837-bf59-aee2d64c4c9c` | 18/18, 1.000000 | REVIEW 1 · SKIP 14 | **REVIEW 0 · SKIP 15** |
| 7E5827505A | `38db3b36-da33-4321-8349-20c32cbb83ce` | 90/90, 1.000000 | REVIEW 49 · SKIP 38 | REVIEW 49 · SKIP 38 |

Повторные прогоны из **пересобранного образа** (не из ручных патчей),
подтверждающие идентичный результат:

| запрос | run_id | результат |
|---|---|---|
| 7E5827505A | `62eefaf3-f00c-4c34-a5c4-6e43c1e8d05b` | 90/90, REVIEW 49 · SKIP 38 |
| 2141006 | `a0239f99-338d-4f75-92be-061a1c590ce2` | 18/18, REVIEW 0 · SKIP 15, Emaux → CATEGORY_NOT_AUTOPARTS |

Карточка Emaux в живом прогоне:
```
SKIP / CATEGORY_NOT_AUTOPARTS
category_path=[0, 13, 1808, 180803]
mode=BLOCKLIST  matched_ancestor=[0, 13, 1808]
```

---

## 4. WP-3 — приоритет структурных полей в воротах 6/8

**BLOCKED_NO_DATA_SOURCE.** Основание — не мнение, а измерение: 0/137 для
`side`, `position`, `vehicle_generation`, `year_from`, `year_to`, `fitment`,
как по прямым путям, так и рекурсивно на любой глубине. Ворота 6 и 8 не
тронуты и продолжают работать по regex; регрессий в их тестах нет.

Реализовывать «приоритет структурного поля» поверх источника, который
физически пуст, означало бы написать мёртвую ветку кода и выдать её за
интеграцию (нарушение CONSTRAINT_3).

---

## 5. Проверки

| проверка | результат |
|---|---|
| backend pytest | **995 passed, 6 skipped** (было 981/6) |
| tests/test_candidate_selection.py | 46 passed (было 26) |
| ruff check | All checks passed |
| ruff format (изменённые файлы) | чисто |
| flutter test | **54 passed** |
| flutter analyze | **No issues found** (через ASCII-путь) |
| dart format | 0 changed |
| alembic check | No new upgrade operations detected |

Замечание по `flutter analyze`: из исходного каталога проекта команда падает
с `FormatException` — в имени каталога неразрывный пробел (U+00A0) и
кириллица ломают JSON в LSP-канале анализатора. Это дефект окружения, не
кода; проверка выполнена на ASCII-копии.

---

## 6. Изменённые файлы

| файл | суть |
|---|---|
| `backend/src/marko/services/parser_models.py` | `category_ids` в маппинг и в `Product` |
| `backend/src/metis/pricing/candidate_selection.py` | `CategoryDomainConfig`, `CategoryDomainContext`, `_gate_category_domain`, `build_category_domain_context`, поля `CandidateItem`, валидация конфига |
| `backend/src/metis/pricing/__init__.py` | экспорты |
| `backend/src/marko/services/catalog_discovery.py` | `_category_id`, `_category_path`, вычисление контекста, передача в гейты |
| `backend/config/comparability.yaml` | секция `category_domain` с доказательной базой |
| `backend/tests/test_candidate_selection.py` | +14 тестов матрицы вариаций |
| `frontend/lib/.../catalog_competitor_section.dart` | локализация двух новых причин |

---

## 7. Что осталось открытым

Ворота категорий не влияют на главный затык: `TIER_UNKNOWN` = 49/87 на
`7E5827505A`. Это по-прежнему **P0-блокер WP-2 предыдущего документа** —
нужны утверждённые владельцем tier-метки для non-KEMP брендов (Polcar,
Detali IF, NTY, VIKA, Autotechteile, VAG, Volkswagen). Категорийные ворота
эту задачу не решают и не должны были.

---

## 8. Артефакты стадии

Каталог: `.artifacts/metis_structured_signals_category_gate_20260726/`

| файл | что это |
|---|---|
| `regenerate_evidence.py` | воспроизводит §1 и §3 из БД по шести блобам, пришпиленным по SHA-256; сети не требует |
| `WP0_RAW_FIELD_AUDIT.txt` | вывод аудита сырых полей, `N = 137` |
| `WP2_CATEGORY_GATE_REPLAY.txt` | ДО/ПОСЛЕ по всем 137 карточкам и список 18 отсечённых |
| `EVIDENCE_SUMMARY.json` | те же числа в машиночитаемом виде |
| `end_of_response.yaml` | манифест Section 15.1, `contract_version 15.1` |
| `machine_summary.yaml` | манифест Section 16, `1.1.0` |
| `footer.md`, `FINAL_RESPONSE.md` | канонический футер и полный ответ |
| `build_governance_manifests.py` | генератор обоих манифестов |

Валидация (все четыре прогона зелёные):

```
uv run validate-response-footer  --manifest .../end_of_response.yaml         → END_OF_RESPONSE_VALID
uv run validate-response-footer  --manifest .../end_of_response.yaml --footer .../footer.md
                                                                             → END_OF_RESPONSE_VALID
uv run validate-machine-summary  --manifest .../machine_summary.yaml         → MACHINE_READABLE_SUMMARY_VALID
uv run validate-machine-summary  --manifest .../machine_summary.yaml \
    --footer-manifest .../end_of_response.yaml --response .../FINAL_RESPONSE.md
                                                                             → MACHINE_READABLE_SUMMARY_VALID
```

Стоп-гейт стадии: `STOP_GATE_METIS_STRUCTURED_SIGNALS_CATEGORY_GATE_20260726 = BLOCKED`.

Ранние скрипты `audit_raw.py` и `replay.py` оставлены как история хода работ,
но невоспроизводимы: они читают `blobs.b64`, которого нет, и указывают на
удалённый временный каталог. Воспроизводить нужно `regenerate_evidence.py`.
