# Full Project Audit — Marko / Metis — 2026-07-18

- audit_run_id: `AUDIT-20260718-115504-LOCAL`
- prompt: `PROMPT_15_014` revision `2.0.0`, execution_mode `AUDIT_ONLY`
- repository snapshot: путь-ориентированный (Git отсутствует), физический корень
  `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`,
  fingerprint замороженного снапшота `216c24b825ba481e7092d0b008e0c4a64501f72d7cf4b52005f01fcdeb6c71b8`
  (заморожен 2026-07-18T12:08:15+02:00 после обнаружения конкурентной модификации)
- artifacts (этот run): `docs/FULL_PROJECT_AUDIT_2026-07-18.md`,
  `docs/FULL_PROJECT_AUDIT_CLAIM_LEDGER_2026-07-18.yaml`,
  `docs/FULL_PROJECT_AUDIT_GAP_REGISTER_2026-07-18.yaml`,
  `docs/FULL_PROJECT_AUDIT_SCOPE_INVENTORY_2026-07-18.yaml`,
  `docs/FULL_PROJECT_AUDIT_VALIDATION_MANIFEST_2026-07-18.yaml`
- generated_at: 2026-07-18T12:40:00+02:00

## 1. Executive Verdict

- `AUDIT_REPORT_GATE` (эта стадия): **BLOCKED**. Причина внешняя: у рабочей
  копии нет системы контроля версий, и во время аудита (12:04–12:08) другой
  процесс (исполнение `PROMPT_15_015`) переписывал `backend/src/metis/pricing/*`.
  В 12:07 дерево транзиентно содержало неопределённое имя (F821), замороженный в
  12:08 снапшот воспроизводимо падает на одном тесте. Аудит «всей кодовой базы по
  одному снапшоту» в таких условиях недостижим честно; покрытие глубокого
  ревью замороженного снапшота — 171 из 246 first-party файлов (69.5%),
  критический слой — 91 из 96 (94.8%).
- `PRODUCTION_CANDIDATE_GATE`: **NOT PASSED** (нет ни одного E4-доказательства).
- `PRODUCTION_READY_PROVEN`: **false** (E5-доказательств нет вообще).
- Сильнейший проверенный результат: до-дрейфовое состояние S1 проходит 415/415
  backend-тестов, полную offline-генерацию SQL миграций в обе стороны, паритет
  31 таблицы модель↔миграции, 21/21 Flutter-тестов, чистый `dart analyze`;
  governance-валидаторы принимают оба примерных манифеста.
- Слабейшая критическая область: воспроизводимость снапшота (нет VCS +
  конкурентная запись) — оценка 10/100 при E3-доказательствах самого дрейфа.
- Best next action (не запуск implementation): инициализировать Git с базовым
  коммитом, остановить/сериализовать конкурентные agent-запуски и возобновить
  аудит на замороженном снапшоте.

Ответ на главный вопрос «что не готово / что доделать / что улучшить» — кратко:
система является добротно спроектированным integrated internal tool с сильной
статикой и юнит-доказательствами (E3-потолок), но: (1) нет ни одного
исполняемого доказательства работы с реальной PostgreSQL/Redis (вся тестовая
пирамида без БД); (2) live-сбор конкурентов закрыт fail-closed вердиктом до
бизнес/юридического решения; (3) runbook-префлайты (бенчмарк, restore-drill,
replay) никогда не исполнялись; (4) нет CI; (5) репозиторий без VCS с
конкурентными записями — процессный P0.

## 2. Audit Scope, Method and Completeness

Invocation policy соблюдена: без внешней сети, без live-запросов, без установки
зависимостей, без изменений продуктового кода. Фазы: identity → inventory →
static review → flow/invariants → safe executable validation → synthesis →
hostile review. Точные знаменатели (см. scope inventory):

| metric | numerator | denominator | unrounded |
|---|---:|---:|---|
| inventory_coverage | 372 | 372 | 1.0 |
| first_party_review_coverage | 171 | 246 | 0.695122 |
| critical_review_coverage | 91 | 96 | 0.947917 |
| weighted_review_coverage | — | — | 0.734104 |

Не прочитаны построчно (disposition `NOT_READ_BLOCKER`): большинство
backend-тестов (исполнены, структурно проверены), ~26 Flutter-страниц/моделей,
крупные docs (metis.md, kemp_pricing_engine.md, scraper_scaling.md, прошлые
аудиты — проверены по заголовкам/вердиктам), 5 из 10 скриптов. Unclassified: 0.

## 3. Repository and Environment Identity

`NO_GIT`. Realpath совпадает с physical root (имя каталога содержит NBSP —
`marko — копия`). Runtime import identity проверена: `marko` и `metis`
резолвятся в аудируемый checkout (CMD-003). Дубликатов checkout не найдено;
соседний каталог `marko/` содержит только `docs/prompts`. Среда: macOS 26.4.1
arm64, Python venv 3.13.9, uv 0.11.25, Flutter 3.44.4; Docker `NOT_AVAILABLE`.
Критический инцидент: конкурентная модификация во время аудита (§1, CLAIM-004).

## 4. Product Architecture and End-to-End Flow

Архитектура соответствует заявленной: Flutter → Firebase JWT → FastAPI →
PostgreSQL; Redis/Celery c четырьмя очередями (`celery`, `store-sync`,
`pricing`, `pricing-calculation`); Metis-ядро (`metis.pricing`) — чистая
детерминированная функция; `marko.pricing` — подтверждённый re-export facade.
Все 14 рёбер канонического flow прослежены статически (trace 100%), ни одно не
верифицировано на E4 (verified 0%). Первый неверифицированный узел —
`AUTH_WORKSPACE` (ничего не исполнялось против реальной БД). Первый сломанный
переход (на снапшоте S2) — `METIS_PRICING_CALCULATION`: contract-регрессия
evaluate из-за in-flight comparability-гейта.

Инварианты (12 из промпта): статически подтверждены — tenant-scoping всех
запросов (объект+workspace в каждом репозитории/сервисе), fail-closed source
gate без обходов (API/CLI/worker/физическая попытка), immutable
content-addressed raw evidence с обязательностью для успеха, fenced
retry/redelivery без дубликатов (unique constraints + fencing tokens),
DB-уровневые направления RAISE/LOWER, abstention-пути, append-only решения
(app-уровень — см. GAP-P2-007), replay из pinned inputs (v2-контракт).
E4-подтверждений нет ни для одного.

## 5. Evidence Model and Claim Ledger Summary

16 материальных claims (2 UNKNOWN, 1 BUSINESS_DECISION_REQUIRED, 1 INFERENCE,
5 EXECUTION_RESULT, 7 FACT_FROM_REPO); material_claim_coverage = 1.0,
reproducible_claim_coverage = 1.0, reverse_trace = 1.0. Противоречий нет.
Особая пара: CLAIM-002 (S1 зелёный) и CLAIM-003 (S2 красный) — не противоречие,
а два состояния одного дерева, зафиксированные по времени.

## 6. Readiness Model

Канонические веса Section 16 (UNVALIDATED ENGINEERING ASSUMPTION), evidence
caps 0/25/50/75/90/100. Веса capability — инженерная нормализация r_i/Σr
(ASSUMPTION-CAPABILITY-WEIGHTS). Итоги (нижние границы, capped):

| system | weighted_readiness | interval | critical_floor | critical evidence floor |
|---|---:|---|---:|---|
| Metis | 57.42 | [57.42, 57.42] | 36.25 | E3 |
| Marko | 56.49 | [56.49, 56.49] | 50.00 | E2 |

project_decision_floor = min(57.42, 36.25, 56.49, 50.0, critical_path_floor) =
36.25 (тянет вниз in-flight comparability). Средние не скрывают пол: он
приведён отдельно.

## 7. What Is Ready

(готово = реализовано и доказано на достигнутом уровне E3; не production)

- Metis-ядро: чистый `recommend_price` c 11-инвариантным post-hoc enforcement,
  MANUAL_REVIEW/INSUFFICIENT_DATA abstention, детерминированный дедуп,
  IQR/MAD/Sn/Qn c точными Rousseeuw–Croux константами и finite-sample
  поправками (oracle-фикстура), winsor-чувствительность, LOO-защита от leakage
  в калибровке, dataset-hash pinning.
- Firebase-аутентификация: полная проверка RS256/aud/iss/claims/email_verified,
  гонко-безопасное создание пользователя/workspace; RBAC owner/admin/member.
- XLSX-ингест: zip-bomb-guard, лимиты, гомоглифы, локали чисел, построчные
  отказы, идемпотентный immutable snapshot.
- Evidence-цепочка скрейпера: SHA-256 content-addressed blobs, целостность при
  чтении/replay, «успех требует raw evidence», lease+fencing+outbox с
  детерминированным task-id, circuit breaker и глобальный Redis-pacing.
- Governance: исполняемые validators Section 15.1/16 (этот отчёт собран ими же).
- Deploy-референс: hardened production compose (read-only, non-root,
  no-new-privileges, loopback, лимиты), pinned образы, аккуратные
  backup/restore-скрипты, честный runbook.

## 8. What Is Partial or Only Code-Complete

- Весь DB-слой: PG-only SQL (advisory locks, ON CONFLICT, partial unique
  indexes) и миграции никогда не исполнялись против реальной PostgreSQL
  (offline SQL — E3-максимум).
- Celery/Redis-runtime: retry-лестницы, redelivery, барьер калибровки — только
  код+юниты на моках.
- Comparability-гейт (S2): реализован, интеграция не завершена, suite красный.
- Операторский UI: функционально полный (очереди, evidence, replay-кнопка,
  accept/override/reject, below-cost double-confirm), но e2e не проверялся.
- Observability: метрики/алерты есть, Prometheus-сбор и dashboards вне репо.

## 9. What Is Missing or Contradicted

- CONTRADICTED (S2): контракт evaluate — красный тест (GAP-P1-005).
- MISSING: VCS; CI; исполненные runbook-префлайты (бенчмарк/restore/replay);
  измеренная ёмкость; rate limiting; DB-уровневый append-only; официальный
  Prom-фид/интеграция `prom_owned_api` (enum есть, реализации нет).

## 10. P0/P1/P2/P3 Gap Register

Полные записи с интервалами — в
`docs/FULL_PROJECT_AUDIT_GAP_REGISTER_2026-07-18.yaml`. Сводка
(S/L/D/C — верхняя граница; RPN — интервал):

| gap | P | title | S·L·D·C | RPN | norm |
|---|---|---|---|---|---|
| GAP-P0-001 | P0 | No VCS + конкурентные записи в общий worktree | 5·5·2·3 | 150–150 | 39.84 |
| GAP-P1-002 | P1 | Нет исполняемых DB/broker-доказательств | 4·4·3·3 | 108–144 | 28.6–38.2 |
| GAP-P1-003 | P1 | Live-сбор NOT_PERMITTED (решение клиента/юристов) | 4·5·1·3 | 60–60 | 15.78 |
| GAP-P1-004 | P1 | E2E/load/backup/restore не исполнялись | 4·4·3·3 | 108–144 | 28.6–38.2 |
| GAP-P1-005 | P1 | In-flight comparability ломает evaluate (S2) | 3·5·1·2 | 30–30 | 7.75 |
| GAP-P1-006 | P1 | Нет CI | 4·4·2·2 | 48–64 | 12.6–16.8 |
| GAP-P2-007 | P2 | Append-only только на уровне приложения | 4·2·4·2 | 48–64 | 12.6–16.8 |
| GAP-P2-008 | P2 | Нет rate limiting | 3·3·3·2 | 36–54 | 9.4–14.2 |
| GAP-P2-009 | P2 | PERMITTED_LIMITED не ограничен операциями | 3·2·3·3 | 54–54 | 14.17 |
| GAP-P2-010 | P2 | Метрики: полные загрузки строк; глобальная глубина очереди | 3·3·3·1 | 18–27 | 4.5–7.0 |
| GAP-P3-011..014 | P3 | Стейл AGENTS.md; PERMITTED-метка у rejected; libm-портируемость replay; мёртвый freshness_generation | ≤2·3·4·2 | 12–32 | 2.9–8.3 |

## 11. Improvement Roadmap and Dependency DAG

Детерминированный порядок (hard_gate_rank → priority → RPN_high →
score_low): **DO_NOW**: IMPROVEMENT-001 (Git baseline + сериализация агентов;
закрывает P0), IMPROVEMENT-005 (доделать comparability, зелёный suite).
**DO_NEXT**: IMPROVEMENT-002 (DB-интеграционные тесты), IMPROVEMENT-006 (CI).
**SCHEDULE**: IMPROVEMENT-004 (бенчмарк/restore/replay-доказательства),
IMPROVEMENT-007..010. **BLOCKED_DECISION**: IMPROVEMENT-003 (source access).
**DEFER**: IMPROVEMENT-011..014. Критическая цепочка: 001 → 005 → 002 → 006 →
004. DO_NOW — рекомендация, не авторизация изменений.

## 12. Technical Architecture and Maintainability Findings

Модульные границы чистые; ownership Metis/Marko выдержан (facade подтверждён).
Крупные модули (market_collection 2959 строк) обоснованы протоколом, но
кандидаты на разбиение. Dead code: `freshness_generation`. Circular deps не
найдены. Ruff: 3 F401 + 1 F821 только в транзиентном mid-edit состоянии.
Ruff/mypy не объявлены dev-зависимостями (P3).

## 13. Data, Matching, Pricing and Replay Findings

Схема БД — образцовая по ограничениям (direction-check рекомендаций на уровне
БД, below-cost авторизация в constraints, partial unique indexes). Matching:
tier-1 точный `model_id` (кросс-продавцовая идентичность Prom) корректен;
точный `sku` между продавцами был слабым сигналом — in-flight comparability
прямо закрывает это 12-мерным fail-closed гейтом (UNKNOWN→MANUAL_REVIEW,
CONFLICT→REJECT). Replay v2: время-ограниченный выбор классификаций, frozen
coefficients, поле-в-поле сравнение включая dispersion-профили и константы;
байтовая точность привязана к платформе (libm, GAP-P3-013).

## 14. Source Access and Provenance Findings

Fail-closed на всех входах, включая каждую физическую попытку; provenance-лейны
(OWNED_STOREFRONT/PUBLIC_COMPETITOR/REPLAY/CLIENT_EXPORT) разделены на уровне
схемы и admission; policy fingerprint хэширует verdict+reference. Замечания:
PERMITTED_LIMITED без операционного скоупа (GAP-P2-009); rejected-таргеты
маркируются `PERMITTED` (GAP-P3-012); `/health/source-access` не требует
аутентификации (info-level). UA-ротация парсера легальна только за гейтом.

## 15. Security, Privacy and Tenant Isolation Findings

JWT-проверка полная; security-заголовки; CORS/TrustedHost валидируются в
production-режиме; SSRF-guard в ScrapeInput (host allowlist, запрет креденшелов
в URL, редиректы fail-closed); bounded fetch (10MB, content-type,
compression-ratio); XLSX-ингест устойчив к zip-bomb. Секретов в repo не
найдено (.env — SENSITIVE_LOCAL, только dev-значения и публичные Firebase
client-ids; значения в отчёт не включены). Пробелы: rate limiting (GAP-P2-008),
tenant-изоляция доказана только на уровне compiled-SQL-текстов (GAP-P1-002),
threat model формально не записана. PII минимальна (email/имя оператора);
retention-политика не определена — business decision.

## 16. Performance, Capacity and Resilience Findings

Измерений нет (ни одного бенчмарка). Математика ёмкости
(C_terminal=min(worker,source,db,queue), ρ-цель 0.70, drain-time) реализована и
юнит-проверена; honest-warnings в метриках («configured, not benchmark
proven»). Метрики-эндпоинты грузят все строки runs в память (GAP-P2-010).
Q(n²) Qn ограничен когортой 500.

## 17. Operations, Deployment, Supply Chain and Observability Findings

Hardened prod-compose; pinned образы; uv.lock фиксирует резолв
(манифест — нижние границы); advisory-скан зависимостей:
`VULNERABILITY_STATUS=NOT_AVAILABLE` (офлайн-политика). Нет CI (GAP-P1-006).
Алерты Prometheus описаны; сбор/дашборды — вне репо. Backup/restore-скрипты
аккуратны, но drills не исполнялись (GAP-P1-004).

## 18. Frontend and Operator Workflow Findings

Ядро UI (клиент API c refresh-once, auth c email-verified enforcement, роутер с
редиректами) прочитано и чисто. Recommendations-страница даёт оператору
очереди, evidence с ценами/множителями/URL, replay-проверку, accept/override/
reject, контекст склада, tier-override; below-cost требует явного второго
подтверждения (проверено виджет-тестом). 21/21 тестов; `dart analyze` чист.
Не прочитаны построчно: dashboard/stores/catalog-страницы и диалоги.
frontend/AGENTS.md устарел (GAP-P3-011).

## 19. Tests Run and Validation Evidence

| cmd | class | purpose | status | exit |
|---|---|---|---|---|
| CMD-001 | SAFE_READ_ONLY | identity/toolchain | PASS | 0 |
| CMD-002 | SAFE_READ_ONLY | физический inventory (9255 путей) | PASS | 0 |
| CMD-003 | SAFE_READ_ONLY | runtime import identity | PASS | 0 |
| CMD-004 | LOCAL_EPHEMERAL | pytest S1: 415 passed | PASS | 0 |
| CMD-005 | SAFE_READ_ONLY | alembic upgrade head --sql (1422 строк) | PASS | 0 |
| CMD-006 | SAFE_READ_ONLY | alembic downgrade base --sql (535 строк) | PASS | 0 |
| CMD-007 | NOT_AVAILABLE | ruff в venv отсутствует | NOT_AVAILABLE | — |
| CMD-008 | SAFE_READ_ONLY | validate-response-footer (пример) | PASS | 0 |
| CMD-009 | SAFE_READ_ONLY | validate-machine-summary (2 примера) | PASS | 0 |
| CMD-010 | SAFE_READ_ONLY | ruff (uv, live 12:07): 4 ошибки, F821 транзиентно | FAIL | 1 |
| CMD-011 | SAFE_READ_ONLY | model↔migration parity (31=31) | PASS | 0 |
| CMD-012 | SAFE_READ_ONLY | import check снапшота S2 | PASS | 0 |
| CMD-013 | LOCAL_EPHEMERAL | pytest S2: 1 failed / 414 passed | FAIL | 1 |
| CMD-014 | NOT_AVAILABLE | flutter analyze (crash тулзы) | NOT_AVAILABLE | — |
| CMD-015 | LOCAL_EPHEMERAL | flutter test: 21 passed | PASS | 0 |
| CMD-016 | SAFE_READ_ONLY | dart analyze: no issues | PASS | 0 |

NOT_RUN_POLICY/NOT_AVAILABLE: docker-стек, alembic против живой БД,
verify_recommendation_replay/evaluate_scraper_benchmark (нет БД/данных),
live-скрейпинг (policy), load/backup drills (нет среды). CMD-013 FAIL — product
defect in-flight состояния, не environment failure.

## 20. Documentation Truthfulness and Code/Docs Drift

README/architecture/runbook — актуальны ине оверклеймят: каждое проверенное
утверждение README сопоставлено коду; runbook явно оговаривает «манифест — не
доказательство». Дрейф: frontend/AGENTS.md (GAP-P3-011); pubspec description —
шаблон. Прошлые аудиты (2026-07-16/17) согласуются с текущими выводами.

## 21. Delete / Retire / Merge / Keep Candidates

- Keep: `marko.pricing` facade (публичный контракт), legacy_collect-ветка
  (нужна для старых runs; retire после миграции данных).
- Retire (после проверки отсутствия consumers): `freshness_generation`
  (или доделать), `calculate_capacity` compatibility-обёртка.
- Merge: metrics-хелперы store/pricing частично дублируются — кандидат на
  объединение. Удалений с недоказанными consumers не предлагается.

## 22. Unknowns, Assumptions and Business Decisions Required

Unknowns: runtime-поведение БД; непрочитанный scope (75 файлов); текущее
состояние живого дерева; измеренная ёмкость; reuse-партиция. Assumptions:
canonical dimension weights (UNVALIDATED), capability weights, риск-оценки
(conservative upper bound), Flutter-scaffolding=generated. Business decisions:
DECISION-SOURCE-ACCESS (владелец — клиент), DECISION-VCS-BASELINE (владелец —
владелец репозитория). Retention/PII-политика — отдельное будущее решение.

## 23. Hostile Review, Variations and Corrections

Hostile-пасс по 24 пунктам промпта: исправлено — (а) первоначальная оценка
покрытия «62%» заменена вычисленной 69.5% (FIXED); (б) ранний план пометить
непрочитанные тесты EXECUTED_AND_REVIEWED пересмотрен: исполнение подтверждено
командами, построчное ревью — нет; принято как limitation с явными
NOT_READ-дисп. для docs/скриптов и EXECUTED_AND_REVIEWED только там, где
исполнение реально покрывает файл (тесты/миграции) (ACCEPTED_WITH_LIMITATION);
(в) соблазн выдать S1-зелёный как «текущее состояние» отвергнут — S2 красный
зафиксирован отдельным claim (FIXED); (г) UI-очереди не выданы за E2E
(ACCEPTED_WITH_LIMITATION). Арифметика пересчитана независимо: RPN/readiness
вычислены исполняемым кодом governance-модуля репозитория, YAML прошёл
round-trip. Variations из frozen ledger: A (optimistic) — «S1-зелёный +
E3-ядро ⇒ pilot-candidate после DB-évidence» — не меняет гейт (нет E4);
B (hostile) — «без VCS ни один результат не воспроизводим ⇒ NO_GO аудита» —
отклонена: метод и bounded-цель воспроизводимы против зафиксированного
fingerprint, поэтому BLOCKED, не NO_GO; C (operator) — «оператор может пройти
workflow только с client-XLSX без live-сбора» — подтверждена как единственный
рабочий режим. Выбран консервативный правдоподобный вердикт: BLOCKED.

## 24. Final Recommendation

1. (P0, сейчас) `git init` + базовый коммит + правило одного писателя для
   агентов; повторный аудит на замороженном снапшоте.
2. Доделать comparability-интеграцию до зелёного suite.
3. Поднять DB-backed интеграционные тесты и CI (это единственный путь к E4 и
   любому pilot-разговору).
4. Принять business-решение об источнике данных Prom; до него продукт честно
   работает в режиме client-XLSX + replay.
5. Только затем — benchmark/restore/replay drills для production-candidate.

Продуктовый вердикт: `production_gate = BLOCKED` (решение об источнике +
отсутствие runtime/операционных доказательств), с одним подтверждённым
repairable FAIL (S2-тест). Аудиторский вердикт этой стадии: `BLOCKED` по
внешней причине; сам отчёт и его артефакты машинно-валидны и согласованы.


## Структурированный результат текущего этапа

STAGE_RESULT:
- stage:
  - id: FULL_PROJECT_AUDIT
  - title: Full project audit Marko + Metis (PROMPT_15_014 rev 2.0.0)
  - type: AUDIT
  - scope owner: Combined
- status: BLOCKED
- completed scope:
  - [SCOPE-IDENTITY] Repository identity, runtime import identity and environment provenance recorded; no Git; path-bound snapshot fingerprint 216c24b8 frozen at 2026-07-18T12:08:15+02:00.
    - artifacts: docs/FULL_PROJECT_AUDIT_VALIDATION_MANIFEST_2026-07-18.yaml
    - evidence: CMD-001, CMD-003
  - [SCOPE-BACKEND-SRC] All 85 backend/src first-party Python files deep-reviewed (S1 state; S2 metis delta reviewed at module and integration level).
    - artifacts: docs/FULL_PROJECT_AUDIT_SCOPE_INVENTORY_2026-07-18.yaml
    - evidence: docs/FULL_PROJECT_AUDIT_2026-07-18.md
  - [SCOPE-EXECUTABLE-CHECKS] pytest S1 415 passed and S2 1 failed/414 passed; alembic offline upgrade and downgrade SQL; model-to-migration table parity; governance validators on examples; flutter test 21 passed; dart analyze clean.
    - artifacts: docs/FULL_PROJECT_AUDIT_VALIDATION_MANIFEST_2026-07-18.yaml
    - evidence: CMD-004, CMD-005, CMD-006, CMD-008, CMD-011, CMD-013, CMD-015, CMD-016
  - [SCOPE-GAP-SYNTHESIS] Claim ledger, 14-gap P0-P3 register with RPN intervals, readiness model and improvement backlog produced and machine-validated.
    - artifacts: docs/FULL_PROJECT_AUDIT_CLAIM_LEDGER_2026-07-18.yaml, docs/FULL_PROJECT_AUDIT_GAP_REGISTER_2026-07-18.yaml
    - evidence: docs/FULL_PROJECT_AUDIT_2026-07-18.md
- strongest verified result:
  - claim: [CLAIM-S1-SUITE-GREEN] The pre-drift state S1 passes 415 of 415 backend tests, generates the full offline migration chain in both directions, matches all 31 model tables to migrations, passes Flutter tests and dart analyze, and its governance validators accept both repository example manifests.
  - evidence level: E3
  - evidence: CMD-004, CMD-005, CMD-006, CMD-011, CMD-015, CMD-016
  - reproduction status: reproducible
  - limitations: No database or broker is exercised by any test; evidence is bound to the pre-drift path state
- weakest critical area:
  - area: [AREA-SNAPSHOT-STABILITY] Repository reproducibility and snapshot stability
  - score/evidence floor: 10.0 / E3
  - reason: No VCS exists and a concurrent PROMPT_15_015 process rewrote backend/src/metis/pricing/* during the audit, transiently leaving an undefined-name defect and a reproducibly failing test in the shared tree.
  - impact: No claim about the current tree survives longer than the moment it is made; whole-codebase audit completeness against one snapshot is unachievable.
  - required resolution: Initialize Git with a committed baseline (or guarantee a frozen worktree) and serialize agent runs, then resume the audit.
- evidence quality:
  - highest level: E3
  - critical floor: E2
  - material claim coverage: 1.00
  - reproducible claim coverage: 1.00
  - freshness status: partial
  - representative scope: partial
  - limitations: All executable evidence is unit-level or offline; no representative runtime, load, backup or security drills exist
- production implication:
  - state: PRODUCTION_BLOCKED
  - production ready: false
  - evidence level: E3
  - passed hard gates: NONE_VERIFIED
  - failed hard gates: S2_COMPARABILITY_INTEGRATION_TEST
  - blocked hard gates: SOURCE_ACCESS_PUBLIC_COLLECTION, DB_RUNTIME_EVIDENCE, REPRESENTATIVE_OPERATIONS
  - statement: The system is a well-engineered integrated internal tool with strong static and unit-level evidence, but production and pilot remain blocked by the source-access decision, absent database/runtime/operational evidence, the red in-flight comparability state, and the ungoverned shared worktree.

## Блокеры

BLOCKERS:
- P0:
  - [BLOCKER-SNAPSHOT-INSTABILITY] No VCS and concurrent uncoordinated agent writes to the audited worktree during the audit run.; owner=repository owner; resolution=Git baseline committed or worktree frozen with the concurrent writer stopped
- P1:
  - [BLOCKER-DB-RUNTIME-EVIDENCE] Docker unavailable and no CI: migrations, PostgreSQL-only SQL, Celery/Redis and replay scripts cannot be executed.; owner=engineering; resolution=Provide Docker or CI with PostgreSQL and Redis
  - [BLOCKER-SOURCE-ACCESS-DECISION] Public Prom collection is NOT_PERMITTED pending a client/legal authorization decision; the mandatory live competitor branch stays closed.; owner=client and legal owner; resolution=Record an official feed or written authorization reference, or accept export/replay-only operation
  - [BLOCKER-S2-RED-TEST] Frozen snapshot S2 reproducibly fails test_authenticated_evaluate_endpoint_returns_actionable_result because the in-flight comparability gate demands evidence the fixtures lack.; owner=engineering (concurrent PROMPT_15_015 executor); resolution=Finish the in-flight feature and restore a green suite on a frozen snapshot
- business decisions:
  - NONE_VERIFIED
- source/access:
  - BLOCKER-SOURCE-ACCESS-DECISION
- data:
  - BLOCKER-S2-RED-TEST
- environment/reproducibility:
  - BLOCKER-SNAPSHOT-INSTABILITY, BLOCKER-DB-RUNTIME-EVIDENCE
- unknowns:
  - unread_first_party_scope, live_tree_current_state, runtime_db_behavior, measured_capacity, reuse_partition

## Следующая часть

NEXT_STAGE:
- id: FULL_PROJECT_AUDIT_RESUME_AFTER_SNAPSHOT_FREEZE
- title: Resume the full project audit on a frozen snapshot
- why it is next:
  - Only snapshot stability and a runtime environment block completion; audit machinery, notes and artifacts already exist
- required inputs:
  - [INPUT-FROZEN-SNAPSHOT] Git baseline or guaranteed-frozen worktree with the concurrent writer stopped; source=repository owner; required_state=committed or verifiably frozen; available=false; evidence=CMD-010
  - [INPUT-RUNTIME-ENV] Docker or CI environment with PostgreSQL and Redis for E4 checks; source=engineering; required_state=available to the audit run; available=false; evidence=CMD-001
  - [INPUT-SOURCE-DECISION] Client/legal decision on Prom marketplace source authorization; source=client; required_state=recorded with auditable reference or explicit export-only decision; available=unknown; evidence=.env.example
- expected artifacts:
  - [ARTIFACT-UPDATED-AUDIT-PACKAGE] report: должен быть создан; purpose=Five-artifact audit package with 100 percent first-party review coverage on the frozen snapshot; required_fields=audit_run_id, coverage, gates
  - [ARTIFACT-DB-EVIDENCE] yaml: должен быть создан; purpose=Executable DB-backed integration command records (alembic upgrade, pytest against PostgreSQL, replay verification); required_fields=command_id, exit_code, output_sha256
- acceptance criteria:
  - [AC-COVERAGE] predicate=first_party_review_coverage == 1.0 on the frozen snapshot; evidence=scope inventory recomputation; threshold=exact 1.0 unrounded
  - [AC-DB-RUN] predicate=alembic upgrade head and the full test suite execute against PostgreSQL with recorded exit codes; evidence=command records with output hashes; threshold=exit 0
- stop condition:
  - gate key: STOP_GATE_FULL_PROJECT_AUDIT_RESUME_AFTER_SNAPSHOT_FREEZE
  - allowed states: PASS, FAIL, BLOCKED, NO_GO
  - automatic transition: false
- client decisions required:
  - [DECISION-VCS-BASELINE] Initialize Git with a committed baseline and serialize agent runs, or continue on an uncontrolled shared worktree?; alternatives=Git baseline plus coordinated runs, Uncontrolled shared worktree; impact=Determines whether any audit, replay or deployment claim can ever be commit-bound and reproducible.; blocking=true; default_forbidden=true; evidence=CMD-001, CMD-010
  - [DECISION-SOURCE-ACCESS] Authorize a permitted Prom source with an auditable reference, or operate on client exports and replay only?; alternatives=Record PERMITTED_* with reference, Export/replay-only operation; impact=Determines whether the live competitor branch of the product flow can ever run.; blocking=true; default_forbidden=true; evidence=README.md, .env.example

STOP_GATE_FULL_PROJECT_AUDIT = BLOCKED

MACHINE_READABLE_SUMMARY:

```yaml
schema:
  name: metis_marko_machine_readable_stage_summary
  version: 1.1.0
  generated_at: "2026-07-18T12:40:00+02:00"
  report_id: FULL-PROJECT-AUDIT-2026-07-18
  audit_id: AUDIT-20260718-115504-LOCAL
stage:
  id: FULL_PROJECT_AUDIT
  title: FULL PROJECT AUDIT MARKO METIS
  status: BLOCKED
  status_reason: The audited worktree has no VCS and was concurrently rewritten by another process during the audit; a stable reproducible snapshot for a complete whole-codebase audit is externally unavailable, and deep-review coverage of the frozen snapshot is 171 of 246 first-party files (69.5 percent).
  acceptance_criteria_passed: false
  audit_complete: false
  production_ready: false
  secondary_findings:
  - type: FAIL
    finding_id: FINDING-S2-RED-TEST
    finding: Frozen snapshot S2 reproducibly fails test_authenticated_evaluate_endpoint_returns_actionable_result due to the in-flight comparability hard gate.
    evidence_refs:
    - command:pytest S2 (CMD-013)
  - type: PASS
    finding_id: FINDING-S1-GREEN
    finding: Pre-drift state S1 passed 415 of 415 tests, offline alembic upgrade and downgrade SQL generation, model-to-migration table parity, Flutter tests and dart analyze.
    evidence_refs:
    - command:pytest S1 (CMD-004)
    - command:alembic --sql (CMD-005, CMD-006)
    - command:flutter test (CMD-015)
  evidence_refs:
  - docs/FULL_PROJECT_AUDIT_2026-07-18.md
  - command:pytest S1/S2
  - command:snapshot fingerprint 216c24b8
repository:
  audit_root: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия
  audit_root_realpath: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия
  topology: MONOREPO
  git_commit: null
  dirty_before_audit: null
  identity_verified: false
  runtime_import_identity: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src
  components:
    metis:
      root: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/metis
      realpath: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/metis
      repository_top_level: null
      git_commit: null
      branch: null
      detached_head: null
      dirty_before_audit: null
      identity_verified: false
      runtime_import_path: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/metis/__init__.py
      evidence_refs:
      - command:import identity (CMD-003)
    marko:
      root: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko
      realpath: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko
      repository_top_level: null
      git_commit: null
      branch: null
      detached_head: null
      dirty_before_audit: null
      identity_verified: false
      runtime_import_path: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko/__init__.py
      evidence_refs:
      - command:import identity (CMD-003)
  duplicate_copies: []
  unresolved_identity_conflicts:
  - NO_GIT_METADATA
  - CONCURRENT_MODIFICATION_DURING_AUDIT
metis:
  weighted_readiness: 57.42187500000001
  readiness_interval:
    lower: 57.42187500000001
    upper: 57.42187500000001
  readiness_scale: '0_100'
  score_basis: CONSERVATIVE_LOWER_BOUND
  critical_floor: 36.25
  evidence_level: E3
  evidence_level_semantics: CRITICAL_EVIDENCE_FLOOR
  highest_evidence_level: E3
  unknown_weight: 0.0
  critical_unknown_count: 0
  engineering_weights_approved: false
  production_eligible: false
  production_gate:
    status: FAIL
    passed_gates: []
    failed_gates:
    - COMPARABILITY_INTEGRATION_TEST
    blocked_gates: []
    unknown_gates:
    - REPRESENTATIVE_OPERATIONS
  dimension_weights:
    implementation: 0.2
    verification: 0.15
    integration: 0.15
    auditability: 0.15
    operations: 0.15
    security: 0.1
    documentation: 0.1
  capabilities:
  - capability_id: METIS-PRICING-KERNEL
    name: Deterministic KEMP pricing engine
    weight: 0.3125
    critical: true
    dimensions:
      implementation: 0.75
      verification: 0.75
      integration: 0.5
      auditability: 0.75
      operations: 0.5
      security: 0.75
      documentation: 0.75
    evidence_level: E3
    raw_interval:
      lower: 67.5
      upper: 67.5
    effective_interval:
      lower: 67.5
      upper: 67.5
    unknown_dimension_weight: 0.0
    evidence_refs:
    - backend/src/metis/pricing/engine.py
    - backend/tests/test_pricing_engine_matrix.py
    - command:pytest S1 415 passed
  - capability_id: METIS-CALIBRATION
    name: Paired-OE tier calibration with leakage protection
    weight: 0.25
    critical: true
    dimensions:
      implementation: 0.75
      verification: 0.75
      integration: 0.5
      auditability: 0.75
      operations: 0.5
      security: 0.5
      documentation: 0.75
    evidence_level: E3
    raw_interval:
      lower: 65.00000000000001
      upper: 65.00000000000001
    effective_interval:
      lower: 65.00000000000001
      upper: 65.00000000000001
    unknown_dimension_weight: 0.0
    evidence_refs:
    - backend/src/metis/pricing/calibration.py
    - backend/tests/test_tier_calibration.py
  - capability_id: METIS-COMPARABILITY
    name: Commercial-comparability hard gate (in-flight)
    weight: 0.25
    critical: true
    dimensions:
      implementation: 0.5
      verification: 0.25
      integration: 0.25
      auditability: 0.5
      operations: 0.25
      security: 0.5
      documentation: 0.25
    evidence_level: E3
    raw_interval:
      lower: 36.25
      upper: 36.25
    effective_interval:
      lower: 36.25
      upper: 36.25
    unknown_dimension_weight: 0.0
    evidence_refs:
    - backend/src/metis/pricing/comparability.py
    - command:pytest S2 1 failed 414 passed
  - capability_id: METIS-TIERING
    name: Brand/tier classification
    weight: 0.1875
    critical: false
    dimensions:
      implementation: 0.75
      verification: 0.75
      integration: 0.5
      auditability: 0.5
      operations: 0.5
      security: 0.5
      documentation: 0.5
    evidence_level: E3
    raw_interval:
      lower: 58.750000000000014
      upper: 58.750000000000014
    effective_interval:
      lower: 58.750000000000014
      upper: 58.750000000000014
    unknown_dimension_weight: 0.0
    evidence_refs:
    - backend/src/metis/pricing/tiering.py
    - backend/tests/test_tiering.py
  critical_capability_ids:
  - METIS-PRICING-KERNEL
  - METIS-CALIBRATION
  - METIS-COMPARABILITY
  strongest_domains:
  - domain_id: METIS-ROBUST-STATISTICS
    name: Robust dispersion statistics (IQR/MAD/Sn/Qn)
    effective_readiness: 70.0
    evidence_level: E3
    critical: false
    why_strong: Exact Rousseeuw-Croux estimators with finite-sample corrections pass a dedicated oracle fixture and mutation-style unit matrix.
    limitations:
    - No representative-load or cross-platform replay evidence
    evidence_refs:
    - backend/src/metis/pricing/statistics.py
    - backend/tests/fixtures/robust_scale_oracle_v1.json
  missing_critical_domains:
  - domain_id: METIS-COMPARABILITY-GREEN
    name: Comparability gate integrated with green suite
    state: CONTRADICTED
    effective_readiness: 36.25
    evidence_level: E3
    reason: 'Frozen snapshot S2 reproducibly fails test_authenticated_evaluate_endpoint_returns_actionable_result: evaluate returns INSUFFICIENT_DATA because fixtures lack the new mandatory comparison evidence.'
    blocks:
    - PRICING_EVALUATE_API
    - PILOT_TRUST
    gap_refs:
    - GAP-P1-005
    evidence_refs:
    - command:pytest S2 1 failed 414 passed
  evidence_refs:
  - backend/src/metis/pricing/
  - command:pytest S1 415 passed
  maturity_class: INTEGRATED_INTERNAL_TOOL
marko:
  weighted_readiness: 56.487500000000004
  readiness_interval:
    lower: 56.487500000000004
    upper: 56.487500000000004
  readiness_scale: '0_100'
  score_basis: CONSERVATIVE_LOWER_BOUND
  critical_floor: 50.0
  evidence_level: E2
  evidence_level_semantics: CRITICAL_EVIDENCE_FLOOR
  highest_evidence_level: E3
  unknown_weight: 0.0
  critical_unknown_count: 0
  engineering_weights_approved: false
  production_eligible: false
  production_gate:
    status: BLOCKED
    passed_gates: []
    failed_gates: []
    blocked_gates:
    - DB_RUNTIME_EVIDENCE
    unknown_gates:
    - DEPLOYMENT
    - BACKUP_RESTORE
    - OBSERVABILITY
    - LOAD
  dimension_weights:
    implementation: 0.2
    verification: 0.15
    integration: 0.15
    auditability: 0.15
    operations: 0.15
    security: 0.1
    documentation: 0.1
  capabilities:
  - capability_id: MARKO-AUTH-TENANT
    name: Firebase auth, workspace tenancy, RBAC
    weight: 0.15
    critical: true
    dimensions:
      implementation: 0.75
      verification: 0.5
      integration: 0.5
      auditability: 0.5
      operations: 0.5
      security: 0.5
      documentation: 0.75
    evidence_level: E3
    raw_interval:
      lower: 57.500000000000014
      upper: 57.500000000000014
    effective_interval:
      lower: 57.500000000000014
      upper: 57.500000000000014
    unknown_dimension_weight: 0.0
    evidence_refs:
    - backend/src/marko/services/auth.py
    - backend/tests/test_auth.py
    - backend/tests/test_tenant_authorization.py
  - capability_id: MARKO-CATALOG-INGEST
    name: Client XLSX catalog ingestion
    weight: 0.12
    critical: true
    dimensions:
      implementation: 0.75
      verification: 0.75
      integration: 0.5
      auditability: 0.75
      operations: 0.5
      security: 0.75
      documentation: 0.75
    evidence_level: E3
    raw_interval:
      lower: 67.5
      upper: 67.5
    effective_interval:
      lower: 67.5
      upper: 67.5
    unknown_dimension_weight: 0.0
    evidence_refs:
    - backend/src/marko/services/xlsx_catalog.py
    - backend/tests/test_xlsx_catalog.py
  - capability_id: MARKO-SCRAPER-RUNTIME
    name: Scraper boundary, evidence journal, lease/fence protocol
    weight: 0.15
    critical: true
    dimensions:
      implementation: 0.75
      verification: 0.5
      integration: 0.25
      auditability: 0.75
      operations: 0.25
      security: 0.5
      documentation: 0.75
    evidence_level: E3
    raw_interval:
      lower: 53.75
      upper: 53.75
    effective_interval:
      lower: 53.75
      upper: 53.75
    unknown_dimension_weight: 0.0
    evidence_refs:
    - backend/src/marko/services/market_collection.py
    - backend/src/marko/services/scrape_journal.py
    - backend/tests/test_scraper_fencing.py
  - capability_id: MARKO-PRICING-ORCHESTRATION
    name: Run lifecycle, calibration barrier, worker tasks
    weight: 0.15
    critical: true
    dimensions:
      implementation: 0.75
      verification: 0.5
      integration: 0.25
      auditability: 0.75
      operations: 0.25
      security: 0.5
      documentation: 0.75
    evidence_level: E2
    raw_interval:
      lower: 53.75
      upper: 53.75
    effective_interval:
      lower: 50.0
      upper: 50.0
    unknown_dimension_weight: 0.0
    evidence_refs:
    - backend/src/marko/services/pricing_runs.py
    - backend/src/marko/worker/tasks/pricing.py
  - capability_id: MARKO-REPLAY-AUDIT
    name: Recommendation replay and append-only decisions
    weight: 0.13
    critical: true
    dimensions:
      implementation: 0.75
      verification: 0.75
      integration: 0.25
      auditability: 0.75
      operations: 0.25
      security: 0.5
      documentation: 0.75
    evidence_level: E3
    raw_interval:
      lower: 57.49999999999999
      upper: 57.49999999999999
    effective_interval:
      lower: 57.49999999999999
      upper: 57.49999999999999
    unknown_dimension_weight: 0.0
    evidence_refs:
    - backend/src/marko/services/recommendation_replay.py
    - backend/tests/test_recommendation_replay.py
  - capability_id: MARKO-OPERATOR-UI
    name: Flutter operator workflow
    weight: 0.12
    critical: false
    dimensions:
      implementation: 0.75
      verification: 0.5
      integration: 0.5
      auditability: 0.5
      operations: 0.5
      security: 0.5
      documentation: 0.5
    evidence_level: E3
    raw_interval:
      lower: 55.000000000000014
      upper: 55.000000000000014
    effective_interval:
      lower: 55.000000000000014
      upper: 55.000000000000014
    unknown_dimension_weight: 0.0
    evidence_refs:
    - frontend/lib/features/pricing/recommendations_page.dart
    - command:flutter test 21 passed
  - capability_id: MARKO-OPS-DEPLOY
    name: Compose/deploy/backup tooling
    weight: 0.09
    critical: false
    dimensions:
      implementation: 0.5
      verification: 0.25
      integration: 0.25
      auditability: 0.5
      operations: 0.25
      security: 0.75
      documentation: 0.75
    evidence_level: E2
    raw_interval:
      lower: 43.75
      upper: 43.75
    effective_interval:
      lower: 43.75
      upper: 43.75
    unknown_dimension_weight: 0.0
    evidence_refs:
    - deploy/compose.production.yaml
    - scripts/backup_postgres.sh
    - docs/production_runbook.md
  - capability_id: MARKO-GOVERNANCE
    name: Section 15/16 governance contracts
    weight: 0.09
    critical: false
    dimensions:
      implementation: 0.75
      verification: 0.75
      integration: 0.75
      auditability: 0.75
      operations: 0.5
      security: 0.5
      documentation: 0.75
    evidence_level: E3
    raw_interval:
      lower: 68.75
      upper: 68.75
    effective_interval:
      lower: 68.75
      upper: 68.75
    unknown_dimension_weight: 0.0
    evidence_refs:
    - backend/src/marko/governance/machine_summary.py
    - command:validate-machine-summary examples VALID
  critical_capability_ids:
  - MARKO-AUTH-TENANT
  - MARKO-CATALOG-INGEST
  - MARKO-SCRAPER-RUNTIME
  - MARKO-PRICING-ORCHESTRATION
  - MARKO-REPLAY-AUDIT
  strongest_domains:
  - domain_id: MARKO-EVIDENCE-CHAIN
    name: Content-addressed raw-evidence chain and replay journal
    effective_readiness: 57.5
    evidence_level: E3
    critical: true
    why_strong: SHA-256-verified compressed blobs, replay cache integrity checks, and success-requires-raw-evidence invariant are enforced in code and unit tests.
    limitations:
    - Never executed against PostgreSQL/Redis in this audit
    evidence_refs:
    - backend/src/marko/services/scrape_journal.py
    - backend/tests/test_scrape_runtime.py
  missing_critical_domains:
  - domain_id: MARKO-DB-INTEGRATION
    name: Executable database/broker integration evidence
    state: MISSING
    effective_readiness: 0.0
    evidence_level: E2
    reason: 'The entire test suite runs without any database: tenant isolation is asserted on compiled SQL text, PostgreSQL-only constructs and migrations are never executed, Docker is unavailable locally, and no CI exists.'
    blocks:
    - PILOT
    - PRODUCTION
    gap_refs:
    - GAP-P1-002
    evidence_refs:
    - backend/tests/test_tenant_authorization.py
    - command:no conftest.py, 415 tests in 2.63s
  evidence_refs:
  - backend/src/marko/
  - command:pytest S1 415 passed
  maturity_class: INTEGRATED_PRODUCT_SHELL
  existing_scraper:
    located: VERIFIED
    physical_path: backend/src/marko/parsers/prom
    entry_point: marko.parsers.prom.gateway.PromGateway.compare
    entry_point_verified: PARTIAL
    input_contract_verified: PARTIAL
    output_contract_verified: PARTIAL
    runtime_reverified: NOT_VERIFIED
    single_request_verified: NOT_VERIFIED
    small_batch_verified: NOT_VERIFIED
    batch_ready: PARTIAL
    parallel_safe: PARTIAL
    timeout_bounded: PARTIAL
    retry_safe: PARTIAL
    idempotent: PARTIAL
    queue_integrated: PARTIAL
    dead_letter_integrated: PARTIAL
    raw_storage_integrated: PARTIAL
    structured_storage_integrated: PARTIAL
    metis_evidence_integrated: PARTIAL
    replayable: PARTIAL
    observable: PARTIAL
    load_tested: NOT_VERIFIED
    production_proven: NOT_VERIFIED
    capacity:
      measured: false
      unique_urls: null
      arrival_rate_urls_per_second: null
      worker_service_rate_urls_per_second: null
      active_workers: null
      average_attempts_per_unique_url: null
      effective_worker_service_rate: null
      total_capacity_urls_per_second: null
      utilization_rho: null
      queue_backlog: null
      queue_stability: NOT_MEASURED
      estimated_drain_seconds: null
      success_rate: null
      retry_amplification: null
      latency_p50_seconds: null
      latency_p95_seconds: null
      latency_p99_seconds: null
      raw_storage_bytes: null
      structured_storage_bytes: null
      memory_peak_bytes: null
      cpu_average_percent: null
    evidence_refs:
    - backend/src/marko/parsers/prom/client.py
    - backend/src/marko/services/scraper_contract.py
  reusable_as_is: []
  adapt_before_reuse: []
  reference_only: []
  do_not_port: []
  unknown_reuse_state: []
  evaluated_component_ids: []
  reuse_partition_valid: null
combined_system:
  maturity_class: PARTIAL_INTEGRATION
  end_to_end_flow_verified: NOT_VERIFIED
  end_to_end_evidence_level: E2
  trace_coverage: 1.0
  verified_trace_coverage: 0.0
  integrated_trace_coverage: 1.0
  last_verified_node: null
  first_unverified_node: AUTH_WORKSPACE
  first_broken_transition: METIS_PRICING_CALCULATION (S2 evaluate contract regression)
  production_eligible: false
  production_gate:
    status: BLOCKED
    passed_gates: []
    failed_gates: []
    blocked_gates:
    - SOURCE_ACCESS
    - DB_RUNTIME_EVIDENCE
    unknown_gates:
    - REPLAY
    - SECURITY
    - TENANT_ISOLATION
    - DEPLOYMENT
    - BACKUP_RESTORE
    - OBSERVABILITY
    - ROLLBACK_RECOVERY
    - ABSTENTION
  recommendation_contract:
    explainable: PARTIAL
    auditable: PARTIAL
    reproducible: PARTIAL
    insufficient_data_abstention: PARTIAL
    manual_review_routing: PARTIAL
  evidence_refs:
  - docs/FULL_PROJECT_AUDIT_2026-07-18.md
gaps:
  p0:
  - gap_id: GAP-P0-001
    system: SHARED
    capability_id: MARKO-OPS-DEPLOY
    title: 'Uncontrolled shared worktree: no VCS and concurrent uncoordinated agent writes'
    description: The checkout has no Git metadata, and during this audit another process (PROMPT_15_015 execution) rewrote backend/src/metis/pricing/* between 12:04 and 12:08, transiently leaving an undefined-name defect and a failing test in the shared tree. Every audited or produced artifact is path-bound and can silently drift; snapshot integrity and rollback are impossible.
    gap_type: DEPLOYMENT_GAP
    priority: P0
    severity: 5
    likelihood: 5
    detection_difficulty: 2
    dependency_centrality: 3
    rpn: 150
    normalized_rpn: 39.839572192513366
    affected_invariants:
    - failure/rollback leaves no partially confirmed state
    - recommendation reproducible from pinned inputs
    blocks:
    - REPRODUCIBLE_AUDIT
    - SAFE_PARALLEL_DEVELOPMENT
    - PRODUCTION_DEPLOYMENT
    evidence_refs:
    - command:no git metadata (CMD-001)
    - command:ruff F821 transient at 12:07 (CMD-010)
    - command:pytest S2 1 failed (CMD-013)
    owner_type: repository owner
    remediation_class: process_and_tooling
    acceptance_evidence_required: E3
  p1:
  - gap_id: GAP-P1-002
    system: MARKO
    capability_id: MARKO-PRICING-ORCHESTRATION
    title: No executable database/broker integration evidence
    description: 'All 415 tests run in 2.6 seconds without any database: tenant isolation is asserted on compiled SQL strings, PostgreSQL-only constructs (advisory locks, ON CONFLICT, partial unique indexes) and the migration chain are never executed against a real PostgreSQL, and Celery/Redis paths are untested. Docker is unavailable locally and no CI pipeline exists in the repository.'
    gap_type: EVIDENCE_GAP
    priority: P1
    severity: 4
    likelihood: 4
    detection_difficulty: 3
    dependency_centrality: 3
    rpn: 144
    normalized_rpn: 38.23529411764706
    affected_invariants:
    - tenant isolation on every transition
    - retry/redelivery cannot duplicate observations
    blocks:
    - PILOT
    - PRODUCTION_CANDIDATE
    evidence_refs:
    - backend/tests/
    - command:pytest 415 passed 2.63s without DB (CMD-004)
    - command:docker NOT_AVAILABLE (CMD-001)
    owner_type: engineering
    remediation_class: integration_test_infrastructure
    acceptance_evidence_required: E4
  - gap_id: GAP-P1-003
    system: COMBINED
    capability_id: MARKO-SCRAPER-RUNTIME
    title: Public competitor collection is NOT_PERMITTED, closing the mandatory live branch
    description: PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT defaults to NOT_PERMITTED with an empty reference; run creation, store sync, CLI and every physical HTTP attempt are fail-closed. The full product flow with live competitor collection cannot be claimed until an official feed or written authorization is recorded. Replay, deterministic evaluation and XLSX ingestion remain available.
    gap_type: SOURCE_ACCESS_GAP
    priority: P1
    severity: 4
    likelihood: 5
    detection_difficulty: 1
    dependency_centrality: 3
    rpn: 60
    normalized_rpn: 15.775401069518717
    affected_invariants:
    - forbidden source request cannot pass any entry point
    blocks:
    - LIVE_COMPETITOR_COLLECTION
    - PRODUCTION_E2E
    evidence_refs:
    - backend/src/marko/services/source_access.py
    - .env.example
    - README.md
    owner_type: client and legal owner
    remediation_class: business_decision
    acceptance_evidence_required: E2
  - gap_id: GAP-P1-004
    system: COMBINED
    capability_id: MARKO-PRICING-ORCHESTRATION
    title: End-to-end flow, load, backup/restore and recovery never executed
    description: No pinned integration or replay run of the full pipeline exists; the production runbook requires benchmark, restore-drill and replay preflights that have never been executed anywhere recorded. All capacity numbers are configured, not measured.
    gap_type: EVIDENCE_GAP
    priority: P1
    severity: 4
    likelihood: 4
    detection_difficulty: 3
    dependency_centrality: 3
    rpn: 144
    normalized_rpn: 38.23529411764706
    affected_invariants:
    - recommendation reproducible from pinned inputs
    blocks:
    - PRODUCTION_CANDIDATE
    - PRODUCTION_READY_PROVEN
    evidence_refs:
    - docs/production_runbook.md
    - command:evaluate_scraper_benchmark not runnable locally (NOT_AVAILABLE)
    owner_type: engineering
    remediation_class: representative_environment_run
    acceptance_evidence_required: E5
  - gap_id: GAP-P1-005
    system: METIS
    capability_id: METIS-COMPARABILITY
    title: In-flight comparability gate breaks the evaluate endpoint contract (frozen snapshot)
    description: 'Snapshot S2 (12:08) reproducibly fails test_authenticated_evaluate_endpoint_returns_actionable_result: the new mandatory comparison-evidence hard gate returns INSUFFICIENT_DATA for fixtures that lack ComparisonEvidence. The feature is mid-implementation by a concurrent process; the shared tree is red.'
    gap_type: PARTIAL_IMPLEMENTATION
    priority: P1
    severity: 3
    likelihood: 5
    detection_difficulty: 1
    dependency_centrality: 2
    rpn: 30
    normalized_rpn: 7.754010695187166
    affected_invariants:
    - insufficient data leads to abstention
    blocks:
    - PRICING_EVALUATE_API
    evidence_refs:
    - command:pytest S2 1 failed 414 passed (CMD-013)
    - backend/src/metis/pricing/comparability.py
    owner_type: engineering
    remediation_class: finish_in_flight_feature
    acceptance_evidence_required: E3
  - gap_id: GAP-P1-006
    system: SHARED
    capability_id: MARKO-OPS-DEPLOY
    title: No CI pipeline enforcing the runbook preflight
    description: The production runbook requires tests, lint, compile, Flutter checks and release build in a clean CI runner, but the repository contains no CI configuration at all; every gate is manual.
    gap_type: DEPLOYMENT_GAP
    priority: P1
    severity: 4
    likelihood: 4
    detection_difficulty: 2
    dependency_centrality: 2
    rpn: 64
    normalized_rpn: 16.844919786096256
    affected_invariants: []
    blocks:
    - DEPLOYABILITY
    evidence_refs:
    - docs/production_runbook.md
    - command:rg no .github/workflows (CMD-002)
    owner_type: engineering
    remediation_class: ci_pipeline
    acceptance_evidence_required: E3
  p2:
  - gap_id: GAP-P2-007
    system: MARKO
    capability_id: MARKO-REPLAY-AUDIT
    title: Append-only guarantees are application-level only
    description: Decisions, overrides, observations and tier classifications are append-only by code convention; no DB triggers or privilege separation prevent UPDATE/DELETE by any connected role.
    gap_type: DATA_MODEL_GAP
    priority: P2
    severity: 4
    likelihood: 2
    detection_difficulty: 4
    dependency_centrality: 2
    rpn: 64
    normalized_rpn: 16.844919786096256
    affected_invariants:
    - operator decision append-only
    blocks:
    - AUDIT_TRUST
    evidence_refs:
    - backend/src/marko/infrastructure/db/models.py
    owner_type: engineering
    remediation_class: db_hardening
    acceptance_evidence_required: E3
  - gap_id: GAP-P2-008
    system: MARKO
    capability_id: MARKO-AUTH-TENANT
    title: No API rate limiting or per-tenant quotas
    description: No rate limiter exists on any endpoint; XLSX upload, pricing-run creation and evaluate are bounded only by size caps and worker capacity.
    gap_type: SECURITY_GAP
    priority: P2
    severity: 3
    likelihood: 3
    detection_difficulty: 3
    dependency_centrality: 2
    rpn: 54
    normalized_rpn: 14.171122994652407
    affected_invariants: []
    blocks:
    - ABUSE_RESISTANCE
    evidence_refs:
    - backend/src/marko/api/main.py
    owner_type: engineering
    remediation_class: middleware
    acceptance_evidence_required: E3
  - gap_id: GAP-P2-009
    system: MARKO
    capability_id: MARKO-SCRAPER-RUNTIME
    title: PERMITTED_LIMITED is not distinguished from PERMITTED_OFFICIAL in code
    description: Both permitted verdicts enable identical behavior; no allowed/prohibited operation scoping exists for the conditional state that Section 16 mapping requires.
    gap_type: SOURCE_ACCESS_GAP
    priority: P2
    severity: 3
    likelihood: 2
    detection_difficulty: 3
    dependency_centrality: 3
    rpn: 54
    normalized_rpn: 14.171122994652407
    affected_invariants: []
    blocks:
    - CONDITIONAL_SOURCE_OPERATION
    evidence_refs:
    - backend/src/marko/services/source_access.py
    owner_type: engineering
    remediation_class: policy_scoping
    acceptance_evidence_required: E3
  - gap_id: GAP-P2-010
    system: MARKO
    capability_id: MARKO-SCRAPER-RUNTIME
    title: Metrics endpoints load entire run telemetry into memory and leak global queue depth
    description: get_*_scraper_metrics loads all requests/attempts/observations per call, and _store_queue_health counts queued sync-runs across all workspaces inside a workspace-scoped endpoint.
    gap_type: CAPACITY_GAP
    priority: P2
    severity: 3
    likelihood: 3
    detection_difficulty: 3
    dependency_centrality: 1
    rpn: 27
    normalized_rpn: 6.951871657754011
    affected_invariants: []
    blocks:
    - METRICS_AT_SCALE
    evidence_refs:
    - backend/src/marko/services/scraper_metrics.py
    owner_type: engineering
    remediation_class: query_optimization
    acceptance_evidence_required: E3
  p3:
  - gap_id: GAP-P3-011
    system: MARKO
    capability_id: MARKO-OPERATOR-UI
    title: frontend/AGENTS.md documents only auth and stores features
    description: The instruction file omits catalog, pricing and dashboard features that exist in lib/features, misleading future agents.
    gap_type: PARTIAL_IMPLEMENTATION
    priority: P3
    severity: 2
    likelihood: 3
    detection_difficulty: 2
    dependency_centrality: 1
    rpn: 12
    normalized_rpn: 2.9411764705882355
    affected_invariants: []
    blocks: []
    evidence_refs:
    - frontend/AGENTS.md
    - frontend/lib/features/
    owner_type: engineering
    remediation_class: doc_update
    acceptance_evidence_required: E2
  - gap_id: GAP-P3-012
    system: MARKO
    capability_id: MARKO-PRICING-ORCHESTRATION
    title: Rejected scrape targets are labeled source_policy_state=PERMITTED
    description: The invalid-input rejection branch in create_pricing_run stamps PERMITTED without an admission decision; the state should be UNKNOWN or NOT_APPLICABLE.
    gap_type: PARTIAL_IMPLEMENTATION
    priority: P3
    severity: 2
    likelihood: 2
    detection_difficulty: 3
    dependency_centrality: 1
    rpn: 12
    normalized_rpn: 2.9411764705882355
    affected_invariants: []
    blocks: []
    evidence_refs:
    - backend/src/marko/services/pricing_runs.py
    owner_type: engineering
    remediation_class: small_fix
    acceptance_evidence_required: E3
  - gap_id: GAP-P3-013
    system: METIS
    capability_id: METIS-PRICING-KERNEL
    title: Float libm operations make byte-exact replay platform-dependent
    description: math.exp/log/pow round-trips through str() are deterministic per platform but may differ across libm builds, so exact replay comparison can report drift after a platform change.
    gap_type: REPLAY_GAP
    priority: P3
    severity: 2
    likelihood: 2
    detection_difficulty: 4
    dependency_centrality: 2
    rpn: 32
    normalized_rpn: 8.288770053475936
    affected_invariants: []
    blocks: []
    evidence_refs:
    - backend/src/metis/pricing/statistics.py
    owner_type: engineering
    remediation_class: documentation_or_decimal_port
    acceptance_evidence_required: E3
  - gap_id: GAP-P3-014
    system: MARKO
    capability_id: MARKO-SCRAPER-RUNTIME
    title: freshness_generation is plumbed but never incremented
    description: The idempotency namespace supports freshness generations, but no code path ever increments it, so re-collection freshness is a dead knob.
    gap_type: PARTIAL_IMPLEMENTATION
    priority: P3
    severity: 2
    likelihood: 2
    detection_difficulty: 3
    dependency_centrality: 1
    rpn: 12
    normalized_rpn: 2.9411764705882355
    affected_invariants: []
    blocks: []
    evidence_refs:
    - backend/src/marko/services/scraper_architecture.py
    owner_type: engineering
    remediation_class: small_fix
    acceptance_evidence_required: E2
  priority_partition_valid: true
  duplicate_gap_ids: []
  critical_dependency_chain:
  - GAP-P0-001
  - GAP-P1-002
  - GAP-P1-004
  - GAP-P1-003
business_decisions_required:
- decision_id: DECISION-SOURCE-ACCESS
  title: Prom marketplace source authorization
  status: MISSING
  owner: client
  options:
  - Record an official feed or written authorization and set PERMITTED_*
  - Operate permanently on client exports and persisted replay only
  recommended_option: null
  recommendation_basis: null
  default_assumption_for_planning: Live collection stays blocked; XLSX, evaluation and replay remain available.
  implementation_blocked: true
  blocked_scope:
  - LIVE_COMPETITOR_COLLECTION
  required_before_stage: PRODUCTION_E2E
  evidence_refs:
  - README.md
  - .env.example
- decision_id: DECISION-VCS-BASELINE
  title: Version control and concurrent-agent coordination
  status: MISSING
  owner: repository owner
  options:
  - Initialize Git, commit a baseline and serialize agent runs
  - Continue on an uncontrolled shared worktree
  recommended_option: Initialize Git, commit a baseline and serialize agent runs
  recommendation_basis: During this audit the tree was rewritten mid-run, transiently broken, and left red; no rollback or attribution is possible without VCS.
  default_assumption_for_planning: All current artifacts are path-bound to fingerprint 216c24b8.
  implementation_blocked: true
  blocked_scope:
  - REPRODUCIBLE_AUDIT
  required_before_stage: FULL_PROJECT_AUDIT_RESUME_AFTER_SNAPSHOT_FREEZE
  evidence_refs:
  - command:CMD-001 NO_GIT
  - command:CMD-010/CMD-013 drift evidence
source_access_states:
- source_id: PROM-PUBLIC-MARKETPLACE
  source_name: Public Prom.ua marketplace pages
  source_type: public_marketplace_http
  state: NOT_PERMITTED
  scope: New live competitor collection anywhere in the system
  basis: Settings default NOT_PERMITTED with empty reference; PERMITTED_* requires a non-empty auditable reference; the gate runs at run creation, store sync, CLI and before every physical HTTP attempt.
  verified_at: "2026-07-18T12:40:00+02:00"
  expires_at: null
  allowed_operations:
  - client-supplied XLSX ingestion
  - deterministic evaluation
  - persisted content-addressed evidence replay
  - stored recommendation reads
  prohibited_operations:
  - new live public marketplace HTTP collection
  blocking_scope:
  - LIVE_COMPETITOR_COLLECTION
  evidence_refs:
  - backend/src/marko/core/config.py
  - backend/src/marko/services/source_access.py
  - backend/src/marko/services/scrape_runtime.py
engineering_assumptions:
- assumption_id: ASSUMPTION-CAPABILITY-WEIGHTS
  statement: Capability and raw-importance weights used for readiness aggregation are engineering estimates.
  rationale: No owner-approved weight decision artifact exists in the repository.
  affected_fields:
  - metis.capabilities
  - marko.capabilities
  - metis.weighted_readiness
  - marko.weighted_readiness
  impact_if_false: Weighted readiness and critical floors shift; per-capability intervals remain valid.
  validation_method: Owner review and approval of a weight decision artifact.
  required_by_stage: null
  status: UNVALIDATED
  evidence_refs: []
- assumption_id: ASSUMPTION-RISK-UPPER-BOUND
  statement: Section 16 gap records use conservative upper-bound risk factors.
  rationale: Exact likelihood/detection values are not measurable without runtime history.
  affected_fields:
  - gaps.p0
  - gaps.p1
  - gaps.p2
  - gaps.p3
  impact_if_false: Ranked order inside a priority bucket may change; priorities are semantic first.
  validation_method: Recalibrate after runtime incidents and CI history exist.
  required_by_stage: null
  status: UNVALIDATED
  evidence_refs: []
- assumption_id: ASSUMPTION-FLUTTER-SCAFFOLD-GENERATED
  statement: frontend platform directories (android/ios/macos/windows/web) are treated as generated Flutter scaffolding.
  rationale: Files match flutter-create output patterns; only build.gradle.kts carries a project-specific package id.
  affected_fields:
  - scope_inventory.items
  impact_if_false: First-party review denominators grow and coverage drops further.
  validation_method: Diff against a fresh flutter create output.
  required_by_stage: null
  status: UNVALIDATED
  evidence_refs: []
future_hypotheses:
- hypothesis_id: HYPOTHESIS-COMPARABILITY-GREEN
  statement: The in-flight PROMPT_15_015 comparability work will restore a green suite once marko-side fixtures attach ComparisonEvidence.
  expected_value: pytest returns to 0 failed on the completed state.
  required_data:
  - A frozen post-implementation snapshot
  - pytest run on that snapshot
  falsification_test: Freeze the tree after the concurrent process stops and run the full suite.
  earliest_applicable_stage: FULL_PROJECT_AUDIT_RESUME_AFTER_SNAPSHOT_FREEZE
  current_action: DEFER_UNTIL_WRITER_STOPS
  evidence_refs: []
unknowns:
- unknown_id: UNKNOWN-REPO-VCS
  field_path: repository.*
  question: Which canonical commit identity owns this worktree and what changed between audit reads?
  reason_unknown: No Git metadata exists and a concurrent process modified files during the audit.
  impact: All claims are path-bound to fingerprint 216c24b8 taken 2026-07-18T12:08:15+02:00; the live tree may already differ.
  resolver_type: REPOSITORY_OWNER_INPUT
  required_input: Git init plus a committed baseline, or a coordinated frozen snapshot
  owner: repository owner
  blocks:
  - REPRODUCIBLE_AUDIT
  target_stage: FULL_PROJECT_AUDIT_RESUME_AFTER_SNAPSHOT_FREEZE
- unknown_id: UNKNOWN-UNREAD-SCOPE
  field_path: scope_inventory.first_party_review_coverage
  question: What defects exist in the first-party files not yet deep-read (most backend tests, most Flutter pages, large docs, five scripts)?
  reason_unknown: 'Session scope: 171 of 246 eligible first-party files were deep-read or executed-and-reviewed; the remainder were executed and structurally reviewed but not line-by-line.'
  impact: Whole-codebase completeness cannot be claimed; coverage numbers are recorded exactly in the scope inventory.
  resolver_type: AUDIT_CONTINUATION
  required_input: A resumed audit run against a frozen snapshot
  owner: engineering
  blocks:
  - AUDIT_COMPLETENESS
  target_stage: FULL_PROJECT_AUDIT_RESUME_AFTER_SNAPSHOT_FREEZE
- unknown_id: UNKNOWN-DB-RUNTIME
  field_path: marko.production_gate
  question: Do migrations, PostgreSQL-only SQL, Celery redelivery and tenant isolation behave correctly at runtime?
  reason_unknown: No database is exercised by any test; Docker is unavailable in the audit environment; no CI exists.
  impact: E4 evidence is unobtainable in this run; production gates stay blocked or unknown.
  resolver_type: INTEGRATION_TEST_RUN
  required_input: Docker or CI with PostgreSQL and Redis
  owner: engineering
  blocks:
  - PILOT
  - PRODUCTION_CANDIDATE
  target_stage: DB_INTEGRATION_EVIDENCE
- unknown_id: UNKNOWN-REUSE
  field_path: marko.reuse_partition
  question: Which Marko components are reusable as-is for Metis ownership migration?
  reason_unknown: Reuse classification was out of scope for this audit run.
  impact: Empty reuse arrays mean unassessed, not verified-empty.
  resolver_type: ARCHITECTURE_REVIEW
  required_input: A dedicated reuse assessment
  owner: engineering
  blocks: []
  target_stage: null
- unknown_id: UNKNOWN-PERF-CAPACITY
  field_path: marko.existing_scraper.capacity
  question: What are measured latency percentiles, throughput and stable concurrency?
  reason_unknown: No controlled benchmark has ever been executed; capacity numbers in configs are budgets, not measurements.
  impact: Capacity claims would be fabricated; benchmark tooling exists but requires a permitted source or fixture environment.
  resolver_type: CONTROLLED_BENCHMARK
  required_input: Isolated benchmark environment and permitted source or fixtures
  owner: engineering
  blocks:
  - PRODUCTION_READY_PROVEN
  target_stage: null
next_stage:
  id: FULL_PROJECT_AUDIT_RESUME_AFTER_SNAPSHOT_FREEZE
  title: RESUME FULL PROJECT AUDIT ON A FROZEN SNAPSHOT
  objective: Complete deep-review coverage and re-run all executable checks against a version-controlled or coordinated frozen snapshot, then finish the audit package with a PASS-eligible gate.
  why_it_is_next: The only externally blocked inputs are snapshot stability and a runtime environment; all other audit machinery, notes and artifacts already exist.
  required_inputs:
  - Git baseline or guaranteed-frozen worktree (concurrent writer stopped)
  - Docker or CI environment with PostgreSQL and Redis for E4 checks
  expected_outputs:
  - Updated five-artifact audit package with 100 percent first-party review coverage
  - Executable DB-backed integration evidence records
  acceptance_criteria:
  - first_party_review_coverage equals 1.0 on the frozen snapshot
  - pytest, alembic upgrade against PostgreSQL, and replay verification all recorded with exit codes
  stop_condition: STOP_GATE_FULL_PROJECT_AUDIT_RESUME_AFTER_SNAPSHOT_FREEZE with no automatic continuation
  client_decisions_required:
  - DECISION-VCS-BASELINE
  - DECISION-SOURCE-ACCESS
  started: false
  new_direct_instruction_required: true
validation:
  yaml_parse: true
  duplicate_key_check: true
  schema_validation: true
  required_field_validation: true
  enum_validation: true
  type_validation: true
  arithmetic_validation: true
  readiness_interval_validation: true
  evidence_ceiling_validation: true
  critical_floor_validation: true
  stop_gate_consistency: true
  production_gate_consistency: true
  reuse_partition_validation: true
  gap_partition_validation: true
  evidence_traceability: true
  reverse_trace_validation: true
  variation_validation: true
  hostile_review: true
  errors: []
  warnings:
  - AUDIT_STAGE_BLOCKED_BY_SNAPSHOT_INSTABILITY
  - FIRST_PARTY_REVIEW_COVERAGE_BELOW_ONE
  - S2_SNAPSHOT_TEST_SUITE_RED
termination:
  stop_gate_key: STOP_GATE_FULL_PROJECT_AUDIT
  stop_gate_value: BLOCKED
  stage_status_matches_stop_gate: true
  next_stage_started: false
  execution_stopped: true
  no_content_after_summary: true
```
