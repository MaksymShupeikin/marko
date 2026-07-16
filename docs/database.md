# Схема данных

- `users` — локальные профили, связанные с Firebase Auth через `firebase_uid`.
- `workspaces` и `workspace_members` — клиентские аккаунты и доступ сотрудников.
- `marketplace_stores` — глобальные продавцы маркетплейса.
- `workspace_stores` — принадлежащие или отслеживаемые аккаунтом магазины.
- `listings` — конкретные товарные предложения продавцов.
- `price_observations` — append-only история цены и наличия.
- `store_sync_product_snapshots` — дедуплицированный структурированный output
  конкретного store-sync run; ключ `(sync_run_id, external_id)`, payload hash и
  completeness не зависят от последующих изменений mutable `listings`.
- `product_matches` — связь товара клиента с конкурентным предложением.
- `sync_runs` — состояние импортов и фоновых обновлений.
- `catalog_import_batches`, `catalog_items` — неизменяемые снимки XLSX и
  нормализованные строки с сохранённым `raw_row`.
- `catalog_item_overrides` — append-only ручной контекст: статус запаса,
  себестоимость, остаток, продажи, приоритет и явный below-cost floor.
- `pricing_runs`, `pricing_run_items` — версия политики, checkpoint и
  идемпотентное состояние каждого SKU.
- `raw_market_captures`, `market_observations` — сырой структурированный вывод
  неизменённого парсера и отдельные рыночные наблюдения.
- `observation_tier_classifications`, `brand_tier_rules` — версионированный
  tiering и ручные исправления без перезаписи старой классификации.
- `tier_calibration_pairs` — замороженные independent paired-OE units с
  seller-deduplicated reference/tier evidence, quality weight и dataset hash.
- `tier_coefficients` — run-scoped category/tier коэффициенты simple median или
  shrinkage, uncertainty interval, validation reasons, selected-model flag,
  policy/dataset/coefficient versions.
- `pricing_recommendations`, `recommendation_decisions` — неизменяемый расчёт,
  снимок catalog/context, normalization trace, evidence IDs, raw/unique/clean
  counts, outlier/sensitivity/action gates, confidence, typed priority, cost
  floor и журнал решения оператора.

## Основные ограничения

- Магазин уникален по `(marketplace, external_id)`.
- Listing уникален по `(store_id, external_id)`.
- Один и тот же конкурент не может быть дважды связан с исходным товаром в
  пределах workspace.
- Цена хранится как `NUMERIC(14, 2)`; в Python следует использовать `Decimal`.
- Автоматические совпадения сохраняют confidence и версию алгоритма.
- Рекомендация уникальна внутри `pricing_run_item`; retry не создаёт второй
  расчёт.
- Calibration pair уникален по `(pricing_run_id, category, tier, oe_norm)`;
  raw listing count не может искусственно увеличить sample size.
- `RAISE` требует цену выше current, `LOWER` — ниже current, а оба действия —
  `action_gates_passed = true`.
- Confidence/source confidence лежат в `[0,1]`; sample sizes и market counts не
  могут быть отрицательными; validated coefficient имеет положительный
  multiplier и effective sample size.
- Below-cost catalog authorization требует `dead_stock`, floor и explicit
  warning confirmation. Decision повторно сохраняет cost, approved floor,
  policy/context и confirmation timestamp.
- Триггеры PostgreSQL запрещают `UPDATE`/`DELETE` для market evidence,
  calibration pairs/coefficients, tier-классификаций, рекомендаций, решений и
  ручных override-записей.

При первом запросе с валидным Firebase ID token API создаёт локального
пользователя и его первый workspace. `firebase_uid` содержит неизменяемый `sub`
из проверенного JWT; бизнес-таблицы продолжают ссылаться на локальный `users.id`.

Миграции находятся в `backend/migrations/versions/`; переход на Firebase Auth
добавлен в `20260713_0004_firebase_auth.py`. Существующие бизнес-данные не
удаляются: пользователь заново связывается с Firebase UID по подтверждённой
почте при первом входе.

Pricing-контур добавлен миграцией
`20260716_0005_pricing_intelligence.py`. Её SQL проверяется offline-командой
`alembic upgrade head --sql`; в рабочем окружении миграцию применяет compose
service `migrate`.

Миграция `20260716_0006_kemp_pricing_engine.py` дополняет контур frozen
calibration snapshots, coefficient selection/versioning, sales fallbacks,
robust-estimator diagnostics, action gates и below-cost audit constraints.
Проверка обеих сторон:

```bash
cd backend
.venv/bin/alembic upgrade head --sql
.venv/bin/alembic downgrade 20260716_0006:base --sql
```
