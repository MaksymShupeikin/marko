# Luna comparability-v2: runbook приёмки и выхода на 4 901 позицию

## Текущий результат

Контур `parser -> deterministic gates -> Luna -> deterministic pricing admission -> recommendation -> UI -> human decision` реализован аддитивно. По умолчанию он выключен (`PRICING_LLM_COMPARABILITY_MODE=off`), автоматической публикации цены нет. `ai_evidence_runtime` остаётся отдельным выключенным shadow-контуром и не участвует в метриках активации Luna.

Это документ эксплуатации, а не разрешение на rollout. Зафиксированный набор из 20 пар прошёл только smoke regression. Он не является promotion denominator: при `0/10` ложных `MATCH` односторонняя 95% верхняя граница false-match rate равна `0.258866`.

Детерминированный semantic gate v2 отдельно перепроверен на тех же 10
подтверждённых cross-парах и 10 hard negatives: `0/10` false hard stops и
`10/10` остановленных hard negatives. Полный отчёт и воспроизводимая команда:
`SEMANTIC_GATE_V2_ACCURACY_REPORT_2026-08-04.md`. Этот результат также имеет
`promotion_eligible=false`; отсутствие hard stop означает `NEEDS_REVIEW`, а не
`MATCH`.

После replay двух клиентских XLS closed-taxonomy coverage вырос с
`61.52% -> 79.49%` на 4 646 строках и с `57.41% -> 78.45%` на 7 743 строках.
Это означает больше детерминированных признаков до Luna, но не является
метрикой correctness: неизвестные типы остаются `UNKNOWN`, а promotion всё ещё
требует независимый locked set 100/300.

## Контракт безопасности

- Luna получает только identity/comparability evidence. Структурированные поля цены и себестоимости рекурсивно удаляются и повторно очищаются на границе Responses API.
- Ответ модели имеет строгий versioned JSON Schema `marko-product-comparability-output-v2`. Финальный `pricing_admission` модель не возвращает: его вычисляет детерминированный код.
- `ADMITTED` возможен только для `identity_verdict=MATCH`, без hard conflict, при доказанных availability, seller/source provenance, OE/cross identity, target-market role и обязательных category/condition/package/unit/side/position/variant полях.
- Явный конфликт даёт `EXCLUDED`; недостаток обязательного доказательства даёт `MANUAL_REVIEW`.
- Изображения только поддерживают доказательство. Они не отменяют конфликт OE, part type, fitment, generation/year, engine/body, side/position, condition, package quantity или unit basis.
- В provider input повышает доверие только `CrossLink` со статусом `CONFIRMED`; передаются bounded counts и хешированные provenance references.
- Detail-only OE/MPN evidence допускается только после сверки URL, product id, seller id, SHA-256 и retained `product_page` journal. `motors.normalizedPartCode` описывает код кандидата; `compatibleOENumbers` не подменяет confirmed cross.
- Если verified detail называет код кандидата и явно содержит search OE в `compatibleOENumbers`, система создаёт только hash-bound cross proposal. До появления confirmed `CrossLink` он имеет `automatic_identity_eligible=false` и может дать только `UNKNOWN`, никогда `MATCH`.
- Неоднозначный `Код_товару` из Prom-экспорта сам по себе не является OE. Если после клиентских OE/MPN/кросс-полей и разрешённого identity reparse позиция остаётся `UNRESOLVED`, она получает `CUSTOMER_IDENTITY_MISSING`: строка сохраняется в manifest, но для неё выполняется ноль market-acquisition запросов и ноль вызовов Luna.
- `MPN_ONLY` может использоваться для bounded retrieval/enrichment и ручной проверки, но не для automatic pricing/calibration. Automatic admission требует `OE_CONFIRMED` либо подтверждённого `OE`-cross; совпадение одного KEMP/aftermarket MPN в native `MPN`/`SKU` поле не поднимает его в OE namespace.
- Детерминированно отклонённые кандидаты не расходуют provider budget. Каждый оставшийся кандидат получает persisted terminal review либо явный `MANUAL_REVIEW` с typed error, включая `PROVIDER_CALL_BUDGET_EXHAUSTED`.
- `shadow` сохраняет recommendation/cohort/`p_min` поведение режима `off`; `required` применяет только детерминированную проекцию admission. Откат: `required -> shadow -> off`, без удаления reviews, feedback или provenance.

## Режимы

| Режим | Provider | Влияние на цену | Разрешённое использование |
|---|---|---|---|
| `off` | Нет | Нет | default и аварийный rollback |
| `shadow` | Да | Нет | locked/shadow наблюдение и parity |
| `required` | Да | В cohort входят только `ADMITTED` | только после всех предыдущих gates; цена всё равно advisory |

`gpt-5.6-luna` и `reasoning_effort=xhigh` фиксируются до завершения full-catalog replay. Результаты другого effort, prompt/schema, image detail, набора/хешей изображений, нормализованного input или CrossLink не разделяют cache identity.

## Stage ledger

| Этап | Текущий статус | Что требуется для перехода |
|---|---|---|
| 0. Freeze | `PASS` | baseline и smoke hashes в `LUNA_COMPARABILITY_V2_FREEZE_2026-08-04.json` |
| 1. Integration | `IMPLEMENTED_AND_VERIFIED` | Ruff/compileall/pytest/PostgreSQL/Alembic, Dart/Flutter/build и Docker rebuild прошли; evidence зафиксирован во freeze JSON |
| 2. Development | `AVAILABLE_NOT_PROMOTION_DENOMINATOR` | prompt/rules freeze; 20 и размечаемые 120/200 используются только для разработки |
| 3. Locked acceptance | `BLOCKED_DATA` | новый непересекающийся locked set: ровно 100 MATCH и 300 hard NOT_MATCH; среди MATCH не менее 50 pricing-eligible и 50 pricing-ineligible |
| 4. Shadow pilot | `BLOCKED_DATA_AND_NOT_EXECUTED` | ровно 200 client-supplied/pinned products, manual labels всех кандидатов, `off`/`shadow` parity |
| 5. Advisory rollout | `BLOCKED_BY_PREVIOUS_GATES` | `required`: 20 -> 200 -> 1 000 -> 4 901, stop gate после каждой ступени |

`BLOCKED_DATA` означает отсутствие требуемых независимых labels/captures, а не отрицательный результат модели. Порог нельзя ослаблять и отсутствующие метрики нельзя превращать в нули.

## Команды доказательств

Все команды выполняются из `backend/`.

### Freeze произвольного pinned набора

```bash
uv run comparability-acceptance freeze \
  --root /absolute/path/to/pinned-capture \
  --git-root .. \
  --expected-baseline-sha a1b755a7d11a495262c35edd804a63074bba771d \
  --model gpt-5.6-luna \
  --reasoning-effort xhigh \
  --output /absolute/path/to/freeze-manifest.json
```

Manifest должен быть создан до прогона, храниться неизменяемо и включать все input, image и label files. Изменение prompt/schema/model/effort требует нового manifest и нового полного locked run.

### Smoke regression

```bash
uv run comparability-acceptance evaluate \
  --truth ../.artifacts/metis_luna_benchmark_20260803/ground_truth.json \
  --predictions ../.artifacts/metis_luna_benchmark_20260803/luna_output.json \
  --profile smoke \
  --output /absolute/path/to/smoke-result.json
```

Допустимый итог — `SMOKE_REGRESSION_PASS` и всегда `promotion_eligible=false`.

### Locked acceptance

```bash
uv run comparability-acceptance evaluate \
  --truth /absolute/path/to/locked-truth.json \
  --predictions /absolute/path/to/locked-predictions.json \
  --profile locked \
  --output /absolute/path/to/locked-result.json
```

`operational_metrics` в predictions обязан содержать реальные denominators для provider terminal results, owned-store candidates, duplicate sellers, terminal candidate accounting и budget exhaustion. Единственный переходный статус — `LOCKED_ACCEPT`.

### Подготовка независимой разметки

Сформировать blinded review pool из сохранённых реальных пар и исключить весь
development benchmark по seed/candidate/pair identity:

```bash
# Один ограниченный search page на seed; без цен, predictions, labels и DB writes.
PYTHONPATH=backend/src backend/.venv/bin/python scripts/prepare_locked_review_live_expansion.py \
  --seed-csv .artifacts/metis_locked_review_accuracy_expansion_v1/seed_queries.csv \
  --output-dir .artifacts/metis_locked_review_accuracy_expansion_v1 \
  --max-queries 9 --max-search-pages 1 \
  --delay 0.5 --delay-jitter 0.15 \
  --timeout 20 --max-attempts 2

cd backend
uv run comparability-acceptance prepare-locked-review-set \
  --source-csv ../.artifacts/metis_locked_review_20260805/db_locked_candidates.csv \
  --source-csv ../.artifacts/metis_locked_review_accuracy_expansion_v1/live_review_source.csv \
  --exclude-development-benchmark ../.artifacts/metis_luna_benchmark_20260803/benchmark_input.json \
  --selection-seed metis-locked-review-db-plus-live-20260805-v21 \
  --csv-output ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/locked_review_tasks.csv \
  --html-output ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/locked_review.html \
  --output ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/locked_review_tasks.json
```

Контракт `comparability-locked-review-set-v2` дополнительно устраняет family
leakage: вариации seed title при том же OE/MPN/SKU, вариации Prom
host/slug/query при том же `p<ID>` и копии candidate family по OE либо
brand+SKU не считаются независимыми статистическими единицами. Fingerprints
повторно вычисляются validator'ом из frozen evidence; старый v1 контракт не
пригоден для promotion.

Рецензент заполняет в CSV только `identity_truth`,
`pricing_admission_truth`, `reason_codes` и `evidence_notes`. В CSV нет цен,
semantic-gate результата или Luna prediction. Для визуальной проверки можно
открыть `locked_review.html`: он показывает парные изображения и сохранённые
характеристики, держит черновик локально и экспортирует совместимый labels CSV.
Единая инструкция разметки и hard-stop правила находятся в
[`METIS_LOCKED_REVIEW_GUIDE.md`](METIS_LOCKED_REVIEW_GUIDE.md).
Затем метки связываются обратно с hash-pinned evidence:

```bash
uv run comparability-acceptance import-locked-review-csv \
  --review-set ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/locked_review_tasks.json \
  --labels-csv ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/locked_review_tasks.csv \
  --reviewer-id REVIEWER_ID \
  --reviewer-role independent_auto_parts_expert \
  --reviewed-at 2026-08-05T00:00:00Z \
  --attest-independent \
  --output ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/locked_review_completed.json

uv run comparability-acceptance validate-locked-review-set \
  --review-set ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/locked_review_completed.json \
  --require-complete

# Слепой overlap из 41 карточки создаётся без меток первого эксперта.
uv run comparability-acceptance prepare-reviewer-overlap \
  --review-set ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/locked_review_completed.json \
  --selection-seed metis-second-reviewer-20260805-v1 \
  --sample-size 41 \
  --csv-output /absolute/path/to/second_reviewer_tasks.csv \
  --html-output /absolute/path/to/second_reviewer.html \
  --output /absolute/path/to/second_reviewer_tasks.json

# Второй эксперт заполняет CSV, после чего его метки импортируются в subset
# через import-locked-review-csv с другим reviewer-id.
# Затем система проверяет согласованность двух независимых разметок.
# Команда требует разные reviewer_id, одинаковые evidence hashes,
# identity agreement >=95% и kappa>=0.85, pricing agreement >=90% и kappa>=0.80.
uv run comparability-acceptance evaluate-reviewer-agreement \
  --primary-review-set ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/locked_review_completed.json \
  --secondary-review-set /absolute/path/to/second_reviewer_completed.json \
  --min-overlap 41 \
  --output ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/reviewer_agreement.json

uv run comparability-acceptance finalize-locked-truth \
  --review-set ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/locked_review_completed.json \
  --selection-seed metis-locked-final-20260805-v1 \
  --output ../.artifacts/metis_locked_review_20260805_db_plus_live_v21/locked_truth.json
```

Финализатор допускает максимум одну пару на seed-product и candidate, требует
ровно `100 MATCH + 300 NOT_MATCH`, включая `50 ADMITTED + 50 EXCLUDED` среди
MATCH. Текущий минимальный blind-review set v21 содержит 405 пар и 405
уникальных seed-product groups; exact independent seed/candidate capacity равна
404. Структурно denominator `100 + 300` достижим; после
независимой разметки все еще может обнаружиться дефицит по классам
`MATCH/NOT_MATCH/ADMITTED/EXCLUDED`.
Емкость считается точным двудольным maximum matching при ограничении
`один seed ↔ один candidate`, поэтому повторы одного SKU не раздувают
статистический denominator.

### Shadow pilot

```bash
uv run comparability-acceptance verify-shadow-parity \
  --off /absolute/path/to/off-hashes.json \
  --shadow /absolute/path/to/shadow-hashes.json \
  --output /absolute/path/to/parity.json

uv run comparability-acceptance evaluate \
  --truth /absolute/path/to/shadow-truth.json \
  --predictions /absolute/path/to/shadow-predictions.json \
  --profile shadow \
  --output /absolute/path/to/shadow-result.json
```

`off-hashes.json` и `shadow-hashes.json` содержат для одной и той же полной популяции `pair_id`, `recommendation_hash`, `cohort_hash`, `p_min_hash`. Любое расхождение останавливает этап.

### Бюджет после pilot

```bash
uv run comparability-acceptance budget \
  --products 1000 \
  --pilot-p95-cost-usd 0.000000 \
  --output /absolute/path/to/stage-budget.json
```

Нулевое значение выше — только placeholder. Перед каждым платным этапом нужно сверить versioned rate card с официальной карточкой модели и подставить измеренный pilot p95 cost per product. Формула: `1.25 * N * pilot_p95`. Превышение бюджета переводит систему обратно в `shadow`.

### Полный учёт строк каталога

Получить manifest:

```text
GET /api/v1/catalog/imports/{batch_id}/terminal-manifest?run_id={run_id}
```

Проверить экспортированный JSON:

```bash
uv run comparability-acceptance verify-catalog-manifest \
  --manifest /absolute/path/to/catalog-terminal-manifest.json \
  --expected-rows 4901 \
  --require-pricing-replay \
  --output /absolute/path/to/catalog-terminal-verification.json
```

Требуется ровно один import outcome на каждую непустую исходную строку и, для каждой `IMPORTED`, terminal `PricingRunItem` конкретного прогона. Неимпортируемые строки остаются отдельно как объяснённый `REJECTED_NOT_IMPORTABLE`; они получают replay-статус `NOT_APPLICABLE_NOT_IMPORTED`. Любой duplicate, missing ordinal, missing run item, non-terminal pricing status, необъяснённый reject, hash mismatch или legacy `NOT_PROVEN` — stop gate. Полный replay нельзя закрыть manifest без `run_id` и флага `--require-pricing-replay`.

Импортированная строка без клиентской идентичности не считается потерянной и не объявляется ошибочно неимпортируемой: её `matching_terminal_status` равен `NOT_MATCHED_CUSTOMER_IDENTITY_MISSING`, а reason code — `CUSTOMER_IDENTITY_MISSING`.

## API и ручная проверка

`GET /api/v1/pricing/runs/{run_id}/comparability-report` возвращает identity/admission counts, coverage, abstention, provider/parser failures, owned-store exclusion, seller deduplication, latency, tokens и estimated cost. Если подтверждённых labels нет, `accuracy.status=NOT_EVALUATED`; отсутствие labels не отображается как нулевая ошибка.

UI показывает deterministic verdict, Luna identity verdict, некалиброванный model score, image/cross evidence, финальный pricing admission и причины. Цена кандидата, normalized price, `p_min` и полоса 2-5% показываются только для `ADMITTED`. Исправления identity и pricing labels независимы и append-only. Существующее ручное accept/reject/override рекомендации остаётся обязательным.

## Типизированная activation

Точного SHA произвольного файла недостаточно. Comparability activation
принимает только `comparability-automatic-activation-v1`, содержащий целиком:

- `LOCKED_ACCEPT` на family-safe truth v2 (`100 MATCH + 300 NOT_MATCH`);
- `SHADOW_ACCEPT` с ровно 200 продуктами и нулевым parity mismatch;
- текущий contract/schema/prompt/provider/model/model-settings hash;
- разные `product_owner_id` и `risk_owner_id`, решение `APPROVE` и timezone-aware
  timestamp;
- канонические SHA-256 обоих embedded evaluation results.

Артефакт строится только после появления всех входов:

```bash
uv run comparability-acceptance build-activation-artifact \
  --locked-result /absolute/path/to/locked-result.json \
  --shadow-result /absolute/path/to/shadow-result.json \
  --runtime-identity /absolute/path/to/runtime-identity.json \
  --product-owner-id PRODUCT_OWNER \
  --risk-owner-id RISK_OWNER \
  --approved-at 2026-08-05T12:00:00Z \
  --output /absolute/path/to/comparability-activation.json
```

Runtime повторно проверяет внешний file SHA, embedded hashes, каждый обязательный
gate и точное совпадение runtime identity. Production preflight выполняет ту же
семантическую проверку артефакта. Старое поведение, при котором
`{"approved": false}` могло считаться валидным только из-за совпавшего SHA,
удалено.

## Stop gates и повторный прогон

Для locked promotion одновременно требуются:

- `0/300` false automatic MATCH и one-sided 95% upper bound `<1%`;
- `0/100` false automatic NOT_MATCH;
- automatic MATCH recall `>=70%`, automatic decision coverage `>=75%`;
- `0` unsafe `ADMITTED` среди минимум 50 pricing-ineligible identity matches;
- admission `>=70%` среди минимум 50 pricing-eligible identity matches;
- owned-store exclusion и seller deduplication `100%`;
- provider valid terminal rate после retry `>=98%`;
- `0` budget-exhausted candidates и полный terminal candidate accounting.

Ошибка любого gate запрещает продвижение. После исправления повторяются весь locked set и новый untouched regression slice; prompt/schema/model/effort остаются фиксированными, а пороги не пересматриваются задним числом.

## Неподтверждённые границы

- Source permission для live Prom не дана: разрешены только pinned/client-supplied captures, live-запросов должно быть ноль.
- TecDoc не считается бесплатным веб-источником по умолчанию. Официальный Web Service/API требует выданный TecAlliance API key, а Catalogue продаётся как подписка. Любое TecDoc-обогащение — отдельный выключенный adapter с подтверждённой лицензией/source permission, pinned response hash и provenance; scraping публичных/партнёрских каталогов вместо лицензии запрещён.
- Locked 100/300 и shadow 200 datasets сейчас не предоставлены, поэтому statistical acceptance и pilot не выполнены.
- Полный прогон 4 901 позиций не выполнялся. Даже успешный pinned replay докажет только catalog replay/advisory readiness, но не актуальность live-рынка.
- Автоматическая публикация цены не входит в этот контур и остаётся запрещённой.
