# Production Readiness Remediation — Completion Report

Дата: 2026-07-16

Проверенный project root:
`/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`

## 1. Итог

```text
REMEDIATION_IMPLEMENTATION = PASS
LOCAL_VERIFICATION = PASS
ENGINEERING_CONTROL_PLANE = PASS
LIVE_PRODUCTION_ACTIVATION = CONDITIONAL
LIVE_PROM_COMPETITOR_COLLECTION = POLICY_BLOCKED
```

Инженерная ремедиация hard-gates из Stage 01 успешно завершена. Проект теперь
имеет исполняемые source-access controls, явную границу Marko → Metis, RBAC и
tenant-scoped authorization, recommendation replay, operator review,
dead-letter replay, production manifest, recovery scripts, runbook,
observability contracts и capacity acceptance model.

`LIVE_PRODUCTION_ACTIVATION` не объявлена безусловным `PASS`, потому что такой
статус требует внешних доказательств, которых невозможно честно создать
изменением кода:

- разрешённого источника competitor data;
- целевой PostgreSQL/Redis/Firebase/TLS infrastructure;
- backup/restore, rollback и sustained-load drills в этой infrastructure;
- принятого labeled matching set и shadow/pilot отчёта.

Это не незавершённая implementation-задача. Это контролируемые activation
prerequisites. До их выполнения система закрыта безопасно и не выдаёт
отсутствующее разрешение за техническую готовность.

## 2. Закрытие исходных hard-gates

| Исходный hard-gate | Результат ремедиации | Статус |
|---|---|---|
| Нет classifier, comparability, pricing и recommendation engine | Детерминированные tiering, comparability gates, KEMP-normalized calculation, abstention, confidence, calibration и recommendation journal находятся в canonical `metis.pricing`; Marko использует этот kernel через application services/API/UI. | PASS |
| Нет сквозного Marko → Metis пути | Создан installable package `metis.pricing`; production Marko imports используют его напрямую, а `marko.pricing` оставлен только как compatibility facade. Wheel содержит оба корректных boundary. | PASS |
| Competitor source имеет `NOT_PERMITTED` | Добавлен fail-closed executable gate до dispatch и перед каждым физическим HTTP attempt. Разрешающий verdict требует auditable reference. Replay и client XLSX не пересекают live-source gate. | PASS как safety control; permission остаётся внешним blocker |
| Tenant isolation и authorization не проверены | `owner/admin/member` возвращается через auth context; административные workflows требуют `owner/admin`; object queries связывают object identity с `workspace_id`; добавлены adversarial tenant/RBAC tests. | PASS на code/test level |
| Нет recommendation replay и operator review | Добавлен exact deterministic replay без network, API/UI drift report, append-only accept/reject/override workflow и guarded below-cost confirmation. | PASS |
| Нет operator flow для terminal failures | Добавлен workspace-scoped dead-letter registry и admin replay, создающий новый workflow без изменения terminal history. | PASS |
| Не определён production deployment | Добавлен hardened reference Compose с private managed DB/Redis, non-root backend, read-only filesystem, separated workers, explicit hosts/CORS, docs-off и loopback ports behind TLS proxy. | PASS как deployment artifact |
| Не определены backup/restore/rollback | Добавлены checksum backup, empty-database restore guard, exact replay verifier и пошаговый production runbook. | PASS как executable procedure |
| Недостаточная observability/load модель | Сохранены обязательные scraper metrics, Prometheus endpoints, alert rules, multi-bottleneck capacity model и benchmark acceptance evaluator с `rho <= 0.70`. | PASS как instrumentation/acceptance contract |

## 3. Реализованные production controls

### Source access

- default verdict: `NOT_PERMITTED`;
- permitted verdict без reference отклоняется конфигурацией;
- API возвращает явный `409 SOURCE_ACCESS_BLOCKED`;
- source state доступен через `GET /api/v1/health/source-access`;
- raw-evidence replay остаётся offline и не создаёт HTTP attempts.

### Security and tenancy

- production validation запрещает debug, wildcard hosts и wildcard CORS;
- Swagger/OpenAPI по умолчанию отключены в production;
- включены trusted-host и security-header controls;
- Firebase project обязателен;
- административные source-triggering и mutation workflows защищены RBAC;
- tenant identity применяется внутри repository/service queries, а не только в
  URL или frontend state.

### Deterministic recommendation lifecycle

- recommendation хранит frozen calculation context и
  `recommendation-replay-v1`;
- replay восстанавливает observations, classifications, coefficients, policy и
  timestamp без network;
- API/UI показывают exact match либо field-level drift;
- operator decisions и overrides append-only;
- terminal failures доступны для управляемого replay.

### Deployment and recovery

- production Compose: `deploy/compose.production.yaml`;
- settings preflight: `scripts/check_production_config.py`;
- PostgreSQL backup: `scripts/backup_postgres.sh`;
- guarded restore: `scripts/restore_postgres.sh`;
- replay verification: `scripts/verify_recommendation_replay.py`;
- alert rules: `deploy/prometheus-alerts.yml`;
- operational procedure: `docs/production_runbook.md`.

## 4. Финальная verification evidence

| Проверка | Результат |
|---|---|
| Backend test suite | `249 passed` |
| Ruff: backend, tests, migrations, root scripts | PASS |
| Python compileall | PASS |
| Dependency lock check | PASS |
| Alembic graph | один head: `20260716_0009` |
| Python wheel build | PASS |
| Wheel ownership boundary | содержит canonical `metis/pricing/*` и compatibility `marko/pricing/__init__.py` |
| Dart formatting | 41 files, 0 changes |
| Dart analyzer | No issues found |
| Flutter tests | `21 passed` |
| Flutter release web build | PASS |
| Production settings preflight | PASS; source correctly reported as blocked |
| Production Compose and alert YAML parsing | PASS |
| Backup/restore shell syntax | PASS |
| Replay verifier CLI loading | PASS |

## 5. Activation prerequisites

Следующие пункты должны быть выполнены в реальной staging/production
infrastructure и не являются основанием объявлять implementation незавершённой:

1. Зафиксировать официальный feed, письменное разрешение или другой допустимый
   source contract; только после этого установить `PERMITTED_*` с reference.
2. Оформить текущую папку в выбранный чистый Git root и провести reviewable
   merge/commit. Deploy из неверсированной папки `копия` запрещён runbook.
3. Развернуть private PostgreSQL/Redis, Firebase project, TLS proxy, secret
   injection, log shipping и Prometheus.
4. Выполнить clean restore, rollback и recommendation replay drills с
   измеренными RPO/RTO.
5. Выполнить controlled load series и принять минимальный worker count,
   проходящий все SLO при `rho <= 0.70`.
6. Утвердить labeled comparability set, business thresholds и shadow/pilot
   acceptance report.

## 6. Финальный gate

```text
GO:
  code review and CI;
  non-network staging;
  client XLSX ingestion;
  deterministic pricing evaluation;
  stored-evidence replay;
  operator review;
  source-blocked production deployment.

NO-GO UNTIL EXTERNAL APPROVAL/DRILLS:
  live systematic Prom competitor collection;
  automatic marketplace price publishing;
  claim of completed live production load/restore validation.
```

Итоговый статус задачи: **успешно завершена инженерная ремедиация всех
доступных code/configuration/documentation hard-gates**. Исторический Stage 01
audit сохраняется без переписывания; этот документ является последующим
evidence-backed completion record.
