# Почему «ничего не работает» на свежем клоне — и как развернуть рабочую среду

Дата: 2026-08-21. Написано после диалога «конкуренты не находятся, цены не
считаются, всё как 2 недели назад».

## Диагноз в одну строку

Код в git приезжает полностью, но **все включатели продукта живут в `.env`,
которого в git нет** (рядом с ключом API). Свежий клон стартует в положении
«всё выключено» — это спроектированный fail-closed, а не поломка.

Конкретно на чистой машине:

1. `PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT` по умолчанию `NOT_PERMITTED` →
   любой прогон падает с `SourceAccessBlocked: Live Prom marketplace
   collection is blocked`. Ноль собранных конкурентов — именно этот эффект.
2. `PRICING_LLM_API_KEY` пуст и `PRICING_LLM_COMPARABILITY_MODE=off` →
   проверка сопоставимости не работает, цены не считаются.
3. База данных пустая: все прогоны и рекомендации живут в Docker-томе той
   машины, где их считали. Чужих результатов на свежем клоне не видно.

Проверка «а это точно оно?»: открой лог прогона или `pricing_run_items.error`
— там будет `SourceAccessBlocked`.

## Разворачивание с нуля (проверенный порядок)

```bash
cp .env.example .env
```

Затем в `.env` поменять/заполнить (остальное можно не трогать):

```bash
# 1. Разрешить сбор с Prom (решение владельца, зафиксировано 2026-07-18)
PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT=PERMITTED_LIMITED
PROM_MARKETPLACE_SOURCE_ACCESS_REFERENCE=local-dev-owner-accepted-2026-07-18

# 2. Проверка сопоставимости (платная! см. «Деньги» ниже)
PRICING_LLM_COMPARABILITY_MODE=required
PRICING_LLM_API_KEY=<получить у Леонида по защищённому каналу — НЕ в чат>

# 3. Решение заказчика 2026-08-21: никакой автоматики
PRICING_COMPARABILITY_V1_AUTOMATIC_ENABLED=false
ATTENTION_MONITORING_ENABLED=false
STORE_MONITORING_ENABLED=false

# 4. Firebase (публичные идентификаторы клиентского приложения, не секреты)
FIREBASE_API_KEY=AIzaSyB3z6DdrNqhHnMw6fwsrni8vhJ1Z66cgtA
FIREBASE_AUTH_DOMAIN=marko-4941e.firebaseapp.com
FIREBASE_PROJECT_ID=marko-4941e
FIREBASE_MESSAGING_SENDER_ID=779526440182
FIREBASE_WEB_APP_ID=1:779526440182:web:050d87e4d64dccb57cd8d7
FIREBASE_STORAGE_BUCKET=marko-4941e.firebasestorage.app
```

Дальше:

```bash
docker compose build
docker compose up -d
docker compose ps          # ждать, пока все 8 сервисов станут (healthy)
```

Проверить, что включатели реально долетели внутрь контейнеров (любое
изменение `.env` требует `docker compose up -d`, простой restart оставляет
старые значения):

```bash
for s in api worker pricing-worker; do docker compose exec -T $s python -c "
from marko.core.config import get_settings as g
from marko.services.source_access import source_access_status
s=g(); print('$s', source_access_status(s).live_collection_allowed,
      s.pricing_llm_comparability_mode, s.attention_monitoring_enabled)"; done
# ожидается: True required False — во всех трёх
```

## Как запускать (не python-тестами)

Рабочий путь — операторский, через UI (`http://localhost:8080`):

1. Войти, загрузить XLSX каталога (страница магазинов/импорта).
2. Панель расчёта → выбрать свежий импорт → выбрать область (для проверки
   хватает «первые N позиций») → предпросмотр покажет число позиций →
   подтвердить запуск.
3. Прогон идёт минуты (сбор с Prom нарочно медленный: пауза ~1 с/запрос,
   circuit breaker). Статус виден на той же панели.
4. Результаты — экран рекомендаций; выгрузка — кнопка экспорта CSV.

Ожидания надо откалибровать: **цены не появляются автоматически — это
требование заказчика.** Система собирает конкурентов, проверяет
сопоставимость и готовит рекомендацию; цена возникает только после решения
оператора на экране рекомендаций. «Прогон завершился, почти всё в
manual_review / insufficient_data» — это штатный результат, а не поломка:
к каждой строке приложен код причины.

## Деньги

С `PRICING_LLM_COMPARABILITY_MODE=required` каждый платный вызов Luna стоит
~$0.02, лимит 10 вызовов на позицию. Прогон на 10–20 позиций обходится в
$0.2–0.5. Не гонять полный каталог (4647 позиций) «посмотреть как работает».
Для бесплатной проверки связки фронт↔бэк можно временно поставить
`PRICING_LLM_COMPARABILITY_MODE=off` — сбор конкурентов и экраны будут жить,
не будет только вердиктов сопоставимости.

## Если нужны уже посчитанные данные

Дампы базы лежат в `backups/` (не в git). Восстановление на пустой том:
попросить свежий дамп и `pg_restore` внутрь контейнера `db`. Без этого на
новой машине история прогонов начинается с нуля.
