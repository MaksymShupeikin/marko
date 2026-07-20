# PROMPT 15.017 — реализация verified market identity spine

## 1. Scope и границы результата

Этот документ фиксирует фактически реализованный P0-контракт для пути:

```text
CatalogItem
  -> QueryInput | ProductSeedInput
  -> retained raw evidence + ScrapeOutput v2
  -> total OfferProcessor
  -> OE extraction/provenance
  -> verified identity
  -> comparability hard gate
  -> calibration eligibility
  -> recommendation/manual review
```

P0 не меняет source-access verdict, не разрешает live Prom collection и не активирует
автоматическое применение цен. Проверка выполнена на deterministic fixtures и
disposable PostgreSQL. Текущий `prom_public_marketplace` verdict остаётся
`NOT_PERMITTED`.

## 2. Нормативный identity contract

| Символ | Поле | Значение | Может служить доказательством кандидата |
|---|---|---|---:|
| `Q` | `search_oe_norm` | OE, по которому выполнен поиск | нет |
| `E` | `extracted_oe_norms` | OE, извлечённые из candidate evidence | да, после проверки provenance/strength |
| `V` | `verified_matched_oe_norm` | единственный доказанный OE кандидата | да |
| `K` | `comparison_identity_key` | ключ exact/cross identity cluster | да, только после `V` |

Инварианты:

```text
V != null  => V in E
K != null  => V != null
E = empty  => V = null AND K = null
status in {VERIFIED_EXACT, VERIFIED_CROSS} => V != null AND K != null
status in {UNKNOWN, CONFLICT, AMBIGUOUS, LEGACY_UNVERIFIED}
  => automatic_eligible = false
```

Exact:

```text
VERIFIED_EXACT iff V = Q
                  AND evidence_strength(V) >= tau_oe
                  AND provenance(V) is complete
K = V
```

Confirmed one-hop cross:

```text
VERIFIED_CROSS iff V != Q
                  AND CONFIRMED_CROSS(Q, V)
                  AND evidence_strength(V) >= tau_oe
K = "XREF:" + sorted(Q, V)
```

`REVIEW`, `UNKNOWN` и `REJECTED` cross links никогда не загружаются как разрешённые
crosses. Транзитивное замыкание не используется.

## 3. Evidence aggregation

Для каждого нормализованного OE `x` доказательства сначала группируются по
`correlation_group`, затем вычисляется:

```text
C(x) = 1 - product_g(1 - max_confidence(x, g))
```

Одна и та же строка, продублированная в title/description, не образует два независимых
подтверждения. Порог `tau_oe = 0.90`. Одно strong evidence или два независимых medium
groups могут пройти порог; unanchored числа, цена, год и телефон не проходят.

Каждый `OeEvidenceItem` хранит normalized value, source kind, source record,
`raw_capture_id`, hash проверенного raw-manifest, JSON path/span, method, extractor
version, confidence и stable evidence reference. `Q` не передаётся extractor как
candidate field.

## 4. Acquisition без sentinel URL

Введён tagged union:

```text
AcquisitionInput = ProductSeedInput | QueryInput
```

Выбор входа:

```text
product_url present -> ProductSeedInput -> gateway.compare(..., strict=True)
product_url absent  -> QueryInput       -> gateway.search(..., strict=True)
```

Query проходит NFKC normalization, trim/collapse whitespace, uppercase, ограничение
`1..255`, reject control characters, URL и `invalid:` sentinel. Query никогда не
интерпретируется как URL, поэтому не создаёт SSRF path. Server-side admission и
idempotency включают workspace/tenant scope. Одинаковый normalized query внутри run
создаёт один `ScrapeTarget`, разные query — разные targets. URL-seed hash namespace
отделён от query hash namespace.

`invalid://missing-product-url` удалён из runtime. URL-seed compatibility сохранена.

## 5. Scraper output и parser truthfulness

`prom-market-acquisition-v2` хранит:

```yaml
input:
  input_kind: query|product_seed
  query: normalized query
  canonical_url: null|canonical Prom product URL
  input_hash: sha256
output:
  acquisition_outcome: RESULTS|EMPTY_SEARCH_RESULT
  candidates_scanned: integer
  records: CandidateEnvelope[]
```

Для query `retrieval_score=null`; положение в выдаче не превращается в identity score.
V1 payload читается compatibility adapter, но legacy attribution не становится
verified без re-enrichment.

Parser distinction:

```text
EMPTY_SEARCH_RESULT:
  expected Apollo record exists
  AND listing.page schema recognized
  AND products = []
  AND total = 0

PARSER_SCHEMA_CHANGED:
  expected record absent
  OR listing.page absent/invalid
  OR products has wrong type/malformed element
  OR total contradicts products
```

No Apollo state остаётся `PARSE_CONTRACT`/anti-bot boundary. Schema drift сохраняет raw
evidence, выставляет `parse_status=FAILED`, `downstream_eligibility=INELIGIBLE`,
`operator_action=REPLAY_REQUIRED` и не становится нулевым рынком.

## 6. Total offer processing и conservation law

Каждый raw element получает ровно один append-only `OfferProcessingOutcome`:

```text
OBSERVATION_PERSISTED
REJECTED_NOT_MAPPING
REJECTED_INVALID_PRICE
REJECTED_INVALID_MATCH_SCORE
REJECTED_MISSING_LISTING_IDENTITY
REJECTED_SCHEMA_MISMATCH
REJECTED_SERIALIZATION
FAILED_INTERNAL_PROCESSING
```

Для каждого capture/run item проверяется:

```text
R = O + J + F
R,O,J,F >= 0
```

где `R` — retrieved, `O` — observations, `J` — typed rejections, `F` — internal
failures. Unique key `(raw_market_capture_id, pricing_run_item_id, raw_offer_index)`
запрещает двойной terminal outcome. Ledger защищён PostgreSQL append-only trigger.

Capture, observations, tier classifications и outcomes создаются одной транзакцией.
Constraint/ledger failure откатывает все строки. Нарушение conservation law после
rollback сохраняется на target/item как `EVIDENCE_ACCOUNTING_ERROR`. В mixed batch
internal failure сохраняется как `FAILED_INTERNAL_PROCESSING`; target и affected item
становятся downstream-ineligible по явной partial policy.

## 7. Source confidence

Единая versioned функция: `source-confidence-v1`.

```text
C_source = I(raw_verified AND parser_contract_verified)
           * sum_i(w_i * q_i)

w = {
  listing_identity: 0.20,
  seller_identity: 0.20,
  price_currency: 0.20,
  availability: 0.10,
  url: 0.10,
  structured_completeness: 0.20
}
```

Все `q_i` конечны и находятся в `[0,1]`; сумма весов равна `1`. Непроверенный raw или
parser contract даёт `0`. Неполный seller/URL/currency/availability/completeness даёт
`<1`. Domain и API defaults равны `0`, а не `1`. Factors, reason codes и method version
сохраняются в observation.

## 8. Calibration hard gates

Calibration eligibility вычисляется одной total pure function
`evaluate_calibration_eligibility`. Логическое условие:

```text
G_cal = automatic_eligible
        AND hard_gate = PASS
        AND oe_status in {VERIFIED_EXACT, VERIFIED_CROSS}
        AND V != null
        AND K != null
        AND persisted Q/E/V/K are internally consistent
        AND seller_identity_verified
        AND source_provenance_verified
        AND valid price/currency/availability/freshness
        AND match/source/tier confidence thresholds pass
        AND NOT used
        AND NOT owned
        AND tier != UNKNOWN
        AND no tier conflict
```

Soft score не компенсирует failed hard gate. Для каждой исключённой observation
сохраняются stable `CAL_*` codes. Append-only observation допускает только отдельно
авторизованное изменение `calibration_exclusion_codes`; остальные поля остаются
immutable.

Calibration grouping использует `(canonical_category_id, K)`, не `Q` и не deprecated
`matched_oe_norm`. Dataset hash включает observation identity, `K`, `V`, status,
comparability policy hash, source/tier method versions, price, currency, seller и time.

Accounting:

```text
observations_considered = eligible_observations + excluded_observations
```

Sparse verified data сохраняет existing insufficient/unvalidated semantics; gates не
ослабляются ради получения коэффициента.

## 9. PostgreSQL migration 20260719_0016

Migration добавляет Q/E/V/K, verification/provenance/confidence fields,
`calibration_accounting`, `ScrapeTarget.input_kind`, `TierCalibrationPair.identity_evidence`
и `offer_processing_outcomes`.

Legacy backfill:

```text
Q = old matched_oe_norm or LEGACY_UNKNOWN
E = []
V = null
K = null
status = LEGACY_UNVERIFIED
hard_gate = MANUAL_REVIEW
automatic_eligible = false
source_confidence = 0
```

CHECK constraints запрещают unsupported statuses, verified status без V/K и automatic
eligibility без verified identity, PASS, seller identity и provenance. `V in E` и exact/
cross consistency дополнительно проверяются domain predicate до calibration.

Rolling old writer не совместим с обязательным `search_oe_norm`: после additive
migration старый процесс не может вставить unsafe row и получает constraint failure.
Поэтому deployment требует короткого coordinated writer stop; silent mixed-version
corruption не допускается.

Downgrade поддержан, но он lossy: verified fields и outcome ledger удаляются, а
deprecated `matched_oe_norm` восстанавливается только для совместимости. Downgrade не
является доказательством старой identity semantics.

## 10. Network-free re-enrichment

Bounded Celery job `marko.worker.re_enrich_market_observations`:

- читает только retained `RawMarketCapture` и связанный `ScrapeTarget.payload`;
- не создаёт HTTP client и всегда сообщает `network_requests=0`;
- использует canonical extractor/verifier;
- поддерживает `batch_size <= 1000`, `dry_run`, `retry_failed` и `SKIP LOCKED`;
- fail-closed сохраняет typed error code;
- записывает extractor version и counts по verification status;
- не повышает row при недостаточном evidence.

DB trigger разрешает только version-bound re-enrichment field set. Failed re-enrichment
не может стать automatic eligible.

## 11. API, metrics и alerts

Recommendation evidence API отдаёт Q/E/V/K, status, safe evidence summary, hard gate,
automatic eligibility, confidence factors/version, calibration exclusions и outcome
counts. Полный raw HTML не возвращается.

Identity metrics включены в pricing-run scraper metrics и structured events:

```text
pricing_query_only_targets_total
pricing_product_seed_targets_total
prom_empty_search_result_total
prom_parser_schema_changed_total
offer_retrieved_total
offer_observation_persisted_total
offer_rejected_total{reason}
offer_internal_failure_total{reason}
oe_extraction_total{source_kind}
oe_verification_total{status}
oe_verified_exact_total / oe_verified_cross_total
oe_unknown_total / oe_conflict_total / oe_ambiguous_total
calibration_observation_excluded_total{reason}
source_confidence_bucket
evidence_accounting_error_total
```

Metric labels не содержат raw OE, URL, seller name или payload. Versioned alert policy
сигнализирует schema drift, internal/accounting failures, verified-rate drop и
source-confidence p50 drop. Thresholds задаются через Settings/ENV.

## 12. Scaling result

Detail-page enrichment в этом P0 не реализован:

```text
k = 0
r_d = 0
```

Поэтому недостаточное listing evidence остаётся `UNKNOWN`; дополнительных network
requests нет. Replay microbenchmark сравнивает current-code candidate boundary с тем же
boundary плюс identity/confidence spine. Это A/B текущего кода, не подмена исторического
production benchmark. Числа и команды находятся в
`.artifacts/prompt_15_017/replay_performance.json` и `command_evidence.yaml`.

## 13. Rollout

Безопасная последовательность:

1. Остановить старые pricing writers; сохранить backup и проверить restore procedure.
2. Применить migration `20260719_0016`.
3. Развернуть новый API/workers одновременно и проверить import identity.
4. Запустить re-enrichment сначала `dry_run=true`, затем bounded batches.
5. Наблюдать UNKNOWN/CONFLICT/verified rates, confidence p50 и accounting alerts.
6. Оставить pricing в shadow/manual-review mode.
7. Отдельным stage получить representative Yuri/Prom evidence и activation approval.

Rollback приложения выполняется только вместе с downgrade/maintenance window, потому
что старый writer не знает обязательный identity contract. Автоматическое применение
цен не включается.

## 14. Что этот P0 не доказывает

- live Prom source permission;
- extraction coverage на текущей реальной разметке Prom;
- representative precision/recall на каталоге Юрия;
- approved cross links, brand/tier labels или automatic pricing activation;
- production backup/restore, deployment rollback и sustained load capacity;
- detail-page enrichment (`k=0`).

Эти ограничения не ослабляют P0 fail-closed контракт: при их отсутствии система
возвращает UNKNOWN/manual review/insufficient data, а не ложный verified match.

## 15. Section 16 P0 extension

К строгой схеме Section 16 `1.1.0` добавлено опциональное обратно-совместимое
`p0_identity_spine`. Если секция присутствует и stage объявлен `PASS`, validator
требует все identity gates `true`, нулевые sentinel/network/failure counters,
непустой successful full suite и пустой `remaining_blockers`. Негативная
параметрическая матрица доказывает, что противоречивый `PASS` отклоняется.
