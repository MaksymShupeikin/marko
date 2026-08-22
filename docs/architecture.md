# Архитектура Marko

Marko начинается как модульный монолит. API, worker и scheduler используют один
Python-пакет и один Docker-образ, но запускаются отдельными процессами.

```text
Flutter ──login/session──> Firebase Auth
   │
   └──REST + JWT──> FastAPI ─────────> PostgreSQL
                       │                   ▲
                       └──> Redis ──> Worker ──> Prom
                                     │
                                     └──> matching engine
```

## Границы модулей

- `api` отвечает только за HTTP, валидацию и авторизацию.
- `services` координирует импорт магазина, обновление каталога, поиск
  конкурентов, Firebase-профиль и workspace.
- `parsers/prom` знает формат URL, HTTP и Apollo cache Prom.
- `repositories` содержит SQL-запросы, а `infrastructure/db` — ORM-модели и
  создание сессий.
- `worker` выполняет медленные сетевые операции вне HTTP-запросов.

FastAPI не обходит каталог синхронно. `POST /api/v1/stores` создаёт `sync_run`,
ставит задачу в очередь и возвращает `202 Accepted`; Flutter опрашивает job,
показывает прогресс и после завершения загружает товары магазина.

## Клиент

Flutter содержит единый экран каталога для web, mobile и desktop. Верхняя панель
(TopBar) содержит поиск, фильтры, быстрые действия («Ціни конкурентів», «Імпорт»)
и меню профиля; на мобильных устройствах действия дублируются в нижней плашке.

Клиент использует Riverpod с ручными providers и GoRouter. Архитектура
плоская: каталог, фильтры, модалы импорта и аналитики цен живут в `features/products/`,
а авторизация — в `features/auth/`. API-файлы вызывают FastAPI через единый
`core/api_client.dart`, controller хранит состояние, а виджеты не выполняют
HTTP-запросы напрямую. Корневой `MaterialApp` расположен в `lib/main.dart`;
отдельных директорий `lib/app` и `lib/shared` нет.

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
