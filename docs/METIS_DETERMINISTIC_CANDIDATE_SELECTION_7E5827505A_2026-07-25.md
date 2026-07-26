# Metis — детерминированный отбор кандидатов `7E5827505A`

Дата проверки: 2026-07-25  
Live run: `aa621d41-646b-4875-bb0c-138423901a8a`  
Метод: `deterministic-candidate-gates-v1`  
Конфигурация: `backend/config/comparability.yaml`  
SHA-256 конфигурации:
`9315cf08bc8b2a2bd93ae1443abc06e92cd4854eaacb892fe0b39633dc13a4da`

## Результат

Алгоритм выполнен на свежей поисковой выдаче Prom.ua по OE
`7E5827505A`. Все 29 полученных записей прошли одну и ту же
детерминированную early-exit цепочку. LLM не использовался.

| Итоговый статус | Количество | Доля от 29 |
|---|---:|---:|
| `COMPARABLE` | 0 | 0,00% |
| `REVIEW` | 25 | 86,21% |
| `SKIP` | 4 | 13,79% |
| **Всего классифицировано** | **29** | **100,00%** |

## Гистограмма первой терминальной причины

| Причина | Статус | Количество |
|---|---|---:|
| `DISMANTLER_SELLER` | `SKIP` | 2 |
| `USED` | `SKIP` | 1 |
| `OEM_NOT_FOUND` | `SKIP` | 1 |
| `TIER_UNKNOWN` | `REVIEW` | 25 |
| `COMPARABLE` | `COMPARABLE` | 0 |
| **Итого** |  | **29** |

Проверенные ранние выходы:

| Индекс | Продавец | Терминальная причина |
|---:|---|---|
| 15 | `интернет магазин "Avtorazborka24"` | `DISMANTLER_SELLER` |
| 20 | `Razborka.club` | `DISMANTLER_SELLER` |
| 9 | `Інтернет-магазин "АВТОДЕТАЛЬ"` | `USED` |
| 21 | `VolunParts - магазин автозапчастин` | `OEM_NOT_FOUND` |

Оставшиеся 25 кандидатов прошли identity, condition, variant, package и
applicability gates, но были остановлены на tier gate. Это соответствует
текущему состоянию `brands.yaml`: доменная политика не утверждена, а
единственное активное правило — `KEMP → kemp`. Система не подставляет tier
для Polcar и других внешних брендов без утверждённого доказательства.

## Где находятся 61 из 90

Баланс выдачи:

```text
Prom reported total       = 90
HTTP search pages fetched = 1
Configured page limit     = 1
Records retrieved         = 29
Records persisted         = 29
Parser rejects            = 0
Owned offers excluded     = 0
Unfetched                 = 90 - 29 = 61
Coverage                  = 29 / 90 = 0.322222 = 32.22%
```

Следовательно, 61 запись не потеряна фильтрами и не отброшена парсером:
она вообще не была запрошена. Причина сохранена как
`SEARCH_PAGE_LIMIT`. Текущий discovery-контур намеренно ограничен одной
страницей через `CATALOG_DISCOVERY_MAX_SEARCH_PAGES = 1`.

Для полного покрытия этого запроса нужно отдельно разрешить и реализовать
контролируемую пагинацию. Это следующий этап, а не часть текущего stop-gate:
он изменит сетевую нагрузку, время ответа, retry budget и объём raw evidence.

## Что реализовано

- чистый `check_candidate()` без LLM;
- конфигурируемые словари, маркеры и пороги;
- десять последовательных ворот с ранним выходом;
- `COMPARABLE / REVIEW / SKIP` и обязательный reason code;
- сохранение `passed_gates`, мягких flags и подробностей каждого выполненного
  gate;
- версия метода, SHA-256 конфигурации и dataset ID tier-правил;
- PostgreSQL persistence для run и каждого candidate verdict;
- histogram/coverage CLI;
- API-поля и Flutter-представление статуса, причины, флагов и числа
  пройденных ворот;
- явное разделение parser discovery и доказательств, реально вошедших в
  pricing recommendation.

## Safety boundary

`COMPARABLE` в этом модуле означает только «детерминированная цепочка не
нашла противоречия». Такой кандидат не становится автоматически
`automatic_eligible`, calibration pair или ценовым evidence. Допуск к цене
остаётся за отдельными Metis comparability, provenance и recommendation
gates.

## Stop-gate

Текущий этап завершён:

- гистограмма по 29 кандидатам получена;
- причина разницы `29/90` доказана;
- большинство остановилось на `TIER_UNKNOWN`, то есть следующий дефицит
  находится в утверждённых tier-данных, а не в необходимости LLM;
- переход к пагинации, разметке 200 объявлений или LLM в рамках этого этапа
  не выполнялся.
