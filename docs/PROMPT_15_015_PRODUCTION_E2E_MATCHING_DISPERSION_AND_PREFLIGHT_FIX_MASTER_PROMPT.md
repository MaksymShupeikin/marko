# Prompt 15.015 — Production E2E, Comparability, Robust Dispersion and Preflight Fix

- Status: executable implementation master prompt
- Revision: `1.0.0`
- Revision date: `2026-07-18`
- Language: Russian with machine-oriented identifiers, formulas, pseudocode and YAML contracts
- Execution mode: `IMPLEMENTATION_AND_VERIFICATION`
- Scope owner: Marko + Metis cross-cutting production-safety remediation
- Primary target repo: `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`
- Prompt ID: `PROMPT_15_015`

## 0. Назначение документа

Этот документ является готовым заданием для последующего ИИ-агента. Он требует не
очередного аудита и не общего плана, а фактического исправления, интеграции и проверки
четырёх связанных проблем:

1. отсутствие доказанного Docker-based end-to-end запуска PostgreSQL, Redis, FastAPI,
   Celery workers, scheduler и Flutter frontend;
2. unsafe matching/comparability path, допускающего автоматическую рекомендацию при
   отсутствии критических данных о товарной идентичности, совместимости, происхождении
   и независимости продавцов;
3. unsafe relaxation в robust-dispersion v3, где двухкластерная выборка переводит
   безопасное `MANUAL_REVIEW` в автоматическое `RAISE`;
4. недостаточно строгий production preflight, который не отличает реальные значения от
   placeholder/sentinel-конфигурации.

Этот prompt не должен автоматически расширяться на изменение разрешений live Prom,
переписывание Prom parser internals или массовое применение цен. Source-access policy
должна оставаться независимым контуром. E2E обязан использовать fixture, XLSX, persisted
evidence или replay и не требовать новых live-запросов к Prom.

---

## 1. MASTER PROMPT

ТЫ — principal software engineer, production-readiness engineer, applied statistician,
data-contract architect, adversarial test engineer и release-safety reviewer проекта
Marko + Metis.

Твоя задача — выполнить полную remediation-работу по контракту `PROMPT_15_015`:
изменить код, схемы, миграции, тесты, scripts, Docker/E2E harness, API/UI contracts и
документацию так, чтобы перечисленные четыре дефекта были либо доказательно закрыты,
либо явно оставлены за fail-closed gate без ложного production claim.

### 1.1. Анти-упрощающий контракт

ОБЯЗАТЕЛЬНО:

1. НЕ думай о токенах, лимитах, ограничениях длины ответа или объёме работы.
2. НЕ упрощай задачу, не заменяй реализацию планом, аудитом, README-обзором или
   несколькими поверхностными тестами.
3. Работай до фактического terminal outcome: исправленный код, миграции, тесты,
   вариационные проверки, E2E evidence и честные gates.
4. Используй русский язык для объяснений и человекочитаемой документации; для схем,
   формул, enum, reason codes, manifest, JSON/YAML и псевдокода используй максимально
   однозначный machine-oriented язык.
5. Не считай passing unit tests доказательством production readiness.
6. Не выдавай отсутствие ошибки на одной fixture за доказательство безопасности класса
   входов.
7. После каждого смыслового изменения выполняй variation testing. После всей реализации
   проведи hostile self-review и исправь найденные дефекты до финального отчёта.
8. Не скрывай неизвестность: `UNKNOWN`, `NOT_AVAILABLE`, `BLOCKED_ENVIRONMENT` и
   `BLOCKED_DATA` предпочтительнее выдуманного `PASS`.
9. Не изменяй чужие несвязанные изменения, не очищай dirty worktree, не используй
   destructive Git commands и не пушь без отдельной прямой команды пользователя.
10. Не ослабляй существующие fail-closed gates ради зелёного теста.

### 1.2. Буквальная цель

Терминальный результат работы должен одновременно обеспечить:

```yaml
terminal_objective:
  docker_e2e:
    required: true
    meaning: >-
      Disposable isolated stack proves PostgreSQL, Redis, migrations, API,
      Celery queues/workers, scheduler, backend workflow and served Flutter
      frontend operate together.
  matching_comparability:
    required: true
    meaning: >-
      Missing or conflicting critical identity/comparability/provenance data
      can never produce an automatic actionable price.
  robust_dispersion_v3:
    required: true
    meaning: >-
      Multimodal/heterogeneous cohorts and estimator disagreement fail closed;
      an unapproved v3 policy cannot relax baseline abstention into an automatic action.
  production_preflight:
    required: true
    meaning: >-
      Placeholder, example, incomplete, unsafe or unreachable production
      configuration deterministically fails with secret-safe diagnostics.
  production_claim:
    allowed_only_if: all required hard gates have representative evidence
```

### 1.3. Входной контракт

В начале выполнения создай фактический manifest и заполни его по текущему checkout:

```yaml
execution_input:
  prompt_id: PROMPT_15_015
  repo_requested: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия
  repo_realpath: DISCOVER
  git_top_level: DISCOVER_OR_NOT_AVAILABLE
  git_commit_before: DISCOVER_OR_NOT_AVAILABLE
  branch_before: DISCOVER_OR_NOT_AVAILABLE
  dirty_paths_before: []
  operating_system: DISCOVER
  architecture: DISCOVER
  docker_binary: DISCOVER
  docker_daemon: DISCOVER
  compose_version: DISCOVER
  python_version: DISCOVER
  flutter_version: DISCOVER
  source_access_changes_authorized: false
  live_prom_requests_authorized: false
  automatic_price_application_authorized: false
```

Если requested path является wrapper без `.git`, найди реальный checkout или явно
зафиксируй `git_top_level: NOT_AVAILABLE`. Не связывай доказательства с другим физическим
репозиторием только потому, что его imports случайно доступны в virtualenv.

### 1.4. Нормативные источники в репозитории

Сначала прочитай и сверь с кодом, но не считай документы автоматически истинными:

- `AGENTS.md`;
- `docs/HOSTILE_SELF_REVIEW_STAGE_0_2026-07-17.md`, особенно missing-data matrix;
- `docs/kemp_pricing_engine.md`, особенно robust-dispersion activation status;
- `docs/production_runbook.md`;
- `compose.yaml` и `deploy/compose.production.yaml`;
- `deploy/.env.production.example`;
- `scripts/check_production_config.py`;
- `scripts/validate_robust_dispersion_decision_diff.py`;
- `backend/src/marko/services/matching.py`;
- `backend/src/marko/services/parser_models.py`;
- `backend/src/marko/services/market_collection.py`;
- `backend/src/marko/services/pricing_runs.py`;
- `backend/src/marko/services/recommendation_replay.py`;
- `backend/src/metis/pricing/types.py`;
- `backend/src/metis/pricing/engine.py`;
- `backend/src/metis/pricing/statistics.py`;
- соответствующие migrations, backend tests, frontend models/UI/tests и scripts.

### 1.5. Жёсткие границы

Не делай следующее без отдельного воспроизводимого основания:

- не переписывай Prom parser/gateway/client internals;
- не включай live Prom collection и не меняй source-access verdict;
- не включай v3 persisted activation до прохождения activation gate;
- не подменяй Firebase production auth небезопасным bypass;
- не записывай реальные secrets в Git, logs, manifests или test snapshots;
- не используй seller name как доказательство независимости продавца;
- не трактуй exact `model_id` или `sku` как достаточное доказательство коммерческой
  сопоставимости;
- не превращай `UNKNOWN` в положительный факт;
- не меняй `MANUAL_REVIEW` на automatic action только ради повышения coverage.

Допускается additive расширение parser output contract или post-parse enrichment, если
оно необходимо для воспроизводимо отсутствующего evidence. Это не разрешает переписывать
network acquisition/parsing logic без отдельного parser defect.

---

## 2. Модель безопасности и единый gate algebra

### 2.1. Классы решений

```text
ABSTAIN_ACTIONS = {MANUAL_REVIEW, INSUFFICIENT_DATA}
AUTOMATIC_ACTIONS = {RAISE, HOLD, LOWER}
SIDE_EFFECT_ACTIONS = {APPLY_PRICE, DISPATCH_LIVE_COLLECTION}
```

`HOLD` считается automatic decision, потому что он утверждает достаточность данных и
может влиять на очередь/операторское действие. Отсутствие изменения цены не превращает
его в abstention.

### 2.2. Gate algebra

Для каждого hard gate `g_j`:

```text
g_j ∈ {0, 1}
G_hard = ∏_{j=1..m} g_j
```

Soft confidence вычисляется только после hard gates:

```text
C_soft = exp( Σ_i w_i · ln(max(ε, q_i)) / Σ_i w_i )
q_i ∈ [0,1], w_i > 0, ε > 0
```

Но в trace нельзя хранить только произведение `G_hard · C_soft`, поскольку это скрывает
причину отказа. Сохраняй отдельно:

```yaml
decision_evidence:
  hard_gates: {gate_name: 0_or_1}
  failed_hard_gates: []
  unknown_hard_fields: []
  soft_factors: {factor_name: decimal_string}
  soft_confidence: decimal_string
  automatic_action_eligible: false
```

Нормативный инвариант:

```text
automatic_action_eligible ⇔ G_hard = 1 ∧ C_soft ≥ τ_conf ∧ all soft floors pass
G_hard = 0 ⇒ action ∈ ABSTAIN_ACTIONS ∧ recommended_price = null
```

Ни один высокий soft score не может компенсировать missing hard field.

### 2.3. Evidence levels

```text
E0 = assertion without located evidence
E1 = located code/config/document
E2 = deterministic component execution
E3 = adversarial/reproducible test evidence
E4 = integrated disposable-stack workflow with persisted trace/replay
E5 = representative operational/load/recovery/pilot evidence
```

Unit tests могут дать E2/E3. Docker E2E может дать E4. Production-ready claim требует
E5 для operational claims и закрытых hard gates; один локальный smoke run недостаточен.

---

## 3. PHASE 0 — Baseline, provenance and reproduction

### 3.1. Сохрани исходное состояние

Выполни read-only discovery:

```bash
pwd
git rev-parse --show-toplevel
git status --short
git branch --show-current
git rev-parse HEAD
git remote -v
command -v docker
docker version
docker compose version
python --version
flutter --version
```

Команды, которых нет, записывай как `NOT_AVAILABLE`; не подменяй их успехом другой
команды. Не печатай credentials из remotes или environment.

### 3.2. Зафиксируй baseline verification

Выполни доступные проверки в корректном project context:

```bash
cd backend
uv run pytest -q
uvx ruff check .
uv run python -m compileall -q src
uv run alembic upgrade head --sql

cd ../frontend
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
flutter build web --release
```

Если какой-либо tool отсутствует, не пропускай молча. Продолжай независимые workstreams,
но соответствующий gate оставляй `BLOCKED_ENVIRONMENT`.

### 3.3. Обязательно воспроизведи четыре исходные проблемы

Создай/используй детерминированные repro cases:

```yaml
baseline_reproductions:
  E2E-BASELINE:
    expected_before_fix: NOT_VERIFIED_OR_BLOCKED_ENVIRONMENT
  MATCH-MISSING-HARD-FIELDS:
    input: five fresh offers without required identity/comparability/provenance fields
    observed_before_fix: RAISE_with_non_null_price
    required_after_fix: ABSTAIN_with_null_price
  DISP-TWO-CLUSTERS:
    prices: [100, 101, 102, 103, 180, 181, 182, 183]
    observed_before_fix: baseline_MANUAL_REVIEW_to_v3_RAISE
    required_after_fix: v3_ABSTAIN
  PREFLIGHT-PLACEHOLDER:
    input: deploy/.env.production.example plus ENVIRONMENT=production
    observed_before_fix: exits_zero_or_accepts_placeholders
    required_after_fix: nonzero_exit_with_redacted_reason_codes
```

Не начинай исправление конкретного дефекта, пока его repro не стал executable test или
versioned fixture. Это предотвращает repair по неточной формулировке документа.

### 3.4. Baseline manifest

Создай machine-readable artifact, например:

```yaml
baseline_manifest:
  schema_version: "1.0.0"
  prompt_id: PROMPT_15_015
  checkout_identity: {}
  commands: []
  tool_versions: {}
  repro_cases: []
  hashes:
    relevant_source_files: {}
    fixtures: {}
  secrets_included: false
```

---

## 4. WORKSTREAM A — Docker-based end-to-end proof

### 4.1. Цель

Создай воспроизводимый disposable E2E contour, который действительно поднимает и
связывает:

```text
PostgreSQL → migrations → FastAPI → Redis → Celery general worker
                                  → Celery pricing worker
                                  → Celery store-sync worker
                                  → scheduler
                                  → Flutter web served container
```

E2E должен доказать не только `container is running`, а бизнес-путь с persisted state,
background task, operator-visible result и deterministic replay.

### 4.2. Docker availability branch

```text
IF docker binary exists AND daemon responds:
    continue
ELSE IF installation is allowed and can be completed safely:
    install the project/platform-approved runtime
    restart/re-probe daemon
ELSE:
    set DOCKER_E2E_GATE = BLOCKED_ENVIRONMENT
    continue all non-Docker remediation
    never report E2E PASS
```

На macOS не выбирай между Docker Desktop, Colima и организационным runtime наугад.
Сначала обнаружь существующий стандарт/документацию. Если установка требует admin
rights, license acceptance или GUI interaction, запроси только это конкретное разрешение.

### 4.3. Изоляция

Никогда не запускай destructive E2E против существующих volumes или production endpoints.

Требования:

- уникальный Compose project name, например `marko-e2e-${RUN_ID}`;
- отдельные disposable volumes;
- loopback-only published ports;
- автоматически выбранные или проверенные свободные порты;
- `ENVIRONMENT=e2e` или эквивалентный отдельный enum, не `production`;
- synthetic credentials, не production secrets;
- live Prom requests отключены;
- cleanup trap сохраняет logs/artifacts до удаления stack;
- `down --volumes --remove-orphans` применяется только к точному E2E project name;
- запрещены широкие `docker system prune` и удаление чужих ресурсов.

### 4.4. E2E profile

После inspection выбери минимальное совместимое изменение: отдельный
`compose.e2e.yaml`, profile `e2e` или test override. Не дублируй весь production compose,
если override достаточно.

E2E configuration должна включать:

- PostgreSQL healthcheck;
- Redis healthcheck;
- one-shot migration service;
- API readiness, проверяющий реальную DB;
- Celery workers с разделёнными очередями;
- scheduler singleton;
- frontend build/serve healthcheck;
- deterministic fixture/evidence loader;
- E2E runner service или host-side script;
- bounded timeouts для каждого перехода состояния.

### 4.5. Auth strategy

Не отключай authentication глобально. Выбери один доказуемо безопасный вариант:

1. Firebase Auth Emulator, изолированный в E2E profile; или
2. test-only signed-token provider, который компилируется/активируется только при
   `ENVIRONMENT=e2e` и аварийно запрещён при `production`; или
3. backend dependency override только внутри process-scoped integration runner, если
   browser-level auth не является частью данного E2E.

Добавь negative test:

```text
ENVIRONMENT=production ∧ E2E_AUTH_BYPASS=true ⇒ startup/preflight failure
```

### 4.6. Нормативный E2E business journey

Путь должен быть полностью воспроизводим без live Prom:

1. stack стартует с чистой DB;
2. migrations доходят до единственного `head`;
3. API `/live` и `/ready` возвращают `200`;
4. создаётся deterministic workspace/user/auth context;
5. импортируется versioned XLSX fixture или catalog fixture;
6. persisted/replay competitor evidence загружается с фиксированными hashes;
7. API создаёт pricing run;
8. Redis/Celery принимает и выполняет реальные background tasks в правильных queues;
9. run достигает terminal state до bounded deadline;
10. рекомендации и excluded evidence сохраняются в PostgreSQL;
11. frontend получает run/recommendation через реальный HTTP API и отображает expected
    operator state;
12. manual decision/accept/reject flow создаёт append-only audit event;
13. exact replay возвращает тот же canonical decision payload/hash;
14. повторная доставка task не создаёт duplicate recommendation;
15. stack logs и DB probes не содержат secrets.

Frontend-пункт проверяй реальным browser/integration runner, а не только unit model test:
загрузка страницы, E2E auth path, получение API state, отображение abstention/reason codes
и корректная доступность operator actions. Сохрани DOM assertions и при возможности
screenshot/trace; визуальный snapshot не заменяет semantic assertions.

### 4.7. E2E invariants

Для workflow key `k`:

```text
N_terminal(k) = N_succeeded(k) + N_failed(k) + N_cancelled(k)
N_active(k) ∈ {0,1}
N_recommendation(k, item_id, policy_version) ≤ 1
H(canonical_replay_output) = H(canonical_original_output)
```

Queue conservation на момент завершения:

```text
submitted = acknowledged_success + acknowledged_terminal_failure
            + explicitly_cancelled
active = 0
unexplained_loss = 0
```

Не требуй `failed = 0` в failure-injection cases; требуй, чтобы failure был bounded,
observable, persisted и replayable.

### 4.8. Failure injection matrix

Обязательно проверь вариации:

| ID | Инъекция | Требуемое поведение |
|---|---|---|
| E2E-F01 | PostgreSQL недоступен при старте API | readiness `503`, no false healthy |
| E2E-F02 | Redis временно недоступен | bounded retry/backoff, visible failure |
| E2E-F03 | worker killed during task | lease/fencing prevents stale commit |
| E2E-F04 | duplicate task delivery | idempotent terminal state, no duplicate output |
| E2E-F05 | malformed XLSX row | row-level rejection, batch remains auditable |
| E2E-F06 | missing persisted evidence | abstention, not invented recommendation |
| E2E-F07 | frontend starts before API ready | bounded retry/healthy eventual render |
| E2E-F08 | migration failure | dependent services do not become ready |
| E2E-F09 | scheduler duplicate attempt | singleton/lock prevents duplicate dispatch |
| E2E-F10 | replay payload tampered | integrity failure, no silent acceptance |

### 4.9. E2E evidence bundle

Сохрани без secrets:

```yaml
e2e_evidence:
  run_id: string
  compose_project: string
  git_commit: string_or_not_available
  image_ids: {}
  tool_versions: {}
  migration_head: string
  service_health: {}
  queue_counts: {}
  workflow_ids: []
  fixture_hashes: {}
  original_decision_hash: string
  replay_decision_hash: string
  failure_injection_results: []
  log_artifacts: []
  browser_assertions: []
  browser_trace_artifact: string_or_null
  cleanup_complete: true
```

### 4.10. E2E acceptance gate

```text
G_e2e = G_runtime · G_db · G_migration · G_api · G_queue · G_worker
        · G_frontend · G_workflow · G_replay · G_idempotency · G_cleanup

DOCKER_E2E_GATE = PASS ⇔ G_e2e = 1
```

Если Docker отсутствует или хотя бы один обязательный компонент заменён mock’ом,
`DOCKER_E2E_GATE` не может быть `PASS`.

---

## 5. WORKSTREAM B — Fail-closed matching and commercial comparability

### 5.1. Корневая проблема

Текущая реализация рассматривает exact `model_id`/`sku` как немедленный match, допускает
unknown brand как compatible и может использовать seller name как fallback identity. В
pricing input отсутствуют typed hard fields для OE provenance, fitment, side/position,
condition, package quantity и verified source identity. Поэтому высокий caller-supplied
confidence способен пропустить семантически недостаточный cohort.

Исправление не должно сводиться к повышению `match_confidence_min`. Числовой threshold не
заменяет отсутствующий hard contract.

### 5.2. Раздели четыре разных понятия

```text
candidate_retrieval   = предложение кандидатов с высокой полнотой;
product_identity      = доказательство, что товары относятся к одной товарной сущности;
commercial_comparability = доказательство, что цену допустимо сравнивать;
pricing_eligibility   = разрешение включить offer в автоматический pricing cohort.
```

Exact ID может повышать retrieval/identity evidence, но не должен автоматически доказывать
condition, kit composition, side, fitment, currency, seller independence или provenance.

### 5.3. Трёхзначная логика каждого измерения

Для каждого dimension `d` используй:

```text
s_d ∈ {MATCH, CONFLICT, UNKNOWN, NOT_APPLICABLE}
```

Не кодируй `UNKNOWN` как `MATCH=false` без reason; оператор и benchmark должны различать
неизвестность и доказанный конфликт.

Нормативная семантика:

```text
CONFLICT       → candidate rejected from comparable cohort;
UNKNOWN hard  → candidate may remain visible, but automatic pricing is forbidden;
MATCH          → dimension passes with evidence reference;
NOT_APPLICABLE → allowed only by versioned category policy.
```

### 5.4. Versioned comparability policy

Введи явный typed contract, название адаптируй к архитектуре, например:

```yaml
comparability_policy:
  policy_id: auto-parts-comparability-v1
  policy_hash: sha256
  category_rules:
    default:
      required_for_identity:
        - oe_reference
        - brand_or_manufacturer
      required_for_commercial_comparability:
        - condition
        - package_quantity
        - currency_presence
      conditional_dimensions:
        fitment: category_policy
        vehicle_generation: category_policy
        year_interval: category_policy
        engine: category_policy
        body_variant: category_policy
        side: category_policy
        position: category_policy
      required_for_provenance:
        - source_identity
        - acquisition_evidence_id
        - parser_contract_version
      required_for_independence:
        - stable_seller_id
```

Если authoritative category-specific policy отсутствует, используй консервативный
engineering default: неизвестное critical dimension блокирует automatic action и направляет
в `MANUAL_REVIEW`. Не придумывай бизнес-правило, что unknown side всегда конфликт или всегда
совместим.

### 5.5. Typed evidence model

Расширь boundary между Marko matching и Metis pricing так, чтобы downstream не получал
только float confidence. Минимальный логический контракт:

```yaml
comparison_evidence:
  seed_identity:
    product_id: string
    oe_raw: string_or_null
    oe_normalized: string_or_null
    oe_provenance: VERIFIED_OR_UNKNOWN
    brand: string_or_null
    manufacturer: string_or_null
  candidate_identity: {}
  dimensions:
    oe_reference: {state: MATCH_OR_CONFLICT_OR_UNKNOWN, evidence_refs: []}
    brand_manufacturer: {state: ..., evidence_refs: []}
    fitment: {state: ..., evidence_refs: []}
    vehicle_generation: {state: ..., evidence_refs: []}
    year_interval: {state: ..., evidence_refs: []}
    engine: {state: ..., evidence_refs: []}
    body_variant: {state: ..., evidence_refs: []}
    side: {state: ..., evidence_refs: []}
    position: {state: ..., evidence_refs: []}
    condition: {state: ..., evidence_refs: []}
    package_quantity: {state: ..., evidence_refs: []}
    currency_presence: {state: ..., evidence_refs: []}
  provenance:
    source_type: string_or_null
    source_record_id: string_or_null
    raw_evidence_sha256: string_or_null
    parser_contract_version: string_or_null
    verified: boolean
  seller_identity:
    stable_seller_id: string_or_null
    identity_source: string_or_null
    verified: boolean
  policy_id: string
  policy_hash: sha256
  hard_gate_result: PASS_OR_REJECT_OR_MANUAL_REVIEW
  reason_codes: []
```

Не обязательно использовать ровно эти class names, но запрещено потерять семантические
поля при переходе parser → matching → persisted comparison → pricing → replay → API/UI.

### 5.6. OE/reference contract

Нормализация OE должна быть deterministic и отдельно хранить raw value:

```text
oe_norm = Normalize(oe_raw)
```

`Normalize` может удалять разрешённые separators/case, но не должна превращать пустое
значение в валидный OE. Cross-reference match разрешён только при наличии versioned
cross-reference source/provenance.

```text
G_oe = 1 ⇔ exact verified OE match
          ∨ verified cross-reference edge(seed_oe, candidate_oe)
```

Совпадение произвольного SKU двух независимых продавцов не является OE-доказательством.

### 5.7. Exact model/SKU rule

Замени short-circuit semantics:

```python
# forbidden
if exact_model_id or exact_sku:
    return automatic_match(score=1.0)

# required concept
candidate = retrieve_by_exact_id(...)
evidence = evaluate_all_required_dimensions(seed, candidate, policy)
return classify(evidence)
```

Exact ID conflict mutation должен завершаться `REJECTED_CONFLICT`, даже если retrieval score
равен `1.0`.

### 5.8. Fitment and interval logic

Для year ranges `[a_1, a_2]` и `[b_1, b_2]`:

```text
overlap_years = max(0, min(a_2,b_2) - max(a_1,b_1) + 1)
union_years   = max(a_2,b_2) - min(a_1,b_1) + 1
year_overlap_ratio = overlap_years / union_years
```

Но threshold `τ_year` является category/business policy, а не универсальной истиной.
Неполный range даёт `UNKNOWN`, а не автоматически полный overlap.

Для categorical hard fields:

```text
both_known ∧ normalized_equal     → MATCH
both_known ∧ normalized_different → CONFLICT
otherwise                          → UNKNOWN
```

Применяй category policy для synonym/ontology mappings; version и hash mapping должны
входить в replay fingerprint.

### 5.9. Side, position, condition and package composition

Нельзя ограничиваться token-antonym check в name. Введи structured fields и provenance.

Минимальные правила:

```text
LEFT vs RIGHT              → CONFLICT
FRONT vs REAR              → CONFLICT when category says position-critical
NEW vs USED/REFURBISHED    → CONFLICT for new-item pricing cohort
quantity 1 vs kit of 2     → CONFLICT unless normalized unit-price policy explicitly allows
known vs unknown hard side → UNKNOWN → no automatic pricing
```

Не вычисляй unit price из kit автоматически без подтверждённой unit semantics.

### 5.10. Currency missingness

Raw missing currency не должна неявно становиться `UAH` до hard validation.

Храни:

```text
currency_raw: str | null
currency_normalized: ISO_4217 | null
currency_inferred: bool
currency_evidence: source/path
```

Для automatic pricing:

```text
G_currency = 1 ⇔ currency_raw present
                 ∧ normalized currency equals policy currency
                 ∧ conversion not required
```

Если продукт позже поддержит FX conversion, это отдельный versioned policy с timestamped
rate provenance; не добавляй его скрыто в этот fix.

### 5.11. Seller independence

Seller name не является stable identity и не может обеспечивать independent sample count.

```text
G_seller_identity(o_i) = 1 ⇔ stable_seller_id non-empty ∧ identity provenance verified
```

Для cohort:

```text
n_unique_verified = |{stable_seller_id_i : G_seller_identity(o_i)=1}|
```

Offers без stable ID могут отображаться в evidence/manual review, но не увеличивают
`n_unique_verified` и не участвуют в automatic cohort.

Проверь aliases:

- одинаковый seller ID, разные names;
- одинаковый name, разные verified IDs;
- пустые IDs, уникальные names;
- whitespace/case variations;
- seller rebranding;
- own-store exclusion до independence count.

### 5.12. Source provenance

`source_confidence=1` от caller не является доказательством. Derive provenance status из
located source/evidence records:

```text
G_provenance(o_i) = 1 ⇔ source_type recognized
                       ∧ source_record_id exists
                       ∧ raw_or_persisted_evidence_hash exists
                       ∧ parser/schema version exists
                       ∧ integrity verification passes
```

Soft source quality может вычисляться после `G_provenance=1`; иначе automatic eligibility
равна нулю.

Здесь `source provenance` означает техническую идентичность и целостность конкретного
evidence record. Она не изменяет и не заменяет отдельное разрешение source-access. Не
меняй `PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT` в рамках этого workstream.

### 5.13. Hard automatic eligibility

Пусть `H_c` — required hard dimensions для category `c`. Для offer `o`:

```text
G_complete(o,c) = ∏_{d∈H_c} I(s_d(o)=MATCH ∨ s_d(o)=NOT_APPLICABLE_APPROVED)
G_no_conflict(o,c) = ∏_{d∈H_c} I(s_d(o)≠CONFLICT)
G_offer(o,c) = G_complete · G_no_conflict · G_currency · G_provenance
               · G_seller_identity · G_availability · G_freshness · G_tier
```

Для recommendation cohort `O`:

```text
O_auto = {o ∈ O : G_offer(o,c)=1}
G_cohort = I(|O_auto| ≥ n_min)
           · I(unique_verified_sellers(O_auto) ≥ s_min)
           · I(n_eff(O_auto) ≥ n_eff_min)
G_auto = G_context · G_cohort · G_matching_policy · G_reproducibility
```

```text
G_auto = 0 ⇒ action ∈ ABSTAIN_ACTIONS ∧ recommended_price = null
```

### 5.14. Classification states and reason codes

Введи stable enums, например:

```text
ELIGIBLE_VERIFIED
REJECTED_IDENTITY_CONFLICT
REJECTED_COMPARABILITY_CONFLICT
MANUAL_MISSING_OE_PROVENANCE
MANUAL_MISSING_BRAND
MANUAL_MISSING_FITMENT
MANUAL_MISSING_SIDE_OR_POSITION
MANUAL_MISSING_CONDITION
MANUAL_MISSING_PACKAGE_QUANTITY
MANUAL_MISSING_STABLE_SELLER_ID
MANUAL_MISSING_SOURCE_PROVENANCE
MANUAL_MISSING_RAW_CURRENCY
MANUAL_POLICY_NOT_APPROVED
```

Reason codes должны быть доступны в DB trace, API, replay diff и operator UI.

### 5.15. Persistence and migration

После inspection выбери normalized tables или immutable JSON contract, но обеспечь:

- versioned policy ID/hash;
- raw + normalized values;
- per-dimension state and reason;
- evidence refs/hashes;
- retrieval rank и rejection/classification;
- stable seller identity source;
- source/parser/schema versions;
- recommendation run fingerprint;
- append-only trace или доказуемую immutability discipline;
- migration upgrade и downgrade/forward-recovery strategy;
- backfill, который не маркирует legacy unknown как verified.

Legacy rows должны получить `UNKNOWN_LEGACY`, а не synthetic `MATCH`.

### 5.16. Marko → Metis boundary

Сохрани доменное различие:

```text
Marko:
  acquisition, parser boundary, candidate retrieval, persisted source evidence,
  product shell, API/UI, queues

Metis:
  typed pricing evidence, hard eligibility, comparability consumption,
  pricing calculation, abstention and deterministic trace
```

Marko не должен передавать в Metis только готовый `confidence` без hard evidence.
Metis обязан повторно проверить минимальный typed contract и fail closed, даже если upstream
ошибочно пометил offer eligible.

### 5.17. API and operator UI

Добавь без ложной уверенности:

- per-offer eligibility state;
- missing/conflicting hard fields;
- policy version/hash;
- verified seller count vs visible offer count;
- automatic eligibility boolean;
- explicit `recommended_price: null` для abstention;
- operator route to correct/attach evidence или reject match;
- запрет accept/apply для ineligible automatic recommendation;
- audit event на manual override, не изменяющий исходный immutable result.

### 5.18. Mandatory adversarial matrix

Каждая variation выполняется минимум для fuzzy, exact SKU и exact model retrieval:

| ID | Mutation | Required result |
|---|---|---|
| M-001 | missing OE/reference | abstain, price null |
| M-002 | unverified cross-reference | abstain, price null |
| M-003 | conflicting verified OE | reject |
| M-004 | missing brand/manufacturer | abstain unless policy explicitly N/A |
| M-005 | conflicting brand under exact ID | reject |
| M-006 | missing fitment | abstain when category requires fitment |
| M-007 | incompatible vehicle generation | reject |
| M-008 | disjoint year intervals | reject |
| M-009 | missing one side | abstain when side-critical |
| M-010 | left vs right | reject |
| M-011 | front vs rear | reject when position-critical |
| M-012 | new vs used/refurbished | reject |
| M-013 | single vs kit quantity | reject or abstain, never silent compare |
| M-014 | source `unknown`, confidence `1` | abstain |
| M-015 | missing source record/hash | abstain |
| M-016 | blank seller IDs, unique names | abstain; unique count not inflated |
| M-017 | same seller ID, multiple names | deduplicate |
| M-018 | raw currency missing | abstain, no default UAH |
| M-019 | currency conflict | reject |
| M-020 | all critical fields verified | eligible if all other gates pass |
| M-021 | remove any one required field from M-020 | automatic → abstain |
| M-022 | add conflict to M-020 | eligible → reject |
| M-023 | permute offers | identical canonical result/hash |
| M-024 | duplicate same evidence | no eligibility/count increase |
| M-025 | five deficient offers reproducing `RAISE 920` | no automatic action, price null |

### 5.19. Metamorphic properties

Добавь property-based или generated tests:

```text
P1: removing verified hard evidence cannot increase eligibility;
P2: adding a hard conflict cannot increase eligibility or confidence;
P3: changing only seller display name cannot create independence;
P4: duplicating an observation cannot increase n_unique_verified or n_eff;
P5: permutation does not change canonical decision;
P6: UNKNOWN → MATCH may unlock eligibility only when every other gate passes;
P7: MATCH → UNKNOWN cannot preserve an automatic action;
P8: exact-ID retrieval never bypasses required dimension evaluation;
P9: replay with same inputs/policy/code contract is exact;
P10: legacy unknown rows cannot become auto-eligible via backfill.
```

### 5.20. Gold set and statistical release gate

Создай versioned labeled dataset contract. Split train/calibration/test по product/OE family,
seller and time, чтобы избежать leakage.

Ключевые метрики:

```text
unsafe_auto_rate = N(automatic on non-comparable/insufficient evidence) / N(automatic)
comparability_precision = TP_comparable / (TP_comparable + FP_comparable)
conflict_recall = TP_conflict / (TP_conflict + FN_conflict)
auto_coverage = N(automatic) / N(total eligible opportunities)
abstention_rate = N(abstain) / N(total)
```

Safety metric имеет приоритет над coverage. Если наблюдается `x=0` unsafe событий на `N`
независимых representative случаях, односторонняя верхняя граница при confidence
`1-α`:

```text
p_upper = 1 - α^(1/N)
```

Для target `p_upper ≤ ε` требуется:

```text
N ≥ ln(α) / ln(1-ε)
```

Не выбирай `ε`, `α` и loss weights за клиента. Запроси их как business release policy;
до утверждения используй строгий engineering gate `unsafe_auto_count = 0` на всей
adversarial matrix и оставь representative activation `BLOCKED_DATA`.

### 5.21. Matching acceptance gate

```text
MATCHING_IMPLEMENTATION_GATE = PASS iff:
  baseline RAISE-920 repro is killed;
  every mandatory hard-field mutation abstains/rejects;
  exact IDs cannot bypass conflicts/unknowns;
  seller independence uses verified stable IDs only;
  raw missing currency remains missing;
  source provenance is derived, not caller asserted;
  persistence/API/UI/replay preserve evidence and reason codes;
  legacy data fails closed;
  all regression/property/mutation tests pass.
```

`MATCHING_PRODUCTION_ACTIVATION` отдельно остаётся `BLOCKED_DATA`, пока нет approved
domain policy и representative gold-set evidence. Не смешивай implementation PASS с
production activation.

---

## 6. WORKSTREAM C — Robust-dispersion v3 safety remediation

### 6.1. Корневая статистическая причина

Qn/Sn/MAD являются robust scale estimators, но малый scale не доказывает unimodality.
Для выборки:

```text
[100, 101, 102, 103, 180, 181, 182, 183]
```

Qn может быть малым, поскольку большинство информативных pairwise distances внутри
кластеров малы. Это не ошибка формулы Qn; это mismatch между estimator и вопросом
«представляет ли cohort один сопоставимый рынок?».

Поэтому запрещено «исправлять» дефект заменой константы Qn, случайным threshold tuning или
возвратом к одному MAD. Нужен отдельный heterogeneity/multimodality gate плюс
консервативная baseline-dominance policy.

### 6.2. Входная выборка

Статистические gates применяй после:

1. hard comparability eligibility;
2. verified seller deduplication;
3. currency/tier normalization;
4. exclusion owned/used/stale/conflicting evidence;

Но сохраняй pre-clean и post-clean profiles, чтобы outlier cleaning не скрыл multimodal
структуру.

Пусть:

```text
p_i > 0
z_i = ln(p_i)
z_(1) ≤ ... ≤ z_(n)
```

Log-space предпочтителен для multiplicative price differences. Не смешивай scale в UAH и
log scale в одном безразмерном threshold.

### 6.3. Estimator disagreement gate

Для Gaussian-consistent scale estimates:

```text
S = {CV_IQR, CV_MAD, CV_Sn, CV_Qn}
cv_min = min(S)
cv_max = max(S)
cv_med = median(S)
D_abs = cv_max - cv_min
D_rel = D_abs / max(cv_med, ε)
```

Current profile уже содержит близкие поля; используй их или расширь versioned trace.

```text
G_estimator_agreement = I(D_rel ≤ τ_disagreement)
```

`τ_disagreement` не выбирай по одной synthetic case. Добавь conservative default для
shadow/manual review и calibration procedure на representative dataset.

### 6.4. Deterministic two-cluster diagnostic

Реализуй deterministic O(n log n) diagnostic в log-price space. Для каждого допустимого
split `k`, где обе части имеют минимум `m_min` independent sellers:

```text
L_k = {z_(1), ..., z_(k)}
R_k = {z_(k+1), ..., z_(n)}

J1 = Σ_i |z_i - median(z)|
J2(k) = Σ_{z∈L_k}|z - median(L_k)| + Σ_{z∈R_k}|z - median(R_k)|

improvement(k) = 1 - J2(k) / max(J1, ε)
balance(k) = min(|L_k|, |R_k|) / n
separation(k) = |median(R_k)-median(L_k)| /
                max(Qn(L_k), Qn(R_k), σ_floor)
gap(k) = z_(k+1)-z_(k)
```

Выбери `k*` детерминированно: максимальный improvement, затем максимальная separation,
затем минимальный index как tie-breaker.

Heterogeneity flag:

```text
cluster_flag =
    improvement(k*) ≥ τ_improvement
    ∧ balance(k*) ≥ τ_balance
    ∧ separation(k*) ≥ τ_separation
    ∧ gap(k*) ≥ τ_gap
```

Thresholds являются versioned policy. До representative calibration выбери conservative
engineering values, которые ловят обязательную two-cluster fixture и не активируют v3.
Запиши rationale и sensitivity grid; не выдавай defaults за statistically calibrated truth.

### 6.5. Cluster diagnostic edge cases

Обработай явно:

- `n < 2·m_min` → diagnostic unavailable, not false negative;
- all equal → no cluster, zero dispersion allowed if other gates pass;
- one extreme outlier → не классифицировать как balanced second market cluster;
- duplicated sellers → deduplicate до diagnostic;
- zero/negative/non-finite prices → hard reject;
- ties around split → deterministic ordering;
- partial degeneracy → existing fail-closed gate remains;
- unequal clusters → policy-defined balance;
- three clusters → at least one heterogeneity flag или manual review;
- scale/translation in log-space → consistent result under multiplicative rescaling.

### 6.6. Baseline safety dominance

До доказанной activation v3 обязана быть не менее консервативной, чем approved baseline
по классу automatic/abstain:

```text
A_v2 = I(action_v2 ∈ AUTOMATIC_ACTIONS)
A_v3 = I(action_v3 ∈ AUTOMATIC_ACTIONS)

unsafe_relaxation = I(A_v2=0 ∧ A_v3=1)
G_non_relaxation = 1 - unsafe_relaxation
```

Нормативно для unapproved/shadow v3:

```text
A_v3 = 1 ⇒ A_v2 = 1 ∧ G_v3_specific = 1
```

Это не утверждает, что v2 статистически идеален. Это release-safety constraint: новый
неоткалиброванный estimator не получает право автоматически отменить baseline abstention.

Если в будущем representative evidence докажет безопасное улучшение coverage, исключение
должно быть отдельной versioned policy с approved decision artifact.

### 6.7. Объединённый v3 hard gate

```text
G_v3_specific = G_capacity
                · G_no_partial_degeneracy
                · G_estimator_agreement
                · G_no_cluster_flag
                · G_sensitivity
                · G_non_relaxation

G_v3_specific = 0 ⇒ action ∈ ABSTAIN_ACTIONS ∧ recommended_price = null
```

Причины должны быть различимы:

```text
ROBUST_SCALE_CAPACITY_EXCEEDED
ROBUST_SCALE_PARTIAL_DEGENERACY
ROBUST_ESTIMATOR_DISAGREEMENT
ROBUST_MULTIMODAL_COHORT
ROBUST_ESTIMATOR_SENSITIVITY
ROBUST_BASELINE_ABSTENTION_NOT_RELAXABLE
ROBUST_DIAGNOSTIC_UNAVAILABLE
```

Не своди все случаи к generic `LOW_CONFIDENCE`.

### 6.8. Policy/versioning/replay

Изменение decision semantics требует нового immutable version identity. Не меняй молча
результаты уже сохранённой `pricing-v3-robust-dispersion`.

Выбери и документируй один вариант:

- новая policy version, например `pricing-v3.1-heterogeneity-gated`; или
- новая major version, если repository version contract этого требует.

Fingerprint должен включать:

```yaml
robust_policy_fingerprint:
  policy_version: string
  selected_scale_method: qn_or_other
  profile_version: string
  correction_profile_version: string
  cluster_diagnostic_version: string
  thresholds:
    disagreement: decimal
    improvement: decimal
    balance: decimal
    separation: decimal
    gap: decimal
    sigma_floor: decimal
  baseline_policy_version: string
  non_relaxation_enabled: true
  code_commit: string_or_not_available
```

Replay старых v1/v2/v3 recommendations должен сохранить старую semantics; новый policy
используется только для новых runs/explicit preview.

### 6.9. Decision-diff script correctness

Исправь contract `scripts/validate_robust_dispersion_decision_diff.py`:

- `validation_gate` сообщает, что script и cases исполнились корректно;
- `safety_gate` не может быть `PASS`, если `unsafe_relaxation_count > 0`;
- `activation_gate` не может быть `PASS` без representative dataset;
- exit code должен быть nonzero для contract-breaking unsafe relaxation в обязательной
  matrix;
- JSON stdout deterministic, diagnostics stderr, no secrets;
- CLI принимает versioned dataset path и policy configs;
- synthetic PASS не маскирует activation `BLOCKED_DATA`.

Пример разделённых статусов:

```yaml
decision_diff_result:
  execution_status: PASS
  synthetic_safety_gate: PASS_OR_NO_GO
  representative_dataset: false
  activation_gate: BLOCKED_DATA
  unsafe_relaxation_count: integer
```

### 6.10. Mandatory robust variation matrix

| ID | Price shape | Required behavior before activation |
|---|---|---|
| R-001 | clean tight grid | deterministic, compare v2/v3 |
| R-002 | all equal | no false cluster; other gates decide |
| R-003 | partial degeneracy | abstain |
| R-004 | single high outlier | robust cleaning; no balanced-cluster false positive |
| R-005 | right skew | deterministic sensitivity result |
| R-006 | balanced two clusters | abstain, `ROBUST_MULTIMODAL_COHORT` |
| R-007 | unequal 2/6 clusters | policy sensitivity recorded |
| R-008 | three clusters | abstain/heterogeneity |
| R-009 | small n=3 | abstain unless approved small-n policy |
| R-010 | small n=4 + outlier | abstain |
| R-011 | weak matching evidence | matching gate abstains before dispersion |
| R-012 | high global dispersion | abstain |
| R-013 | duplicate sellers | invariant after dedup |
| R-014 | prices multiplied by 10 | same dimensionless classification/action ratio |
| R-015 | permuted prices/offers | exact canonical result |
| R-016 | one price removed from cluster boundary | no discontinuous unsafe auto transition |
| R-017 | boundary ±ε around every threshold | deterministic documented side |
| R-018 | non-finite/zero/negative | hard reject |
| R-019 | v2 abstain, v3 would auto | v3 forced abstain |
| R-020 | representative labeled cohort | release metrics and confidence bounds |

### 6.11. Mutation tests

Существующие mutations формул Sn/Qn должны остаться killed. Добавь mutations:

- отключить cluster gate;
- инвертировать `≥/≤` threshold;
- позволить split с singleton cluster;
- считать balance по offers до seller dedup;
- использовать raw prices вместо log prices;
- убрать baseline non-relaxation;
- заменить maximum separation на minimum;
- потерять policy version/hash в replay;
- разрешить `unsafe_relaxation_count > 0` при exit code 0.

Каждая mutation должна быть убита конкретным test node.

### 6.12. Performance

Sn/Qn могут иметь O(n²) memory/time. Сохрани существующий cohort cap и benchmark.
Новый cluster diagnostic должен быть O(n log n) после sorting и желательно O(n) scan с
prefix/suffix summaries, либо bounded O(n²) только при доказанном малом cap.

Измеряй:

```text
T(n), peak_memory(n), n ∈ {5,10,25,50,100,250,500}
```

Не утверждай production capacity по microbenchmark. Используй его для regression budget.

### 6.13. Statistical activation gate

На representative holdout вычисли:

```text
unsafe_relaxation_rate = N(v2_abstain ∧ v3_auto ∧ outcome_unsafe) / N(evaluable)
false_auto_rate_v3
abstention_rate_v3
coverage_delta = auto_coverage_v3 - auto_coverage_v2
loss_delta = mean(L_v3 - L_v2)
```

Loss function должен быть утверждён:

```text
L = c_false_raise·I(false RAISE)
  + c_false_lower·I(false LOWER)
  + c_false_hold·I(false HOLD)
  + c_abstain·I(unnecessary abstention)
```

Не назначай `c_*` самостоятельно как бизнес-истину. До approval safety ordering:

```text
c_false_automatic >> c_unnecessary_abstention
```

Activation разрешена, только если одновременно:

```text
unsafe_relaxation_count_required_matrix = 0
upper_confidence_bound(false_auto_rate_v3) ≤ approved_epsilon
loss_delta_upper_bound ≤ approved_noninferiority_margin
all critical slices pass
replay exactness = 100%
feature flag rollout and rollback tested
```

### 6.14. Robust-dispersion acceptance

```text
ROBUST_V3_IMPLEMENTATION_GATE = PASS iff:
  two-cluster repro abstains with explicit reason;
  estimator disagreement and heterogeneity are traced;
  baseline abstention cannot be silently relaxed;
  decision-diff exit/status semantics are truthful;
  required variations and mutations pass;
  old replay versions remain exact;
  new policy remains disabled for persisted production runs by default.
```

```text
ROBUST_V3_ACTIVATION_GATE = PASS only with representative approved evidence;
otherwise BLOCKED_DATA, not FAIL and not PASS.
```

---

## 7. WORKSTREAM D — Strict production preflight

### 7.1. Корневая проблема

Текущий checker в основном конструирует `Settings`, проверяет `is_production` и печатает
часть derived state. Syntactically valid placeholders вроде `api.example.com`,
`your-firebase-project` и `replace` могут пройти. Пример `.env` также не является
self-contained input для documented command, если в нём нет `ENVIRONMENT=production`.

### 7.2. Раздели template и valid config

`deploy/.env.production.example` должен быть безопасным template и обязан FAIL preflight,
пока placeholders не заменены. Добавь явный header:

```text
# TEMPLATE_ONLY=1
# This file is intentionally invalid for deployment until every REQUIRED value is replaced.
ENVIRONMENT=production
```

Не добавляй реальные secrets. Documented preflight command должен принимать explicit
`--env-file`, а не зависеть от случайно экспортированного shell environment.

### 7.3. Validation layers

Раздели preflight на уровни:

```text
P0_INPUT_SOURCE
P1_STATIC_SCHEMA
P2_PLACEHOLDER_AND_SECRET_HYGIENE
P3_TOPOLOGY_AND_SECURITY
P4_DEPENDENCY_CONNECTIVITY
P5_DATABASE_SCHEMA
P6_RUNTIME_SERVICES
P7_WORKFLOW_SMOKE
```

Итог:

```text
G_preflight = ∏_{k=0..7} P_k
PRODUCTION_PREFLIGHT = PASS ⇔ G_preflight = 1
```

Static mode может завершиться без network, но не должен называться полным production
preflight.

### 7.4. Explicit CLI contract

Спроектируй CLI, совместимый с repository conventions, например:

```text
check_production_config.py \
  --env-file /secure/path/marko.env \
  --mode static|connectivity|full \
  --format human|json \
  --output-json artifacts/preflight.json
```

Требования:

- explicit file path;
- no implicit `.env` discovery in production mode;
- clear precedence env-file vs process env;
- detect duplicate keys;
- reject unreadable/world-readable secret file according to platform capability;
- never print secret values or full credential-bearing DSNs;
- stable error codes;
- exit `0` only when requested mode fully passes;
- distinct nonzero exit for validation failure vs tool/internal error;
- deterministic JSON ordering/schema version.

### 7.5. Placeholder detection

Нормализуй candidate value только для detection, не изменяя фактическую config:

```text
v_norm = casefold(trim(v))
```

Минимальные sentinel classes:

```text
empty/null
replace, changeme, change-me, todo, tbd
example, example.com, *.example.com
your-*, your_*, <...>, ${...}
USER, PASSWORD, PRIVATE_*_HOST
localhost/127.0.0.1 when field policy forbids local production endpoint
known sample credentials from repository templates
```

Не используй один global regex без field context. Например Firebase API key не является
серверным secret, но всё равно не должна быть `replace`; loopback допустим для reverse
proxy bind, но не обязательно допустим для managed DB endpoint.

### 7.6. Field policy registry

Определи typed policy:

```yaml
production_field_policy:
  DATABASE_URL:
    required: true
    secret: true
    parser: sqlalchemy_url
    allowed_schemes: [postgresql+asyncpg]
    placeholder_forbidden: true
    connectivity_probe: postgres_select_1
  CELERY_BROKER_URL:
    required: true
    secret: true
    parser: redis_url
    allowed_schemes: [rediss]
    placeholder_forbidden: true
    connectivity_probe: redis_ping
  CELERY_RESULT_BACKEND:
    required: true
    secret: true
    parser: redis_url
    allowed_schemes: [rediss]
    placeholder_forbidden: true
  ALLOWED_HOSTS:
    required: true
    wildcard_forbidden: true
    example_domain_forbidden: true
  CORS_ORIGINS:
    required: true
    https_required: true
    wildcard_forbidden: true
    example_domain_forbidden: true
  FIREBASE_PROJECT_ID:
    required: true
    placeholder_forbidden: true
  PUBLIC_API_BASE_URL:
    required: true
    https_required: true
    example_domain_forbidden: true
```

Список дополни после inspection production compose/frontend args. Не требуй entropy от
public identifiers; валидируй формат и sentinel status.

Требование `rediss://` основано на текущем hardened production template. Если утверждённая
deployment topology использует private-network Redis без TLS, не ослабляй проверку молча:
зафиксируй отдельную approved topology policy и тесты допустимого исключения.

### 7.7. Static security assertions

Production config должна fail closed, если:

- `ENVIRONMENT != production`;
- `DEBUG=true`;
- effective API docs enabled;
- wildcard allowed hosts;
- wildcard credentialed CORS;
- non-HTTPS public origins без explicit local exception, запрещённого в production;
- placeholder endpoints/IDs;
- required value missing;
- permitted source verdict не имеет reference — существующее правило не ослаблять;
- E2E auth bypass включён;
- feature flag robust v3 включён без activation artifact/version;
- database/broker URL имеет unsupported scheme;
- secret-bearing URI попадает в diagnostic output;
- production config file случайно tracked Git’ом.

### 7.8. Connectivity and schema assertions

В `connectivity/full` mode выполняй bounded probes:

```text
DNS resolution
TCP connect with timeout
TLS verification where required
PostgreSQL SELECT 1
Redis PING for broker and result backend
Alembic current == exactly one head
API live/ready
Celery inspect/ping for every required queue worker
scheduler singleton evidence
frontend HTTP health and expected build metadata
```

Не печатай connection strings в exception. Redact userinfo/query credentials.

### 7.9. Workflow smoke

`full` mode должен использовать тот же safe fixture/replay contour, что E2E, и доказать:

- import accepted;
- background task completed;
- matching missing-data gate abstains;
- robust two-cluster gate abstains;
- recommendation persisted;
- replay exact;
- no live Prom request performed;
- no automatic price application performed.

### 7.10. Structured result

```yaml
production_preflight_result:
  schema_version: "1.0.0"
  requested_mode: full
  environment: production
  config_source_realpath: redacted_or_safe_path
  config_sha256: sha256_without_contents
  git_commit: string_or_not_available
  checks:
    - id: PREFLIGHT_ENVIRONMENT
      status: PASS_OR_FAIL_OR_BLOCKED
      reason_codes: []
      secret_safe: true
  passed: false
  blockers: []
  warnings: []
  secrets_emitted: false
```

### 7.11. Negative variation matrix

Каждая строка обязана завершиться nonzero и конкретным reason code:

| ID | Variation |
|---|---|
| P-001 | missing `ENVIRONMENT` |
| P-002 | `ENVIRONMENT=development` |
| P-003 | `DEBUG=true` |
| P-004 | API docs effectively enabled |
| P-005 | `DATABASE_URL` from example template |
| P-006 | DB user/password literally `USER/PASSWORD` |
| P-007 | DB host `PRIVATE_POSTGRES_HOST` |
| P-008 | Redis host `PRIVATE_REDIS_HOST` |
| P-009 | unsupported `redis://` when TLS policy requires `rediss://` |
| P-010 | `ALLOWED_HOSTS=api.example.com` |
| P-011 | wildcard host |
| P-012 | `CORS_ORIGINS=https://app.example.com` |
| P-013 | HTTP production origin |
| P-014 | `FIREBASE_PROJECT_ID=your-firebase-project` |
| P-015 | Firebase fields equal `replace` |
| P-016 | duplicate env key with conflicting values |
| P-017 | malformed URL/DSN |
| P-018 | unreachable DB |
| P-019 | reachable DB but migration behind head |
| P-020 | Redis reachable but wrong auth/TLS |
| P-021 | missing required Celery worker/queue |
| P-022 | duplicate scheduler |
| P-023 | E2E auth bypass in production |
| P-024 | robust v3 enabled without activation artifact |
| P-025 | config file tracked or secret diagnostic leak |

Positive variations:

- synthetic isolated E2E config passes `static` and E2E-specific preflight;
- secret-injected representative production-like config passes static checks;
- connectivity mode passes against disposable TLS-equivalent dependencies if available;
- full mode passes only after workflow smoke.

### 7.12. Secret-leak tests

Inject unique canary secrets:

```text
CANARY_DB_PASSWORD_7f...
CANARY_REDIS_PASSWORD_9a...
```

Capture stdout/stderr/JSON/logs and assert canaries never appear. Проверяй также URL-encoded
forms. Не сохраняй canaries в committed snapshots.

### 7.13. Preflight acceptance

```text
PREFLIGHT_IMPLEMENTATION_GATE = PASS iff:
  production example is explicitly template-only and fails until replaced;
  ENVIRONMENT=production is present/documented;
  every placeholder variation fails;
  valid non-placeholder config passes static mode;
  requested connectivity/full modes cannot pass with skipped checks;
  secrets never appear in output;
  JSON schema and exit codes are stable;
  runbook commands exactly match executable CLI;
  robust-v3 and E2E-auth activation constraints are enforced.
```

---

## 8. Cross-cutting implementation contract

### 8.1. Schema and migration discipline

Перед migration:

1. построй current head graph;
2. проверь, что существует ровно один head;
3. выбери новый revision после актуального head;
4. проверь upgrade на чистой PostgreSQL DB;
5. проверь upgrade на representative pre-fix snapshot, если fixture доступна;
6. не backfill unknown как verified;
7. сгенерируй offline SQL;
8. определи downgrade или документированный forward-only recovery;
9. проверь indexes/constraints на ожидаемых query paths;
10. сохрани row counts и integrity probes до/после.

Нельзя считать SQLite достаточной заменой PostgreSQL для JSON, enum, partial unique index,
locking, transaction isolation, outbox или fencing semantics.

### 8.2. Deterministic fingerprint

Для каждой новой recommendation сохраняй canonical fingerprint:

```text
F = SHA256(canonical_json({
  input_context,
  eligible_and_excluded_observation_ids,
  raw_evidence_hashes,
  matching_policy_id_and_hash,
  comparability_dimension_results,
  tier_coefficients_and_versions,
  pricing_policy_and_hash,
  robust_diagnostic_policy_and_thresholds,
  parser_schema_version,
  code_commit_or_build_identity,
  rounding_policy_version
}))
```

Canonical JSON должен иметь deterministic key ordering, numeric representation, timezone и
Unicode normalization. Secret values не входят в fingerprint.

### 8.3. Replay

Replay обязан:

- выбирать implementation по persisted version;
- не обращаться к live network;
- не заменять missing legacy fields новыми defaults;
- выдавать exact match или structured drift;
- сравнивать action, price, reasons, hard gates, cohorts, policy hashes и fingerprint;
- сохранять original и replay artifacts без мутации original history.

### 8.4. API compatibility

Если добавляются обязательные response fields:

- используй additive backward-compatible change или versioned endpoint/schema;
- сгенерируй OpenAPI и проверь schema;
- обнови frontend models/API tests;
- запрети silent default, превращающий отсутствующий hard field в verified;
- документируй nullable vs absent semantics.

### 8.5. Observability

Минимальные counters/histograms/events:

```text
matching_candidates_total{classification,reason}
matching_automatic_eligible_total{policy_version}
matching_missing_hard_field_total{field,category}
pricing_abstention_total{reason,policy_version}
pricing_robust_cluster_flag_total{policy_version}
pricing_unsafe_relaxation_blocked_total{baseline,candidate}
preflight_check_total{check,status}
e2e_workflow_duration_seconds{stage}
celery_task_terminal_total{queue,status}
replay_exact_match_total{policy_version}
```

Не включай SKU, URLs, tokens, credentials или unbounded free text в metric labels.

### 8.6. Feature flags

Flags должны иметь fail-closed defaults:

```text
PRICING_V3_ROBUST_DISPERSION_ENABLED=false
PRICING_COMPARABILITY_V1_AUTOMATIC_ENABLED=false
E2E_AUTH_BYPASS=false
```

Названия адаптируй к существующей config. Production activation требует versioned
activation artifact, а не только boolean env var.

### 8.7. Rollback

Опиши и протестируй:

- выключение новых automatic eligibility/v3 flags;
- возврат к shadow/manual review без потери evidence;
- draining Celery queues;
- compatibility старого API/frontend;
- replay старых versions;
- schema rollback или forward-compatible safe state;
- отсутствие автоматического применения цен во время rollback.

---

## 9. Пошаговая последовательность выполнения

Не перескакивай через steps. После каждого step обновляй execution ledger.

### STEP 00 — Scope/provenance lock

Deliverables:

- input manifest;
- Git/worktree snapshot;
- tool availability;
- exact physical repo identity;
- list of user-owned dirty paths to preserve.

Stop gate:

```text
STOP_GATE_STEP_00 = PASS if target checkout is unambiguous;
otherwise BLOCKED_REPOSITORY_IDENTITY.
```

### STEP 01 — Executable baseline reproductions

Создай tests/fixtures для четырёх исходных problems. Baseline tests могут быть expected
failure до fix, но должны детерминированно воспроизводить defect.

Stop gate:

```text
STOP_GATE_STEP_01 = PASS iff all four baseline states are located and reproducible;
environment-only Docker absence may be BLOCKED_ENVIRONMENT while other repros proceed.
```

### STEP 02 — Production preflight static hardening

Сначала исправь template/CLI/static validation. Это даёт безопасную конфигурационную
основу для E2E и не зависит от domain matching decisions.

Required output:

- explicit env-file CLI;
- placeholder registry;
- secret-safe output;
- negative matrix;
- corrected runbook/example.

### STEP 03 — Disposable E2E harness foundation

Создай isolated Compose override/profile, fixture loader, E2E auth strategy, bounded runner
и cleanup. Если runtime отсутствует, code/harness можно завершить, но execution gate остаётся
blocked до реального запуска.

### STEP 04 — Matching/comparability typed contract

Реализуй:

- typed dimension states/evidence;
- versioned policy;
- exact-ID non-bypass;
- stable seller identity;
- source/currency missingness;
- hard eligibility in both Marko and Metis boundaries.

Не жди бизнес-решения, чтобы реализовать fail-closed `UNKNOWN → MANUAL_REVIEW`; business
approval требуется только для расширения automatic eligibility.

### STEP 05 — Persistence, API and frontend integration

Добавь migration, repositories/services, API schema, UI reason visibility, operator manual
path и immutable audit trail. Legacy rows fail closed.

### STEP 06 — Matching hostile variation and gold-set harness

Выполни M-001..M-025, metamorphic/property tests, exact-ID conflict probes, replay tests и
benchmark schema. Исправляй код, а не expected values, если expected values выражают hard
safety invariant.

### STEP 07 — Robust heterogeneity gate

Реализуй estimator disagreement, log-space cluster diagnostic, baseline non-relaxation,
reason codes, version/fingerprint и truthful decision-diff CLI.

### STEP 08 — Robust variations, mutations and performance

Выполни R-001..R-020, threshold boundary grid, mutations и benchmark. Убедись, что
two-cluster case не становится automatic после незначительной permutation/rescale.

### STEP 09 — Full integrated Docker E2E

После merge всех fixes подними чистый stack и выполни business journey + failure
injections. Не используй уже заполненную developer DB как substitute чистой миграции.

### STEP 10 — Full production-like preflight

На disposable stack выполни `static`, `connectivity`, `full`; проверь negative configs и
secret canaries. Production endpoints/secrets не требуются для E4 local evidence.

### STEP 11 — Regression and compatibility sweep

Выполни backend/frontend/unit/integration/replay/OpenAPI/migration/build checks. Сравни
baseline и after-fix behavior. Любой unexpected automatic-action increase разбери по case.

### STEP 12 — Hostile self-review and repair loop

Отдельно атакуй собственную реализацию:

- можно ли обойти gate через exact ID?
- можно ли поставить caller confidence=1?
- можно ли создать независимость уникальными names?
- можно ли default’ом заполнить currency?
- можно ли включить v3 одним env flag без artifact?
- можно ли получить cluster false negative permutation?
- можно ли пройти preflight с новым placeholder spelling?
- можно ли вывести secret через exception?
- можно ли назвать E2E PASS с mocked queue/DB?
- можно ли переиспользовать stale worker fencing token?

Каждую найденную проблему исправь и повтори relevant matrix. Не заканчивай на списке
дефектов.

### STEP 13 — Final gates and handoff

Сформируй truthful status каждого независимого gate. Не усредняй их.

---

## 10. Variation testing protocol — обязательно, не опционально

### 10.1. Variation dimensions

Для каждого critical case варьируй минимум:

```yaml
variation_dimensions:
  presence: [present, missing, null, empty, whitespace]
  provenance: [verified, unverified, tampered, stale]
  identity: [exact, crossref, fuzzy, conflict, unknown]
  seller: [stable_unique, duplicate_id, blank_id, alias, owned]
  currency: [UAH, other, missing, malformed]
  cohort_shape: [tight, skewed, outlier, two_cluster, three_cluster, degenerate]
  sample_size: [0, 1, 2, 3, 4, 5, 8, 20, 100, 500, over_cap]
  ordering: [original, reversed, random_permutations]
  scale: [x0.1, x1, x10, x1000]
  delivery: [once, duplicate, retry, worker_loss]
  environment: [development, e2e, production]
  config: [valid, missing, placeholder, malformed, unreachable]
```

### 10.2. Pairwise and interaction coverage

Не ограничивайся one-factor-at-a-time. Минимум pairwise combinations для:

- exact ID × conflict dimension;
- missing field × high confidence;
- blank seller ID × multiple names;
- two-cluster × duplicate sellers;
- two-cluster × small n;
- v3 flag × missing activation artifact;
- production × E2E auth bypass;
- placeholder × syntactically valid URL;
- retry × stale fencing token;
- replay × policy version mismatch.

### 10.3. Boundary variations

Для каждого threshold `τ` тестируй:

```text
τ - ε, τ, τ + ε
```

где `ε` соответствует decimal precision contract, а не binary float artifact. Проверяй
rounding/tick boundaries отдельно.

### 10.4. Randomized/property testing

Используй fixed seeds и сохраняй minimal counterexample. Randomized tests дополняют, но не
заменяют deterministic fixtures. Любой найденный counterexample превращай в постоянный
regression test.

### 10.5. Mutation testing

Mutation score сам по себе не production proof. Для critical invariants required score:

```text
critical_mutations_survived = 0
```

Все survivors классифицируй: equivalent, unreachable или test gap. Не удаляй mutation из
набора только потому, что её трудно убить.

---

## 11. Полная verification matrix

Команды адаптируй к обнаруженному toolchain, но не сокращай coverage:

```bash
# Backend
cd backend
uv run pytest -q
uvx ruff check .
uv run python -m compileall -q src
uv run alembic heads
uv run alembic upgrade head --sql

# Focused safety
uv run pytest -q \
  tests/test_matching.py \
  tests/test_pricing_engine.py \
  tests/test_pricing_engine_matrix.py \
  tests/test_robust_dispersion.py \
  tests/test_robust_dispersion_engine.py \
  tests/test_robust_dispersion_variations.py \
  tests/test_recommendation_replay.py

cd ..
backend/.venv/bin/python scripts/run_robust_dispersion_mutation_probes.py
backend/.venv/bin/python scripts/validate_robust_dispersion_decision_diff.py
backend/.venv/bin/python scripts/benchmark_robust_dispersion.py --repeats 5

# Frontend
cd frontend
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
flutter build web --release
cd ..

# Compose static
docker compose config --quiet
docker compose -f compose.yaml -f compose.e2e.yaml config --quiet
docker compose --env-file PATH_TO_REDACTED_ENV \
  -f deploy/compose.production.yaml config --quiet

# Isolated E2E — use exact implemented scripts/project name
scripts/e2e_up.sh
scripts/e2e_verify.sh
scripts/e2e_failure_matrix.sh
scripts/e2e_down.sh

# Preflight
backend/.venv/bin/python scripts/check_production_config.py \
  --env-file PATH --mode static --format json
backend/.venv/bin/python scripts/check_production_config.py \
  --env-file PATH --mode full --format json
```

Не копируй эти command names слепо, если implementation выбрала Python runner вместо shell
scripts. Обнови этот список и runbook так, чтобы документация совпадала с реально
исполняемыми entrypoints.

---

## 12. Acceptance criteria — machine-testable

### AC-E2E

```yaml
AC_E2E:
  docker_runtime_real: true
  postgres_real: true
  redis_real: true
  celery_workers_real: true
  api_real: true
  frontend_served: true
  clean_migration: PASS
  business_workflow: PASS
  replay_exact: true
  duplicate_delivery_safe: true
  failure_matrix_passed: true
  live_prom_requests: 0
  automatic_price_applications: 0
  cleanup_complete: true
```

### AC-MATCHING

```yaml
AC_MATCHING:
  raise_920_missing_data_reproduced_before: true
  raise_920_missing_data_killed_after: true
  missing_required_field_action: ABSTAIN
  missing_required_field_price: null
  exact_id_bypass_possible: false
  stable_seller_id_required_for_independence: true
  caller_confidence_can_fake_provenance: false
  missing_currency_defaults_to_uah: false
  mandatory_variations_passed: true
  critical_mutations_survived: 0
  replay_preserves_contract: true
```

### AC-ROBUST

```yaml
AC_ROBUST:
  two_cluster_action: MANUAL_REVIEW_OR_INSUFFICIENT_DATA
  two_cluster_price: null
  explicit_heterogeneity_reason: true
  unsafe_relaxation_count_required_matrix: 0
  estimator_disagreement_traced: true
  policy_versioned: true
  old_replay_exact: true
  production_feature_default: false
  representative_activation_evidence: PRESENT_OR_BLOCKED_DATA
```

### AC-PREFLIGHT

```yaml
AC_PREFLIGHT:
  example_env_self_describes_template: true
  example_env_contains_environment_production: true
  example_env_passes_preflight_without_replacement: false
  placeholder_variations_rejected: 25
  valid_static_config_passes: true
  skipped_connectivity_cannot_pass_full: true
  secret_canaries_emitted: 0
  stable_json_schema: true
  documented_commands_executable: true
```

### AC-REGRESSION

```yaml
AC_REGRESSION:
  backend_tests: PASS
  frontend_format: PASS
  frontend_analyze: PASS
  frontend_tests: PASS
  frontend_release_build: PASS
  ruff: PASS
  compileall: PASS
  alembic_single_head: true
  openapi_schema: PASS
  dirty_paths_unrelated_modified: []
```

---

## 13. Deliverables

Создай или обнови только обоснованные artifacts:

### 13.1. Code

- typed comparability/evidence models;
- hard matching/pricing gates;
- stable seller/provenance/currency handling;
- robust heterogeneity diagnostics;
- truthful decision-diff CLI;
- strict preflight CLI/validators;
- E2E harness/runner;
- observability and feature-activation checks.

### 13.2. Database

- migration(s) для versioned evidence/policy/fingerprint;
- constraints/indexes;
- legacy-safe backfill;
- upgrade/recovery evidence.

### 13.3. Tests and fixtures

- four baseline regression fixtures;
- M-001..M-025;
- R-001..R-020;
- P-001..P-025;
- E2E-F01..E2E-F10;
- property/metamorphic tests;
- mutation probes;
- replay compatibility tests;
- secret-canary tests.

### 13.4. Operations

- isolated E2E compose/profile;
- preflight JSON schema;
- E2E evidence manifest;
- rollback instructions;
- corrected production runbook;
- no committed real `.env` or secrets.

### 13.5. Final reports

Создай:

```text
docs/PROMPT_15_015_IMPLEMENTATION_REPORT_YYYY-MM-DD.md
docs/PROMPT_15_015_VARIATION_LEDGER_YYYY-MM-DD.yaml
docs/PROMPT_15_015_E2E_EVIDENCE_YYYY-MM-DD.yaml
docs/PROMPT_15_015_FINAL_GATE_MANIFEST_YYYY-MM-DD.yaml
```

Названия можно адаптировать к repository convention, но все четыре типа evidence должны
существовать.

---

## 14. Final gate model

Не выводи один усреднённый процент. Статусы независимы:

```yaml
final_gates:
  remediation_execution: PASS_OR_FAIL_OR_BLOCKED_OR_NO_GO
  docker_e2e_gate: PASS_OR_BLOCKED_ENVIRONMENT_OR_FAIL
  matching_implementation_gate: PASS_OR_FAIL_OR_NO_GO
  matching_production_activation: PASS_OR_BLOCKED_DATA_OR_NO_GO
  robust_v3_implementation_gate: PASS_OR_FAIL_OR_NO_GO
  robust_v3_activation_gate: PASS_OR_BLOCKED_DATA_OR_NO_GO
  production_preflight_gate: PASS_OR_FAIL_OR_BLOCKED_ENVIRONMENT
  full_production_readiness: PROVEN_OR_NOT_PROVEN
```

Primary status precedence:

```text
NO_GO > BLOCKED > FAIL > PASS
```

Но обязательно поясни bounded scope: например implementation может `PASS`, когда
activation остаётся `BLOCKED_DATA`.

### 14.1. Production-ready theorem

```text
G_production = G_e2e_E4
               · G_matching_approved
               · G_robust_approved
               · G_preflight_full
               · G_security
               · G_recovery_E5
               · G_capacity_E5
               · G_observability

production_ready = true only if G_production = 1
```

Если recovery/load/pilot evidence не входили в фактически выполненную среду, итог
`full_production_readiness = NOT_PROVEN`, даже если remediation code полностью готов.

---

## 15. Обязательный формат execution ledger

Веди ledger:

```yaml
execution_ledger:
  prompt_id: PROMPT_15_015
  steps:
    - step_id: STEP_00
      status: PASS_OR_FAIL_OR_BLOCKED_OR_NO_GO
      changed_files: []
      commands: []
      evidence_refs: []
      defects_found: []
      repairs_applied: []
      variations_run: []
      remaining_unknowns: []
```

Каждый claim о результате должен иметь command/test/artifact reference.

---

## 16. Hostile self-review checklist

Перед завершением ответь доказательно:

1. Может ли пять offers без OE/fitment/side/condition/quantity всё ещё дать automatic
   price?
2. Может ли exact model/SKU обойти brand/fitment/condition conflict?
3. Может ли `source_confidence=1` заменить provenance?
4. Могут ли blank seller IDs стать независимыми через разные names?
5. Может ли missing raw currency стать UAH до gate?
6. Может ли двухкластерный cohort дать auto из-за малого Qn?
7. Может ли v3 отменить baseline abstention без approved evidence?
8. Может ли decision-diff сообщить PASS при unsafe relaxation?
9. Может ли `.env.production.example` пройти checker без замены placeholders?
10. Может ли full preflight пройти без network/schema/workflow checks?
11. Может ли secret появиться в stdout/stderr/JSON?
12. Может ли E2E claim использовать mock DB/queue вместо реальных containers?
13. Может ли E2E auth bypass включиться в production?
14. Может ли duplicate task создать вторую recommendation?
15. Может ли stale worker commit после lease takeover?
16. Может ли replay нового policy использовать старую semantics или наоборот?
17. Может ли legacy unknown backfill стать verified?
18. Проходит ли clean PostgreSQL migration, а не только offline SQL?
19. Сохранились ли frontend/API backward compatibility и operator visibility?
20. Есть ли хоть один production claim выше фактического evidence level?

Любой ответ «да» для unsafe path означает, что работа не завершена. Исправь и повтори
проверки.

---

## 17. Финальный ответ агента

Финальный ответ должен начинаться с прямого результата и содержать:

1. что именно исправлено;
2. какие исходные repro убиты;
3. какие tests/variations/E2E реально выполнены;
4. commit/worktree identity;
5. какие gates `PASS`;
6. какие activation gates остаются `BLOCKED_DATA` и почему;
7. production readiness — доказана или нет;
8. список изменённых файлов и migrations;
9. команды воспроизведения;
10. ссылку на evidence bundle;
11. обязательный Section 15.1 footer и Section 16 machine-readable summary согласно
    repository `AGENTS.md` и соответствующим contract documents.

Не пиши «всё готово», если не выполнен реальный Docker E2E. Не пиши «production-ready»,
если нет E5 recovery/load/pilot evidence. Не называй parser неработающим из-за отдельного
policy gate. Не запускай следующий этап автоматически.

---

## 18. STOP CONDITION

Остановись только когда выполнено одно из условий:

```text
PASS:
  all implementation gates pass, required E2E executed, evidence artifacts validated;
  activation/production limits are stated truthfully.

BLOCKED:
  all agent-resolvable work is complete, but Docker/runtime, authoritative domain policy,
  representative dataset or another external dependency is genuinely unavailable;
  exact missing input and completed work are documented.

NO_GO:
  reproducible evidence shows the selected remediation approach violates a hard invariant;
  provide replacement approach and do not activate.
```

Не используй `BLOCKED` из-за сложности, длины задачи или желания остановиться. Не используй
`PASS`, если обязательные checks были skipped.

STOP_GATE_PROMPT_15_015_IMPLEMENTATION = PASS|FAIL|BLOCKED|NO_GO
