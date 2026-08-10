# KEMP: внутренний join, OE/OEM-воронка и gate Luna

Дата контракта: 2026-08-09.

Этот runbook проводит три потока строго по порядку и отделяет подготовленный
код от действий, которые может выполнить только заказчик в PostgreSQL и живом
окружении. Он не разрешает сетевой сбор, не меняет `source_access`, не публикует
цены и не меняет публичные id товаров.

## 1. Что реализовано

| Поток | Код | Граница |
|---|---|---|
| KEMP-код на витрине | миграция `20260809_0050`, две generated-колонки, частичный индекс | код `776…` остаётся приватным и не становится поисковым запросом |
| Каталог ↔ свои витрины | `marko.catalog_internal_code_join_cli` | возвращает группу карточек; неоднозначная карточка и любое число карточек, кроме одной, останавливают single-card consumer |
| OE/OEM-воронка | `marko.market_funnel_cli report` | только читает уже сохранённый pricing run; сеть не запускает |
| Human truth | слепая партия 150–300 пар, канарейки, отдельный model-prediction файл, сведение метрик | модель измеряется относительно человека и не объявляется правдой |
| No-OE gate | замороженная стратифицированная выборка 80/1617, human labels, канарейки и шесть метрик | Luna `MATCH` остаётся `SEMANTIC_MATCH_CANDIDATE_MANUAL_REVIEW`; identity/pricing admission всегда 0 |

Не реализовано намеренно: добавление `internal_code` в
`marko_catalog_identity_kind/value`. Эта отдельная развилка сменила бы
`sha256(kind:value)[:32]` и, следовательно, публичные id сохранённых товаров.

## 2. Найти правильный checkout

Между `marko` и `копия` стоит U+00A0. Путь нужно разрешать глобом:

```bash
MARKO_CHECKOUT="$(python3 - <<'PY'
import glob
matches = glob.glob('/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko*копия')
if len(matches) != 1:
    raise SystemExit(f'expected exactly one checkout, got {matches!r}')
print(matches[0])
PY
)"
cd "$MARKO_CHECKOUT"
git status --short
```

Не продолжать, если найдено не ровно одно совпадение.

## 3. Поток 1 — миграция и read-only join

### 3.1. Сначала одноразовая PostgreSQL-проверка

Все PostgreSQL-тесты запускаются только на одноразовых базах. Никогда не
выставлять opt-in-флаги на рабочей базе.

Для основной группы тестов имя базы должно содержать `p15017`:

```bash
cd "$MARKO_CHECKOUT/backend"
export DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@HOST:5432/marko_p15017_kemp_join'
export MARKO_RUN_POSTGRES_INTEGRATION=1

.venv/bin/alembic -c alembic.ini upgrade head
PYTHONPATH=src .venv/bin/python -m pytest -q -m postgres
```

Отдельные группы намеренно требуют другие одноразовые базы и отдельные
предохранители:

- `MARKO_RUN_MIGRATION_GUARD=1` — база с `migration_guard` в имени;
- `MARKO_RUN_FITMENT_POSTGRES=1` — база с `fitment` в имени;
- `MARKO_RUN_TENANT_MATRIX=1` — база с `tenant_matrix` в имени.

Их нельзя механически включать вместе на одной базе: некоторые тесты проверяют
откаты и создают/изменяют фикстуры. После каждого прогона смотреть `-rs` и
зафиксировать точное число выполненных/пропущенных тестов. Локальный зелёный
набор без PostgreSQL не закрывает этот gate.

Минимальная адресная проверка новой функции после `upgrade head`:

```bash
MARKO_RUN_POSTGRES_INTEGRATION=1 \
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_listing_internal_code_postgres.py
```

### 3.2. Накатить рабочую базу

Перед рабочей миграцией:

1. Сделать проверяемую резервную копию базы.
2. Зафиксировать `alembic current` и `alembic heads`.
3. Выбрать окно обслуживания. `ALTER TABLE ... GENERATED ... STORED` вычислит
   значения для существующих `listings`, а создание индекса просканирует
   таблицу и может удерживать блокировки.
4. Не запускать миграцию одновременно с массовой синхронизацией витрин.

```bash
cd "$MARKO_CHECKOUT/backend"
.venv/bin/alembic -c alembic.ini current
.venv/bin/alembic -c alembic.ini heads
.venv/bin/alembic -c alembic.ini upgrade head
.venv/bin/alembic -c alembic.ini current
```

Ожидаемая голова этого checkout: `20260810_0051` (mergepoint, включающий
`20260809_0050` и `20260807_0045`). Если более ранний migration
guard отказал, не обходить его и не редактировать данные автоматически —
сохранить полный вывод и разбирать конкретный отказ.

`20260809_0050` использует отдельный `marko_oem_join_key`: он складывает тот же
набор кириллических омоглифов, что и Python `normalize_oem_identifier`.
Это существенно для наблюдавшейся формы `77643352с` с кириллической `с`,
которая должна соединиться с каталогом как `77643352C`. Миграция также
дозаполняет только оставшиеся пустыми `catalog_items.internal_code_norm` после
SQL-засыпки `0049`; уже установленный приложением ключ она не перезаписывает.

### 3.3. Получить числа join

Создать новый каталог: CLI специально отказывается перезаписывать артефакты.

```bash
cd "$MARKO_CHECKOUT"
MARKO_JOIN_DIR='.artifacts/kemp-internal-join-2026-08-09-run-01'
mkdir -p "$MARKO_JOIN_DIR"

PYTHONPATH=backend/src backend/.venv/bin/python \
  -m marko.catalog_internal_code_join_cli \
  --workspace-id '<WORKSPACE_UUID>' \
  --import-batch-id '<IMPORT_BATCH_UUID>' \
  --json-out "$MARKO_JOIN_DIR/join.json" \
  --csv-out "$MARKO_JOIN_DIR/join.csv" \
  --manifest-out "$MARKO_JOIN_DIR/manifest.json"
```

В отчёте проверить:

- `catalog_positions`, `catalog_positions_with_code` и
  `catalog_positions_without_code`;
- `matched_catalog_positions` и `matched_listing_cards` — это разные числа,
  потому что один товар может жить на четырёх витринах;
- `NO_OWNED_LISTING_MATCH`;
- `AMBIGUOUS_OWNED_LISTING_INTERNAL_CODES` — карточка содержит больше одного
  различного кода KEMP и не должна соединяться;
- `snapshots_without_part_numbers` — старые snapshots без ключа
  `raw_data.part_numbers`.

Если `snapshots_without_part_numbers` велик, лечение — новая штатная
синхронизация четырёх owned-витрин. Не делать SQL-засыпку из названия, SKU или
OE. После синхронизации повторить отчёт в новом каталоге и сравнить manifests.

Join ограничен `workspace_id` и `workspace_stores.kind = 'owned'`. Он не
выбирает «первую» карточку и не меняет существующую identity-цепочку.

## 4. Поток 2 — живой pricing run и пятиступенчатая воронка

Этот раздел выполняет заказчик только после того, как действующая запись
`source_access` уже разрешает ограниченный сбор. Код/этот runbook не дают такого
разрешения. При 403, 429, CAPTCHA/challenge или policy denial сбор должен
остановиться с сохранением уже полученной трассы.

### 4.1. Preview до старта

Токен авторизации не писать в файл и не включать в артефакты:

```bash
export MARKO_API_BASE='https://YOUR-MARKO-HOST/api/v1'
read -s MARKO_AUTH_TOKEN
export MARKO_AUTH_TOKEN
export MARKO_IMPORT_BATCH_ID='<IMPORT_BATCH_UUID>'

jq -n --arg import_batch_id "$MARKO_IMPORT_BATCH_ID" '{
  import_batch_id: $import_batch_id,
  scope_mode: "FULL_CATALOG",
  catalog_item_ids: []
}' > /tmp/marko-kemp-preview-request.json

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer ${MARKO_AUTH_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/marko-kemp-preview-request.json \
  "${MARKO_API_BASE}/pricing/runs/preview" \
  > /tmp/marko-kemp-preview-response.json

jq '{import_batch_id, scope_mode, estimate, exclusions_truncated,
     preview_expires_at, scope_hash, policy_snapshot_hash}' \
  /tmp/marko-kemp-preview-response.json
```

До старта проверить `estimate`, exclusions, `network_eligible_items` и
`identity_blocked_items`. Preview не является доказательством доступности
рынка и не обещает число рекомендаций.

### 4.2. Старт с тем же контрактом

```bash
export MARKO_PREVIEW_TOKEN="$(jq -r '.preview_token' \
  /tmp/marko-kemp-preview-response.json)"

jq -n \
  --arg import_batch_id "$MARKO_IMPORT_BATCH_ID" \
  --arg preview_token "$MARKO_PREVIEW_TOKEN" '{
    import_batch_id: $import_batch_id,
    scope_mode: "FULL_CATALOG",
    catalog_item_ids: [],
    confirm_full_catalog: true,
    idempotency_key: "kemp-oe-funnel-20260809-run-01",
    preview_token: $preview_token
  }' > /tmp/marko-kemp-start-request.json

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer ${MARKO_AUTH_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/marko-kemp-start-request.json \
  "${MARKO_API_BASE}/pricing/runs" \
  > /tmp/marko-kemp-start-response.json

export MARKO_PRICING_RUN_ID="$(jq -r '.id' \
  /tmp/marko-kemp-start-response.json)"
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer ${MARKO_AUTH_TOKEN}" \
  "${MARKO_API_BASE}/pricing/runs/${MARKO_PRICING_RUN_ID}" | jq .
```

Не запускать второй full-catalog run, если первый активен. Не менять policy
между preview и start. Дождаться терминального состояния штатным мониторингом;
не делать агрессивный polling.

### 4.3. Свести воронку после терминального состояния

```bash
cd "$MARKO_CHECKOUT"
MARKO_FUNNEL_DIR='.artifacts/kemp-oe-funnel-2026-08-09-run-01'
mkdir -p "$MARKO_FUNNEL_DIR/review"

PYTHONPATH=backend/src backend/.venv/bin/python \
  -m marko.market_funnel_cli report \
  --workspace-id '<WORKSPACE_UUID>' \
  --run-id "$MARKO_PRICING_RUN_ID" \
  --json-out "$MARKO_FUNNEL_DIR/funnel.json" \
  --rows-csv-out "$MARKO_FUNNEL_DIR/funnel_rows.csv" \
  --review-pool-csv-out "$MARKO_FUNNEL_DIR/review/market_pool.csv" \
  --prediction-json-out "$MARKO_FUNNEL_DIR/model_predictions.json" \
  --manifest-out "$MARKO_FUNNEL_DIR/manifest.json"
```

Основные поля:

1. `positions_with_public_key`;
2. `positions_with_external_candidate`;
3. `positions_with_candidate_surviving_comparison`;
4. `positions_with_price_recommendation`;
5. `drop_stage_histogram` и `drop_reason_histogram`.

Контрольные поля:

- `positions_with_pricing_primary_key`;
- `positions_with_retrieval_only_candidate` — discovery есть, ценового права
  нет;
- `unsafe_price_recommendations` обязан быть 0: recommendation считается
  price-bearing только когда все `evidence_observation_ids` входят в
  persisted `automatic_eligible` comparison survivors **и** каждый survivor
  найден по `pricing_primary`-ключу; retrieval-only hit не проходит этот
  барьер даже при ошибочно выставленном persisted-флаге;
- `owned_echo_observations` — свои витрины видны диагностически, но не входят
  в рынок;
- `ownership_unclassified_observations` — строки без сохранённой tier/ownership
  classification fail closed и не считаются внешним рынком;
- `stage_counts_are_monotonic` обязан быть `true`.
- `price_showing_ready` остаётся `false`: этот отчёт измеряет persisted-воронку,
  но сам не содержит human-truth accuracy.

Популяция отчёта — все `OE_CONFIRMED` строки import batch этого run, включая
не попавшие в исполняемую область. Поэтому `not_in_run_scope` остаётся видимой
причиной, а не исчезает из знаменателя.

### 4.4. Получить human truth на 150–300 парах

Канарейки должны быть заранее известными парами, проверенными независимо от
текущего поискового сигнала. Номер OE, по которому карточка была найдена, сам
по себе не является human truth. Минимальные специальные колонки canary CSV:

```text
canary_id,expected_identity_truth,expected_pricing_admission_truth
```

Остальные колонки совпадают с `market_pool.csv` и содержат доказательства пары.
Допустимые ответы: `MATCH|NOT_MATCH` и `ADMITTED|EXCLUDED`. Хотя бы одна
канарейка обязательна. Экспорт не содержит price-полей; явные суммы с валютой
в title/description и price-characteristics редактируются до записи как
`<PRICE_REDACTED>` и для рыночных пар, и для канареек.

```bash
mkdir -p "$MARKO_FUNNEL_DIR/secure-canary-key"

PYTHONPATH=backend/src backend/.venv/bin/python \
  -m marko.market_funnel_cli prepare-review \
  --market-pool-csv "$MARKO_FUNNEL_DIR/review/market_pool.csv" \
  --canary-source-csv '<SECURE_CANARY_SOURCE.csv>' \
  --batch-size 200 \
  --selection-seed 'kemp-market-human-review-2026-08-09-v1' \
  --blinded-source-out "$MARKO_FUNNEL_DIR/review/blinded_pairs.csv" \
  --canary-key-out "$MARKO_FUNNEL_DIR/secure-canary-key/key.json" \
  --manifest-out "$MARKO_FUNNEL_DIR/review/batch_manifest.json"

PYTHONPATH=backend/src backend/.venv/bin/python \
  -m marko.comparability_acceptance_cli prepare-locked-review-set \
  --source-csv "$MARKO_FUNNEL_DIR/review/blinded_pairs.csv" \
  --selection-seed 'kemp-market-human-review-2026-08-09-v1' \
  --csv-output "$MARKO_FUNNEL_DIR/review/labels.csv" \
  --html-output "$MARKO_FUNNEL_DIR/review/review.html" \
  --output "$MARKO_FUNNEL_DIR/review/review_set.json"
```

Заказчик размечает `labels.csv`, не открывая `model_predictions.json` и
`secure-canary-key/key.json`. Затем:

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  -m marko.comparability_acceptance_cli import-locked-review-csv \
  --review-set "$MARKO_FUNNEL_DIR/review/review_set.json" \
  --labels-csv "$MARKO_FUNNEL_DIR/review/labels.csv" \
  --reviewer-id '<REVIEWER_ID>' \
  --reviewer-role 'catalog-owner' \
  --reviewed-at '<ISO-8601-TIMESTAMP>' \
  --attest-independent \
  --output "$MARKO_FUNNEL_DIR/review/reviewed_set.json"

PYTHONPATH=backend/src backend/.venv/bin/python \
  -m marko.comparability_acceptance_cli validate-locked-review-set \
  --review-set "$MARKO_FUNNEL_DIR/review/reviewed_set.json" \
  --require-complete \
  --output "$MARKO_FUNNEL_DIR/review/review_validation.json"

PYTHONPATH=backend/src backend/.venv/bin/python \
  -m marko.market_funnel_cli score-review \
  --reviewed-set "$MARKO_FUNNEL_DIR/review/reviewed_set.json" \
  --predictions "$MARKO_FUNNEL_DIR/model_predictions.json" \
  --canary-key "$MARKO_FUNNEL_DIR/secure-canary-key/key.json" \
  --report-manifest "$MARKO_FUNNEL_DIR/manifest.json" \
  --review-batch-manifest "$MARKO_FUNNEL_DIR/review/batch_manifest.json" \
  --output "$MARKO_FUNNEL_DIR/review/model_vs_human.json"
```

`score-review` возвращает ненулевой код, если канарейки провалены, не все
model reviews терминальны, итоговая партия вышла за 150–300 строк, в настоящих
(не canary) строках нет обоих классов `MATCH` и `NOT_MATCH`, найден хотя бы один
model false accept или хотя бы один небезопасный pricing admission. Канарейки проверяются отдельно и не
улучшают/ухудшают метрики модели. `price_showing_ready` остаётся `false` до
явного решения оператора после чтения отчёта. Перед подсчётом CLI обязательно
сверяет байтовые SHA-256 `model_predictions.json` и canary key с двумя
манифестами; отредактированные после заморозки predictions не принимаются.

## 5. Поток 3 — замороженный gate Luna для no-OE

### 5.1. Уже замороженный вход

Файл:
`experiments/semantic_discovery_without_oe/fixtures/stratified_sample_2026-08-09.json`.

- population: 1617 no-OE строк;
- sample: 80 строк, 46 категорий, 43 part-family;
- 4 партии по 20;
- обязательные `1230665005` и `2179741467` присутствуют;
- SHA-256 файла:
  `351446c1d99c1beeda28084596a9c38c02f597744c36292d539c0f9965e84e23`.

Воспроизводящее замораживание (в новый файл, потому что overwrite запрещён):

```bash
cd "$MARKO_CHECKOUT"
PYTHONPATH=backend/src backend/.venv/bin/python \
  experiments/semantic_discovery_without_oe/evaluation_cli.py freeze \
  --sample-size 80 \
  --selection-seed 'semantic-discovery-gate-2026-08-09-v1' \
  --output /tmp/stratified_sample_replay.json
shasum -a 256 /tmp/stratified_sample_replay.json
```

Полный byte hash меняется из-за `created_at`; стабильный
`sample_manifest_sha256` внутри файла связывает входы, алгоритм, строки и
партии. Сравнивать нужно и manifest hash, и список `row_id`.

### 5.2. Живой сбор — только после отдельного разрешения

Каждая партия берётся из `live_batches` frozen sample и содержит не более 20
семян. Для каждой нужен новый `--output-dir`. Пример для первой партии:

```bash
MARKO_SAMPLE='experiments/semantic_discovery_without_oe/fixtures/stratified_sample_2026-08-09.json'
MARKO_SEMANTIC_DIR='.artifacts/semantic-discovery-gate-2026-08-09'
mkdir -p "$MARKO_SEMANTIC_DIR"

MARKO_ROW_ARGS=()
while IFS= read -r MARKO_ROW_ID; do
  MARKO_ROW_ARGS+=(--row-id "$MARKO_ROW_ID")
done < <(jq -r '.live_batches[0].row_ids[]' "$MARKO_SAMPLE")

PYTHONPATH=backend/src backend/.venv/bin/python \
  experiments/semantic_discovery_without_oe/run_pilot.py \
  "${MARKO_ROW_ARGS[@]}" \
  --output-dir "$MARKO_SEMANTIC_DIR/batch-01" \
  --live \
  --run-luna \
  --queries-per-seed 1 \
  --max-search-pages 1 \
  --max-detail-cards 3 \
  --max-luna-pairs 5
```

Повторить только для индексов `[1]`, `[2]`, `[3]`, с каталогами `batch-02..04`.
Не запускать оставшиеся партии после 403/429/CAPTCHA, source-access denial или
нарушения hash/manifest. Не увеличивать лимиты, чтобы «добрать покрытие».

### 5.3. Слепая разметка, канарейки и шесть метрик

Secure semantic-canary CSV содержит доказательства известной пары и поля:

```text
canary_id,row_id,seed_title,seed_category,candidate_title,candidate_url,
candidate_seller,candidate_description,candidate_image,expected_identity_truth
```

`expected_identity_truth` — `MATCH` или `NOT_MATCH`. Ключ выводится вне папки
человеческой разметки; хотя бы одна канарейка обязательна.

```bash
mkdir -p "$MARKO_SEMANTIC_DIR/review" "$MARKO_SEMANTIC_DIR/secure-canary-key"

PYTHONPATH=backend/src backend/.venv/bin/python \
  experiments/semantic_discovery_without_oe/evaluation_cli.py prepare-labels \
  --sample "$MARKO_SAMPLE" \
  --run-dir "$MARKO_SEMANTIC_DIR/batch-01" \
  --run-dir "$MARKO_SEMANTIC_DIR/batch-02" \
  --run-dir "$MARKO_SEMANTIC_DIR/batch-03" \
  --run-dir "$MARKO_SEMANTIC_DIR/batch-04" \
  --canary-source-csv '<SECURE_SEMANTIC_CANARIES.csv>' \
  --seed-labels-out "$MARKO_SEMANTIC_DIR/review/seed_labels.csv" \
  --candidate-labels-out "$MARKO_SEMANTIC_DIR/review/candidate_labels.csv" \
  --system-predictions-out "$MARKO_SEMANTIC_DIR/system_predictions.json" \
  --canary-key-out "$MARKO_SEMANTIC_DIR/secure-canary-key/key.json" \
  --manifest-out "$MARKO_SEMANTIC_DIR/review/label_manifest.json"
```

Человек заполняет только:

- `seed_labels.csv`: `correct_candidate_retrieved=YES|NO` и
  `review_complete=true`;
- `candidate_labels.csv`: `human_identity_truth=MATCH|NOT_MATCH`.

Он не должен видеть `system_predictions.json` или canary key до окончания.
Все остальные поля, включая `evidence_sha256`, неизменяемы: evaluator
пересчитывает hash каждой seed/candidate строки и останавливает измерение при
любом расхождении. `prepare-labels` также принимает только точное
непересекающееся покрытие всех 80 seed успешными live+Luna runs со статусом
`COMPLETED`; profile-only, частичная или `COMPLETED_WITH_ERRORS` партия
отклоняется до разметки.
После разметки:

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  experiments/semantic_discovery_without_oe/evaluation_cli.py evaluate \
  --sample "$MARKO_SAMPLE" \
  --seed-labels "$MARKO_SEMANTIC_DIR/review/seed_labels.csv" \
  --candidate-labels "$MARKO_SEMANTIC_DIR/review/candidate_labels.csv" \
  --system-predictions "$MARKO_SEMANTIC_DIR/system_predictions.json" \
  --canary-key "$MARKO_SEMANTIC_DIR/secure-canary-key/key.json" \
  --label-manifest "$MARKO_SEMANTIC_DIR/review/label_manifest.json" \
  --output "$MARKO_SEMANTIC_DIR/evaluation.json"
```

Отчёт считает:

1. retrieval seed recall;
2. precision и false rejects детерминированных отказов;
3. false accepts, false not-match и abstention Luna;
4. availability подробной карточки и замороженной usable-картинки именно
   внешнего кандидата (исходная картинка KEMP в эту метрику не засчитывается);
5. покрытие независимыми продавцами;
6. HTTP/Luna/runtime budget на семя.

Провал канареек делает измерение незавершённым. Любой critical false accept
даёт решение `LEAVE_AS_MANUAL_TOOL`. Даже при полном измерении автоматические
identity/pricing admissions остаются 0; итог требует выбора оператора из
`SCALE_MANUAL_REVIEW_PILOT`, `SCALE_WITH_HARDENING`,
`LEAVE_AS_MANUAL_TOOL`. До метрик evaluator сверяет sample, скрытые system
predictions и canary key с `label_manifest.json`; human label CSV проверяются
отдельными row-level evidence hashes, потому что их разрешённые label-поля
после выдачи партии закономерно меняются.

## 6. Условия остановки и честные неизвестные

| Gate | Закрывается только когда |
|---|---|
| Поток 1 | migration прошла на базе заказчика; join выдал реальные counts и reasons; старые snapshots отделены от отсутствующего кода |
| Поток 2 | живой run терминален; пятиступенчатая воронка посчитана; 150–300 пар размечены; канарейки прошли; model-vs-human метрики известны |
| Поток 3 | 80 frozen seeds обработаны без нарушения границ; human labels и канарейки полны; шесть метрик посчитаны; оператор принял решение |

До закрытия этих gates нельзя утверждать:

- сколько позиций соединится с owned-карточками;
- сколько OE-позиций получит рыночного кандидата или цену;
- что 143 ранее пропущенных PostgreSQL-теста зелёные;
- что Luna восстанавливает OE;
- что какая-либо рекомендация готова к показу или публикации.

Позиции `OE_CONFIRMED`, которые отвалились на `MARKET_CANDIDATE`, образуют
вторую популяцию no-result. Их нельзя молча смешивать с исходными 1617 no-OE:
после воронки для них замораживается отдельный manifest и отдельно считается
знаменатель.
