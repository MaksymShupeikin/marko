# PROMPT 15.018 — CROSS COMMERCIAL COMPARABILITY, SALE PRICE BOUNDARY AND 20→60 OE VALIDATION

- Статус: EXECUTABLE_IMPLEMENTATION_MASTER_PROMPT
- Версия: 1.0.0
- Дата: 2026-07-20
- Язык: русский + machine-oriented identifiers, formulas, pseudocode, SQL/YAML contracts
- Режим: IMPLEMENTATION_AND_VERIFICATION
- Приоритет: P0/P1, FAIL_CLOSED, PRICE_AND_COMMERCIAL_COMPARABILITY
- Целевой проект: Marko + Metis
- Целевой checkout: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия
- Prompt ID: PROMPT_15_018_CROSS_COMMERCIAL_COMPARABILITY_AND_PRICE_BOUNDARY

---

## 0. Назначение

Этот документ — исполнимое задание для ИИ-агента. Агент должен не написать ещё один
аудит, а реализовать и доказать безопасный переход:

~~~text
confirmed cross identity
  -> current payable sale price
  -> explicit reference/strikethrough price
  -> package quantity
  -> commercial unit basis
  -> installation-position equivalence
  -> reviewed brand class / pricing tier
  -> automatic comparability gate
  -> calibration eligibility
  -> pricing eligibility
~~~

Текущий воспроизводимый пример:

~~~yaml
catalog_seed:
  brand: KEMP
  oe_norm: "9065401517"
  title: "Датчик износа тормозных колодок Mercedes Sprinter / VW Crafter"

candidate:
  listing_id: "3122803874"
  seller: VIA-MARKET
  brand: Metzger
  sku: "1190108"
  verified_original_number: "9065401517"
  identity_decision: MATCH
  raw_price: "412"
  price_original: "412"
  discounted_price: "330"
  has_discount: true
  visible_sale_price_uah: "330"
  visible_reference_price_uah: "412"
  measure_unit: "шт."
  package_quantity: null
  installation_position: null
  pricing_tier: unknown
  current_gate: MANUAL_REVIEW
~~~

Identity пары подтверждена. Автоматическая ценовая сопоставимость не подтверждена,
потому что отсутствуют или не утверждены:

1. package_quantity;
2. unit_basis;
3. installation_position_equivalence;
4. approved pricing tier для Metzger.

Дополнительно подтверждён price-boundary defect: downstream использует 412 UAH, хотя
текущая цена покупки равна 330 UAH.

Требуется исправить contracts, code paths, PostgreSQL schema, enrichment, provenance,
tests, replay, observability и staged live validation 20→60 cross-OE. Автоматическое
изменение цен продавца не входит в scope и остаётся запрещённым.

---

# 1. MASTER PROMPT ДЛЯ ИИ-АГЕНТА

## 1.1. Роль

ТЫ — principal backend engineer, data-contract architect, applied statistician,
PostgreSQL migration engineer, automotive comparability engineer, adversarial test
engineer и production-safety reviewer проекта Marko + Metis.

Твоя задача — фактически реализовать
PROMPT_15_018_CROSS_COMMERCIAL_COMPARABILITY_AND_PRICE_BOUNDARY в указанном checkout.
Не ограничивайся советами, планом, псевдокодом, audit-only отчётом или несколькими
unit-тестами.

Терминальный результат:

~~~text
correct code
+ additive/backward-compatible migration
+ deterministic price resolver
+ quantity/unit/position evidence
+ fail-closed tier approval
+ replay and PostgreSQL integration proof
+ bounded 20-OE evaluation
+ conditional 60-OE expansion
+ hostile self-review and repair
+ truthful Section 15/16 final response
~~~

## 1.2. Анти-упрощающий контракт

ОБЯЗАТЕЛЬНО:

1. Не используй бюджет токенов, длину ответа, стоимость работы или объём контекста как
   причину сокращать scope. Системные и безопасностные ограничения соблюдай, но не
   превращай их в предлог для поверхностной реализации.
2. Не упрощай задачу до переименования price, regex для 2 шт. или добавления одной
   записи Metzger в YAML.
3. Не заменяй implementation аудитом. Короткий baseline audit допустим до изменений;
   hostile review обязателен после изменений.
4. Не объявляй UNKNOWN значением 1, PER_PIECE, MATCH, AFTERMARKET_A/B или PASS.
5. Работай по фактам текущего checkout. Старый отчёт не заменяет проверку кода.
6. Пиши отчёты на русском. Идентификаторы, enum, reason codes, SQL, YAML, formulas и
   schemas должны быть machine-readable и однозначными.
7. После каждого слоя запускай targeted tests. После полной реализации проведи
   variation testing, migration testing, replay testing и hostile self-review.
8. Любую найденную на variation ошибку исправь и повтори затронутую матрицу.
9. Не ослабляй hard gates ради coverage, красивого dashboard или количества
   рекомендаций.
10. Не фабрикуй approved_by, approved_at, domain-expert label, source permission,
    package quantity, tier или representative accuracy.
11. Не меняй несвязанные пользовательские файлы, не очищай dirty worktree, не применяй
    destructive Git-команды и не выполняй push без отдельной команды.
12. Не записывай secrets, credentials или неограниченные raw payloads в logs.
13. Не активируй automatic price application. Максимальный допустимый результат этого
    prompt — доказанная eligibility в shadow/manual mode.
14. Существующий Prom parser не переписывай с нуля. Меняй только подтверждённый
    input/output boundary и downstream resolver/enrichment.

## 1.3. Terminal objective

Работа завершена только при одновременном выполнении:

~~~yaml
terminal_objective:
  price_boundary:
    canonical_sale_price: implemented_and_verified
    reference_price_separate: implemented_and_verified
    legacy_price_alias: backward_compatible
    discount_conflicts: fail_closed
  unit_comparability:
    package_quantity: extracted_with_provenance_or_unknown
    unit_basis: normalized_with_provenance_or_unknown
    unit_price: computed_only_when_verified
  position_comparability:
    structured_position_vector: implemented
    equivalence_policy: versioned_and_category_aware
    unknown_or_conflict: manual_review
  tier_safety:
    metzger_commercial_class: evidence_bound
    metzger_pricing_tier: human_approved_or_unknown
    fabricated_approval: impossible
  downstream_safety:
    calibration_requires_complete_verified_comparability: true
    pricing_requires_complete_verified_comparability: true
    reference_price_never_used_as_sale_price: true
  staged_validation:
    oe20_gate: executed_or_truthfully_blocked
    oe60_gate: conditional_on_oe20
    false_match_automatic_lane: 0
    false_sale_price_selection: 0
  production_side_effects:
    seller_prices_changed: 0
    automatic_recommendations_activated: 0
~~~

## 1.4. Execution manifest

Перед изменением кода создай manifest:

~~~yaml
execution_input:
  prompt_id: PROMPT_15_018_CROSS_COMMERCIAL_COMPARABILITY_AND_PRICE_BOUNDARY
  requested_repo: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия
  repo_realpath: DISCOVER
  git_top_level: DISCOVER_OR_NOT_AVAILABLE
  git_commit_before: DISCOVER_OR_NOT_AVAILABLE
  dirty_paths_before: []
  python_version: DISCOVER
  postgresql_version: DISCOVER
  alembic_heads_before: DISCOVER
  parser_contract_version_before: DISCOVER
  price_resolver_version_before: DISCOVER_OR_NOT_IMPLEMENTED
  comparability_policy_version_before: DISCOVER
  brand_rules_version_before: DISCOVER
  source_access_state: DISCOVER_WITHOUT_CHANGING
  live_prom_requests_authorized: false
  automatic_price_application_authorized: false
  baseline_tests:
    command: DISCOVER
    passed: 0
    failed: 0
    skipped: 0
~~~

Если checkout не содержит Git metadata, укажи NOT_AVAILABLE. Не заимствуй commit из
соседней папки. Если live collection не разрешена, полностью реализуй code/replay/migration
scope и верни BLOCKED только для live 20/60 evidence, а не для agent-resolvable кода.

---

# 2. Подтверждённая исходная карта

Сначала перепроверь, затем используй как стартовую карту:

- backend/src/marko/services/parser_models.py уже содержит raw fields price,
  price_original, discounted_price, has_discount, measure_unit, position и
  package_quantity;
- для listing 3122803874 retained snapshot содержит price=412,
  price_original=412, discounted_price=330, has_discount=true;
- backend/src/marko/services/matching.py выбирает product.price раньше
  product.price_original и не учитывает discounted_price;
- backend/src/marko/services/catalog_import.py также выбирает product.price раньше
  product.discounted_price;
- backend/src/marko/services/offer_processing.py принимает только product.price и
  переносит его в AcceptedCandidate.price;
- backend/src/marko/services/market_collection.py сохраняет candidate.price в
  MarketObservation.price;
- backend/src/marko/infrastructure/db/models.py имеет одно market_observations.price,
  но не хранит канонический sale/reference split;
- scripts/run_cross_discovery.py экспортирует только price_uah=product.price;
- backend/src/metis/pricing/comparability.py уже требует position и package_quantity
  для применимых категорий;
- backend/config/brands.yaml fail-closed: domain_policy_approved=false, non-KEMP rules
  не утверждены;
- backend/src/metis/pricing/types.py не содержит общего ProductTier.AFTERMARKET:
  существуют AFTERMARKET_A и AFTERMARKET_B;
- backend/src/metis/pricing/brand_rules.py запрещает активировать non-KEMP rule без
  domain approval, reviewer, timestamp и evidence;
- candidate review сохранён в
  .artifacts/metis_cross_candidate_review_20260720/METIS_CROSS_CANDIDATE_REVIEW_3122803874.yaml;
- общий smoke report находится в docs/METIS_CROSS_LIVE_SMOKE_2026-07-20.md.

Если конкретные строки уже изменились, адаптируй implementation к текущему состоянию,
но сохрани инварианты prompt.

---

# 3. Жёсткие границы

НЕ ДЕЛАТЬ:

- не проектировать новый scraper;
- не трактовать price_original или зачёркнутую цену как текущую цену покупки;
- не удалять исходные price fields;
- не разрушать replay старых Product snapshots;
- не предполагать package_quantity=1 только из measure_unit=шт.;
- не делить цену на количество, извлечённое из OE, года, размера, двигателя или model id;
- не считать изображение единственной детали доказательством package quantity;
- не считать exact OE автоматическим доказательством одинаковой упаковки;
- не считать exact OE автоматическим доказательством front/rear/left/right;
- не преобразовывать UNKNOWN position в NOT_APPLICABLE;
- не маппить Metzger в AFTERMARKET_A или AFTERMARKET_B без доменного решения;
- не добавлять фиктивные approved_by/approved_at;
- не включать в calibration reference/strikethrough price;
- не включать в calibration normalized unit price без verified unit basis;
- не расширять live test до 60 OE, если 20-OE gate не прошёл;
- не интерпретировать 20/20 или 60/60 без ошибок как доказательство 100% production
  precision;
- не выполнять automatic pricing writes.

---

# 4. Нормативный price contract

## 4.1. Термины

~~~text
P_raw        = normalized Product.price
P_original   = normalized Product.price_original
P_discounted = normalized Product.discounted_price
D_flag       = Product.has_discount
P_sale       = current payable sale price
P_ref        = old/reference/strikethrough price
Delta        = P_ref - P_sale
r_discount   = Delta / P_ref
r_overstate  = Delta / P_sale
~~~

Для текущего дефекта:

~~~text
P_sale = 330
P_ref = 412
Delta = 412 - 330 = 82
r_discount = 82 / 412 = 0.199029... = 19.90%
r_overstate = 82 / 330 = 0.248484... = 24.85%
~~~

Не смешивай denominator:

- 19.90% — скидка относительно старой цены;
- 24.85% — завышение, если старую цену ошибочно использовать вместо текущей.

## 4.2. Canonical resolver

Создай один versioned resolver, например:

~~~text
backend/src/marko/services/price_evidence.py

resolve_price_evidence(
  price,
  price_original,
  discounted_price,
  has_discount,
  currency,
  provenance
) -> ResolvedPriceEvidence
~~~

Запрещено оставлять отдельные расходящиеся функции в matching, catalog_import,
offer_processing и scripts.

Нормативная модель:

~~~yaml
ResolvedPriceEvidence:
  sale_price: Decimal|null
  reference_price: Decimal|null
  currency: string|null
  discount_state: EXPLICIT|INFERRED|NONE|CONFLICT|UNKNOWN
  selection_state: VERIFIED|PARTIAL|CONFLICT|INVALID
  selected_source: DISCOUNTED_PRICE|PRICE|PRICE_ORIGINAL|NONE
  raw:
    price: string|null
    price_original: string|null
    discounted_price: string|null
    has_discount: boolean|null
  discount_amount: Decimal|null
  discount_ratio: Decimal|null
  overstatement_ratio: Decimal|null
  reason_codes: [string]
  method_version: sale-price-resolver-v1
  provenance: EvidenceProvenance
~~~

## 4.3. Selection truth table

Реализуй и протестируй минимум:

| D_flag | P_raw | P_original | P_discounted | P_sale | P_ref | State |
|---|---:|---:|---:|---:|---:|---|
| true | 412 | 412 | 330 | 330 | 412 | VERIFIED/EXPLICIT |
| true | 330 | 412 | 330 | 330 | 412 | VERIFIED/EXPLICIT |
| true | 330 | 412 | null | 330 | 412 | VERIFIED/EXPLICIT |
| false | 412 | 412 | null | 412 | null | VERIFIED/NONE |
| null | 412 | 412 | null | 412 | null | VERIFIED/DIRECT |
| null | 412 | 412 | 330 | 330 | 412 | PARTIAL/INFERRED |
| true | 330 | 300 | 330 | null | null | CONFLICT |
| true | 412 | 412 | null | null | null | CONFLICT |
| false | 412 | 412 | 330 | null | null | CONFLICT |
| any | NaN/0/-1 | any | any | null | null | INVALID |

Правила:

1. При D_flag=true валидный P_discounted имеет приоритет как P_sale.
2. Если D_flag=true и P_discounted отсутствует, но P_raw<P_original, используй
   P_raw как sale и P_original как reference.
3. P_ref выбирается из непротиворечивого reference candidate только если P_ref>P_sale.
   Если P_raw и P_original образуют два разных reference candidate выше P_sale,
   результат CONFLICT до явного source-specific contract.
4. При D_flag=false различающийся P_discounted — конфликт, а не скрытая скидка.
5. При D_flag=null и ровно одной непротиворечивой цене без discounted alternative
   допускается VERIFIED/DIRECT. Отсутствие флага само по себе не делает payable price
   неизвестной.
6. При D_flag=null и наличии меньшей discounted alternative допускается INFERRED только
   как evidence, но automatic eligibility
   остаётся false до подтверждения policy.
7. Если P_ref=P_sale, reference_price=null; бессодержательную reference price не храни.
8. Если P_ref<P_sale, ставь CONFLICT.
9. Все Decimal должны быть finite, positive и quantized согласно currency policy.
10. Sale price — единственная цена, допустимая в market statistics и calibration.
11. Reference price хранится для audit/discount analytics и никогда не является
   самостоятельным market offer.

## 4.4. Backward compatibility

- Сохрани Product.price, price_original, discounted_price, has_discount как raw source
  contract.
- MarketObservation.price временно сохрани как compatibility alias P_sale.
- Все новые записи обязаны удовлетворять price == sale_price.
- Старые записи backfill: sale_price=price, reference_price=null,
  price_selection_state=LEGACY_SINGLE_PRICE.
- Legacy rows нельзя автоматически объявить verified discount evidence.
- До replay legacy rows должны иметь automatic_eligible=false и reason
  LEGACY_PRICE_EVIDENCE_UNVERIFIED, если их eligibility зависит от новой price
  семантики.

---

# 5. PostgreSQL schema и migration

## 5.1. Additive columns

Добавь в market_observations, если текущая схема подтверждает необходимость:

~~~text
sale_price NUMERIC(14,2)
reference_price NUMERIC(14,2) NULL
discount_amount NUMERIC(14,2) NULL
discount_ratio NUMERIC(12,8) NULL
price_selection_state VARCHAR(32)
discount_state VARCHAR(32)
price_selected_source VARCHAR(32)
price_reason_codes JSON
price_evidence JSON
price_resolver_version VARCHAR(80)
package_quantity INTEGER NULL
package_quantity_state VARCHAR(32)
unit_basis VARCHAR(32)
unit_comparability_state VARCHAR(32)
normalized_unit_price NUMERIC(14,4) NULL
unit_evidence JSON
unit_policy_version VARCHAR(80)
position_vector JSON
position_evidence JSON
position_equivalence_state VARCHAR(32)
position_policy_version VARCHAR(80)
commercial_class VARCHAR(32)
commercial_class_evidence JSON
~~~

Проверь существующие имена и избегай дублирования. Не смешивай
MarketObservation.reference_price со смыслом TierCalibrationPair.reference_price:
одинаковое имя допустимо в разных таблицах, но семантика должна быть документирована.

## 5.2. Constraints

Минимальные constraints:

~~~sql
CHECK (sale_price > 0);
CHECK (price = sale_price);
CHECK (reference_price IS NULL OR reference_price > sale_price);
CHECK (
  price_selection_state IN
  ('VERIFIED','PARTIAL','CONFLICT','INVALID','LEGACY_SINGLE_PRICE')
);
CHECK (
  discount_state IN
  ('EXPLICIT','INFERRED','NONE','CONFLICT','UNKNOWN','LEGACY_UNKNOWN')
);
CHECK (
  (reference_price IS NULL AND discount_amount IS NULL AND discount_ratio IS NULL)
  OR
  (
    reference_price IS NOT NULL
    AND discount_amount = reference_price - sale_price
    AND discount_ratio >= 0
    AND discount_ratio < 1
    AND abs(
      discount_ratio
      - ((reference_price - sale_price) / reference_price)
    ) <= 0.00000001
  )
);
CHECK (package_quantity IS NULL OR package_quantity > 0);
CHECK (normalized_unit_price IS NULL OR normalized_unit_price > 0);
CHECK (
  package_quantity_state IN
  ('VERIFIED','INFERRED','CONFLICT','UNKNOWN','NOT_APPLICABLE','LEGACY_UNKNOWN')
);
CHECK (
  unit_comparability_state IN
  ('MATCH','CONFLICT','UNKNOWN','NOT_APPLICABLE','LEGACY_UNKNOWN')
);
CHECK (
  position_equivalence_state IN
  ('MATCH','CONFLICT','UNKNOWN','NOT_APPLICABLE','LEGACY_UNKNOWN')
);
CHECK (
  normalized_unit_price IS NULL
  OR (
    package_quantity IS NOT NULL
    AND unit_basis IN ('PER_PIECE','PER_PAIR','PER_SET','PER_KIT')
  )
);
~~~

Automatic eligibility должна дополнительно требовать:

~~~text
price_selection_state = VERIFIED
AND sale_price IS NOT NULL
AND unit_comparability_state IN {MATCH, NOT_APPLICABLE}
AND position_equivalence_state IN {MATCH, NOT_APPLICABLE}
AND package_quantity evidence is sufficient for category policy
AND approved pricing tier exists
~~~

## 5.3. Migration order

~~~text
1. Add nullable columns and enums/checks that accept legacy state.
2. Backfill sale_price=price and LEGACY_SINGLE_PRICE.
3. Deploy resolver writers.
4. Replay retained captures into new evidence fields.
5. Measure unknown/conflict counts.
6. Add stricter NOT NULL/check constraints only when every row is compatible.
7. Switch readers to canonical fields.
8. Keep compatibility alias until a later separately reviewed migration.
~~~

Upgrade и downgrade проверь на disposable PostgreSQL. SQLite-only test недостаточен.

---

# 6. Package quantity и unit basis

## 6.1. Разделение понятий

~~~text
listing_unit       = коммерческая единица объявления
measure_unit       = upstream label, например "шт."
package_quantity   = число физически сопоставимых деталей в listing_unit
unit_basis         = PER_PIECE|PER_PAIR|PER_SET|PER_KIT|PER_PACKAGE|UNKNOWN|NOT_APPLICABLE
P_unit             = P_sale / Q_effective
~~~

measure_unit=шт. НЕ доказывает package_quantity=1. Оно сообщает только единицу продажи,
но комплект может содержать 2 датчика, 4 колодки или набор.

## 6.2. Evidence provenance

Каждый extracted fact:

~~~yaml
EvidenceAtom:
  field: package_quantity|unit_basis|position
  raw_value: string|null
  normalized_value: any
  source_kind: STRUCTURED_FIELD|CHARACTERISTIC|TITLE|DESCRIPTION|DETAIL_PAGE|CATEGORY_POLICY
  source_path: string|null
  source_span: string|null
  raw_capture_sha256: string
  extractor_version: string
  confidence: Decimal
  state: VERIFIED|INFERRED|CONFLICT|UNKNOWN|NOT_APPLICABLE
  observed_at: RFC3339
~~~

Без raw_capture_sha256 и source_path/span evidence не может включить automatic lane.

## 6.3. Source precedence

~~~text
explicit structured characteristic
  > explicit comparisonEvidence
  > explicit title/description phrase
  > approved category-specific default
  > UNKNOWN
~~~

При двух несовместимых значениях результат CONFLICT независимо от confidence.

## 6.4. Quantity extractor

Поддержи украинские, русские и распространённые латинские маркеры:

~~~text
1 шт, 2 шт., 2 штуки, 2 штуки в комплекте
комплект 2 шт, к-кт 2 шт, набір 2 шт
пара, pair, set of 2, 2 pcs
упаковка 4 шт, package 4 pcs
~~~

Обязательные negative cases:

~~~text
2E0906206A
9065401517
W639
115 CDI
2003.09
L=103 мм
24V
2.0 TDI
1190108
~~~

Ни одно число из negative cases не может стать package_quantity.

## 6.5. Unit normalization

P_unit разрешено вычислять только когда:

~~~text
P_sale verified
AND package_quantity verified
AND package_quantity > 0
AND category policy confirms divisibility/comparability
AND no conflicting unit evidence
~~~

Для PER_PAIR/PER_SET/PER_KIT не дели цену автоматически, если составляющие набора не
эквивалентны одной seed unit. В таком случае normalized_unit_price=null и MANUAL_REVIEW.

---

# 7. Installation position

## 7.1. PositionVector

Введи structured representation:

~~~yaml
PositionVector:
  axle: FRONT|REAR|BOTH|UNKNOWN|NOT_APPLICABLE
  side: LEFT|RIGHT|BOTH|UNIVERSAL|UNKNOWN|NOT_APPLICABLE
  vertical: UPPER|LOWER|UNKNOWN|NOT_APPLICABLE
  radial: INNER|OUTER|UNKNOWN|NOT_APPLICABLE
  orientation: INPUT|OUTPUT|UNKNOWN|NOT_APPLICABLE
  free_text_norm: string|null
~~~

Не все dimensions применимы ко всем категориям. Category policy обязана явно задавать
required, optional и approved_not_applicable dimensions.

## 7.2. Equivalence

~~~text
E_pos(seed,candidate,category_policy) ∈ {MATCH, CONFLICT, UNKNOWN, NOT_APPLICABLE}
~~~

Правила:

- любой required dimension CONFLICT => overall CONFLICT;
- required UNKNOWN при отсутствии approved inference => overall UNKNOWN;
- все required MATCH/NOT_APPLICABLE => MATCH;
- NOT_APPLICABLE разрешён только versioned category policy;
- exact OE усиливает identity, но не подменяет position evidence;
- front и rear — конфликт;
- left и right — конфликт, кроме policy=side_interchangeable;
- candidate UNKNOWN против seed FRONT => MANUAL_REVIEW.

Для текущей пары 9065401517 ↔ 1190108 identity=MATCH, но position остаётся UNKNOWN,
пока retained evidence или authoritative catalog не подтвердит эквивалентность.

---

# 8. Metzger: commercial class против pricing tier

## 8.1. Не скрывать несовпадение taxonomy

Текущий ProductTier содержит:

~~~text
OEM, OES, AFTERMARKET_A, AFTERMARKET_B, BUDGET, KEMP, USED, UNKNOWN
~~~

Общего ProductTier.AFTERMARKET нет. Поэтому строка Metzger → AFTERMARKET не может быть
молча преобразована в AFTERMARKET_A или AFTERMARKET_B.

## 8.2. Нормативное безопасное решение

Раздели:

~~~text
commercial_class ∈ {OEM, OES, AFTERMARKET, KEMP, USED, UNKNOWN}
pricing_tier ∈ existing ProductTier
~~~

До доменного решения допустимо:

~~~yaml
brand: Metzger
commercial_class: AFTERMARKET
commercial_class_state: EVIDENCE_SUPPORTED_DRAFT
pricing_tier: UNKNOWN
approved: false
automatic_eligible: false
~~~

Для активации pricing tier требуются:

- реальный approved_by;
- approved_at;
- evidence references;
- scope: global или category-specific;
- минимум одна versioned review выборка;
- решение, является ли Metzger AFTERMARKET_A, AFTERMARKET_B, BUDGET или отдельным новым
  ProductTier;
- migration всех consumers, если вводится новый enum;
- replay и coefficient compatibility test.

Нельзя подставлять имя пользователя, разработчика или ИИ как доменного reviewer без
явного подтверждения.

## 8.3. Brand rule negative tests

- approved=true при domain_policy_approved=false => reject;
- отсутствует approved_by => reject;
- отсутствует approved_at => reject;
- evidence пуст => reject;
- normalized не равно normalize_brand(Metzger) => reject;
- generic AFTERMARKET передан в enum без такого значения => reject;
- conflicting category rules => CONFLICT/UNKNOWN;
- draft rule не меняет runtime classification.

---

# 9. Comparability и automatic gate

## 9.1. Commercial comparability vector

~~~text
X = (
  identity,
  condition,
  currency,
  sale_price,
  package_quantity,
  unit_basis,
  normalized_unit_price,
  position,
  category,
  pricing_tier,
  seller_identity,
  provenance
)
~~~

Hard gate:

~~~text
G_auto =
  G_identity
* G_condition
* G_currency
* G_sale_price
* G_unit
* G_position
* G_category
* G_tier
* G_seller
* G_provenance
~~~

Каждый G_i бинарный:

~~~text
G_auto = 1 => candidate may enter automatic cohort
G_auto = 0 => candidate must not enter calibration/pricing
~~~

Soft confidence не может компенсировать hard-gate zero.

## 9.2. Current candidate expected result

После price fix, но до unit/position/tier approval:

~~~yaml
listing_id: "3122803874"
identity: MATCH
condition: NEW
sale_price: "330.00"
reference_price: "412.00"
package_quantity: null
unit_basis: UNKNOWN
position_equivalence: UNKNOWN
commercial_class: AFTERMARKET
pricing_tier: UNKNOWN
automatic_eligible: false
hard_gate_result: MANUAL_REVIEW
reason_codes:
  - MANUAL_MISSING_PACKAGE_QUANTITY
  - MANUAL_MISSING_UNIT_BASIS
  - MANUAL_MISSING_POSITION
  - MANUAL_MISSING_APPROVED_TIER
~~~

Reference price 412 не должна появиться как отдельный offer.

## 9.3. Calibration predicate

Calibration допускает observation только если:

~~~text
automatic_eligible = true
AND comparability_hard_gate_result = PASS
AND verified_matched_oe_norm IS NOT NULL
AND price_selection_state = VERIFIED
AND price = sale_price
AND normalized unit basis is comparable
AND position equivalence is MATCH or approved NOT_APPLICABLE
AND pricing_tier != UNKNOWN
AND seller identity verified
AND source provenance verified
~~~

Reference/old prices и manual-review candidates исключаются с typed reason codes.

---

# 10. Code integration map

После baseline audit реализуй единственный canonical path:

~~~text
Product raw fields
  -> resolve_price_evidence()
  -> process_offer_candidate()
  -> AcceptedCandidate.price_evidence
  -> MarketObservation sale/reference persistence
  -> package/unit/position enrichment
  -> ComparisonEvidence
  -> automatic_eligible
  -> calibration/pricing readers
~~~

Обязательные consumers resolver:

- services/matching.py;
- services/catalog_import.py;
- services/offer_processing.py;
- services/market_collection.py;
- scripts/run_cross_discovery.py;
- serializers/API/export paths, если они читают observation.price;
- replay and fixture builders.

Удаляй или депрекейтируй локальные price fallback functions. Repository search не должен
обнаружить runtime path, который выбирает price раньше discounted_price в обход resolver.
Canonical price arithmetic и persistence выполняй через Decimal. Если legacy API требует
float, conversion допускается только в явном compatibility adapter после canonical
resolution; float не должен участвовать в выборе sale/reference или расчёте коэффициента.

---

# 11. Outcome taxonomy и observability

Добавь typed outcomes/reasons:

~~~text
PRICE_RESOLVED_EXPLICIT_DISCOUNT
PRICE_RESOLVED_DIRECT
PRICE_INFERRED_DISCOUNT_MANUAL
PRICE_CONFLICT_DISCOUNT_FLAG
PRICE_CONFLICT_REFERENCE_BELOW_SALE
PRICE_INVALID_NON_POSITIVE
PRICE_INVALID_NON_DECIMAL
PACKAGE_QUANTITY_VERIFIED
PACKAGE_QUANTITY_UNKNOWN
PACKAGE_QUANTITY_CONFLICT
UNIT_BASIS_VERIFIED
UNIT_BASIS_UNKNOWN
UNIT_BASIS_CONFLICT
POSITION_MATCH
POSITION_UNKNOWN
POSITION_CONFLICT
TIER_DRAFT_NOT_APPROVED
TIER_APPROVED
COMMERCIAL_COMPARABILITY_PASS
COMMERCIAL_COMPARABILITY_MANUAL
COMMERCIAL_COMPARABILITY_REJECT
~~~

Метрики:

~~~text
price_discount_explicit_total
price_discount_inferred_total
price_conflict_total
reference_price_present_total
sale_reference_spread_ratio
package_quantity_verified_total
package_quantity_unknown_total
package_quantity_conflict_total
unit_basis_verified_total
unit_basis_unknown_total
position_match_total
position_unknown_total
position_conflict_total
tier_unknown_total
automatic_eligible_total
manual_review_total
calibration_excluded_price_total
calibration_excluded_unit_total
calibration_excluded_position_total
calibration_excluded_tier_total
~~~

Не логируй полный HTML. Логируй IDs, hashes, reason codes, versions и безопасные samples.

---

# 12. Test matrix

## 12.1. Price unit tests

Покрой всю truth table и вариации:

- пробелы, NBSP, comma decimal;
- 330, 330.0, 330.00;
- null/empty;
- NaN/Infinity;
- zero/negative;
- reference=sale;
- reference<sale;
- discounted>reference;
- has_discount type mismatch;
- currency missing/conflict;
- deterministic serialization/hash;
- Decimal, без float для persistence/math.

Текущий regression fixture обязателен:

~~~text
price=412
price_original=412
discounted_price=330
has_discount=true
=> sale_price=330
=> reference_price=412
=> discount_amount=82
=> discount_ratio=0.19902913 within declared quantization
=> overstatement_ratio=0.24848485 within declared quantization
~~~

## 12.2. Quantity/unit tests

Positive and negative examples из раздела 6. Дополнительно:

- комплект 2 шт против seed 1 шт => CONFLICT/MANUAL according to policy;
- пара датчиков => quantity=2, basis=PER_PAIR;
- 1 шт explicit => quantity=1, PER_PIECE;
- measure_unit=шт без explicit quantity => quantity UNKNOWN;
- два conflicting spans => CONFLICT;
- category policy default без approval => UNKNOWN;
- normalization deterministic under word order/case changes.

## 12.3. Position tests

- FRONT vs FRONT => MATCH;
- FRONT vs REAR => CONFLICT;
- LEFT vs RIGHT => CONFLICT;
- BOTH vs LEFT => policy-driven, not implicit;
- UNKNOWN vs FRONT => UNKNOWN;
- NOT_APPLICABLE only with approved policy;
- OE exact with position unknown => identity MATCH, position UNKNOWN;
- multilingual markers: передний/передній/front, задний/задній/rear,
  левый/лівий/left, правый/правий/right.

## 12.4. Tier tests

Все negative tests из 8.3 и:

- Metzger draft commercial class does not enable pricing;
- approved existing tier changes runtime only after valid policy load;
- historical replay pins rules version;
- changing tier rule changes dataset/coefficient hash;
- removing rule returns UNKNOWN, not stale cached tier.

## 12.5. PostgreSQL tests

- migration upgrade on representative legacy rows;
- downgrade or documented irreversible boundary;
- constraints reject sale<=0;
- constraints reject reference<=sale;
- constraints reject normalized unit price without quantity/basis;
- automatic_eligible cannot coexist with unknown unit/position/tier;
- price compatibility alias equals sale_price;
- idempotent replay/upsert;
- duplicate observation does not create a second active evidence row.

## 12.6. Replay E2E

Replay retained candidate 3122803874 without network:

~~~text
raw Product snapshot
-> price resolver
-> observation
-> comparison evidence
-> MANUAL_REVIEW
~~~

Expected:

- sale=330;
- reference=412;
- identity MATCH;
- no automatic calibration pair;
- no price recommendation;
- zero network requests;
- deterministic output hash on repeated run.

---

# 13. Staged 20→60 cross-OE validation

## 13.1. General constraints

- Используй только CONFIRMED one-hop cross links.
- Не используй transitive closure.
- Сохраняй raw captures и normalized outputs.
- Одно объявление продавца не считай несколькими независимыми sellers.
- Owned sellers исключай из target market.
- Никаких automatic price writes.
- Live requests выполняй только в существующей разрешённой source scope.
- Если permission отсутствует, не подменяй live stage replay-данными.

## 13.2. Deterministic sample 20

Выбери 20 unique cross-OE детерминированно, с manifest и seed. Стратифицируй:

~~~text
category
source seller count
cross confidence
presence of discount
presence of quantity markers
presence of position markers
brand known/unknown
price ratio risk
~~~

Не выбирай только простые положительные примеры.

Для каждого cross-OE сохрани:

~~~yaml
evaluation_row:
  our_oe_norm: string
  cross_oe_norm: string
  cross_link_id: UUID
  listing_id: string
  seller_id: string
  raw_capture_sha256: string
  predicted_identity: MATCH|NOT_MATCH|UNCERTAIN
  reviewed_identity: MATCH|NOT_MATCH|UNCERTAIN
  sale_price_predicted: Decimal|null
  sale_price_reviewed: Decimal|null
  reference_price_predicted: Decimal|null
  reference_price_reviewed: Decimal|null
  package_quantity_predicted: int|null
  package_quantity_reviewed: int|null
  unit_basis_predicted: enum
  unit_basis_reviewed: enum
  position_predicted: PositionVector
  position_reviewed: PositionVector
  commercial_class_predicted: enum
  pricing_tier_predicted: ProductTier
  pricing_tier_reviewed: ProductTier|UNKNOWN
  reviewer_type: AI_ASSISTED|DOMAIN_EXPERT|OPERATOR
  reviewer_id: string|null
  evidence_refs: [string]
  automatic_eligible: boolean
  final_reason_codes: [string]
~~~

ИИ может выполнить evidence-backed visual pre-review, но обязан указать
reviewer_type=AI_ASSISTED. Это не заменяет domain approval tier.

## 13.3. Metrics

~~~text
TP = predicted MATCH and reviewed MATCH
FP = predicted MATCH and reviewed NOT_MATCH
FN = predicted NOT_MATCH and reviewed MATCH
TN = predicted NOT_MATCH and reviewed NOT_MATCH

Precision_match = TP / (TP + FP)
Recall_match = TP / (TP + FN)

E_price_i = abs(P_sale_pred_i - P_sale_review_i) / P_sale_review_i
Price_exact_rate = count(E_price_i = 0) / N_price_labeled

Unit_exact_rate =
  correct(package_quantity, unit_basis) / N_unit_applicable_labeled

Position_exact_rate =
  correct(PositionVector) / N_position_applicable_labeled

Auto_completeness =
  complete_verified_auto_rows / automatic_eligible_rows

Coverage_auto = automatic_eligible_rows / retrieved_independent_offers
Review_rate = manual_review_rows / retrieved_independent_offers
~~~

UNKNOWN не является ошибкой, если система корректно abstain. Но UNKNOWN не входит в
automatic coverage.

UNCERTAIN review labels не включай в TP/FP/FN/TN denominator. Покажи их отдельным
счётчиком и coverage. Запрещено удалять UNCERTAIN строки из evaluation dataset.

## 13.4. Wilson lower bound

Для observed precision p_hat и n predicted positives:

~~~text
LB95 =
  (
    p_hat + z^2/(2n)
    - z * sqrt(p_hat*(1-p_hat)/n + z^2/(4n^2))
  )
  / (1 + z^2/n)

z = 1.96
~~~

Важно:

- 20/20 без ошибок даёт LB95 примерно 0.839;
- 60/60 без ошибок даёт LB95 примерно 0.940.

Следовательно, zero observed errors на 20 или 60 — инженерный promotion gate, но не
доказательство production precision>=0.95. Не завышай claim.

## 13.5. Gate 20

Переход к 60 разрешён только если:

~~~yaml
gate_20:
  unique_cross_oes: 20
  label_completeness: 1.0
  reviewed_retained_candidates_min: 10
  price_labeled_candidates_min: 10
  unit_applicable_labeled_min: 10
  position_applicable_labeled_min: 10
  false_match_in_automatic_lane: 0
  false_sale_price_selection: 0
  reference_price_used_as_sale: 0
  automatic_rows_with_unknown_package_or_unit: 0
  automatic_rows_with_unknown_position: 0
  automatic_rows_with_unknown_tier: 0
  automatic_rows_without_provenance: 0
  retained_offer_accounting_conserved: true
  seller_price_writes: 0
  decision:
    all_pass: PROMOTE_TO_60
    insufficient_denominator: BLOCKED_INSUFFICIENT_VALIDATION_DATA
    any_fail: STOP_AND_REPAIR
~~~

Thresholds non-vacuity обязательны. Нулевой automatic lane, нулевой retained set или
недостаточный denominator не являются PASS даже при нуле ошибок. Если реальных
retained/applicable examples меньше threshold, верни
BLOCKED_INSUFFICIENT_VALIDATION_DATA и расширь evidence только отдельным разрешённым
действием; не понижай threshold после просмотра результата.

При fail:

1. останови expansion;
2. классифицируй root cause;
3. исправь agent-resolvable code/policy;
4. повтори affected 20 sample;
5. не меняй sample seed после ошибки;
6. только после чистого rerun переходи к 60.

## 13.6. Gate 60

~~~yaml
gate_60:
  unique_cross_oes: 60
  includes_original_20: true
  label_completeness: 1.0
  reviewed_retained_candidates_min: 30
  price_labeled_candidates_min: 30
  unit_applicable_labeled_min: 30
  position_applicable_labeled_min: 30
  false_match_in_automatic_lane: 0
  false_sale_price_selection: 0
  automatic_completeness: 1.0
  unit_exact_rate_for_automatic_lane: 1.0
  position_exact_rate_for_automatic_lane: 1.0
  reference_price_leakage_to_market_distribution: 0
  calibration_pairs_from_manual_review: 0
  seller_price_writes: 0
  output: SHADOW_EVALUATION_ONLY
~~~

Если любой denominator gate60 меньше 30, результат не PASS, а
BLOCKED_INSUFFICIENT_VALIDATION_DATA. Не интерпретируй отсутствие automatic rows как
доказательство безопасности classifier.

Даже PASS gate_60 не активирует production pricing. Следующий stage должен быть
representative domain-reviewed evaluation с заранее утверждёнными precision thresholds.

---

# 14. Variation testing

Проведи не только happy-path tests, но и минимум следующие вариации.

## 14.1. Price variations

- explicit sale/reference;
- no discount;
- inferred discount;
- flag conflict;
- stale reference;
- malformed decimal;
- currency mismatch;
- duplicated offer with changed sale price;
- same listing observed at two times;
- sale price disappears on replay;
- reference price changes, sale stays same;
- discount ends: 330/412 -> 412/null.

## 14.2. Quantity variations

- single;
- pair;
- homogeneous kit;
- heterogeneous kit;
- pack size in title;
- pack size only in characteristics;
- conflicting title and characteristic;
- numerical noise;
- missing description;
- multilingual spelling;
- Unicode/NBSP/hyphen variations.

## 14.3. Position variations

- explicit match;
- explicit conflict;
- one side universal;
- category position not applicable;
- seed position unknown;
- candidate position unknown;
- exact OE with title conflict;
- multiple vehicle fitments;
- left/right language aliases.

## 14.4. Tier variations

- no rules file;
- draft rule;
- invalid approval metadata;
- category-scoped rule;
- global/category conflict;
- rules version changed between replay and current run;
- generic commercial class without pricing tier.

## 14.5. Operational variations

- duplicate delivery;
- process restart after persistence before acknowledgement;
- migration on legacy observations;
- replay under newer Product fields;
- partial raw capture;
- parser schema drift;
- 429/timeout does not become empty market;
- source permission blocked before HTTP request;
- deterministic artifacts across repeated replay.

---

# 15. Rollout, rollback и compatibility

## 15.1. Rollout

~~~text
Phase A: schema expand
Phase B: resolver + dual write price/sale/reference
Phase C: retained replay and evidence backfill
Phase D: quantity/unit/position enrichment in shadow
Phase E: comparability gate readers
Phase F: 20-OE validation
Phase G: conditional 60-OE validation
Phase H: domain tier approval in separate signed artifact
~~~

## 15.2. Rollback

- Старый код не должен записывать price, расходящийся с sale_price.
- Если mixed-version deploy небезопасен, используй coordinated deploy или DB protection.
- Rollback не должен превращать reference price в sale price.
- Не удаляй evidence columns в аварийном rollback.
- Документируй, какие readers совместимы с LEGACY_SINGLE_PRICE.

## 15.3. Idempotency

Observation identity должна учитывать listing identity и observed_at/run semantics, но
повторная обработка одного retained capture не должна создавать расходящиеся canonical
facts. Изменение resolver version должно создавать явный re-enrichment event, а не тихо
переписывать историю без lineage.

---

# 16. Required artifacts

ИИ-агент должен создать:

~~~yaml
required_artifacts:
  - implementation_manifest
  - changed_files_manifest
  - price_contract_document
  - alembic_migration
  - migration_upgrade_downgrade_report
  - retained_candidate_replay_report
  - quantity_unit_extraction_report
  - position_equivalence_report
  - metzger_tier_decision_template
  - oe20_sample_manifest
  - oe20_evaluation_dataset
  - oe20_metrics_report
  - oe60_sample_manifest_if_gate20_passes
  - oe60_evaluation_dataset_if_authorized
  - oe60_metrics_report_if_executed
  - calibration_exclusion_report
  - hostile_self_review
  - command_evidence
  - final_section_15_16_response
~~~

Для command evidence:

~~~yaml
command_evidence:
  command: string
  cwd: string
  exit_code: int
  result: PASS|FAIL|BLOCKED|SKIPPED
  summary: string
  log_path: string|null
  log_sha256: string|null
~~~

---

# 17. Acceptance criteria

## 17.1. Functional

- [ ] Listing 3122803874 resolves sale=330 and reference=412.
- [ ] Price resolver является единственным canonical runtime path.
- [ ] Reference price не попадает в market distribution/calibration.
- [ ] MarketObservation сохраняет price evidence и resolver version.
- [ ] Legacy rows не становятся verified discount evidence.
- [ ] package_quantity не выводится из measure_unit=шт.
- [ ] Numeric noise не становится quantity.
- [ ] unit price вычисляется только из verified comparable unit.
- [ ] position имеет typed vector и category-aware equivalence.
- [ ] exact OE с unknown position остаётся manual.
- [ ] generic AFTERMARKET отделён от pricing tier.
- [ ] Metzger rule не активируется без реального approval.
- [ ] Calibration требует полный PASS.
- [ ] Current candidate остаётся MANUAL_REVIEW до закрытия четырёх полей.

## 17.2. Verification

- [ ] Price variation matrix зелёная.
- [ ] Quantity/unit variation matrix зелёная.
- [ ] Position variation matrix зелёная.
- [ ] Tier fail-closed matrix зелёная.
- [ ] PostgreSQL migration/constraint tests зелёные.
- [ ] Retained replay network requests=0.
- [ ] Full backend suite зелёный.
- [ ] Ruff/format/type/compile checks зелёные или честно BLOCKED.
- [ ] 20-OE gate выполнен либо конкретно BLOCKED по external input.
- [ ] 60-OE не стартовал при failed 20 gate.

## 17.3. Mathematical gate

~~~text
G_stage =
  G_price
* G_migration
* G_unit
* G_position
* G_tier_safety
* G_downstream
* G_replay
* G_variation
~~~

~~~text
G_stage = 1 => implementation stage may PASS
G_stage = 0 => implementation stage must FAIL or BLOCKED
~~~

Live evaluation gates учитываются отдельно:

~~~text
G_live = G_20 * G_60
~~~

Implementation может PASS при G_stage=1 и G_live=0 только если live scope внешне
BLOCKED и это не маскируется как representative validation. Production readiness остаётся
false.

---

# 18. Hostile self-review

После зелёных тестов ответь доказательно:

1. Есть ли runtime путь, который всё ещё берёт price=412 раньше discounted_price=330?
2. Может ли reference price попасть в median/IQR/MAD/calibration?
3. Может ли discount conflict попасть в automatic lane?
4. Может ли legacy price считаться verified без replay?
5. Может ли measure_unit=шт превратиться в package_quantity=1?
6. Может ли OE/model/year/size стать quantity?
7. Может ли heterogeneous kit быть ошибочно поделен на pieces?
8. Может ли exact OE скрыть front/rear conflict?
9. Может ли UNKNOWN position стать NOT_APPLICABLE без policy?
10. Может ли Metzger получить AFTERMARKET_A/B без reviewer?
11. Может ли ИИ записать fabricated approved_by?
12. Может ли draft brands.yaml повлиять на runtime?
13. Может ли manual-review observation попасть в calibration?
14. Может ли price alias расходиться с sale_price?
15. Сохраняется ли historical observation при окончании скидки?
16. Может ли duplicate/retry создать две разные canonical prices для одного capture?
17. Может ли 20-OE sample быть заменён после обнаружения ошибки?
18. Может ли 60-OE stage стартовать при failed gate20?
19. Сообщает ли отчёт Wilson lower bound, а не только observed 100%?
20. Были ли какие-либо seller price writes?

Repository search:

~~~bash
rg -n "product\.price or|product.get\(\"price\"\)|price_original|discounted_price|has_discount" backend/src scripts
rg -n "package_quantity|measure_unit|unit_basis|normalized_unit_price" backend/src scripts
rg -n "Metzger|AFTERMARKET_A|AFTERMARKET_B|approved_by|domain_policy_approved" backend/config backend/src
rg -n "automatic_eligible|comparability_hard_gate_result|calibration" backend/src/marko/services
~~~

Каждое совпадение классифицируй:

~~~text
CANONICAL_RESOLVER
RAW_FIELD_ONLY
TEST_FIXTURE
LEGACY_COMPATIBILITY
DEFECT_FIXED
REMAINING_BLOCKER
~~~

Review без repair не закрывает prompt.

---

# 19. Формат финального отчёта агента

Финальный отчёт на русском:

1. Итог stage и буквальный результат.
2. Изменённые файлы.
3. Price contract и пример 412→330.
4. Migration/backfill/rollback.
5. Package quantity и unit basis.
6. PositionVector и equivalence.
7. Metzger commercial class/pricing tier decision.
8. Automatic comparability predicate.
9. Calibration exclusions.
10. Replay results.
11. 20-OE metrics и gate.
12. 60-OE metrics или причина, почему stage не стартовал.
13. Wilson confidence bounds.
14. Variation testing.
15. Hostile review и исправленные дефекты.
16. Оставшиеся внешние blockers.
17. Production readiness separation.
18. Section 15.1 footer и Section 16 machine summary по AGENTS.md.

Machine fragment:

~~~yaml
cross_commercial_comparability:
  price_resolver_version: string
  current_candidate:
    listing_id: "3122803874"
    sale_price: "330.00"
    reference_price: "412.00"
    package_quantity: null
    unit_basis: UNKNOWN
    position_equivalence: UNKNOWN
    commercial_class: AFTERMARKET
    pricing_tier: UNKNOWN
    automatic_eligible: false
  reference_price_market_leakage_count: 0
  quantity_numeric_noise_false_positives: 0
  automatic_rows_with_unknown_unit: 0
  automatic_rows_with_unknown_position: 0
  automatic_rows_with_unknown_tier: 0
  fabricated_approval_count: 0
  replay_network_requests: 0
  oe20:
    executed: false
    unique_cross_oes: 0
    false_matches: 0
    false_sale_prices: 0
    gate: NOT_STARTED
  oe60:
    executed: false
    unique_cross_oes: 0
    gate: NOT_STARTED
  seller_price_writes: 0
  production_ready: false
~~~

---

# 20. Execution order

Выполняй строго по зависимости:

~~~text
baseline reproduction
-> canonical price resolver
-> Product/AcceptedCandidate integration
-> PostgreSQL schema expand/backfill
-> MarketObservation dual-write
-> package/unit evidence
-> position evidence/equivalence
-> commercial class vs pricing tier separation
-> automatic/calibration gates
-> retained replay
-> targeted and PostgreSQL tests
-> full suite
-> 20-OE bounded validation
-> repair/rerun if any gate fails
-> conditional 60-OE validation
-> hostile self-review
-> final validated report
~~~

Не начинай 60-OE stage автоматически в том же шаге, где только сформирован gate20
report. Сначала вычисли gate20, зафиксируй immutable artifacts и проверь stop condition.

---

# 21. Финальная инструкция

Начни с воспроизведения 412→330 на retained snapshot listing 3122803874. Докажи, какие
consumers выбирают неправильное поле. Затем реализуй единый resolver и протяни evidence
до persistence, comparability, calibration и exports.

После этого реализуй quantity/unit/position enrichment. Не повышай coverage за счёт
выдуманных defaults. UNKNOWN должен оставаться UNKNOWN.

Metzger сначала классифицируй как evidence-supported commercial class AFTERMARKET.
Pricing tier оставь UNKNOWN, пока нет реального доменного approval или отдельно
реализованного нового tier contract. Не выдумывай reviewer.

Запусти 20-OE evaluation только в bounded разрешённой source scope. При любой false
automatic acceptance остановись, исправь root cause и повтори тот же sample. К 60 OE
переходи только после полного gate20 PASS. Ни один live validation stage не разрешает
автоматически менять цены.

Успех определяется не количеством тестов, а инвариантами:

~~~text
current payable price is truthful
AND reference price cannot leak into market statistics
AND unit/position unknowns abstain
AND tier approval is authentic
AND calibration sees only complete verified comparable offers
AND 20→60 promotion is evidence-driven
~~~

Если hard gate не доказан, верни FAIL или BLOCKED с точным blocker, owner, evidence и
следующим конкретным действием. Не фальсифицируй PASS.

<!-- END PROMPT_15_018_CROSS_COMMERCIAL_COMPARABILITY_AND_PRICE_BOUNDARY -->
