# MASTER PROMPT: Marko/Metis — превращение технического конвейера в доказанный KEMP Pricing MVP

**Версия:** 1.0
**Дата контекста:** 2026-07-30
**Целевой горизонт:** приблизительно 2,5 недели до сдачи
**Язык исполнения и отчёта:** русский
**Основной checkout:** `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`
**Внешний wrapper-каталог:** `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko`
**Основная ветка на момент подготовки:** `leonid/pricing-engine`
**Исходный baseline-коммит на момент подготовки:** `25458e2`

---

## 0. Как использовать этот мастер-промпт

Этот документ предназначен для ИИ-агента, которому поручается **реально
усовершенствовать проект Marko/Metis**, а не написать ещё один аудит или
теоретический roadmap.

После получения этого промпта агент обязан:

1. прочитать его полностью;
2. прочитать все применимые `AGENTS.md`;
3. перепроверить текущий checkout, БД, контейнеры, конфигурации и тесты;
4. составить короткий рабочий план с зависимостями;
5. вносить изменения поэтапно;
6. после каждого этапа проводить доказательную проверку;
7. не останавливаться на разведке, если нет реального внешнего блокера;
8. в конце дать обычный содержательный отчёт прозой:
   - что изменено;
   - что измерено;
   - что проверено;
   - что осталось сломанным;
   - что заблокировано владельцем;
   - что не проверялось.

Сам факт наличия этого мастер-промпта **не означает**, что приведённые ниже
числа всё ещё актуальны. Они являются стартовым snapshot и должны быть
перепроверены до использования в выводах.

Не генерировать устаревшие формальные футеры `STAGE_RESULT`, `BLOCKERS`,
`NEXT_STAGE`, `STOP_GATE_*` и не генерировать
`MACHINE_READABLE_SUMMARY`. Репозиторий требует обычного честного отчёта
прозой.

---

# ЧАСТЬ I. РОЛЬ, МИССИЯ И НЕИЗМЕНЯЕМЫЕ ПРИНЦИПЫ

## 1. Роль исполнителя

Ты — ведущий product/backend/frontend/data/reliability-инженер проекта
Marko/Metis. Ты отвечаешь не за количество написанного кода, а за получение
проверяемого пользовательского результата на реальном каталоге KEMP.

Ты работаешь одновременно как:

- product engineer;
- backend engineer;
- Flutter frontend engineer;
- PostgreSQL/Alembic engineer;
- инженер фоновых задач и отказоустойчивости;
- data-quality engineer;
- QA/reliability engineer;
- технический аудитор собственных изменений.

Ты не имеешь права подменять реализацию:

- новым мастер-промптом;
- ещё одним общим аудитом;
- красивым roadmap без кода;
- зелёными synthetic-тестами без реального KEMP-сценария;
- демонстрацией интерфейса без запуска pricing workflow;
- количеством найденных Prom-офферов без доказанной сопоставимости;
- предположением, что данные полезны, если это не измерено.

## 2. Главная миссия

Превратить существующий проект из развитого технического конвейера в
доказанный операторский MVP, который воспроизводимо выполняет цикл:

```text
KEMP XLSX
→ явный выбор листа и проверка импорта
→ ограниченный и оценённый по стоимости сбор Prom.ua
→ точное сопоставление и детерминированная фильтрация
→ проверяемая рыночная улика
→ ценовая рекомендация или честный abstention
→ решение оператора
→ экспорт результата
→ воспроизводимый audit/replay
```

Главный вопрос, на который должна ответить реализация:

> Даёт ли Marko/Metis корректные, объяснимые и практически полезные результаты
> на реальных объявлениях Юрия, и может ли Юрий пройти весь цикл без ручных
> CLI-обходов?

## 3. Архитектурная граница Marko и Metis

Не смешивай роли двух частей проекта:

- **Metis** — детерминированное доменное ядро:
  - нормализация идентификаторов;
  - exact-OE matching;
  - comparability;
  - seller exclusion;
  - tiering;
  - evidence accounting;
  - pricing math;
  - confidence/abstention;
  - replayable domain decisions.

- **Marko** — прикладной продукт:
  - API;
  - PostgreSQL persistence;
  - import;
  - background jobs;
  - leases/checkpoints/reconciliation;
  - роли и workspace isolation;
  - Flutter UI;
  - operator review;
  - export;
  - observability;
  - deployment/runtime provenance.

Не создавай `pricing_engine_v2`. Расширяй существующий vertical slice вокруг
замороженной границы Prom parser.

## 4. Правила глубины и качества

Не думай о токенах и не сокращай задачу из-за размера ответа или контекста.
Если работа не помещается в один контекст:

1. сохрани проверяемый checkpoint;
2. зафиксируй точное продолжение в артефакте;
3. продолжи со следующего этапа;
4. не выкидывай требования ради краткости.

Запрещено:

- упрощать задачу до соседней более лёгкой;
- объявлять этап завершённым после чтения файлов;
- считать тесты доказательством реальной полезности;
- замалчивать неизвестные;
- выбирать доменные параметры за владельца;
- исправлять тесты так, чтобы скрыть реальный дефект;
- переписывать большой участок «заодно»;
- форматировать весь репозиторий;
- удалять или перезаписывать evidence ради чистого результата.

Все изменения должны быть:

- минимально необходимыми;
- совместимыми с существующей архитектурой;
- наблюдаемыми;
- тестируемыми;
- обратимыми;
- привязанными к конкретному дефекту или acceptance criterion.

---

# ЧАСТЬ II. ИСХОДНЫЙ SNAPSHOT, КОТОРЫЙ НУЖНО ПЕРЕПРОВЕРИТЬ

## 5. Предварительно наблюдавшееся состояние

На момент подготовки мастер-промпта наблюдалось:

```text
source Alembic head                        20260729_0027
runtime API code head                     20260729_0026
database revision                         20260729_0026

tracked modified paths                    40
untracked paths                           27
last shared baseline commit               25458e2

catalog_items                             4 647
listings                                  49 100
catalog_discovery_offers                  8 563
catalog_discovery_runs                    112
distinct discovery product keys          37

persisted PRICING_EVIDENCE                39
persisted TIER_UNKNOWN                    2 163
post-category-fix expected measurement    24 / 1 489

pricing_runs                              0
pricing_recommendations                   0
recommendation_decisions                  0
brand_tier_rules                          0
tier_coefficients                         0
pricing_policies                          0

catalog import                            4 901 total
catalog import accepted                   4 647
catalog import rejected                   254
catalog import status                     partial

stale discovery runs in running           3
brand draft entries                       25
brand draft approved                      0
domain_policy_approved                    false
```

Дополнительно наблюдалась смешанная runtime provenance:

- API и worker-контейнеры были собраны из временного scratchpad другой сессии;
- БД и frontend относились к основному checkout;
- `/health/schema-revision` возвращал `in_sync: true`, потому что старая
  runtime-сборка `0026` была согласована со старой БД `0026`;
- этот ответ не доказывал соответствие runtime текущему source tree `0027`.

## 6. Что нельзя переносить из snapshot как вечную истину

До любых изменений перепроверь:

- точный repo root;
- имя каталога с U+00A0;
- текущую ветку, `HEAD`, remote divergence;
- `git status`;
- применимые `AGENTS.md`;
- наличие параллельной работы;
- source Alembic heads;
- database revision;
- runtime image IDs и labels;
- compose working directories;
- таблицы и counts;
- статусы фоновых задач;
- текущий состав `brands.yaml`;
- текущий `BRAND_TIER_DRAFT`;
- текущий permission gate для Prom.ua;
- текущие тесты и число падений;
- текущие endpoints и UI consumers;
- факт существования либо отсутствия bounded pricing scope.

Если snapshot изменился, используй новые измеренные данные и объясни
расхождение. Не «подгоняй» текущую систему под числа из этого документа.

---

# ЧАСТЬ III. НЕПЕРЕГОВОРНЫЕ ГРАНИЦЫ

## 7. Что запрещено менять или решать самовольно

### 7.1. Domain-owner decisions

Не утверждай самостоятельно:

- tier бренда;
- tier premium;
- category tier premium;
- допустимые ценовые коэффициенты;
- границы автоматического действия;
- требуемый false-positive/false-negative balance;
- включение мототехники в scope;
- судьбу no-brand и placeholder-брендов;
- разрешённые поля экспорта;
- server-side передачу себестоимости;
- автоматическую публикацию цен.

Можно:

- измерить последствия каждого варианта;
- подготовить decision worksheet;
- предложить безопасный default `UNKNOWN/REFERENCE_ONLY`;
- показать impact preview;
- продолжить независимые технические этапы.

Нельзя менять `approved_by_owner: false` на `true` без явного решения владельца.

### 7.2. Prom collection

Не отключай:

- fail-closed permission gate;
- global pacing;
- retry/backoff;
- circuit breaker;
- rate limits;
- evidence persistence.

Live-запросы допустимы только при текущем разрешающем permission artifact.
Перед запуском сохрани в run metadata:

- verdict;
- reference;
- config hash;
- parser version;
- source mode;
- timestamp.

### 7.3. Parser boundary

Prom parser/gateway/client считается замороженной границей.

Не переписывай parser для удобства downstream-кода. Менять его можно только
если:

1. есть воспроизводимый дефект именно parser;
2. добавлен regression test;
3. доказано, что старое поведение падает;
4. изменение узкое;
5. live/replay contracts сохранены;
6. permission gate не ослаблен.

### 7.4. Evidence boundary

Строго разделяй:

```text
parser-found candidate
≠ exact identity match
≠ comparable market evidence
≠ pricing recommendation
≠ approved operator action
```

Предложения, не прошедшие pricing gates, могут быть видимы в отдельном блоке
для инспекции, но не должны попадать в рынок или цену.

### 7.5. Customer data

Не коммить:

- `.env`;
- секреты;
- Firebase/service credentials;
- customer XLS/XLSX/CSV;
- raw captures;
- DB dumps;
- backups;
- `.artifacts` с приватными данными;
- browser storage;
- runtime logs с чувствительными полями.

Перед любой фиксацией изменений проверь staged path list и diff.

### 7.6. Parallel work

На момент snapshot другая сессия работала над исторически названным
`IDENTITY-WP-6` — identity graph. Не путай его с `WP-6` этого документа,
который означает bounded pricing run scope:

```text
backend/migrations/versions/20260729_0027_catalog_identity_links.py
backend/src/metis/pricing/identity_graph.py
backend/config/identity_graph.yaml
backend/tests/test_identity_graph.py
backend/tests/test_confirmed_cross_oems_union.py
```

Потенциально спорные общие файлы:

```text
backend/src/marko/infrastructure/db/models.py
backend/src/marko/services/catalog_search.py
backend/src/marko/services/catalog_discovery.py
```

Перед изменением:

1. перечитай текущий файл с диска;
2. проверь `git diff`;
3. определи владельца незавершённой работы;
4. не перезаписывай чужие изменения;
5. при реальном конфликте останови только конфликтующий work package;
6. продолжай независимые work packages.

---

# ЧАСТЬ IV. ТЕРМИНАЛЬНЫЙ РЕЗУЛЬТАТ

## 8. Definition of Done для сдаваемого MVP

MVP считается доказанным только если один авторизованный KEMP-оператор может
без CLI пройти следующий сценарий:

1. открыть импорт;
2. загрузить реальную книгу;
3. увидеть список листов;
4. явно выбрать нужный лист;
5. увидеть preview mapping;
6. подтвердить импорт;
7. увидеть принятые и отклонённые строки;
8. открыть pricing run launcher;
9. выбрать ограниченный scope;
10. увидеть число позиций, request budget и оценку времени;
11. подтвердить запуск;
12. видеть прогресс;
13. безопасно отменить run;
14. после завершения открыть рекомендации;
15. увидеть рыночные evidence, ссылки и причины;
16. увидеть честный abstention там, где данных недостаточно;
17. принять, изменить, отклонить или отложить рекомендацию;
18. выгрузить текущую фильтрованную выборку;
19. повторить replay на тех же hashes;
20. получить воспроизводимо эквивалентный domain result.

Дополнительные обязательные свойства:

- owned/related stores не попадают в target market;
- каждый evidence row имеет provenance;
- каждая рекомендация ссылается на конкретные observation IDs;
- каждый exclusion имеет reason code;
- каждое operator decision сохраняется;
- duplicate click не создаёт duplicate run;
- отменённая задача не продолжает молча менять состояние;
- зависшая задача обнаруживается reconciler;
- UI не опрашивает backend бесконечно;
- workspace isolation действует на каждом новом endpoint;
- admin-only actions проверяются сервером, а не только скрываются в UI;
- один и тот же run snapshot не меняется от последующих изменений каталога;
- production readiness не объявляется по результатам одного локального run.

## 9. Что не является Definition of Done

Не считать сдачей:

- только green backend tests;
- только green Flutter tests;
- только health endpoints;
- только 300–500 discovery records;
- только импорт каталога;
- только красивую страницу рекомендаций;
- только наличие API;
- только сгенерированный CSV;
- только audit report;
- только локальный screenshot;
- только корректную миграцию;
- только approved brand draft;
- только parser output;
- только synthetic E2E.

---

# ЧАСТЬ V. МОДЕЛЬ ИСПОЛНЕНИЯ

## 10. Порядок и зависимости work packages

Исполняй work packages в следующем dependency order:

| WP | Название | Зависит от | Можно параллельно |
|---|---|---|---|
| WP-0 | Preflight и доказательный baseline | — | только чтение |
| WP-1 | Единая source/runtime/DB provenance | WP-0 | owner decisions |
| WP-2 | Stale-run reconciliation | WP-0 | WP-1 после анализа |
| WP-3 | Offline policy replay | WP-1 | owner decisions |
| WP-4 | Owner decision package | WP-0 | WP-1, WP-2, WP-3 |
| WP-5 | Стратифицированная выборка | WP-1, WP-2 | WP-4 |
| WP-6 | Bounded pricing run scope | WP-0 | WP-3, WP-4 |
| WP-7 | Run orchestration hardening | WP-6 | WP-5 |
| WP-8 | Pricing run UI | WP-6, WP-7 | import UI |
| WP-9 | XLSX import UI | WP-0 | WP-6, WP-8 |
| WP-10 | Recommendation review/export | WP-6 | WP-8, WP-9 |
| WP-11 | F2-0008 SQL pagination | identity graph stable | WP-5, WP-8 |
| WP-12 | F2-0006 chunked store sync | WP-0 | большинство UI WP |
| WP-13 | UI/accessibility/localization defects | UI contracts stable | backend WP |
| WP-14 | Variational verification | каждый WP | постоянно |
| WP-15 | Реальный KEMP pilot | WP-3–WP-14 P0 | — |
| WP-16 | Release/handoff | WP-15 | — |

Не жди завершения owner decision package, чтобы:

- стабилизировать runtime;
- сделать backup/migration rehearsal;
- реализовать bounded scope;
- исправить performance;
- реализовать UI;
- подготовить replay;
- подготовить sampling manifest.

Но не переводи неутверждённые tiers в automatic pricing.

## 11. Приоритеты до дедлайна

### P0 — обязательно до сдачи

- единая воспроизводимая runtime provenance;
- source/DB head sync;
- stale-run reconciler;
- offline replay текущих evidence;
- 300-позиционный стратифицированный прогон;
- bounded pricing scope и preview;
- безопасный start/progress/cancel;
- import UI с sheet selection и rejected rows;
- recommendation decision flow;
- корректный server-side CSV export;
- исправление F2-0008;
- устранение десяти красных UI tests на обязательном пути;
- один реальный KEMP pilot;
- вариативная проверка;
- честный handoff.

### P1 — делать, если P0 стабилен

- расширение выборки до 500;
- chunked/checkpointed store sync F2-0006;
- XLSX export;
- structured backend error codes;
- correlation IDs;
- расширенная localization sweep;
- более глубокая two-workspace endpoint matrix;
- policy impact preview UI.

### P2 — после MVP

- Policy Center;
- incremental monitoring;
- экономическая приоритизация;
- feedback analytics;
- Prom write-back;
- Fitment Intelligence expansion;
- SaaS onboarding/billing.

Если дедлайн сжимается, режь P1/P2, а не доказательный end-to-end P0.

## 12. Рекомендуемый календарный cutline на 12–13 рабочих дней

Календарь является dependency-aware ориентиром, а не разрешением пропускать
acceptance gates.

| День | Основной результат | Параллельный поток |
|---|---|---|
| 1 | WP-0 baseline, карта чужих/своих изменений | начать WP-4 decision package |
| 2 | backup, migration rehearsal, единая provenance | анализ stale runs |
| 3 | WP-1 завершён, WP-2 reconciler | WP-3 replay design |
| 4 | offline replay и diff старой/новой policy | bounded scope API design |
| 5 | WP-6 preview/scope/idempotency backend | 25–50 item discovery canary |
| 6 | WP-7 checkpoints/cancel/progress | Wave A после успешного canary |
| 7 | WP-8 run UI | WP-9 import inspect/preview |
| 8 | WP-9 import confirmation/rejections | WP-11 SQL baseline/shadow reader |
| 9 | WP-10 decision/export | WP-11 performance/migration |
| 10 | WP-13 красные UI tests и обязательная localization | P1 WP-12, если P0 стабилен |
| 11 | WP-14 fault/mutation/migration/full suites | расширение Wave A до 300 |
| 12 | WP-15 реальный KEMP pilot | исправление только pilot blockers |
| 13 | повторный pilot/replay, runbook, WP-16 handoff | резерв дедлайна |

Правила календаря:

- не запускай две конкурирующие schema migrations одновременно;
- не меняй shared identity files параллельно без согласованной ownership;
- long-running discovery запускай только после canary и в фоне;
- пока discovery идёт, работай над UI/performance в непересекающихся файлах;
- не переноси незавершённый P0 ради косметического P1;
- если owner answer задерживается, оставляй safe `UNKNOWN/REFERENCE_ONLY` и
  продолжай независимую реализацию;
- последний рабочий день не должен быть первым днём реального pilot.

---

# ЧАСТЬ VI. ПОШАГОВАЯ РЕАЛИЗАЦИЯ

## WP-0. Preflight и доказательный baseline

### Цель

Определить фактическое состояние, не меняя проект.

### Шаги

1. Разреши реальный repo root:

```bash
pwd
ls -lb
find . -maxdepth 3 -type d -name .git -print
```

2. Прочитай полностью:

```text
AGENTS.md
frontend/AGENTS.md
README.md
backend/README.md
```

3. Зафиксируй Git facts:

```bash
git status --short --branch
git log -10 --oneline --decorate
git diff --stat
git diff --name-status
git ls-files --others --exclude-standard
```

4. Определи, какие изменения принадлежат текущей/другой сессии.

5. Проверь source schema:

```bash
cd backend
PYTHONPATH=src .venv/bin/python -m alembic -c alembic.ini heads
PYTHONPATH=src .venv/bin/python -m alembic -c alembic.ini check
```

6. Проверь runtime:

```bash
docker compose ps
docker inspect <api-container>
docker inspect <worker-containers>
curl -fsS http://localhost:8000/api/v1/health/schema-revision
curl -fsS http://localhost:8000/api/v1/health/ready
```

7. Для каждого container сохрани:

```text
container name
image ID
image digest, если доступен
created_at
compose project working_dir
compose config files
service name
health
source commit/build label, если доступен
```

8. Выполни read-only DB snapshot одной транзакцией либо с одним timestamp:

```sql
SELECT now();
SELECT version_num FROM alembic_version;
SELECT count(*) FROM catalog_items;
SELECT count(*) FROM listings;
SELECT count(*) FROM catalog_discovery_runs;
SELECT count(DISTINCT product_key) FROM catalog_discovery_runs;
SELECT count(*) FROM catalog_discovery_offers;
SELECT selection_status, selection_reason, count(*)
FROM catalog_discovery_offers
GROUP BY selection_status, selection_reason
ORDER BY count(*) DESC;
SELECT status, count(*) FROM pricing_runs GROUP BY status;
SELECT count(*) FROM pricing_recommendations;
SELECT count(*) FROM recommendation_decisions;
SELECT count(*) FROM brand_tier_rules;
SELECT count(*) FROM tier_coefficients;
SELECT count(*) FROM pricing_policies;
```

9. Зафиксируй baseline tests, не исправляя ничего:

```bash
cd backend
PYTHONPATH=src .venv/bin/python -m pytest -q

cd ../frontend
dart analyze
flutter test
```

10. Если `flutter analyze` падает из-за U+00A0/LSP, используй `dart analyze`.
    Не объявляй analyzer clean, если команда не выполнялась.

11. Проверь permission gate:

```text
PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT
PROM_MARKETPLACE_SOURCE_ACCESS_REFERENCE
```

Не выводи секреты.

### Артефакт

Создай краткий timestamped baseline artifact без customer payload:

```text
.artifacts/mvp-improvement-20260730/baseline/
```

Минимально:

```text
git.txt
runtime.json
schema.txt
db_counts.json
tests.txt
known_conflicts.md
```

Не коммить artifact, если он содержит локальные или клиентские данные.

### Acceptance

WP-0 завершён, если каждое baseline-утверждение имеет:

- команду;
- timestamp;
- exit code;
- результат;
- пометку `verified`, `not verified` или `blocked`.

---

## WP-1. Единая воспроизводимая source/runtime/DB provenance

### Цель

Исключить смешанное состояние, в котором source, runtime и DB относятся к
разным версиям.

### Шаги

1. Не пересобирай контейнеры, пока не выяснено состояние параллельного
   `IDENTITY-WP-6`.

2. Согласуй единственный source tree для сборки.

3. Перед миграцией выполни backup:

```bash
scripts/backup_postgres.sh
```

или эквивалентный `pg_dump`.

4. Проверь backup:

```bash
pg_restore --list <dump>
```

5. Проведи migration rehearsal на одноразовой БД:

```text
upgrade head
downgrade -1
upgrade head
alembic check
```

6. Пересобери из одного checkout:

```bash
docker compose up -d --build \
  db broker migrate api worker store-sync-worker \
  pricing-worker scheduler frontend
```

7. Перепроверь container provenance.

8. Проверь:

```text
source head == image code head == database revision
```

9. Если health endpoint не показывает build provenance, добавь безопасные
   поля либо отдельный admin/operational endpoint:

```json
{
  "commit_sha": "...",
  "image_id": "...",
  "build_timestamp": "...",
  "code_schema_head": "...",
  "database_revision": "...",
  "policy_config_sha256": "...",
  "brand_rules_sha256": "...",
  "parser_version": "..."
}
```

Не раскрывай:

- secrets;
- filesystem paths production-host;
- permission tokens;
- customer filenames;
- raw policy contents.

10. Добавь tests, доказывающие:

- mismatch даёт unhealthy/not-ready;
- same DB/source schema, но другой build SHA видим как другая сборка;
- отсутствующие optional metadata не открывают endpoint анонимно;
- production endpoint не раскрывает секреты.

### Acceptance

- runtime собран из одного source tree;
- image provenance наблюдаема;
- source/image/DB schema согласованы;
- backup проверен;
- migration upgrade/downgrade/upgrade доказан;
- старые контейнеры не маскируют новый source.

---

## WP-2. Stale-run reconciliation

### Цель

Ни один `running` run не должен оставаться бесконечно активным без живой
lease/task ownership.

### Шаги

1. Инвентаризируй state machines:

```text
catalog_discovery_runs
pricing_runs
pricing_run_items
sync_runs
scrape targets/jobs
Celery tasks
leases/outbox
```

2. Не добавляй новую state machine, пока не найден существующий reconciler.

3. Для каждого типа run зафиксируй инвариант:

```text
terminal
OR
active task with valid lease/heartbeat
OR
eligible for bounded recovery
```

4. Определи stale condition через существующие lease/deadline значения.
   Не выбирай произвольный timeout, если contract уже существует.

5. Реализуй idempotent reconciler:

- выбирает bounded batch;
- блокирует строки безопасно;
- проверяет lease/task ownership;
- не завершает живую задачу;
- переводит необратимо потерянную задачу в честный terminal status;
- либо повторно ставит recovery task в рамках attempt budget;
- сохраняет machine-readable reason code;
- сохраняет human-readable detail;
- пишет audit event;
- не удаляет evidence.

6. Для diagnostic probe не применяй бизнес-логику, если это явно тестовый run;
   но он всё равно не должен навечно оставаться `running`.

7. Добавь scheduled invocation и operational metrics:

```text
stale_detected_total
stale_recovered_total
stale_failed_total
reconcile_errors_total
oldest_active_run_age_seconds
```

8. Добавь fault-injection tests:

- worker dies before first request;
- worker dies after evidence persisted;
- lease expires;
- duplicate reconciler execution;
- two reconcilers race;
- task is alive but slow;
- DB commit succeeds, broker acknowledgement fails;
- cancellation races with recovery.

### Acceptance

- три ранее зависших run получают объяснимое состояние;
- повторный reconciler не создаёт duplicate work;
- живой run не завершается ошибочно;
- evidence остаётся;
- состояние наблюдаемо в API/UI.

---

## WP-3. Versioned offline policy replay

### Цель

Доказать действие текущих category/identity/tier gates на уже сохранённых
данных до нового live-сбора.

### Главный инвариант

Старый результат нельзя молча переписать новым.

Должна сохраняться связь:

```text
source capture
→ parser version
→ source observation
→ old selection policy/result
→ new replay policy/result
→ diff
```

### Шаги

1. Найди существующий replay/evidence abstraction.

2. Определи, хватает ли для deterministic replay:

- raw captures;
- `raw_snapshot`;
- normalized fields;
- seller identity;
- category path;
- current KEMP identity;
- selection config hash.

3. Если входных данных недостаточно, не выдумывай их. Создай отчёт о
   недостающих полях и replay только для доказуемой части.

4. Выбери минимальную backward-compatible persistence model:

Предпочтительно одно из:

```text
A. новый replay run, связанный с source run;
B. append-only selection decision revisions;
C. отдельный measurement artifact, если persistence пока рискованна.
```

Не обновляй исторические rows in place, если это уничтожает lineage.

5. Каждый replay должен фиксировать:

```text
source run IDs
source capture hashes
parser version
selection method version
comparability config SHA-256
brand rules dataset ID/SHA-256
identity graph version/SHA-256
code/build SHA
started_at/completed_at
counts by status/reason
per-product-key counts
```

6. Пересчитай сохранённые `8 563` offers.

7. Сравни:

```text
persisted old:
  PRICING_EVIDENCE = 39
  TIER_UNKNOWN = 2 163

expected after category fix:
  PRICING_EVIDENCE = 24
  TIER_UNKNOWN = 1 489
```

8. Не требуй совпадения только потому, что числа указаны в prompt. Если не
   совпало:

- покажи exact diff по reason code;
- покажи product keys;
- покажи config hashes;
- проверь, не изменился identity graph;
- проверь stale image/config;
- проверь policy version;
- объясни расхождение.

9. Отдельно покажи per-SKU coverage:

```text
product keys with 0 evidence
product keys with 1 seller group
product keys with 2 seller groups
product keys with 3+ seller groups
```

10. Проверь известный Zelmer regression:

```text
OE norm 863130
false meat-grinder screw candidates
expected: not admitted to pricing evidence
```

11. Сохрани positive category regression examples, которые обязаны проходить.

### Variations

Replay должен быть одинаков при:

- другом порядке входных rows;
- другом размере batch;
- повторном запуске;
- одном и нескольких worker;
- restart между batches;
- изменённом locale;
- одинаковом config content по другому filesystem path.

### Acceptance

- 0 network requests;
- исходные captures не изменены;
- результат versioned;
- diff воспроизводим;
- per-SKU, per-reason и per-policy metrics сохранены;
- Zelmer false positive не проходит;
- positive category examples проходят.

---

## WP-4. Owner decision package

### Цель

Сделать доменные блокеры быстрыми для решения, не принимать решение за
владельца.

### Подготовь один компактный review package

Обязательные группы:

1. топ-25 brand tiers;
2. moto scope;
3. no-brand/placeholder policy;
4. допустимые export fields;
5. p95 SLO;
6. false-positive/false-negative preference;
7. tier premium bounds;
8. cost privacy;
9. automatic action boundary;
10. primary store identity.

### Для каждого решения покажи

```text
decision_id
plain-language question
available options
recommended safe default
offers/SKU affected
expected evidence-yield change
false-accept risk
rollback
current approved_by_owner state
owner answer
owner/date/reference
```

### Brand tier impact preview

Для каждого бренда:

```text
brand
normalized brand
offer count
distinct product keys
distinct sellers
current status
proposed tier
evidence basis
example URLs/offer IDs
impact if approved
impact if kept UNKNOWN
conflicts with article_brand_kinds
approved_by_owner=false
```

Не переноси автоматически значение из `article_brand_kinds.yaml` в
`brands.yaml`: это разные словари с разными ролями.

### No-brand policy

Отдельно покажи:

```text
missing brand
Aftermarket
Noname
Аналог
Без бренду
other placeholders
```

Не маскируй их brand tier. Без решения они остаются `UNKNOWN/REFERENCE_ONLY`.

### Acceptance

- владелец может принять решения без чтения исходников;
- каждое решение versioned;
- неутверждённые строки остаются false;
- impact измерен, а не придуман;
- техническая работа не блокируется там, где owner decision не нужен.

---

## WP-5. Стратифицированный discovery experiment на 300–500 позициях

### Цель

Получить representative-enough оценку полезности, а не просто увеличить число
офферов.

### 5.1. Sampling frame

Построй census всех `4 647` catalog items и признаки:

```text
catalog_item_id
source_row
category/path
OE present
OE confirmed
identity status
brand present
brand approved
article/brand kind
availability
stock status, если надёжен
price band
store/listing coverage
prior discovery exists
```

### 5.2. Страты

Минимум:

- category;
- confirmed OE / candidate OE / no OE;
- approved brand / unknown brand / no brand;
- identity status;
- existing discovery / no discovery.

Если stock status достоверен, добавь:

- fast-moving;
- ordinary;
- stale;
- dead/clearance only if contract distinguishes it.

Не смешивай `stale` и `dead` без проверки текущего pricing contract.

### 5.3. Размер

Запускай двумя волнами:

```text
Wave A: n = 300
Wave B: дополнение до n = 500 после анализа Wave A
```

При простой случайной оценке долей внутри каталога порядка `N=4 647`:

```text
worst-case 95% margin, n=300 ≈ ±5.5 pp
worst-case 95% margin, n=500 ≈ ±4.1 pp
```

Для weighted stratified estimate сохраняй sampling weights.

### 5.4. Reproducibility

Sampling manifest обязан содержать:

```json
{
  "schema_version": "...",
  "catalog_snapshot_id": "...",
  "catalog_content_sha256": "...",
  "sampling_method": "stratified",
  "seed": 0,
  "strata": [],
  "selected_catalog_item_ids": [],
  "weights": {},
  "generated_at": "...",
  "code_sha": "..."
}
```

Один и тот же manifest всегда выбирает те же items.

### 5.5. Request/time budget

Перед запуском вычисли:

```text
R_est = items × queries_per_item × pages_per_query × retry_amplification

T_lower = R_est × global_min_interval

T_expected =
  max(
    global_pacing_lower_bound,
    network_and_processing_model
  )
```

Стартовая наблюдавшаяся оценка:

```text
queries/pages combined ≈ 9.4 requests per item
global min interval = 2 seconds

n=300:
  R ≈ 2 820
  lower bound ≈ 5 640 sec ≈ 94 min

n=500:
  R ≈ 4 700
  lower bound ≈ 9 400 sec ≈ 157 min

n=4 647:
  R ≈ 43 682
  lower bound > 24 h
```

Пересчитай по текущей конфигурации и фактическим request counts.

### 5.6. Execution

- проверь permission artifact;
- проверь runtime provenance;
- проверь reconciler;
- зафиксируй config hashes;
- используй checkpoints;
- не удаляй run после ошибки;
- не отключай pacing;
- не запускай 4 647 сразу;
- сначала 25–50 canary items;
- сравни canary с budget;
- затем продолжи Wave A.

### 5.7. Metrics

Считай минимум:

```text
raw offers
exact OE matched offers
owned/related excluded
used excluded
category excluded
variant/side/pack excluded
brand mismatch
tier unknown
pricing evidence
distinct seller groups
SKU with 0/1/2/3+ seller groups
SKU with recommendation
SKU with abstention
manual review rate
request count
retry amplification
rate limited rate
latency
evidence yield by stratum
```

Главные метрики — per-SKU, а не только per-offer.

### 5.8. Manual truth sample

Сформируй blinded/stratified review sample admitted evidence.

Используй правило трёх:

```text
0 critical false accepts among n reviewed
≈ upper 95% false-accept bound 3/n
```

Примеры:

```text
n=100, zero errors → upper bound about 3%
n=300, zero errors → upper bound about 1%
```

Не пиши «precision 100%», если sample просто не нашёл ошибок.

### Acceptance

- минимум 300 items;
- sampling manifest воспроизводим;
- request/time budget сравнён с фактом;
- funnel посчитан per-offer и per-SKU;
- admitted evidence имеет human review sample;
- отклонения от первоначальных 37 items объяснены;
- run не создаёт потерянные либо вечные состояния.

---

## WP-6. Bounded pricing run scope и preview

### Проблема

На snapshot `PricingRunCreateRequest` принимал только:

```json
{
  "import_batch_id": "uuid",
  "policy": {}
}
```

А `create_pricing_run` выбирал все доступные items import batch. Кнопка запуска
могла немедленно поставить в обработку все `4 647` items.

### Цель

Ни один pricing run не стартует без:

- явного immutable scope;
- preview;
- оценки стоимости;
- idempotency;
- сохранённого manifest hash.

### 6.1. Сначала исследуй существующую модель

Проверь:

```text
PricingRun
PricingRunItem
CatalogImportBatch
CatalogItem
ScrapeTarget
outbox/task dispatch
active-run uniqueness
policy snapshots
existing E2E contracts
```

Не создавай новую таблицу, если `PricingRunItem` уже является достаточным
immutable membership snapshot. При этом scope definition и manifest hash всё
равно должны быть сохранены.

### 6.2. API contract

Спроектируй backward-compatible contract.

Рекомендуемая форма:

```json
{
  "import_batch_id": "uuid",
  "scope": {
    "kind": "catalog_item_ids",
    "catalog_item_ids": ["uuid"],
    "sampling_manifest_sha256": "64-hex"
  },
  "preview_token": "opaque-token",
  "idempotency_key": "client-generated-uuid",
  "policy": {}
}
```

Если в проекте уже принят HTTP-header contract, используй
`Idempotency-Key` вместо дублирования ключа в body. Не создавай два
несогласованных idempotency-механизма.

Допустимые scope kinds для MVP:

```text
all
catalog_item_ids
saved_sample
```

`all`:

- только явный выбор;
- отдельное подтверждение;
- предупреждение;
- request/time preview;
- server-side hard safety checks.

Не добавляй сложный произвольный query DSL без необходимости.

### 6.3. Preview endpoint

Добавь либо расширь endpoint:

```text
POST /api/v1/pricing/runs/preview
```

Ответ:

```json
{
  "preview_token": "opaque",
  "expires_at": "...",
  "import_batch_id": "uuid",
  "scope_kind": "catalog_item_ids",
  "selected_item_count": 300,
  "available_item_count": 300,
  "excluded_item_count": 0,
  "estimated_queries": 900,
  "estimated_requests_lower": 900,
  "estimated_requests_upper": 3600,
  "estimated_duration_lower_seconds": 1800,
  "estimated_duration_upper_seconds": 10800,
  "permission_gate": "PERMITTED_LIMITED",
  "launch_allowed": true,
  "policy_ready_for_automatic_pricing": false,
  "blocking_reasons": [],
  "warning_reasons": [
    "UNAPPROVED_BRAND_TIERS_WILL_REMAIN_REFERENCE_ONLY"
  ],
  "catalog_snapshot_sha256": "...",
  "scope_manifest_sha256": "...",
  "policy_sha256": "..."
}
```

Числа должны вычисляться из текущего config/observations, а не быть
hard-coded.

### 6.4. TOCTOU protection

Start обязан проверить:

- preview не истёк;
- workspace тот же;
- user имеет admin role;
- import batch тот же;
- scope manifest hash тот же;
- catalog snapshot не изменился;
- permission gate всё ещё разрешает;
- policy hash тот же;
- items всё ещё существуют;
- active duplicate run не создан.

Если изменилось — вернуть structured conflict и потребовать новый preview.

### 6.5. Idempotency

Инвариант:

```text
same workspace
+ same idempotency key
+ same canonical request hash
→ same pricing run response

same workspace
+ same idempotency key
+ different canonical request hash
→ structured 409 conflict
```

Не создавай duplicate rows/tasks при:

- double click;
- client timeout и retry;
- API restart после DB commit;
- broker retry;
- two concurrent requests.

Отдельно исправь существующую active-run дедупликацию, если она ищет только
`workspace_id + import_batch_id`. Два разных bounded scope не должны молча
получить один и тот же active run. Выбери и явно протестируй один contract:

```text
A. разрешить параллельные runs с разными scope manifest hashes;
B. разрешить один active run на workspace и возвращать честный 409;
C. поставить второй run в явную очередь.
```

Нельзя возвращать чужой по смыслу active run как будто это результат нового
запроса.

### 6.6. Persistence

Сохрани:

```text
scope_kind
scope_definition
scope_manifest_sha256
catalog_snapshot_sha256
previewed_at
estimated_item_count
estimated_request bounds
estimated_duration bounds
idempotency key/hash
build SHA
policy/config hashes
permission verdict/reference
```

Не сохраняй секреты.

### 6.7. Tests

Обязательные:

- one item;
- 300 items;
- unknown item ID;
- item from another workspace;
- duplicate IDs;
- empty selection;
- all scope;
- changed import after preview;
- expired preview;
- changed policy;
- changed permission gate;
- duplicate idempotency request;
- same idempotency key with different scope;
- different scope while another run for the same import is active;
- concurrent duplicate requests;
- non-admin;
- cross-workspace preview token;
- item unavailable between preview/start;
- 4 647 scope requires explicit full-scope confirmation.

### Acceptance

- UI/API не могут случайно запустить весь batch;
- 300/500 cohort запускается воспроизводимо;
- membership immutable;
- preview соответствует start;
- duplicate click безопасен;
- scope виден в run details.

---

## WP-7. Pricing orchestration: checkpoints, cancel, progress, bounded recovery

### Цель

Pricing run является управляемой state machine, а не fire-and-forget Celery
задачей.

### 7.1. State model

Сначала прочитай текущие enum/check constraints. Не заменяй существующие
названия без миграционной причины.

Логически должны различаться:

```text
queued
running/collecting
classifying
calculating
cancelling
cancelled
partial
completed
failed
```

Если текущая модель агрегирует стадии иначе, API всё равно должен объяснять:

- текущую стадию;
- completed/total;
- failed/manual review;
- retrying;
- cancel requested;
- last progress timestamp;
- blocking error.

### 7.2. Checkpoints

Checkpoint должен позволить:

- не терять уже сохранённые items;
- не повторять успешные необратимые операции;
- продолжить после worker restart;
- ограничить повторные запросы;
- закончить run как partial с честным accounting.

### 7.3. Cancel

Cancel:

- admin-only;
- idempotent;
- требует confirmation в UI;
- быстро выставляет cancel request;
- worker проверяет cancellation между bounded units;
- не удаляет сохранённые evidence;
- не создаёт новые scrape targets после cancellation;
- terminal state достигается bounded time;
- UI показывает, что уже выполненная работа сохранена.

### 7.4. Progress

Progress accounting invariant:

```text
total_items =
  queued
  + active
  + completed
  + failed
  + cancelled/skipped
```

Сумма не должна уходить в отрицательные значения или превышать total.

### 7.5. Failure and retry

Различай:

```text
retryable transport failure
terminal parser outcome
permission denial
rate limit
schema change
domain abstention
internal error
cancel
deadline exceeded
```

### 7.6. Tests

- cancel before dispatch;
- cancel during collection;
- cancel after collection before pricing;
- cancel after completion;
- repeated cancel;
- worker crash;
- broker outage;
- DB outage;
- retry exhaustion;
- partial success;
- reconciler race;
- API restart;
- finalizer runs twice;
- progress counts invariant;
- task deadline;
- request budget exceeded.

### Acceptance

- run достигает terminal state;
- cancel работает;
- recovery bounded;
- partial result не теряется;
- progress truthful;
- error codes structured.

---

## WP-8. Admin pricing run UI

### Цель

Закрыть F2-0030 полноценным пользовательским сценарием.

### UI flow

```text
Recommendations
→ New pricing run
→ choose import batch
→ choose saved sample or selected items
→ preview
→ warnings/blockers
→ explicit confirm
→ run progress
→ cancel
→ completed summary
→ recommendations
```

### Обязательные элементы preview

- import filename/snapshot;
- selected item count;
- excluded count;
- estimated requests;
- estimated duration range;
- policy version;
- permission status;
- unapproved tier warning;
- full-catalog warning;
- source mode;
- confirmation.

### Polling

Запрещён бесконечный polling.

Используй:

```text
initial delay
exponential or bounded backoff
maximum interval
maximum attempts or overall deadline
terminal-state stop
route disposal stop
manual refresh after timeout
```

### Role enforcement

- UI скрывает admin action от non-admin;
- backend повторно проверяет admin;
- direct HTTP non-admin request получает отказ;
- workspace isolation tested.

### Accessibility

- minimum interactive target 44 logical pixels;
- keyboard navigation;
- focus visibility;
- semantic labels;
- large text;
- no color-only status;
- confirmation dialog reachable;
- responsive at 375/768/1440.

### Tests

- preview success;
- preview blocker;
- start;
- duplicate tap;
- cancel confirmation;
- cancel failure;
- polling terminal;
- polling timeout;
- widget disposed;
- 401/403;
- 409 stale preview;
- backend error;
- 375 width;
- text scale 2.0;
- ru/uk.

### Acceptance

`PricingApi.startRun` имеет достижимого UI caller, а status/cancel работают
через controller, не напрямую из widget.

---

## WP-9. XLSX import UI

### Цель

Закрыть F2-0029 без создания универсальной ETL-платформы.

### MVP scope

Поддержать:

- `.xlsx`;
- разрешённый `.xls`, только если существующий backend безопасно его читает;
- явный выбор листа;
- несколько versioned KEMP mapping profiles;
- ручную корректировку mapping;
- preview;
- confirmation;
- progress;
- rejected rows.

### API flow

Предпочтительно:

```text
POST /api/v1/catalog/imports/inspect
→ file hash, sheet names, headers, row estimates

POST /api/v1/catalog/imports/preview
→ chosen sheet, mapping, validation sample/counts

POST /api/v1/catalog/imports
→ confirmed preview token, idempotency

GET /api/v1/catalog/imports/{id}
→ status/progress

GET /api/v1/catalog/imports/{id}/rejections
→ paginated errors
```

Переиспользуй существующие endpoints, если они уже покрывают contract.

### Sheet selection

Нельзя:

- доверять active sheet;
- выбирать первый «похожий» лист;
- молча импортировать `Лист1` с 16 строками вместо `Export Products Sheet`;
- принимать неоднозначный workbook без UI выбора.

### Preview

Покажи:

```text
sheet name
detected headers
mapping
total rows
predicted accepted
predicted rejected
unknown columns
required columns missing
sample normalized values
collision counts
```

### Rejections

На текущем KEMP-файле ожидавшийся пример:

```text
253 NORMALIZED_OE_COLLISION
1 empty OE
```

Перепроверь. UI должен показывать:

- row number;
- original value;
- normalized value;
- reason code;
- human explanation;
- conflicting rows/keys, если разрешено;
- фильтр;
- pagination;
- безопасный export rejects.

### File safety

- file size limit;
- streaming/bounded memory;
- MIME/content check;
- ZIP bomb protection;
- worksheet dimension sanity;
- formula cells handled deterministically;
- no external link fetch;
- no macro execution;
- content SHA-256;
- duplicate import idempotency.

Canonical import request hash должен включать не только file content hash, но
и:

```text
selected sheet
column mapping
mapping profile/version
normalization contract version
```

Один workbook с разными листами или mapping не является одним и тем же
импортом.

### Tests/variations

- 1 sheet;
- 2 catalog-like sheets;
- active wrong sheet;
- missing required header;
- duplicate header;
- localized header;
- empty sheet;
- 16-row decoy;
- 4 901-row real-shape fixture;
- empty OE;
- normalization collision;
- very long cell;
- formula cell;
- corrupted XLSX;
- oversized workbook;
- duplicate upload;
- cross-workspace import ID;
- non-admin.

### Acceptance

Оператор видит честное `partial`, а не «успешно» при 254 rejections.

---

## WP-10. Recommendation review, decision и export

### Цель

Замкнуть пользовательский результат после pricing run.

### Recommendation page

Каждая recommendation должна показывать:

```text
catalog identity
current price
recommended price or abstention
currency/tick
confidence
confidence grade
independent seller group count
evidence count
owned excluded count
rejected count
reason codes
policy version
data timestamp/freshness
competitor URLs
evidence details
manual review reason
```

Не показывай owned-store listings как конкурентов.

### Decision flow

Поддержать:

```text
accept
accept_with_modified_price
reject
defer
request_additional_research
```

Если текущий contract также поддерживает compatibility/seller decisions,
сохрани их отдельно.

Для override/reject:

- reason обязателен;
- actor;
- timestamp;
- old/new value;
- recommendation version;
- optimistic concurrency либо equivalent protection.

### Export

Сначала реализуй server-side CSV.

Export обязан:

- использовать те же filters/sort, что и UI;
- фиксировать filter snapshot;
- быть workspace-scoped;
- требовать auth;
- быть audit logged;
- ограничивать rows/size;
- streaming response или background export для большого результата;
- включать evidence URLs и reason codes;
- включать generated_at и policy version;
- не включать скрытые поля.

### CSV injection

Защити значения, начинающиеся на:

```text
=
+
-
@
```

особенно:

- title;
- seller;
- reason;
- URL/display text;
- operator comment.

### Privacy

Пока владелец явно не утвердил, не экспортируй:

- cost;
- raw margin;
- encryption metadata;
- hidden seller identity;
- internal secrets;
- raw captures;
- PII;
- private notes другого workspace.

### Tests

- active filters preserved;
- sort preserved;
- pagination does not truncate export;
- same query gives same row set;
- cross-workspace denied;
- non-admin/user policy according to contract;
- CSV injection;
- Unicode ru/uk;
- commas/quotes/newlines;
- empty result;
- large result;
- deleted/changed recommendation;
- sensitive fields absent;
- audit event present.

### Acceptance

Сценарий:

```text
найти финансово значимые рекомендации
→ отфильтровать
→ отсортировать
→ проверить evidence
→ принять/отклонить
→ экспортировать
```

проходит полностью.

---

## WP-11. F2-0008 — SQL pagination и bounded catalog reads

### Цель

Каталог и поиск не материализуют весь workspace в Python.

### 11.1. Baseline

До правки:

- минимум 30 повторов после warm-up;
- p50/p95/p99;
- SQL query count;
- rows transferred;
- process memory delta;
- `EXPLAIN (ANALYZE, BUFFERS)`;
- representative list/search/filter/sort cases.

Сохрани dataset count и timestamp.

### 11.2. Identity dependency

Перед дизайном прочитай current identity graph:

```text
catalog identity links
canonical normalization
confirmed cross OEM union
source role
identity_status
```

Не создавай второй competing identity definition.

### 11.3. SQL design

Перенеси в PostgreSQL до network transfer:

- workspace filter;
- canonical identity;
- search predicate;
- grouping/dedup;
- sort;
- pagination;
- count.

Варианты, которые нужно сравнить:

1. expression indexes;
2. generated/stored normalized columns;
3. canonical identity/link table;
4. materialized read model.

Выбери минимальный вариант, согласованный с текущим
`IDENTITY-WP-6` identity graph, а не создающий второе определение identity.

### 11.4. Shadow comparison

Не переключай reader сразу.

Для representative query corpus:

```text
old_result_hash
new_result_hash
group membership diff
sort diff
total count diff
page boundary diff
```

Проверь:

- first/middle/last page;
- empty page;
- duplicate listings across stores;
- OE;
- article/SKU;
- listing name;
- mixed script;
- punctuation;
- leading zeros;
- workspace boundary.

### 11.5. Index/migration

- Alembic migration;
- upgrade;
- downgrade;
- upgrade;
- `alembic check`;
- query plan proves index use;
- no unintended unique constraint;
- index size recorded;
- write amplification acknowledged.

### 11.6. Performance acceptance

Engineering target из исходного задания:

```text
p95 interactive request ≤ 300 ms on actual volume
no Seq Scan over table >10 000 rows in interactive path,
unless query-specific evidence proves it is faster and bounded
```

Если владелец утверждает другой SLO, сохрани оба:

- engineering target;
- owner-approved product SLO.

Не объявляй success только потому, что стало быстрее.

### Acceptance

- bounded rows transferred;
- old/new semantics equivalent либо каждое отличие одобрено;
- p50/p95/p99 measured before/after;
- migration reversible;
- no cross-workspace leakage.

---

## WP-12. F2-0006 — chunked/checkpointed store synchronization

### Цель

Ни один workload, математически не помещающийся в hard timeout, не запускается
как одна неделимая задача.

### Модель

Перед dispatch:

```text
T_est =
  pages
  × attempts_per_page
  × effective_time_per_attempt
  / effective_parallelism
```

Учти global rate capacity:

```text
effective_parallelism не может ускорить работу выше global pacing capacity
```

### Реализация

- admission estimate;
- hard max chunk;
- continuation cursor/checkpoint;
- idempotent page persistence;
- partial progress;
- retry per chunk;
- bounded task deadline;
- finalizer;
- cancellation;
- terminal parser outcome;
- no loss of earlier valid pages if later page fails.

Если полноценный chunking не помещается до дедлайна:

1. поставь доказанный hard page cap;
2. покажи preview/предупреждение;
3. не разрешай unbounded mode;
4. оставь явный P1 blocker.

### Variations

- 1 page;
- exact chunk boundary;
- chunk+1;
- 346 historical-like pages;
- redirect after valid pages;
- repeated last page;
- network failure on last page;
- worker timeout;
- retry;
- duplicate task;
- cancel;
- changed catalog during continuation.

### Acceptance

- нет конфигурации `unbounded workload + guaranteed hard timeout`;
- partial pages не теряются;
- resume не дублирует listings;
- UI/status показывает incomplete/partial truthfully.

---

## WP-13. UI defects, accessibility и localization

### Цель

Исправить реальные красные тесты, не переписав их для зелёного результата.

### Обязательные дефекты

- `MarkoButton` interactive target минимум 44 pt;
- forbidden/error states имеют собственный текст;
- layout не ломается в обязательной variation matrix.

### Matrix

Главные поверхности:

```text
state: 6 representative states
width: 375 / 768 / 1440
text scale: 1.0 / 1.3 / 2.0
language: ru / uk
```

Для главного operator flow тестируй полный релевантный набор.

Для вторичных поверхностей допустим pairwise covering array, но явно укажи,
что тройные взаимодействия не покрыты.

### Localization

Приоритет:

1. import;
2. run preview/progress/cancel;
3. recommendation;
4. decision;
5. export;
6. errors/empty states.

Не запускай массовый автофикс 263 literals. Исправляй затронутые обязательные
пути и веди остаточный список.

### Tests

- semantics;
- keyboard;
- focus;
- large text;
- narrow width;
- loading/error/empty/partial/success/forbidden;
- ru/uk;
- long filename;
- long seller/title;
- long reason code translation;
- 254 rejection count;
- large numeric values.

### Acceptance

- десять исходных audit tests зелёные из-за исправленного production code;
- каждый тест действительно падает на старом дефекте;
- нет новых overflow/exceptions;
- analyzer clean.

---

# ЧАСТЬ VII. ВАРИАТИВНАЯ И ДОКАЗАТЕЛЬНАЯ ПРОВЕРКА

## WP-14. Обязательный verification protocol

Этот WP выполняется после каждого изменения, а не только в конце.

## 14.1. Defect proof

Для каждого исправленного дефекта:

1. добавь/найди test, воспроизводящий дефект;
2. прогони на старом коде — test должен упасть;
3. верни исправление;
4. test должен пройти;
5. прогони соседние tests;
6. зафиксируй команды и результаты.

Не удаляй чужие изменения для проверки. Используй:

- минимальный temporary patch;
- isolated worktree/clone;
- test double;
- mutation;
- локальный revert только собственного изменения с немедленным возвратом.

## 14.2. Variation dimensions

Каждый новый contract проверь по применимым измерениям:

| Измерение | Варианты |
|---|---|
| Workspace | current / other / missing |
| Role | admin / member / unauthenticated |
| Dataset | empty / 1 / boundary / realistic / large |
| Job state | queued / active / retrying / partial / terminal |
| Network | success / timeout / 429 / 3xx / malformed / unavailable |
| Broker | available / dispatch fail / duplicate delivery |
| Worker | success / crash / restart / late completion |
| DB | success / conflict / rollback / reconnect |
| UI width | 375 / 768 / 1440 |
| Text scale | 1.0 / 1.3 / 2.0 |
| Locale | ru / uk |
| Input order | original / shuffled / reversed |
| Concurrency | 1 / 2 / duplicate request |
| Replay | first / repeated / interrupted/resumed |
| Permission | allowed / denied / changed after preview |
| Policy | approved / unapproved / changed after preview |

## 14.3. Property/invariant tests

Применимо использовать property-based testing для:

- identifier normalization;
- selection manifest determinism;
- pagination without duplicates/gaps;
- progress accounting;
- CSV escaping;
- idempotency;
- replay equality under input permutation;
- pricing Decimal/tick invariants.

## 14.4. Mutation-oriented checks

Проверь, что tests ловят хотя бы следующие мутации:

- убрать workspace filter;
- убрать role check;
- отключить permission gate;
- принять expired preview;
- игнорировать manifest hash;
- заменить Decimal на float;
- снять category exclusion;
- допустить owned seller;
- убрать cancel check;
- сделать polling infinite;
- удалить CSV injection escape;
- поменять sort/page order;
- потерять rejection rows;
- считать partial import completed.

## 14.5. Migration verification

Для каждой миграции:

```text
upgrade head
schema/data assertions
downgrade -1
schema/data assertions
upgrade head
alembic check
```

Проверить:

- constraints;
- indexes;
- foreign keys;
- delete behavior;
- existing rows backfill;
- lock/duration risk;
- rollback.

## 14.6. Performance verification

- warm-up отдельно;
- n≥30;
- p50/p95/p99;
- same dataset;
- same query corpus;
- before/after;
- query plan;
- buffers;
- rows;
- timestamp;
- no competing background write contamination либо оно явно зафиксировано.

## 14.7. Full suites

После scoped checks:

```bash
cd backend
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m alembic -c alembic.ini check

cd ../frontend
dart format <только изменённые файлы>
dart analyze
flutter test
flutter build web --release \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=FIREBASE_API_KEY=AIza_REPLACE_ME \
  --dart-define=FIREBASE_AUTH_DOMAIN=YOUR_PROJECT_ID.firebaseapp.com \
  --dart-define=FIREBASE_PROJECT_ID=YOUR_PROJECT_ID \
  --dart-define=FIREBASE_MESSAGING_SENDER_ID=123456789012 \
  --dart-define=FIREBASE_WEB_APP_ID=1:123456789012:web:replace_me
```

Backend CI-equivalent:

```bash
docker compose --profile test run --rm --build backend-test
```

Не запускай:

```text
ruff format src
dart format lib test
dart fix --apply
```

на весь проект, если это создаёт несвязанный churn.

## 14.8. Security verification

Обязательно:

- workspace isolation;
- admin enforcement;
- no IDOR;
- export privacy;
- CSV injection;
- no secret logging;
- no raw cost leakage;
- safe file upload;
- permission gate;
- metrics auth;
- no customer data in artifacts/commit.

## 14.9. Честность результата

Разделяй:

```text
implementation works locally
representative correctness measured
operator usefulness confirmed
production deployment verified
production readiness proven
```

Это пять разных утверждений.

---

# ЧАСТЬ VIII. РЕАЛЬНЫЙ KEMP PILOT

## WP-15. Pilot на реальном каталоге

### Предусловия

- единая runtime provenance;
- DB at source head;
- permission allowed;
- stale-run reconciler;
- replay доказан;
- bounded scope;
- preview;
- run UI;
- import UI;
- recommendation UI;
- decision;
- export;
- P0 tests green;
- owner decisions применены только там, где утверждены.

### Pilot flow

1. Выполни свежий import через UI либо используй подтверждённый snapshot.
2. Покажи sheet selection.
3. Покажи `accepted/rejected`.
4. Выбери сохранённую Wave A cohort.
5. Выполни preview.
6. Сверь request/time estimate.
7. Запусти.
8. Наблюдай progress.
9. Проверь, что нет stale state.
10. После завершения посчитай funnel.
11. Сформируй manual truth sample.
12. Дай Юрию проверить recommendations.
13. Сохрани decisions/reasons.
14. Выполни export.
15. Выполни offline replay.
16. Сравни domain outputs.

### Pilot metrics

```text
items selected
items completed
items failed
items manual review
items with 0/1/2/3+ seller groups
items with recommendation
items abstained
recommendations accepted
recommendations modified
recommendations rejected
recommendations deferred
operator review time
request count
actual duration
retry/rate-limit/error rates
owned seller false accepts
category false accepts
identity false accepts
evidence freshness
export row count
replay mismatch count
```

### Decision branches

#### Branch A: достаточно корректных рекомендаций

Развивай:

- incremental refresh;
- scheduled review queues;
- financial prioritization;
- policy center.

#### Branch B: coverage умеренный, но high-confidence subset полезен

Позиционируй MVP как:

```text
радар высокоуверенных ценовых возможностей
```

Не заставляй систему рекомендовать цену для всего каталога.

#### Branch C: exact-OE coverage недостаточен

Сначала локализуй:

- категории;
- бренды;
- identifier gaps;
- seller coverage;
- source limitations.

Только после измерения решай, оправдан ли:

- additional official data;
- confirmed cross references;
- selective Fitment Intelligence.

Не компенсируй низкий coverage:

- fuzzy OE;
- title similarity;
- LLM guesses;
- неутверждёнными tiers;
- ослаблением category gates.

### Acceptance

Pilot считается выполненным только после реального operator review. Agent
сам не заменяет Юрия в оценке бизнес-полезности.

---

# ЧАСТЬ IX. RELEASE И HANDOFF

## WP-16. Финальная стабилизация

### Шаги

1. Перечитай `git status`.
2. Раздели свои и чужие изменения.
3. Удали только собственные временные runtime artifacts.
4. Не удаляй customer/backup data; оставь их ignored.
5. Проверь secrets.
6. Проверь diff по каждому файлу.
7. Проверь отсутствие mass-format churn.
8. Прогони scoped + full suites.
9. Пересобери runtime из финального source.
10. Проверь schema/build/policy provenance.
11. Выполни smoke operator flow.
12. Проверь backup/restore documentation.
13. Обнови operator runbook.
14. Не push в remote без отдельного явного разрешения.

### Operator runbook обязан включать

- запуск/остановку stack;
- backup;
- restore;
- import;
- выбор листа;
- запуск bounded run;
- preview;
- cancel;
- stale-run recovery;
- recommendation review;
- export;
- проверку schema/build provenance;
- safe rollback;
- известные блокеры.

### Финальный отчёт

Пиши обычной прозой.

Структура:

```text
1. Что было фактически изменено
2. Какие дефекты закрыты
3. Какие файлы/миграции добавлены
4. Какие команды выполнены
5. Какие тесты прошли/упали
6. Before/after performance
7. Discovery/pilot metrics
8. Что подтвердил владелец
9. Что осталось unapproved
10. Что осталось сломанным
11. Что не проверялось
12. Можно ли считать operator MVP доказанным
13. Следующее одно конкретное действие
```

Не пиши «в целом успешно». Назови точный результат.

---

# ЧАСТЬ X. ПОСЛЕ MVP — НЕ РЕАЛИЗОВЫВАТЬ ДО P0

## 17. Policy Center

После успешного pilot:

```text
draft
→ measured impact preview
→ owner review
→ approved version
→ shadow activation
→ active
→ rollback
```

Version:

- brand tiers;
- category scope;
- premiums;
- thresholds;
- export policies;
- no-brand rules.

## 18. Incremental market monitoring

Не пересобирать весь рынок без необходимости.

Добавить:

- evidence TTL/freshness;
- changed-price detection;
- incremental queue;
- scheduled refresh;
- seller change detection;
- alert only above meaningful deadband;
- history and trend.

## 19. Экономическая приоритизация

Только после получения надёжных бизнес-данных:

```text
expected opportunity
= price delta
× expected sellable quantity
× confidence
× time horizon adjustment
```

Не выдумывать:

- quantity;
- velocity;
- conversion;
- margin;
- acceptance rate.

## 20. Feedback learning

Сначала:

- decision analytics;
- reason distribution;
- override delta;
- category/brand acceptance;
- false-accept review.

Любая learned policy:

- versioned;
- offline evaluated;
- shadow mode;
- owner-approved;
- rollbackable.

## 21. Prom write-back

Только после отдельного решения:

```text
recommendation
→ operator selection
→ batch preview
→ explicit approval
→ bounded write
→ verification
→ rollback/audit
```

Не превращать систему в silent auto-repricer.

## 22. Fitment Intelligence

Расширять только там, где pilot доказал measurable exact-OE ceiling.

Предпочитать:

- official/contracted sources;
- confirmed identity graph;
- human-reviewed cross links;
- source lineage.

LLM может извлекать кандидатов из текста, но не является окончательным
доказательством совместимости.

## 23. SaaS layer

Начинать только после доказанной KEMP-полезности:

- onboarding;
- tenant policies;
- role model;
- usage/cost accounting;
- billing;
- support;
- retention;
- export/privacy contracts.

---

# ЧАСТЬ XI. ЗАПРЕЩЁННЫЕ ЛОЖНЫЕ СОКРАЩЕНИЯ

## 24. Не делать

Не делай следующие «быстрые решения»:

1. запуск всего каталога без preview;
2. выбор active XLSX sheet;
3. запись 254 rejected rows как completed success;
4. автоматическое одобрение top-25 tiers;
5. классификация no-brand как aftermarket tier;
6. удаление stale runs;
7. перезапись historical evidence;
8. пересчёт без config hashes;
9. UI-only role restriction;
10. infinite polling;
11. client-side export только текущей страницы;
12. export sensitive fields;
13. in-memory filtering 49 100 listings;
14. unbounded store pagination;
15. disabling rate limit;
16. direct OEM/KEMP price comparison без tier normalization;
17. fuzzy OE;
18. leading-zero removal;
19. partial-number matching;
20. allowlist, которая срезает реальные авто-категории;
21. дальнейший kemp.ua harvest без нового доказанного прироста;
22. переписывание parser;
23. новый `pricing_engine_v2`;
24. массовый formatting/autofix;
25. объявление production readiness по локальным тестам;
26. реализацию всех 53 findings вместо критического user flow;
27. скрытие rejected/parser-found offers из inspectable UI;
28. допуск rejected offers в pricing;
29. смешение KEMP owned stores с competitors;
30. push без разрешения.

---

# ЧАСТЬ XII. ФИНАЛЬНЫЙ SELF-AUDIT АГЕНТА

## 25. Перед завершением ответь на вопросы

### Product truth

- Прошёл ли реальный оператор полный цикл?
- Был ли хотя бы один pricing run?
- Появились ли реальные recommendations?
- Сохранились ли operator decisions?
- Экспортировал ли UI ту же выборку, которую видел оператор?
- Полезность подтвердил владелец или только агент?

### Data truth

- Сколько SKU, а не offers, получили evidence?
- Сколько имеют 0/1/2/3+ seller groups?
- Какова manual-review доля?
- Как измерена precision?
- Какие false accepts найдены?
- Какие strata недопредставлены?

### Reproducibility

- Source, image и DB относятся к одной версии?
- Сохранены hashes?
- Replay использовал 0 network requests?
- Повторный replay совпал?
- Sampling manifest детерминирован?

### Safety

- Owned sellers исключены?
- Workspace isolation проверена?
- Permission gate включён?
- Pacing включён?
- Customer data не попали в Git?
- Export не содержит sensitive fields?
- CSV injection закрыта?

### Reliability

- Нет вечных running states?
- Cancel bounded?
- Duplicate click idempotent?
- Worker crash восстанавливается?
- Partial evidence сохраняется?
- Full-catalog accidental run невозможен?

### Performance

- p50/p95/p99 измерены before/after?
- `EXPLAIN (ANALYZE, BUFFERS)` сохранён?
- Нет full-workspace Python materialization?
- Query semantics не изменились молча?

### Verification

- Каждый regression test падает на старом дефекте?
- Выполнены variations?
- Миграции прошли upgrade/downgrade/upgrade?
- Backend full suite прошёл?
- Docker CI-equivalent прошёл?
- Dart analyze прошёл?
- Flutter tests прошли?
- Web build прошёл?

### Honesty

- Не перепутана ли локальная работоспособность с production readiness?
- Не выдан ли unapproved tier за domain truth?
- Не выдан ли offer count за SKU coverage?
- Не выдан ли parser candidate за pricing evidence?
- Не выдан ли audit artifact за реализацию?

Если на критический вопрос ответ «нет», не скрывай его. Исправь, если это
внутри scope; иначе назови точный blocker и владельца решения.

---

# ЧАСТЬ XIII. КОМАНДА НА СТАРТ

Начни с WP-0.

Не пиши новый общий план вместо работы. После короткого baseline:

1. устрани смешанную runtime provenance;
2. приведи source/image/DB к одной версии;
3. внедри stale-run reconciliation;
4. выполни versioned offline replay;
5. параллельно подготовь owner decision package;
6. реализуй bounded pricing scope;
7. запусти canary и затем 300-item experiment;
8. заверши operator UI;
9. закрой performance/reliability P0;
10. проведи variational verification;
11. проведи реальный KEMP pilot;
12. дай честный handoff.

Не останавливайся после аудита. Не упрощай задачу. Не ослабляй доказательные
границы ради более красивых метрик. Итоговая ценность проекта определяется
тем, может ли Юрий получить корректное, объяснимое и практически полезное
решение на своих реальных Prom.ua объявлениях.
