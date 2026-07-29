# ИСПОЛНЕНИЕ: три исхода отбора и база подъёма цены

**Дата:** 2026-07-28
**Задание:** отбор сопоставимых товаров (часть A) + база для подъёма цены (часть B)

---

## Часть A. Три исхода вместо двух

`CandidateStatus` теперь описывает **применимость**, а не уверенность:

```
PRICING_EVIDENCE  та же деталь, уровень известен и приводится → в расчёт
REFERENCE_ONLY    та же деталь, уровень неизвестен/неприводим → показывается
REJECTED          другая деталь / б-у / свой магазин           → не показывается
```

Цепочка разделена на две фазы. Идентичность (только `REJECTED`):
`own_seller → dismantler_seller → category_domain → condition →
remanufactured → oem_identity → oem_stuffing → variant → package →
applicability`. Сопоставимость (только `REFERENCE_ONLY`):
`tier_classification → own_brand → tier_known → premium_calibration →
price_anomaly`.

### Результат на записанном прогоне 7E5827505A

```
БЫЛО                        СТАЛО
COMPARABLE  0               PRICING_EVIDENCE   0
REVIEW     25               REFERENCE_ONLY    25
SKIP        4               REJECTED           4

Показывается заказчику: 25 из 29 (86.2%), было 0
```

`PRICING_EVIDENCE = 0` — честное состояние: `brands.yaml` одобряет только KEMP,
а валидированных коэффициентов уровня нет. Оба шага делает человек.
Реплей: `backend/tests/test_candidate_outcomes_7e5827505a.py`.

### Отклонения от задания

| Что | Почему |
|---|---|
| `category_domain` и `oem_stuffing` оставлены в фазе идентичности, хотя в списке A.2 их нет | первый отсекает лестницы для бассейнов из выдачи по числовому артикулу, второй — только флаг; удаление было бы регрессом без запроса |
| `USED_BY_TIER` остался `REJECTED` внутри `tier_classification` | это факт об идентичности, добытый поздно, потому что нужен классификатор |
| `SAME_BRAND_KEMP` (`SKIP`) → `OWN_BRAND` (`REFERENCE_ONLY`), срабатывает по tier, а не только по списку продавцов | требование заказчика: цены других продавцов KEMP видны, но не влияют на расчёт; калибровочный якорь читает свой набор |

Ворота 11 подключены к существующему источнику — `load_tier_coefficients`,
только `validated`. Кандидат нашего уровня коэффициента не требует: отношение
единица по построению.

---

## Часть B. Относительно чего поднимается цена

Новый чистый модуль `metis/pricing/raise_policy.py` + конфиг
`config/raise_policy.yaml` (пресеты `aggressive` 0.25 / `balanced` 0.50 /
`premium` 0.75, по умолчанию `balanced`).

Ограждения в порядке спецификации: значимость 3% → потолок шага 25%
(`STEP_CAPPED`) → уверенность (`HIGH` при n≥4 и CV<0.15, `MEDIUM` при n≥3 и
CV<0.35, иначе `LOW` → `SHOW_BUT_FLAG`) → округление вниз до 10 грн →
себестоимость только флагом.

### Правило stale

```
stale дешевле самого дешёвого конкурента → RAISE, потолок = цена самого дешёвого
stale не дешевле                          → молчание (STALE_NOT_CHEAPEST)
fresh дороже целевой точки                → молчание (ALREADY_COMPETITIVE)
dead                                      → ликвидация, не тронута
```

Потолок «до самого дешёвого» — решение исполнителя. Заказчик задал условие
подъёма, но не цель; поднимать залежавшийся товар до медианы значило бы
обменять остатки спроса на маржу. Флаг `STALE_CAPPED_AT_CHEAPEST`.

### Проверенный численный пример воспроизведён

```
E = [1650, 1720, 1940, 2100]
p25 = 1702.5  p50 = 1830.0  p75 = 1980.0  IQR = 277.5  robust_CV = 0.1516
n = 4, но CV > 0.15  →  MEDIUM (не HIGH)
```

### Изменённые контрактные тесты

Решение заказчика по `stale` и запрет снижения по ходовому товару меняют смысл
уже принятых требований v1. Изменено:

| Тест | Было | Стало |
|---|---|---|
| `test_fresh_market_lower_case_produces_manual_lower_candidate` | fresh дороже рынка → `LOWER` | `HOLD` + `PRICE_ALREADY_AT_OR_ABOVE_TARGET` |
| `test_stale_age_pressure_is_monotonic_and_continuous` | чем дольше лежит, тем глубже уценка | инвариант **потерял носителя**: у dead stock `beta = 1`, возраст не влияет; заменён на «уценка dead stock насыщена» + новый «медленный товар не уценивается» |
| `test_dead_stock_target_is_not_higher_than_stale_for_same_age` | сравнение dead и stale | сравнение dead с текущей ценой |
| `test_missing_cost_does_not_block_market_clearance_recommendation` | на stale | на dead stock |
| `test_fresh_product_can_follow_supported_market_downward` | `LOWER` | «никогда не советует вниз» |
| `test_fresh_items_follow_market_in_both_directions` | вверх и вниз | «вверх или молчание» |
| `test_raise_is_capped_by_maximum_single_step` | потолок 15%, цена 920 | потолок 25%, цена 1000 |

`test_r019_baseline_abstention_cannot_be_relaxed` сохранён с расширенным
порогом уверенности: иначе новая проверка воздерживалась бы первой и тест
проходил бы по неверной причине.

### Ставшие недостижимыми ручки политики

Ноль обращений в коде: `min_raise_threshold`, `min_lower_threshold`,
`safety_discount`, `max_raise_step`, `lower_market_support_enabled` — заменены
порогами из `raise_policy.yaml`. Только в ветке ликвидации, куда `stale`
больше не попадает: `stale_markdown_beta`, `stale_age_threshold_days`,
`stale_age_half_life_days`. Не удалены: это политика, уценка stale может
вернуться.

Политика подъёма не копируется в каждый прогон — в `policy_config` пишется
только её identity (`strategy`, `method_version`, `source_sha256`), чтобы не
завести второй расходящийся источник правды.

---

## Часть 3. API и UI

`GET /catalog/competitors` отдаёт два списка — `pricing_evidence[]` и
`reference_only[]` — плюс `confidence_grade` и `dispersion`, чтобы карточка
показывала арифметику, а не только вывод. `discovery_items` остался полным
списком для диагностики.

Карточка: блок «Учитываются в расчёте», блок «Показаны справочно · в расчёт
не входят», в обоих — ссылка на каждое объявление. Карточка расчёта называет
причину молчания вместо пустого места («изменение ниже порога значимости»,
«товар лежалый и не дешевле самого дешёвого конкурента» и т.д.).
Отброшенные кандидаты в карточке больше не показываются — только счётчиком
в гистограмме.

Скриншот: `frontend/test/goldens/catalog_7e5827505a.png`, генерируется
`frontend/test/catalog_7e5827505a_golden_test.dart`.

---

## Проверки

```
backend  pytest tests -q     1255 passed, 6 skipped
frontend flutter test        85 passed
миграция 20260728_0024       рендерится офлайн, голова одна
```

Миграция отображает исторические строки один-к-одному
(`COMPARABLE→PRICING_EVIDENCE`, `REVIEW→REFERENCE_ONLY`, `SKIP→REJECTED`) и
переименовывает счётчики прогона; `rejected_count` не тронут — он считает
отказы парсера, а не кандидатов.

## Открыто

- Живой прогон `7E5827505A` не выполнен: доступ к Prom в этом окружении
  `NOT_PERMITTED`. Скриншот сделан на фикстуре с распределением записанного
  прогона.
- `PRICING_EVIDENCE` останется нулём, пока человек не одобрит бренды в
  `brands.yaml` и не появится валидированная калибровка.
