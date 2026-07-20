# PROMPT 15.016 — Yuri V1 Requirements Alignment Audit and Remediation

- **Status:** executable master prompt artifact
- **Revision:** `1.0.0`
- **Revision date:** `2026-07-18`
- **Language:** русский для рассуждений и отчётов; English identifiers, formulas, enums, pseudocode, JSON/YAML для машинной однозначности
- **Execution mode:** `AUDIT_REVIEW_IMPLEMENT_VERIFY`
- **Scope owner:** Marko product shell + Metis pricing/evidence kernel
- **Primary target root:** `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`
- **Prompt ID:** `PROMPT_15_016`
- **Terminal objective:** доказательно привести текущую реализацию к буквальному Yuri V1 contract либо завершить работу честным `BLOCKED`/`NO_GO` с точным первым недоказанным переходом

---

## 0. Назначение и способ использования

Этот документ — самостоятельное задание для последующего ИИ-агента. Он не является
готовым аудитом, отчётом об уже выполненной реализации или разрешением на production
deployment. Передай агенту **весь раздел `1. MASTER PROMPT` целиком**.

Агент должен:

1. перепроверить исходный Yuri V1 gap analysis по текущему физическому checkout;
2. воспроизвести подтверждённые дефекты до их исправления;
3. исправить product code, contracts, persistence, API, UI, migrations и tests в
   пределах явно разрешённого scope;
4. доказать исправления вариационными, adversarial, metamorphic, replay и E2E
   проверками;
5. отделить успешную локальную реализацию от representative-data, source-permission,
   privacy-decision и production-activation gates;
6. не продолжать через нерешённое business decision или недоказанный hard gate.

Исходные выводы, перечисленные ниже, — это `BASELINE_HYPOTHESES`, которые направляют
проверку. Они не заменяют чтение текущего кода и не дают права объявить дефект или его
исправление без свежего evidence.

---

# 1. MASTER PROMPT

## 1.1. Роль агента

ТЫ — principal software engineer, applied pricing statistician, automotive product
identity architect, data-contract engineer, privacy/security reviewer, adversarial test
engineer и production-readiness auditor проекта **Marko + Metis**.

Работай одновременно на четырёх уровнях:

1. **Business semantics:** буквальные требования Юрия, включая OE-first identity,
   ручные решения, два режима управления ценой, KEMP cohort policy и конфиденциальность
   себестоимости.
2. **Mathematical correctness:** cohort construction, tier normalization, robust fair
   price, confidence/abstention, stock-age markdown и priority ranking.
3. **System correctness:** acquisition → immutable evidence → structured observation →
   comparability → cohort → recommendation → operator decision → audit trail.
4. **Evidence correctness:** каждое утверждение должно иметь воспроизводимый источник;
   passing tests не равны production readiness.

Не смешивай ownership:

- **Metis** — evidence/comparability/pricing/recommendation kernel и математические
  инварианты.
- **Marko** — product shell, import, FastAPI/PostgreSQL/Redis/Celery orchestration,
  Prom adapters, Flutter operator workflow и integration boundary вокруг Metis.
- **Prom parser** — существующая и ранее frozen boundary; не переписывай parser
  internals без воспроизводимого parser defect и отдельного доказательства, что
  additive adapter/replay transformation не решает проблему безопаснее.

## 1.2. Буквальная терминальная цель

Не ограничивайся аудитом или планом. После evidence-first ревизии выполни разрешённые
исправления и доведи систему до следующего terminal state:

```yaml
terminal_outcome:
  allowed_values:
    - PASS
    - FAIL
    - BLOCKED
    - NO_GO
  PASS_requires:
    yuri_v1_semantic_contract: VERIFIED
    oe_first_cross_brand_identity: VERIFIED
    tier_comparability_after_identity: VERIFIED
    kemp_target_cohort_exclusion: VERIFIED
    used_item_exclusion: VERIFIED
    description_condition_evidence_path: VERIFIED
    manual_operator_decision: VERIFIED
    no_automatic_prom_writeback: VERIFIED
    stock_age_pricing_modes: VERIFIED
    explicit_cost_privacy_state: VERIFIED
    literal_change_sorting: VERIFIED
    confidence_abstention: VERIFIED
    representative_client_data_gate: PASSED_OR_EXPLICITLY_BLOCKED
    source_access_gate: PASSED_OR_EXPLICITLY_BLOCKED
    product_code_and_migrations: VERIFIED
    backend_frontend_replay_e2e: VERIFIED
  forbidden_shortcuts:
    - audit_report_without_remediation
    - unit_tests_only
    - README_as_implementation_evidence
    - fixture_only_production_claim
    - lowering_fail_closed_gates_to_get_green_tests
```

Если code remediation завершена, но нет реального клиентского XLSX, approved cost
privacy mode, representative Prom replay или legal/source permission, финальный
project/production gate обязан быть `BLOCKED`, даже когда implementation stage имеет
`PASS`.

## 1.3. Анти-упрощающий контракт

ОБЯЗАТЕЛЬНО:

1. НЕ думай о токенах, лимитах, длине ответа, стоимости контекста или количестве
   файлов. Полнота и истинность важнее краткости.
2. НЕ упрощай задачу до README review, grep-списка, общего плана, одного happy-path
   теста или косметического рефакторинга.
3. НЕ защищай предыдущий аудит. Попытайся опровергнуть каждую baseline hypothesis.
4. НЕ считай существующий тест правильным только потому, что он зелёный. Если тест
   закрепляет неверную бизнес-семантику, сначала докажи конфликт с normative contract,
   затем замени тест на правильный regression contract.
5. НЕ переписывай реализацию вслепую. Сначала найди first broken transition и создай
   failing reproduction.
6. НЕ смешивай OE identity, brand/tier classification и fitment comparability. Это
   разные измерения с разными failure semantics.
7. НЕ включай KEMP-конкурентов в target fair-price cohort. Сохранять их как evidence
   можно; влиять на целевую медиану или recommendation guardrail — нельзя без нового
   письменного business decision.
8. НЕ объявляй «б/у полностью исключены», пока condition/title/description evidence
   не проходит через live/replay persistence и adversarial tests.
9. НЕ утверждай, что себестоимость скрыта от разработчиков/оператора/администратора,
   пока threat model и выбранная архитектура реально обеспечивают такое свойство.
10. НЕ выдумывай дату закупки. Текущая V1 hypothesis — ручной `stock_status` плюс
    необязательный `stock_age_days`; `purchase_date` вводится только после явного
    подтверждения наличия данных.
11. НЕ превращай description-derived cross number в автоматическое identity evidence.
    В V1 это максимум candidate/manual-review evidence, пока отдельный gold set не
    докажет precision.
12. НЕ обходи `source_access` и не делай новые live Prom requests без явного разрешения.
13. НЕ меняй и не применяй цены на Prom. V1 заканчивается рекомендацией и ручным
    операторским решением.
14. НЕ включай Autopro, 1С/BAS, TecDoc/full cross database, automatic publishing или
    elasticity model в V1.
15. НЕ очищай dirty worktree, не удаляй чужие изменения, не используй destructive Git
    commands, force push, migration downgrade на пользовательских данных или shared
    infrastructure.
16. НЕ устанавливай/обновляй зависимости и не меняй lockfiles, если это не необходимо
    для исправления и явно не разрешено применимыми инструкциями.
17. НЕ раскрывай secrets, raw cost values или client data в logs, snapshots, fixtures,
    reports и final response.
18. НЕ трактуй `UNKNOWN`, `NOT_AVAILABLE`, `NOT_RUN`, пустой список или отсутствие
    исключения как `PASS`.
19. После каждого смыслового изменения проводи variation testing; после всей работы —
    hostile self-review. Исправь найденные дефекты до финального gate.
20. Продолжай всю независимую работу автономно. Проси пользователя только о реально
    недоступном business/legal/privacy/data decision, которое меняет архитектуру.

## 1.4. Границы разрешённых действий

```yaml
execution_authority:
  read_current_checkout: true
  run_safe_local_tests: true
  edit_product_code: true
  edit_tests: true
  add_migrations: true
  edit_api_and_flutter_contracts: true
  create_local_fixture_and_replay_evidence: true
  create_reports_and_manifests: true
  preserve_unrelated_user_changes: required
  rewrite_prom_parser_internals: false
  live_prom_requests: false
  source_access_policy_relaxation: false
  automatic_price_writeback: false
  autopro_integration: false
  tecdoc_or_full_cross_database: false
  one_c_integration: false
  production_deploy: false
  git_commit_or_push: false
  destructive_data_operations: false
```

Если пользователь отдельно изменил authority, запиши точную цитату/источник и новое
значение в execution manifest. Не расширяй authority по косвенному намёку.

## 1.5. Контракт запуска

До любых изменений создай run manifest и заполни фактическими значениями:

```yaml
execution_input:
  prompt_id: PROMPT_15_016
  prompt_revision: "1.0.0"
  execution_mode: AUDIT_REVIEW_IMPLEMENT_VERIFY
  requested_root: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия"
  realpath: DISCOVER
  git_top_level: DISCOVER_OR_NOT_AVAILABLE
  git_commit_before: DISCOVER_OR_NOT_AVAILABLE
  branch_before: DISCOVER_OR_NOT_AVAILABLE
  dirty_paths_before: DISCOVER
  runtime_import_paths: DISCOVER
  applicable_instruction_files: DISCOVER
  python_version: DISCOVER
  uv_version: DISCOVER
  flutter_version: DISCOVER
  docker_context: DISCOVER_OR_NOT_REQUIRED
  source_access_state: DISCOVER
  live_prom_requests_authorized: false
  automatic_price_writeback_authorized: false
  parser_internal_changes_authorized: false
  real_client_workbook: NOT_PROVIDED_UNLESS_DISCOVERED
  representative_prom_replay: DISCOVER_OR_NOT_AVAILABLE
  cost_privacy_mode:
    value: UNDECIDED
    allowed_values:
      - UNDECIDED
      - LOCAL_DEVICE_ONLY
      - PRIVATE_INSTANCE_PROTECTED_SERVER
  stock_age_input_mode:
    default: MANUAL_STATUS_PLUS_OPTIONAL_AGE_DAYS
    requires_yuri_confirmation: true
  report_language: ru
  machine_contract_language: en_identifiers_yaml
```

Правила repository identity:

1. Внешняя папка `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko` может быть wrapper.
2. Работай только с тем physical tree, который содержит проверяемые backend/frontend/docs.
3. Если `.git` отсутствует, не придумывай commit/branch/dirty status; используй
   `NOT_AVAILABLE` и path/hash-bound evidence.
4. Не используй sibling checkout как доказательство текущего tree.
5. Зафиксируй pre-change hashes всех изменяемых критических файлов и parser boundary.

---

## 2. Нормативный Yuri V1 contract

Считай следующий contract первичным продуктовым источником для этой remediation.
Если текущий код или старый документ ему противоречит, код/документ должен быть
исправлен либо конфликт должен быть вынесен как blocking business decision.

### 2.1. Термины

```yaml
terms:
  catalog_item: товар Юрия/KEMP в импортированном каталоге
  competitor_offer: наблюдаемое предложение независимого продавца
  oe_identity: идентичность детали по нормализованному OE/OEM номеру
  brand: производитель/торговая марка; не identity gate для same-OE comparison
  tier: рыночный уровень OEM/OES/aftermarket/KEMP/budget/used
  target_cohort: предложения, используемые для расчёта KEMP-equivalent fair market price
  kemp_reference_cohort: предложения других продавцов KEMP, сохранённые отдельно
  owned_cohort: предложения магазина Юрия; никогда не являются независимым рынком
  automatic_eligible: достаточно доказательств для вычисления рекомендации
  automatic_writeback: автоматическое изменение цены во внешней системе; запрещено V1
  manual_review: оператор обязан проверить evidence и принять решение вручную
  stale_stock: залежалый товар по ручному status/age policy
  dead_stock: неликвид, для которого разрешён более агрессивный clearance workflow
```

### 2.2. Требования R-01…R-17

| ID | Нормативное требование | Обязательный V1 outcome |
|---|---|---|
| `R-01` | Сопоставлять по OE, не по бренду | Same normalized OE может допустить different brand; different OE не может стать same identity из-за одинакового бренда/названия |
| `R-02` | Сравнивать только сопоставимый рыночный уровень | После identity gates выполняется tier classification и KEMP-equivalent normalization |
| `R-03` | Решение и изменение цены вручную | Agent создаёт recommendation/evidence; оператор accept/reject/override; внешнего writeback нет |
| `R-04` | Два режима вверх/вниз с учётом давности | Active/fresh следует рынку; stale/dead получает монотонно более сильный clearance pressure с возрастом |
| `R-05` | Себестоимость вводит Юрий, privacy должна быть честной | Manual input есть; visibility/threat model соответствует явно выбранному privacy mode |
| `R-06` | Начинать с самых больших изменений | UI/API имеют буквальную сортировку по `absolute_recommended_change`, отдельно от economic priority |
| `R-07` | Ссылка на competitor listing | Каждая evidence row содержит проверяемый URL либо явный reason отсутствия |
| `R-08` | Cross numbers искать в описаниях | Только phase-2/candidate lane; извлечение из description не даёт automatic identity без validation |
| `R-09` | Б/у полностью исключать | Used/refurbished evidence в title/description/condition всегда hard reject для target cohort |
| `R-10` | Других продавцов KEMP не брать в целевой рынок | KEMP observations сохраняются отдельно и никогда не входят в target median/guardrail |
| `R-11` | V1 не включает Autopro, writeback, 1С/BAS, full crosses | Границы отражены в коде, UI, API и документации |
| `R-12` | Товар физически на складе; FX/replacement-cost не ядро | Inventory context есть; FX/replacement-cost не определяют V1 recommendation |
| `R-13` | Sunk cost не должен блокировать рыночное решение | Cost — аналитический context/warning, не безусловный floor; любое below-cost решение остаётся ручным и auditable |
| `R-14` | 3–5 продаж/SKU/месяц недостаточно для elasticity | V1 не заявляет elasticity/causal demand model |
| `R-15` | Заявленные 4901/94%/97%/22% должны быть измерены | Пока реального XLSX нет — `BLOCKED_DATA`; после получения — repeatable coverage report |
| `R-16` | Prom сейчас, Autopro позже | Текущий provider contract не расширяется на Autopro |
| `R-17` | Узкая/сомнительная выборка должна abstain | `INSUFFICIENT_DATA`/`MANUAL_REVIEW`, а не ложная точная рекомендация |

### 2.3. Явный V1 scope

```yaml
v1_scope:
  must_have:
    - R-01
    - R-02
    - R-03
    - R-04
    - R-05
    - R-06
    - R-07
    - R-09
    - R-10
    - R-17
    - catalog_import_and_context
  deferred_but_prepared:
    - R-08_description_cross_candidate_lane
  explicitly_out_of_scope:
    - Autopro
    - automatic_price_publication
    - 1C_or_BAS
    - TecDoc_full_cross_database
    - demand_elasticity_claim
    - FX_replacement_cost_core
```

---

## 3. Baseline hypotheses: что обязательно перепроверить

Следующие выводы получены предыдущим review. Они являются leads, не facts:

| Hypothesis ID | Предыдущий вывод | Основные anchors для перепроверки |
|---|---|---|
| `H-01` | Query начинается с OE, но `match_offer` отбрасывает different brand до OE evidence | `backend/src/marko/services/matching.py`, `tests/test_matching.py` |
| `H-02` | Comparability считает `brand_manufacturer` identity dimension | `backend/src/metis/pricing/comparability.py` |
| `H-03` | Tier normalization существует, но cross-brand offers не доходят до неё | `backend/src/metis/pricing/engine.py`, tiering/coefficient tests |
| `H-04` | Non-dumping KEMP входит в eligible/cleaned cohort с multiplier one | `backend/src/metis/pricing/engine.py`, `test_pricing_engine_matrix.py` |
| `H-05` | Live/replay persistence передаёт `description=None` | `backend/src/marko/services/market_collection.py`, parser model/adapters |
| `H-06` | Used reject существует после классификации, но description-only used может пройти незамеченным | tiering, market collection, engine hard rejection |
| `H-07` | `fresh` запрещено рекомендовать вниз | pricing invariants/tests |
| `H-08` | `stock_age_days` влияет на priority, но не непрерывно на markdown target | clearance formula and tests |
| `H-09` | Cost отправляется API и хранится plaintext `NUMERIC` | API schema, DB models, migrations, UI payload |
| `H-10` | Sorting использует priority/review score, а не absolute price change | pricing query, API enum, Flutter controller |
| `H-11` | Manual decisions, below-cost warning, URLs и abstention уже существуют | API/UI/decision ledger/engine tests |
| `H-12` | Реального клиентского XLSX нет; catalog ratios — supplied context | project files, audit docs, fixtures |

Для каждой hypothesis создай запись:

```yaml
hypothesis_check:
  hypothesis_id: H-XX
  status: CONFIRMED | REFUTED | PARTIAL | UNKNOWN
  claim_type: FACT | EXECUTION_RESULT | INFERENCE
  evidence_refs: []
  reproduction_command: null
  first_broken_transition: null
  affected_requirements: []
  remediation_required: true | false
```

---

## 4. Evidence и truth model

### 4.1. Уровни доказательств

```yaml
evidence_levels:
  E0: assertion_without_current_evidence
  E1: documentation_or_static_reference
  E2: unit_or_contract_test
  E3: integrated_local_replay_or_database_flow
  E4: representative_pinned_dataset_or_disposable_full_stack_e2e
  E5: approved_production_shadow_evidence_with_monitoring_and_rollback
```

Правила ceiling:

- README/comment/design doc не выше `E1`.
- Unit test не выше `E2`.
- Несколько unit tests не превращаются автоматически в `E3`.
- Fixture E2E не доказывает representative correctness.
- Реальные данные без pinned snapshot, labels и leakage control не дают `E4`.
- Production readiness требует `E4/E5` по каждому critical invariant.

### 4.2. Типы claims

Не смешивай:

```text
FACT
EXECUTION_RESULT
INFERENCE
ENGINEERING_PROPOSAL
BUSINESS_DECISION_REQUIRED
LEGAL_POLICY_BLOCKER
HYPOTHESIS
UNKNOWN
```

### 4.3. Traceability

Каждое изменение должно иметь двунаправленную трассу:

```text
R-XX
  -> observed defect / hypothesis
  -> failing test or reproducible trace
  -> code/schema/UI change
  -> positive regression
  -> negative/adversarial variation
  -> evidence artifact
  -> stage gate
```

Изменение без `requirement_id`, pre-fix reproduction и post-fix evidence не считается
закрытым.

---

## 5. Формальная модель product identity и comparability

### 5.1. Нормализация OE

Определи versioned функцию нормализации, не меняя silently уже сохранённые значения:

\[
N_{oe}(s)=\operatorname{UPPER}
\left(\operatorname{REMOVE\_NON\_ALNUM}(\operatorname{NFKC}(s))\right)
\]

Минимальные свойства:

```text
N_oe("1K0 698 151 E") = N_oe("1K0-698-151-E")
N_oe(null) = UNKNOWN, not empty-pass
len(N_oe(s)) < policy.min_length -> INVALID
different raw values collapsing to one normalized value -> collision evidence
```

Не делай approximate/fuzzy OE identity в V1. Validated alias/cross может быть отдельным
relation type, но description-derived candidate не эквивалентен exact OE.

### 5.2. Tri-state evidence

Для каждой критической dimension используй:

```text
PASS     — подтверждено совместимое значение
FAIL     — подтверждён конфликт
UNKNOWN  — данных недостаточно
```

Критические dimensions:

```yaml
critical_comparability_dimensions:
  identity:
    - oe_reference
  fitment:
    - vehicle_platform_or_generation_when_category_requires
    - engine_when_category_requires
    - year_interval_when_category_requires
  part_variant:
    - side
    - position
    - body_variant
    - package_quantity
  commercial:
    - condition
    - availability
    - currency
  provenance:
    - immutable_raw_capture
    - stable_source_listing_id
    - stable_seller_id
    - observation_freshness
```

`brand_manufacturer` исключи из identity conflict. Brand может влиять на tier, coefficient
и confidence, но different brand при same exact OE не является причиной reject.

### 5.3. Admission predicate

Для catalog item \(i\) и offer \(j\):

\[
A_{ij}=
\mathbf{1}[G^{oe}_{ij}=PASS]
\cdot
\mathbf{1}[\forall d\in D_{hard}:G^d_{ij}=PASS]
\cdot
\mathbf{1}[used_j=false]
\cdot
\mathbf{1}[available_j=true]
\cdot
\mathbf{1}[freshness_j\leq H_{max}]
\]

Правила:

- любой `FAIL` → `REJECT` с dimension-specific reason code;
- любой required `UNKNOWN` → `MANUAL_REVIEW`, не automatic eligibility;
- `brand_seed != brand_offer` не меняет OE admission;
- exact same brand/name при OE conflict не может пройти;
- fitment conflict всегда сильнее fuzzy title similarity;
- retrieval match не является comparability proof.

### 5.4. Category-specific required fields

Не требуй одинаковые fitment dimensions для всех категорий. Создай versioned policy:

```yaml
comparability_policy:
  policy_id: yuri-v1-comparability-v2
  category_rules:
    brake_pad:
      hard: [oe_reference, axle_position, condition, package_quantity]
      conditional: [vehicle_generation, engine]
    shock_absorber:
      hard: [oe_reference, axle_position, side, condition]
      conditional: [body_variant, suspension_type]
    generic_unknown:
      hard: [oe_reference, condition]
      automatic_action_allowed: false
```

Не придумывай окончательный category map без доказательств. Непокрытая категория должна
abstain, а не использовать permissive default.

---

## 6. Tier normalization и разделение cohorts

### 6.1. Непересекающиеся lanes

После comparability создай явную классификацию роли observation:

```text
TARGET_MARKET
KEMP_REFERENCE
OWNED_STORE
USED_REJECTED
DUMPING_DIAGNOSTIC
MANUAL_REVIEW
HARD_REJECTED
```

Инварианты:

\[
T_i\cap K_i=\varnothing,
\quad T_i\cap O_i=\varnothing,
\quad K_i\cap O_i=\varnothing
\]

где \(T_i\) — target cohort, \(K_i\) — other-KEMP reference lane, \(O_i\) — owned
store lane.

Обязательная metamorphic property:

```text
При неизменном TARGET_MARKET произвольное изменение цен KEMP_REFERENCE
не должно менять fair_price, recommended_price или action.
```

KEMP reference может менять только явно помеченные diagnostic/calibration outputs, но
не target recommendation. Если текущий direct-KEMP guardrail влияет на action/price,
удали или изолируй его и перепиши противоречащие тесты.

### 6.2. KEMP-equivalent normalization

Для raw price \(p_{ij}\), category \(c_i\), tier \(t_{ij}\) и validated multiplier
\(m_{c_i,t_{ij}}>0\):

\[
q_{ij}=\frac{p_{ij}}{m_{c_i,t_{ij}}}
\]

где \(q_{ij}\) — KEMP-equivalent price. Для direct KEMP diagnostic lane
\(m_{c,KEMP}=1\), но такие observations не входят в \(T_i\).

Coefficient contract:

```yaml
tier_coefficient:
  category: required
  tier: required
  multiplier: positive_finite_decimal
  confidence: bounded_0_1
  validated: boolean
  model_version: required
  dataset_hash: required_for_action
  sample_size: required
  effective_sample_size: required
  interval_lower: required_for_action
  interval_upper: required_for_action
  leave_one_oe_out: required
```

Unvalidated/missing coefficient → exclude from automatic target cohort or route to
manual review. Не подставляй `1` как silent fallback для unknown tier.

### 6.3. Robust fair market price

После seller deduplication и hard gates:

\[
Q_i=\{q_{ij}:j\in T_i\}
\]

Минимальный baseline:

\[
\hat p_i=\operatorname{median}(Q_i)
\]

Outlier/dispersion logic должна использовать существующий versioned Metis policy
(IQR/MAD/\(S_n\)/\(Q_n\), если уже реализовано), а не новый ad hoc фильтр. Любая
мультимодальность, estimator disagreement или недостаточная effective sample size
должна усиливать abstention, а не превращать `MANUAL_REVIEW` в action.

Seller deduplication выполняй до оценки \(n\). Seller name не является стабильным
identity; предпочитай platform seller ID и explicit independence evidence.

---

## 7. Condition, description и cross candidate lanes

### 7.1. Mandatory V1 condition evidence

Обеспечь additive data path:

```text
raw capture/replay
  -> description_raw / condition_raw
  -> normalized condition evidence
  -> used/refurbished classifier
  -> persisted observation
  -> comparability hard gate
  -> API evidence
  -> operator UI
```

Если frozen parser model не содержит description, сначала ищи безопасный путь:

1. уже имеющееся поле в raw payload/capture;
2. additive adapter рядом с parser boundary;
3. replay transformation с versioned parser contract;
4. только при доказанной невозможности — минимальное parser contract extension без
   изменения extraction semantics.

Не делай новые live detail-page requests без source permission.

### 7.2. Used classifier

Проверяй title, description и explicit condition. Минимальные multilingual markers
должны быть versioned и тестироваться, а не hard-code без provenance:

```text
б/у, бу, бывший в употреблении, вживаний, уживаний,
разборка, шрот, refurbished, remanufactured, used
```

Нужны boundary-aware patterns, чтобы не ловить подстроки внутри безопасных слов.
Любой positive used signal → `USED_OR_REFURBISHED` и исключение из target cohort.
Conflicting condition evidence → `MANUAL_REVIEW` или hard reject согласно policy, но
никогда automatic action.

### 7.3. Description cross extraction — отдельная phase-2 lane

Извлекай потенциальные OE/cross tokens из description только в структуру:

```yaml
cross_candidate:
  raw_token: string
  normalized_token: string
  context_window: string
  source_observation_id: uuid
  extraction_method_version: string
  confidence: decimal_0_1
  validation_state: UNVALIDATED | MANUALLY_CONFIRMED | REJECTED
  automatic_identity_eligible: false
```

До отдельного labeled benchmark такие candidates не участвуют в target cohort. Не
смешивай mandatory V1 description-for-condition с deferred cross matching.

---

## 8. Recommendation modes, sunk cost и stock age

### 8.1. Input model

V1 использует:

```yaml
stock_context:
  stock_status: fresh | stale | dead_stock | unknown
  stock_age_days: optional_nonnegative_decimal
  stock_qty: optional_nonnegative_decimal
  expected_units_sold: optional_nonnegative_decimal
  cost: optional_sensitive_decimal
  liquidity_target: decimal_0_1
  urgency: decimal_0_1
```

Не добавляй `purchase_date` без отдельного подтверждения, что Юрий может выгрузить или
реально заполнить её для каталога.

### 8.2. Market gap

Для current price \(p_i\) и fair price \(\hat p_i\):

\[
\Delta_i=\hat p_i-p_i,
\qquad
r_i=\frac{\Delta_i}{\max(p_i,\varepsilon)}
\]

Action threshold должен быть versioned:

```text
r_i >= raise_threshold  -> RAISE candidate
r_i <= -lower_threshold -> LOWER candidate
otherwise               -> HOLD
```

Любой action остаётся рекомендацией; operator принимает решение вручную.

### 8.3. Fresh/active policy

Удали безусловный invariant `fresh cannot lower`, если он подтверждён в текущем коде
и противоречит R-13. Для active stock рыночная цена может быть ниже current price.
Себестоимость не должна silently заменять market evidence hard floor.

Safety contract:

- recommendation below cost разрешена только как visibly flagged manual decision;
- UI показывает current price, fair price, cost (только если privacy mode разрешает),
  loss amount/percentage и reason;
- no automatic writeback;
- operator confirmation и reason обязательны;
- решение append-only и auditable.

### 8.4. Stale/dead monotonic age pressure

Для статуса \(s\), возраста \(a\), threshold \(A_s\), half-life \(H_s>0\):

\[
z(a,s)=\max(0,a-A_s)
\]

\[
\beta_{age}(a,s)=1-\exp\left(-\ln(2)\frac{z(a,s)}{H_s}\right)
\]

\[
\beta_i=\operatorname{clamp}
\left(\max(\beta_{base,s},\beta_{age}(a_i,s),liquidity_i,urgency_i),0,1\right)
\]

Для lower-market quantile \(L_i=Q_{\alpha}(Q_i)\):

\[
p^{clear}_i=(1-\beta_i)p_i+\beta_i\min(p_i,L_i)
\]

Обязательные свойства:

```text
a2 >= a1  => beta(a2,s) >= beta(a1,s)
a2 >= a1  => p_clear(a2,s) <= p_clear(a1,s), ceteris paribus
dead_stock pressure >= stale pressure
fresh uses market-gap policy, not clearance formula
unknown age never becomes zero-age certainty
```

Не выдумывай `A_s`, `H_s`, `beta_base` и quantile. Вынеси их в versioned policy;
существующие defaults должны быть помечены engineering assumptions до approval.

---

## 9. Confidence и abstention

### 9.1. Factors

Используй положительные factors \(f_k\in[0,1]\):

```text
sample_size_quality
effective_sample_quality
seller_independence_quality
oe_identity_quality
comparability_completeness
tier_confidence
coefficient_confidence
source_provenance_quality
freshness_quality
dispersion_quality
estimator_stability
```

Один возможный агрегатор — weighted geometric mean:

\[
C_i=\exp\left(\frac{\sum_k w_k\ln(\max(f_{ik},\epsilon))}
{\sum_k w_k}\right)
\]

Но hard gates не усредняются. Если critical factor ниже floor или dimension UNKNOWN,
автоматический action запрещён независимо от среднего \(C_i\).

### 9.2. Decision contract

```pseudocode
if unique_sellers < policy.minimum_unique_sellers:
    return INSUFFICIENT_DATA

if any(hard_gate == FAIL):
    return REJECTED_EVIDENCE

if any(required_hard_gate == UNKNOWN):
    return MANUAL_REVIEW

if coefficient_not_validated or cohort_unstable:
    return MANUAL_REVIEW

if confidence < policy.confidence_min:
    return MANUAL_REVIEW

return compute_manual_recommendation_candidate()
```

Confidence не является вероятностью правильности, пока нет outcome-labeled calibration.
UI/report не должны называть его probability/accuracy.

---

## 10. Literal sorting и operator workflow

### 10.1. Метрики изменения

Для рекомендованной цены \(p_i^*\):

\[
\Delta^{abs}_i=|p_i^*-p_i|
\]

\[
\Delta^{pct}_i=\frac{|p_i^*-p_i|}{\max(p_i,\varepsilon)}
\]

Сохрани economic scores как отдельные typed fields, но добавь literal sort:

```yaml
recommendation_sort:
  ABSOLUTE_RECOMMENDED_CHANGE:
    primary: absolute_change_desc
    tie_breakers: [confidence_desc, computed_at_desc, recommendation_id_asc]
  PERCENT_RECOMMENDED_CHANGE:
    primary: percentage_change_desc
  EXPECTED_GROSS_UPLIFT:
    primary: economic_priority_desc
  CLEARANCE_CAPITAL_LOCK:
    primary: clearance_priority_desc
  REVIEW_PRIORITY:
    primary: review_priority_desc
```

Если Юрий буквально просит «самое большое рекомендуемое изменение цены», default UI
должен быть `ABSOLUTE_RECOMMENDED_CHANGE`, либо UI должен явно показывать выбранную
альтернативу. Не называй economic priority «максимальным изменением».

### 10.2. Manual workflow

Каждая recommendation page должна показывать:

- current/recommended price и absolute/percentage delta;
- action/reason codes;
- confidence factors и weakest factor;
- target cohort evidence;
- отдельно KEMP reference observations с пометкой `NOT_IN_TARGET_MEDIAN`;
- excluded/manual-review evidence и причины;
- competitor URLs;
- tier/raw price/multiplier/KEMP-equivalent price;
- stock context и age policy;
- privacy-safe cost context;
- accept/reject/override с обязательной причиной;
- явное сообщение «цена на Prom.ua не изменяется автоматически».

---

## 11. Cost privacy: обязательный threat model и decision gate

### 11.1. Нельзя обещать невозможное

Сервер не может одновременно вычислять функцию от raw cost и криптографически не иметь
доступа к raw cost без отдельной client-side/secure-compute архитектуры. Поэтому фраза
«себестоимость видит только Юрий» требует точного определения adversary:

```yaml
actors:
  yuri_operator: SHOULD_ACCESS
  other_workspace_user: MUST_NOT_ACCESS
  ordinary_support_user: MUST_NOT_ACCESS
  application_logs: MUST_NOT_CONTAIN
  analytics_exports: MUST_NOT_CONTAIN
  database_reader: DEPENDS_ON_MODE
  hosting_admin: DEPENDS_ON_MODE
  application_runtime: DEPENDS_ON_MODE
```

### 11.2. Mode A — LOCAL_DEVICE_ONLY

```yaml
LOCAL_DEVICE_ONLY:
  raw_cost_sent_to_api: false
  raw_cost_persisted_server_side: false
  server_side_cost_based_recommendation: false
  client_side_cost_warning: allowed
  server_audit_payload: derived_decision_metadata_only
  caveat: derived values may still leak information and require review
```

### 11.3. Mode B — PRIVATE_INSTANCE_PROTECTED_SERVER

```yaml
PRIVATE_INSTANCE_PROTECTED_SERVER:
  raw_cost_sent_to_private_api: true
  persistence: encrypted_or_equivalently_protected_at_rest
  transport: authenticated_tls
  authorization: workspace_and_role_bound
  logs_traces_errors: redacted
  exports: excluded_by_default
  database_admin_access: technically_possible_unless_stronger_boundary_exists
  key_management: outside_database_and_not_committed
  audit: append_only_access_and_change_events
```

### 11.4. Decision rule

Если `cost_privacy_mode=UNDECIDED`:

1. выполни все decision-independent исправления;
2. создай ADR с обеими моделями, data-flow diagram, threat model и migration impact;
3. не создавай ложный privacy PASS;
4. не продолжай с irreversible cost migration;
5. выставь `BLOCKED_BUSINESS_DECISION` для cost privacy gate.

Ни один вариант не должен хранить raw cost в generic `raw_row`, logs, analytics event,
error payload или test fixture.

---

## 12. Catalog import и representative data gate

### 12.1. Измерения реального файла

Если реальный client workbook предоставлен и его обработка разрешена, вычисли:

\[
coverage_x=\frac{\#\{rows:\ valid(x)\}}{N}
\]

Для заявленных показателей измерь:

```yaml
catalog_quality:
  total_rows: measured
  valid_rows: measured
  rejected_rows: measured
  kemp_brand_share: measured
  valid_oe_share: measured
  dimension_coverage: measured
  currency_distribution: measured
  cost_coverage: sensitive_do_not_export_raw
  duplicate_raw_oe_count: measured
  normalized_oe_collision_count: measured
  duplicate_sku_count: measured
  missing_url_count: measured
  stock_status_coverage: measured
  stock_age_days_coverage: measured
```

Для proportions добавь Wilson interval, не только point estimate:

\[
\hat p=\frac{x}{n},\quad
CI_{Wilson}=\frac{\hat p+\frac{z^2}{2n}\pm z
\sqrt{\frac{\hat p(1-\hat p)}{n}+\frac{z^2}{4n^2}}}
{1+\frac{z^2}{n}}
\]

### 12.2. Если файла нет

Не генерируй 4901 synthetic rows как «доказательство». Оставь:

```yaml
representative_client_catalog_gate:
  status: BLOCKED_DATA
  claimed_values:
    rows: 4901
    kemp_share: 0.94
    oe_usable_share: 0.97
    dimensions_share: 0.22
  verified_values: null
  required_input: real client export or approved anonymized representative snapshot
```

Synthetic/adversarial fixtures всё равно обязательны для code correctness, но не
закрывают representative gate.

---

## 13. Пошаговое выполнение и stop-gates

Веди execution ledger. Между техническими этапами можешь продолжать автоматически
только при `PASS`; при `FAIL`, `BLOCKED` или `NO_GO` останови зависимые изменения,
заверши независимые проверки и выдай точный blocker.

### STAGE 0 — Repository identity, instructions и baseline

Задачи:

1. Найди physical root/realpath и применимые instruction files.
2. Зафиксируй Git identity либо `NOT_AVAILABLE`.
3. Сними dirty-path inventory и не трогай unrelated changes.
4. Найди runtime import paths, migrations head, backend/frontend toolchain.
5. Зафиксируй parser boundary hashes.
6. Запусти baseline tests без изменений; отдели environment failures от product failures.

Gate:

```yaml
GATE_00_BASELINE:
  pass_if:
    - target_tree_unambiguous_or_explicitly_unknown
    - applicable_instructions_read
    - pre_change_state_recorded
    - baseline_results_recorded_without_fabrication
  fail_if:
    - wrong_tree_selected
    - user_changes_would_be_overwritten
```

### STAGE 1 — Requirements trace и hostile re-audit

Задачи:

1. Создай matrix R-01…R-17 → code → tests → DB/API/UI → status.
2. Перепроверь H-01…H-12.
3. Для каждого defect найди first broken transition.
4. Отдели implementation gap, test-contract gap, data gap и business decision.
5. Не меняй код до фиксации pre-change evidence.

Gate: `GATE_01_REQUIREMENTS_TRUTH = PASS` только если все 17 требований имеют
evidence-backed disposition.

### STAGE 2 — Pre-fix reproductions

Создай failing/characterization tests:

- same OE + KEMP seed + Bosch/Sachs candidate должен допускаться до tier stage;
- same brand/name + conflicting OE должен отклоняться;
- brand mismatch не является identity failure;
- KEMP reference price mutation не меняет target recommendation;
- description-only used item исключается;
- current `description=None` path обнаруживается integration test;
- age monotonicity нарушается/подтверждается;
- fresh market-lower case воспроизводит запрещённый current invariant;
- API sort не имеет literal absolute change;
- cost raw value проходит/не проходит запрещённые boundaries.

Не принимай тест, который проходит до исправления и не различает bad/good semantics.

Gate: `GATE_02_DEFECT_REPRODUCTION = PASS` при наличии deterministic reproduction либо
`REFUTED` с доказательством, что исходный claim неверен.

### STAGE 3 — OE-first identity и comparability repair

Задачи:

1. Сделай normalized OE primary identity gate.
2. Удали brand equality из identity rejection.
3. Сохрани fitment/side/position/engine/category hard conflicts.
4. Раздели retrieval match и automatic comparability.
5. Добавь reason codes и versioned policy/hash.
6. Обнови serializer/persistence/replay так, чтобы решение воспроизводилось.
7. Перепиши старые тесты, закрепляющие неправильный brand rejection.

Gate: все positive/negative/adversarial identity cases проходят; missing critical fields
не дают automatic action.

### STAGE 4 — Cohort role и KEMP isolation

Задачи:

1. Добавь explicit cohort role в domain result и evidence API.
2. Исключи other-KEMP из target cohort до cleaning/median/guardrail.
3. Сохрани KEMP reference evidence отдельно.
4. Исключи owned seller и duplicates.
5. Обнови fair-price counts: raw, target, KEMP-reference, owned, rejected, unique.
6. Создай migration/backfill только если persisted role действительно нужен.
7. Удали/замени тесты, ожидающие KEMP в competitor/fair-price count.

Gate: `TARGET_MARKET ∩ KEMP_REFERENCE = ∅`; KEMP metamorphic invariance доказана.

### STAGE 5 — Description/condition и used exclusion

Задачи:

1. Протащи available description/condition через additive frozen boundary.
2. Не делай live requests.
3. Persist raw + normalized condition provenance.
4. Hard-reject used/refurbished before target cohort.
5. Покажи reason и evidence в API/UI.
6. Реализуй cross candidate extraction только как disabled/manual phase-2 lane, если
   это не расширяет scope.

Gate: used в title, description или explicit condition не может попасть в target cohort.

### STAGE 6 — Stock-age modes и sunk-cost policy

Задачи:

1. Реализуй versioned monotonic age pressure для stale/dead.
2. Убери некорректный blanket-ban на fresh LOWER.
3. Сохрани no-writeback и manual confirmation.
4. Cost используй как visible analytic warning, а не universal market floor.
5. Не выдумывай purchase date.
6. Обнови reason codes, context snapshot и replay.

Gate: mathematical properties и scenario matrix проходят; below-cost decision всегда
явный и auditable.

### STAGE 7 — Cost privacy decision boundary

Задачи:

1. Создай ADR и threat model.
2. Если mode approved — реализуй строго его.
3. Если `UNDECIDED` — убери ложные privacy claims и stop dependent persistence changes.
4. Проверь logs, API responses, DB, raw import, analytics и tests на leakage.

Gate может быть `BLOCKED_BUSINESS_DECISION`; это не отменяет PASS других stages.

### STAGE 8 — Literal ranking и operator UX

Задачи:

1. Добавь absolute/percentage delta fields.
2. Добавь stable sort API enum и DB/query ordering.
3. Выведи literal sort в Flutter.
4. Не удаляй typed economic queues; переименуй labels, если они вводят в заблуждение.
5. Покажи target/KEMP/excluded lanes и competitor URLs.
6. Сохрани accept/reject/override, reason, below-cost warning и no-writeback text.

Gate: API and Flutter contract tests доказывают deterministic order и semantics.

### STAGE 9 — Persistence, migration, replay и backward compatibility

Задачи:

1. Инвентаризируй новые/изменённые поля.
2. Создай additive migration с constraints/indexes.
3. Определи backfill semantics; unknown не превращай в false/pass.
4. Обнови replay schema/version и compatibility reader.
5. Докажи idempotency и tenant/workspace isolation.
6. Сгенерируй offline upgrade SQL; destructive downgrade не запускай на данных.

Gate: clean database + upgraded prior schema дают одинаковый valid contract.

### STAGE 10 — Verification, variation и mutation

Выполни матрицу из раздела 14. Для каждого invariant:

1. positive case;
2. nearest negative;
3. missing-data case;
4. conflicting-data case;
5. boundary case;
6. metamorphic relation;
7. targeted mutation.

Gate: все обязательные tests pass, targeted unsafe mutations killed, no invariant
relaxed.

### STAGE 11 — Representative client and market evidence

Если data доступны и разрешены:

1. импортируй real/anonymized representative XLSX repeatably;
2. измерь catalog statistics;
3. replay pinned Prom evidence без новых live requests;
4. собери labeled positive/adversarial cases;
5. оцени precision/abstention/manual-review rates с intervals;
6. не смешивай calibration/train и evaluation OE/seller snapshots.

Если data нет — `BLOCKED_DATA`; implementation не переименовывай в production proof.

### STAGE 12 — Hostile self-review и final gates

Проверь:

- не остался ли brand equality в скрытом adapter/query/test path;
- не входит ли KEMP через другой branch, replay или legacy payload;
- не теряется ли description при сериализации;
- не превращается ли UNKNOWN condition в new;
- не зависит ли target recommendation от KEMP diagnostic lane;
- монотонен ли age markdown;
- не утекла ли cost в raw row/log/context snapshot/export;
- literal ли sorting;
- не ослаблены ли confidence/dispersion gates;
- не заявлена ли production readiness по fixtures;
- не изменён ли frozen parser без разрешения;
- не выполнен ли внешний writeback.

Исправь собственные report/manifest inconsistencies и rerun validators.

---

## 14. Обязательная verification matrix

### 14.1. OE/identity cases

| Case | Expected |
|---|---|
| Same normalized OE, KEMP seed, Bosch offer | admitted to tier/comparability |
| Same normalized OE, brand missing | identity pass; tier may be manual/unknown |
| Same brand, different OE | reject identity conflict |
| Same OE, left/right conflict | reject comparability conflict |
| Same OE, engine conflict in required category | reject/manual per category policy; never auto |
| OE only in description, not validated | cross candidate/manual only |
| Unicode spaces/hyphens in equivalent OE | same normalized identity |
| Normalization collision | explicit collision/manual review |

### 14.2. Cohort cases

| Case | Expected |
|---|---|
| Other KEMP, normal price | `KEMP_REFERENCE`, not target |
| Other KEMP, dumping price | diagnostic/rejected, not target |
| Owned seller | `OWNED_STORE`, not target |
| Same seller repeated listings | one independent contribution or explicit dedup |
| Change only KEMP prices | fair/recommendation unchanged |
| Unknown tier coefficient | manual/excluded, no multiplier=1 fallback |

### 14.3. Condition cases

| Evidence | Expected |
|---|---|
| `б/у` in title | hard reject |
| `вживаний` only in description | hard reject |
| explicit `condition=used` | hard reject |
| description unavailable | required condition UNKNOWN; no unsafe auto action |
| safe word containing similar substring | no false used marker |
| title says new, description says used | conflict → reject/manual, never target |

### 14.4. Pricing/age cases

| Case | Expected |
|---|---|
| Fresh, fair > current | RAISE candidate if gates pass |
| Fresh, fair < current | LOWER candidate allowed; manual only |
| Stale age increases | target non-increasing |
| Dead vs stale same inputs | dead target no higher than stale |
| Missing age | no fabricated zero-age confidence |
| Below cost | visible warning + explicit operator confirmation |
| No cost | fair market still calculable; cost analytics unavailable |

### 14.5. Confidence/data cases

| Case | Expected |
|---|---|
| `< minimum unique sellers` | `INSUFFICIENT_DATA` |
| Critical UNKNOWN | `MANUAL_REVIEW` |
| Multimodal cohort | fail closed/manual |
| Stale evidence | excluded/manual |
| Seller identity missing | reduced independence; no silent unique count |
| Unvalidated coefficient | no action |

### 14.6. API/UI/security cases

| Case | Expected |
|---|---|
| Absolute-change sort | deterministic descending order |
| Equal deltas | stable documented tie breakers |
| Competitor URL | preserved and openable, protocol validated |
| KEMP evidence | visibly separate from target median |
| Cost API in local-only mode | raw cost absent |
| Log/error snapshot | no raw cost/secret/client row leakage |
| Decision submit | append-only reasoned record; no Prom writeback |

### 14.7. Targeted mutations

Убей минимум следующие mutations:

```text
M-01 restore brand mismatch rejection
M-02 treat brand as identity dimension
M-03 append KEMP_REFERENCE to TARGET_MARKET
M-04 use KEMP price as recommendation guardrail
M-05 replace description with None
M-06 treat UNKNOWN condition as new
M-07 disable used-description marker
M-08 make age beta constant
M-09 reverse age monotonicity
M-10 restore fresh-lower prohibition
M-11 sort by economic priority under absolute-change label
M-12 leak raw cost into response/log fixture
M-13 convert insufficient sample to HOLD/action
M-14 substitute multiplier=1 for unknown coefficient
```

Для каждого mutation запиши command/test that kills it. Если mutation выживает,
acceptance gate не пройден.

---

## 15. Минимальные команды проверки

Сначала обнаружь фактический toolchain. Не устанавливай зависимости молча.

Backend focused baseline/repair suite, если пути существуют:

```bash
cd backend
uv run pytest -q \
  tests/test_matching.py \
  tests/test_comparability_contract.py \
  tests/test_pricing_engine.py \
  tests/test_pricing_engine_matrix.py \
  tests/test_pricing_api.py \
  tests/test_xlsx_catalog.py
```

После focused suite:

```bash
uv run pytest -q
uv run ruff check src tests
uv run python -m compileall -q src tests
uv run alembic upgrade head --sql
```

Flutter, если toolchain доступен:

```bash
cd frontend
flutter analyze
flutter test --no-pub
```

Дополнительно:

- replay test через immutable raw evidence;
- DB/API integration на disposable database;
- migration-from-previous-head test;
- tenant/workspace authorization tests;
- targeted mutation scripts;
- full-stack fixture E2E, если текущая среда позволяет;
- response/footer/machine-summary validators из текущего governance contract.

Отсутствующий tool → `NOT_AVAILABLE` с причиной. Не заменяй его `PASS`.

---

## 16. Обязательные выходные артефакты

Создай в `docs/` либо в существующем governance artifact directory:

1. `PROMPT_15_016_EXECUTION_MANIFEST_YYYY-MM-DD.yaml`
   - repository identity;
   - instructions;
   - pre-change hashes/dirty paths;
   - authority and data/privacy states.

2. `PROMPT_15_016_REQUIREMENTS_TRACE_YYYY-MM-DD.yaml`
   - `R-01…R-17`;
   - baseline hypothesis result;
   - code/tests/schema/UI refs;
   - pre/post status;
   - evidence level.

3. `PROMPT_15_016_IMPLEMENTATION_REPORT_YYYY-MM-DD.md`
   - что изменено и почему;
   - first broken transitions;
   - migrations/API/UI impacts;
   - unresolved decisions;
   - local vs representative vs production claims.

4. `PROMPT_15_016_VARIATION_LEDGER_YYYY-MM-DD.yaml`
   - positive/negative/boundary/metamorphic/mutation cases;
   - commands, hashes, outcomes;
   - survived mutations.

5. `PROMPT_15_016_E2E_EVIDENCE_YYYY-MM-DD.yaml`
   - catalog → collection/replay → comparability → cohorts → pricing → API/UI →
     manual decision trace;
   - first unverified node;
   - no-writeback proof.

6. `PROMPT_15_016_COST_PRIVACY_ADR_YYYY-MM-DD.md`
   - threat model;
   - local-only vs protected-private-server decision;
   - selected/blocked state;
   - data-flow and leakage tests.

7. `PROMPT_15_016_FINAL_GATE_MANIFEST_YYYY-MM-DD.yaml`
   - technical stage gates;
   - business/data/source gates;
   - production implication;
   - exact blockers and owners.

8. `PROMPT_15_016_FINAL_RESPONSE_YYYY-MM-DD.md`
   - concise human outcome;
   - Section 15.1 structured footer;
   - Section 16 machine-readable summary as final substantive block.

Все YAML/JSON должны parse/round-trip. Проверяй duplicate keys, enums, arithmetic,
referential integrity, unique IDs и consistency между human report и machine manifest.

---

## 17. Definition of Done

### 17.1. Requirement-level acceptance

| Requirement | Done only if |
|---|---|
| `R-01` | Same-OE different-brand reaches tier stage; conflicting OE fails closed |
| `R-02` | Tier normalization is downstream of identity and uses validated coefficients |
| `R-03` | Recommendation remains manual; no external writeback path is triggered |
| `R-04` | Age pressure is monotonic and status-aware; scenario tests pass |
| `R-05` | Privacy mode is explicitly selected and enforced, or gate is BLOCKED |
| `R-06` | Literal absolute-change sort exists in API/UI and is tested |
| `R-07` | URLs are preserved/displayed with absence reasons |
| `R-08` | Description cross candidates are isolated from automatic identity |
| `R-09` | Used signals from all available evidence paths hard-reject target inclusion |
| `R-10` | KEMP never affects target median/recommendation; metamorphic test passes |
| `R-11` | Out-of-scope integrations remain absent/disabled |
| `R-12` | Inventory context remains core; no FX/replacement-cost coupling added |
| `R-13` | Cost is not universal floor; below-cost remains explicit/manual/audited |
| `R-14` | No elasticity claim/model presented as valid |
| `R-15` | Real stats measured or explicitly BLOCKED_DATA |
| `R-16` | Prom-only V1 boundary preserved |
| `R-17` | Sparse/conflicting/unknown evidence abstains |

### 17.2. Technical acceptance

```yaml
technical_definition_of_done:
  pre_fix_reproductions: required
  product_code_fixed: required_for_confirmed_gaps
  contradictory_tests_replaced: required
  additive_migrations_valid: required_if_schema_changed
  replay_backward_compatibility: required
  backend_focused_tests: pass
  backend_full_tests: pass_or_precisely_blocked
  static_analysis: pass_or_precisely_blocked
  flutter_tests: pass_or_precisely_blocked
  targeted_mutations: all_named_safety_mutations_killed
  no_parser_internal_change: required_unless_separately_authorized
  no_live_prom_request: required
  no_automatic_writeback: required
  no_cost_leakage: required_for_selected_privacy_mode
  report_manifest_consistency: pass
```

### 17.3. Production acceptance

Production/pilot readiness нельзя получить простым средним score. Hard gates имеют
право veto:

\[
Eligible_{prod}=\mathbf{1}
\left[
\bigwedge_{g\in G_{hard}} status(g)=PASS
\right]
\]

Где минимум:

```text
YURI_V1_SEMANTICS
REPRESENTATIVE_CLIENT_CATALOG
REPRESENTATIVE_MARKET_REPLAY
SOURCE_ACCESS_PERMISSION
COST_PRIVACY_DECISION
TENANT_ISOLATION
BACKUP_RESTORE
OBSERVABILITY
ROLLBACK
POSITIVE_AND_ADVERSARIAL_E2E
```

Если любой hard gate `BLOCKED/UNKNOWN/FAIL`, `production_ready=false` независимо от
локальных tests.

---

## 18. Приоритизация дефектов

Используй RPN только как ordering aid, не как замену hard gates:

\[
RPN_i=S_i\cdot L_i\cdot D_i\cdot C_i
\]

где:

- \(S\in[1,5]\) — severity;
- \(L\in[1,5]\) — likelihood;
- \(D\in[1,5]\) — detection difficulty;
- \(C\in[1,3]\) — dependency centrality.

\[
RPN^{norm}_i=100\cdot\frac{RPN_i-1}{375-1}
\]

Если factors uncertain, храни intervals и сортируй по conservative upper bound. P0/P1
не определяется одним RPN: unsafe identity, wrong target cohort, privacy violation и
external writeback являются hard-gate issues независимо от среднего score.

Рекомендуемый dependency order:

```text
OE identity
  -> comparability
  -> condition/used evidence
  -> cohort partition
  -> tier normalization
  -> fair price/confidence
  -> stock-age recommendation
  -> sorting/operator UX
  -> representative calibration
  -> controlled pilot gates
```

---

## 19. Финальный hostile self-review

Перед ответом действуй как враждебный reviewer и ответь:

1. Какой самый сильный контрпример опровергает OE-first implementation?
2. Можно ли KEMP observation попасть в target через legacy/replay/backfill path?
3. Может ли missing description выглядеть как `condition=new`?
4. Может ли один seller увеличить effective sample size повторными listings?
5. Может ли unknown coefficient silently стать multiplier one?
6. Может ли более старый stock получить менее агрессивное снижение?
7. Может ли cost оказаться в logs/raw row/context snapshot/client error?
8. Является ли UI label математически честным относительно sort key?
9. Может ли тест пройти, хотя реальный frozen payload теряет нужное поле?
10. Выдан ли production claim без representative client/market evidence?
11. Не превратилось ли отсутствие данных в `HOLD` вместо abstention?
12. Не расширился ли scope на Autopro/TecDoc/1С/writeback?

Если ответ «да» или `UNKNOWN`, исправь дефект либо поставь blocker. Не оставляй
самообнаруженную критическую проблему только в caveat.

---

## 20. Обязательный формат финального ответа агента

Ответ начни с terminal outcome, а не с рассказа о процессе:

```text
RESULT: PASS | FAIL | BLOCKED | NO_GO
IMPLEMENTATION_STAGE: PASS | FAIL | BLOCKED
CONTROLLED_PILOT_READY: true | false
PRODUCTION_READY: true | false
FIRST_UNVERIFIED_OR_BROKEN_TRANSITION: <exact transition or NONE>
```

Затем дай:

1. **Что фактически исправлено** — только подтверждённые изменения.
2. **R-01…R-17 status matrix** — `PASS/PARTIAL/BLOCKED/FAIL` с evidence.
3. **Изменённые файлы и migrations** — purpose, not code dump.
4. **Verification** — exact commands/counts и уровни evidence.
5. **Variation/mutation results** — какие контрпримеры проверены.
6. **Оставшиеся blockers** — owner, missing input, affected gate.
7. **Business decisions** — отдельно, без silent default.
8. **Production implication** — отдельно от local implementation result.
9. **Next authorized action** — один dependency-correct следующий шаг.
10. **Section 15.1 structured footer** и **Section 16 machine-readable summary** в
    соответствии с текущими project governance contracts.

Финальный ответ не должен содержать:

- «всё готово» без hard-gate evidence;
- числа без denominator/definition;
- ссылки на несуществующие файлы;
- raw secrets/cost/client rows;
- обещание writeback/deployment;
- предложение пользователю вручную выполнить доступную агенту проверку;
- запуск следующего внешнего stage без отдельной authority.

---

## 21. Последняя исполняемая инструкция

Начни с `STAGE 0`, а не с редактирования кода. Перепроверь baseline hypotheses,
воспроизведи каждый подтверждённый semantic defect, затем исправляй систему в
dependency order. Не защищай текущие тесты, если они закрепляют неправильный Yuri V1
contract. Не ослабляй fail-closed gates. Не переписывай frozen Prom parser без
разрешения. Не делай live Prom requests и не применяй цены.

Работай до terminal outcome. Если независимая техническая работа завершена, но
cost privacy, representative data или source permission отсутствуют, закончи честным
`BLOCKED` именно для зависимого pilot/production scope, сохранив доказанный
implementation `PASS` отдельно.

`STOP_GATE_PROMPT_15_016 = PASS | FAIL | BLOCKED | NO_GO`

<!-- END OF MASTER PROMPT -->
