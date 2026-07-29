# Metis — Wave 0 remediation по функциональному аудиту

Дата: 2026-07-27
Исходный аудит: `.artifacts/audit-2026-07-27/REPORT.md`
Реестр исходных находок: `.artifacts/audit-2026-07-27/FINDINGS.jsonl`

## 1. Итог

Реализованы 15 безопасных исправлений Wave 0 из 16. Исправление F-0016
намеренно не активировано: допустимые диапазоны tier premium являются доменным
решением Q2, а поставляемый конфиг специально использует нейтральные значения
до калибровки. Подмена этого решения инженерным предположением могла бы
заблокировать рабочий конфиг или исказить нормализацию цен.

Дополнительно подтверждено, что F-0003 уже устранена текущими изменениями Gate 1:
реальный ответ Prom для
`https://prom.ua/ua/c2847093-kemp.html?page=346` — HTTP 301 на канонический URL,
и текущая fail-closed граница распознаёт именно этот узкий redirect как конец
пагинации. Добавлен regression-тест с измеренным URL; другие 3xx, смена хоста,
query или первая страница по-прежнему считаются ошибкой.

## 2. Закрытые находки

| Finding | Реализация | Проверка |
|---|---|---|
| F-0002 | Единый money formatter с currency, price tick и точностью tick; тот же формат используется в карточке, evidence и decision dialog | `audit_findings_test.dart`, `pricing_models_test.dart` |
| F-0007 | Idempotency key строится детерминированно из канонического содержания операции; evidence verdicts сортируются | два одинаковых HITL-запроса дают один key |
| F-0008 | Operational Prometheus endpoint требует `CurrentUser` | анонимный запрос получает 401 |
| F-0013 | UI получает `canAdministerWorkspace`; store sync/delete/connect, discovery, context/tier override и admin fitment actions скрыты или отключены для member | widget-тест member-состояния |
| F-0014 | LOW_DISPERSION и HIGH_DISPERSION имеют разные, семантически корректные подписи | regression-тест reason labels |
| F-0017 | Статус системы формируется из `/health/ready` и `/health/source-access`, различает active/limited/unavailable и обновляется каждые 30 секунд | provider-тест healthy + limited |
| F-0018 | Неутверждённый mixed-script/non-Latin brand abstains в UNKNOWN | tiering regression-тест |
| F-0019 | Конфликт явного brand rule с текстовым KEMP marker даёт UNKNOWN/TIER_CONFLICT | tiering regression-тест |
| F-0022 | Polling ограничен пятью последовательными ошибками, использует exponential backoff 2/4/8/16/30 s и имеет явный retry monitoring | controller regression-тест failure → retry → completed |
| F-0025 | `is_available=null` больше не превращается в «Нет в наличии» | model regression-тест |
| F-0029 | Язык сохраняется в SharedPreferences, восстанавливается при запуске и защищён от restore/select race | provider regression-тест |
| F-0030 | Минимальная цель IconButton увеличена с 40 до 44 pt | статический контракт темы + полный widget suite |
| F-0031 | Все четыре ограниченных списка показывают «и ещё N» | reason-summary regression-тесты |
| F-0034 | Отсутствующие source confidence и price-unit certainty остаются `null`; UI показывает «не измерено» | model regression-тесты |
| F-0037 | Candidate report требует `workspace_id`; SQL-запрос и CLI явно scoped | SQL compile regression-тест |

## 3. F-0016 — корректно оставлена открытой

До ответа на Q2 нельзя одновременно выполнить оба текущих контракта:

1. считать диапазоны OEM/OES/Aftermarket нормативными;
2. принимать поставляемые нейтральные `premium = 1.0` до реальной калибровки.

Следующее безопасное изменение после решения владельца:

- зафиксировать нормативные интервалы в versioned config schema;
- различать `CATEGORY_VALIDATED`, `GLOBAL_FALLBACK`, `UNVALIDATED`;
- при выходе за интервал abstain с `TIER_PREMIUM_OUT_OF_RANGE`;
- добавить boundary-тесты на нижнюю/верхнюю границу и значения непосредственно
  за границей;
- не менять коэффициент молча.

## 4. Верификация

Выполнено:

```text
backend:
  uv run ruff check src tests
  result: All checks passed

  uv run pytest -q
  result: 1176 passed, 6 skipped

frontend:
  dart analyze --fatal-infos
  result: No issues found

  flutter test
  result: 79 passed

  flutter build web --release
  result: build/web created successfully; Wasm dry run succeeded

repository:
  git diff --check
  result: clean
```

`flutter analyze` дважды завершился падением самого LSP-клиента на усечённом
JSON initialization message, содержащем percent-encoded путь рабочей директории.
Это не диагностическая ошибка исходников: прямой `dart analyze --fatal-infos`
на том же package завершился без замечаний, а весь Flutter test suite прошёл.

Глобальный `ruff format --check src tests` обнаруживает существующий форматный
baseline в файлах за пределами этого remediation. Изменённые здесь Python-файлы
проверены отдельным `ruff format --check`; массовое форматирование чужого diff
не выполнялось.

## 5. Границы результата

Этот этап закрывает Wave 0, но не означает production readiness и не закрывает
остальные 22 находки аудита. В частности, всё ещё требуют отдельной реализации:

- F-0001: SQL-пагинация каталога вместо загрузки всех listings в Python;
- F-0004: достижимый XLSX import/preflight и запуск pricing run из UI;
- F-0005 и Q4: единый контракт OE normalization и решение по leading zeros;
- F-0027 и Q3: утверждённый brand-tier dataset;
- репрезентативный real-market E2E и подтверждение качества рекомендаций.

Исторические audit artifacts не переписаны: они сохраняют факт состояния на
момент аудита. Этот документ является отдельным remediation evidence.
