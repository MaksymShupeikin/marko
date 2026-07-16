# Архитектура Marko

Marko начинается как модульный монолит. API, worker и scheduler используют один
Python-пакет и один Docker-образ, но запускаются отдельными процессами.

```text
Flutter ──login/session──> Firebase Auth
   │
   └──REST + JWT──> FastAPI ─────────> PostgreSQL
                       │                   ▲
                       └──> Redis ──> collection worker ──> Prom
                                     │
                                     ├──> run-level tier calibration
                                     └──> pricing calculation worker
```

## Границы модулей

- `api` отвечает только за HTTP, валидацию и авторизацию.
- `services` координирует импорт магазина, обновление каталога, поиск
  конкурентов, Firebase-профиль и workspace.
- `parsers/prom` знает формат URL, HTTP и Apollo cache Prom.
- `repositories` содержит SQL-запросы, а `infrastructure/db` — ORM-модели и
  создание сессий.
- `worker` выполняет медленные сетевые операции вне HTTP-запросов.
- `pricing` содержит чистое детерминированное ядро: tier coefficients,
  paired-OE calibration, KEMP normalization, MAD/IQR, confidence,
  режимы fresh/stale/dead_stock, priority и invariant enforcement.

## Pricing run

```text
XLSX import
   └─> PricingRun + 1 PricingRunItem на SKU
         └─> queue pricing (existing PromGateway, Redis pacing/circuit)
               └─> append raw capture + observation + tier classification
                     └─> barrier: все SKU собраны
                           ├─> freeze paired-OE dataset + SHA-256
                           ├─> simple median benchmark
                           └─> selected category shrinkage coefficients
                                 └─> queue pricing-calculation
                                       └─> target leave-one-OE-out coefficient
                                             └─> recommendation + priority
                                             + immutable calculation trace
```

Сетевой парсер `parsers/prom` не масштабируется путём модификации его
внутренностей. Масштабирование находится вокруг него: versioned logical items,
отдельные task/HTTP retry budgets, глобальный Redis pacing каждого physical
attempt, raw HTML journal, replay, checkpoints и идемпотентные DB-ограничения.
`store_sync`, `comparison_job`, logical request и physical attempt не
смешиваются в одной единице capacity. Расчёт не начинается до run-level barrier,
поэтому коэффициент
категории не оценивается по одной позиции. Global prior для shrinkage исключает
target category, а applied coefficient исключает target OE, если тот находился
в run calibration dataset.

Recommendations не смешиваются в одну очередь по несопоставимым raw units:

- raise — UAH/month opportunity или явно маркированный proxy;
- clearance — UAH locked inventory;
- review — capital at risk under weak evidence;
- hold — newest-first operational list.

Подробные формулы и policy contract находятся в
[`kemp_pricing_engine.md`](kemp_pricing_engine.md).
Scraper capacity, reconciliation, storage и benchmark contract находятся в
[`scraper_scaling.md`](scraper_scaling.md).

FastAPI не обходит каталог синхронно. `POST /api/v1/stores` создаёт `sync_run`,
ставит задачу в очередь и возвращает `202 Accepted`; Flutter опрашивает job,
показывает прогресс и после завершения загружает товары магазина.

## Клиент

Flutter содержит один набор feature-модулей для web, mobile и desktop. Разметка
выбирается по доступной ширине окна: нижняя навигация на компактных экранах и
`NavigationRail` на широких.

Клиент использует Riverpod с ручными providers и GoRouter. Архитектура намеренно
плоская: у каждого feature одна директория с файлами `*_models.dart`,
`*_api.dart`, `*_controller.dart` и `*_page.dart`. API-файл вызывает FastAPI
через единый `core/api_client.dart`, controller хранит состояние, а виджет не
выполняет HTTP-запросы напрямую. Корневой `MaterialApp` расположен в
`lib/main.dart`; отдельных директорий `lib/app` и `lib/shared` нет.

Firebase реализует регистрацию, подтверждение почты, Google OAuth и обновление
сессий. Android получает Google credential через официальный `google_sign_in`,
web использует Firebase popup. Flutter отправляет Firebase ID token в FastAPI.
FastAPI проверяет RS256-подпись по публичным ключам Google, на первом запросе
создаёт локального пользователя и workspace, затем использует этот workspace
для stores/jobs. Firebase databases для бизнес-данных не используются.

Backend URL передаётся на этапе сборки:

```bash
flutter build web \
  --dart-define=API_BASE_URL=https://api.example.com \
  --dart-define=FIREBASE_API_KEY=AIza_REPLACE_ME \
  --dart-define=FIREBASE_AUTH_DOMAIN=YOUR_PROJECT_ID.firebaseapp.com \
  --dart-define=FIREBASE_PROJECT_ID=YOUR_PROJECT_ID \
  --dart-define=FIREBASE_MESSAGING_SENDER_ID=123456789012 \
  --dart-define=FIREBASE_WEB_APP_ID=1:123456789012:web:replace_me
```
